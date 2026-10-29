"""Local Chinese/English speech with a sci-fi treatment, streamed sentence by sentence
so playback starts fast and can be cut off mid-sentence."""
import re
import numpy as np
from scipy.signal import lfilter
from . import models

VOICE = 68          # deep, clear Kokoro male voice; see the listening page for alternatives
SR_OUT = 24000


def sentences(text):
    parts = re.split(r"(?<=[。！？!?；;\n])|(?<=[.](?=\s))|(?<=[，])(?=.{12,})", text)
    return [p.strip() for p in parts if p and p.strip()]


def scifi(x, sr=SR_OUT, amount=1.0):
    """Port of the old Jarvis FFmpeg chain (aecho 20/45/70 ms + bass/treble + band-limit),
    done in numpy so it works on streamed chunks."""
    if amount <= 0:
        return x
    y = x.copy()
    for ms, g in ((20, 0.45), (45, 0.32), (70, 0.12)):
        d = int(sr * ms / 1000)
        y[d:] += amount * g * 0.55 * x[:-d]
    # gentle low shelf (+~4 dB around 110 Hz) and a 90 Hz high-pass, both one-pole
    a_lp = np.exp(-2 * np.pi * 110 / sr)
    y = y + 0.6 * amount * lfilter([1 - a_lp], [1, -a_lp], y)
    a_hp = np.exp(-2 * np.pi * 90 / sr)
    hp = lfilter([a_hp, -a_hp], [1, -a_hp], y)
    peak = np.abs(hp).max() + 1e-6
    return (hp / peak * 0.9).astype(np.float32)


# The old Jarvis release's exact FFmpeg treatment (src/core/voice/jarvis_tts.py)
METALLIC_FILTER = ("aecho=0.8:0.85:20|45|70:0.45|0.32|0.12,"
                   "chorus=0.4:0.6:45:0.2:0.18:1.2,"
                   "bass=g=4:f=110,treble=g=2.5,highpass=f=90,lowpass=f=8500")


def metallic(x, sr):
    """Run the original FFmpeg chain when ffmpeg is installed; numpy approximation otherwise."""
    import shutil, subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg                  # pip-installed ffmpeg, no Homebrew needed
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ff = None
    if not ff:
        return scifi(x, sr)
    p = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
                        "-af", METALLIC_FILTER, "-f", "f32le", "-ac", "1", "pipe:1"],
                       input=np.asarray(x, np.float32).tobytes(), capture_output=True, check=True)
    y = np.frombuffer(p.stdout, np.float32)
    peak = float(np.abs(y).max()) if y.size else 0.0
    return (y * (0.97 / 1.5 / peak) if peak > 1e-6 else y).astype(np.float32)


class PiperSpeaker:
    """The community Piper "jarvis-high" voice (English) with the old metallic treatment."""
    def __init__(self, model_path=None, length_scale=1.05, fx=True):
        from piper import PiperVoice, SynthesisConfig
        path = str(model_path or models.JARVIS_VOICE)
        self.voice = PiperVoice.load(path, config_path=path + ".json")
        self.cfg = SynthesisConfig(length_scale=length_scale)
        self.sr = self.voice.config.sample_rate
        self.fx = fx

    def synth(self, text):
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(SR_OUT, self.sr)
        for s in sentences(text):
            # the English Piper voice reads Chinese characters as "Chinese letter"; drop them
            s = re.sub(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]+", " ", s).strip()
            if not re.search(r"[A-Za-z0-9]", s):
                continue
            chunks = [c.audio_float_array for c in self.voice.synthesize(s, syn_config=self.cfg)]
            if not chunks:
                continue
            x = np.concatenate(chunks).astype(np.float32)
            if self.fx:
                x = metallic(x, self.sr)
            yield resample_poly(x, SR_OUT // g, self.sr // g).astype(np.float32)


def make_speaker():
    return PiperSpeaker() if models.LANG == "en" else Speaker()


class Speaker:
    def __init__(self, voice=VOICE, speed=1.0, fx=1.0, engine=None):
        self.tts = engine or models.tts()
        self.voice, self.speed, self.fx = voice, speed, fx

    def synth(self, text):
        """Yield float32 chunks at 24 kHz, one per sentence."""
        for s in sentences(text):
            a = self.tts.generate(s, sid=self.voice, speed=self.speed)
            yield scifi(np.asarray(a.samples, np.float32), a.sample_rate, self.fx)
