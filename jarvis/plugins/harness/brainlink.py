"""Jarvis's deep brain: a long-lived DeepSeek Harness session, driven over the Agent Client Protocol (ACP).

The voice layer stays quick and simple. Big jobs (building a new ability, fixing an old one, anything that needs
planning, files and tests) go to the brain window, where this module keeps one Harness process running:

  dsh --profile jarvis   (an ACP profile: deepseek-flash, which can see images, plus Jarvis's skill folders)

Its workspace is ~/.jarvis/lab. The brain may write only there: new abilities go into lab/skills-trial and only the
user's approval (skills.promote) moves them into ~/.jarvis/skills, where the voice layer loads them. Every step it
takes is streamed to the HUD; anything that needs permission is asked in the brain window.

A self-check runs once per version and writes ~/.jarvis/brain-check.json, so it can be read back from outside."""
import json, os, queue, subprocess, threading, time, urllib.request
from pathlib import Path

from ... import config
from ...paths import DATA as JARVIS, HOME
LAB = JARVIS / "lab"
TRIAL = LAB / "skills-trial"
LIVE = JARVIS / "skills"
DSH_HOME = HOME / ".dsh"
PROFILE = "jarvis"
from . import dsh as _dsh
CHECK = JARVIS / "brain-check.json"
SESSION_FILE = LAB / "session.json"
EFFORT_FILE = JARVIS / "brain-effort.json"
EFFORT_LEVELS = ("low", "high", "max")     # the three tiers DeepSeek-V4.1-Flash advertises: 低 / 中 / 高
DEFAULT_EFFORT = "high"                     # 中档, the provider's own default
UI = None          # set by the service: UI(message) broadcasts to the HUD

# DeepSeek list prices, CNY per million tokens, [off-peak, peak] — same table as the Harness cost meter (2026-09).
# Peak is Beijing time, Mon-Fri 09:00-12:00 and 14:00-18:00; off-peak is half price.
PRICES = {
    "deepseek-flash": {"cacheHit": (0.02, 0.04), "cacheMiss": (1.0, 2.0), "output": (4.0, 8.0)},
    "deepseek-v4-flash": {"cacheHit": (0.02, 0.04), "cacheMiss": (1.0, 2.0), "output": (4.0, 8.0)},
    "deepseek-v4-flash-vision-exp": {"cacheHit": (0.02, 0.04), "cacheMiss": (1.0, 2.0), "output": (4.0, 8.0)},
    "deepseek-v4-pro": {"cacheHit": (0.15, 0.3), "cacheMiss": (4.5, 9.0), "output": (13.5, 27.0)},
}
DEFAULT_MODEL = "deepseek-flash"
BALANCE_URL = "https://api.deepseek.com/user/balance"
BALANCE_TTL = 60.0
USAGE_TTL = 4.0            # at most one log read every few seconds per tab

# Read the Harness session log (concatenated zstd frames of JSONL) and sum each model call's token buckets.
# Node ships with the Harness and is the only zstd decoder guaranteed to be present.
USAGE_JS = r"""
const fs = require('fs'), z = require('zlib');
const b = fs.readFileSync(process.argv[1]);
const offs = [];
for (let i = 0; i + 3 < b.length; i++) if (b[i] === 0x28 && b[i+1] === 0xb5 && b[i+2] === 0x2f && b[i+3] === 0xfd) offs.push(i);
let text = '';
for (let k = 0; k < offs.length; k++) {
  try { text += z.zstdDecompressSync(b.subarray(offs[k], k + 1 < offs.length ? offs[k+1] : b.length)).toString('utf8'); } catch (_) {}
}
const isPeak = ms => {
  const d = new Date(ms + 8 * 3600e3), w = d.getUTCDay();
  if (w === 0 || w === 6) return false;
  const m = d.getUTCHours() * 60 + d.getUTCMinutes();
  return (m >= 540 && m < 720) || (m >= 840 && m < 1080);
};
const buckets = {};
for (const line of text.split('\n')) {
  if (!line) continue;
  let d; try { d = JSON.parse(line); } catch (_) { continue; }
  if (d.type !== 'assistant/message' || !d.data || !d.data.usage) continue;
  const u = d.data.usage, model = (d.data.message && d.data.message.source && d.data.message.source.model) || 'deepseek-flash';
  const peak = isPeak(d.time), key = model + '|' + peak;
  const x = buckets[key] || (buckets[key] = { model, peak, calls: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, totalTokens: 0 });
  for (const f of ['inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens','totalTokens']) x[f] += u[f] || 0;
  x.calls++;
}
console.log(JSON.stringify({ buckets: Object.values(buckets) }));
"""

