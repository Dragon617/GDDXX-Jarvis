"""Wake word detectors with one interface: process(frame) -> keyword or None.

English: openWakeWord's pre-trained "hey jarvis" model (run directly with onnxruntime,
same feature pipeline as the openwakeword package).
Chinese: sherpa-onnx keyword spotter with pinyin keywords.
"""
import numpy as np
import onnxruntime as ort

CHUNK = 1280  # 80 ms at 16 kHz


class HeyJarvis:
    # Real voices (and accents) score well below clean recordings, so the acoustic gate is loose:
    # a confident hit (>= strong) is trusted, a weaker one only wakes if the local transcript agrees.
    def __init__(self, model_dir, threshold=0.25, patience=1, strong=0.6):
        o = ort.SessionOptions(); o.inter_op_num_threads = o.intra_op_num_threads = 1
        self.mel = ort.InferenceSession(str(model_dir / "melspectrogram.onnx"), o)
        self.emb = ort.InferenceSession(str(model_dir / "embedding_model.onnx"), o)
        self.ww = ort.InferenceSession(str(model_dir / "hey_jarvis_v0.1.onnx"), o)
        self.threshold, self.patience, self.strong = threshold, patience, strong
        self.reset()

    def reset(self):
        self.raw = np.zeros(0, np.float32)          # int16-scaled samples
        self.pending = np.zeros(0, np.float32)
        self.mels = np.ones((76, 32), np.float32)
        self.embs = np.zeros((16, 96), np.float32)
        self.hits = 0
        self.cool = 0
        self.score = 0.0

    def process(self, frame):
        self.pending = np.concatenate([self.pending, np.asarray(frame, np.float32) * 32767])
        out = None
        while len(self.pending) >= CHUNK:
            chunk, self.pending = self.pending[:CHUNK], self.pending[CHUNK:]
            self.raw = np.concatenate([self.raw, chunk])[-(CHUNK + 480):]
            if len(self.raw) < CHUNK + 480:
                continue
            m = self.mel.run(None, {"input": self.raw[None, :]})[0].squeeze() / 10 + 2   # (8, 32)
            self.mels = np.vstack([self.mels, m])[-76:]
            e = self.emb.run(None, {"input_1": self.mels[None, :, :, None]})[0].reshape(96)
            self.embs = np.vstack([self.embs, e])[-16:]
            self.score = float(self.ww.run(None, {"x.1": self.embs[None]})[0][0][0])
            if self.cool > 0:
                self.cool -= 1; continue
            self.hits = self.hits + 1 if self.score >= self.threshold else 0
            if self.hits >= self.patience:
                self.hits, self.cool = 0, 15          # ~1.2 s refractory
                out = "hey jarvis" if self.score >= self.strong else "jarvis?"
        return out


class SherpaKws:
    def __init__(self, spotter):
        self.kws = spotter; self.stream = spotter.create_stream()

    def process(self, frame):
        self.stream.accept_waveform(16000, frame)
        hit = None
        while self.kws.is_ready(self.stream):
            self.kws.decode_stream(self.stream)
            r = self.kws.get_result(self.stream)
            if r:
                hit = r; self.kws.reset_stream(self.stream)
        return hit
