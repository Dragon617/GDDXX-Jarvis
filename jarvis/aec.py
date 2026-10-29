"""Echo cancellation with WebRTC's audio processing module (via the livekit wheel,
which ships prebuilt binaries for Apple Silicon). It removes Jarvis's own voice from
the microphone so the user can talk over it."""
import numpy as np
from livekit import rtc

SR, HOP = 16000, 160  # WebRTC APM works on 10 ms frames


class EchoCanceller:
    def __init__(self, delay_ms=40, noise_suppression=True):
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=noise_suppression,
                                             high_pass_filter=True, auto_gain_control=False)
        self.apm.set_stream_delay_ms(delay_ms)
        self.mic = np.zeros(0, np.float32)
        self.ref = np.zeros(0, np.float32)

    @staticmethod
    def _frame(x):
        pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
        return rtc.AudioFrame(pcm.tobytes(), SR, 1, HOP)

    def playback(self, samples):
        """Call with exactly what the speaker is about to play (16 kHz mono float)."""
        self.ref = np.concatenate([self.ref, np.asarray(samples, np.float32)])
        while len(self.ref) >= HOP:
            f, self.ref = self.ref[:HOP], self.ref[HOP:]
            self.apm.process_reverse_stream(self._frame(f))

    def capture(self, samples):
        """Microphone in, echo-free microphone out (may lag by up to 10 ms)."""
        self.mic = np.concatenate([self.mic, np.asarray(samples, np.float32)])
        out = []
        while len(self.mic) >= HOP:
            f, self.mic = self.mic[:HOP], self.mic[HOP:]
            fr = self._frame(f)
            self.apm.process_stream(fr)
            out.append(np.frombuffer(bytes(fr.data), np.int16).astype(np.float32) / 32767)
        return np.concatenate(out) if out else np.zeros(0, np.float32)
