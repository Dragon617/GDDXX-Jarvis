"""Mi Home (米家) devices on the local network, for the brain to switch on request.

Device keys come from ~/.jarvis/mihome.json (written once by `python -m jarvis.plugins.mihome.connect`).
Commands go straight to the device over the home Wi-Fi (miIO protocol, UDP 54321); the
miot spec that says which property does what is fetched once from miot-spec.org and cached."""
import hashlib, json, socket, struct, time, urllib.parse, urllib.request
from ...paths import DATA as JARVIS
DEVICES = JARVIS / "mihome.json"
SPEC_CACHE = JARVIS / "miot-spec-cache.json"
# never operated by voice: locks, cooking and heating appliances, network gear, printers
BLOCKED = ("lock", "cooker", "kettle", "router", "repeater", "printer", "oven", "heater")
KIND = [("airer", "clothes drying rack 晾衣架"), ("light", "light / lamp 灯"), ("fan", "fan 风扇"),
        ("airp", "air purifier 空气净化器"), ("airpurifier", "air purifier 空气净化器"), (".tv.", "TV 电视"),
        ("wifispeaker", "smart speaker 音箱")]


def devices():
    try:
        devs = json.loads(DEVICES.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [d for d in devs if d.get("token") and d.get("localip") and not any(b in (d.get("model") or "") for b in BLOCKED)]


def describe(d):
    kind = next((k for m, k in KIND if m in d["model"]), "device")
    return f'{d["name"]} ({kind}; {"online" if d.get("isOnline") else "offline"})'


def _get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def spec(model):
    cache = {}
    try:
        cache = json.loads(SPEC_CACHE.read_text())
    except Exception:
        pass
    if model not in cache:
        inst = _get("https://miot-spec.org/miot-spec-v2/instances", {"status": "all"})["instances"]
        cands = sorted([i for i in inst if i["model"] == model], key=lambda i: i.get("version", 0), reverse=True)
        cache[model] = _get("https://miot-spec.org/miot-spec-v2/instance", {"type": cands[0]["type"]}) if cands else None
        SPEC_CACHE.write_text(json.dumps(cache))
    return cache[model]


def _find(sp, services, prop):
    for want in services:
        for s in sp.get("services", []):
            if want in s["type"]:
                for p in s.get("properties", []):
                    if f":{prop}:" in p["type"]:
                        return s["iid"], p
    return None


def plan(d, feature, action):
    """-> (siid, piid, value) for this device, or raise ValueError with a reason to tell the user."""
    sp = spec(d["model"])
    if not sp:
        raise ValueError(f'{d["name"]} is an older model I cannot control yet')
    if feature == "rack":
        hit = _find(sp, [":airer:"], "motor-control")
        if not hit:
            raise ValueError(f'{d["name"]} has no up/down control')
        siid, p = hit
        words = {"up": ("up", "rise"), "down": ("down", "descend", "fall"), "stop": ("pause", "stop")}[action]
        for v in p.get("value-list", []):
            if any(w in v["description"].lower() for w in words):
                return siid, p["iid"], v["value"]
        raise ValueError(f'{d["name"]} does not support "{action}"')
    if action not in ("on", "off"):
        raise ValueError(f'"{action}" only works with the drying rack')
    order = [":light:"] if feature == "light" else [":air-purifier:", ":fan:", ":television:", ":light:", ":switch:", ":speaker:"]
    hit = _find(sp, order, "on")
    if not hit:
        raise ValueError(f'{d["name"]} has no {feature} switch')
    return hit[0], hit[1]["iid"], action == "on"


def send(d, siid, piid, value):
    r = rpc(d, "set_properties", [{"did": str(d["did"]), "siid": siid, "piid": piid, "value": value}])
    code = (r or [{}])[0].get("code", -1)
    if code != 0:
        raise ValueError(f'{d["name"]} refused the command (code {code})')
    return True


def read(d, siid, piid):
    r = rpc(d, "get_properties", [{"did": str(d["did"]), "siid": siid, "piid": piid}])
    item = (r or [{}])[0]
    if item.get("code", -1) != 0:
        raise ValueError(f'{d["name"]} could not report its state (code {item.get("code")})')
    return item.get("value")


def rpc(d, method, params):
    """miIO over UDP: hello for the device's clock, then one AES-encrypted request."""
    from Crypto.Cipher import AES
    token = bytes.fromhex(d["token"])
    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    addr = (d["localip"], 54321)
    last = None
    # the first packet after a while often fails with "host is down" until the computer's ARP
    # entry for the device is fresh again, so retry a few times with a short pause
    for i in range(4):
        if i:
            time.sleep(0.8)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2.5)
        try:
            s.sendto(bytes.fromhex("21310020" + "ff" * 28), addr)
            hello = s.recv(1024)
            did, stamp = hello[8:12], struct.unpack(">I", hello[12:16])[0]
            body = json.dumps({"id": int(time.time() * 1000) % 1000000, "method": method,
                               "params": params}).encode()
            pad = 16 - len(body) % 16
            enc = AES.new(key, AES.MODE_CBC, iv).encrypt(body + bytes([pad]) * pad)
            head = struct.pack(">HHI", 0x2131, 32 + len(enc), 0) + did + struct.pack(">I", stamp + 1)
            s.sendto(head + hashlib.md5(head + token + enc).digest() + enc, addr)
            out = AES.new(key, AES.MODE_CBC, iv).decrypt(s.recv(4096)[32:])
            r = json.loads(out[:-out[-1]].rstrip(b"\0").decode())
            if "result" in r:
                return r["result"]
            last = f"device error {r.get('error')}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            print(f"home: try {i + 1} to {d['name']} failed: {last}", flush=True)
        finally:
            s.close()
    raise ValueError(f'{d["name"]} did not respond ({last})')


