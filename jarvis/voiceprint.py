"""Speaker verification: Jarvis answers only the user's voice.

The user reads a few lines once (enrolment); each line becomes a 192-number voiceprint from a CAM++ model
(3D-Speaker, Chinese + English, run by sherpa-onnx). From then on every wake and every command is compared with
that voiceprint; a voice that does not match (a video, music, another person, Jarvis's own echo) is ignored.

  ~/.jarvis/models/speaker/<model>.onnx     the model
  ~/.jarvis/voiceprint.json                 the user's voiceprint and the threshold (delete it to start over)

Every decision is logged ("voiceprint: 0.71 / 0.42 -> yes, command") so the threshold can be tuned from real use."""
import json, os, threading, time
from pathlib import Path
import numpy as np

from .paths import DATA, MODELS
_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL = Path(os.environ.get("JARVIS_SPEAKER_MODEL", MODELS / "speaker" / _NAME))
if not MODEL.exists() and (DATA / "models" / "speaker" / _NAME).exists():
    MODEL = DATA / "models" / "speaker" / _NAME          # where 0.x versions kept it
PROFILE = DATA / "voiceprint.json"
SR = 16000
MIN_SECONDS = 0.8          # shorter than this, a voiceprint is not reliable: undecided
LINES = [                  # what the user reads at enrolment: both languages, varied sounds
    "嘿贾维斯，帮我看看今天有什么安排。",
    "Hey Jarvis, what's the weather like tomorrow morning?",
    "把客厅的灯打开，再把空调调到二十六度。",
    "Jarvis, take the Raptor engine apart and show me how it works.",
    "我刚才说的那件事，你帮我记一下，明天提醒我。",
    "Thanks Jarvis, that's all for now.",
]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Voiceprint:
    def __init__(self):
        self.ex, self.lock = None, threading.Lock()
        self.profile = None
        self.enrolling, self.enrolled = False, []
        self.on = True
        self.load()

    # -- model -----------------------------------------------------------------------------------------------------
    def available(self):
        return MODEL.exists()

    def _extractor(self):
        if self.ex is None:
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=1, provider="cpu")
            self.ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        return self.ex

    def embed(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if len(samples) < MIN_SECONDS * SR or not self.available():
            return None
        with self.lock:
            ex = self._extractor()
            st = ex.create_stream()
            st.accept_waveform(sample_rate=SR, waveform=samples)
            st.input_finished()
            if not ex.is_ready(st):
                return None
            v = np.asarray(ex.compute(st), dtype=np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else None

    # -- the user's voiceprint -----------------------------------------------------------------------------------
    def load(self):
        try:
            p = json.loads(PROFILE.read_text())
            p["mean"] = np.asarray(p["mean"], np.float32)
            p["each"] = [np.asarray(e, np.float32) for e in p["each"]]
            if not p.get("claude_fix"):        # claude-vp-floor: one-time, see the comment in apply.py
                p["threshold"] = min(float(p.get("threshold", 0.55)), 0.40); p["claude_fix"] = "2026-10-22"
                self.profile = p; self.on = p.get("on", True)
                try:
                    self.save()
                except Exception:
                    pass
            self.profile = p
            self.on = p.get("on", True)
        except Exception:
            self.profile = None

    def save(self):
        p = dict(self.profile)
        p["mean"] = [round(float(x), 6) for x in p["mean"]]
        p["each"] = [[round(float(x), 6) for x in e] for e in p["each"]]
        p["on"] = self.on
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE.write_text(json.dumps(p, ensure_ascii=False))

    def ready(self):
        return bool(self.profile) and self.on and self.available()

    def score(self, v):
        """Similarity to the user: the better of the average voiceprint and the closest single line."""
        p = self.profile
        return max(float(np.dot(v, p["mean"])), max(float(np.dot(v, e)) for e in p["each"]))

    def verify(self, samples, why=""):
        """True: the user. False: someone or something else. None: can't tell (too short, or no voiceprint yet)."""
        if not self.ready():
            return None
        t0 = time.time()
        v = self.embed(samples)
        if v is None:
            log(f"voiceprint: too short ({len(samples) / SR:.1f}s) -> undecided, {why}")
            return None
        s, th = self.score(v), self.profile["threshold"]
        ok = s >= th
        log(f"voiceprint: {s:.2f} / {th:.2f} -> {'yes' if ok else 'NO'}, {why} ({(time.time() - t0) * 1000:.0f} ms)")
        self._remember(s, ok, why)
        return ok

    def _remember(self, s, ok, why):
        """Keep recent scores, so the threshold can be checked against real use."""
        rec = self.profile.setdefault("recent", [])
        rec.append([round(time.time()), round(s, 3), int(ok), why[:20]])
        del rec[:-200]
        if len(rec) % 10 == 0:
            try:
                self.save()
            except Exception:
                pass

    # -- enrolment ---------------------------------------------------------------------------------------------------
    def start_enroll(self):
        if not self.available():
            return {"ok": False, "error": "the speaker model is missing"}
        self.enrolling, self.enrolled = True, []
        return {"ok": True, "lines": LINES}

    def add(self, samples):
        """One line read during enrolment. Returns progress, or the finished profile."""
        if len(samples) < 1.2 * SR:
            return {"ok": False, "short": True, "got": len(self.enrolled), "need": len(LINES)}
        v = self.embed(samples)
        if v is None:
            return {"ok": False, "got": len(self.enrolled), "need": len(LINES)}
        self.enrolled.append(v)
        if len(self.enrolled) < len(LINES):
            return {"ok": True, "got": len(self.enrolled), "need": len(LINES)}
        return self.finish()

    def finish(self):
        self.enrolling = False
        each = self.enrolled
        if len(each) < 3:
            return {"ok": False, "error": "too few lines were heard"}
        mean = np.mean(each, axis=0); mean /= np.linalg.norm(mean)
        # how close each line is to the others: the user's own spread sets the bar
        self_scores = [float(np.dot(e, (np.sum(each, axis=0) - e) / np.linalg.norm(np.sum(each, axis=0) - e))) for e in each]
        lo = min(self_scores)
        threshold = float(np.clip(lo - 0.12, 0.30, 0.55))
        self.profile = {"model": MODEL.name, "created": time.strftime("%Y-%m-%d %H:%M"), "mean": mean, "each": each,
                        "self": [round(x, 3) for x in self_scores], "threshold": round(threshold, 3), "recent": []}
        self.on = True
        self.save()
        log(f"voiceprint enrolled: self-similarity {min(self_scores):.2f}..{max(self_scores):.2f}, threshold {threshold:.2f}")
        return {"ok": True, "done": True, "threshold": round(threshold, 2), "self": self.profile["self"]}

    def cancel(self):
        self.enrolling, self.enrolled = False, []

    # -- what the voice layer can do ---------------------------------------------------------------------------------
    def status(self):
        if not self.available():
            return {"ok": True, "state": "no model"}
        if not self.profile:
            return {"ok": True, "state": "not enrolled", "note": "Jarvis answers any voice until the user enrols"}
        rec = self.profile.get("recent", [])[-50:]
        return {"ok": True, "state": "on" if self.on else "off", "threshold": self.profile["threshold"],
                "enrolled": self.profile["created"], "recent_accepted": sum(r[2] for r in rec), "recent_rejected": len(rec) - sum(r[2] for r in rec)}


VP = Voiceprint()
ENROLL = None          # set by the service: ENROLL() starts enrolment once Jarvis has finished speaking


def tool():
    return {"type": "function", "function": {
        "name": "voiceprint",
        "description": "Jarvis's speaker verification: it answers only the user's voice, ignoring videos, music, other people "
                       "and its own echo. 'enroll' (录入声纹, 认一下我的声音): the user reads six lines shown on screen; "
                       "'status'; 'off' / 'on' (暂时关掉声纹); 'forget' (删除声纹).",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["enroll", "status", "on", "off", "forget"]},
                                                        "loose": {"type": "boolean", "description": "with 'on': a looser threshold, if it keeps ignoring the user"}},
                       "required": ["action"]}}}


def run(action="status", loose=False, **_):
    if action == "enroll":
        if not VP.available():
            return {"ok": False, "error": "the speaker model is not installed"}
        if ENROLL:
            ENROLL()
        return {"ok": True, "note": "Enrolment starts as soon as you finish this reply: six lines appear on screen for the "
                                    "user to read aloud, one at a time. Tell the user that in one short sentence."}
    if action == "status":
        return VP.status()
    if action in ("on", "off"):
        if not VP.profile:
            return {"ok": False, "error": "no voiceprint yet; enrol first"}
        VP.on = action == "on"
        if action == "on" and loose:
            VP.profile["threshold"] = round(max(0.25, VP.profile["threshold"] - 0.06), 3)
        VP.save()
        return VP.status()
    if action == "forget":
        try:
            PROFILE.unlink()
        except Exception:
            pass
        VP.profile = None
        return {"ok": True, "note": "voiceprint deleted; Jarvis answers any voice again"}
    return {"ok": False, "error": "unknown action"}


def provide():
    return [(tool(), run)], ""
