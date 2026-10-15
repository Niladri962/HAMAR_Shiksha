"""Local speech-to-text for voice questions (OpenAI Whisper, open weights, MIT).

Privacy: audio is decoded and transcribed in memory on this server, then
discarded. It is never written to disk, stored in the database or sent to any
external service. Only the transcript - which the user reviews before sending -
becomes a question.

The browser records 16 kHz mono 16-bit PCM WAV, so no ffmpeg is needed.
"""
from __future__ import annotations

import io
import logging
import threading
import time
import wave
from collections import defaultdict, deque

from app.config import get_settings

log = logging.getLogger("hamar_shiksha.stt")

SAMPLE_RATE = 16_000
MIN_RMS = 0.004  # quieter than this is treated as silence (Whisper invents text from silence)
PROMPTS = {"hi": "यह कक्षा के विद्यार्थी का प्रश्न है।", "en": "This is a school student's question."}

_model = None
_model_name = None
_lock = threading.Lock()
_recent: dict[int, deque] = defaultdict(deque)


class STTError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(get_settings().stt_model)


def allow(user_id: int) -> bool:
    """Per-user hourly limit (transcription is CPU-heavy)."""
    now, q = time.monotonic(), _recent[user_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= get_settings().stt_requests_per_hour:
        return False
    q.append(now)
    return True


def decode_wav(data: bytes):
    """16-bit PCM WAV (any rate, mono or stereo) -> float32 mono at 16 kHz."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
                raise STTError("Audio must be 16-bit PCM WAV")
            rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
            if not 8000 <= rate <= 48000 or channels not in (1, 2):
                raise STTError("Unsupported audio format")
            if frames / rate > get_settings().stt_max_seconds + 1:
                raise STTError(f"Recording is too long (max {get_settings().stt_max_seconds} seconds)", 413)
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise STTError("Not a valid WAV recording") from exc
    audio = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = int(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
    return audio


def _load():
    global _model, _model_name
    name = get_settings().stt_model
    if _model is None or _model_name != name:
        import whisper

        log.info("Loading Whisper model %s", name)
        _model, _model_name = whisper.load_model(name, device="cpu"), name
    return _model


def transcribe(data: bytes, language: str) -> dict:
    if not enabled():
        raise STTError("Voice input is not enabled on this server", 503)
    import numpy as np

    audio = decode_wav(data)
    seconds = len(audio) / SAMPLE_RATE
    if seconds < 0.3 or float(np.sqrt(np.mean(audio ** 2))) < MIN_RMS:
        return {"text": "", "language": language, "seconds": round(seconds, 1), "reason": "silence"}
    started = time.perf_counter()
    with _lock:  # one transcription at a time; Whisper is not thread-safe
        model = _load()
        result = model.transcribe(audio, language=language if language in PROMPTS else None, fp16=False,
                                  temperature=0.0, condition_on_previous_text=False,
                                  initial_prompt=PROMPTS.get(language))
    segments = [s for s in result.get("segments", [])
                if not (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0)]
    text = " ".join(s["text"].strip() for s in segments).strip()
    if text in PROMPTS.values():  # the prompt echoed back on near-silence
        text = ""
    return {"text": text[:500], "language": result.get("language", language), "seconds": round(seconds, 1),
            "latency_ms": int((time.perf_counter() - started) * 1000), "model": f"whisper:{_model_name}",
            "reason": None if text else "no_speech"}
