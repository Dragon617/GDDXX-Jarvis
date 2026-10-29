"""Today's plan, kept as one small JSON file per day in ~/.jarvis/schedule/ on this computer.
The language model fills it from conversation ("上午十点开会，下午做报价单"); the HUD shows it
in 今日安排 and counts it in 工作汇报; the service reminds five minutes before each item."""
import json, re, time
from datetime import date, datetime, timedelta
from pathlib import Path

from .paths import SCHEDULE as DIR
FIELDS = ("start", "end", "title", "title_en", "note", "done")


def _day(day=None):
    if not day or day == "today":
        return date.today().isoformat()
    if day == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    if day == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return date.fromisoformat(day).isoformat()


def _hhmm(v):
    """'9:5' / '09:05' / '' -> 'HH:MM' or ''."""
    m = re.match(r"^\s*(\d{1,2})[:：](\d{1,2})", str(v or ""))
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else ""


def load(day=None):
    try:
        data = json.loads((DIR / f"{_day(day)}.json").read_text(encoding="utf-8"))
        return data if isinstance(data.get("items"), list) else {"items": []}
    except Exception:
        return {"items": []}


def save(data, day=None):
    DIR.mkdir(parents=True, exist_ok=True)
    data["items"].sort(key=lambda x: (x.get("start") or "99:99", x["id"]))
    p = DIR / f"{_day(day)}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _clean(item, base=None):
    out = dict(base or {})
    for k in FIELDS:
        if k in item and item[k] is not None:
            v = item[k]
            out[k] = _hhmm(v) if k in ("start", "end") else bool(v) if k == "done" else str(v).strip()
    out.setdefault("title", out.get("title_en", "")); out.setdefault("title_en", out.get("title", ""))
    for k in ("start", "end", "note"):
        out.setdefault(k, "")
    out.setdefault("done", False)
    return out


def manage(action, day=None, items=None, id=None, changes=None):
    data = load(day)
    its = data["items"]
    find = lambda i: next((x for x in its if x["id"] == i), None)
    if action == "add":
        nid = max([x["id"] for x in its] + [0])
        for it in items or []:
            nid += 1
            its.append({"id": nid, **_clean(it)})
    elif action in ("update", "remove"):
        target = find(id)
        if not target:
            return {"ok": False, "error": f"no item {id}", "day": _day(day), "items": its}
        if action == "remove":
            its.remove(target)
        else:
            target.update(_clean(changes or {}, target))
    elif action == "clear":
        its.clear()
    elif action != "list":
        return {"ok": False, "error": f"unknown action {action}"}
    if action != "list":
        save(data, day)
    return {"ok": True, "day": _day(day), "items": load(day)["items"]}


def due(minutes=5, now=None):
    """Items of today that start within `minutes` and are not done."""
    now = now or datetime.now()
    out = []
    for it in load()["items"]:
        if it.get("done") or not it.get("start"):
            continue
        h, m = map(int, it["start"].split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if timedelta(0) < start - now <= timedelta(minutes=minutes):
            out.append(it)
    return out


def tool():
    item = {"type": "object", "properties": {
        "start": {"type": "string", "description": "HH:MM, 24-hour; empty if no time was given"},
        "end": {"type": "string", "description": "HH:MM or empty"},
        "title": {"type": "string", "description": "short title in the user's own language (Chinese if they spoke Chinese), at most 10 characters"},
        "title_en": {"type": "string", "description": "the same title in English, for speaking"},
        "note": {"type": "string", "description": "optional detail, user's language"},
        "done": {"type": "boolean"}}}
    return {"type": "function", "function": {
        "name": "manage_schedule",
        "description": "The user's day plan (shown on their screen as 今日安排 and counted in the work report). "
                       "list = read it; add = add items; update = change one item by id (times, title, done); "
                       "remove = delete one item by id; clear = empty the day. To postpone an item to another day, "
                       "remove it here and add it on that day.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "add", "update", "remove", "clear"]},
            "day": {"type": "string", "description": "today (default), tomorrow, yesterday or YYYY-MM-DD"},
            "items": {"type": "array", "items": item, "description": "for add"},
            "id": {"type": "integer", "description": "for update/remove"},
            "changes": {**item, "description": "for update: only the fields that change"}},
            "required": ["action"]}}}


HINT = (" You keep the user's day plan with manage_schedule. When they tell you what they will do, add every "
        "item (24-hour HH:MM times; 'three in the afternoon' = 15:00; no time given = empty start), with a short "
        "title in their own language and an English title_en. When something is finished, cancelled or moved, "
        "update or remove it. Before answering anything about their day or their progress, call list. "
        "After adding items, confirm briefly how many you added and the first one.")


def provide():
    return [(tool(), manage)], HINT
