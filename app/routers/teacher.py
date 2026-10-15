"""Teacher portal API. A teacher sees only classes with an active, approved
assignment, and only students enrolled in those classes. Students are
referenced by their random public ID, never by sequential database IDs."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_teacher
from app.models import (
    AIInteraction,
    AIRecommendation,
    Assessment,
    AssessmentResult,
    Assignment,
    AssignmentSubmission,
    AttendanceRecord,
    AuditLog,
    AuthSession,
    ClassSection,
    LearningProgress,
    SchoolReport,
    StudentEnrollment,
    Subject,
    TeacherClassAssignment,
    TeacherProfile,
    TimetableSlot,
    User,
    utcnow,
)
from app.scope import get_class_for_teacher, not_found, teacher_assignments, teacher_can_see_student, teacher_class_ids
from app.services import accounts, analytics, content, insights, learner, pariksha, sync
from app.services.exports import MEDIA_TYPES, Table, render

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
Teacher = Depends(require_teacher)
ATTENDANCE_EDIT_DAYS = 7
AI_DAILY_LIMIT = 100


def _profile(db: Session, p: Principal) -> TeacherProfile:
    return db.get(TeacherProfile, p.user.id)


def _student_by_public_id(db: Session, p: Principal, public_id: str) -> User:
    user = db.scalar(select(User).where(User.public_id == public_id))
    if user is None or not teacher_can_see_student(db, p.user.id, user.id):
        raise not_found("Student")
    return user


def _class_students(db: Session, class_id: int) -> list[tuple[StudentEnrollment, User]]:
    return list(db.execute(select(StudentEnrollment, User).join(User, User.id == StudentEnrollment.student_user_id)
                           .where(StudentEnrollment.class_section_id == class_id,
                                  StudentEnrollment.active.is_(True))
                           .order_by(StudentEnrollment.roll_no, User.full_name)).all())


def _ai_quota(db: Session, p: Principal) -> None:
    since = utcnow() - timedelta(days=1)
    used = db.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.actor_user_id == p.user.id, AuditLog.action.like("ai.%"), AuditLog.at >= since)) or 0
    if used >= AI_DAILY_LIMIT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily AI request limit reached")


# --------------------------------------------------------------------- me ----

@router.get("/me")
def me(p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _profile(db, p)
    assigns = teacher_assignments(db, p.user.id)
    slots = db.scalars(select(TimetableSlot).where(TimetableSlot.teacher_user_id == p.user.id)
                       .order_by(TimetableSlot.day_of_week, TimetableSlot.period)).all()
    class_ids = {a.class_section_id for a in assigns}
    counts = dict(db.execute(select(StudentEnrollment.class_section_id, func.count()).where(
        StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True))
        .group_by(StudentEnrollment.class_section_id)).all())
    return {
        "name": p.user.full_name, "employee_id": prof.employee_id, "designation": prof.designation,
        "is_head_teacher": prof.is_head_teacher,
        "school": {"name": prof.school.name, "official_code": prof.school.official_code,
                   "district": prof.school.district.name, "block": prof.school.block.name,
                   "medium": prof.school.medium, "is_demo": prof.school.is_demo},
        "assignments": [{"class_id": a.class_section_id, "class": a.class_section.label,
                         "grade": a.class_section.grade, "subject_id": a.subject_id, "subject": a.subject.name,
                         "subject_hi": a.subject.name_hi, "subject_code": a.subject.code,
                         "is_class_teacher": a.is_class_teacher,
                         "students": counts.get(a.class_section_id, 0)} for a in assigns],
        "timetable": [{"day": s.day_of_week, "period": s.period,
                       "class": db.get(ClassSection, s.class_section_id).label,
                       "subject": db.get(Subject, s.subject_id).name} for s in slots],
        "subjects": [{"id": s.id, "code": s.code, "name": s.name, "name_hi": s.name_hi}
                     for s in db.scalars(select(Subject).order_by(Subject.name))],
    }


# ----------------------------------------------------------------- roster ----

@router.get("/classes/{class_id}/roster")
def roster(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    since = date.today() - timedelta(days=30)
    out = []
    for enr, u in _class_students(db, cs.id):
        att = dict(db.execute(select(AttendanceRecord.status, func.count()).where(
            AttendanceRecord.person_user_id == u.id, AttendanceRecord.date >= since)
            .group_by(AttendanceRecord.status)).all())
        total = sum(att.values())
        avg = db.scalar(select(func.avg(AssessmentResult.score / AssessmentResult.max_score)).join(Assessment).where(
            AssessmentResult.student_user_id == u.id, Assessment.class_section_id == cs.id,
            AssessmentResult.max_score > 0))
        out.append({"student": u.public_id, "name": u.full_name, "roll_no": enr.roll_no, "login_id": u.login_id,
                    "attendance_30d": round((att.get("present", 0) + att.get("late", 0)) / total, 4) if total else None,
                    "avg_score_pct": round(avg, 4) if avg is not None else None})
    return {"class": {"id": cs.id, "label": cs.label, "grade": cs.grade, "academic_year": cs.academic_year},
            "students": out}


# ------------------------------------------------------------- attendance ----

class AttendanceItem(BaseModel):
    student: str = Field(max_length=32)
    status: Literal["present", "absent", "late", "leave"]


class AttendanceIn(BaseModel):
    date: date
    records: list[AttendanceItem] = Field(max_length=200)


def _check_attendance_date(d: date) -> None:
    today = date.today()
    if d > today or d < today - timedelta(days=ATTENDANCE_EDIT_DAYS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Attendance can be recorded for today and the previous {ATTENDANCE_EDIT_DAYS} days")


@router.get("/classes/{class_id}/attendance")
def get_attendance(class_id: int, on: date = Query(default_factory=date.today), p: Principal = Teacher,
                   db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    students = _class_students(db, cs.id)
    marks = {r.person_user_id: r.status for r in db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.class_section_id == cs.id, AttendanceRecord.date == on))}
    return {"date": on.isoformat(), "records": [
        {"student": u.public_id, "name": u.full_name, "roll_no": e.roll_no, "status": marks.get(u.id)}
        for e, u in students]}


@router.post("/classes/{class_id}/attendance")
def record_attendance(class_id: int, body: AttendanceIn, request: Request, p: Principal = Teacher,
                      db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    note = sync.mark_attendance(db, p, cs, body.date, [r.model_dump() for r in body.records])
    audit(db, "attendance.recorded", principal=p, request=request, entity_type="class_section",
          entity_id=cs.id, date=body.date.isoformat(), count=len(body.records))
    db.commit()
    return {"saved": len(body.records), "note": note}


# ------------------------------------------------------------ assignments ----

class AssignmentIn(BaseModel):
    class_section_id: int
    subject_id: int
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    kind: Literal["homework", "worksheet", "project"] = "homework"
    topic: str = Field(default="", max_length=120)
    due_date: date | None = None
    ai_assisted: bool = False


@router.get("/assignments")
def list_assignments(class_id: int | None = None, p: Principal = Teacher, db: Session = Depends(get_db)):
    ids = teacher_class_ids(db, p.user.id)
    if class_id is not None:
        if class_id not in ids:
            raise not_found("Class")
        ids = {class_id}
    rows = db.scalars(select(Assignment).where(Assignment.class_section_id.in_(ids or [-1]))
                      .order_by(Assignment.created_at.desc()).limit(100)).all()
    out = []
    for a in rows:
        enrolled = db.scalar(select(func.count(StudentEnrollment.id)).where(
            StudentEnrollment.class_section_id == a.class_section_id, StudentEnrollment.active.is_(True)))
        done = db.scalar(select(func.count(AssignmentSubmission.id)).where(
            AssignmentSubmission.assignment_id == a.id))
        out.append({"id": a.id, "class_id": a.class_section_id, "class": db.get(ClassSection, a.class_section_id).label,
                    "subject": a.subject.name, "title": a.title, "description": a.description, "kind": a.kind,
                    "topic": a.topic, "due_date": a.due_date.isoformat() if a.due_date else None,
                    "submitted": done, "enrolled": enrolled, "ai_assisted": a.ai_assisted})
    return out


@router.post("/assignments", status_code=201)
def create_assignment(body: AssignmentIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    get_class_for_teacher(db, p, body.class_section_id, body.subject_id)
    a = Assignment(created_by=p.user.id, **body.model_dump())
    db.add(a)
    db.flush()
    audit(db, "assignment.created", principal=p, request=request, entity_type="assignment", entity_id=a.id)
    db.commit()
    return {"id": a.id}


def _own_assignment(db: Session, p: Principal, assignment_id: int) -> Assignment:
    a = db.get(Assignment, assignment_id)
    if a is None or a.class_section_id not in teacher_class_ids(db, p.user.id):
        raise not_found("Assignment")
    return a


@router.get("/assignments/{assignment_id}/submissions")
def submissions(assignment_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    a = _own_assignment(db, p, assignment_id)
    subs = {s.student_user_id: s for s in db.scalars(select(AssignmentSubmission).where(
        AssignmentSubmission.assignment_id == a.id))}
    out = []
    for e, u in _class_students(db, a.class_section_id):
        s = subs.get(u.id)
        out.append({"student": u.public_id, "name": u.full_name, "roll_no": e.roll_no,
                    "submission_id": s.id if s else None, "content": s.content if s else None,
                    "submitted_at": s.submitted_at.isoformat() if s else None,
                    "feedback": s.feedback if s else None})
    return {"assignment": {"id": a.id, "title": a.title}, "submissions": out}


class FeedbackIn(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)


@router.post("/submissions/{submission_id}/feedback")
def give_feedback(submission_id: int, body: FeedbackIn, p: Principal = Teacher, db: Session = Depends(get_db)):
    s = db.get(AssignmentSubmission, submission_id)
    if s is None:
        raise not_found("Submission")
    _own_assignment(db, p, s.assignment_id)
    s.feedback, s.feedback_by = body.feedback, p.user.id
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ assessments ----

class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=6)
    answer_index: int = Field(ge=0, le=5)
    topic: str = Field(default="", max_length=120)


class AssessmentIn(BaseModel):
    class_section_id: int
    subject_id: int
    title: str = Field(min_length=3, max_length=200)
    topic: str = Field(default="", max_length=120)
    kind: Literal["quiz", "unit_test", "baseline", "offline"] = "quiz"
    questions: list[QuestionIn] = Field(default_factory=list, max_length=50)
    max_score: float | None = Field(default=None, gt=0, le=1000)  # offline tests only
    due_date: date | None = None
    publish: bool = False
    ai_assisted: bool = False


@router.get("/assessments")
def list_assessments(class_id: int | None = None, p: Principal = Teacher, db: Session = Depends(get_db)):
    ids = teacher_class_ids(db, p.user.id)
    if class_id is not None:
        if class_id not in ids:
            raise not_found("Class")
        ids = {class_id}
    rows = db.scalars(select(Assessment).where(Assessment.class_section_id.in_(ids or [-1]))
                      .order_by(Assessment.created_at.desc()).limit(100)).all()
    out = []
    for a in rows:
        n, avg = db.execute(select(func.count(AssessmentResult.id),
                                   func.avg(AssessmentResult.score / AssessmentResult.max_score))
                            .where(AssessmentResult.assessment_id == a.id, AssessmentResult.max_score > 0)).one()
        out.append({"id": a.id, "class_id": a.class_section_id, "class": a.class_section.label,
                    "subject": a.subject.name, "title": a.title, "topic": a.topic, "kind": a.kind,
                    "questions": len(a.questions or []), "max_score": a.max_score, "published": a.published,
                    "due_date": a.due_date.isoformat() if a.due_date else None, "results": n,
                    "avg_score_pct": round(avg, 4) if avg is not None else None, "ai_assisted": a.ai_assisted})
    return out


@router.post("/assessments", status_code=201)
def create_assessment(body: AssessmentIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    get_class_for_teacher(db, p, body.class_section_id, body.subject_id)
    questions = content.clean_questions([q.model_dump() for q in body.questions], body.topic or "General")
    if body.kind == "offline":
        if not body.max_score:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Offline tests need a maximum score")
        max_score = body.max_score
    else:
        if not questions:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one valid question")
        max_score = float(len(questions))
    a = Assessment(class_section_id=body.class_section_id, subject_id=body.subject_id, created_by=p.user.id,
                   title=body.title, topic=body.topic, kind=body.kind, max_score=max_score, questions=questions,
                   published=body.publish, due_date=body.due_date, ai_assisted=body.ai_assisted)
    db.add(a)
    db.flush()
    audit(db, "assessment.created", principal=p, request=request, entity_type="assessment", entity_id=a.id)
    db.commit()
    return {"id": a.id, "questions": len(questions), "published": a.published}


def _own_assessment(db: Session, p: Principal, assessment_id: int) -> Assessment:
    a = db.get(Assessment, assessment_id)
    if a is None:
        raise not_found("Assessment")
    get_class_for_teacher(db, p, a.class_section_id, a.subject_id)
    return a


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    a = _own_assessment(db, p, assessment_id)
    return {"id": a.id, "title": a.title, "topic": a.topic, "kind": a.kind, "questions": a.questions,
            "max_score": a.max_score, "published": a.published, "class": a.class_section.label,
            "subject": a.subject.name}


@router.post("/assessments/{assessment_id}/publish")
def publish_assessment(assessment_id: int, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    a = _own_assessment(db, p, assessment_id)
    a.published = True
    audit(db, "assessment.published", principal=p, request=request, entity_type="assessment", entity_id=a.id)
    db.commit()
    return {"ok": True}


@router.get("/assessments/{assessment_id}/results")
def assessment_results(assessment_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    a = _own_assessment(db, p, assessment_id)
    res = {r.student_user_id: r for r in db.scalars(select(AssessmentResult).where(
        AssessmentResult.assessment_id == a.id))}
    rows = []
    for e, u in _class_students(db, a.class_section_id):
        r = res.get(u.id)
        rows.append({"student": u.public_id, "name": u.full_name, "roll_no": e.roll_no,
                     "score": r.score if r else None, "max_score": r.max_score if r else a.max_score,
                     "status": r.status if r else None,
                     "topic_breakdown": r.topic_breakdown if r else None,
                     "submitted_at": r.submitted_at.isoformat() if r else None})
    return {"assessment": {"id": a.id, "title": a.title, "max_score": a.max_score}, "results": rows}


class ScoreItem(BaseModel):
    student: str = Field(max_length=32)
    score: float = Field(ge=0)


class ScoresIn(BaseModel):
    scores: list[ScoreItem] = Field(max_length=200)


@router.post("/assessments/{assessment_id}/scores")
def enter_scores(assessment_id: int, body: ScoresIn, request: Request, p: Principal = Teacher,
                 db: Session = Depends(get_db)):
    """Record marks for an offline (paper) test."""
    a = _own_assessment(db, p, assessment_id)
    if a.kind != "offline":
        raise HTTPException(status.HTTP_409_CONFLICT, "Online assessments are graded automatically")
    by_public = {u.public_id: u for _, u in _class_students(db, a.class_section_id)}
    topic = a.topic or "General"
    for item in body.scores:
        u = by_public.get(item.student)
        if u is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Student is not in this class")
        if item.score > a.max_score:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Score exceeds maximum")
        if db.scalar(select(AssessmentResult.id).where(AssessmentResult.assessment_id == a.id,
                                                       AssessmentResult.student_user_id == u.id)):
            continue  # marks already entered; corrections go through the head teacher
        scored = {"score": item.score, "max_score": a.max_score, "status": "final",
                  "topic_breakdown": {topic: [item.score, a.max_score]},
                  "items": [{"id": "paper", "qtype": "offline", "response": None, "score": item.score,
                             "max": a.max_score, "method": "teacher", "confidence": 1.0, "needs_review": False,
                             "lo": (a.questions or [{}])[0].get("lo") if a.questions else None, "topic": topic}]}
        pariksha.record_result(db, a, u.id, scored, answers={}, graded_by=p.user.id)
    audit(db, "assessment.scores_entered", principal=p, request=request, entity_type="assessment",
          entity_id=a.id, count=len(body.scores))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------ performance ----

@router.get("/classes/{class_id}/performance")
def class_performance(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    my_subjects = {a.subject_id for a in teacher_assignments(db, p.user.id) if a.class_section_id == cs.id}
    summary = analytics.class_summary(db, cs, include_students=True)
    summary["subjects"] = [s for s in summary["subjects"] if s["subject_id"] in my_subjects]
    students = _class_students(db, cs.id)
    ids = [u.id for _, u in students]
    lps = db.scalars(select(LearningProgress).where(LearningProgress.student_user_id.in_(ids or [-1]),
                                                    LearningProgress.subject_id.in_(my_subjects or [-1]))).all()
    grid: dict[int, dict] = {}
    for lp in lps:
        grid.setdefault(lp.student_user_id, {})[f"{lp.subject_id}:{lp.topic}"] = {
            "mastery": lp.mastery, "attempted": lp.attempted}
    summary["students"] = [{"student": u.public_id, "name": u.full_name, "roll_no": e.roll_no,
                            "topics": grid.get(u.id, {})} for e, u in students]
    return summary


@router.get("/students/{public_id}/progress")
def student_progress(public_id: str, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    u = _student_by_public_id(db, p, public_id)
    my_subjects = {a.subject_id for a in teacher_assignments(db, p.user.id)}
    lps = db.scalars(select(LearningProgress).where(LearningProgress.student_user_id == u.id,
                                                    LearningProgress.subject_id.in_(my_subjects or [-1]))).all()
    results = db.execute(select(AssessmentResult, Assessment).join(Assessment).where(
        AssessmentResult.student_user_id == u.id, Assessment.subject_id.in_(my_subjects or [-1]))
        .order_by(AssessmentResult.submitted_at.desc()).limit(30)).all()
    recs = db.scalars(select(AIRecommendation).where(AIRecommendation.target_type == "student",
                                                     AIRecommendation.target_id == u.id)
                      .order_by(AIRecommendation.created_at.desc()).limit(20)).all()
    audit(db, "student.progress_viewed", principal=p, request=request, entity_type="user", entity_id=u.id)
    db.commit()
    return {"student": {"id": u.public_id, "name": u.full_name},
            "topics": [{"subject": lp.subject.name, "topic": lp.topic, "mastery": lp.mastery,
                        "correct": lp.correct, "attempted": lp.attempted,
                        "last_activity_at": lp.last_activity_at.isoformat()} for lp in lps],
            "results": [{"assessment": a.title, "subject": a.subject.name, "score": r.score, "max_score": r.max_score,
                         "submitted_at": r.submitted_at.isoformat()} for r, a in results],
            "recommendations": [insights.rec_dict(r) for r in recs if r.evidence.get("subject_id") in my_subjects]}


@router.post("/students/{public_id}/reset-credentials")
def reset_student_credentials(public_id: str, request: Request, p: Principal = Teacher,
                              db: Session = Depends(get_db)):
    """School-mediated recovery: only the student's class teacher may reissue a password."""
    u = _student_by_public_id(db, p, public_id)
    enr = db.scalar(select(StudentEnrollment).where(StudentEnrollment.student_user_id == u.id,
                                                    StudentEnrollment.active.is_(True)))
    is_class_teacher = db.scalar(select(TeacherClassAssignment.id).where(
        TeacherClassAssignment.teacher_user_id == p.user.id, TeacherClassAssignment.active.is_(True),
        TeacherClassAssignment.class_section_id == enr.class_section_id,
        TeacherClassAssignment.is_class_teacher.is_(True)).limit(1))
    if not is_class_teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the class teacher can reset student credentials")
    temp = accounts.reset_to_temporary_password(db, u)
    db.execute(update(AuthSession).where(AuthSession.user_id == u.id).values(revoked=True))
    audit(db, "student.credentials_reset", principal=p, request=request, entity_type="user", entity_id=u.id)
    db.commit()
    return {"login_id": u.login_id, "temporary_password": temp,
            "note": "Give this to the student or guardian in person. The student must change it at next sign-in."}


