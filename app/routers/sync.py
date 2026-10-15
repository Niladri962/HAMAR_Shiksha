"""Offline synchronisation API (store-and-forward)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, get_principal
from app.models import (
    Assessment,
    AssessmentResult,
    LessonPlan,
    SynchronizationEvent,
    TeachingMilestone,
    User,
    StudentEnrollment,
)
from app.scope import current_enrollment, teacher_assignments
from app.services import pariksha, sync

router = APIRouter(prefix="/api/sync", tags=["sync"])


class EventIn(BaseModel):
    event_uid: str = Field(min_length=8, max_length=64)
    type: str = Field(max_length=30)
    created_at: str = Field(max_length=40)
    payload: dict


class PushIn(BaseModel):
    device_uid: str = Field(min_length=8, max_length=64)
    profile: Literal["browser", "school_pc", "smart_class", "android"] = "browser"
    app_version: str | None = Field(default=None, max_length=30)
    events: list[EventIn] = Field(max_length=sync.MAX_EVENTS_PER_PUSH)


@router.post("/push")
def push(body: PushIn, request: Request, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if p.user.must_change_password:
        raise HTTPException(403, "Password change required before continuing")
    device = sync.device_for(db, p, body.device_uid, body.profile, body.app_version)
    results = sync.push(db, p, device, [e.model_dump() for e in body.events])
    if results:
        audit(db, "sync.push", principal=p, request=request, entity_type="device", entity_id=device.id,
              accepted=sum(r["status"] == "accepted" for r in results),
              other=[r for r in results if r["status"] not in ("accepted", "duplicate")][:20])
    db.commit()
    return {"results": results, "server_time": device.last_sync_at.isoformat() + "Z"}


@router.get("/pull")
def pull(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Offline bundle for the signed-in user, built with the same scope rules
    as the online APIs. Answer keys are never included."""
    if p.user.must_change_password:
        raise HTTPException(403, "Password change required before continuing")
    if p.portal == "student":
        enr = current_enrollment(db, p.user.id)
        if enr is None:
            return {"portal": "student", "assessments": []}
        done = set(db.scalars(select(AssessmentResult.assessment_id).where(
            AssessmentResult.student_user_id == p.user.id)))
        rows = db.scalars(select(Assessment).where(Assessment.class_section_id == enr.class_section_id,
                                                   Assessment.published.is_(True), Assessment.kind != "offline")).all()
        return {"portal": "student", "assessments": [
            {"id": a.id, "title": a.title, "subject": a.subject.name, "questions": [pariksha.public_item(q) for q in a.questions]}
            for a in rows if a.id not in done]}
    if p.portal == "teacher":
        assigns = teacher_assignments(db, p.user.id)
        class_ids = {a.class_section_id for a in assigns}
        rosters = {}
        for cid in class_ids:
            rosters[cid] = [{"student": u.public_id, "name": u.full_name, "roll_no": e.roll_no}
                            for e, u in db.execute(select(StudentEnrollment, User)
                                                   .join(User, User.id == StudentEnrollment.student_user_id)
                                                   .where(StudentEnrollment.class_section_id == cid,
                                                          StudentEnrollment.active.is_(True))
                                                   .order_by(StudentEnrollment.roll_no)).all()]
        today = date.today()
        ms = db.scalars(select(TeachingMilestone).where(
            TeachingMilestone.class_section_id.in_(class_ids or [-1]),
            TeachingMilestone.planned_week_start >= today - timedelta(days=35),
            TeachingMilestone.planned_week_start <= today + timedelta(days=35))).all()
        pairs = {(a.class_section_id, a.subject_id) for a in assigns}
        plans = db.scalars(select(LessonPlan).where(LessonPlan.class_section_id.in_(class_ids or [-1]),
                                                    LessonPlan.status == "approved")).all()
        return {"portal": "teacher",
                "classes": [{"id": a.class_section_id, "label": a.class_section.label, "subject": a.subject.name,
                             "subject_id": a.subject_id} for a in assigns],
                "rosters": rosters,
                "milestones": [{"id": m.id, "class_id": m.class_section_id, "week": m.planned_week_start.isoformat(),
                                "topic": m.learning_outcome.topic, "code": m.learning_outcome.code, "status": m.status}
                               for m in ms if (m.class_section_id, m.subject_id) in pairs],
                "lesson_plans": [{"id": lp.id, "title": lp.title, "body": lp.body, "sources": lp.sources}
                                 for lp in plans if (lp.class_section_id, lp.subject_id) in pairs]}
    return {"portal": p.portal}


@router.get("/status")
def status(device_uid: str | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    recent = db.scalars(select(SynchronizationEvent).where(SynchronizationEvent.user_id == p.user.id)
                        .order_by(SynchronizationEvent.received_at.desc()).limit(20)).all()
    return {"recent": [{"event_uid": e.event_uid, "type": e.event_type, "status": e.status, "detail": e.detail,
                        "received_at": e.received_at.isoformat() + "Z"} for e in recent]}
