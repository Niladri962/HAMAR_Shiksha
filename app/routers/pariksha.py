"""Pariksha Engine API (teacher side): question bank, bank-built assessments,
review queue for uncertain grading, misconceptions and competency reports."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_teacher
from app.models import Assessment, AssessmentResult, Question, StudentEnrollment, User
from app.scope import get_class_for_teacher, not_found, teacher_assignments, teacher_class_ids
from app.services import pariksha

router = APIRouter(prefix="/api/teacher/pariksha", tags=["pariksha"])
Teacher = Depends(require_teacher)


def _teach_pairs(db: Session, p: Principal) -> set[tuple[int, int]]:
    return {(a.class_section.grade, a.subject_id) for a in teacher_assignments(db, p.user.id)}


def _q_dict(q: Question, with_key: bool = True) -> dict:
    k = q.answer_key
    d = {"id": q.id, "subject_id": q.subject_id, "grade": q.grade, "topic": q.topic, "qtype": q.qtype, "text": q.text,
         "options": q.options, "difficulty": q.difficulty, "language": q.language, "status": q.status,
         "source": q.source, "ai_generated": q.ai_generated, "is_demo": q.is_demo,
         "learning_outcome": q.learning_outcome.code if q.learning_outcome else None}
    if with_key and k:
        d.update(correct_option=k.correct_option, accepted_answers=k.accepted_answers, rubric=k.rubric,
                 max_marks=k.max_marks, misconceptions=k.misconceptions)
    return d


@router.get("/bank")
def bank(subject_id: int, grade: int, status_filter: str | None = None, p: Principal = Teacher,
         db: Session = Depends(get_db)):
    if (grade, subject_id) not in _teach_pairs(db, p):
        raise not_found("Subject")
    stmt = select(Question).where(Question.subject_id == subject_id, Question.grade == grade,
                                  Question.status != "retired")
    if status_filter:
        stmt = stmt.where(Question.status == status_filter)
    return [_q_dict(q) for q in db.scalars(stmt.order_by(Question.status, Question.topic, Question.id).limit(300))]


class QuestionIn(BaseModel):
    subject_id: int
    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=2, max_length=120)
    learning_outcome_id: int | None = None
    qtype: Literal["mcq", "short", "descriptive"]
    text: str = Field(min_length=3, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=6)
    correct_option: int | None = None
    accepted_answers: list[str] = Field(default_factory=list, max_length=10)
    rubric: str | None = Field(default=None, max_length=2000)
    max_marks: float = Field(default=1, gt=0, le=20)
    difficulty: int = Field(default=2, ge=1, le=3)
    language: Literal["en", "hi"] = "en"
    misconceptions: dict[str, str] = Field(default_factory=dict)


@router.post("/bank", status_code=201)
def add_question(body: QuestionIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    if (body.grade, body.subject_id) not in _teach_pairs(db, p):
        raise not_found("Subject")
    q = pariksha.create_question(db, body.model_dump(), created_by=p.user.id, source="teacher", status_="approved")
    audit(db, "question.created", principal=p, request=request, entity_type="question", entity_id=q.id)
    db.commit()
    return _q_dict(q)


@router.post("/bank/{question_id}/{action}")
def question_action(question_id: int, action: Literal["approve", "retire"], request: Request, p: Principal = Teacher,
                    db: Session = Depends(get_db)):
    q = db.get(Question, question_id)
    if q is None or (q.grade, q.subject_id) not in _teach_pairs(db, p):
        raise not_found("Question")
    if action == "approve":
        if q.status != "draft" or q.created_by != p.user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can approve only your own drafts")
        q.status, q.approved_by = "approved", p.user.id
    else:
        if q.source == "scert":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "SCERT questions are managed centrally")
        q.status = "retired"
    audit(db, f"question.{action}d", principal=p, request=request, entity_type="question", entity_id=q.id)
    db.commit()
    return _q_dict(q)


class FromBankIn(BaseModel):
    class_id: int
    subject_id: int
    title: str = Field(min_length=3, max_length=200)
    kind: Literal["quiz", "unit_test", "quarterly", "annual", "baseline"] = "unit_test"
    learning_outcome_ids: list[int] = Field(default_factory=list, max_length=20)
    topic: str | None = Field(default=None, max_length=120)
    count: int = Field(default=10, ge=1, le=40)
    difficulty: int | None = Field(default=None, ge=1, le=3)
    qtypes: list[Literal["mcq", "short", "descriptive"]] = Field(default_factory=lambda: ["mcq", "short"])
    due_date: date | None = None
    publish: bool = False


@router.post("/assessments", status_code=201)
def assessment_from_bank(body: FromBankIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, body.class_id, body.subject_id)
    qs = pariksha.pick_questions(db, subject_id=body.subject_id, grade=cs.grade, count=body.count,
                                 lo_ids=body.learning_outcome_ids or None, topic=body.topic,
                                 difficulty=body.difficulty, qtypes=tuple(body.qtypes))
    if not qs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No approved questions match these filters")
    items = [pariksha.bank_item(q) for q in qs]
    a = Assessment(class_section_id=cs.id, subject_id=body.subject_id, created_by=p.user.id, title=body.title,
                   topic=body.topic or qs[0].topic, kind=body.kind, questions=items,
                   max_score=float(sum(i["max_marks"] for i in items)), published=body.publish,
                   due_date=body.due_date)
    db.add(a)
    db.flush()
    audit(db, "assessment.created", principal=p, request=request, entity_type="assessment", entity_id=a.id,
          from_bank=len(items))
    db.commit()
    return {"id": a.id, "questions": len(items), "max_score": a.max_score, "published": a.published}


@router.get("/review-queue")
def review_queue(p: Principal = Teacher, db: Session = Depends(get_db)):
    """Answers the engine could not grade with confidence. Nothing here counts
    towards a learner record until a teacher confirms the marks."""
    out = []
    for r, item in pariksha.review_queue(db, teacher_class_ids(db, p.user.id)):
        a = r.assessment
        get_class_for_teacher(db, p, a.class_section_id, a.subject_id)
        q = next((x for x in a.questions if x["id"] == item["id"]), {})
        u = db.get(User, r.student_user_id)
        out.append({"result_id": r.id, "item_id": item["id"], "assessment": a.title, "student": u.full_name,
                    "question": q.get("text"), "response": item.get("response"), "max": item["max"],
                    "accepted": q.get("accepted"), "rubric": q.get("rubric"), "method": item["method"],
                    "confidence": item["confidence"], "submitted_at": r.submitted_at.isoformat()})
    return out


class ReviewIn(BaseModel):
    marks: dict[str, float]


@router.post("/results/{result_id}/review")
def review(result_id: int, body: ReviewIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    r = db.get(AssessmentResult, result_id)
    if r is None:
        raise not_found("Result")
    get_class_for_teacher(db, p, r.assessment.class_section_id, r.assessment.subject_id)
    pariksha.apply_review(db, r, body.marks, p.user.id)
    audit(db, "assessment.reviewed", principal=p, request=request, entity_type="assessment_result", entity_id=r.id,
          items=list(body.marks))
    db.commit()
    return {"result_id": r.id, "status": r.status, "score": r.score, "max_score": r.max_score}


@router.get("/assessments/{assessment_id}/misconceptions")
def misconceptions(assessment_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    a = db.get(Assessment, assessment_id)
    if a is None:
        raise not_found("Assessment")
    get_class_for_teacher(db, p, a.class_section_id, a.subject_id)
    return pariksha.misconception_report(db, a)


@router.get("/competencies")
def competencies(class_id: int, subject_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id, subject_id)
    ids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id == cs.id, StudentEnrollment.active.is_(True))))
    return pariksha.class_competency_report(db, ids, subject_id, cs.grade)
