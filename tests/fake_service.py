"""Run the real voice service with a silent fake sound card, for testing the HUD without a microphone.

    JARVIS_VOICE_MODELS=... python tests/fake_service.py
"""
import os, sys, threading, time, types
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("JARVIS_STAY_ON", "1")


class Silent:
    def __init__(self, samplerate, blocksize, channels, dtype, callback):
        self.cb, self.bs = callback, blocksize

    def __enter__(self):
        def run():
            rng = np.random.default_rng(0)
            while True:
                ind = rng.normal(0, 0.002, (self.bs, 1)).astype(np.float32)
                self.cb(ind, np.zeros((self.bs, 1), np.float32), self.bs, None, None)
                time.sleep(self.bs / 48000)
        threading.Thread(target=run, daemon=True).start()
        return self

    def __exit__(self, *a):
        pass


sys.modules["sounddevice"] = types.SimpleNamespace(Stream=Silent, default=types.SimpleNamespace(device=(0, 0)),
                                                   query_devices=lambda i: {"name": "fake"})
from jarvis import service  # noqa: E402
service.main()
