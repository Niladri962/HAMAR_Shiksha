"""Teacher Saathi API: planning, milestones, grounded Q&A, lesson plans,
worksheets, remediation, micro-courses and substitute lessons.

AI output is always a *draft*: teachers edit and approve before use, and
every draft carries the textbook passages it was grounded on."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_teacher
from app.models import (
    AIRecommendation,
    AuditLog,
    ClassSection,
    ClassSession,
    LearningOutcome,
    LessonPlan,
    RemediationPlan,
    Subject,
    TeacherProfile,
    TeacherTrainingModule,
    TeachingMilestone,
    TrainingCompletion,
    User,
    utcnow,
)
from app.scope import get_class_for_teacher, not_found, teacher_assignments
from app.services import learner, pariksha, planning
from app.slm import gyan

router = APIRouter(prefix="/api/teacher/saathi", tags=["teacher-saathi"])
Teacher = Depends(require_teacher)
AI_DAILY_LIMIT = 100


def ai_quota(db: Session, p: Principal) -> None:
    since = utcnow() - timedelta(days=1)
    used = db.scalar(select(func.count(AuditLog.id)).where(
        AuditLog.actor_user_id == p.user.id, AuditLog.action.like("ai.%"), AuditLog.at >= since)) or 0
    if used >= AI_DAILY_LIMIT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily AI request limit reached")


def _teaches(db: Session, p: Principal, grade: int, subject_id: int) -> bool:
    return any(a.class_section.grade == grade and a.subject_id == subject_id for a in teacher_assignments(db, p.user.id))


# ----------------------------------------------------------- planning ----

@router.get("/learning-outcomes")
def learning_outcomes(subject_id: int, grade: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    rows = db.scalars(select(LearningOutcome).where(LearningOutcome.subject_id == subject_id,
                                                    LearningOutcome.grade == grade)
                      .order_by(LearningOutcome.chapter_no, LearningOutcome.code)).all()
    return [{"id": lo.id, "code": lo.code, "chapter_no": lo.chapter_no, "chapter": lo.chapter_title, "topic": lo.topic,
             "description": lo.description, "description_hi": lo.description_hi, "periods": lo.planned_periods,
             "is_demo": lo.is_demo} for lo in rows]


@router.get("/plan")
def plan(class_id: int, subject_id: int, scope: Literal["week", "month", "year"] = "month",
         ref: date | None = None, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id, subject_id)
    created = planning.generate_plan(db, cs, subject_id)
    if created:
        db.commit()
    items = planning.plan_view(db, cs, subject_id, scope=scope, ref=ref)
    cal = planning.calendar_for(db, cs)
    return {"class": cs.label, "scope": scope, "milestones": items,
            "summary": planning.ptl_for_classes(db, [cs.id]),
            "calendar": {"academic_year": cal.academic_year, "start": cal.start_date.isoformat(),
                         "end": cal.end_date.isoformat(), "exam_windows": cal.exam_windows,
                         "is_demo": cal.is_demo} if cal else None}


class TaughtIn(BaseModel):
    lesson_plan_id: int | None = None
    # Optional one-tap record that the lesson used a smart class / ICT lab etc.
    digital_resource_id: int | None = None


@router.post("/milestones/{milestone_id}/taught")
def mark_taught(milestone_id: int, body: TaughtIn, request: Request, p: Principal = Teacher,
                db: Session = Depends(get_db)):
    m = db.get(TeachingMilestone, milestone_id)
    if m is None:
        raise not_found("Milestone")
    get_class_for_teacher(db, p, m.class_section_id, m.subject_id)
    changed = planning.mark_taught(db, m, p.user.id, body.lesson_plan_id)
    usage_id = None
    if body.digital_resource_id is not None:
        from app.models import DigitalResource
        from app.services import digital

        r = db.get(DigitalResource, body.digital_resource_id)
        cs = db.get(ClassSection, m.class_section_id)
        if r is None or r.school_id != cs.school_id:
            raise not_found("Resource")
        usage_id = digital.log_usage(db, resource=r, class_section=cs, teacher_id=p.user.id, subject_id=m.subject_id,
                                     learning_outcome_id=m.learning_outcome_id,
                                     activity=f"Taught {m.learning_outcome.code}").id
    audit(db, "milestone.taught", principal=p, request=request, entity_type="teaching_milestone", entity_id=m.id)
    db.commit()
    return {"id": m.id, "status": m.status, "changed": changed, "digital_usage_id": usage_id}


# ------------------------------------------------------- grounded Q&A ----

class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    subject_id: int | None = None
    grade: int | None = Field(default=None, ge=1, le=12)
    language: Literal["en", "hi"] = "en"


@router.post("/ask")
def ask(body: AskIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    ai_quota(db, p)
    res = gyan.answer_question(db, question=body.question, grade=body.grade, subject_id=body.subject_id,
                               language=body.language, audience="teacher")
    audit(db, "ai.saathi_ask", principal=p, request=request, verified=res.verified, reason=res.reason,
          model=res.model, latency_ms=res.latency_ms)
    db.commit()
    return {"answer": res.answer, "verified": res.verified, "citations": res.citations, "reason": res.reason,
            "ai_generated": res.ai_generated, "model": res.model, "latency_ms": res.latency_ms,
            "related": res.retrieved if not res.verified else []}


# -------------------------------------------------------- lesson plans ----

def _plan_dict(lp: LessonPlan) -> dict:
    return {"id": lp.id, "class_id": lp.class_section_id, "subject": lp.subject.name, "subject_id": lp.subject_id,
            "grade": lp.grade, "topic": lp.topic, "language": lp.language, "title": lp.title, "body": lp.body,
            "sources": lp.sources, "status": lp.status, "ai_generated": lp.ai_generated, "model": lp.model,
            "learning_outcome_id": lp.learning_outcome_id, "created_at": lp.created_at.isoformat(),
            "is_demo": lp.is_demo}


def _own_plan(db: Session, p: Principal, plan_id: int) -> LessonPlan:
    lp = db.get(LessonPlan, plan_id)
    if lp is None or not _teaches(db, p, lp.grade, lp.subject_id):
        raise not_found("Lesson plan")
    if lp.class_section_id:
        get_class_for_teacher(db, p, lp.class_section_id, lp.subject_id)
    return lp


@router.get("/lesson-plans")
def list_plans(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    subjects = {a.subject_id for a in teacher_assignments(db, p.user.id) if a.class_section_id == cs.id}
    rows = db.scalars(select(LessonPlan).where(LessonPlan.class_section_id == cs.id,
                                               LessonPlan.subject_id.in_(subjects or [-1]),
                                               LessonPlan.status != "archived")
                      .order_by(LessonPlan.created_at.desc()).limit(50)).all()
    return [_plan_dict(lp) for lp in rows]


class GenerateIn(BaseModel):
    class_id: int
    subject_id: int
    topic: str = Field(min_length=2, max_length=120)
    learning_outcome_id: int | None = None
    language: Literal["en", "hi"] = "hi"
    minutes: int = Field(default=40, ge=10, le=120)
    notes: str = Field(default="", max_length=500)


@router.post("/lesson-plans/generate", status_code=201)
def generate_plan(body: GenerateIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    ai_quota(db, p)
    cs = get_class_for_teacher(db, p, body.class_id, body.subject_id)
    subject = db.get(Subject, body.subject_id)
    lo = db.get(LearningOutcome, body.learning_outcome_id) if body.learning_outcome_id else None
    d = gyan.draft_lesson_plan(db, subject_name=subject.name, subject_id=subject.id, grade=cs.grade, topic=body.topic,
                               language=body.language, minutes=body.minutes, notes=body.notes,
                               outcome=lo.description if lo else None)
    lp = LessonPlan(class_section_id=cs.id, subject_id=subject.id, grade=cs.grade,
                    learning_outcome_id=lo.id if lo else None, topic=body.topic, language=body.language,
                    title=f"{body.topic} - {cs.label}", body=d.text, sources=d.sources, status="draft",
                    ai_generated=d.ai_generated, model=d.model, created_by=p.user.id)
    db.add(lp)
    db.flush()
    audit(db, "ai.lesson_plan", principal=p, request=request, entity_type="lesson_plan", entity_id=lp.id,
          model=d.model, grounded=len(d.sources))
    db.commit()
    return {**_plan_dict(lp), "note": d.note,
            "notice": "Draft for your review. Check accuracy against the cited pages before approving."}


class EditPlanIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=20000)


@router.put("/lesson-plans/{plan_id}")
def edit_plan(plan_id: int, body: EditPlanIn, p: Principal = Teacher, db: Session = Depends(get_db)):
    lp = _own_plan(db, p, plan_id)
    lp.title, lp.body, lp.status = body.title, body.body, "draft"
    db.commit()
    return _plan_dict(lp)


@router.post("/lesson-plans/{plan_id}/approve")
def approve_plan(plan_id: int, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    lp = _own_plan(db, p, plan_id)
    lp.status, lp.approved_by, lp.approved_at = "approved", p.user.id, utcnow()
    audit(db, "lesson_plan.approved", principal=p, request=request, entity_type="lesson_plan", entity_id=lp.id)
    db.commit()
    return _plan_dict(lp)


# ---------------------------------------------------------- worksheets ----

class WorksheetIn(BaseModel):
    subject_id: int
    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=2, max_length=120)
    learning_outcome_id: int | None = None
    language: Literal["en", "hi"] = "hi"
    count: int = Field(default=5, ge=1, le=10)


@router.post("/worksheet")
def worksheet(body: WorksheetIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    """Draft MCQs from the textbook passages; saved as *draft* bank questions for teacher approval."""
    ai_quota(db, p)
    if not _teaches(db, p, body.grade, body.subject_id):
        raise not_found("Subject")
    subject = db.get(Subject, body.subject_id)
    d = gyan.draft_questions(db, subject_name=subject.name, subject_id=subject.id, grade=body.grade,
                             topic=body.topic, language=body.language, count=body.count)
    saved = []
    for q in (d.data or {}).get("questions", [])[: body.count]:
        try:
            opts = [str(o).strip() for o in q["options"]][:4]
            item = {"subject_id": subject.id, "grade": body.grade, "topic": body.topic, "qtype": "mcq",
                    "text": str(q["text"]).strip()[:500], "options": opts, "correct_option": int(q["answer_index"]),
                    "learning_outcome_id": body.learning_outcome_id, "language": body.language, "difficulty": 2,
                    "rubric": str(q.get("explanation") or "")[:500] or None}
            new = pariksha.create_question(db, item, created_by=p.user.id, source="ai_draft", status_="draft",
                                           ai_generated=True)
            saved.append({"id": new.id, "text": new.text, "options": new.options,
                          "correct_option": item["correct_option"], "explanation": item["rubric"]})
        except (KeyError, TypeError, ValueError, HTTPException):
            continue  # malformed model output is dropped, never repaired silently
    audit(db, "ai.worksheet", principal=p, request=request, model=d.model, drafted=len(saved))
    db.commit()
    return {"drafts": saved, "sources": d.sources, "ai_generated": d.ai_generated, "model": d.model,
            "note": d.text or d.note,
            "notice": "Drafts are not visible to students. Check each answer key, then approve in the question bank."}


# --------------------------------------------------------- remediation ----

def _rem_dict(r: RemediationPlan, db: Session) -> dict:
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(r.student_ids or [-1])))}
    return {"id": r.id, "class_id": r.class_section_id, "topic": r.topic, "status": r.status,
            "plan_text": r.plan_text, "evidence": r.evidence, "sources": r.sources, "ai_generated": r.ai_generated,
            "students": [names[i] for i in r.student_ids if i in names], "created_at": r.created_at.isoformat()}


@router.get("/remediation")
def list_remediation(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    subjects = {a.subject_id for a in teacher_assignments(db, p.user.id) if a.class_section_id == cs.id}
    rows = db.scalars(select(RemediationPlan).where(RemediationPlan.class_section_id == cs.id,
                                                    RemediationPlan.subject_id.in_(subjects or [-1]))
                      .order_by(RemediationPlan.created_at.desc())).all()
    return [_rem_dict(r, db) for r in rows]


@router.post("/remediation/from-recommendation/{rec_id}", status_code=201)
def remediation_from_rec(rec_id: int, request: Request, language: Literal["en", "hi"] = "hi",
                         p: Principal = Teacher, db: Session = Depends(get_db)):
    ai_quota(db, p)
    rec = db.get(AIRecommendation, rec_id)
    if rec is None or rec.target_type != "class":
        raise not_found("Recommendation")
    ev = rec.evidence or {}
    cs = get_class_for_teacher(db, p, rec.target_id, ev.get("subject_id"))
    subject = db.get(Subject, ev["subject_id"])
    evidence_txt = (f"class average mastery {ev.get('class_average_mastery', 0):.0%} on '{ev.get('topic')}', "
                    f"{ev.get('students_below_threshold')} of {ev.get('students_assessed')} students below 60%")
    d = gyan.draft_remediation(db, subject_name=subject.name, subject_id=subject.id, grade=cs.grade,
                               topic=ev["topic"], evidence=evidence_txt, language=language)
    lo_id = db.scalar(select(LearningOutcome.id).where(LearningOutcome.subject_id == subject.id,
                                                       LearningOutcome.grade == cs.grade,
                                                       LearningOutcome.topic.ilike(ev["topic"])).limit(1))
    r = RemediationPlan(class_section_id=cs.id, subject_id=subject.id, learning_outcome_id=lo_id, topic=ev["topic"],
                        student_ids=ev.get("student_ids_below_threshold", []), plan_text=d.text,
                        evidence={**{k: v for k, v in ev.items() if k != "key"}, "summary": evidence_txt},
                        sources=d.sources, ai_generated=d.ai_generated, ai_recommendation_id=rec.id)
    db.add(r)
    db.flush()
    audit(db, "ai.remediation_plan", principal=p, request=request, entity_type="remediation_plan", entity_id=r.id,
          model=d.model)
    db.commit()
    return _rem_dict(r, db)


class RemStatusIn(BaseModel):
    status: Literal["approved", "completed", "dismissed"]
    plan_text: str | None = Field(default=None, max_length=20000)


@router.post("/remediation/{plan_id}/status")
def remediation_status(plan_id: int, body: RemStatusIn, request: Request, p: Principal = Teacher,
                       db: Session = Depends(get_db)):
    r = db.get(RemediationPlan, plan_id)
    if r is None:
        raise not_found("Remediation plan")
    get_class_for_teacher(db, p, r.class_section_id, r.subject_id)
    if body.plan_text:
        r.plan_text = body.plan_text
    r.status = body.status
    if body.status == "approved":
        r.approved_by = p.user.id
        for sid in r.student_ids:  # an approved intervention becomes part of each learner record
            learner.record_event(db, student_id=sid, event_type="intervention", recorded_by=p.user.id,
                                 event_uid=f"remediation-{r.id}-{sid}",
                                 payload={"remediation_plan_id": r.id, "topic": r.topic,
                                          "summary": f"Small-group remediation: {r.topic}"})
    if body.status == "completed":
        r.completed_at = utcnow()
    audit(db, "remediation." + body.status, principal=p, request=request, entity_type="remediation_plan", entity_id=r.id)
    db.commit()
    return _rem_dict(r, db)


# ------------------------------------------------------ micro-courses ----

@router.get("/training")
def training(p: Principal = Teacher, db: Session = Depends(get_db)):
    done = {c.module_id: c for c in db.scalars(select(TrainingCompletion).where(
        TrainingCompletion.teacher_user_id == p.user.id))}
    mine = {a.subject_id for a in teacher_assignments(db, p.user.id)}
    quals = set(db.get(TeacherProfile, p.user.id).subject_qualifications or [])
    codes = {s.id: s.code for s in db.scalars(select(Subject))}
    mastery = _class_mastery_by_subject(db, p.user.id)
    out = []
    for m in db.scalars(select(TeacherTrainingModule).where(TeacherTrainingModule.status == "approved")
                        .order_by(TeacherTrainingModule.code)):
        # Recommended: a subject the teacher teaches without a recorded qualification in it,
        # or where the teacher's own students are below the "learned" level.
        reasons = []
        if m.subject_id in mine and codes.get(m.subject_id) not in quals:
            reasons.append("You teach this subject without a recorded qualification in it.")
        avg = mastery.get(m.subject_id)
        if avg is not None and avg < planning.LEARNED_AT:
            reasons.append(f"Your students' average mastery in this subject is {round(avg * 100)}%.")
        out.append({"id": m.id, "code": m.code, "title": m.title, "title_hi": m.title_hi, "area": m.competency_area,
                    "minutes": m.duration_minutes, "subject_id": m.subject_id, "is_demo": m.is_demo,
                    "completed": m.id in done, "score": done[m.id].score if m.id in done else None,
                    "recommended": bool(reasons) and m.id not in done, "reasons": reasons})
    return sorted(out, key=lambda x: (not x["recommended"], x["completed"], x["code"]))


def _class_mastery_by_subject(db: Session, teacher_id: int) -> dict[int, float]:
    """Mean competency mastery of the teacher's own students, per subject they teach."""
    from app.models import LearnerCompetency, StudentEnrollment

    out = {}
    for a_subject, class_ids in _group_assignments(teacher_assignments(db, teacher_id)).items():
        sids = select(StudentEnrollment.student_user_id).where(StudentEnrollment.class_section_id.in_(class_ids),
                                                               StudentEnrollment.active.is_(True))
        avg = db.scalar(select(func.avg(LearnerCompetency.mastery)).join(
            LearningOutcome, LearningOutcome.id == LearnerCompetency.learning_outcome_id).where(
            LearnerCompetency.student_user_id.in_(sids), LearningOutcome.subject_id == a_subject,
            LearnerCompetency.attempted >= 3))
        if avg is not None:
            out[a_subject] = avg
    return out


