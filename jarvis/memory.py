"""Jarvis's long-term memory: plain files in ~/.jarvis/memory, kept on this computer only.

  conversations/2026-10-21.jsonl   every line said, by the user and by Jarvis (English, Chinese subtitle, when)
  work/2026-10-21.jsonl            every tool Jarvis used: what was asked, what came back
  notes.md                         facts the user asked Jarvis to keep (one per line, with the date)

Nothing is ever thrown away by Jarvis itself; delete a day's file to forget that day."""
import json, os, re, threading, time
from datetime import datetime, timedelta
from pathlib import Path

from .paths import MEMORY as ROOT
CONV, WORK, NOTES = ROOT / "conversations", ROOT / "work", ROOT / "notes.md"
_lock = threading.Lock()
README = __doc__


def _day(t=None):
    return datetime.fromtimestamp(t or time.time()).strftime("%Y-%m-%d")


def _append(folder, row):
    try:
        with _lock:
            folder.mkdir(parents=True, exist_ok=True)
            if not (ROOT / "README.txt").exists():
                (ROOT / "README.txt").write_text(README, encoding="utf-8")
            with open(folder / f"{_day(row['t'])}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"memory: {e}", flush=True)


def log_turn(who, en, zh="", via=""):
    """who: 'you' or 'jarvis'. en: what was said (for the user, their own words in whatever language)."""
    en = (en or "").strip()
    if not en:
        return
    row = {"t": round(time.time(), 1), "who": who, "en": en}
    if zh:
        row["zh"] = zh.strip()
    if via:
        row["via"] = via
    _append(CONV, row)


def log_work(tool, args, result):
    if tool in ("search_memory",):            # looking things up is not work worth keeping
        return
    try:
        res = result if isinstance(result, dict) else {"result": str(result)}
        small = {k: v for k, v in res.items() if k not in ("svg", "data", "cloud") and len(json.dumps(v, ensure_ascii=False)) < 1500}
    except Exception:
        small = {"result": str(result)[:600]}
    _append(WORK, {"t": round(time.time(), 1), "tool": tool, "args": args, "result": small})


def _rows(folder, days=None, since=None):
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.jsonl"))
    if days:
        want = set(days)
        files = [f for f in files if f.stem in want]
    out = []
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    if since is None or r.get("t", 0) >= since:
                        out.append(r)
                except Exception:
                    continue
        except Exception:
            continue
    return out


def recent_turns(n=80, hours=None):
    days = [_day(time.time() - 86400 * k) for k in range(30)]   # the last month is plenty for the subtitle history
    rows = _rows(CONV, days, since=time.time() - hours * 3600 if hours else None)
    return rows[-n:]


def _terms(q):
    q = (q or "").lower()
    words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 1]
    han = re.findall(r"[一-鿿]+", q)
    grams = [h[i:i + 2] for h in han for i in range(max(1, len(h) - 1))] if han else []
    return words, grams


def _resolve_date(when):
    """'2026-10-20', 'today', 'yesterday', '今天', '昨天', '前天' -> a day."""
    w = (when or "").strip().lower()
    if not w:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
        return w
    back = {"today": 0, "今天": 0, "yesterday": 1, "昨天": 1, "前天": 2, "day before yesterday": 2}.get(w)
    return _day(time.time() - 86400 * back) if back is not None else None


