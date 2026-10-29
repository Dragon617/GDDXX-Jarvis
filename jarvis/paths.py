"""Where Jarvis keeps things, the same way on macOS, Windows and Linux.

  DATA   ~/.jarvis (or JARVIS_HOME): the user's own files. Config and keys, memory, schedule, voiceprint, skills, logs.
         Never shipped, never uploaded.
  APP    the installed runtime: Python venv and the speech models.
         macOS ~/Library/Application Support/Jarvis · Windows %LOCALAPPDATA%\\Jarvis · Linux ~/.local/share/jarvis
  WORK   the folder where Jarvis's helpers save what they make (Desktop/Jarvis 作品 unless config says otherwise)
"""
import os
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

HOME = Path.home()
DATA = Path(os.environ.get("JARVIS_HOME", HOME / ".jarvis"))


def _app_dir():
    if os.environ.get("JARVIS_APP_DIR"):
        return Path(os.environ["JARVIS_APP_DIR"])
    if IS_MAC:
        return HOME / "Library" / "Application Support" / "Jarvis"
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "Jarvis"
    return Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "jarvis"


APP = _app_dir()
MODELS = Path(os.environ.get("JARVIS_VOICE_MODELS", APP / "models"))
DESKTOP = HOME / "Desktop"

CONFIG = Path(os.environ.get("JARVIS_CONFIG", DATA / "config.json"))
MEMORY = Path(os.environ.get("JARVIS_MEMORY", DATA / "memory"))
SKILLS = DATA / "skills"
SKILLS_TRIAL = DATA / "lab" / "skills-trial"
SKILLS_ARCHIVE = DATA / "skills-archive"
LAB = DATA / "lab"
HOLO = DATA / "holo"
SCHEDULE = DATA / "schedule"
CLIPS = DATA / "clips"


def workspace():
    """Where helper agents save what they make."""
    from . import config
    w = config.get("workspace")
    return Path(w).expanduser() if w else DESKTOP / "Jarvis 作品"


def ensure():
    DATA.mkdir(parents=True, exist_ok=True)
    return DATA
