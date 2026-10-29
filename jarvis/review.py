"""Jarvis's nightly review: read back a day of conversations and work, find what went wrong or was missing, and
propose what to fix or learn. Nothing is changed by the review itself; the user decides in the morning.

  ~/.jarvis/memory/reviews/<day>.json    {"day", "made", "summary_en", "summary_zh", "proposals": [...], "reported"}

A proposal is {"id", "kind": "learn" | "fix" | "habit", "title", "why", "evidence", "plan", "state"}:
  learn  an ability it lacks: goes on the learning list once approved, and the brain builds it at night
  habit  a change in how it behaves that a written recipe (a SKILL.md with no code) can carry
  fix    a fault in Jarvis's own program: the brain may not edit its core, so it is reported for the user to act on
States: new -> approved / rejected; approved learn/habit -> building -> trial -> learned."""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path

from . import config, memory, skills

ROOT = memory.ROOT / "reviews"
CORRECTION = re.compile(r"不对|错了|没反应|没有反应|不是这个|又没|还是没|怎么没|说了.{0,6}没|你没|不行|不好使|听错|搞错|wrong|didn't|doesn't work|not working")


def _day(offset=1):
    return (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")


def path(day):
    return ROOT / f"{day}.json"


def load(day):
    try:
        return json.loads(path(day).read_text(encoding="utf-8"))
    except Exception:
        return None


def save(r):
    ROOT.mkdir(parents=True, exist_ok=True)
    path(r["day"]).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def _signals(conv, work):
    """Things a program can see without a model: tool failures, corrections, repeats, possible self-echo."""
    out = []
    for w in work:
        res = w.get("result") or {}
        if isinstance(res, dict) and res.get("ok") is False:
            out.append(f"tool {w['tool']} failed at {memory._when(w['t'])}: {json.dumps(res, ensure_ascii=False)[:200]}")
    you = [c for c in conv if c["who"] == "you"]
    for c in you:
        if CORRECTION.search(c["en"]):
            out.append(f"user correction at {memory._when(c['t'])}: {c['en'][:120]}")
        if re.search(r"\bsir\b|先生", c["en"], re.I) and re.search(r"[a-z]", c["en"], re.I):
            out.append(f"possible self-echo (user line sounds like Jarvis) at {memory._when(c['t'])}: {c['en'][:120]}")
    seen = {}
    for c in you:
        k = re.sub(r"\W", "", c["en"])[:16]
        if len(k) >= 6:
            seen.setdefault(k, []).append(c)
    for k, cs in seen.items():
        if len(cs) >= 3:
            out.append(f"asked {len(cs)} times: {cs[0]['en'][:100]}")
    return out[:40]


def _transcript(conv, work, limit=14000):
    rows = [(c["t"], f"[{memory._when(c['t'])[11:]}] {'USER' if c['who'] == 'you' else 'JARVIS'}{'(' + c['via'] + ')' if c.get('via') else ''}: {c['en'][:300]}") for c in conv]
    rows += [(w["t"], f"[{memory._when(w['t'])[11:]}] TOOL {w['tool']} {json.dumps(w.get('args'), ensure_ascii=False)[:120]} -> {json.dumps(w.get('result'), ensure_ascii=False)[:160]}") for w in work]
    text = "\n".join(r for _, r in sorted(rows))
    return text[-limit:]


PROMPT = """You are reviewing one day of J.A.R.V.I.S., a voice assistant on the user's computer, the way a careful engineer
reviews logs. Below: what was said (USER / JARVIS) and every tool call with its result, then signals a script found.

Find, in order of importance:
1. Times Jarvis said it did something that no tool call in that turn did, or a tool returned an error.
2. Times the user had to correct it, repeat themselves, or gave up.
3. Things the user asked for that no tool could do (Jarvis said it can't, or dodged).
4. Behaviour the user disliked (too long, wrong language, answering its own echo, etc.).

Then propose at most 5 changes. Each: kind "learn" (a new ability to build), "habit" (a change in behaviour a written
recipe can carry) or "fix" (a fault in Jarvis's own program that only the user can repair). Be concrete and honest:
only what the log shows, quote the evidence briefly. If the day went fine, say so and propose nothing.

Reply with JSON only:
{"summary_en": "one or two spoken sentences for Jarvis to say, as a butler, addressing the user as {name}",
 "summary_zh": "the same in Chinese",
 "proposals": [{"kind": "learn|habit|fix", "title": "short, Chinese", "why": "Chinese, one sentence",
                "evidence": "quote or time", "plan": "Chinese, how to do it, one or two sentences"}]}

SIGNALS:
{signals}

LOG ({day}):
{log}
"""


def run(day=None, force=False):
    """Review a day (default: yesterday). Uses the voice layer's own model; returns the review."""
    from . import brain
    day = day or _day(1)
    old = load(day)
    if old and not force:
        return old
    conv = [r for r in memory._rows(memory.CONV, [day])]
    work = [r for r in memory._rows(memory.WORK, [day])]
    r = {"day": day, "made": time.strftime("%Y-%m-%d %H:%M"), "turns": len(conv), "jobs": len(work), "proposals": [], "reported": False}
    if len(conv) < 2:
        r.update(summary_en="", summary_zh="", empty=True)
        save(r)
        return r
    base, key, model = config.llm()
    if not base:
        r.update(error="no language model configured")
        return r
    sig = _signals(conv, work)
    body = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.replace("{signals}", "\n".join(sig) or "(none)")
                          .replace("{day}", day).replace("{name}", config.user_name()).replace("{log}", _transcript(conv, work))}]}
    try:
        msg = brain._chat(base, key, body)
        data = json.loads(re.search(r"\{.*\}", msg.get("content") or "", re.S).group(0))
    except Exception as e:
        r.update(error=f"{type(e).__name__}: {e}"[:300], signals=sig)
        return r
    for i, p in enumerate(data.get("proposals", [])[:5]):
        if p.get("kind") not in ("learn", "habit", "fix") or not p.get("title"):
            continue
        r["proposals"].append({"id": f"{day.replace('-', '')}-{i + 1}", "kind": p["kind"], "title": str(p["title"])[:60],
                               "why": str(p.get("why", ""))[:200], "evidence": str(p.get("evidence", ""))[:200],
                               "plan": str(p.get("plan", ""))[:300], "state": "new"})
    r.update(summary_en=str(data.get("summary_en", ""))[:400], summary_zh=str(data.get("summary_zh", ""))[:300], signals=sig)
    save(r)
    return r


