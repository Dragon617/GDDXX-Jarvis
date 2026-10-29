"""English version: run the voice engine over simulated microphone audio and check every scenario.

Microphone = my speech + other people/TV + room noise + Jarvis's own voice leaking
back after echo cancellation (residual gain ECHO).
"""
import os, sys, time, numpy as np, soundfile as sf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis import models
from jarvis.engine import VoiceEngine

SR = 16000
CL = Path(os.environ.get("JARVIS_TEST_CLIPS", Path(__file__).parent / "clips_en"))
clip = lambda k: sf.read(CL / f"{k}.wav", dtype="float32")[0]
import os
rng = np.random.default_rng(int(os.environ.get("SEED", 0)))
MODE = sys.argv[1] if len(sys.argv) > 1 else "0.12"
USE_AEC = MODE == "aec"
ECHO = 0.0 if USE_AEC else float(MODE)
IR = np.zeros(1600, np.float32); IR[480] = 0.7   # 30 ms speaker->mic delay, loud laptop speaker
IR[480:] += np.random.default_rng(9).normal(0, 1, 1120).astype(np.float32) * np.exp(-np.arange(1120) / 250) * 0.1

ASR = models.Transcriber("en", 4)
REPLY_TEXT = ("Good morning, sir. You have twelve tasks today and nine are already complete. The stand-up and the design review "
              "are behind you. This afternoon you have the development sprint, the project retrospective, and the documentation. "
              "I would suggest starting with the sprint, as it should take about two hours.")


def run(name, events, total, expect, reply_after_command=False, echo=ECHO):
    user = np.zeros(int(total * SR), np.float32)
    for t0, k, gain in events:
        x = clip(k) * gain
        i = int(t0 * SR); user[i:i + len(x)] += x[: len(user) - i]
    noise = rng.normal(0, 0.004, len(user)).astype(np.float32)
    got, play = [], {"pos": None, "x": None, "said": ""}

    def start(k, said):          # like service.say(): the engine knows Jarvis is talking
        play.update(pos=0, x=clip(k), said=said); eng.set_speaking(True)
        if USE_AEC:
            play["room"] = np.convolve(play["x"], IR)[: len(play["x"])].astype(np.float32)

    def on(name_, data):
        if name_ == "heard":
            return
        got.append((name_, data.get("text", data.get("keyword", data.get("dbg") or ""))))
        if name_ == "ack":
            start("ack", "Yes, sir?")
        if name_ == "command":
            play["pos"] = None
            if reply_after_command:
                start("reply", REPLY_TEXT)
        if name_ in ("barge_in", "stop"):
            play["pos"] = None; eng.set_speaking(False)

    eng = VoiceEngine(on, wake=models.wake("en"), vad=models.vad(), asr=ASR)
    if USE_AEC:
        from jarvis.aec import EchoCanceller
        aec = EchoCanceller(noise_suppression=os.environ.get('NS', '1') == '1')
    t_start = time.time()
    for i in range(0, len(user), 512):
        fr = user[i:i + 512] + noise[i:i + 512]
        if play["pos"] is not None:
            seg = play["x"][play["pos"]:play["pos"] + len(fr)]
            if len(seg) < len(fr):
                play["pos"] = None; eng.set_speaking(False, said=play["said"]); eng.set_playback_level(0)
                if USE_AEC: aec.playback(np.zeros(len(fr), np.float32))
            else:
                if USE_AEC:
                    aec.playback(seg); fr = fr + play["room"][play["pos"]:play["pos"] + len(fr)]
                else:
                    fr = fr + echo * seg
                play["pos"] += len(fr)
                eng.set_playback_level(0.0 if USE_AEC else float(np.sqrt(np.mean(seg ** 2))))
        elif USE_AEC:
            aec.playback(np.zeros(len(fr), np.float32))
        eng.feed(aec.capture(fr) if USE_AEC else fr)
    eng.feed(np.zeros(SR, np.float32))
    names = [g[0] for g in got]
    ok = expect(got)
    rt = (time.time() - t_start) / (total + 1)
    print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {got}   (x{rt:.2f} realtime)")
    return ok


def has(got, *seq):
    names = [g[0] for g in got]
    it = iter(names); return all(s in it for s in seq)

