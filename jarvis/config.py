"""The user's settings, in ~/.jarvis/config.json. This file holds API keys, so it stays on this computer:
it is written readable by the current user only, and nothing in Jarvis ever uploads or logs it.

  {
    "name": "sir",                       how Jarvis addresses the user
    "reply_lang": "en",                  en = English voice with a Chinese subtitle (default) · zh = Chinese
    "llm":   {"provider": "deepseek", "base_url": "...", "api_key": "...", "model": "..."},
    "amap":  {"key": "..."},             optional: weather and routes in China (plugin amap)
    "harness": {"path": "..."},          optional: DeepSeek Harness command-line path (plugin harness)
    "plugins": {"mihome": true, ...},    optional: switch plugins off
    "workspace": "~/Desktop/Jarvis 作品"
  }
Environment variables JARVIS_LLM_BASE_URL / JARVIS_LLM_API_KEY / JARVIS_LLM_MODEL override the llm block.
"""
import json
import os
import threading

from .paths import CONFIG, IS_WIN

_lock = threading.Lock()


def load():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get(key, default=None):
    return load().get(key, default)


def section(name):
    v = load().get(name)
    return v if isinstance(v, dict) else {}


def update(**changes):
    """Merge top-level keys into the config and save it, private to this user."""
    with _lock:
        cfg = load()
        for k, v in changes.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        _private(tmp)
        os.replace(tmp, CONFIG)
        _private(CONFIG)
        return cfg


def _private(p):
    if IS_WIN:
        try:                                     # only the current user may read it
            import subprocess
            user = os.environ.get("USERNAME", "")
            if user:
                subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:(F)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass
    else:
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass


def llm():
    """(base_url, api_key, model) of the language model, or (None, '', '') when none is set up yet."""
    c = section("llm")
    return (os.environ.get("JARVIS_LLM_BASE_URL") or c.get("base_url"),
            os.environ.get("JARVIS_LLM_API_KEY") or c.get("api_key", ""),
            os.environ.get("JARVIS_LLM_MODEL") or c.get("model", ""))


def plugin_on(name, default=True):
    return bool(section("plugins").get(name, default))


def user_name():
    return (get("name") or "sir").strip() or "sir"
