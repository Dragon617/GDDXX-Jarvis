"""Douyin creator-backend numbers, read from screenshots the user drops on the Desktop.

The user screenshots the 抖音创作者中心 pages of a video (总览 / 流量分析) onto the Desktop and asks
"how did yesterday's video do?". Jarvis reads the newest screenshots with the system's text
recognition (Apple Vision on macOS, RapidOCR elsewhere; fully offline), pulls out the numbers, keeps a small history in
~/.jarvis/creator_history.json so later videos can be compared, and shows a data panel on the HUD.
Nothing leaves this computer except what the language model is told."""
import json, re, time
from datetime import datetime
from pathlib import Path

from ..paths import DATA, DESKTOP
HISTORY = DATA / "creator_history.json"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".heic", ".webp"}
UI = None                       # set by brain: UI(message) sends a message to the HUD window

# label on screen -> (key, kind). kind: count / pct / sec
LABELS = {
    "播放量": ("plays", "count"), "点赞量": ("likes", "count"), "评论量": ("comments", "count"),
    "分享量": ("shares", "count"), "收藏量": ("saves", "count"), "弹幕量": ("danmaku", "count"),
    "完播率": ("completion", "pct"), "2s跳出率": ("bounce_2s", "pct"), "5s完播率": ("retain_5s", "pct"),
    "平均播放时长": ("avg_watch", "sec"), "平均播放占比": ("avg_ratio", "pct"),
    "涨粉量": ("new_fans", "count"), "脱粉量": ("lost_fans", "count"), "粉丝播放占比": ("fan_view_ratio", "pct"),
    "主页访问量": ("profile_visits", "count"), "作品点赞量": ("likes", "count"),
}
ROW_LABELS = {   # values sit on the same row, to the right
    "推荐页": ("src_feed", "pct"), "个人主页": ("src_profile", "pct"), "搜索": ("src_search", "pct"),
    "关注页": ("src_following", "pct"), "消息页": ("src_message", "pct"), "同城": ("src_local", "pct"),
    "平台扶持流量": ("boost", "count"),
}
NAMES_EN = {"plays": "views", "likes": "likes", "comments": "comments", "shares": "shares", "saves": "saves",
            "danmaku": "bullet comments", "completion": "completion rate", "bounce_2s": "2-second drop-off rate",
            "retain_5s": "5-second retention", "avg_watch": "average watch time (seconds)",
            "avg_ratio": "average share of the video watched", "new_fans": "new followers", "lost_fans": "lost followers",
            "fan_view_ratio": "share of views from existing followers", "profile_visits": "profile visits",
            "src_feed": "traffic from the recommendation feed", "src_profile": "traffic from profile page",
            "src_search": "traffic from search", "src_following": "traffic from following feed",
            "src_message": "traffic from messages", "src_local": "traffic from nearby feed",
            "boost": "extra views pushed by the platform"}
NUM = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?\s*(?:万|w|W|亿)?\s*(?:%|％|s|秒|次播放|次)?$")
CHANGE = re.compile(r"比往期\s*([+-−]?\s*\d[\d,]*(?:\.\d+)?)\s*[%％]")
VIDEO_DATE = re.compile(r"(20\d\d)年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}:\d{2})?")


# ---------------------------------------------------------------- OCR
def ocr(path):
    """Text boxes on an image (Apple Vision on macOS, RapidOCR elsewhere)."""
    from .. import platforms
    return platforms.ocr(path)


# ---------------------------------------------------------------- parsing
def norm(t):
    return re.sub(r"[\s ⓘ①ⓘ()（）:：]", "", t)


def to_number(text, kind):
    t = text.replace(",", "").replace("％", "%").replace("−", "-").strip()
    m = re.search(r"[+-]?\d+(?:\.\d+)?", t)
    if not m:
        return None
    v = float(m.group())
    if "亿" in t:
        v *= 1e8
    elif re.search(r"万|w|W", t):
        v *= 1e4
    if kind == "count":
        return int(round(v))
    return round(v, 2)


def _merge_units(boxes):
    """'3.43' + '万' or '9.51' + '%' recognised as separate boxes -> one value box."""
    out, used = [], set()
    for i, b in enumerate(boxes):
        if i in used:
            continue
        b = dict(b)
        if re.fullmatch(r"[+-]?\d[\d,]*(?:\.\d+)?", b["t"]):
            for j, c in enumerate(boxes):
                if j == i or j in used or c["t"] not in ("万", "%", "％", "s", "秒", "亿", "w"):
                    continue
                same_row = abs((c["y"] + c["h"] / 2) - (b["y"] + b["h"] / 2)) < b["h"] * 0.8
                gap = c["x"] - (b["x"] + b["w"])
                if same_row and -0.005 < gap < 0.04:
                    b["t"] += c["t"]; b["w"] = c["x"] + c["w"] - b["x"]; used.add(j)
                    break
        out.append(b)
    return out