# -------------------------------------------------------- recommendations ----

@router.get("/recommendations")
def recommendations(p: Principal = Teacher, db: Session = Depends(get_db)):
    assigns = teacher_assignments(db, p.user.id)
    class_ids = {a.class_section_id for a in assigns}
    pairs = {(a.class_section_id, a.subject_id) for a in assigns}
    class_recs = [r for r in db.scalars(select(AIRecommendation).where(
        AIRecommendation.target_type == "class", AIRecommendation.target_id.in_(class_ids or [-1]),
        AIRecommendation.status.in_(insights.OPEN)).order_by(AIRecommendation.created_at.desc()))
        if (r.target_id, r.evidence.get("subject_id")) in pairs]
    student_ids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True))))
    my_subjects = {s for _, s in pairs}
    student_recs = [r for r in db.scalars(select(AIRecommendation).where(
        AIRecommendation.target_type == "student", AIRecommendation.target_id.in_(student_ids or [-1]),
        AIRecommendation.status == "pending_review").order_by(AIRecommendation.created_at.desc()).limit(200))
        if r.evidence.get("subject_id") in my_subjects]
    names = {u.id: (u.public_id, u.full_name) for u in db.scalars(select(User).where(User.id.in_(
        [r.target_id for r in student_recs] + [i for r in class_recs for i in r.evidence.get(
            "student_ids_below_threshold", [])] or [-1])))}

    def with_names(r: AIRecommendation) -> dict:
        d = insights.rec_dict(r)
        if r.target_type == "student":
            d["student"] = {"id": names[r.target_id][0], "name": names[r.target_id][1]}
        else:
            d["students_who_may_benefit"] = [{"id": names[i][0], "name": names[i][1]}
                                             for i in r.evidence.get("student_ids_below_threshold", []) if i in names]
        return d

    return {"class": [with_names(r) for r in class_recs], "student": [with_names(r) for r in student_recs]}