def _group_assignments(assigns) -> dict[int, list[int]]:
    g: dict[int, list[int]] = {}
    for a in assigns:
        g.setdefault(a.subject_id, []).append(a.class_section_id)
    return g


@router.get("/training/{module_id}")
def training_module(module_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    m = db.get(TeacherTrainingModule, module_id)
    if m is None or m.status != "approved":
        raise not_found("Module")
    c = dict(m.content or {})
    c["check"] = [{"q": q["q"], "options": q["options"]} for q in c.get("check", [])]  # keys stay server-side
    return {"id": m.id, "title": m.title, "title_hi": m.title_hi, "minutes": m.duration_minutes, "content": c,
            "is_demo": m.is_demo}


class TrainingIn(BaseModel):
    answers: list[int] = Field(default_factory=list, max_length=20)


@router.post("/training/{module_id}/complete")
def complete_training(module_id: int, body: TrainingIn, request: Request, p: Principal = Teacher,
                      db: Session = Depends(get_db)):
    m = db.get(TeacherTrainingModule, module_id)
    if m is None or m.status != "approved":
        raise not_found("Module")
    check = (m.content or {}).get("check", [])
    correct = sum(1 for q, a in zip(check, body.answers) if q["answer"] == a)
    score = round(correct / len(check), 4) if check else None
    c = db.scalar(select(TrainingCompletion).where(TrainingCompletion.teacher_user_id == p.user.id,
                                                   TrainingCompletion.module_id == m.id))
    if c is None:
        c = TrainingCompletion(teacher_user_id=p.user.id, module_id=m.id, score=score)
        db.add(c)
    else:
        c.score = max(c.score or 0, score or 0)
    audit(db, "training.completed", principal=p, request=request, entity_type="training_module", entity_id=m.id,
          score=score)
    db.commit()
    return {"score": score, "correct": correct, "total": len(check)}


# --------------------------------------------------- substitute lesson ----

class SubstituteIn(BaseModel):
    class_id: int
    lesson_plan_id: int
    notes: str = Field(default="", max_length=500)
    digital_resource_id: int | None = None  # e.g. the smart class the lesson is shown on


@router.post("/substitute", status_code=201)
def launch_substitute(body: SubstituteIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    """A head teacher (school supervisor) launches an approved lesson plan for a
    class whose subject teacher is absent. Students see it as a supervised lesson."""
    prof = db.get(TeacherProfile, p.user.id)
    cs = db.get(ClassSection, body.class_id)
    if cs is None or cs.school_id != prof.school_id:
        raise not_found("Class")
    if not prof.is_head_teacher:
        get_class_for_teacher(db, p, cs.id)  # otherwise only for one's own class
    lp = db.get(LessonPlan, body.lesson_plan_id)
    if lp is None or lp.status != "approved" or lp.grade != cs.grade:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose an approved lesson plan for this class level")
    s = ClassSession(class_section_id=cs.id, lesson_plan_id=lp.id, mode="substitute", launched_by=p.user.id,
                     notes=body.notes)
    db.add(s)
    db.flush()
    if body.digital_resource_id is not None:
        from app.models import DigitalResource
        from app.services import digital

        r = db.get(DigitalResource, body.digital_resource_id)
        if r is None or r.school_id != cs.school_id:
            raise not_found("Resource")
        digital.log_usage(db, resource=r, class_section=cs, teacher_id=p.user.id, subject_id=lp.subject_id,
                          learning_outcome_id=lp.learning_outcome_id, activity=f"AI-supported lesson: {lp.title}"[:200],
                          source="ai_class")
    audit(db, "substitute_lesson.launched", principal=p, request=request, entity_type="class_session", entity_id=s.id,
          class_id=cs.id, lesson_plan_id=lp.id)
    db.commit()
    return {"id": s.id, "class": cs.label, "title": lp.title}


@router.get("/approved-plans")
def approved_plans(p: Principal = Teacher, db: Session = Depends(get_db)):
    """Approved plans in the teacher's school (for the substitute workflow)."""
    prof = db.get(TeacherProfile, p.user.id)
    class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.school_id == prof.school_id)))
    rows = db.scalars(select(LessonPlan).where(LessonPlan.status == "approved",
                                               LessonPlan.class_section_id.in_(class_ids or [-1]))
                      .order_by(LessonPlan.grade, LessonPlan.topic)).all()
    return [_plan_dict(lp) for lp in rows]


@router.post("/substitute/{session_id}/end")
def end_substitute(session_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    s = db.get(ClassSession, session_id)
    prof = db.get(TeacherProfile, p.user.id)
    if s is None or db.get(ClassSection, s.class_section_id).school_id != prof.school_id:
        raise not_found("Session")
    s.ended_at = utcnow()
    db.commit()
    return {"ok": True}
