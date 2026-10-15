"""Student portal API (AI Class). Every query is keyed on the signed-in
student's own user ID and current enrolment; no endpoint accepts another
student's ID."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_student
from app.models import (
    ActivityCompletion,
    AIInteraction,
    AIRecommendation,
    Assessment,
    AssessmentResult,
    Assignment,
    AssignmentSubmission,
    AttendanceRecord,
    ClassSession,
    LearnerCompetency,
    LearningActivity,
    LearningOutcome,
    LearningProgress,
    StudentEnrollment,
    Subject,
)
from app.scope import current_enrollment, not_found
from app.services import aiclass, content, insights, learner, pariksha

router = APIRouter(prefix="/api/student", tags=["student"])
Student = Depends(require_student)


def _enrollment(db: Session, p: Principal) -> StudentEnrollment:
    enr = current_enrollment(db, p.user.id)
    if enr is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are not enrolled in a class. Please contact your school.")
    return enr


def _class_subjects(db: Session, class_id: int) -> list[Subject]:
    ids = aiclass.class_subject_ids(db, class_id)
    return list(db.scalars(select(Subject).where(Subject.id.in_(ids or [-1])).order_by(Subject.name)))


def _subject_dict(s: Subject) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "name_hi": s.name_hi}


@router.get("/me")
def me(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    cs = enr.class_section
    return {"name": p.user.full_name, "class": cs.label, "grade": cs.grade, "academic_year": cs.academic_year,
            "school": cs.school.name, "is_demo": cs.school.is_demo, "language": p.user.preferred_language,
            "subjects": [_subject_dict(s) for s in _class_subjects(db, cs.id)]}


# ------------------------------------------------------------ assignments ----

@router.get("/assignments")
def assignments(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    subs = {s.assignment_id: s for s in db.scalars(select(AssignmentSubmission).where(
        AssignmentSubmission.student_user_id == p.user.id))}
    rows = db.scalars(select(Assignment).where(Assignment.class_section_id == enr.class_section_id)
                      .order_by(Assignment.due_date.is_(None), Assignment.due_date, Assignment.id.desc())
                      .limit(100)).all()
    return [{"id": a.id, "title": a.title, "description": a.description, "kind": a.kind, "topic": a.topic,
             "subject": a.subject.name, "subject_hi": a.subject.name_hi,
             "due_date": a.due_date.isoformat() if a.due_date else None,
             "submitted": a.id in subs, "feedback": subs[a.id].feedback if a.id in subs else None}
            for a in rows]


class SubmitIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


@router.post("/assignments/{assignment_id}/submit")
def submit_assignment(assignment_id: int, body: SubmitIn, p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    a = db.get(Assignment, assignment_id)
    if a is None or a.class_section_id != enr.class_section_id:
        raise not_found("Assignment")
    sub = db.scalar(select(AssignmentSubmission).where(AssignmentSubmission.assignment_id == a.id,
                                                       AssignmentSubmission.student_user_id == p.user.id))
    if sub is not None and sub.feedback:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reviewed by your teacher")
    if sub is None:
        sub = AssignmentSubmission(assignment_id=a.id, student_user_id=p.user.id)
        db.add(sub)
    sub.content = body.content
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ assessments ----

@router.get("/assessments")
def assessments(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    results = {r.assessment_id: r for r in db.scalars(select(AssessmentResult).where(
        AssessmentResult.student_user_id == p.user.id))}
    rows = db.scalars(select(Assessment).where(Assessment.class_section_id == enr.class_section_id,
                                               Assessment.published.is_(True))
                      .order_by(Assessment.created_at.desc()).limit(100)).all()
    out = []
    for a in rows:
        r = results.get(a.id)
        if a.kind == "offline" and r is None:
            continue
        out.append({"id": a.id, "title": a.title, "topic": a.topic, "kind": a.kind, "subject": a.subject.name,
                    "subject_hi": a.subject.name_hi, "questions": len(a.questions or []),
                    "due_date": a.due_date.isoformat() if a.due_date else None,
                    "result": {"score": r.score, "max_score": r.max_score, "status": r.status} if r else None})
    return out


@router.get("/assessments/{assessment_id}")
def take_assessment(assessment_id: int, p: Principal = Student, db: Session = Depends(get_db)):
    a = aiclass.published_assessment(db, _enrollment(db, p), assessment_id)
    done = db.scalar(select(AssessmentResult.id).where(AssessmentResult.assessment_id == a.id,
                                                       AssessmentResult.student_user_id == p.user.id))
    # Answer keys are stripped; they are revealed only after submission.
    return {"id": a.id, "title": a.title, "subject": a.subject.name, "already_submitted": done is not None,
            "questions": [pariksha.public_item(q) for q in a.questions]}


class AnswersIn(BaseModel):
    answers: dict[str, int | str] = Field(max_length=60)


@router.post("/assessments/{assessment_id}/submit")
def submit_assessment(assessment_id: int, body: AnswersIn, request: Request, p: Principal = Student,
                      db: Session = Depends(get_db)):
    r, scored = aiclass.submit_assessment(db, _enrollment(db, p), assessment_id, body.answers)
    audit(db, "assessment.submitted", principal=p, request=request, entity_type="assessment", entity_id=assessment_id)
    db.commit()
    review = [{"id": it["id"], "chosen": it["response"], "correct": it["score"] >= it["max"] and not it["needs_review"],
               "needs_review": it["needs_review"], "score": it["score"], "max": it["max"],
               "correct_index": next((q.get("answer_index") for q in r.assessment.questions if q["id"] == it["id"]), None)}
              for it in scored["items"]]
    return {"score": scored["score"], "max_score": scored["max_score"], "status": scored["status"], "review": review}


# --------------------------------------------------------------- learning ----

def _strip_answers(content_: dict) -> dict:
    c = dict(content_ or {})
    if "questions" in c:
        c["questions"] = [{"id": q.get("id", f"q{i + 1}"), "text": q["text"], "options": q["options"]}
                          for i, q in enumerate(c["questions"])]
    return c


@router.get("/activities")
def activities(subject_id: int | None = None, p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    allowed = aiclass.class_subject_ids(db, enr.class_section_id)
    if subject_id is not None and subject_id not in allowed:
        raise not_found("Subject")
    stmt = select(LearningActivity).where(LearningActivity.grade == enr.class_section.grade,
                                          LearningActivity.approved.is_(True),
                                          LearningActivity.subject_id.in_({subject_id} if subject_id else allowed or {-1}))
    done = {c.activity_id: c for c in db.scalars(select(ActivityCompletion).where(
        ActivityCompletion.student_user_id == p.user.id))}
    return [{"id": a.id, "title": a.title, "topic": a.topic, "kind": a.kind, "language": a.language,
             "subject": a.subject.name, "subject_hi": a.subject.name_hi, "subject_id": a.subject_id,
             "content": _strip_answers(a.content), "completed": a.id in done,
             "score": done[a.id].score if a.id in done else None, "approved": True}
            for a in db.scalars(stmt.order_by(LearningActivity.subject_id, LearningActivity.topic))]


class CompleteIn(BaseModel):
    answers: dict[str, int] = Field(default_factory=dict, max_length=60)


@router.post("/activities/{activity_id}/complete")
def complete_activity(activity_id: int, body: CompleteIn, p: Principal = Student, db: Session = Depends(get_db)):
    out = aiclass.complete_activity(db, _enrollment(db, p), activity_id, body.answers)
    db.commit()
    return out


# ----------------------------------------------------- adaptive practice ----

@router.get("/practice")
def practice(subject_id: int, topic: str | None = None, count: int = 5, p: Principal = Student,
             db: Session = Depends(get_db)):
    """Approved bank questions at a difficulty matched to demonstrated mastery."""
    enr = _enrollment(db, p)
    if subject_id not in aiclass.class_subject_ids(db, enr.class_section_id):
        raise not_found("Subject")
    grade = enr.class_section.grade
    lp_stmt = select(LearningProgress).where(LearningProgress.student_user_id == p.user.id,
                                             LearningProgress.subject_id == subject_id)
    if topic:
        lp_stmt = lp_stmt.where(LearningProgress.topic.ilike(topic))
    lps = db.scalars(lp_stmt).all()
    mastery = min((lp.mastery for lp in lps), default=0.5) if lps else 0.5
    level = 1 if mastery < 0.5 else (2 if mastery < 0.75 else 3)
    if not topic and lps:
        topic = min(lps, key=lambda lp: lp.mastery).topic  # weakest topic first
    qs = pariksha.pick_questions(db, subject_id=subject_id, grade=grade, count=min(count, 10), topic=topic,
                                 difficulty=level, qtypes=("mcq", "short"))
    return {"topic": topic, "difficulty": level, "basis_mastery": round(mastery, 4),
            "questions": [pariksha.public_item(pariksha.bank_item(q)) for q in qs]}


class PracticeIn(BaseModel):
    answers: dict[str, int | str] = Field(max_length=20)


@router.post("/practice/check")
def practice_check(body: PracticeIn, p: Principal = Student, db: Session = Depends(get_db)):
    """Score practice answers deterministically and record them in the learner record."""
    enr = _enrollment(db, p)
    from app.models import Question

    allowed = aiclass.class_subject_ids(db, enr.class_section_id)
    items, review = [], []
    for qid, ans in body.answers.items():
        if not qid.startswith("b") or not qid[1:].isdigit():
            raise HTTPException(422, "Unknown question")
        q = db.get(Question, int(qid[1:]))
        if q is None or q.status != "approved" or q.grade != enr.class_section.grade or q.subject_id not in allowed:
            raise not_found("Question")
        item = pariksha.bank_item(q)
        fake = Assessment(questions=[item], topic=q.topic)
        scored = pariksha.score_submission(fake, {qid: ans})["items"][0]
        items.append({"lo": item["lo"], "score": scored["score"], "max": scored["max"], "topic": q.topic,
                      "needs_review": scored["needs_review"]})
        review.append({"id": qid, "correct": scored["score"] >= scored["max"], "needs_review": scored["needs_review"],
                       "correct_index": item.get("answer_index"), "accepted": item.get("accepted", [])[:1]})
        if not scored["needs_review"]:
            insights._bump_progress(db, p.user.id, q.subject_id, q.topic, int(scored["score"] >= scored["max"]), 1)
    learner.record_event(db, student_id=p.user.id, event_type="activity_completion",
                         payload={"kind": "practice", "items": items,
                                  "summary": f"Practice: {sum(1 for r in review if r['correct'])}/{len(review)}"})
    insights.refresh_student_recommendations(db, p.user.id)
    db.commit()
    return {"review": review}


# ---------------------------------------------------------------- record ----

@router.get("/progress")
def progress(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    lps = db.scalars(select(LearningProgress).where(LearningProgress.student_user_id == p.user.id)
                     .order_by(LearningProgress.subject_id, LearningProgress.topic)).all()
    results = db.execute(select(AssessmentResult, Assessment).join(Assessment).where(
        AssessmentResult.student_user_id == p.user.id).order_by(AssessmentResult.submitted_at.desc()).limit(30)).all()
    since = date.today() - timedelta(days=30)
    att = dict(db.execute(select(AttendanceRecord.status, func.count()).where(
        AttendanceRecord.person_user_id == p.user.id, AttendanceRecord.date >= since)
        .group_by(AttendanceRecord.status)).all())
    total = sum(att.values())
    lessons_done = db.scalar(select(func.count(ActivityCompletion.id)).where(
        ActivityCompletion.student_user_id == p.user.id)) or 0
    achieved = db.scalar(select(func.count(LearnerCompetency.id)).where(
        LearnerCompetency.student_user_id == p.user.id, LearnerCompetency.status == "achieved")) or 0
    badges = []
    if lessons_done >= 1:
        badges.append({"key": "first_step", "label": "First step", "label_hi": "पहला कदम"})
    if lessons_done >= 5:
        badges.append({"key": "five_lessons", "label": "5 activities completed", "label_hi": "5 गतिविधियाँ पूरी"})
    if results:
        badges.append({"key": "quiz_taker", "label": "Quiz taker", "label_hi": "क्विज़ में भाग लिया"})
    if any(r.score == r.max_score and r.max_score > 0 for r, _ in results):
        badges.append({"key": "full_marks", "label": "Full marks", "label_hi": "पूरे अंक"})
    if achieved:
        badges.append({"key": "competency", "label": f"{achieved} learning outcome(s) achieved",
                       "label_hi": f"{achieved} अधिगम परिणाम हासिल"})
    return {
        "class": enr.class_section.label,
        "attendance_30d": round((att.get("present", 0) + att.get("late", 0)) / total, 4) if total else None,
        "lessons_completed": lessons_done,
        "topics": [{"subject": lp.subject.name, "subject_hi": lp.subject.name_hi, "topic": lp.topic,
                    "mastery": lp.mastery, "correct": lp.correct, "attempted": lp.attempted} for lp in lps],
        "results": [{"assessment": a.title, "subject": a.subject.name, "score": r.score, "max_score": r.max_score,
                     "status": r.status, "submitted_at": r.submitted_at.isoformat()} for r, a in results],
        "achievements": badges,
    }


@router.get("/record")
def record(p: Principal = Student, db: Session = Depends(get_db)):
    _enrollment(db, p)
    return learner.learner_record(db, p.user.id, limit=30)


@router.get("/recommendations")
def recommendations(p: Principal = Student, db: Session = Depends(get_db)):
    rows = db.scalars(select(AIRecommendation).where(
        AIRecommendation.target_type == "student", AIRecommendation.target_id == p.user.id,
        AIRecommendation.audience == "student", AIRecommendation.status.in_(insights.OPEN))
        .order_by(AIRecommendation.created_at.desc()).limit(20)).all()
    return [insights.rec_dict(r) for r in rows]


@router.get("/live-lesson")
def live_lesson(p: Principal = Student, db: Session = Depends(get_db)):
    """An approved lesson launched today for the student's class (e.g. substitute lesson)."""
    enr = _enrollment(db, p)
    since = date.today()
    s = db.scalar(select(ClassSession).where(ClassSession.class_section_id == enr.class_section_id,
                                             ClassSession.ended_at.is_(None), ClassSession.started_at >= since)
                  .order_by(ClassSession.started_at.desc()))
    if s is None:
        return None
    lp = s.lesson_plan
    return {"session_id": s.id, "mode": s.mode, "title": lp.title, "subject": lp.subject.name, "topic": lp.topic,
            "body": lp.body, "sources": lp.sources, "started_at": s.started_at.isoformat(),
            "notice": "Supervised lesson. Ask your teacher or supervisor if anything is unclear."}


