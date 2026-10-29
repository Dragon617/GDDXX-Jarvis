"""Optimus walking hologram: why a biped is harder than a car, as a particle show.
The show lives in the HUD (hud/optimus.js); this module only starts, stops and steers it.
On-screen numbers are tagged 报道 or 估算. Do not invent unpublished mass, torque or fall rates."""
import re, time

UI = None
STAGES = {
    "bot": ["慢走", "整机", "步态", "走路演示"],
    "car_vs_bot": ["对比汽车", "车和人", "车与人", "支撑多边形", "多边形"],
    "pendulum": ["倒立摆", "投影", "质心"],
    "zmp": ["零力矩", "zmp", "脚底", "足底", "翻边", "压力中心"],
    "capture": ["捕获点", "落脚", "接住", "摔倒"],
    "stack": ["三层", "伺服", "延迟", "规划层"],
    "hard": ["复刻", "账单", "有多难", "未公开", "力学"],
}
ON = {"at": 0}


def _stage(text):
    t = (text or "").lower()
    for k, words in STAGES.items():
        if any(w in t for w in words):
            return k
    return None


def _latest():
    from . import roadster, starship
    return ON["at"] > 0 and ON["at"] >= roadster.ON["at"] and ON["at"] >= starship.ON["at"]


def wants(text):
    """True when the user is asking for the Optimus walk show, or steering it while it is the show on screen."""
    t = (text or "").lower()
    name = re.search(r"optimus|人形机器人|双足|人形", t)
    walk = re.search(r"走路|行走|步态", t)
    show = re.search(r"演示|全息|播放|看看|展示|拆解|原理|讲讲|放一下|打开|show|demo|play", t)
    topic = re.search(r"捕获点|倒立摆|零力矩|zmp|支撑多边形|复刻有多难|走路比开车|对比汽车", t)
    if topic:
        return True
    if name and (show or walk):
        return True
    if walk and show and re.search(r"机器人|optimus|人形|贾维斯", t):
        return True
    if _latest() and re.search(r"暂停|继续|停一下|收起|关掉|跳到|回到|重新播放|再放一遍|下一场|上一场|pause|resume|replay", t):
        return True
    return False


def run(action="play", stage="", **_):
    action = (action or "play").lower()
    msg = {"type": "optimus", "action": action}
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
    notes = {"play": "The Optimus walk hologram is running: about 90 seconds, seven scenes. Numbers on screen are tagged 报道 or 估算. "
                     "It is silent by design: reply with ONE short sentence only, e.g. 'Optimus, from the support polygon to the capture point.' "
                     "Do not narrate the scenes, and do not state mass, torque or fall rate as if they were published.",
             "replay": "running it again from the top; one short sentence only",
             "stage": f"jumping to the '{msg.get('stage')}' scene; one short sentence only",
             "pause": "paused", "resume": "resumed", "hide": "folded away"}
    return {"ok": True, "doing": notes.get(action, action)}


def tool():
    return {"type": "function", "function": {
        "name": "show_optimus_walk",
        "description": "Play the Optimus walking hologram: a particle humanoid, car-versus-biped support polygons, the linear inverted pendulum, "
                       "ZMP on the sole, capture-point foot placement (miss versus catch), the plan/estimate/servo stack, and the rebuild bill. "
                       "Use it when the user asks to show Optimus walking, why walking is harder than driving, the capture point, ZMP, or how hard the Jarvis rebuild is "
                       "(Optimus 走路, 演示人形, 捕获点, 倒立摆, 对比汽车, 复刻有多难). "
                       "action 'play' starts it; 'stage' jumps to bot, car_vs_bot, pendulum, zmp, capture, stack or hard; 'pause', 'resume', 'replay', 'hide'.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["play", "stage", "pause", "resume", "replay", "hide"]},
            "stage": {"type": "string", "description": "for 'stage': one of " + ", ".join(STAGES)}}}}}


HINT = (" For the Optimus walking demonstration (why a biped is harder than a car) call show_optimus_walk. The show is silent and labelled on "
        "screen, including which numbers are reported and which are estimates. After it starts say one short sentence and stop; do not narrate it, "
        "and do not invent unpublished mass, torque, control rate or fall statistics. Never claim it is on screen unless the tool ran this turn and returned ok.")
