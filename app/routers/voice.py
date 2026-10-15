"""Voice input: local speech-to-text. Speech output (reading answers aloud)
happens in the browser with the device's own voices."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings
from app.deps import Principal, get_principal
from app.services import stt

router = APIRouter(prefix="/api/voice", tags=["voice"])
MAX_BYTES = 2_000_000  # 30 s of 16 kHz 16-bit mono is ~0.96 MB


@router.get("/status")
def status(p: Principal = Depends(get_principal)):
    s = get_settings()
    return {"speech_to_text": stt.enabled(), "model": f"whisper:{s.stt_model}" if s.stt_model else None,
            "max_seconds": s.stt_max_seconds, "languages": ["hi", "en"]}


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), language: Literal["hi", "en"] = Form("hi"),
                     p: Principal = Depends(get_principal)):
    if not stt.enabled():
        raise HTTPException(503, "Voice input is not enabled on this server")
    data = await audio.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Recording is too large")
    if not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise HTTPException(422, "Not a valid WAV recording")
    if not stt.allow(p.user.id):
        raise HTTPException(429, "Too many voice requests this hour. Please type your question.")
    try:
        return await run_in_threadpool(stt.transcribe, data, language)
    except stt.STTError as exc:
        raise HTTPException(exc.status, str(exc))