# -------------------------------------------------------------- assistant ----

class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=content.MAX_QUESTION_CHARS)
    subject_id: int | None = None
    language: Literal["en", "hi"] = "en"


@router.post("/assistant")
def ask(body: AskIn, p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enrollment(db, p)
    if content.assistant_quota_left(db, p.user.id) <= 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You have asked many questions this hour. "
                                                               "Please try again later.")
    subjects = _class_subjects(db, enr.class_section_id)
    subject = None
    if body.subject_id is not None:
        subject = next((s for s in subjects if s.id == body.subject_id), None)
        if subject is None:
            raise not_found("Subject")
    row = content.ask_assistant(db, student_id=p.user.id, class_section_id=enr.class_section_id,
                                grade=enr.class_section.grade, subjects=subjects, subject=subject,
                                question=body.question, language=body.language)
    db.commit()
    return {"answer": row.answer, "provider": row.provider, "flagged": row.flagged, "verified": row.verified,
            "citations": row.citations, "ai_generated": ":" in row.provider and not row.provider.startswith("gyan"),
            "notice": "AI answers can be wrong. Check with your teacher or textbook."}


@router.get("/assistant/history")
def history(p: Principal = Student, db: Session = Depends(get_db)):
    rows = db.scalars(select(AIInteraction).where(AIInteraction.student_user_id == p.user.id)
                      .order_by(AIInteraction.created_at.desc()).limit(20)).all()
    return [{"question": r.question, "answer": r.answer, "citations": r.citations or [], "verified": r.verified,
             "at": r.created_at.isoformat()} for r in reversed(rows)]