def _value_below(label, boxes):
    """Nearest number under a label (the dashboard tiles put the value right under the label)."""
    lb = label["y"] + label["h"]
    best = None
    for b in boxes:
        if b is label or not NUM.match(b["t"].replace(" ", "")):
            continue
        dy = b["y"] - lb
        if not (-0.004 < dy < 0.14):
            continue
        if abs(b["x"] - label["x"]) > max(0.06, label["w"] * 1.2):
            continue
        score = dy + abs(b["x"] - label["x"]) * 0.5
        if best is None or score < best[0]:
            best = (score, b)
    return best[1] if best else None


def _change_below(value, boxes):
    vb = value["y"] + value["h"]
    for b in sorted(boxes, key=lambda b: b["y"]):
        m = CHANGE.search(b["t"].replace(" ", ""))
        if m and -0.004 < b["y"] - vb < 0.08 and abs(b["x"] - value["x"]) < 0.12:
            return float(m.group(1).replace("−", "-").replace(" ", ""))
    return None


def _row_values(label, boxes):
    """Numbers on the same row to the right of a label, left to right (e.g. '97.5%', '+25%')."""
    cy = label["y"] + label["h"] / 2
    row = [b for b in boxes if b is not label and b["x"] > label["x"] + label["w"] - 0.005
           and abs(b["y"] + b["h"] / 2 - cy) < max(label["h"], 0.012) * 0.9]
    row.sort(key=lambda b: b["x"])
    return [b for b in row if re.search(r"\d", b["t"])]


def parse(boxes):
    """Turn text boxes from one screenshot into {"metrics": {...}, "title", "posted"}."""
    boxes = _merge_units([b for b in boxes if b["t"]])
    metrics = {}
    for b in boxes:
        n = norm(b["t"])
        if n in LABELS:
            key, kind = LABELS[n]
            if key in metrics:
                continue
            v = _value_below(b, boxes)
            if not v:
                continue
            val = to_number(v["t"], kind)
            if val is None:
                continue
            metrics[key] = {"label": n, "value": val, "text": v["t"].replace(" ", ""), "change_pct": _change_below(v, boxes)}
        elif n in ROW_LABELS:
            key, kind = ROW_LABELS[n]
            vals = _row_values(b, boxes)
            if key in metrics or not vals:
                continue
            val = to_number(vals[0]["t"], kind)
            if val is None:
                continue
            entry = {"label": n, "value": val, "text": vals[0]["t"].replace(" ", ""), "change_pct": None}
            if len(vals) > 1 and re.match(r"^[+-−]", vals[1]["t"]):
                entry["vs_7d"] = vals[1]["t"].replace(" ", "")
            metrics[key] = entry
    text = "\n".join(b["t"] for b in sorted(boxes, key=lambda b: (round(b["y"], 2), b["x"])))
    posted = None
    m = VIDEO_DATE.search(text.replace(" ", ""))
    if m:
        posted = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" + (f" {m.group(4)}" if m.group(4) else "")
    title = None
    tops = [b for b in boxes if b["y"] < 0.2 and len(b["t"]) >= 12]
    tagged = [b for b in tops if "#" in b["t"]]
    if tops:
        first = sorted(tagged or tops, key=lambda b: b["y"])[0]
        # the caption wraps over a few lines; join the lines that belong to it
        lines = sorted([b for b in tops if abs(b["x"] - first["x"]) < 0.03 and b["y"] <= first["y"] + 0.06
                        and not VIDEO_DATE.search(b["t"].replace(" ", ""))], key=lambda b: b["y"])
        title = "".join(b["t"] for b in lines) or first["t"]
    diag = [b["t"] for b in boxes if re.search(r"上涨|下降|表现|较往期|出色|偏低", b["t"]) and len(b["t"]) > 8]
    return {"metrics": metrics, "title": title, "posted": posted, "notes": diag[:3]}


# ---------------------------------------------------------------- screenshots
def screenshots(hours=48, limit=4):
    cutoff = time.time() - hours * 3600
    files = [p for p in DESKTOP.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_EXT and not p.name.startswith(".") and p.stat().st_mtime >= cutoff]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _load_history():
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(entry):
    hist = [h for h in _load_history() if h.get("key") != entry["key"]]
    hist.append(entry)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(hist[-60:], ensure_ascii=False, indent=1), encoding="utf-8")
    return hist


