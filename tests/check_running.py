"""After the real app has been started: wait for the voice service, then check its logs.

    python tests/check_running.py SECONDS
Passes when ws://127.0.0.1:8765 answers with a state message and no log under ~/.jarvis has a Traceback."""
import asyncio
import json
import sys
import time
from pathlib import Path

DATA = Path.home() / ".jarvis"


async def probe():
    import websockets
    async with websockets.connect("ws://127.0.0.1:8765", open_timeout=5) as ws:
        for _ in range(20):
            m = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if m.get("type") in ("state", "sys", "llm", "agents", "schedule"):
                return m["type"]
    return None


def logs():
    out = []
    for f in ("voice.log", "app.log"):
        p = DATA / f
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace")
            print(f"----- {p} (last 60 lines)\n" + "\n".join(t.splitlines()[-60:]), flush=True)
            if "Traceback" in t:
                out.append(f)
    return out


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 240
    t0, got, err = time.time(), None, ""
    while time.time() - t0 < limit and not got:
        try:
            got = asyncio.run(probe())
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(5)
    bad = logs()
    print(f"service answered: {got!r} after {time.time() - t0:.0f}s  (last error: {err})")
    if not got or bad:
        sys.exit(f"FAILED: service={'ok' if got else 'no answer'}, tracebacks in {bad}")
    print("OK")


if __name__ == "__main__":
    main()