def pending():
    """Reviews not yet reported to the user, newest first."""
    if not ROOT.exists():
        return []
    out = []
    for f in sorted(ROOT.glob("*.json"), reverse=True)[:7]:
        r = load(f.stem)
        if r and not r.get("reported") and not r.get("empty") and not r.get("error"):
            out.append(r)
    return out


def decide(pid, approve):
    """The user approves or rejects one proposal. Approved learn/habit items go on the learning list for the night."""
    for f in sorted(ROOT.glob("*.json"), reverse=True)[:14]:
        r = load(f.stem)
        for p in (r or {}).get("proposals", []):
            if p["id"] == pid:
                p["state"] = "approved" if approve else "rejected"
                save(r)
                if approve and p["kind"] in ("learn", "habit"):
                    items = skills._learn_load()
                    if not any(i.get("from") == pid for i in items):
                        items.append({"id": f"L{int(time.time())}", "what": p["title"], "asked": p.get("evidence", ""),
                                      "plan": p.get("plan", ""), "kind": p["kind"], "from": pid, "state": "approved",
                                      "times": 1, "first": time.strftime("%Y-%m-%d %H:%M"), "last": time.strftime("%Y-%m-%d %H:%M")})
                        skills._learn_save(items)
                return {"ok": True, "proposal": p}
    return {"ok": False, "error": "no such proposal"}