class RefreshIn(BaseModel):
    class_id: int


@router.post("/recommendations/refresh")
def refresh_recommendations(body: RefreshIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, body.class_id)
    subjects = {a.subject_id for a in teacher_assignments(db, p.user.id) if a.class_section_id == cs.id}
    recs = insights.refresh_class_recommendations(db, cs, subjects)
    audit(db, "insights.class_refreshed", principal=p, request=request, entity_type="class_section",
          entity_id=cs.id, count=len(recs))
    db.commit()
    return {"generated_or_updated": len(recs)}


class ReviewIn(BaseModel):
    decision: Literal["approve", "dismiss"]
    note: str = Field(default="", max_length=1000)


@router.post("/recommendations/{rec_id}/review")
def review_recommendation(rec_id: int, body: ReviewIn, request: Request, p: Principal = Teacher,
                          db: Session = Depends(get_db)):
    rec = db.get(AIRecommendation, rec_id)
    if rec is None:
        raise not_found("Recommendation")
    subject_id = (rec.evidence or {}).get("subject_id")
    if rec.target_type == "class":
        get_class_for_teacher(db, p, rec.target_id, subject_id)
    elif rec.target_type == "student":
        if not teacher_can_see_student(db, p.user.id, rec.target_id) or subject_id not in {
                a.subject_id for a in teacher_assignments(db, p.user.id)}:
            raise not_found("Recommendation")
    else:
        raise not_found("Recommendation")
    rec.status = "approved" if body.decision == "approve" else "dismissed"
    rec.reviewed_by, rec.reviewed_at, rec.review_note = p.user.id, utcnow(), body.note
    audit(db, "recommendation.reviewed", principal=p, request=request, entity_type="ai_recommendation",
          entity_id=rec.id, decision=body.decision)
    db.commit()
    return insights.rec_dict(rec)


