"""Everything the language model can do, gathered in one place.

A tool source is any module with
    provide() -> (list of (openai_tool_schema, function), hint_text)
and optionally
    wants(text) -> tool name    (a request that must really run this tool, not just be talked about)
    bind(ctx)                   (gets the window/voice hooks: ctx.ui, ctx.say_alone, ctx.narrate, ctx.gen)

Built-in sources live in the jarvis package; optional ones in jarvis/plugins (switch them off in config.json
under "plugins"). A new plugin is one file in jarvis/plugins with provide(): see docs/extend.md.
"""
import importlib
import pkgutil
import traceback
from pathlib import Path

from . import config

CORE = ["screen", "sysmon", "schedule", "memory", "voiceprint", "hologram"]
PLUGINS = sorted(m.name for m in pkgutil.iter_modules([str(Path(__file__).parent / "plugins")]))   # every module in plugins/
LAST = "skills"          # learned abilities come last, so a built-in tool always keeps its name

_mods = {}


class Ctx:
    """Hooks the service hands to tool sources."""
    ui = staticmethod(lambda msg: None)               # send a message to the HUD
    say_alone = staticmethod(lambda en, zh="": False)  # speak on Jarvis's own initiative, when nobody is mid-conversation
    narrate = staticmethod(lambda en, zh="": None)     # speak after whatever Jarvis is saying now
    gen = staticmethod(lambda: 0)                      # conversation counter: moves on when the user cuts in


CTX = Ctx()


def _load(name, plugin):
    key = ("plugins." if plugin else "") + name
    if key in _mods:
        return _mods[key]
    try:
        m = importlib.import_module(f".{key}", __package__)
    except Exception as e:
        print(f"tools: {key} not loaded: {type(e).__name__}: {e}", flush=True)
        m = None
    if m is not None and hasattr(m, "bind"):
        try:
            m.bind(CTX)
        except Exception:
            traceback.print_exc()
    _mods[key] = m
    return m


def sources():
    out = [_load(n, False) for n in CORE]
    out += [_load(n, True) for n in PLUGINS if config.plugin_on(n)]
    out.append(_load(LAST, False))
    return [m for m in out if m is not None and hasattr(m, "provide")]


def plugin(name):
    """An optional plugin module, or None when it is switched off or cannot load (e.g. a missing package)."""
    return _load(name, True) if config.plugin_on(name) else None


def bind(**hooks):
    for k, v in hooks.items():
        setattr(CTX, k, staticmethod(v))
    for m in list(_mods.values()):
        if m is not None and hasattr(m, "bind"):
            m.bind(CTX)


def collect(text=""):
    """(schemas, {name: function}, hints, forced tool name or None) for one reply."""
    schemas, run, hints, force = [], {}, [], None
    for m in sources():
        try:
            pairs, hint = m.provide()
        except Exception as e:
            print(f"tools: {m.__name__}.provide failed: {type(e).__name__}: {e}", flush=True)
            continue
        for schema, fn in pairs:
            if schema and schema["function"]["name"] not in run:
                schemas.append(schema)
                run[schema["function"]["name"]] = fn
        if hint and pairs:
            hints.append(hint)
        if force is None and text and hasattr(m, "wants"):
            try:
                w = m.wants(text)
            except Exception:
                w = None
            if w and w in run:
                force = w
    return schemas, run, "".join(hints), force


def names():
    return set(collect()[1])
