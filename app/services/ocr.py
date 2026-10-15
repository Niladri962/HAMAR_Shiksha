"""Handwritten-answer recognition interface (Pariksha Engine).

No OCR engine is bundled: reliable Devanagari + English handwriting
recognition needs an evaluated model (for example a fine-tuned TrOCR or an
approved government OCR service) benchmarked on real answer sheets.

Until one is integrated, `recognise()` returns no text with zero confidence,
so every handwritten answer goes to the teacher review queue. An engine plugged
in here must return a confidence; anything below the threshold is still
routed to a teacher - marks are never assigned silently.
"""
from __future__ import annotations

from dataclasses import dataclass

REVIEW_BELOW = 0.9


@dataclass
class OCRResult:
    text: str
    confidence: float
    engine: str


class OCRBackend:
    name = "none"

    def recognise(self, image_bytes: bytes, language: str = "hi") -> OCRResult:
        return OCRResult(text="", confidence=0.0, engine=self.name)


_backend: OCRBackend = OCRBackend()


def get_backend() -> OCRBackend:
    return _backend


def set_backend(b: OCRBackend) -> None:
    global _backend
    _backend = b


def needs_review(r: OCRResult) -> bool:
    return r.confidence < REVIEW_BELOW