_BALANCE = {"at": 0.0, "data": None}
_BALANCE_LOCK = threading.Lock()


def _node():
    """The Node binary shipped beside the Harness (zstd support), or one on PATH."""
    env = os.environ.get("JARVIS_NODE")
    if env and Path(env).exists():
        return env
    roots = sorted([*(DSH_HOME / "dsh-runtimes").glob("*/dependencies/node/bin/node"),
                    *(DSH_HOME / "dsh-runtimes").glob("*/dependencies/node/node.exe")])
    for p in reversed(roots):
        if p.exists():
            return str(p)
    import shutil
    return shutil.which("node") or ""


def _session_log(sid):
    if not sid:
        return None
    hits = list((DSH_HOME / "sessions").glob(f"*/{sid}/session.v4.jsonl.zstd"))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def _read_usage(path):
    """Summed token buckets for one session log, or raise with a short reason."""
    node = _node()
    if not node:
        raise RuntimeError("no Node runtime found for zstd")
    r = subprocess.run([node, "-e", USAGE_JS, str(path)], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "node failed").strip()[:200])
    return json.loads(r.stdout or "{}").get("buckets") or []


def _cost_of(buckets):
    """CNY cost of the token buckets, pricing each call in its own peak/off-peak window."""
    total = 0.0
    for b in buckets:
        row = PRICES.get(b.get("model"), PRICES[DEFAULT_MODEL])
        tier = 1 if b.get("peak") else 0
        total += (b.get("inputTokens", 0) * row["cacheMiss"][tier] +
                  b.get("cacheWriteTokens", 0) * row["cacheMiss"][tier] +
                  b.get("cacheReadTokens", 0) * row["cacheHit"][tier] +
                  b.get("outputTokens", 0) * row["output"][tier]) / 1e6
    return round(total, 6)


def account_balance():
    """The account's remaining balance, cached for a minute. Never raises: returns {error} instead."""
    now = time.time()
    with _BALANCE_LOCK:
        if _BALANCE["data"] is not None and now - _BALANCE["at"] < BALANCE_TTL:
            return _BALANCE["data"]
    key = ""
    try:
        key = _settings_key()
    except Exception:
        pass
    if not key:
        try:
            key = config.section("llm").get("api_key", "")
        except Exception:
            pass
    if not key:
        return {"error": "no API key"}
    try:
        req = urllib.request.Request(BALANCE_URL, headers={"Authorization": "Bearer " + key,
                                                           "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.loads(r.read().decode("utf-8"))
        rows = body.get("balance_infos") or []
        info = rows[0] if rows else {}
        data = {"currency": info.get("currency") or "CNY",
                "total": float(info.get("total_balance") or 0),
                "granted": float(info.get("granted_balance") or 0),
                "toppedUp": float(info.get("topped_up_balance") or 0),
                "available": body.get("is_available") is True}
        with _BALANCE_LOCK:
            _BALANCE["at"], _BALANCE["data"] = now, data
        return data
    except Exception as e:
        msg = {"error": f"{type(e).__name__}: {e}"[:200]}
        with _BALANCE_LOCK:
            _BALANCE["at"] = now          # don't hammer a failing endpoint
        return msg
VERSION = "2"

PROFILE_PACKAGE = {
    "name": "dsh-profile-jarvis", "private": True, "dependencies": {},
    "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-acp-app"], "patchReload": "startup"}},
}
PROFILE_PATCH = """# Jarvis's brain: written by Jarvis (jarvis/plugins/harness/brainlink.py). Edit with care; Jarvis rewrites it when it changes.
- id: acp
  name: '@deepseek-ai/dsh-acp'
  inject:
    - acpAppStartup
  config:
    provider: deepseek-official
    model: deepseek-flash
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: deepseek-official
    model: deepseek-flash
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
  config:
    customSkillDirs:
      - !!js process.env.HOME + '/.jarvis/skills'
      - !!js process.env.HOME + '/.jarvis/lab/skills-trial'
- id: system-prompt
  name: '@deepseek-ai/dsh-system-prompt'
  config:
    personaPrefix: You are the deep brain of J.A.R.V.I.S., the user's personal assistant on their computer, powered by the {{model}} model.
    personaSuffix: Your working directory is Jarvis's lab, ~/.jarvis/lab. Read AGENTS.md there before any build.
"""

