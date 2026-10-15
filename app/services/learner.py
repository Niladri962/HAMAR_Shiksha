"""Centralised learner record.

Every attendance mark, assessment result, activity completion and approved
intervention is written once as a validated, idempotent `learner_events`
row. Competencies (per learning outcome) and topic progress are derived from
these events, and every module reads the same record.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LearnerCompetency,
    LearnerEvent,
    LearningOutcome,
    StudentEnrollment,
    User,
    utcnow,
)

EVENT_TYPES = {"attendance", "assessment_result", "activity_completion", "lesson_completed", "intervention",
               # self-improvement and peer help (app/services/studenthelp.py)
               "chapter_read", "revision_review", "peer_help"}
MIN_ATTEMPTS = 3
ACHIEVED_AT, NEEDS_PRACTICE_BELOW = 0.75, 0.6


def record_event(db: Session, *, student_id: int, event_type: str, payload: dict, occurred_at: datetime | None = None,
                 recorded_by: int | None = None, source: str = "online", event_uid: str | None = None,
                 device_id: int | None = None) -> tuple[LearnerEvent, bool]:
    """Insert one event. Returns (event, created); a repeated event_uid is a no-op."""
    if event_type not in EVENT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown learner event type {event_type}")
    uid = event_uid or uuid.uuid4().hex
    existing = db.scalar(select(LearnerEvent).where(LearnerEvent.event_uid == uid))
    if existing is not None:
        if existing.student_user_id != student_id:  # uid reuse across students is a forgery attempt
            raise HTTPException(status.HTTP_409_CONFLICT, "Event identifier already used")
        return existing, False
    enr = db.scalar(select(StudentEnrollment).where(StudentEnrollment.student_user_id == student_id,
                                                    StudentEnrollment.active.is_(True)))
    if enr is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Student has no active enrolment")
    ev = LearnerEvent(event_uid=uid, student_user_id=student_id, school_id=enr.class_section.school_id,
                      class_section_id=enr.class_section_id, event_type=event_type, payload=payload,
                      occurred_at=occurred_at or utcnow(), recorded_by=recorded_by, source=source, device_id=device_id)
    db.add(ev)
    db.flush()
    if event_type in ("assessment_result", "activity_completion"):
        _update_competencies(db, student_id, ev)
    return ev, True


def _update_competencies(db: Session, student_id: int, ev: LearnerEvent) -> None:
    """payload['items'] = [{lo: code, score, max}] (final, reviewed scores only)."""
    per_lo: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for item in ev.payload.get("items", []):
        if item.get("lo") and not item.get("needs_review"):
            per_lo[item["lo"]][0] += float(item.get("score", 0))
            per_lo[item["lo"]][1] += float(item.get("max", 1))
    if not per_lo:
        return
    los = {lo.code: lo for lo in db.scalars(select(LearningOutcome).where(LearningOutcome.code.in_(list(per_lo))))}
    for code, (got, mx) in per_lo.items():
        lo = los.get(code)
        if lo is None or mx <= 0:
            continue
        comp = db.scalar(select(LearnerCompetency).where(LearnerCompetency.student_user_id == student_id,
                                                         LearnerCompetency.learning_outcome_id == lo.id))
        if comp is None:
            comp = LearnerCompetency(student_user_id=student_id, learning_outcome_id=lo.id, correct=0, attempted=0,
                                     evidence=[])
            db.add(comp)
        comp.correct += got
        comp.attempted += mx
        comp.mastery = round(comp.correct / comp.attempted, 4)
        comp.status = competency_status(comp.mastery, comp.attempted)
        comp.evidence = (list(comp.evidence or []) + [ev.event_uid])[-10:]
        comp.updated_at = utcnow()
    db.flush()


def competency_status(mastery: float, attempted: float) -> str:
    if attempted < MIN_ATTEMPTS:
        return "developing"
    if mastery >= ACHIEVED_AT:
        return "achieved"
    if mastery < NEEDS_PRACTICE_BELOW:
        return "needs_practice"
    return "developing"


def learner_record(db: Session, student_id: int, *, subject_ids: set[int] | None = None, limit: int = 50) -> dict:
    """Read model used by the student portal, teachers (assigned students only - caller checks) and exports."""
    comps = db.scalars(select(LearnerCompetency).where(LearnerCompetency.student_user_id == student_id)).all()
    if subject_ids is not None:
        comps = [c for c in comps if c.learning_outcome.subject_id in subject_ids]
    events = db.scalars(select(LearnerEvent).where(LearnerEvent.student_user_id == student_id)
                        .order_by(LearnerEvent.occurred_at.desc()).limit(limit)).all()
    return {
        "competencies": [{"code": c.learning_outcome.code, "subject": c.learning_outcome.subject.name,
                          "chapter": c.learning_outcome.chapter_title, "topic": c.learning_outcome.topic,
                          "description": c.learning_outcome.description,
                          "description_hi": c.learning_outcome.description_hi, "mastery": c.mastery,
                          "correct": c.correct, "attempted": c.attempted, "status": c.status,
                          "evidence": c.evidence} for c in sorted(comps, key=lambda c: c.learning_outcome.code)],
        "events": [{"uid": e.event_uid, "type": e.event_type, "occurred_at": e.occurred_at.isoformat(),
                    "source": e.source, "summary": e.payload.get("summary")} for e in events],
    }


def weekly_priorities(db: Session, class_ids: set[int], subject_ids: set[int]) -> list[dict]:
    """Students needing help this week, with the competency and the evidence."""
    rows = db.execute(
        select(LearnerCompetency, StudentEnrollment, User)
        .join(StudentEnrollment, StudentEnrollment.student_user_id == LearnerCompetency.student_user_id)
        .join(User, User.id == LearnerCompetency.student_user_id)
        .where(StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True),
               LearnerCompetency.status == "needs_practice")).all()
    by_student: dict[int, dict] = {}
    for comp, enr, user in rows:
        lo = comp.learning_outcome
        if lo.subject_id not in subject_ids:
            continue
        d = by_student.setdefault(user.id, {"student": user.public_id, "name": user.full_name,
                                            "class_id": enr.class_section_id, "roll_no": enr.roll_no, "needs": []})
        evidence_events = db.scalars(select(LearnerEvent).where(LearnerEvent.event_uid.in_(comp.evidence or [])))
        d["needs"].append({"code": lo.code, "subject": lo.subject.name, "topic": lo.topic,
                           "description": lo.description, "mastery": comp.mastery,
                           "evidence": f"{comp.correct:g} of {comp.attempted:g} marks",
                           "sources": [e.payload.get("summary") for e in evidence_events if e.payload.get("summary")]})
    out = list(by_student.values())
    for d in out:
        d["needs"].sort(key=lambda n: n["mastery"])
        d["priority_score"] = round(sum(1 - n["mastery"] for n in d["needs"]), 3)
    return sorted(out, key=lambda d: -d["priority_score"])