def read_stats(hours=48):
    files = screenshots(hours)
    if not files:
        return {"ok": False, "error": f"no screenshots on the Desktop from the last {hours} hours. "
                                      "Ask the user to screenshot the video's page in 抖音创作者中心 (总览 and 流量分析) onto the Desktop."}
    merged = {"metrics": {}, "title": None, "posted": None, "notes": []}
    used = []
    for f in reversed(files):                       # oldest first, so the newest screenshot wins on clashes
        try:
            p = parse(ocr(f))
        except ImportError:
            return {"ok": False, "error": "text recognition is not installed yet. Reinstall Jarvis."}
        except Exception as e:
            print(f"creator: {f.name}: {type(e).__name__}: {e}", flush=True)
            continue
        if not p["metrics"]:
            continue
        used.append(f.name)
        for k, v in p["metrics"].items():
            if k not in merged["metrics"] or v.get("change_pct") is not None:
                merged["metrics"][k] = v
        merged["title"] = merged["title"] or p["title"]
        merged["posted"] = merged["posted"] or p["posted"]
        merged["notes"] += [n for n in p["notes"] if n not in merged["notes"]]
    if not merged["metrics"]:
        return {"ok": False, "error": "found screenshots on the Desktop but none looked like the 抖音 creator backend",
                "files": [f.name for f in files]}
    mt = merged["metrics"]
    key = (merged["posted"] or "") + "|" + (merged["title"] or "")[:30]
    prev = [h for h in _load_history() if h.get("key") != key]
    _save_history({"key": key, "title": merged["title"], "posted": merged["posted"],
                   "read_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "metrics": {k: v["value"] for k, v in mt.items()}})
    derived = {}
    if mt.get("plays", {}).get("value") and mt.get("new_fans"):
        derived["new_fans_per_10k_views"] = round(mt["new_fans"]["value"] / mt["plays"]["value"] * 1e4, 1)
    if mt.get("plays", {}).get("value") and mt.get("shares") and mt.get("saves"):
        derived["shares_plus_saves_per_1k_views"] = round((mt["shares"]["value"] + mt["saves"]["value"]) / mt["plays"]["value"] * 1e3, 1)
    vs_last = None
    if prev:
        last = prev[-1]
        vs_last = {"title": (last.get("title") or "")[:40], "posted": last.get("posted"),
                   "changes": {NAMES_EN.get(k, k): {"before": last["metrics"][k], "now": v["value"]}
                               for k, v in mt.items() if k in last.get("metrics", {})}}
    if UI:
        UI({"type": "stats", "title": merged["title"], "posted": merged["posted"],
            "metrics": {k: {"label": v["label"], "value": v["value"], "text": v["text"], "change": v.get("change_pct")}
                        for k, v in mt.items()}, "derived": derived})
    return {"ok": True, "video_caption": merged["title"], "posted": merged["posted"], "screenshots_read": used,
            "numbers": {NAMES_EN.get(k, k): (v["value"], v["text"]) for k, v in mt.items()},
            "change_vs_creator_average_pct": {NAMES_EN.get(k, k): v["change_pct"] for k, v in mt.items() if v.get("change_pct") is not None},
            "derived": derived, "platform_notes": merged["notes"], "vs_previous_report": vs_last,
            "note": "A data panel is now on screen. Percent values are already percentages."}


def tool():
    return {"type": "function", "function": {
        "name": "read_creator_stats",
        "description": "Read the user's Douyin (抖音) creator-backend numbers for a video from the screenshots they put on "
                       "the Desktop: views, likes, comments, shares, saves, completion and retention, new followers, "
                       "traffic sources, and how they compare with the user's usual videos and the last report. Shows "
                       "a data panel on screen. Use it whenever the user asks how a video or their account is doing.",
        "parameters": {"type": "object", "properties": {
            "hours": {"type": "number", "description": "only use screenshots taken in the last this many hours (default 48)"}}}}}


def run(hours=48, **_):
    try:
        return read_stats(float(hours or 48))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":          # python -m jarvis.plugins.creator  -> print what the screenshots say
    import pprint
    pprint.pprint(read_stats())


HINT = (" When the user asks how a video, their Douyin account or 'the data' (数据, 播放, 涨粉) is doing, call "
        "read_creator_stats. Brief them like a butler reporting to an employer: open with the headline (views and "
        "new followers), then the one number that tells the real story (shares and saves, retention, or the jump "
        "against their usual videos), then one honest weak spot. Allow yourself one dry, understated British quip, "
        "never cheesy. Up to four sentences. Use only numbers the tool returned, rounded the way people say them "
        "(thirty-four thousand views). If it finds no screenshots, say so and ask them to screenshot the video's "
        "page in the creator backend onto the Desktop.")


def bind(ctx):
    global UI
    UI = ctx.ui


def provide():
    return [(tool(), run)], HINT
