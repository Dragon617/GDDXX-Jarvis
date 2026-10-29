"""set_screen: standby (black starfield, only the core) or awake (all panels)."""
UI = None


def bind(ctx):
    global UI
    UI = ctx.ui


def set_screen(mode="standby"):
    if not UI:
        return {"ok": False, "error": "no window connected"}
    mode = "awake" if mode == "awake" else "standby"
    UI({"type": "screen", "mode": mode})
    return {"ok": True, "mode": mode, "note": "the screen changes right after you finish speaking"}


TOOL = {"type": "function", "function": {
    "name": "set_screen",
    "description": "Switch the Jarvis window: 'standby' = black starfield with only the particle core (panels hidden), "
                   "'awake' = show all panels. Use when the user asks for standby / 待机 / sleep screen, or to show the panels.",
    "parameters": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["standby", "awake"]}}, "required": ["mode"]}}}


def provide():
    return [(TOOL, set_screen)], ""