LAB_AGENTS = """# Jarvis's lab — rules for the brain

You are the part of Jarvis that thinks, plans and builds. The voice layer (quick replies, the HUD, the speaker) is
separate and simple; it can only use abilities that are installed in `~/.jarvis/skills`.

## Talking to the user
The user reads your replies in the brain window. Reply in the language they write in, plainly and briefly. Say what
you are about to do before long work, and what came out of it at the end.

## How to give Jarvis a new ability
An ability is a folder (a skill) with this layout:

    <name>/
      SKILL.md     frontmatter: name, description (when to use it); body: how it works, in plain words
      tool.py      optional: Python the voice layer runs. Must define TOOLS (OpenAI-style function list) and
                   run(name, args) -> dict. Standard library only, no network unless the task needs it,
                   fast (under 3 s), never deletes files.
      test.json    required when tool.py exists: [{"tool": "...", "args": {...}, "expect": {"ok": true}}, ...]

1. Build it only in `skills-trial/<name>/` inside this lab. Never write to `~/.jarvis/skills`, never edit Jarvis's
   own program or `~/.dsh`.
2. Prefer a SKILL.md that combines tools Jarvis already has over new code. Write code only when needed.
3. Run its tests with the `jarvis_skill_test` tool until they pass.
4. Then tell the user what it does and that it is waiting in the trial area for their approval. Only they install it.

## What you can use
- `jarvis_memory_search`: what was said and done before.
- `jarvis_learning_list`: things Jarvis said it could not do yet, and what the user approved for learning.
- `jarvis_skills`: abilities installed and in trial.
- `jarvis_skill_test`: run a trial skill's tests.
Keep each job small. If something fails twice the same way, stop and tell the user why.
"""


def _settings_key():
    base, key, _ = config.llm()
    return key if key and "deepseek" in (base or "") else ""


def ensure_profile():
    """Write the 'jarvis' Harness profile and the lab. Returns the files it wrote."""
    wrote = []
    prof = DSH_HOME / "profiles" / PROFILE
    prof.mkdir(parents=True, exist_ok=True)
    files = {prof / "package.json": json.dumps(PROFILE_PACKAGE, indent=2) + "\n",
             prof / "cordis.yml": "# dsh profile root. Edit cordis.patch.yml, not this file.\n[]\n",
             prof / "cordis.patch.yml": PROFILE_PATCH,
             prof / "pnpm-workspace.yaml": "packages:\n  - .\n\nnodeLinker: hoisted\nautoInstallPeers: false\n",
             LAB / "AGENTS.md": LAB_AGENTS}
    for path, text in files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            wrote.append(str(path))
    for d in (TRIAL, LIVE):
        d.mkdir(parents=True, exist_ok=True)
    return wrote


def load_effort():
    """Per-conversation tier, remembered across restarts: {tab: low|high|max}."""
    try:
        data = json.loads(EFFORT_FILE.read_text(encoding="utf-8"))
        tabs = data.get("tabs") if isinstance(data, dict) else None
        return {str(k): v for k, v in (tabs or {}).items() if v in EFFORT_LEVELS}
    except Exception:
        return {}


def mcp_servers():
    """Jarvis's own tools, offered to every brain session as a stdio MCP server."""
    import sys
    here = Path(__file__).resolve().parents[2]          # the jarvis package
    return [{"name": "jarvis", "command": sys.executable, "args": [str(here / "mcp_server.py")], "env": []}]


