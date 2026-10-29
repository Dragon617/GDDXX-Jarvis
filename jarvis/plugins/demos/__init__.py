"""Hologram demos: a Starship flight, a hovering Roadster and an Optimus walk. The shows themselves live in the HUD
(hud/demos/*.js); these modules start, stop and steer them. Real footage for the shows is optional: see scripts/fetch_media.py."""
from . import optimus, roadster, starship

ORDER = (optimus, roadster, starship)          # most specific first: an Optimus question can mention cars


def bind(ctx):
    for m in ORDER:
        m.UI = ctx.ui


def provide():
    return [(m.tool(), m.run) for m in ORDER], "".join(m.HINT for m in ORDER)


def wants(text):
    for m in ORDER:
        if m.wants(text):
            return m.tool()["function"]["name"]
    return None
