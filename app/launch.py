"""What the Jarvis icon runs (macOS app and Windows shortcut alike), with the Python that ships with Jarvis.
First run, or after an update: set up (app/install.py). Then open the window, inside Jarvis's own environment."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import install  # noqa: E402

if not install.installed() and not install.run():
    sys.exit(1)
py = str(install.venv_python())
if os.name == "nt":
    py = py.replace("python.exe", "pythonw.exe")          # no console window
args = [py, str(ROOT / "app" / "window.py")]
if os.name == "nt":
    subprocess.Popen(args, close_fds=True)
else:
    os.execv(py, args)
