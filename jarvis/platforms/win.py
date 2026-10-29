"""Windows: OpenCV (DirectShow) camera, MediaPipe hands, RapidOCR text, a Startup-folder shortcut for login."""
import os
import subprocess
from pathlib import Path

from .generic import open_path, open_camera, hand_detector, ocr        # noqa: F401

NAME = "PC"


def _startup_link():
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.lnk"


def autostart(on=True):
    link = _startup_link()
    if not on:
        link.unlink(missing_ok=True)
        return {"ok": True, "on": False}
    app = Path(os.environ.get("LOCALAPPDATA", "")) / "Jarvis"            # where the installer puts Jarvis
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:L); $s.TargetPath=$env:T; $s.Arguments=$env:A; "
          "$s.WorkingDirectory=$env:W; $s.IconLocation=$env:I; $s.Save()")
    env = {**os.environ, "L": str(link), "T": str(app / "python" / "pythonw.exe"), "A": f'"{app / "app" / "launch.py"}"',
           "W": str(app), "I": str(app / "jarvis.ico")}
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
    return {"ok": r.returncode == 0, "on": True, "error": r.stderr[-300:] if r.returncode else ""}
