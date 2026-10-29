"""The Jarvis window: the HUD in a native web view (WebKit on macOS, WebView2 on Windows).
The voice service runs as a child process only while this window is open."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis import paths  # noqa: E402

import webview  # noqa: E402

LOG = paths.DATA / "voice.log"


def start_service():
    paths.DATA.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 5_000_000:      # keep the log small: start a fresh one
        LOG.replace(LOG.with_suffix(".log.old"))
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if paths.IS_MAC and ".app/Contents/" in str(ROOT):
        env["JARVIS_APP_BUNDLE"] = str(ROOT).split(".app/Contents/")[0] + ".app"
    flags = subprocess.CREATE_NO_WINDOW if paths.IS_WIN else 0
    exe = sys.executable.replace("pythonw.exe", "python.exe")
    return subprocess.Popen([exe, "-m", "jarvis"], cwd=str(ROOT), env=env, stdout=open(LOG, "a", encoding="utf-8"),
                            stderr=subprocess.STDOUT, creationflags=flags)


def stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    svc = start_service()
    try:
        webview.create_window("Jarvis", str(ROOT / "hud" / "index.html"), width=1440, height=900,
                              min_size=(1100, 700), background_color="#000000")
        # private_mode: no disk cache, so an updated HUD shows on the next launch
        webview.start(http_server=True, private_mode=True)
    finally:
        stop(svc)


if __name__ == "__main__":
    main()
