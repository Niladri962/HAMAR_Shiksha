"""AI Class student actions, shared by the online API and offline sync so the
same validation and learner-record updates apply to both paths."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActivityCompletion,
    Assessment,
    AssessmentResult,
    LearningActivity,
    LearningOutcome,
    StudentEnrollment,
    TeacherClassAssignment,
)
from app.scope import not_found
from app.services import insights, learner, pariksha


def class_subject_ids(db: Session, class_id: int) -> set[int]:
    return set(db.scalars(select(TeacherClassAssignment.subject_id).where(
        TeacherClassAssignment.class_section_id == class_id, TeacherClassAssignment.active.is_(True))))


def published_assessment(db: Session, enr: StudentEnrollment, assessment_id: int) -> Assessment:
    a = db.get(Assessment, assessment_id)
    if a is None or not a.published or a.class_section_id != enr.class_section_id or a.kind == "offline":
        raise not_found("Assessment")
    return a


def submit_assessment(db: Session, enr: StudentEnrollment, assessment_id: int, answers: dict, *,
                      source: str = "online", event_uid: str | None = None, device_id: int | None = None,
                      submitted_at: datetime | None = None) -> tuple[AssessmentResult, dict]:
    a = published_assessment(db, enr, assessment_id)
    if db.scalar(select(AssessmentResult.id).where(AssessmentResult.assessment_id == a.id,
                                                   AssessmentResult.student_user_id == enr.student_user_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already submitted this assessment")
    scored = pariksha.score_submission(a, answers)
    r = pariksha.record_result(db, a, enr.student_user_id, scored, answers=answers, source=source,
                               event_uid=event_uid, device_id=device_id, submitted_at=submitted_at)
    return r, scored


def _lo_code(db: Session, act: LearningActivity) -> str | None:
    return db.scalar(select(LearningOutcome.code).where(LearningOutcome.subject_id == act.subject_id,
                                                        LearningOutcome.grade == act.grade,
                                                        LearningOutcome.topic.ilike(act.topic)).limit(1))


def complete_activity(db: Session, enr: StudentEnrollment, activity_id: int, answers: dict, *,
                      source: str = "online", event_uid: str | None = None, device_id: int | None = None,
                      at: datetime | None = None) -> dict:
    a = db.get(LearningActivity, activity_id)
    allowed = class_subject_ids(db, enr.class_section_id)
    if a is None or not a.approved or a.grade != enr.class_section.grade or a.subject_id not in allowed:
        raise not_found("Activity")
    questions = (a.content or {}).get("questions", [])
    review, correct = [], 0
    for i, q in enumerate(questions):
        qid = q.get("id", f"q{i + 1}")
        try:
            ok = int(answers.get(qid)) == q["answer_index"]
        except (TypeError, ValueError):
            ok = False
        correct += ok
        review.append({"id": qid, "correct": ok, "correct_index": q["answer_index"]})
    score = round(correct / len(questions), 4) if questions else None
    comp = db.scalar(select(ActivityCompletion).where(ActivityCompletion.activity_id == a.id,
                                                      ActivityCompletion.student_user_id == enr.student_user_id))
    first = comp is None
    if first:
        db.add(ActivityCompletion(activity_id=a.id, student_user_id=enr.student_user_id, score=score))
    elif questions:
        comp.score = max(comp.score or 0, score or 0)  # conflict rule: keep the best attempt
    lo = _lo_code(db, a)
    learner.record_event(
        db, student_id=enr.student_user_id, event_type="activity_completion" if questions else "lesson_completed",
        occurred_at=at, source=source, event_uid=event_uid, device_id=device_id,
        payload={"activity_id": a.id, "kind": a.kind, "score": score,
                 "summary": f"{a.title}" + (f": {correct}/{len(questions)}" if questions else " (read)"),
                 "items": [{"lo": lo, "score": correct, "max": len(questions), "topic": a.topic}] if questions and lo else []})
    if questions:
        insights.apply_exercise(db, enr.student_user_id, a, correct, len(questions))
    return {"score": score, "review": review, "first_completion": first}