cmd = lambda got: [t for n, t in got if n == "command"]
low = lambda g: [c.lower() for c in cmd(g)]
names = lambda g: [x[0] for x in g]
R = []
R.append(run("1 wake + command in one breath", [(1.0, "wake_cmd", 1)], 6, lambda g: len(cmd(g)) == 1 and "weather" in low(g)[0] and "jarvis" not in low(g)[0]))
R.append(run("2 my normal talk is ignored", [(0.5, "chat", 1)], 6, lambda g: g == []))
R.append(run("3 TV in the room is ignored", [(0.5, "tv", 0.6)], 8, lambda g: g == []))
R.append(run("4 someone says Travis -> ignored", [(0.5, "other", 0.8)], 6, lambda g: g == []))
R.append(run("5 wake, pause, then command", [(0.5, "wake_only", 1), (3.0, "cmd_after", 1)], 7,
             lambda g: has(g, "wake", "ack", "command") and "schedule" in low(g)[-1]))
R.append(run("6 wake over TV + chatter", [(0.3, "tv", 0.35), (2.0, "wake_cmd2", 1)], 9, lambda g: len(cmd(g)) == 1 and "work progress" in low(g)[0]))
R.append(run("7 command after wake times out", [(0.5, "wake_only", 1)], 14, lambda g: has(g, "ack", "timeout")))
R.append(run("8 Jarvis speaking, no one interrupts", [(0.5, "wake_cmd", 1)], 26,
             lambda g: len(cmd(g)) == 1 and "barge_in" not in names(g) and "ack" not in names(g), reply_after_command=True))
R.append(run("9 interrupt with 'Stop.'", [(0.5, "wake_cmd", 1), (8.0, "stop", 1)], 14,
             lambda g: has(g, "command", "barge_in", "stop"), reply_after_command=True))
R.append(run("10 interrupt with a new request", [(0.5, "wake_cmd", 1), (8.0, "new_cmd", 1)], 16,
             lambda g: has(g, "command", "barge_in", "command") and "alarm" in low(g)[-1], reply_after_command=True))
R.append(run("11 interrupt with Hey Jarvis + request", [(0.5, "wake_cmd", 1), (8.0, "wake_cmd2", 1)], 16,
             lambda g: has(g, "command", "barge_in", "command") and "work progress" in low(g)[-1] and "jarvis" not in low(g)[-1], reply_after_command=True))
R.append(run("13 wake, ack, then command after ack", [(0.5, "wake_only", 1), (4.5, "early_cmd", 1)], 10,
             lambda g: has(g, "wake", "ack", "command") and "rack" in low(g)[-1] and "barge_in" not in names(g)))
R.append(run("14 interrupt the ack with the request", [(0.5, "wake_only", 1), (2.3, "early_cmd", 1)], 9,
             lambda g: has(g, "ack", "command") and "rack" in low(g)[-1]))
R.append(run("15 follow-up after reply, no wake word", [(0.5, "wake_cmd", 1), (25.5, "follow", 1)], 34,
             lambda g: len(cmd(g)) == 2 and "what about" in low(g)[-1], reply_after_command=True))
R.append(run("16 reply ends, silence -> back to standby", [(0.5, "wake_cmd", 1)], 36,
             lambda g: len(cmd(g)) == 1 and names(g)[-1] == "timeout", reply_after_command=True))
R.append(run("17 'thanks' after reply ends the chat", [(0.5, "wake_cmd", 1), (25.5, "stop", 1), (28.0, "chat", 1)], 34,
             lambda g: len(cmd(g)) == 1 and "stop" in names(g), reply_after_command=True))
R.append(run("18 wake, then Chinese command", [(0.5, "wake_only", 1), (4.5, "zh_cmd", 1)], 10,
             lambda g: has(g, "ack", "command") and cmd(g)[-1] == "把晾衣架的灯关了"))
R.append(run("19 Chinese follow-up after reply", [(0.5, "wake_cmd", 1), (25.5, "zh_follow", 1)], 34,
             lambda g: len(cmd(g)) == 2 and "后天" in cmd(g)[-1], reply_after_command=True))
R.append(run("20 Hey Jarvis + Chinese in one breath", [(0.5, "zh_wake_cmd", 1)], 8,
             lambda g: len(cmd(g)) == 1 and cmd(g)[0].startswith("把台灯")))
R.append(run("21 interrupt reply in Chinese", [(0.5, "wake_cmd", 1), (8.0, "zh_new_cmd", 1)], 16,
             lambda g: has(g, "command", "barge_in", "command") and "闹钟" in cmd(g)[-1], reply_after_command=True))
R.append(run("22 Chinese TV in standby ignored", [(0.5, "zh_tv", 0.6)], 8, lambda g: g == []))
R.append(run("23 Chinese chatter in standby ignored", [(0.5, "zh_chat", 1)], 6, lambda g: g == []))
R.append(run("12 talking ABOUT Jarvis is ignored", [(0.5, "mention", 0.9)], 6, lambda g: "command" not in names(g)))
print(f"\n{sum(R)}/{len(R)} passed ({'real echo + WebRTC AEC' if USE_AEC else f'echo residual {ECHO}'})")
