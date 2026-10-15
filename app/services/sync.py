"""Store-and-forward synchronisation for offline devices.

Clients queue events locally (IndexedDB) with a unique `event_uid` and push
them when connectivity returns. The server:
  1. authenticates the user (session) and the device (registry, not revoked),
  2. validates each event with the SAME service functions as online requests
     (so offline mode can never widen permissions),
  3. deduplicates by event_uid,
  4. applies documented conflict rules,
  5. records every outcome in `synchronization_events`.

Conflict rules
- attendance.mark   : per student-day, the most recent *client* timestamp wins;
                      an older offline mark never overwrites a newer one.
- assessment.submit : first submission wins; later ones are `conflict`.
- activity.complete : completions merge; the best score is kept.
- milestone.taught  : idempotent; first "taught" timestamp is kept.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    AttendanceRecord,
    ClassSection,
    DeviceRegistry,
    StudentEnrollment,
    SynchronizationEvent,
    TeachingMilestone,
    User,
    utcnow,
)
from app.scope import current_enrollment, get_class_for_teacher
from app.services import aiclass, learner, planning

ATTENDANCE_EDIT_DAYS = 7
MAX_EVENTS_PER_PUSH = 200
ALLOWED = {"teacher": {"attendance.mark", "milestone.taught"},
           "student": {"assessment.submit", "activity.complete"}}


def device_for(db: Session, p: Principal, device_uid: str, profile: str = "browser", app_version: str | None = None) -> DeviceRegistry:
    d = db.scalar(select(DeviceRegistry).where(DeviceRegistry.device_uid == device_uid))
    school_id = p.assignment.school_id if p.assignment else None
    if d is None:
        d = DeviceRegistry(device_uid=device_uid, school_id=school_id, registered_by=p.user.id, profile=profile,
                           label=f"{profile} ({p.portal})", app_version=app_version)
        db.add(d)
        db.flush()
    if d.status != "active":
        raise HTTPException(403, "This device has been revoked. Contact your school administrator.")
    if d.school_id and school_id and d.school_id != school_id:
        raise HTTPException(403, "This device is registered to another school")
    d.last_seen_at = utcnow()
    d.app_version = app_version or d.app_version
    return d


def _parse_ts(v) -> datetime:
    """Client timestamps are ISO 8601; stored as naive UTC like every other timestamp."""
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return utcnow()
    return ts if ts.tzinfo is None else ts.astimezone(timezone.utc).replace(tzinfo=None)


def push(db: Session, p: Principal, device: DeviceRegistry, events: list[dict]) -> list[dict]:
    if len(events) > MAX_EVENTS_PER_PUSH:
        raise HTTPException(413, f"At most {MAX_EVENTS_PER_PUSH} events per push")
    allowed = ALLOWED.get(p.portal, set())
    results = []
    seen: set[str] = set()  # duplicates inside the same batch (not yet visible in the table)
    for ev in events:
        uid = str(ev.get("event_uid", ""))[:64]
        etype = ev.get("type")
        client_ts = min(_parse_ts(ev.get("created_at")), utcnow())
        if not uid:
            results.append({"event_uid": uid, "status": "rejected", "detail": "missing event_uid"})
            continue
        if uid in seen:
            results.append({"event_uid": uid, "status": "duplicate", "detail": "repeated in this batch"})
            continue
        seen.add(uid)
        prior = db.scalar(select(SynchronizationEvent).where(SynchronizationEvent.event_uid == uid))
        if prior is not None:
            results.append({"event_uid": uid, "status": "duplicate", "detail": prior.status})
            continue
        status_, detail = "accepted", None
        sp = db.begin_nested()
        try:
            if etype not in allowed:
                raise HTTPException(403, f"Event type {etype!r} not permitted for this portal")
            detail = _apply(db, p, device, etype, ev.get("payload") or {}, uid, client_ts)
            if detail and detail.startswith("conflict"):
                status_ = "conflict"
            sp.commit()
        except HTTPException as exc:
            sp.rollback()
            status_ = "conflict" if exc.status_code == 409 else "rejected"
            detail = str(exc.detail)[:300]
        db.add(SynchronizationEvent(event_uid=uid, device_id=device.id, user_id=p.user.id, event_type=str(etype)[:30],
                                    payload=ev.get("payload") or {}, client_created_at=client_ts, status=status_,
                                    detail=detail))
        results.append({"event_uid": uid, "status": status_, "detail": detail})
    device.last_sync_at = utcnow()
    db.flush()
    return results


def _apply(db: Session, p: Principal, device: DeviceRegistry, etype: str, payload: dict, uid: str,
           client_ts: datetime) -> str | None:
    if etype == "assessment.submit":
        enr = _enrollment(db, p)
        aiclass.submit_assessment(db, enr, int(payload["assessment_id"]), dict(payload.get("answers") or {}),
                                  source="sync", event_uid=uid, device_id=device.id, submitted_at=client_ts)
        return None
    if etype == "activity.complete":
        enr = _enrollment(db, p)
        aiclass.complete_activity(db, enr, int(payload["activity_id"]), dict(payload.get("answers") or {}),
                                  source="sync", event_uid=uid, device_id=device.id, at=client_ts)
        return None
    if etype == "attendance.mark":
        cs = get_class_for_teacher(db, p, int(payload["class_id"]))
        return mark_attendance(db, p, cs, date.fromisoformat(payload["date"]), payload.get("records") or [],
                               client_ts=client_ts, source="sync", uid=uid, device_id=device.id)
    if etype == "milestone.taught":
        m = db.get(TeachingMilestone, int(payload["milestone_id"]))
        if m is None:
            raise HTTPException(404, "Milestone not found")
        get_class_for_teacher(db, p, m.class_section_id, m.subject_id)
        planning.mark_taught(db, m, p.user.id, payload.get("lesson_plan_id"), at=client_ts)
        return None
    raise HTTPException(422, "Unknown event type")


def _enrollment(db: Session, p: Principal) -> StudentEnrollment:
    enr = current_enrollment(db, p.user.id)
    if enr is None:
        raise HTTPException(409, "No active enrolment")
    return enr


def mark_attendance(db: Session, p: Principal, cs: ClassSection, on: date, records: list[dict], *,
                    client_ts: datetime | None = None, source: str = "online", uid: str | None = None,
                    device_id: int | None = None) -> str | None:
    """Shared by the online attendance API and sync. Returns a conflict note if any mark was skipped."""
    today = date.today()
    if on > today or on < today - timedelta(days=ATTENDANCE_EDIT_DAYS):
        raise HTTPException(422, f"Attendance can be recorded for today and the previous {ATTENDANCE_EDIT_DAYS} days")
    students = {u.public_id: u for u in db.scalars(
        select(User).join(StudentEnrollment, StudentEnrollment.student_user_id == User.id).where(
            StudentEnrollment.class_section_id == cs.id, StudentEnrollment.active.is_(True)))}
    when = client_ts or utcnow()
    skipped = 0
    for item in records:
        u = students.get(item.get("student"))
        st = item.get("status")
        if u is None or st not in ("present", "absent", "late", "leave"):
            raise HTTPException(422, "Invalid student or status")
        rec = db.scalar(select(AttendanceRecord).where(AttendanceRecord.person_user_id == u.id,
                                                       AttendanceRecord.date == on))
        if rec is not None and rec.recorded_at > when:
            skipped += 1  # newer mark already on the server
            continue
        if rec is None:
            rec = AttendanceRecord(person_user_id=u.id, person_type="student", school_id=cs.school_id,
                                   class_section_id=cs.id, date=on, status=st)
            db.add(rec)
        changed = rec.status != st or rec.id is None
        rec.status, rec.recorded_by, rec.recorded_at = st, p.user.id, when
        db.flush()
        if changed:
            learner.record_event(db, student_id=u.id, event_type="attendance", recorded_by=p.user.id,
                                 occurred_at=datetime.combine(on, datetime.min.time()), source=source,
                                 device_id=device_id, event_uid=f"att-{u.id}-{on.isoformat()}-{st}-{rec.id}-{int(when.timestamp())}",
                                 payload={"date": on.isoformat(), "status": st,
                                          "summary": f"Attendance {on.isoformat()}: {st}"})
    return f"conflict: {skipped} newer mark(s) kept" if skipped else None
