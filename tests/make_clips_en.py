"""English test speech: my voice and other people from Kokoro, Jarvis from Piper + metallic FX."""
import sys, os, numpy as np, soundfile as sf
from pathlib import Path
from scipy.signal import resample_poly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis import models
from jarvis.tts import PiperSpeaker
OUT = Path(__file__).parent / "clips_en"; OUT.mkdir(exist_ok=True)
ME, OTHER, TV = 68, 0, 1
CLIPS = {
  "wake_cmd":  (ME, "Hey Jarvis, what's the weather in Shanghai tomorrow?"),
  "chat":      (ME, "I'm going downstairs to pick up a package, back in five minutes."),
  "tv":        (TV, "Tonight's top story. Markets rallied as investors reacted to the latest economic data."),
  "other":     (OTHER, "Did you see Travis at the meeting yesterday? He looked really tired."),
  "mention":   (OTHER, "I think Jarvis is a great name for an assistant."),
  "wake_only": (ME, "Hey Jarvis."),
  "cmd_after": (ME, "Show me today's schedule."),
  "wake_cmd2": (ME, "Hey Jarvis, summarize my work progress for today."),
  "stop":      (ME, "Stop."),
  "new_cmd":   (ME, "Actually, set an alarm for eight tomorrow morning."),
}
REPLY = ("Good morning, sir. You have twelve tasks today and nine are already complete. The stand-up and the design review "
         "are behind you. This afternoon you have the development sprint, the project retrospective, and the documentation. "
         "I would suggest starting with the sprint, as it should take about two hours.")
tts = models.tts(threads=4)
for k, (sid, text) in CLIPS.items():
    a = tts.generate(text, sid=sid, speed=1.0)
    x = resample_poly(np.array(a.samples, np.float32), 2, 3).astype(np.float32)
    sf.write(OUT / f"{k}.wav", x / (np.abs(x).max() + 1e-6) * 0.5, 16000); print(k, round(len(x) / 16000, 1))
sp = PiperSpeaker(os.environ.get("JARVIS_VOICE_MODEL"))
x = np.concatenate(list(sp.synth(REPLY)))
x = resample_poly(x, 2, 3).astype(np.float32)
sf.write(OUT / "reply.wav", x / (np.abs(x).max() + 1e-6) * 0.5, 16000); print("reply", round(len(x) / 16000, 1))
