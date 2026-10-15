"""Progress grades, attendance follow-up, digital-resource use and recognition
for teachers and students. Admin views of the same data live in admin.py
(Command Centre). Logic: app/services/monitoring.py, digital.py, recognition.py."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_student, require_teacher
from app.models import (
    Appreciation,
    ClassSection,
    DigitalResource,
    DigitalUsage,
    LearningOutcome,
    School,
    StudentEnrollment,
    Subject,
    TeacherProfile,
    User,
    utcnow,
)
from app.scope import current_enrollment, get_class_for_teacher, not_found, teacher_assignments, teacher_can_see_student
from app.services import digital, monitoring, recognition

router = APIRouter(tags=["engage"])
Teacher = Depends(require_teacher)
Student = Depends(require_student)
APPRECIATIONS_PER_DAY = 30


def _profile(db: Session, p: Principal) -> TeacherProfile:
    return db.get(TeacherProfile, p.user.id)


# ============================================================ teacher ====

@router.get("/api/teacher/progress-grades")
def teacher_progress_grades(scope: Literal["mine", "school"] = "mine", p: Principal = Teacher,
                            db: Session = Depends(get_db)):
    """Planned / taught / learned grade per class-subject, with corrective actions.
    `scope=school` (head teacher only) covers every class in the school."""
    prof = _profile(db, p)
    if scope == "school":
        if not prof.is_head_teacher:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Head teacher only")
        class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.school_id == prof.school_id)))
        rows = monitoring.class_subject_progress(db, class_ids)
    else:
        assigns = teacher_assignments(db, p.user.id)
        pairs = {(a.class_section_id, a.subject_id) for a in assigns}
        rows = [r for r in monitoring.class_subject_progress(db, list({c for c, _ in pairs}), None,
                                                              {s for _, s in pairs})
                if (r["class_id"], r["subject_id"]) in pairs]
    school = monitoring.school_grades(db, [db.get(School, prof.school_id)])[0] if scope == "school" else None
    return {"rows": rows, "school": school, "definition": monitoring.GRADE_DEFINITION}


@router.get("/api/teacher/classes/{class_id}/attendance-risk")
def class_attendance_risk(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    get_class_for_teacher(db, p, class_id)
    # The teacher already sees every child by name, so small groups need not be hidden here.
    return monitoring.attendance_risk(db, [class_id], min_group=1)


# ------------------------------------------------------- digital resources ----

class UsageIn(BaseModel):
    resource_id: int
    class_id: int
    subject_id: int
    learning_outcome_id: int | None = None
    minutes: int = Field(default=35, ge=5, le=240)
    activity: str = Field(default="", max_length=200)
    used_on: date | None = None


class ResourceIn(BaseModel):
    kind: Literal["ict_lab", "smart_class", "digital_library", "language_lab", "tablets"]
    label: str = Field(min_length=2, max_length=120)
    devices: int = Field(default=1, ge=1, le=500)
    target_sessions_per_week: int = Field(default=10, ge=1, le=60)
    installed_year: int | None = Field(default=None, ge=2000, le=2030)


class ResourceStatusIn(BaseModel):
    status: Literal["working", "not_working"]
    note: str = Field(default="", max_length=300)


@router.get("/api/teacher/digital")
def teacher_digital(p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _profile(db, p)
    res = db.scalars(select(DigitalResource).where(DigitalResource.school_id == prof.school_id)
                     .order_by(DigitalResource.kind, DigitalResource.label)).all()
    mine = db.execute(select(DigitalUsage, DigitalResource.label, ClassSection, Subject.name).join(
        DigitalResource, DigitalResource.id == DigitalUsage.resource_id).join(
        ClassSection, ClassSection.id == DigitalUsage.class_section_id).outerjoin(
        Subject, Subject.id == DigitalUsage.subject_id).where(DigitalUsage.teacher_user_id == p.user.id)
        .order_by(DigitalUsage.used_on.desc(), DigitalUsage.id.desc()).limit(15)).all()
    summary = digital.utilisation(db, [prof.school_id])
    return {"resources": [digital.resource_dict(r) for r in res],
            "school": {k: summary[k] for k in ("sessions", "aligned_rate", "by_kind", "gaps", "rows", "definition")},
            "my_recent": [{"id": u.id, "resource": label, "class": cs.label, "subject": subj, "used_on": u.used_on.isoformat(),
                           "minutes": u.minutes, "activity": u.activity, "aligned": u.learning_outcome_id is not None,
                           "source": u.source} for u, label, cs, subj in mine],
            "is_head_teacher": prof.is_head_teacher}


@router.post("/api/teacher/digital/usage", status_code=201)
def log_digital_usage(body: UsageIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, body.class_id, body.subject_id)
    r = db.get(DigitalResource, body.resource_id)
    if r is None or r.school_id != _profile(db, p).school_id:
        raise not_found("Resource")
    if body.used_on and (body.used_on > date.today() or body.used_on < date.today() - timedelta(days=14)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Date must be within the last 14 days")
    if body.learning_outcome_id is not None:
        lo = db.get(LearningOutcome, body.learning_outcome_id)
        if lo is None or lo.subject_id != body.subject_id or lo.grade != cs.grade:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Learning outcome does not match the class and subject")
    u = digital.log_usage(db, resource=r, class_section=cs, teacher_id=p.user.id, subject_id=body.subject_id,
                          learning_outcome_id=body.learning_outcome_id, minutes=body.minutes,
                          activity=body.activity, used_on=body.used_on)
    audit(db, "digital.usage_logged", principal=p, request=request, entity_type="digital_usage", entity_id=u.id)
    db.commit()
    return {"id": u.id}


@router.post("/api/teacher/digital/resources", status_code=201)
def add_resource(body: ResourceIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _profile(db, p)
    if not prof.is_head_teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Head teacher only")
    r = DigitalResource(school_id=prof.school_id, **body.model_dump())
    db.add(r)
    db.flush()
    audit(db, "digital.resource_added", principal=p, request=request, entity_type="digital_resource", entity_id=r.id)
    db.commit()
    return digital.resource_dict(r)


@router.post("/api/teacher/digital/resources/{resource_id}/status")
def resource_status(resource_id: int, body: ResourceStatusIn, request: Request, p: Principal = Teacher,
                    db: Session = Depends(get_db)):
    """Any teacher of the school can report a fault or a repair (audited)."""
    r = db.get(DigitalResource, resource_id)
    if r is None or r.school_id != _profile(db, p).school_id:
        raise not_found("Resource")
    r.status, r.status_note, r.updated_at = body.status, body.note, utcnow()
    audit(db, "digital.status_changed", principal=p, request=request, entity_type="digital_resource",
          entity_id=r.id, status=body.status)
    db.commit()
    return digital.resource_dict(r)


@router.get("/api/teacher/learning-outcomes")
def outcomes_for_class(class_id: int, subject_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id, subject_id)
    return [{"id": lo.id, "code": lo.code, "topic": lo.topic, "description": lo.description}
            for lo in db.scalars(select(LearningOutcome).where(LearningOutcome.subject_id == subject_id,
                                                               LearningOutcome.grade == cs.grade)
                                 .order_by(LearningOutcome.chapter_no, LearningOutcome.code))]


# ------------------------------------------------------------ recognition ----

class AppreciateIn(BaseModel):
    category: str = Field(max_length=20)
    message: str = Field(default="", max_length=300)


def _appreciation_quota(db: Session, giver_id: int) -> None:
    n = db.scalar(select(func.count(Appreciation.id)).where(
        Appreciation.giver_user_id == giver_id, Appreciation.created_at >= utcnow() - timedelta(days=1))) or 0
    if n >= APPRECIATIONS_PER_DAY:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily appreciation limit reached")


def _check_message(text: str) -> None:
    from app.services.studenthelp import check_post

    if text.strip():
        check_post(text)


@router.get("/api/teacher/recognition")
def teacher_recognition(p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = _profile(db, p)
    class_ids = list({a.class_section_id for a in teacher_assignments(db, p.user.id)})
    sids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True))))
    imp = recognition.improvers(db, sids, limit=6)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([s for s, _ in imp] or [-1])))}
    given = db.execute(select(Appreciation, User.full_name).join(User, User.id == Appreciation.recipient_user_id).where(
        Appreciation.giver_user_id == p.user.id).order_by(Appreciation.created_at.desc()).limit(10)).all()
    colleagues = []
    if prof.is_head_teacher:
        colleagues = [{"public_id": t.user.public_id, "name": t.user.full_name}
                      for t in db.scalars(select(TeacherProfile).where(
                          TeacherProfile.school_id == prof.school_id, TeacherProfile.user_id != p.user.id,
                          TeacherProfile.verification_status == "verified"))]
    return {"badges": recognition.teacher_badges(db, p.user.id),
            "received": recognition.appreciations_for(db, p.user.id),
            "improvers": [{"public_id": users[s].public_id, "name": users[s].full_name, "gain_points": g} for s, g in imp],
            "given": [{**recognition.appreciation_dict(db, a, show_giver=False), "to": name} for a, name in given],
            "student_categories": [{"key": k, "label": v[0], "label_hi": v[1]} for k, v in recognition.STUDENT_CATEGORIES.items()],
            "teacher_categories": [{"key": k, "label": v[0], "label_hi": v[1]} for k, v in recognition.TEACHER_CATEGORIES.items()],
            "colleagues": colleagues,
            "certificate": {"name": p.user.full_name, "school": db.get(School, prof.school_id).name}}


@router.post("/api/teacher/students/{public_id}/appreciate", status_code=201)
def appreciate_student(public_id: str, body: AppreciateIn, request: Request, p: Principal = Teacher,
                       db: Session = Depends(get_db)):
    if body.category not in recognition.STUDENT_CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category")
    user = db.scalar(select(User).where(User.public_id == public_id))
    if user is None or not teacher_can_see_student(db, p.user.id, user.id):
        raise not_found("Student")
    _appreciation_quota(db, p.user.id)
    _check_message(body.message)
    a = Appreciation(recipient_user_id=user.id, giver_user_id=p.user.id, giver_role="teacher",
                     category=body.category, message=body.message.strip())
    db.add(a)
    db.flush()
    audit(db, "appreciation.given", principal=p, request=request, entity_type="appreciation", entity_id=a.id)
    db.commit()
    return {"id": a.id}


@router.post("/api/teacher/colleagues/{public_id}/appreciate", status_code=201)
def appreciate_colleague(public_id: str, body: AppreciateIn, request: Request, p: Principal = Teacher,
                         db: Session = Depends(get_db)):
    prof = _profile(db, p)
    if not prof.is_head_teacher:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Head teacher only")
    if body.category not in recognition.TEACHER_CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category")
    user = db.scalar(select(User).where(User.public_id == public_id))
    tp = db.get(TeacherProfile, user.id) if user else None
    if tp is None or tp.school_id != prof.school_id or user.id == p.user.id:
        raise not_found("Teacher")
    _appreciation_quota(db, p.user.id)
    _check_message(body.message)
    a = Appreciation(recipient_user_id=user.id, giver_user_id=p.user.id, giver_role="head_teacher",
                     category=body.category, message=body.message.strip())
    db.add(a)
    db.flush()
    audit(db, "appreciation.given", principal=p, request=request, entity_type="appreciation", entity_id=a.id)
    db.commit()
    return {"id": a.id}


# ============================================================ student ====

@router.get("/api/student/recognition")
def student_recognition(p: Principal = Student, db: Session = Depends(get_db)):
    enr = current_enrollment(db, p.user.id)
    cs = enr.class_section if enr else None
    school = db.get(School, cs.school_id) if cs else None
    return {"badges": recognition.student_badges(db, p.user.id),
            "challenge": recognition.weekly_challenge(db, p.user.id),
            "appreciations": recognition.appreciations_for(db, p.user.id),
            "certificate": {"name": p.user.full_name, "class": cs.label if cs else "",
                            "school": school.name if school else "", "udise": school.official_code if school else ""},
            "note": "Most badges reward improvement, effort and regularity, not only marks."}
