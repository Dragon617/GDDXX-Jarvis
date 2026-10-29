"""Live system numbers for the HUD's top bar and for questions like "what's using my CPU?".
Everything is read locally with psutil; nothing leaves this computer."""
import time

try:
    import psutil
except ImportError:          # older installs: the HUD simply keeps its placeholders
    psutil = None

_last = {"t": 0.0, "sent": 0, "recv": 0}


def sample():
    """CPU %, memory %, network up/down in bytes per second, disk free %, battery."""
    if not psutil:
        return None
    now = time.time()
    io = psutil.net_io_counters()
    dt = now - _last["t"] if _last["t"] else 0.0
    up = (io.bytes_sent - _last["sent"]) / dt if dt else 0.0
    down = (io.bytes_recv - _last["recv"]) / dt if dt else 0.0
    _last.update(t=now, sent=io.bytes_sent, recv=io.bytes_recv)
    out = {"cpu": round(psutil.cpu_percent(interval=None)), "mem": round(psutil.virtual_memory().percent),
           "up": max(0, round(up)), "down": max(0, round(down)),
           "disk_free": round(100 - psutil.disk_usage("/").percent)}
    try:
        b = psutil.sensors_battery()
        if b:
            out["battery"], out["charging"] = round(b.percent), bool(b.power_plugged)
    except Exception:
        pass
    return out


def report(top=5):
    """Fuller snapshot for the language model: the numbers plus the busiest apps."""
    if not psutil:
        return {"ok": False, "error": "system monitor not installed"}
    s = sample() or {}
    procs = []
    for p in psutil.process_iter(["name", "memory_percent"]):
        try:
            procs.append((p.cpu_percent(interval=None), p.info["memory_percent"] or 0.0, p.info["name"]))
        except Exception:
            pass
    time.sleep(0.5)            # cpu_percent needs two readings
    busy = []
    for p in psutil.process_iter(["name", "memory_percent"]):
        try:
            busy.append({"app": p.info["name"], "cpu": round(p.cpu_percent(interval=None)),
                         "mem": round(p.info["memory_percent"] or 0.0, 1)})
        except Exception:
            pass
    busy.sort(key=lambda x: (x["cpu"], x["mem"]), reverse=True)
    du = psutil.disk_usage("/")
    s.update(ok=True, disk_free_gb=round(du.free / 1e9, 1), busiest=busy[:top],
             uptime_hours=round((time.time() - psutil.boot_time()) / 3600, 1))
    return s


def tool():
    return {"type": "function", "function": {
        "name": "get_system_status",
        "description": "Read this computer's live status: CPU %, memory %, network speed (bytes/s), free disk, battery, "
                       "uptime and the busiest apps. Use it for any question about the computer's performance.",
        "parameters": {"type": "object", "properties": {}}}}


def provide():
    return [(tool(), lambda **a: report())], ""
