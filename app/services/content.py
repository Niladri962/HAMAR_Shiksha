"""Shared helpers for AI-assisted content and the supervised student tutor.
All generation goes through Gyan SLM (app.slm.gyan)."""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIInteraction, Subject, utcnow
from app.slm import gyan

MAX_QUESTION_CHARS = 500
HOURLY_LIMIT = 30

_WELLBEING = re.compile(
    r"suicid|kill myself|want to die|hurt myself|self[- ]harm|abuse|touch(ed)? me|"
    r"आत्महत्या|मरना चाहत|खुद को चोट|मार डाल", re.I)
_PRIVACY = re.compile(
    r"password|पासवर्ड|otp\b|other student|another student|(marks|result|score)s? of|"
    r"phone number|mobile number|address of|\badmin\b|teacher'?s (number|address)|"
    r"दूसरे छात्र|के अंक", re.I)

WELLBEING_REPLY = {
    "en": ("It sounds like you may be going through something difficult. You are not alone. "
           "Please talk to a teacher, a parent or another adult you trust today. You can also "
           "call CHILDLINE on 1098 (free, any time)."),
    "hi": ("लगता है आप किसी कठिन समय से गुज़र रहे हैं। आप अकेले नहीं हैं। कृपया आज ही अपने "
           "शिक्षक, माता-पिता या किसी भरोसेमंद बड़े से बात करें। आप चाइल्डलाइन 1098 (निःशुल्क) "
           "पर भी कॉल कर सकते हैं।"),
}
PRIVACY_REPLY = {
    "en": "I can only help with your lessons. I cannot share passwords or anyone's personal information or marks.",
    "hi": "मैं केवल आपकी पढ़ाई में मदद कर सकता हूँ। मैं पासवर्ड या किसी की निजी जानकारी या अंक साझा नहीं कर सकता।",
}


def clean_questions(raw: list, default_topic: str) -> list[dict]:
    """Validate MCQ dicts from any source (teacher, SLM draft, bank); drop malformed ones."""
    out = []
    for q in raw or []:
        try:
            text = str(q["text"]).strip()
            options = [str(o).strip() for o in q["options"]][:6]
            ans = int(q["answer_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if not text or len(options) < 2 or not 0 <= ans < len(options) or len(set(options)) < len(options):
            continue
        item = {"id": f"q{len(out) + 1}", "text": text[:500], "options": [o[:200] for o in options],
                "answer_index": ans, "topic": str(q.get("topic") or default_topic)[:120], "qtype": "mcq"}
        for k in ("question_id", "lo", "explanation"):
            if q.get(k) is not None:
                item[k] = q[k]
        out.append(item)
    return out


def ask_assistant(db: Session, *, student_id: int, class_section_id: int | None, grade: int,
                  subjects: list[Subject], subject: Subject | None, question: str,
                  language: str) -> AIInteraction:
    question = question.strip()[:MAX_QUESTION_CHARS]
    lang = language if language in gyan.SUPPORTED_LANGUAGES else "en"
    flagged, reason, citations, verified, latency = False, None, [], False, None
    provider = "safety-filter"

    if _WELLBEING.search(question):
        answer, flagged, reason = WELLBEING_REPLY[lang], True, "wellbeing"
    elif _PRIVACY.search(question):
        answer, flagged, reason = PRIVACY_REPLY[lang], True, "privacy"
    else:
        # Retrieval is limited to the student's grade (and chosen subject).
        res = gyan.answer_question(db, question=question, grade=grade,
                                   subject_id=subject.id if subject else None, language=lang, audience="student")
        answer, citations, verified, latency = res.answer, res.citations, res.verified, res.latency_ms
        provider = f"{res.runtime}:{res.model}" if res.ai_generated and res.model else (
            "textbook-retrieval" if res.verified else f"gyan:{res.reason}")
        if res.reason == "injection":
            flagged, reason = True, "injection"

    row = AIInteraction(student_user_id=student_id, class_section_id=class_section_id,
                        subject_id=subject.id if subject else None, question=question, answer=answer,
                        provider=provider, flagged=flagged, flag_reason=reason, verified=verified,
                        citations=citations, latency_ms=latency)
    db.add(row)
    db.flush()
    return row


def assistant_quota_left(db: Session, student_id: int) -> int:
    since = utcnow() - timedelta(hours=1)
    used = db.scalar(select(func.count(AIInteraction.id)).where(
        AIInteraction.student_user_id == student_id, AIInteraction.created_at >= since)) or 0
    return max(0, HOURLY_LIMIT - used)
