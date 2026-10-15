"""Pariksha Engine: question bank, deterministic scoring, review queue,
competency analysis and misconception detection.

Scoring policy
- MCQ: exact option match (deterministic).
- Short answer: normalised exact or numeric match = correct; near match
  (similarity 0.5-0.92) = needs teacher review; otherwise incorrect.
- Descriptive / handwritten: always teacher-reviewed (OCR, when added, only
  pre-fills a suggestion with its confidence - see app/services/ocr.py).
A result containing any uncertain item stays `pending_review` and does not
update the learner record until a teacher confirms the marks.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, defaultdict

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerKey,
    Assessment,
    AssessmentResult,
    LearningOutcome,
    Question,
    utcnow,
)
from app.services import insights, learner

DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s)).translate(DIGITS).lower().strip()
    s = re.sub(r"[।॥.,;:!?\"'()\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _number(s: str) -> float | None:
    """Parse '0.5', '1/2', '-3', '३/८' (punctuation kept, unlike normalise())."""
    s = unicodedata.normalize("NFC", str(s)).translate(DIGITS).strip().rstrip(".।").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?", s)
    if not m:
        return None
    return float(m.group(1)) / float(m.group(2)) if m.group(2) else float(m.group(1))


def score_short(response: str, accepted: list[str]) -> tuple[float, str, float, bool]:
    """Returns (fraction, method, confidence, needs_review)."""
    if not response or not response.strip():
        return 0.0, "blank", 1.0, False
    r = normalise(response)
    best = 0.0
    for a in accepted:
        na = normalise(a)
        if r == na:
            return 1.0, "exact", 1.0, False
        rn, an = _number(response), _number(a)
        if rn is not None and an is not None:
            if abs(rn - an) < 1e-6:
                return 1.0, "numeric", 1.0, False
            continue
        best = max(best, difflib.SequenceMatcher(None, r, na).ratio())
    if best >= 0.92:
        return 1.0, "fuzzy", round(best, 3), False
    if best >= 0.5:
        return 0.0, "fuzzy", round(best, 3), True
    return 0.0, "no_match", round(1 - best, 3), False


# ------------------------------------------------------------ question bank ----

def bank_item(q: Question) -> dict:
    """Snapshot of a bank question for an assessment (server-side only)."""
    k = q.answer_key
    item = {"id": f"b{q.id}", "question_id": q.id, "qtype": q.qtype, "text": q.text, "options": q.options or [],
            "topic": q.topic, "lo": q.learning_outcome.code if q.learning_outcome else None,
            "max_marks": k.max_marks if k else 1.0, "difficulty": q.difficulty}
    if q.qtype == "mcq":
        item["answer_index"] = k.correct_option
        item["misconceptions"] = (k.misconceptions or {}) if k else {}
    else:
        item["accepted"] = (k.accepted_answers or []) if k else []
        item["rubric"] = k.rubric if k else None
    return item


def pick_questions(db: Session, *, subject_id: int, grade: int, count: int, lo_ids: list[int] | None = None,
                   topic: str | None = None, difficulty: int | None = None, exclude: set[int] | None = None,
                   qtypes: tuple[str, ...] = ("mcq", "short", "descriptive")) -> list[Question]:
    stmt = select(Question).where(Question.subject_id == subject_id, Question.grade == grade,
                                  Question.status == "approved", Question.qtype.in_(qtypes))
    if lo_ids:
        stmt = stmt.where(Question.learning_outcome_id.in_(lo_ids))
    if topic:
        stmt = stmt.where(Question.topic.ilike(topic))
    rows = [q for q in db.scalars(stmt.order_by(Question.id)) if not exclude or q.id not in exclude]
    if difficulty is not None:  # nearest difficulty first, then the rest
        rows.sort(key=lambda q: abs(q.difficulty - difficulty))
    return rows[:count]


def public_item(item: dict) -> dict:
    """What a student may see before submitting."""
    return {"id": item["id"], "text": item["text"], "options": item.get("options") or [],
            "qtype": item.get("qtype", "mcq"), "max_marks": item.get("max_marks", 1)}


# ------------------------------------------------------------------ scoring ----

def score_submission(assessment: Assessment, answers: dict) -> dict:
    items, total, maximum = [], 0.0, 0.0
    topic_breakdown: dict[str, list] = {}
    pending = False
    for q in assessment.questions:
        qtype = q.get("qtype", "mcq")
        mx = float(q.get("max_marks", 1))
        resp = answers.get(q["id"])
        if qtype == "mcq":
            try:
                chosen = int(resp) if resp is not None and resp != "" else None
            except (TypeError, ValueError):
                chosen = None
            frac, method, conf, review = (1.0 if chosen == q["answer_index"] else 0.0), "mcq", 1.0, False
        elif qtype == "short":
            frac, method, conf, review = score_short(str(resp or ""), q.get("accepted", []))
            chosen = str(resp or "")[:500]
        else:  # descriptive
            frac, method, conf, review, chosen = 0.0, "teacher", 0.0, True, str(resp or "")[:3000]
        got = round(frac * mx, 2)
        pending |= review
        items.append({"id": q["id"], "question_id": q.get("question_id"), "qtype": qtype, "response": chosen,
                      "score": got, "max": mx, "method": method, "confidence": conf, "needs_review": review,
                      "lo": q.get("lo"), "topic": q.get("topic") or assessment.topic or "General"})
        if not review:
            total += got
        maximum += mx
    for it in items:
        if not it["needs_review"]:
            t = topic_breakdown.setdefault(it["topic"], [0, 0])
            t[0] += it["score"]
            t[1] += it["max"]
    return {"items": items, "score": round(total, 2), "max_score": maximum,
            "topic_breakdown": {k: [round(v[0], 2), v[1]] for k, v in topic_breakdown.items()},
            "status": "pending_review" if pending else "final"}


def record_result(db: Session, assessment: Assessment, student_id: int, scored: dict, *, answers: dict,
                  graded_by: int | None = None, source: str = "online", event_uid: str | None = None,
                  device_id: int | None = None, submitted_at=None) -> AssessmentResult:
    r = AssessmentResult(assessment_id=assessment.id, student_user_id=student_id, score=scored["score"],
                         max_score=scored["max_score"], answers=answers, topic_breakdown=scored["topic_breakdown"],
                         item_results=scored["items"], status=scored["status"], graded_by=graded_by,
                         submitted_at=submitted_at or utcnow())
    db.add(r)
    db.flush()
    if r.status == "final":
        _finalise(db, r, source=source, event_uid=event_uid, device_id=device_id, recorded_by=graded_by)
    return r


def _finalise(db: Session, r: AssessmentResult, *, source: str = "online", event_uid: str | None = None,
              device_id: int | None = None, recorded_by: int | None = None) -> None:
    a = r.assessment
    learner.record_event(
        db, student_id=r.student_user_id, event_type="assessment_result", occurred_at=r.submitted_at,
        recorded_by=recorded_by, source=source, event_uid=event_uid or f"result-{r.id}", device_id=device_id,
        payload={"assessment_id": a.id, "result_id": r.id, "subject_id": a.subject_id, "score": r.score,
                 "max_score": r.max_score, "summary": f"{a.title}: {r.score:g}/{r.max_score:g}",
                 "items": [{"lo": i.get("lo"), "score": i["score"], "max": i["max"], "topic": i.get("topic")}
                           for i in (r.item_results or []) if not i.get("needs_review")]})
    insights.apply_result(db, r)
    from app.services import studenthelp

    studenthelp.capture_mistakes(db, r)


def review_queue(db: Session, class_ids: set[int]) -> list[tuple[AssessmentResult, dict]]:
    rows = db.scalars(select(AssessmentResult).join(Assessment).where(
        Assessment.class_section_id.in_(class_ids or [-1]), AssessmentResult.status == "pending_review")
        .order_by(AssessmentResult.submitted_at)).all()
    return [(r, it) for r in rows for it in (r.item_results or []) if it.get("needs_review")]


def apply_review(db: Session, r: AssessmentResult, marks: dict[str, float], teacher_id: int) -> AssessmentResult:
    """Teacher confirms marks for the uncertain items of one result."""
    items = [dict(i) for i in r.item_results or []]
    for it in items:
        if it["id"] in marks:
            m = float(marks[it["id"]])
            if not 0 <= m <= it["max"]:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Marks for {it['id']} out of range")
            it.update(score=m, needs_review=False, method="teacher", confidence=1.0, reviewed_by=teacher_id)
    r.item_results = items
    if any(i.get("needs_review") for i in items):
        return r
    r.score = round(sum(i["score"] for i in items), 2)
    tb: dict[str, list] = {}
    for i in items:
        t = tb.setdefault(i.get("topic") or "General", [0, 0])
        t[0] += i["score"]
        t[1] += i["max"]
    r.topic_breakdown = tb
    r.status = "final"
    r.graded_by = teacher_id
    db.flush()
    _finalise(db, r, recorded_by=teacher_id)
    return r


# ----------------------------------------------------------------- analysis ----

def misconception_report(db: Session, assessment: Assessment) -> list[dict]:
    results = db.scalars(select(AssessmentResult).where(AssessmentResult.assessment_id == assessment.id)).all()
    out = []
    for q in assessment.questions:
        if q.get("qtype", "mcq") != "mcq":
            continue
        counts = Counter()
        for r in results:
            v = (r.answers or {}).get(q["id"])
            if v is not None:
                counts[int(v)] += 1
        n = sum(counts.values())
        if not n:
            continue
        wrong = [(o, c) for o, c in counts.most_common() if o != q["answer_index"]]
        top = wrong[0] if wrong else None
        note = (q.get("misconceptions") or {}).get(str(top[0])) if top else None
        out.append({"id": q["id"], "text": q["text"], "options": q["options"], "correct_index": q["answer_index"],
                    "responses": n, "correct_rate": round(counts[q["answer_index"]] / n, 3),
                    "distribution": {str(o): c for o, c in sorted(counts.items())},
                    "common_wrong_option": top[0] if top else None,
                    "common_wrong_share": round(top[1] / n, 3) if top else 0,
                    "likely_misconception": note if top and top[1] / n >= 0.25 else None})
    return sorted(out, key=lambda d: d["correct_rate"])


def class_competency_report(db: Session, student_ids: list[int], subject_id: int, grade: int) -> list[dict]:
    from app.models import LearnerCompetency

    los = db.scalars(select(LearningOutcome).where(LearningOutcome.subject_id == subject_id,
                                                   LearningOutcome.grade == grade).order_by(LearningOutcome.code)).all()
    comps = defaultdict(list)
    for c in db.scalars(select(LearnerCompetency).where(LearnerCompetency.student_user_id.in_(student_ids or [-1]),
                                                        LearnerCompetency.learning_outcome_id.in_([lo.id for lo in los] or [-1]))):
        comps[c.learning_outcome_id].append(c)
    out = []
    for lo in los:
        cs = comps.get(lo.id, [])
        assessed = [c for c in cs if c.attempted >= learner.MIN_ATTEMPTS]
        out.append({"code": lo.code, "chapter": lo.chapter_title, "topic": lo.topic, "description": lo.description,
                    "students_assessed": len(assessed),
                    "achieved": sum(1 for c in assessed if c.status == "achieved"),
                    "needs_practice": sum(1 for c in assessed if c.status == "needs_practice"),
                    "avg_mastery": round(sum(c.mastery for c in assessed) / len(assessed), 4) if assessed else None})
    return out


def validate_new_question(body: dict) -> None:
    qtype = body["qtype"]
    if qtype == "mcq":
        opts = body.get("options") or []
        if len(opts) < 2 or len(set(opts)) != len(opts):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "MCQ needs at least 2 distinct options")
        if body.get("correct_option") is None or not 0 <= body["correct_option"] < len(opts):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Correct option index is invalid")
    elif qtype == "short" and not body.get("accepted_answers"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Short-answer questions need accepted answers")


def create_question(db: Session, body: dict, *, created_by: int | None, source: str, status_: str,
                    ai_generated: bool = False, is_demo: bool = False) -> Question:
    validate_new_question(body)
    q = Question(subject_id=body["subject_id"], grade=body["grade"], learning_outcome_id=body.get("learning_outcome_id"),
                 topic=body["topic"], qtype=body["qtype"], text=body["text"], options=body.get("options") or [],
                 difficulty=body.get("difficulty", 2), language=body.get("language", "en"), status=status_,
                 source=source, ai_generated=ai_generated, created_by=created_by, is_demo=is_demo)
    db.add(q)
    db.flush()
    db.add(AnswerKey(question_id=q.id, correct_option=body.get("correct_option"),
                     accepted_answers=body.get("accepted_answers") or [], rubric=body.get("rubric"),
                     max_marks=body.get("max_marks", 1), misconceptions=body.get("misconceptions") or {}))
    db.flush()
    return q