def _when(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def search(query="", date="", limit=14, **_):
    """Lines from earlier conversations and past work that match the query (and/or fall on that date)."""
    day = _resolve_date(date)
    days = [day] if day else None
    words, grams = _terms(query)
    hits = []
    for kind, folder in (("said", CONV), ("did", WORK)):
        for r in _rows(folder, days):
            text = (json.dumps(r.get("args", ""), ensure_ascii=False) + " " + json.dumps(r.get("result", ""), ensure_ascii=False)
                    if kind == "did" else r.get("en", "") + " " + r.get("zh", "")).lower()
            score = sum(2 for w in words if w in text) + sum(1 for g in grams if g in text)
            if (words or grams) and not score:
                continue
            hits.append((score, r["t"], kind, r))
    if not hits:
        return {"ok": True, "found": [], "note": "nothing in memory matches" + (f" on {day}" if day else "")}
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    best = sorted(hits[:limit] if (words or grams) else hits[-limit:], key=lambda h: h[1])
    found = []
    for _, t, kind, r in best:
        if kind == "said":
            found.append({"when": _when(t), "who": "user" if r["who"] == "you" else "Jarvis", "said": r["en"][:400]})
        else:
            found.append({"when": _when(t), "tool": r["tool"], "args": r.get("args"), "result": json.dumps(r.get("result"), ensure_ascii=False)[:400]})
    return {"ok": True, "found": found, "total_matches": len(hits)}


def notes():
    try:
        return [l[2:].strip() for l in NOTES.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    except Exception:
        return []


def remember(fact="", **_):
    fact = re.sub(r"\s+", " ", fact or "").strip()
    if not fact:
        return {"ok": False, "error": "nothing to remember"}
    have = notes()
    if any(fact.lower() == n.split("] ", 1)[-1].lower() for n in have):
        return {"ok": True, "note": "already kept"}
    with _lock:
        ROOT.mkdir(parents=True, exist_ok=True)
        new = not NOTES.exists()
        with open(NOTES, "a", encoding="utf-8") as f:
            if new:
                f.write("# Things Jarvis keeps for you\n\n")
            f.write(f"- [{_day()}] {fact}\n")
    return {"ok": True, "kept": fact}


def forget(fact="", **_):
    want = (fact or "").lower().strip()
    if not want or not NOTES.exists():
        return {"ok": False, "error": "nothing like that is kept"}
    lines = NOTES.read_text(encoding="utf-8").splitlines()
    words, grams = _terms(want)
    def hit(l):
        t = l.lower()
        return l.startswith("- ") and (want in t or (words or grams) and all(w in t for w in words) and sum(g in t for g in grams) >= max(1, len(grams) // 2))
    keep = [l for l in lines if not hit(l)]
    if len(keep) == len(lines):
        return {"ok": False, "error": "nothing like that is kept", "kept_notes": notes()[-20:]}
    with _lock:
        NOTES.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return {"ok": True, "forgot": len(lines) - len(keep)}


def prompt_block():
    """What goes into every system prompt: the kept notes (newest last) and where the rest lives."""
    kept = notes()[-60:]
    text = "\n".join(f"- {n}" for n in kept)
    if len(text) > 3000:
        text = text[-3000:]
    days = sorted(p.stem for p in CONV.glob("*.jsonl")) if CONV.exists() else []
    span = f"Your memory of conversations goes back to {days[0]}." if days else "Your long-term memory is new and still empty."
    return (" You have a long-term memory on this computer: every conversation and every job you have done is kept. " + span +
            " For anything about earlier conversations or past work (上次, 昨天, 之前, 'what did we', 'did you'), call search_memory "
            "before answering and answer only from what it returns. When the user tells you something lasting about themselves or "
            "their plans, or asks you to remember something (记住), call remember_fact; when they ask you to forget it, forget_fact. "
            + (f"Things they asked you to keep:\n{text}\n" if text else ""))


def tools():
    return [
        {"type": "function", "function": {
            "name": "search_memory",
            "description": "Search Jarvis's long-term memory: everything the user and Jarvis said in earlier conversations, and "
                           "every job Jarvis did (holograms shown, schedule changes, routes, DeepSeek Harness tasks, device "
                           "switches). Use it whenever the user refers to the past.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "a few key words in English or Chinese, e.g. '猛禽 发动机' or 'weekly report'"},
                "date": {"type": "string", "description": "optional: YYYY-MM-DD, 'today', 'yesterday', '昨天', '前天'"}}}}},
        {"type": "function", "function": {
            "name": "remember_fact",
            "description": "Keep one lasting fact about the user or their work in Jarvis's notes, e.g. their preferences, people, "
                           "projects, or something they say to remember.",
            "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "the fact, one short sentence, in the user's language"}}, "required": ["fact"]}}},
        {"type": "function", "function": {
            "name": "forget_fact",
            "description": "Remove a kept fact from Jarvis's notes when the user asks to forget it.",
            "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    ]


RUN = {"search_memory": search, "remember_fact": remember, "forget_fact": forget}


def warm_history(keep=8, hours=12):
    """The last few turns from disk, as chat messages, so a restart doesn't wipe the thread."""
    msgs = []
    for r in recent_turns(keep, hours=hours):
        msgs.append({"role": "user" if r["who"] == "you" else "assistant",
                     "content": r["en"] if r["who"] == "you" else r["en"] + (f"\n【中文】{r['zh']}" if r.get("zh") else "")})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    while msgs and msgs[-1]["role"] == "user":      # a question that was never answered
        msgs.pop()
    return msgs


def provide():
    return [(t, RUN[t["function"]["name"]]) for t in tools()], prompt_block()