class Brain:
    def __init__(self):
        self.proc, self.lock, self.next = None, threading.Lock(), 0
        self.pending, self.perms = {}, {}
        self.session, self.caps, self.busy, self.error = None, {}, False, ""
        self.text = []                  # the assistant's words in the current turn
        self.sessions = {}              # tab -> sessionId
        self.session_to_tab = {}        # sessionId -> tab
        self.texts = {}                 # tab -> assistant chunks in the current turn
        self.asked = {}                 # tab -> what it was last asked (shown on the HUD's Agent panel)
        self.busy_tabs = set()
        self.effort = load_effort()     # tab -> low|high|max (DeepSeek-V4.1-Flash reasoning tier)
        self.usage_at = {}              # tab -> last time its session log was read
        self.usage_lock = threading.Lock()
        self.perm_tab = {}              # permission id -> tab
        self.on_update = None           # extra listener: f(update) for the self-check

    # -- process and wire -------------------------------------------------------------------------------------------
    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        DSH = _dsh()
        if DSH is None:
            self.error = "DeepSeek Harness is not installed"
            return False
        ensure_profile()
        env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
        key = _settings_key()
        if key:
            env["DEEPSEEK_API_KEY"] = key
        LAB.mkdir(parents=True, exist_ok=True)
        log = open(JARVIS / "brain.log", "a", encoding="utf-8")
        log.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')}\n"); log.flush()
        self.proc = subprocess.Popen([str(DSH), "--profile", PROFILE], cwd=LAB, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        r = self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, timeout=90)
        self.caps = r.get("agentCapabilities", {}) if isinstance(r, dict) else {}
        return bool(self.caps)

    def _send(self, obj):
        with self.lock:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def call(self, method, params, timeout=60):
        self.next += 1
        i, q = self.next, queue.Queue()
        self.pending[i] = q
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        try:
            m = q.get(timeout=timeout)
        except queue.Empty:
            self.pending.pop(i, None)
            raise TimeoutError(f"{method} timed out")
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error'].get('message')} {json.dumps(m['error'].get('data', ''), ensure_ascii=False)[:300]}")
        return m.get("result", {})

    def _read(self):
        for line in self.proc.stdout:
            try:
                m = json.loads(line)
            except Exception:
                continue
            if "method" not in m and m.get("id") in self.pending:
                self.pending.pop(m["id"]).put(m)
            elif m.get("method") == "session/update":
                self._update(m.get("params", {}))
            elif m.get("method") == "session/request_permission":
                self._permission(m)
            elif "id" in m and "method" in m:          # anything else asked of a client: say we don't do it
                self._send({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "not supported"}})
        self.busy = False
        self.busy_tabs.clear()
        if UI:
            for t in list(self.sessions) or ["default"]:
                UI({"type": "brain", "kind": "status", "state": "stopped", "effort": self.effort_for(t), "tab": t})

    # -- sessions ---------------------------------------------------------------------------------------------------
    def open_session(self, fresh=False, tab="default"):
        """One Harness session per conversation tab, resumed across restarts unless fresh."""
        if not self.start():
            raise RuntimeError(self.error or "the brain did not start")
        tab = tab or "default"
        sid = self.sessions.get(tab)
        if sid and not fresh:
            self.session = sid
            return sid
        old = None
        try:
            data = json.loads(SESSION_FILE.read_text())
            if isinstance(data.get("tabs"), dict):
                old = data["tabs"].get(tab)
            elif tab == "default":
                old = data.get("sessionId")
        except Exception:
            pass
        if old and not fresh:
            try:
                self.call("session/resume", {"sessionId": old, "cwd": str(LAB), "mcpServers": mcp_servers()}, timeout=90)
                self.sessions[tab] = old
                self.session_to_tab[old] = tab
                self.session = old
                self._apply_effort(old, tab)
                return old
            except Exception as e:
                print(f"brain: resume failed, starting fresh: {e}", flush=True)
        r = self.call("session/new", {"cwd": str(LAB), "mcpServers": mcp_servers()}, timeout=120)
        sid = r["sessionId"]
        self.sessions[tab] = sid
        self.session_to_tab[sid] = tab
        self.session = sid
        self._apply_effort(sid, tab)
        self._save_sessions(tab)
        self.request_usage(tab, force=True)
        return sid

    def _save_sessions(self, tab="default"):
        try:
            SESSION_FILE.write_text(json.dumps({"sessionId": self.session, "tabs": self.sessions,
                                                "last": tab, "at": time.time()}))
        except Exception:
            pass

    def _stored_sid(self, tab="default"):
        """The session id remembered for a tab, without resuming the ACP session."""
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            tabs = data.get("tabs") if isinstance(data, dict) else None
            if isinstance(tabs, dict) and tabs.get(tab):
                return tabs[tab]
            if tab == "default" and isinstance(data, dict):
                return data.get("sessionId")
        except Exception:
            pass
        return None

    # -- reasoning tier (DeepSeek-V4.1-Flash: low / high / max = 低 / 中 / 高) ------------------------------------------
    def effort_for(self, tab="default"):
        return self.effort.get(tab or "default", DEFAULT_EFFORT)

    def _save_effort(self):
        try:
            EFFORT_FILE.write_text(json.dumps({"tabs": self.effort}, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    def _apply_effort(self, sid, tab):
        """Tell one ACP session which reasoning tier to use. Never raises: an older Harness may not offer the knob."""
        level = self.effort_for(tab)
        try:
            self.call("session/set_config_option",
                      {"sessionId": sid, "configId": "reasoning_effort", "value": level}, timeout=30)
            return True, ""
        except Exception as e:
            return False, str(e)[:300]

    def set_effort(self, tab="default", level=None):
        """Switch one conversation's tier now and remember it for the next session in that tab."""
        tab = tab or "default"
        level = level if level in EFFORT_LEVELS else DEFAULT_EFFORT
        self.effort[tab] = level
        self._save_effort()
        sid = self.sessions.get(tab)
        ok, err = True, ""
        if sid and self.proc and self.proc.poll() is None:
            ok, err = self._apply_effort(sid, tab)
        if UI:
            UI({"type": "brain", "kind": "effort", "level": level, "ok": ok, "error": err, "tab": tab})
        return {"ok": ok, "level": level, "error": err}

    # -- what this conversation spent ------------------------------------------------------------------------------
    def usage_stats(self, tab="default"):
        """Tokens and money for one conversation tab, plus the account's remaining balance."""
        tab = tab or "default"
        sid = self.sessions.get(tab) or self._stored_sid(tab)
        out = {"kind": "usage_stats", "tab": tab, "tokens": 0, "input": 0, "output": 0, "cacheRead": 0,
               "cacheWrite": 0, "cost": 0.0, "currency": "CNY", "peak": False, "calls": 0,
               "session": bool(sid), "at": time.time(), "balance": account_balance()}
        path = _session_log(sid)
        if path:
            try:
                buckets = _read_usage(path)
                for b in buckets:
                    out["input"] += b.get("inputTokens", 0)
                    out["output"] += b.get("outputTokens", 0)
                    out["cacheRead"] += b.get("cacheReadTokens", 0)
                    out["cacheWrite"] += b.get("cacheWriteTokens", 0)
                    out["tokens"] += b.get("totalTokens", 0)
                    out["calls"] += b.get("calls", 0)
                    out["peak"] = out["peak"] or bool(b.get("peak"))
                out["cost"] = _cost_of(buckets)
                out["currency"] = "CNY"
            except Exception as e:
                out["error"] = str(e)[:200]
        return out

    def request_usage(self, tab="default", force=False):
        """Recompute one tab's usage off the reader thread and send it to the HUD (throttled)."""
        tab = tab or "default"
        now = time.time()
        with self.usage_lock:
            if not force and now - self.usage_at.get(tab, 0) < USAGE_TTL:
                return
            self.usage_at[tab] = now

        def work():
            try:
                stats = self.usage_stats(tab)
                if UI:
                    UI({"type": "brain", **stats})
            except Exception as e:
                print(f"brain: usage failed: {e}", flush=True)
        threading.Thread(target=work, daemon=True).start()

    def prompt(self, text, images=(), done=None, tab="default"):
        """Send one message to one conversation tab; returns at once. done(stop, text) runs when it ends."""
        tab = tab or "default"
        def work():
            try:
                self.busy_tabs.add(tab)
                self.asked[tab] = text
                self.texts[tab] = []
                self.busy = True
                if UI:
                    UI({"type": "brain", "kind": "status", "state": "working", "effort": self.effort_for(tab), "tab": tab})
                blocks = [{"type": "text", "text": text}] + [{"type": "image", "data": b64, "mimeType": mime} for b64, mime in images]
                for attempt in (1, 2):           # a failed turn restarts the brain once and tries again
                    try:
                        sid = self.open_session(tab=tab)
                        r = self.call("session/prompt", {"sessionId": sid, "prompt": blocks}, timeout=60 * 60)
                        break
                    except RuntimeError as e:
                        if attempt == 2 or "Internal error" not in str(e) or self.texts.get(tab):
                            raise
                        print(f"brain: turn failed, restarting once: {e}", flush=True)
                        self.restart()
                stop = r.get("stopReason", "end_turn")
            except Exception as e:
                stop = "error"
                self.error = str(e)
                if UI:
                    UI({"type": "brain", "kind": "error", "text": str(e)[:500], "tab": tab})
            self.busy_tabs.discard(tab)
            self.busy = bool(self.busy_tabs)
            answer = "".join(self.texts.get(tab, [])).strip()
            if UI:
                UI({"type": "brain", "kind": "status", "state": "idle", "stop": stop, "effort": self.effort_for(tab), "tab": tab})
            self.request_usage(tab, force=True)
            try:
                from ... import memory
                memory.log_work("brain", {"prompt": text[:500]}, {"stop": stop, "answer": answer[:1500]})
            except Exception:
                pass
            if done:
                done(stop, answer)
        threading.Thread(target=work, daemon=True).start()

    def restart(self):
        """Stop the Harness process; the next prompt starts a fresh one with the current profile."""
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc, self.session, self.caps = None, None, {}
        self.sessions.clear(); self.session_to_tab.clear(); self.texts.clear()
        self.busy_tabs.clear(); self.perm_tab.clear()
        for q in list(self.pending.values()):
            q.put({"error": {"message": "brain restarted"}})
        self.pending.clear()

    def cancel(self, tab=None):
        sid = self.sessions.get(tab or "default")
        if sid and self.proc and self.proc.poll() is None:
            self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})

    def new_conversation(self, tab="default"):
        tab = tab or "default"
        old = self.sessions.pop(tab, None)
        if old:
            self.session_to_tab.pop(old, None)
            if self.proc and self.proc.poll() is None:
                try:
                    self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": old}})
                except Exception:
                    pass
        self.texts.pop(tab, None)
        self.session = None
        return self.open_session(fresh=True, tab=tab)

    def close_session(self, tab="default"):
        tab = tab or "default"
        sid = self.sessions.pop(tab, None)
        if sid:
            self.session_to_tab.pop(sid, None)
            if self.proc and self.proc.poll() is None:
                try:
                    self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": sid}})
                except Exception:
                    pass
        self.texts.pop(tab, None)
        self.busy_tabs.discard(tab)
        if self.session == sid:
            self.session = next(iter(self.sessions.values()), None)
        if not self.sessions:
            self.session = None
        self._save_sessions("default")
        return {"ok": True, "closed": tab}

    # -- what comes back ------------------------------------------------------------------------------------------
    def _update(self, p):
        u = p.get("update", {})
        kind = u.get("sessionUpdate")
        sid = p.get("sessionId") or u.get("sessionId") or self.session
        tab = self.session_to_tab.get(sid, "default")
        if self.on_update:
            self.on_update(u)
        out = None
        if kind in ("agent_message_chunk", "agent_thought_chunk"):
            c = u.get("content", {})
            t = c.get("text", "") if isinstance(c, dict) else ""
            if kind == "agent_message_chunk":
                self.texts.setdefault(tab, []).append(t)
            out = {"kind": "say" if kind == "agent_message_chunk" else "think", "text": t, "id": u.get("messageId")}
        elif kind == "tool_call":
            out = {"kind": "tool", "id": u.get("toolCallId"), "title": u.get("title"), "status": u.get("status"),
                   "input": json.dumps(u.get("rawInput"), ensure_ascii=False)[:600]}
        elif kind == "tool_call_update":
            content = u.get("content") or []
            text = " ".join(x.get("content", {}).get("text", "") for x in content if isinstance(x, dict) and isinstance(x.get("content"), dict))
            out = {"kind": "tool", "id": u.get("toolCallId"), "status": u.get("status"), "output": text[:800]}
        elif kind == "usage_update":
            out = {"kind": "usage", "used": u.get("used"), "size": u.get("size"), "cost": u.get("cost")}
        elif kind == "config_option_update":
            for o in u.get("configOptions") or []:
                if isinstance(o, dict) and o.get("id") == "reasoning_effort":
                    level = str(o.get("currentValue") or "")
                    if level in EFFORT_LEVELS:
                        self.effort[tab] = level
                        out = {"kind": "effort", "level": level, "ok": True}
        if out and UI:
            UI({"type": "brain", **out, "tab": tab})

    def _permission(self, m):
        rid, p = m["id"], m.get("params", {})
        tool = (p.get("toolCall") or {}).get("toolCallId")
        tab = self.session_to_tab.get(p.get("sessionId"), "default")
        q = queue.Queue()
        self.perms[str(rid)] = q
        self.perm_tab[str(rid)] = tab
        if UI:
            UI({"type": "brain", "kind": "ask", "ask": str(rid), "tool": tool, "tab": tab})
        def wait():
            try:
                allow = q.get(timeout=10 * 60)
            except queue.Empty:
                allow = False
            self.perms.pop(str(rid), None)
            outcome = {"outcome": "selected", "optionId": "allow-once" if allow else "reject-once"}
            self._send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": outcome}})
            if UI:
                UI({"type": "brain", "kind": "answered", "ask": str(rid), "allow": bool(allow)})
        threading.Thread(target=wait, daemon=True).start()

    def answer(self, ask, allow):
        q = self.perms.get(str(ask))
        if q:
            q.put(bool(allow))


