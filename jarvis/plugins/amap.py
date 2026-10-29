"""Weather, places and routes from AMap (高德) Web services.

The key lives only in ~/.jarvis/config.json on this computer: {"amap": {"key": "..."}}.
Saved places (home, work, ...) are in ~/.jarvis/places.json. Location is never tracked:
routes start from home unless the user names another start, and the city comes from
the home address or, without one, from this computer's public IP."""
import json, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from ..paths import CONFIG, DATA
PLACES = DATA / "places.json"
BASE = "https://restapi.amap.com"
MODES = {"car": "driving", "transit": "transit", "walk": "walking", "bike": "bicycling"}
_cache = {}
LAST_ROUTE = None        # the route last asked for, picked up by the service to show on the HUD


def key():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("amap", {}).get("key", "")
    except Exception:
        return ""


def get(path, **params):
    k = key()
    if not k:
        raise RuntimeError("no AMap key in ~/.jarvis/config.json")
    url = f"{BASE}{path}?" + urllib.parse.urlencode({**params, "key": k, "output": "json"})
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    ok = data.get("status") == "1" or data.get("errcode") == 0
    if not ok:
        raise RuntimeError(f"AMap {path}: {data.get('info') or data.get('errmsg')} ({data.get('infocode') or data.get('errcode')})")
    return data


def cached(name, ttl, fn):
    hit = _cache.get(name)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[name] = (time.time(), val)
    return val


