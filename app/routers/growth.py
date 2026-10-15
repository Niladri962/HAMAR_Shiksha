"""Student self-improvement and peer help (students) + moderation and study
pairs (teachers). See app/services/studenthelp.py for the rules."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_student, require_teacher
from app.models import (
    ClassSection,
    CurriculumDocument,
    Doubt,
    DoubtReply,
    StudentGoal,
    StudyPair,
    Subject,
    User,
    utcnow,
)
from app.scope import current_enrollment, get_class_for_teacher, not_found, teacher_can_see_student, teacher_class_ids
from app.services import aiclass, learner, studenthelp

router = APIRouter(tags=["student-growth"])
Student = Depends(require_student)
Teacher = Depends(require_teacher)
POSTS_PER_HOUR = 20


def _enr(db: Session, p: Principal):
    enr = current_enrollment(db, p.user.id)
    if enr is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are not enrolled in a class. Please contact your school.")
    return enr


def _post_quota(db: Session, user_id: int) -> None:
    since = utcnow() - timedelta(hours=1)
    n = (db.scalar(select(func.count(Doubt.id)).where(Doubt.student_user_id == user_id, Doubt.created_at >= since)) or 0) + \
        (db.scalar(select(func.count(DoubtReply.id)).where(DoubtReply.author_user_id == user_id,
                                                           DoubtReply.created_at >= since)) or 0)
    if n >= POSTS_PER_HOUR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You have posted a lot this hour. Please try later.")


# ===================================================================== student ==

@router.get("/api/student/growth")
def growth(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enr(db, p)
    goals = db.scalars(select(StudentGoal).where(
        StudentGoal.student_user_id == p.user.id, StudentGoal.status == "active",
        StudentGoal.week_start == studenthelp.week_start(utcnow().date())).order_by(StudentGoal.id)).all()
    open_doubts = db.scalar(select(func.count(Doubt.id)).where(
        Doubt.class_section_id == enr.class_section_id, Doubt.audience == "class", Doubt.status == "open",
        Doubt.student_user_id != p.user.id)) or 0
    return {"level": studenthelp.level_and_streak(db, p.user.id),
            "goals": [studenthelp.goal_dict(db, g) for g in goals],
            "goal_kinds": {k: {"label": v[1], "label_hi": v[2]} for k, v in studenthelp.GOAL_KINDS.items()},
            "revision": studenthelp.revision_summary(db, p.user.id),
            "study_buddies": studenthelp.my_pairs(db, p.user.id),
            "class_doubts_waiting": open_doubts}


class GoalIn(BaseModel):
    kind: Literal["practice", "lessons", "chapters", "revision", "helping", "custom"]
    title: str = Field("", max_length=140)
    target: int = Field(3, ge=1, le=50)


@router.post("/api/student/goals", status_code=201)
def add_goal(body: GoalIn, p: Principal = Student, db: Session = Depends(get_db)):
    _enr(db, p)
    if body.kind == "custom" and len(body.title.strip()) < 3:
        raise HTTPException(422, "Please describe your goal")
    g = studenthelp.create_goal(db, p.user.id, body.kind, body.title, body.target)
    db.commit()
    return studenthelp.goal_dict(db, g)


def _my_goal(db: Session, p: Principal, goal_id: int) -> StudentGoal:
    g = db.get(StudentGoal, goal_id)
    if g is None or g.student_user_id != p.user.id:
        raise not_found("Goal")
    return g


@router.post("/api/student/goals/{goal_id}/tick")
def tick_goal(goal_id: int, p: Principal = Student, db: Session = Depends(get_db)):
    g = _my_goal(db, p, goal_id)
    if g.kind != "custom":
        raise HTTPException(422, "This goal counts your activity automatically")
    g.manual_progress = min(g.target, g.manual_progress + 1)
    db.commit()
    return studenthelp.goal_dict(db, g)


@router.post("/api/student/goals/{goal_id}/archive")
def archive_goal(goal_id: int, p: Principal = Student, db: Session = Depends(get_db)):
    _my_goal(db, p, goal_id).status = "archived"
    db.commit()
    return {"ok": True}


@router.get("/api/student/revision")
def revision(p: Principal = Student, db: Session = Depends(get_db)):
    _enr(db, p)
    subjects = {s.id: s for s in db.scalars(select(Subject))}
    items = studenthelp.due_items(db, p.user.id)
    return {"summary": studenthelp.revision_summary(db, p.user.id),
            "items": [{"id": r.id, "topic": r.topic, "text": r.question["text"], "options": r.question["options"],
                       "times_wrong": r.times_wrong, "correct_streak": r.correct_streak,
                       "subject": subjects[r.subject_id].name if r.subject_id in subjects else None,
                       "subject_hi": subjects[r.subject_id].name_hi if r.subject_id in subjects else None}
                      for r in items]}


class RevisionAnswer(BaseModel):
    choice: int = Field(ge=0, le=10)


@router.post("/api/student/revision/{item_id}/answer")
def revision_answer(item_id: int, body: RevisionAnswer, p: Principal = Student, db: Session = Depends(get_db)):
    _enr(db, p)
    out = studenthelp.answer_revision(db, p.user.id, item_id, body.choice)
    db.commit()
    return out


@router.get("/api/student/library")
def library(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enr(db, p)
    subj_ids = aiclass.class_subject_ids(db, enr.class_section_id)
    read = studenthelp.sections_read(db, p.user.id)
    books = studenthelp.library(db, enr.class_section.grade, list(subj_ids))
    subjects = {s.id: s for s in db.scalars(select(Subject))}
    for b in books:
        s = subjects.get(b["subject_id"])
        b["subject"], b["subject_hi"] = (s.name, s.name_hi) if s else (None, None)
        for sec in b["sections"]:
            sec["read"] = f"{b['id']}|{sec['key']}" in read
    return {"grade": enr.class_section.grade, "books": books}


def _my_book(db: Session, p: Principal, doc_id: int) -> CurriculumDocument:
    enr = _enr(db, p)
    d = db.get(CurriculumDocument, doc_id)
    if (d is None or d.approval_status != "approved" or d.grade != enr.class_section.grade
            or d.subject_id not in aiclass.class_subject_ids(db, enr.class_section_id)):
        raise not_found("Book")
    return d


@router.get("/api/student/library/{doc_id}")
def read_section(doc_id: int, key: str, p: Principal = Student, db: Session = Depends(get_db)):
    d = _my_book(db, p, doc_id)
    return {"document": d.title, "publisher": d.publisher, "is_demo": d.is_demo, "key": key,
            "passages": studenthelp.read_section(db, d, key[:250])}


class ReadIn(BaseModel):
    key: str = Field(min_length=3, max_length=250)


@router.post("/api/student/library/{doc_id}/read")
def mark_read(doc_id: int, body: ReadIn, p: Principal = Student, db: Session = Depends(get_db)):
    d = _my_book(db, p, doc_id)
    if not studenthelp.read_section(db, d, body.key):
        raise HTTPException(422, "Unknown section")
    learner.record_event(db, student_id=p.user.id, event_type="chapter_read",
                         event_uid=f"read-{p.user.id}-{d.id}-{hashlib.sha1(body.key.encode()).hexdigest()[:16]}",
                         payload={"document_id": d.id, "section": body.key,
                                  "summary": f"Read {d.title}: {body.key[2:]}"})
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ doubts --

class DoubtIn(BaseModel):
    audience: Literal["teacher", "class"]
    subject_id: int | None = None
    topic: str = Field("", max_length=120)
    body: str = Field(min_length=5, max_length=600)


@router.get("/api/student/doubts")
def my_doubts(p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enr(db, p)
    return [studenthelp.doubt_dict(db, d, p.user.id, teacher_view=False)
            for d in studenthelp.student_doubts(db, p.user.id, enr.class_section_id)]


@router.post("/api/student/doubts", status_code=201)
def ask_doubt(body: DoubtIn, request: Request, p: Principal = Student, db: Session = Depends(get_db)):
    enr = _enr(db, p)
    if body.subject_id is not None and body.subject_id not in aiclass.class_subject_ids(db, enr.class_section_id):
        raise not_found("Subject")
    _post_quota(db, p.user.id)
    text = f"{body.topic} {body.body}"
    try:
        studenthelp.check_post(text)
    except studenthelp.PostRejected as exc:
        if exc.detail["reason"] == "wellbeing":
            # Never posted publicly: goes privately to the teacher, and the student sees the support message.
            d = Doubt(student_user_id=p.user.id, class_section_id=enr.class_section_id, subject_id=None,
                      audience="teacher", topic="Wellbeing - please check in", body=body.body.strip(), status="open")
            db.add(d)
            audit(db, "doubt.wellbeing_flag", principal=p, request=request, entity_type="doubt")
            db.commit()
        raise
    d = Doubt(student_user_id=p.user.id, class_section_id=enr.class_section_id, subject_id=body.subject_id,
              audience=body.audience, topic=body.topic.strip(), body=body.body.strip())
    db.add(d)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=False)


class ReplyIn(BaseModel):
    body: str = Field(min_length=2, max_length=800)


def _visible_doubt(db: Session, p: Principal, doubt_id: int) -> Doubt:
    enr = _enr(db, p)
    d = db.get(Doubt, doubt_id)
    if d is None or d.class_section_id != enr.class_section_id or (
            d.student_user_id != p.user.id and (d.audience != "class" or d.status == "hidden")):
        raise not_found("Doubt")
    return d


@router.post("/api/student/doubts/{doubt_id}/replies", status_code=201)
def student_reply(doubt_id: int, body: ReplyIn, p: Principal = Student, db: Session = Depends(get_db)):
    d = _visible_doubt(db, p, doubt_id)
    if d.audience == "teacher" and d.student_user_id != p.user.id:
        raise not_found("Doubt")
    if d.status == "resolved":
        raise HTTPException(409, "This doubt is closed")
    _post_quota(db, p.user.id)
    studenthelp.check_post(body.body)
    r = DoubtReply(doubt_id=d.id, author_user_id=p.user.id, author_role="student", body=body.body.strip())
    db.add(r)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=False)


def _reply_for_student(db: Session, p: Principal, reply_id: int) -> tuple[DoubtReply, Doubt]:
    r = db.get(DoubtReply, reply_id)
    if r is None or r.hidden:
        raise not_found("Reply")
    return r, _visible_doubt(db, p, r.doubt_id)


@router.post("/api/student/replies/{reply_id}/accept")
def student_accept(reply_id: int, p: Principal = Student, db: Session = Depends(get_db)):
    r, d = _reply_for_student(db, p, reply_id)
    if d.student_user_id != p.user.id:
        raise HTTPException(403, "Only the student who asked can mark an answer as helpful")
    studenthelp.accept_reply(db, r, p.user.id)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=False)


@router.post("/api/student/replies/{reply_id}/report")
def student_report(reply_id: int, request: Request, p: Principal = Student, db: Session = Depends(get_db)):
    r, _ = _reply_for_student(db, p, reply_id)
    r.reported = True
    audit(db, "doubt.reply_reported", principal=p, request=request, entity_type="doubt_reply", entity_id=r.id)
    db.commit()
    return {"ok": True, "message": "Thank you. Your teacher will check this answer."}


@router.get("/api/student/study-buddies")
def study_buddies(p: Principal = Student, db: Session = Depends(get_db)):
    _enr(db, p)
    return studenthelp.my_pairs(db, p.user.id)


# ===================================================================== teacher ==

@router.get("/api/teacher/help/doubts")
def teacher_doubts(class_id: int | None = None, p: Principal = Teacher, db: Session = Depends(get_db)):
    ids = teacher_class_ids(db, p.user.id)
    if class_id is not None:
        get_class_for_teacher(db, p, class_id)
        ids = {class_id}
    rows = db.scalars(select(Doubt).where(Doubt.class_section_id.in_(ids or [-1]))
                      .order_by((Doubt.status == "open").desc(), Doubt.created_at.desc()).limit(100)).all()
    labels = {c.id: c.label for c in db.scalars(select(ClassSection).where(ClassSection.id.in_(ids or [-1])))}
    out = []
    for d in rows:
        item = studenthelp.doubt_dict(db, d, p.user.id, teacher_view=True)
        item["class"] = labels.get(d.class_section_id)
        out.append(item)
    return out


def _teacher_doubt(db: Session, p: Principal, doubt_id: int) -> Doubt:
    d = db.get(Doubt, doubt_id)
    if d is None or d.class_section_id not in teacher_class_ids(db, p.user.id):
        raise not_found("Doubt")
    return d


@router.post("/api/teacher/help/doubts/{doubt_id}/replies", status_code=201)
def teacher_reply(doubt_id: int, body: ReplyIn, p: Principal = Teacher, db: Session = Depends(get_db)):
    d = _teacher_doubt(db, p, doubt_id)
    r = DoubtReply(doubt_id=d.id, author_user_id=p.user.id, author_role="teacher", body=body.body.strip(),
                   accepted=True)
    db.add(r)
    d.status = "answered"
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=True)


class DoubtStatus(BaseModel):
    status: Literal["open", "resolved", "hidden"]


@router.post("/api/teacher/help/doubts/{doubt_id}/status")
def teacher_doubt_status(doubt_id: int, body: DoubtStatus, request: Request, p: Principal = Teacher,
                         db: Session = Depends(get_db)):
    d = _teacher_doubt(db, p, doubt_id)
    d.status = body.status
    audit(db, "doubt.status", principal=p, request=request, entity_type="doubt", entity_id=d.id, status=body.status)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=True)


def _teacher_reply(db: Session, p: Principal, reply_id: int) -> tuple[DoubtReply, Doubt]:
    r = db.get(DoubtReply, reply_id)
    if r is None:
        raise not_found("Reply")
    return r, _teacher_doubt(db, p, r.doubt_id)


@router.post("/api/teacher/help/replies/{reply_id}/accept")
def teacher_accept(reply_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    r, d = _teacher_reply(db, p, reply_id)
    studenthelp.accept_reply(db, r, p.user.id)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=True)


@router.post("/api/teacher/help/replies/{reply_id}/hide")
def teacher_hide(reply_id: int, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    r, d = _teacher_reply(db, p, reply_id)
    r.hidden, r.accepted = True, False
    audit(db, "doubt.reply_hidden", principal=p, request=request, entity_type="doubt_reply", entity_id=r.id)
    db.commit()
    return studenthelp.doubt_dict(db, d, p.user.id, teacher_view=True)


@router.get("/api/teacher/help/classes/{class_id}/pairs")
def class_pairs(class_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    subjects = {s.id: s.name for s in db.scalars(select(Subject))}
    pairs = []
    for sp in db.scalars(select(StudyPair).where(StudyPair.class_section_id == cs.id, StudyPair.status == "active")):
        pairs.append({"id": sp.id, "topic": sp.topic, "subject": subjects.get(sp.subject_id), "note": sp.note,
                      "helper": db.get(User, sp.helper_user_id).full_name,
                      "learner": db.get(User, sp.learner_user_id).full_name})
    suggestions = studenthelp.pair_suggestions(db, cs)
    for s in suggestions:
        s["subject"] = subjects.get(s["subject_id"])
    return {"class": cs.label, "pairs": pairs, "suggestions": suggestions,
            "rule": "Suggested when a classmate has at least 80% mastery in a topic and another is below 55% "
                    "(3+ answers each). You decide whether to pair them."}


class PairIn(BaseModel):
    helper: str = Field(min_length=8, max_length=64)
    learner: str = Field(min_length=8, max_length=64)
    topic: str = Field(min_length=2, max_length=120)
    subject_id: int | None = None
    note: str = Field("", max_length=300)


@router.post("/api/teacher/help/classes/{class_id}/pairs", status_code=201)
def create_pair(class_id: int, body: PairIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = get_class_for_teacher(db, p, class_id)
    users = []
    for pid in (body.helper, body.learner):
        u = db.scalar(select(User).where(User.public_id == pid))
        enr = current_enrollment(db, u.id) if u else None
        if u is None or enr is None or enr.class_section_id != cs.id or not teacher_can_see_student(db, p.user.id, u.id):
            raise not_found("Student")
        users.append(u)
    if users[0].id == users[1].id:
        raise HTTPException(422, "Choose two different students")
    sp = StudyPair(class_section_id=cs.id, subject_id=body.subject_id, topic=body.topic.strip(),
                   helper_user_id=users[0].id, learner_user_id=users[1].id, created_by=p.user.id, note=body.note.strip())
    db.add(sp)
    db.flush()
    audit(db, "study_pair.created", principal=p, request=request, entity_type="study_pair", entity_id=sp.id)
    db.commit()
    return {"id": sp.id}


@router.post("/api/teacher/help/pairs/{pair_id}/end")
def end_pair(pair_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    sp = db.get(StudyPair, pair_id)
    if sp is None or sp.class_section_id not in teacher_class_ids(db, p.user.id):
        raise not_found("Pair")
    sp.status = "done"
    db.commit()
    return {"ok": True}