def all_open():
    out = []
    if ROOT.exists():
        for f in sorted(ROOT.glob("*.json"), reverse=True)[:7]:
            r = load(f.stem) or {}
            out += [dict(p, day=r.get("day")) for p in r.get("proposals", []) if p.get("state") == "new"]
    return out


def mark_reported(day):
    r = load(day)
    if r:
        r["reported"] = True
        save(r)


# -- night learning ---------------------------------------------------------------------------------------------
NIGHT = memory.ROOT / "night.json"


def night_task():
    """The one approved learning item the brain works on tonight (approved, never tried, oldest first)."""
    items = [i for i in skills._learn_load() if i["state"] == "approved"]
    return items[0] if items else None


def night_prompt(item):
    kind = item.get("kind", "learn")
    return (f"夜间自学（用户已批准，无人值守）。学习清单 id：{item['id']}\n"
            f"要学会的：{item['what']}\n" + (f"用户当时的原话或证据：{item.get('asked', '')}\n" if item.get("asked") else "") +
            (f"计划：{item['plan']}\n" if item.get("plan") else "") +
            ("这是一个习惯类改进：写一个只有 SKILL.md 的说明型技能就够了，不要写代码。\n" if kind == "habit" else "") +
            "按 AGENTS.md 的规则在 skills-trial 里完成它：先调用 jarvis_learning_update 标记为 building，做完必须用 "
            "jarvis_skill_test 测试通过。整个过程控制在 25 分钟内，遇到需要用户同意的操作就跳过并说明。"
            "最后用两三句中文总结：做了什么、怎么用、还有什么不确定。")


def night_log(entry):
    try:
        log = json.loads(NIGHT.read_text(encoding="utf-8"))
    except Exception:
        log = []
    log.append(entry)
    NIGHT.write_text(json.dumps(log[-60:], ensure_ascii=False, indent=1), encoding="utf-8")


def night_results(since_hours=20):
    try:
        log = json.loads(NIGHT.read_text(encoding="utf-8"))
    except Exception:
        return []
    cut = time.time() - since_hours * 3600
    return [e for e in log if e.get("t", 0) >= cut and not e.get("reported")]


def mark_night_reported():
    try:
        log = json.loads(NIGHT.read_text(encoding="utf-8"))
        for e in log:
            e["reported"] = True
        NIGHT.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def start_learning(item=None, on_done=None, limit=25 * 60):
    """Hand one approved learning item to the brain now. Returns at once."""
    from . import skills as sk
    from .plugins.harness import brainlink
    if not brainlink.available():
        return {"ok": False, "error": "no brain (DeepSeek Harness) on this computer"}
    import threading
    item = item or night_task()
    if not item:
        return {"ok": False, "error": "nothing approved to learn"}
    if brainlink.BRAIN.busy:
        return {"ok": False, "error": "the brain is busy with another job"}
    before = {s["folder"] for s in sk.listing()["trial"]}
    t0 = time.time()
    timer = threading.Timer(limit, brainlink.BRAIN.cancel)
    def done(stop, answer):
        timer.cancel()
        new = [s for s in sk.listing()["trial"] if s["folder"] not in before]
        tested = {s["folder"]: sk.test(s["folder"], "trial").get("ok") for s in new}
        items = sk._learn_load()
        for i in items:
            if i["id"] == item["id"]:
                i["state"] = "trial" if any(tested.values()) else "approved"
                i["tries"] = i.get("tries", 0) + 1
                if i["tries"] >= 2 and not any(tested.values()):
                    i["state"] = "stuck"
        sk._learn_save(items)
        night_log({"t": time.time(), "item": item["what"], "id": item["id"], "stop": stop, "minutes": round((time.time() - t0) / 60, 1),
                   "trial": list(tested), "passed": tested, "answer": (answer or "")[:800]})
        if on_done:
            on_done(item, tested, answer)
    timer.start()
    brainlink.BRAIN.prompt(night_prompt(item), done=done)
    return {"ok": True, "learning": item["what"], "note": "the brain is working on it in the brain window; it takes up to 25 minutes"}
