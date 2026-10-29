"""Tesla Roadster hover hologram: how the new Roadster sticks upside down (fan suction), flies on 10 cold-air thrusters,
and lands with a suicide burn - then the same rig on a Model Y. The show lives in the HUD (hud/roadster.js);
this module only starts, stops and steers it."""
import re, time

UI = None
STAGES = {   # HUD stage keys and the words people use for them
    "car": ["整车", "外观", "车身", "overview"],
    "suction": ["倒挂", "吸附", "风扇", "负压", "按在墙上", "suction", "upside"],
    "thrust": ["喷口", "推进器", "十个", "10个", "气瓶", "thruster"],
    "nozzle": ["喷管", "超音速", "白雾", "结霜", "nozzle"],
    "compare": ["两种落法", "落地", "对比", "自杀式", "点火", "compare", "suicide"],
    "modely": ["model y", "modely", "我们的车", "我们自己的车", "国产", "毛豆"],
    "bill": ["账单", "代价", "现实", "能量", "充气", "bill"],
}
ON = {"at": 0}


def _stage(text):
    t = (text or "").lower()
    for k, words in STAGES.items():
        if any(w in t for w in words):
            return k
    return None


def wants(text):
    """True when the user is plainly asking for the Roadster show (or steering it while it plays)."""
    t = (text or "").lower()
    car = re.search(r"roadster|特斯拉|飞行汽车|飞车|会飞的车|悬停|倒挂|model ?y|跑车", t)
    show = re.search(r"演示|全息|播放|看看|展示|拆解|怎么飞|飞起来|原理|讲讲|放一下|打开|show|demo|play", t)
    if car and show:
        return True
    live = time.time() - ON["at"] < 120
    return bool(live and re.search(r"暂停|继续|停一下|收起|关掉|跳到|回到|重新播放|再放一遍|pause|resume|replay|skip", t))


def run(action="play", stage="", **_):
    action = (action or "play").lower()
    msg = {"type": "roadster", "action": action}
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
    notes = {"play": "The Roadster hologram is running now: about 90 seconds, seven scenes, every number labelled on screen. "
                     "It is silent by design: reply with ONE short sentence only, e.g. 'The Roadster, upside down to touchdown.' "
                     "Do not narrate the scenes.",
             "replay": "running it again from the top; one short sentence only",
             "stage": f"jumping to the '{msg.get('stage')}' scene; one short sentence only",
             "pause": "paused", "resume": "resumed", "hide": "folded away"}
    return {"ok": True, "doing": notes.get(action, action)}


def tool():
    return {"type": "function", "function": {
        "name": "show_roadster_hover",
        "description": "Play the new Tesla Roadster as a 3D particle hologram: how it hangs upside down on a wall (underbody fans pull a "
                       "low-pressure seal, 4,700 kg downforce), its 10 cold-air thrusters fed by 600 L carbon tanks at 380 bar, the supersonic "
                       "nozzle and frost, a gentle descent vs a suicide burn from 10 m, then the same rig on a Tesla Model Y, and the real-world bill. "
                       "Use it whenever the user asks to show, demonstrate or explain the flying / hovering Tesla Roadster, the flying car, "
                       "or whether our own car (Model Y) could fly (特斯拉飞车, Roadster 悬停, 倒挂, 飞行汽车, 我们的车能不能飞). "
                       "action 'play' (default) starts it; 'stage' with stage jumps to one scene (倒挂, 喷口, 喷管, 两种落法, Model Y, 账单); "
                       "'pause', 'resume', 'replay', 'hide' (收起).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["play", "stage", "pause", "resume", "replay", "hide"]},
            "stage": {"type": "string", "description": "for 'stage': one of " + ", ".join(STAGES)}}}}}


HINT = (" For the flying / hovering Tesla Roadster demonstration (or 'can our Model Y fly') call show_roadster_hover. The show is "
        "silent and fully labelled on screen, so after it starts say one short sentence and stop; do not narrate it. Never claim it "
        "is on screen unless the tool ran this turn and returned ok.")
