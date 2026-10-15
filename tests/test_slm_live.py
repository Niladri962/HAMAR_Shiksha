"""Live Gyan SLM checks against the configured local runtime.

Opt-in (needs Ollama running with the model pulled):
    HS_LIVE_SLM_MODEL=gemma2:2b python -m pytest -m slm
"""
import os
import re

import pytest

from app.slm import gyan
from app.slm.runtime import OllamaRuntime, set_runtime

pytestmark = pytest.mark.slm
MODEL = os.environ.get("HS_LIVE_SLM_MODEL", "gemma2:2b")


@pytest.fixture
def live():
    rt = OllamaRuntime("http://127.0.0.1:11434", MODEL, ctx=4096, timeout=180)
    h = rt.health()
    if not h.get("ok") or not h.get("model_available"):
        pytest.skip(f"Ollama with {MODEL} not available")
    set_runtime(rt)
    yield rt
    set_runtime(None)


def test_live_answer_is_cited_from_the_textbook(live, db):
    r = gyan.answer_question(db, question="Which fraction is bigger, 1/3 or 1/5?", grade=5, subject_id=None)
    assert r.verified and r.ai_generated and "1/3" in r.answer
    assert any(c["page"] in (2, 4) for c in r.citations)


def test_live_hindi_answer(live, db):
    r = gyan.answer_question(db, question="भिन्न में हर क्या बताता है?", grade=5, subject_id=None, language="hi")
    assert r.verified and re.search(r"[ऀ-ॿ]", r.answer)


def test_live_off_syllabus_is_refused(live, db):
    r = gyan.answer_question(db, question="Who won the cricket world cup?", grade=5, subject_id=None)
    assert r.verified is False and "could not verify" in r.answer
