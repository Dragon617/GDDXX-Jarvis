"""Loads the local sherpa-onnx models. Everything runs offline on this computer."""
import os, re, tempfile
from pathlib import Path
import sherpa_onnx

from . import config
from .paths import MODELS as ROOT
KWS_DIR = ROOT / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
ASR_DIR = ROOT / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
TTS_DIR = ROOT / "kokoro-multi-lang-v1_1"
SR = 16000
LANG = os.environ.get("JARVIS_LANG") or config.get("voice_lang") or "en"          # "en" (default) or "zh"
EN_WAKE_DIR = ROOT / "openwakeword"
EN_ASR_DIR = ROOT / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
JARVIS_VOICE = Path(os.environ.get("JARVIS_VOICE_MODEL", ROOT / "jarvis" / "jarvis-high.onnx"))
if not JARVIS_VOICE.exists() and (ROOT / "alan" / "en_GB-alan-medium.onnx").exists():
    JARVIS_VOICE = ROOT / "alan" / "en_GB-alan-medium.onnx"   # stand-in British voice until jarvis-high is downloaded

# pinyin initials + finals with tones, the format the wenetspeech KWS model expects
KEYWORDS = [
    "h āi j iǎ w éi s ī :2.0 #0.25 @嗨贾维斯",
    "h ēi j iǎ w éi s ī :2.0 #0.25 @嘿贾维斯",
    "j iǎ w éi s ī :1.5 #0.3 @贾维斯",
]


def kws(threads=1):
    kw_file = Path(tempfile.gettempdir()) / "jarvis-keywords.txt"
    kw_file.write_text("\n".join(KEYWORDS) + "\n", encoding="utf-8")
    d = KWS_DIR
    return sherpa_onnx.KeywordSpotter(
        tokens=str(d / "tokens.txt"),
        encoder=str(d / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        decoder=str(d / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        joiner=str(d / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"),
        num_threads=threads, keywords_file=str(kw_file),
        keywords_score=1.5, keywords_threshold=0.25, num_trailing_blanks=1, provider="cpu",
    )


def vad(threshold=0.5, min_silence=0.45):
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(ROOT / "silero_vad.onnx")
    cfg.silero_vad.threshold = threshold
    cfg.silero_vad.min_silence_duration = min_silence
    cfg.silero_vad.min_speech_duration = 0.15
    cfg.silero_vad.window_size = 512
    cfg.silero_vad.max_speech_duration = 8.0     # a noisy room must not hold one segment open forever
    cfg.sample_rate = SR
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)


def wake(lang=None):
    from .wakeword import HeyJarvis, SherpaKws
    return HeyJarvis(EN_WAKE_DIR) if (lang or LANG) == "en" else SherpaKws(kws())


def asr(threads=2, lang=None):
    if (lang or LANG) == "en":
        d = EN_ASR_DIR
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
            model_type="nemo_transducer", num_threads=threads)
    d = ASR_DIR
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"),
        num_threads=threads, use_itn=True, language="auto",
    )


def tts(threads=2):
    d = TTS_DIR
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(d / "model.onnx"), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}"),
            num_threads=threads),
        rule_fsts=f"{d / 'date-zh.fst'},{d / 'phone-zh.fst'},{d / 'number-zh.fst'}",
    )
    return sherpa_onnx.OfflineTts(cfg)


class Transcriber:
    """English: Parakeet first (best accuracy), SenseVoice as a safety net when Parakeet
    returns nothing or clearly too little (it sometimes does on overlapping speech).
    Chinese: SenseVoice."""
    def __init__(self, lang=None, threads=2):
        import re
        self.lang = lang or LANG
        self.sv = asr(threads, "zh")
        self.pk = asr(threads, "en") if self.lang == "en" else None
        self._tag = re.compile(r"<\|[^|]*\|>")

    def _run(self, rec, samples):
        st = rec.create_stream(); st.accept_waveform(SR, samples); rec.decode_stream(st)
        return self._tag.sub("", st.result.text).strip()

    def text(self, samples, mixed=False):
        """mixed=True: the user may speak Chinese (commands); otherwise English only (wake checks)."""
        if not self.pk:
            return self._run(self.sv, samples)
        sv = None
        if mixed:
            # Parakeet turns Chinese into English-sounding nonsense, so let SenseVoice decide first
            sv = self._run(self.sv, samples)
            han = len(re.findall(r"[\u4e00-\u9fff]", sv))
            if han >= 2 and han >= 0.3 * len(re.sub(r"[\s\W]", "", sv)):
                return sv
        pk = self._run(self.pk, samples)
        if len(pk.split()) >= 2:
            return pk                      # Parakeet is enough; skip the second model to keep up in real time
        sv = sv if sv is not None else self._run(self.sv, samples)
        if len(pk.split()) * 2 < len(sv.split()):
            return sv.capitalize() if sv.isupper() else sv
        return pk
