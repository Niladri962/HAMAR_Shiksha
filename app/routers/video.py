"""AI video lessons (see app/services/videolesson.py).

Teachers: a class's own subject teacher, or the head teacher for any class in
the school (covering an absent teacher), gives a topic; Gyan SLM drafts the
lesson; the teacher edits and publishes it. Students of that class watch the
published lessons; finishing one is recorded in the learner record."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_student, require_teacher
from app.models import ClassSection, LearnerEvent, Subject, TeacherClassAssignment, TeacherProfile, VideoLesson
from app.routers.saathi import ai_quota
from app.scope import current_enrollment, get_class_for_teacher, not_found, teacher_class_ids
from app.services import learner, videolesson

router = APIRouter(tags=["video-lessons"])
Teacher = Depends(require_teacher)
Student = Depends(require_student)


def _uid(lesson_id: int, student_id: int) -> str:
    return f"video-{lesson_id}-{student_id}"


def _class_for(db: Session, p: Principal, class_id: int, subject_id: int) -> ClassSection:
    """Subject teacher of the class, or the head teacher for any class/subject taught in the school."""
    prof = db.get(TeacherProfile, p.user.id)
    cs = db.get(ClassSection, class_id)
    if cs is None or prof is None or cs.school_id != prof.school_id:
        raise not_found("Class")
    if prof.is_head_teacher:
        taught = db.scalar(select(TeacherClassAssignment.id).where(
            TeacherClassAssignment.class_section_id == cs.id, TeacherClassAssignment.subject_id == subject_id,
            TeacherClassAssignment.active.is_(True)).limit(1))
        if taught is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This subject is not taught in that class")
        return cs
    return get_class_for_teacher(db, p, class_id, subject_id)


def _lesson_for_teacher(db: Session, p: Principal, lesson_id: int) -> VideoLesson:
    v = db.get(VideoLesson, lesson_id)
    if v is None:
        raise not_found("Video lesson")
    _class_for(db, p, v.class_section_id, v.subject_id)
    return v


def _out(db: Session, v: VideoLesson, **kw) -> dict:
    return videolesson.lesson_dict(v, subject=db.get(Subject, v.subject_id), cs=db.get(ClassSection, v.class_section_id), **kw)


def _watched(db: Session, lesson_id: int) -> int:
    return db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.event_uid.like(f"video-{lesson_id}-%"))) or 0


# ===================================================================== teacher ==

class GenerateIn(BaseModel):
    class_id: int
    subject_id: int
    topic: str = Field(min_length=3, max_length=160)
    language: Literal["hi", "en"] = "hi"
    reason: Literal["teacher_absent", "revision", "catch_up"] = "teacher_absent"


class SceneIn(BaseModel):
    heading: str = Field(min_length=1, max_length=90)
    narration: str = Field(min_length=10, max_length=700)
    points: list[str] = Field(default_factory=list, max_length=4)
    visual: str = Field(default="📘", max_length=4)


class QuizIn(BaseModel):
    question: str = Field(min_length=3, max_length=200)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(default="", max_length=200)


class EditIn(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    scenes: list[SceneIn] = Field(min_length=1, max_length=videolesson.MAX_SCENES + 2)
    quiz: list[QuizIn] = Field(default_factory=list, max_length=3)


@router.get("/api/teacher/video-lessons/options")
def options(p: Principal = Teacher, db: Session = Depends(get_db)):
    """Classes and subjects this teacher may make lessons for (head teacher: the whole school)."""
    prof = db.get(TeacherProfile, p.user.id)
    q = (select(ClassSection, Subject).join(TeacherClassAssignment, TeacherClassAssignment.class_section_id == ClassSection.id)
         .join(Subject, Subject.id == TeacherClassAssignment.subject_id).where(TeacherClassAssignment.active.is_(True)))
    q = q.where(ClassSection.school_id == prof.school_id) if prof.is_head_teacher else         q.where(TeacherClassAssignment.teacher_user_id == p.user.id)
    out: dict[int, dict] = {}
    for cs, subj in db.execute(q.order_by(ClassSection.grade, ClassSection.section, Subject.name)):
        c = out.setdefault(cs.id, {"id": cs.id, "label": cs.label, "grade": cs.grade, "subjects": []})
        if all(x["id"] != subj.id for x in c["subjects"]):
            c["subjects"].append({"id": subj.id, "name": subj.name, "name_hi": subj.name_hi})
    return {"classes": list(out.values()), "is_head_teacher": prof.is_head_teacher}


@router.post("/api/teacher/video-lessons/generate", status_code=201)
def generate(body: GenerateIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    cs = _class_for(db, p, body.class_id, body.subject_id)
    ai_quota(db, p)
    subject = db.get(Subject, body.subject_id)
    v = videolesson.generate(db, cs=cs, subject=subject, topic=body.topic.strip(), language=body.language,
                             reason=body.reason, created_by=p.user.id)
    if not v.scenes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, v.note)
    db.add(v)
    db.flush()
    audit(db, "ai.video_lesson_drafted" if v.ai_generated else "video_lesson.drafted", principal=p, request=request,
          entity_type="video_lesson", entity_id=v.id, class_id=cs.id, ai=v.ai_generated)
    db.commit()
    return _out(db, v)


@router.get("/api/teacher/video-lessons")
def list_lessons(p: Principal = Teacher, db: Session = Depends(get_db)):
    prof = db.get(TeacherProfile, p.user.id)
    if prof.is_head_teacher:
        class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.school_id == prof.school_id)))
    else:
        class_ids = list(teacher_class_ids(db, p.user.id))
    rows = db.scalars(select(VideoLesson).where(VideoLesson.class_section_id.in_(class_ids or [-1]),
                                                VideoLesson.status != "archived")
                      .order_by(VideoLesson.created_at.desc()).limit(50)).all()
    return [_out(db, v, watched=_watched(db, v.id)) for v in rows]


@router.get("/api/teacher/video-lessons/{lesson_id}")
def get_lesson(lesson_id: int, p: Principal = Teacher, db: Session = Depends(get_db)):
    v = _lesson_for_teacher(db, p, lesson_id)
    return _out(db, v, watched=_watched(db, v.id))


@router.put("/api/teacher/video-lessons/{lesson_id}")
def edit_lesson(lesson_id: int, body: EditIn, request: Request, p: Principal = Teacher, db: Session = Depends(get_db)):
    v = _lesson_for_teacher(db, p, lesson_id)
    title, scenes, quiz = videolesson.normalise(body.model_dump())
    if not scenes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each scene needs a heading and some narration")
    v.title, v.scenes, v.quiz = title or v.title, scenes, quiz
    audit(db, "video_lesson.edited", principal=p, request=request, entity_type="video_lesson", entity_id=v.id)
    db.commit()
    return _out(db, v)


@router.post("/api/teacher/video-lessons/{lesson_id}/{action}")
def lesson_action(lesson_id: int, action: Literal["publish", "unpublish", "archive"], request: Request,
                  p: Principal = Teacher, db: Session = Depends(get_db)):
    v = _lesson_for_teacher(db, p, lesson_id)
    if action == "publish":
        videolesson.publish(v, p.user.id)
    else:
        v.status = "draft" if action == "unpublish" else "archived"
    audit(db, f"video_lesson.{action}", principal=p, request=request, entity_type="video_lesson", entity_id=v.id)
    db.commit()
    return _out(db, v)


# ===================================================================== student ==

def _student_lesson(db: Session, p: Principal, lesson_id: int) -> VideoLesson:
    enr = current_enrollment(db, p.user.id)
    v = db.get(VideoLesson, lesson_id)
    if enr is None or v is None or v.status != "published" or v.class_section_id != enr.class_section_id:
        raise not_found("Video lesson")
    return v


@router.get("/api/student/video-lessons")
def student_lessons(p: Principal = Student, db: Session = Depends(get_db)):
    enr = current_enrollment(db, p.user.id)
    if enr is None:
        return []
    rows = db.scalars(select(VideoLesson).where(VideoLesson.class_section_id == enr.class_section_id,
                                                VideoLesson.status == "published")
                      .order_by(VideoLesson.published_at.desc()).limit(30)).all()
    seen = set(db.scalars(select(LearnerEvent.event_uid).where(
        LearnerEvent.event_uid.in_([_uid(v.id, p.user.id) for v in rows] or ["-"]))))
    return [{**_out(db, v, for_student=True), "watched": _uid(v.id, p.user.id) in seen} for v in rows]


@router.get("/api/student/video-lessons/{lesson_id}")
def student_lesson(lesson_id: int, p: Principal = Student, db: Session = Depends(get_db)):
    return _out(db, _student_lesson(db, p, lesson_id), for_student=True)


class WatchedIn(BaseModel):
    quiz_correct: int = Field(default=0, ge=0, le=3)
    quiz_total: int = Field(default=0, ge=0, le=3)


@router.post("/api/student/video-lessons/{lesson_id}/watched")
def watched(lesson_id: int, body: WatchedIn, p: Principal = Student, db: Session = Depends(get_db)):
    v = _student_lesson(db, p, lesson_id)
    _, created = learner.record_event(
        db, student_id=p.user.id, event_type="lesson_completed", event_uid=_uid(v.id, p.user.id),
        payload={"video_lesson_id": v.id, "subject_id": v.subject_id, "topic": v.topic,
                 "quiz_correct": min(body.quiz_correct, body.quiz_total), "quiz_total": body.quiz_total,
                 "summary": f"Watched video lesson: {v.title}"})
    db.commit()
    return {"ok": True, "first_time": created}
