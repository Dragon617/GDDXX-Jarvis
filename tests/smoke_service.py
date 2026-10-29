"""Run the real Service with a fake duplex sound card: the mic hears my recorded lines plus
the speaker's own output after a 30 ms room delay (-6 dB). Events are read from the WebSocket."""
import asyncio, json, os, sys, threading, time, types, numpy as np, soundfile as sf
from pathlib import Path
from scipy.signal import resample_poly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
EN = os.environ.get("JARVIS_LANG", "en") == "en"
CL = Path(os.environ.get("JARVIS_TEST_CLIPS", Path(__file__).parent / ("clips_en" if EN else "clips")))
mic16 = np.zeros(16000 * 26, np.float32)
for t0, k in [(1.0, "wake_cmd"), (8.0, "stop"), (12.0, "wake_only"), (15.0, "cmd_after"), (21.0, "new_cmd")]:
    x = sf.read(CL / f"{k}.wav", dtype="float32")[0]; i = int(t0 * 16000); mic16[i:i + len(x)] += x
mic48 = resample_poly(mic16, 3, 1).astype(np.float32) + np.random.default_rng(0).normal(0, 0.003, len(mic16) * 3).astype(np.float32)
DELAY = 1440  # 30 ms at 48 kHz

class FakeDuplex:
    def __init__(self, samplerate, blocksize, channels, dtype, callback): self.cb, self.bs = callback, blocksize
    def __enter__(self):
        def run():
            echo = np.zeros(len(mic48) + DELAY + self.bs, np.float32)
            for i in range(0, len(mic48) - self.bs, self.bs):
                ind = (mic48[i:i + self.bs] + 0.5 * echo[i:i + self.bs])[:, None]
                outd = np.zeros((self.bs, 1), np.float32)
                self.cb(ind, outd, self.bs, None, None)
                echo[i + DELAY:i + DELAY + self.bs] += outd[:, 0]
                time.sleep(self.bs / 48000)
        threading.Thread(target=run, daemon=True).start(); return self
    def __exit__(self, *a): pass
sys.modules["sounddevice"] = types.SimpleNamespace(Stream=FakeDuplex)
from jarvis import service

async def main():
    s = service.Service(); threading.Thread(target=s.audio_loop, daemon=True).start()
    asyncio.create_task(s.ws_main()); await asyncio.sleep(1)
    import websockets
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        t0 = time.time()
        while time.time() - t0 < 27:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), 1))
            except asyncio.TimeoutError: continue
            if m["type"] != "state": print(round(time.time() - t0, 1), m, flush=True)
asyncio.run(main())