def control(device, feature, action):
    devs = devices()
    d = next((x for x in devs if x["name"] == device), None) or \
        next((x for x in devs if device.lower() in x["name"].lower()), None)
    if not d:
        return {"ok": False, "error": f"no device called {device}"}
    try:
        if action == "status":
            if feature == "rack":
                return {"ok": False, "error": "the rack position cannot be read"}
            siid, piid, _ = plan(d, feature, "on")
            now = read(d, siid, piid)
            return {"ok": True, "device": d["name"], "feature": feature, "is_on": bool(now)}
        siid, piid, value = plan(d, feature, action)
        send(d, siid, piid, value)
        if feature == "rack":
            return {"ok": True, "device": d["name"], "feature": feature, "action": action}
        # read it back, so Jarvis only says "it's off" when the device really says so
        time.sleep(0.4)
        try:
            now = bool(read(d, siid, piid))
        except Exception:
            return {"ok": True, "device": d["name"], "feature": feature, "action": action, "verified": False}
        if now != bool(value):
            return {"ok": False, "device": d["name"], "error": f"the device accepted the command but its {feature} is still {'on' if now else 'off'}"}
        return {"ok": True, "device": d["name"], "feature": feature, "is_on": now, "verified": True}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool():
    """OpenAI-style tool definition, or None when no devices are connected."""
    devs = devices()
    if not devs:
        return None
    return {"type": "function", "function": {
        "name": "control_home_device",
        "description": "Switch a Mi Home device in the user's home. Devices: " + "; ".join(describe(d) for d in devs)
                       + ". feature 'light' = the device's light (e.g. a drying rack's light), 'power' = the device itself, "
                         "'rack' = raise/lower/stop the drying rack (actions up/down/stop). action 'status' reads whether "
                         "the light/power is on now without changing it.",
        "parameters": {"type": "object", "properties": {
            "device": {"type": "string", "enum": [d["name"] for d in devs]},
            "feature": {"type": "string", "enum": ["light", "power", "rack"]},
            "action": {"type": "string", "enum": ["on", "off", "up", "down", "stop", "status"]}},
            "required": ["device", "feature", "action"]}}}


HINT = (" You can switch the user's Mi Home devices with the control_home_device tool. When asked to turn "
        "something on or off, call it, then confirm in one short sentence, or say plainly why it failed. "
        "Never say a device is on or off from memory: for every request to switch or check a device, call the tool "
        "in this turn (action 'status' to check) and report only what it returned. Locks, cookers, kettles and "
        "routers are deliberately not switchable by voice; say so if asked.")


def provide():
    t = tool()
    return ([(t, control)] if t else []), HINT