BRAIN = Brain()


def self_check():
    """Start the brain once and record what works: started, session, a reply, a call to Jarvis's own tools, images."""
    report = {"version": VERSION, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}
    def step(name, ok, **info):
        report["steps"].append({"step": name, "ok": bool(ok), **info})
        CHECK.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return ok
    try:
        report["profile_written"] = ensure_profile()
        t = time.time()
        if not step("start", BRAIN.start(), seconds=round(time.time() - t, 1), caps=BRAIN.caps, error=BRAIN.error):
            return report
        t = time.time()
        sid = BRAIN.open_session(fresh=True)
        step("session", bool(sid), seconds=round(time.time() - t, 1))
        seen = []
        BRAIN.on_update = lambda u: seen.append(u.get("sessionUpdate") + ":" + str(u.get("title", "")))
        done = threading.Event(); res = {}
        t = time.time()
        BRAIN.prompt("这是启动自检，不用做任何事。只回复两个字：在线", done=lambda s, a: (res.update(stop=s, text=a), done.set()))
        done.wait(180)
        step("reply", "在线" in res.get("text", ""), seconds=round(time.time() - t, 1), stop=res.get("stop"), text=res.get("text", "")[:200])
        done.clear(); res.clear(); seen.clear(); t = time.time()
        BRAIN.prompt("启动自检第二步：调用 jarvis_skills 工具，然后只回复已安装和试用中的能力各有几个。",
                     done=lambda s, a: (res.update(stop=s, text=a), done.set()))
        done.wait(240)
        step("jarvis_tools", any("jarvis_skills" in x for x in seen), seconds=round(time.time() - t, 1),
             text=res.get("text", "")[:300], updates=seen[:20])
        step("image_input", bool(BRAIN.caps.get("promptCapabilities", {}).get("image")))
    except Exception as e:
        step("error", False, error=f"{type(e).__name__}: {e}"[:600])
    finally:
        BRAIN.on_update = None
        BRAIN.session = None           # the check's conversation is not the workbench
        try:
            SESSION_FILE.unlink()
        except Exception:
            pass
    return report


def check_once():
    try:
        old = json.loads(CHECK.read_text())
        if old.get("version") == VERSION and all(s.get("ok") for s in old.get("steps", [])):
            return
    except Exception:
        pass
    threading.Thread(target=self_check, daemon=True).start()


def open_window(task="", **_):
    """Voice layer: open the brain window with the task filled in. The user reads it and starts it themselves."""
    if UI:
        UI({"type": "brain", "kind": "open", "task": (task or "").strip()})
    return {"ok": True, "note": "The brain window is open on the right with the task filled in; it starts when the user "
                                "presses send. Tell the user that in one short sentence. Do not claim the work is done."}


def voice_tool():
    return {"type": "function", "function": {
        "name": "open_brain",
        "description": "Open your brain window (your deep-thinking workspace on the right of the screen) with a task filled in. "
                       "Use for jobs that need planning, building or several steps: learning a new ability, building or "
                       "fixing something, research. Also when the user says 打开大脑, 大脑窗口, 让大脑来做.",
        "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "the full task in the user's words (Chinese)"}}}}}


def available():
    return _dsh() is not None