# ------------------------------------------------- learner record views ----

@router.get("/priorities")
def priorities(p: Principal = Teacher, db: Session = Depends(get_db)):
    """Weekly priority list: students with competencies needing practice, with evidence."""
    assigns = teacher_assignments(db, p.user.id)
    rows = learner.weekly_priorities(db, {a.class_section_id for a in assigns}, {a.subject_id for a in assigns})
    labels = {a.class_section_id: a.class_section.label for a in assigns}
    for r in rows:
        r["class"] = labels.get(r["class_id"])
    return {"week_of": (date.today() - timedelta(days=date.today().weekday())).isoformat(), "students": rows}


@router.get("/students/{public_id}/record")
def student_record(public_id: str, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    u = _student_by_public_id(db, p, public_id)
    rec = learner.learner_record(db, u.id, subject_ids={a.subject_id for a in teacher_assignments(db, p.user.id)})
    audit(db, "learner_record.viewed", principal=p, request=request, entity_type="user", entity_id=u.id)
    db.commit()
    return {"student": {"id": u.public_id, "name": u.full_name}, **rec}


@router.get("/classes/{class_id}/ai-interactions")
def flagged_interactions(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    """Supervision view: assistant exchanges flagged by the safety filter."""
    cs = get_class_for_teacher(db, p, class_id)
    rows = db.execute(select(AIInteraction, User).join(User, User.id == AIInteraction.student_user_id).where(
        AIInteraction.class_section_id == cs.id, AIInteraction.flagged.is_(True))
        .order_by(AIInteraction.created_at.desc()).limit(50)).all()
    return [{"id": i.id, "student": {"id": u.public_id, "name": u.full_name}, "question": i.question,
             "answer": i.answer, "reason": i.flag_reason, "at": i.created_at.isoformat()} for i, u in rows]


# ---------------------------------------------------------------- reports ----

class ReportIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=10000)


@router.post("/reports", status_code=201)
def submit_report(body: ReportIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _profile(db, p)
    metrics = {}
    for cid in teacher_class_ids(db, p.user.id):
        s = analytics.class_summary(db, db.get(ClassSection, cid), include_students=False)
        metrics[s["label"]] = {"students": s["students"], "attendance_rate_30d": s["attendance_rate_30d"],
                               "subjects": {x["code"]: x["avg_score_pct"] for x in s["subjects"]}}
    r = SchoolReport(school_id=prof.school_id, submitted_by=p.user.id, period=body.period, title=body.title,
                     body=body.body, metrics=metrics)
    db.add(r)
    db.flush()
    audit(db, "school_report.submitted", principal=p, request=request, entity_type="school_report", entity_id=r.id)
    db.commit()
    return {"id": r.id}


@router.get("/reports")
def my_reports(p: Principal = Teacher, db: Session = Depends(get_db)):
    return [{"id": r.id, "title": r.title, "period": r.period, "status": r.status,
             "submitted_at": r.submitted_at.isoformat()}
            for r in db.scalars(select(SchoolReport).where(SchoolReport.submitted_by == p.user.id)
                                .order_by(SchoolReport.submitted_at.desc()))]


@router.get("/classes/{class_id}/export")
def export_class(class_id: int, request: Request, format: Literal["csv", "xlsx", "pdf"] = "csv",
                 p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    roster_data = roster(class_id, p, db)["students"]
    table = Table(f"Class progress report - {cs.label} ({cs.academic_year}), {cs.school.name}",
                  ["Roll no", "Student", "Attendance (30 days)", "Average score"],
                  [[s["roll_no"], s["name"], s["attendance_30d"], s["avg_score_pct"]] for s in roster_data],
                  [f"Generated {utcnow():%Y-%m-%d %H:%M} UTC by {p.user.full_name}",
                   "Contains student personal data - keep within the school."],
                  classification="CONFIDENTIAL - student records")
    audit(db, "report.exported", principal=p, request=request, entity_type="class_section", entity_id=cs.id,
          format=format)
    db.commit()
    return Response(render(table, format), media_type=MEDIA_TYPES[format],
                    headers={"Content-Disposition": f'attachment; filename="class-{cs.grade}{cs.section}.{format}"',
                             "Cache-Control": "no-store"})


# ------------------------------------------------------- head teacher only ----

def _head(db: Session, p: Principal) -> TeacherProfile:
    prof = _profile(db, p)
    if not prof.is_head_teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Head teacher access required")
    return prof


@router.get("/school/classes")
def school_classes(p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _head(db, p)
    return [{"id": c.id, "label": c.label, "grade": c.grade, "academic_year": c.academic_year}
            for c in db.scalars(select(ClassSection).where(ClassSection.school_id == prof.school_id)
                                .order_by(ClassSection.grade, ClassSection.section))]


class EnrollIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    guardian_name: str = Field(min_length=2, max_length=150)
    guardian_phone: str | None = Field(default=None, max_length=20)
    guardian_consent: bool
    birth_year: int | None = Field(default=None, ge=2000, le=2025)
    gender: Literal["female", "male", "other"] | None = None
    roll_no: int | None = Field(default=None, ge=1, le=999)


@router.post("/school/classes/{class_id}/students", status_code=201)
def head_enroll(class_id: int, body: EnrollIn, request: Request, p: Principal = Teacher,
                db: Session = Depends(get_db)):
    prof = _head(db, p)
    cs = db.get(ClassSection, class_id)
    if cs is None or cs.school_id != prof.school_id:
        raise not_found("Class")
    user, temp = accounts.enroll_student(db, cs=cs, enrolled_by=p.user.id, **body.model_dump())
    audit(db, "student.enrolled", principal=p, request=request, entity_type="user", entity_id=user.id, class_id=cs.id)
    db.commit()
    return {"student": user.public_id, "login_id": user.login_id, "temporary_password": temp}


@router.get("/school/teacher-attendance")
def get_teacher_attendance(on: date = Query(default_factory=date.today), p: Principal = Teacher,
                           db: Session = Depends(get_db)):
    prof = _head(db, p)
    teachers = db.scalars(select(TeacherProfile).where(TeacherProfile.school_id == prof.school_id,
                                                       TeacherProfile.verification_status == "verified")).all()
    marks = {r.person_user_id: r.status for r in db.scalars(select(AttendanceRecord).where(
        AttendanceRecord.school_id == prof.school_id, AttendanceRecord.person_type == "teacher",
        AttendanceRecord.date == on))}
    return {"date": on.isoformat(), "records": [{"teacher": t.user.public_id, "name": t.user.full_name,
                                                 "status": marks.get(t.user_id)} for t in teachers]}


class TeacherAttItem(BaseModel):
    teacher: str = Field(max_length=32)
    status: Literal["present", "absent", "late", "leave"]


class TeacherAttIn(BaseModel):
    date: date
    records: list[TeacherAttItem] = Field(max_length=100)


@router.post("/school/teacher-attendance")
def record_teacher_attendance(body: TeacherAttIn, request: Request, p: Principal = Teacher,
                              db: Session = Depends(get_db)):
    prof = _head(db, p)
    _check_attendance_date(body.date)
    staff = {t.user.public_id: t for t in db.scalars(select(TeacherProfile).where(
        TeacherProfile.school_id == prof.school_id, TeacherProfile.verification_status == "verified"))}
    for item in body.records:
        t = staff.get(item.teacher)
        if t is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Teacher is not at this school")
        rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.person_user_id == t.user_id,
                                                       AttendanceRecord.date == body.date))
        if rec is None:
            rec = AttendanceRecord(person_user_id=t.user_id, person_type="teacher", school_id=prof.school_id,
                                   date=body.date, status=item.status)
            db.add(rec)
        rec.status, rec.recorded_by, rec.recorded_at = item.status, p.user.id, utcnow()
    audit(db, "teacher_attendance.recorded", principal=p, request=request, date=body.date.isoformat(),
          count=len(body.records))
    db.commit()
    return {"saved": len(body.records)}