# -- places ---------------------------------------------------------------
def places():
    try:
        return json.loads(PLACES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find(query, city=""):
    """Address or place name -> {name, address, location 'lng,lat', city, adcode}."""
    try:
        r = get("/v3/place/text", keywords=query, city=city, citylimit="false", offset=1, page=1)
        if r.get("pois"):
            p = r["pois"][0]
            return _fill({"name": p.get("name") or query, "address": _s(p.get("address")), "location": p["location"],
                          "city": _s(p.get("cityname")), "adcode": _s(p.get("adcode"))})
    except Exception as e:
        print(f"amap place search: {e}", flush=True)
    r = get("/v3/geocode/geo", address=query, city=city)
    if not r.get("geocodes"):
        raise RuntimeError(f"could not find {query}")
    g = r["geocodes"][0]
    return _fill({"name": query, "address": _s(g.get("formatted_address")), "location": g["location"],
                  "city": _s(g.get("city")) or _s(g.get("province")), "adcode": _s(g.get("adcode"))})


def _s(v):
    return v if isinstance(v, str) else ""        # AMap sends [] for empty fields


def regeo(location):
    """'lng,lat' -> {city, district, adcode} (place search sometimes leaves the adcode empty)."""
    def fetch():
        a = get("/v3/geocode/regeo", location=location)["regeocode"]["addressComponent"]
        return {"city": _s(a.get("city")) or _s(a.get("province")), "district": _s(a.get("district")), "adcode": _s(a.get("adcode"))}
    return cached("rg" + location, 86400 * 30, fetch)


def _fill(p):
    if p.get("location") and not p.get("adcode"):
        try:
            g = regeo(p["location"])
            p = {**p, "adcode": g["adcode"], "city": p.get("city") or g["city"], "district": g["district"]}
        except Exception as e:
            print(f"amap regeo: {e}", flush=True)
    return p


def save_place(label, address, mode=""):
    found = find(address, here()["adcode"] if label != "home" else "")
    ps = places()
    ps[label] = {**found, "query": address, **({"mode": mode} if mode in MODES else {})}
    PLACES.parent.mkdir(parents=True, exist_ok=True)
    PLACES.write_text(json.dumps(ps, ensure_ascii=False, indent=1), encoding="utf-8")
    _cache.clear()
    return {"ok": True, "label": label, **ps[label]}


def here():
    """The user's city: from the home address if saved, else from the public IP (cached for a day)."""
    h = places().get("home")
    if h and h.get("location") and not h.get("adcode"):
        h = _fill(h)                                   # older saves had no adcode, which sent weather to the IP's city
    if h and h.get("adcode"):
        return {"city": h.get("city", ""), "adcode": h["adcode"], "location": h["location"], "from": "home"}
    def ip():
        r = get("/v3/ip")
        rect = _s(r.get("rectangle"))
        loc = ""
        if rect:
            (a, b), (c, d) = [map(float, p.split(",")) for p in rect.split(";")]
            loc = f"{(a + c) / 2:.6f},{(b + d) / 2:.6f}"
        return {"city": _s(r.get("city")), "adcode": _s(r.get("adcode")), "location": loc, "from": "ip"}
    return cached("ip", 86400, ip)


# -- weather --------------------------------------------------------------
def weather(city=""):
    adcode = here()["adcode"] if not city else find(city, here()["adcode"])["adcode"] or city
    def fetch():
        live = get("/v3/weather/weatherInfo", city=adcode, extensions="base")["lives"][0]
        fc = get("/v3/weather/weatherInfo", city=adcode, extensions="all")["forecasts"][0]
        days = [{"date": c["date"], "week": c["week"], "day": c["dayweather"], "night": c["nightweather"],
                 "high": c["daytemp"], "low": c["nighttemp"]} for c in fc["casts"]]
        return {"ok": True, "city": live["city"], "now": live["weather"], "temp": live["temperature"],
                "humidity": live["humidity"], "wind": f'{live["winddirection"]}风 {live["windpower"]}级',
                "report_time": live["reporttime"], "days": days}
    return cached(f"wx{adcode}", 1200, fetch)


# -- routes ---------------------------------------------------------------
def _place(q, default):
    ps = places()
    if not q:
        return default
    lab = {"家": "home", "home": "home", "公司": "work", "单位": "work", "work": "work", "office": "work"}.get(q.strip().lower(), q)
    return ps.get(lab) or find(q, here()["adcode"])


def route(destination, origin="", mode=""):
    ps = places()
    start = _place(origin, ps.get("home") or {"name": "当前城市", "location": here()["location"], "adcode": here()["adcode"]})
    end = _place(destination, None)
    mode = mode if mode in MODES else (end.get("mode") or "car")
    o, d = start["location"], end["location"]
    poly, dist, secs, line = [], 0, 0, ""
    traffic = []                                   # (polyline, status) pieces, driving only
    if mode == "car":
        p = get("/v3/direction/driving", origin=o, destination=d, strategy=10, extensions="all")["route"]["paths"][0]
        dist, secs = int(p["distance"]), int(p["duration"])
        poly = [s["polyline"] for s in p["steps"]]
        for st in p["steps"]:
            tm = st.get("tmcs") or []
            if isinstance(tm, list) and tm:
                traffic += [(t.get("polyline", ""), TRAFFIC.get(t.get("status"), -1)) for t in tm if isinstance(t, dict)]
            else:
                traffic.append((st["polyline"], -1))
    elif mode == "walk":
        p = get("/v3/direction/walking", origin=o, destination=d)["route"]["paths"][0]
        dist, secs = int(p["distance"]), int(p["duration"])
        poly = [s["polyline"] for s in p["steps"]]
    elif mode == "bike":
        p = get("/v4/direction/bicycling", origin=o, destination=d)["data"]["paths"][0]
        dist, secs = int(p["distance"]), int(p["duration"])
        poly = [s["polyline"] for s in p["steps"]]
    else:
        city = start.get("adcode") or here()["adcode"]
        r = get("/v3/direction/transit/integrated", origin=o, destination=d, city=city,
                cityd=end.get("adcode") or city, strategy=0)["route"]
        if not r.get("transits"):
            raise RuntimeError("no public transport route found")
        t = r["transits"][0]
        dist, secs = int(r.get("distance") or 0), int(t["duration"])
        names = []
        for seg in t["segments"]:
            for bl in (seg.get("bus") or {}).get("buslines") or []:
                names.append(bl["name"].split("(")[0]); poly.append(bl.get("polyline", ""))
            w = seg.get("walking") or {}
            for st in w.get("steps") or []:
                poly.append(st.get("polyline", ""))
        line = " → ".join(names)
    eta = (datetime.now() + timedelta(seconds=secs)).strftime("%H:%M")
    nav_mode = {"car": "car", "transit": "bus", "walk": "walk", "bike": "ride"}[mode]
    nav = "https://uri.amap.com/navigation?" + urllib.parse.urlencode({
        "from": f'{o},{start.get("name", "")}', "to": f'{d},{end.get("name", destination)}',
        "mode": nav_mode, "policy": 1, "src": "jarvis", "coordinate": "gaode", "callnative": 1})
    return {"ok": True, "from": start.get("name", ""), "to": end.get("name", destination), "to_address": end.get("address", ""),
            "mode": mode, "minutes": round(secs / 60), "km": round(dist / 1000, 1), "eta": eta, "line": line,
            "nav_url": nav, "path": _shape(";".join(x for x in poly if x)),
            "holo": _holo(traffic or [(x, -1) for x in poly if x])}


TRAFFIC = {"畅通": 0, "缓行": 1, "拥堵": 2, "严重拥堵": 3}


def _holo(pieces, budget=700):
    """Route pieces -> {"segs": [{"p": [[x, y]...], "s": status}]} in -1..1 (x east, y north), same scale on
    both axes, for the 3D particle map. status: 0 clear, 1 slow, 2 jammed, 3 very jammed, -1 unknown."""
    import math
    segs = []
    for pl, st in pieces:
        pts = [tuple(map(float, q.split(","))) for q in (pl or "").split(";") if "," in q]
        if len(pts) >= 2:
            segs.append((pts, st))
    allp = [q for ps, _ in segs for q in ps]
    if len(allp) < 2:
        return None
    k = math.cos(math.radians(sum(q[1] for q in allp) / len(allp)))
    xs, ys = [q[0] * k for q in allp], [q[1] for q in allp]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 or 1e-9
    step = max(1, len(allp) // budget)
    out, prev = [], None
    for ps, st in segs:
        keep = ps[::step] + [ps[-1]]
        pts = [[round((q[0] * k - cx) / half * 0.9, 4), round((q[1] - cy) / half * 0.9, 4)] for q in keep]
        if prev is not None and prev["s"] == st:
            prev["p"] += pts[1:]                    # merge runs of the same status
        else:
            prev = {"p": pts, "s": st}
            out.append(prev)
    return {"segs": out, "km_per_unit": round(half / 0.9 * 111.0, 3),
            "geo": {"lng": round(cx / k, 6), "lat": round(cy, 6), "half": half, "k": k}}


def static_map(holo, size=1024):
    """A real AMap street map under the hologram: PNG (data URL) centred on the route, north up, and its
    half-width in hologram units so the HUD can lay it exactly under the route."""
    import base64, math
    g = holo["geo"]
    z = max(3, min(17, math.floor(math.log2(g["k"] * 720 * size / 1024 / (g["half"] * 1.45)))))
    url = f"{BASE}/v3/staticmap?" + urllib.parse.urlencode({
        "location": f'{g["lng"]:.6f},{g["lat"]:.6f}', "zoom": z, "size": f"{size}*{size}", "key": key()})
    with urllib.request.urlopen(url, timeout=10) as r:
        kind, data = r.headers.get("Content-Type", ""), r.read()
    if not kind.startswith("image"):
        raise RuntimeError(f"AMap staticmap: {data[:200]!r}")
    half_deg = g["k"] * 360 * size / 2 / (256 * 2 ** z)          # image half-width, in the same units as _holo
    return {"img": f"data:{kind.split(';')[0]};base64," + base64.b64encode(data).decode(), "half": round(half_deg / g["half"] * 0.9, 4), "zoom": z}


def _shape(polyline, n=16, aspect=3.4):
    """AMap polyline -> up to n points in 0..1 (y down), keeping the map's proportions inside a
    box `aspect` times wider than tall (the HUD's route strip)."""
    import math
    pts = [tuple(map(float, p.split(","))) for p in polyline.split(";") if "," in p]
    if len(pts) < 2:
        return []
    step = max(1, len(pts) // n)
    pts = pts[::step] + [pts[-1]]
    k = math.cos(math.radians(sum(p[1] for p in pts) / len(pts)))      # shrink longitude to metres
    xs, ys = [p[0] * k for p in pts], [p[1] for p in pts]
    dx, dy = (max(xs) - min(xs)) or 1e-9, (max(ys) - min(ys)) or 1e-9
    sc = min(0.9 * aspect / dx, 0.8 / dy)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [[round(0.5 + (x - cx) * sc / aspect, 4), round(0.5 - (y - cy) * sc, 4)] for x, y in zip(xs, ys)]


# -- tools for the language model ------------------------------------------
def tools():
    if not key():
        return []
    return [
        {"type": "function", "function": {
            "name": "get_weather",
            "description": "Weather now and the next 3 days. Without a city: the user's own city.",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}},
        {"type": "function", "function": {
            "name": "plan_route",
            "description": "Travel time, distance and arrival time to a place, with live traffic for driving. Starts from "
                           "home unless the user names a start. The route is shown on their screen with a QR code that "
                           "opens navigation in the AMap app on their phone. Use the place name the user said, in Chinese.",
            "parameters": {"type": "object", "properties": {
                "destination": {"type": "string", "description": "place name or address, or 'work' / 'home'"},
                "origin": {"type": "string", "description": "optional start; default home"},
                "mode": {"type": "string", "enum": list(MODES)}},
                "required": ["destination"]}}},
        {"type": "function", "function": {
            "name": "save_place",
            "description": "Remember the user's home or work address (or another named place) for routes and the morning commute.",
            "parameters": {"type": "object", "properties": {
                "label": {"type": "string", "description": "home, work, or a short name"},
                "address": {"type": "string", "description": "address or place name, in Chinese as the user said it"},
                "mode": {"type": "string", "enum": list(MODES), "description": "how they usually travel there"}},
                "required": ["label", "address"]}}},
    ]


def run(name, args):
    if name == "get_weather":
        return weather(args.get("city", ""))
    if name == "plan_route":
        global LAST_ROUTE
        r = LAST_ROUTE = route(args["destination"], args.get("origin", ""), args.get("mode", ""))
        return {k: v for k, v in r.items() if k not in ("path", "nav_url", "holo")}   # the model doesn't need those
    if name == "save_place":
        return save_place(args["label"], args["address"], args.get("mode", ""))


HINT = (" For weather use get_weather; for getting somewhere use plan_route (it starts from home; the route and a "
        "QR code for phone navigation appear on screen, so mention the QR code). Say the travel time and arrival "
        "time plainly. When the user tells you their home or work address, call save_place. If home is not saved "
        "yet and they ask for a route, give the answer and then ask for their home address once.")


def provide():
    return [(t, (lambda n: lambda **a: run(n, a))(t["function"]["name"])) for t in tools()], HINT
