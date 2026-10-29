"""Starship launch hologram: the whole flight of SpaceX's Starship V3, from ignition to both stages caught by the
tower, as a silent particle hologram with labelled callouts. The show itself lives in the HUD (hud/starship.js);
this module only starts, stops and steers it."""
import re, time

UI = None
STAGES = {   # HUD stage keys and the words people use for them
    "stack": ["全箭", "整体", "overview", "stack"],
    "inside": ["内部", "结构", "油箱", "inside", "tank"],
    "ignite": ["点火", "ignit"],
    "ascent": ["升空", "起飞", "爬升", "liftoff", "ascent", "max q", "最大动压"],
    "stage": ["分离", "热分离", "stag"],
    "booster": ["助推器", "一级", "回收助推", "booster", "boostback"],
    "orbit": ["入轨", "轨道", "orbit"],
    "deploy": ["星链", "卫星", "部署", "starlink", "deploy"],
    "reentry": ["再入", "隔热", "reentry", "re-entry", "heat shield"],
    "flop": ["俯冲", "腹部", "belly"],
    "catch": ["接住", "飞船回收", "筷子", "catch", "chopstick"],
    "reuse": ["复用", "reuse"],
}
ON = {"at": 0}


def _stage(text):
    t = (text or "").lower()
    for k, words in STAGES.items():
        if any(w in t for w in words):
            return k
    return None


def wants(text):
    """True when the user is plainly asking for the launch show (or steering it while it plays)."""
    t = (text or "").lower()
    rocket = re.search(r"星舰|starship|spacex|火箭|super heavy|超重型", t)
    show = re.search(r"发射|升空|回收|演示|拆解|全过程|流程|launch|flight|全息|播放|看看", t)
    if rocket and show:
        return True
    live = time.time() - ON["at"] < 200
    return bool(live and re.search(r"暂停|继续|停一下|收起|关掉|跳到|回到|重新播放|再放一遍|pause|resume|replay|skip", t))


def run(action="play", stage="", **_):
    action = (action or "play").lower()
    msg = {"type": "starship", "action": action}
    if action == "stage":
        key = stage if stage in STAGES else _stage(stage)
        if not key:
            return {"ok": False, "error": "unknown stage", "stages": list(STAGES)}
        msg["stage"] = key
    if UI:
        UI(msg)
    if action in ("play", "replay", "stage", "resume"):
        ON["at"] = time.time()
    elif action == "hide":
        ON["at"] = 0
    notes = {"play": "The launch hologram is running now: about two minutes, twelve stages, every step labelled on screen. "
                     "It is silent by design: reply with ONE short sentence only, e.g. 'Starship, from ignition to the catch.' "
                     "Do not narrate the stages.",
             "replay": "running it again from the top; one short sentence only",
             "stage": f"jumping to the '{msg.get('stage')}' stage; one short sentence only",
             "pause": "paused", "resume": "resumed", "hide": "folded away"}
    return {"ok": True, "doing": notes.get(action, action)}


def tool():
    return {"type": "function", "function": {
        "name": "show_launch_sequence",
        "description": "Play SpaceX's latest rocket, Starship V3, as a 3D particle hologram of a whole flight: on the pad, its insides, "
                       "ignition of 33 Raptor engines, liftoff, Max-Q, hot staging, the booster flying back and being caught by the tower, "
                       "the ship reaching orbit and deploying Starlink satellites, reentry, belly flop, flip and the tower catch, full reuse. "
                       "Use it whenever the user asks to show, demonstrate, break down or play a SpaceX / Starship / rocket launch "
                       "(星舰, SpaceX 火箭发射, 发射全过程, 从升空到回收). action 'play' (default) starts it; 'stage' with stage jumps to one part "
                       "(e.g. 热分离, 助推器回收, 再入, 接住); 'pause', 'resume', 'replay', 'hide' (收起).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["play", "stage", "pause", "resume", "replay", "hide"]},
            "stage": {"type": "string", "description": "for 'stage': one of " + ", ".join(STAGES)}}}}}


HINT = (" For a SpaceX / Starship launch demonstration call show_launch_sequence. The show is silent and fully labelled on "
        "screen, so after it starts say one short sentence and stop; do not narrate it. Never claim it is on screen unless the "
        "tool ran this turn and returned ok. Speak as if projecting it from your own archives.")
