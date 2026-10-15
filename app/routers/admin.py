"""Admin portal API (state / district / block administrators).

Every query that touches schools passes through `scope_schools` or one of the
`get_*_for_admin` helpers, so scope is enforced server-side regardless of the
IDs or codes a client sends.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.deps import Principal, require_admin
from app.models import (
    BLOCK_ADMIN,
    DISTRICT_ADMIN,
    STATE_ADMIN,
    AIRecommendation,
    AuditLog,
    AuthSession,
    Block,
    ClassSection,
    District,
    Role,
    School,
    SchoolCodeRegistry,
    SchoolReport,
    StudentEnrollment,
    Subject,
    TeacherClassAssignment,
    TeacherProfile,
    User,
    UserRoleAssignment,
    utcnow,
)
from app.registry import import_registry_csv, normalise_code, resolve_geography, validate_for_registration
from app.scope import (
    admin_can_see_block,
    admin_can_see_district,
    admin_can_see_school,
    get_class_for_admin,
    get_school_for_admin,
    not_found,
    scope_schools,
)
from app.services import accounts, analytics, insights
from app.services.exports import MEDIA_TYPES, Table, render

router = APIRouter(prefix="/api/admin", tags=["admin"])
AnyAdmin = Depends(require_admin())
StateOnly = Depends(require_admin(STATE_ADMIN))
StateOrDistrict = Depends(require_admin(STATE_ADMIN, DISTRICT_ADMIN))


# ---------------------------------------------------------------- helpers ----

def scoped_schools(db: Session, p: Principal, *, district_id: int | None = None,
                   block_id: int | None = None, active_only: bool = True) -> list[School]:
    stmt = scope_schools(select(School), p)
    if active_only:
        stmt = stmt.where(School.status == "active")
    if district_id is not None:
        stmt = stmt.where(School.district_id == district_id)
    if block_id is not None:
        stmt = stmt.where(School.block_id == block_id)
    return list(db.scalars(stmt.order_by(School.name)))


def school_row(s: School, snap, today: date | None = None) -> dict:
    st = analytics.data_status(snap, today)
    return {
        "id": s.id, "official_code": s.official_code, "name": s.name, "status": s.status,
        "district": s.district.name, "block": s.block.name, "locality": s.locality,
        "locality_type": s.locality_type, "category": s.category, "medium": s.medium,
        "classes": f"{s.lowest_class}-{s.highest_class}", "is_demo": s.is_demo,
        "data_status": st, "latest": analytics.snapshot_dict(snap),
        "flags": analytics.support_flags(snap, st),
    }


def _check_narrowing(db: Session, p: Principal, district_id: int | None, block_id: int | None) -> None:
    if district_id is not None and not admin_can_see_district(p, district_id):
        raise not_found("District")
    if block_id is not None:
        b = db.get(Block, block_id)
        if b is None or not admin_can_see_block(p, b):
            raise not_found("Block")


# -------------------------------------------------------------- monitoring ----

@router.get("/overview")
def overview(district_id: int | None = None, block_id: int | None = None,
             p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    _check_narrowing(db, p, district_id, block_id)
    schools = scoped_schools(db, p, district_id=district_id, block_id=block_id)
    ids = [s.id for s in schools]
    snaps = analytics.latest_snapshots(db, ids)
    teachers = db.scalar(select(func.count(TeacherProfile.user_id)).where(
        TeacherProfile.school_id.in_(ids or [-1]), TeacherProfile.verification_status == "verified")) or 0
    students = db.scalar(select(func.count(StudentEnrollment.id)).join(ClassSection).where(
        ClassSection.school_id.in_(ids or [-1]), StudentEnrollment.active.is_(True))) or 0
    pending = db.scalar(scope_schools(select(func.count(School.id)), p).where(School.status == "pending")) or 0
    rows = [school_row(s, snaps.get(s.id)) for s in schools]
    return {
        "totals": {
            "schools_active": len(schools), "schools_pending_activation": pending,
            "districts": len({s.district_id for s in schools}), "blocks": len({s.block_id for s in schools}),
            "teachers_verified": teachers, "students_enrolled": students,
            "schools_needing_support": sum(1 for r in rows if r["flags"]),
            "demo_schools": sum(1 for s in schools if s.is_demo),
        },
        "metrics": analytics.aggregate(schools, snaps),
        "trend": analytics.trend(db, ids),
        "subjects": {s.code: {"name": s.name, "name_hi": s.name_hi} for s in db.scalars(select(Subject))},
        "generated_at": utcnow().isoformat() + "Z",
    }


@router.get("/districts")
def districts(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    schools = scoped_schools(db, p)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    by_d: dict[int, list[School]] = {}
    for s in schools:
        by_d.setdefault(s.district_id, []).append(s)
    ids = list(db.scalars(select(District.id))) if p.role == STATE_ADMIN else [p.district_id]
    out = []
    for d in db.scalars(select(District).where(District.id.in_(ids or [-1])).order_by(District.name)):
        ds = by_d.get(d.id, [])
        out.append({"id": d.id, "code": d.code, "name": d.name, "name_hi": d.name_hi, "is_demo": d.is_demo,
                    "division": d.division.name if d.division else None,
                    "division_hi": d.division.name_hi if d.division else None,
                    "metrics": analytics.aggregate(ds, snaps),
                    "needs_support": sum(1 for s in ds if analytics.support_flags(
                        snaps.get(s.id), analytics.data_status(snaps.get(s.id))))})
    return out


@router.get("/districts/{district_id}/blocks")
def district_blocks(district_id: int, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    d = db.get(District, district_id)
    if d is None or not admin_can_see_district(p, district_id):
        raise not_found("District")
    blocks = [b for b in db.scalars(select(Block).where(Block.district_id == district_id).order_by(Block.name))
              if admin_can_see_block(p, b)]
    schools = scoped_schools(db, p, district_id=district_id)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    out = []
    for b in blocks:
        bs = [s for s in schools if s.block_id == b.id]
        out.append({"id": b.id, "code": b.code, "name": b.name, "name_hi": b.name_hi,
                    "metrics": analytics.aggregate(bs, snaps),
                    "needs_support": sum(1 for s in bs if analytics.support_flags(
                        snaps.get(s.id), analytics.data_status(snaps.get(s.id))))})
    return {"district": {"id": d.id, "name": d.name, "name_hi": d.name_hi, "code": d.code}, "blocks": out}


@router.get("/blocks/{block_id}/schools")
def block_schools(block_id: int, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    b = db.get(Block, block_id)
    if b is None or not admin_can_see_block(p, b):
        raise not_found("Block")
    schools = list(db.scalars(scope_schools(select(School), p).where(School.block_id == block_id)
                              .order_by(School.name)))
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    return {"block": {"id": b.id, "name": b.name, "name_hi": b.name_hi, "code": b.code,
                      "district": {"id": b.district.id, "name": b.district.name}},
            "schools": [school_row(s, snaps.get(s.id)) for s in schools]}


@router.get("/schools/{school_id}")
def school_detail(school_id: int, request: Request, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    snaps = analytics.latest_snapshots(db, [s.id])
    history = db.scalars(select(analytics.SchoolPerformanceSnapshot).where(
        analytics.SchoolPerformanceSnapshot.school_id == s.id)
        .order_by(analytics.SchoolPerformanceSnapshot.period.desc()).limit(6)).all()
    classes = db.scalars(select(ClassSection).where(ClassSection.school_id == s.id)
                         .order_by(ClassSection.grade, ClassSection.section)).all()
    counts = dict(db.execute(select(StudentEnrollment.class_section_id, func.count()).where(
        StudentEnrollment.class_section_id.in_([c.id for c in classes] or [-1]),
        StudentEnrollment.active.is_(True)).group_by(StudentEnrollment.class_section_id)).all())
    teachers = db.execute(select(TeacherProfile.verification_status, func.count()).where(
        TeacherProfile.school_id == s.id).group_by(TeacherProfile.verification_status)).all()
    reports = db.scalars(select(SchoolReport).where(SchoolReport.school_id == s.id)
                         .order_by(SchoolReport.submitted_at.desc()).limit(5)).all()
    audit(db, "school.viewed", principal=p, request=request, entity_type="school", entity_id=s.id)
    db.commit()
    return {
        **school_row(s, snaps.get(s.id)),
        "district_id": s.district_id, "block_id": s.block_id,
        "history": [analytics.snapshot_dict(h) for h in reversed(history)],
        "classes": [{"id": c.id, "label": c.label, "grade": c.grade, "section": c.section,
                     "academic_year": c.academic_year, "students": counts.get(c.id, 0)} for c in classes],
        "teachers": {k: v for k, v in teachers},
        "reports": [{"id": r.id, "title": r.title, "period": r.period, "status": r.status,
                     "submitted_at": r.submitted_at.isoformat()} for r in reports],
    }


@router.get("/classes/{class_id}")
def class_detail(class_id: int, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    cs = get_class_for_admin(db, p, class_id)
    summary = analytics.class_summary(db, cs, include_students=False)
    summary["school"] = {"id": cs.school.id, "name": cs.school.name, "official_code": cs.school.official_code}
    return summary


@router.get("/search/schools")
def search_schools(request: Request, code: str | None = Query(None, max_length=20),
                   q: str | None = Query(None, max_length=80), p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    if code:
        c = normalise_code(code)
        s = db.scalar(select(School).where(School.official_code == c))
        found = s is not None and admin_can_see_school(p, s)
        audit(db, "school.code_search", principal=p, request=request, code=c,
              outcome="success" if found else ("denied" if s else "failure"))
        db.commit()
        if not found:  # identical response for "absent" and "outside your scope"
            raise not_found("School")
        return [school_row(s, analytics.latest_snapshots(db, [s.id]).get(s.id))]
    if q and len(q.strip()) >= 3:
        like = f"%{q.strip()}%"
        rows = db.scalars(scope_schools(select(School), p).where(
            or_(School.name.ilike(like), School.locality.ilike(like))).order_by(School.name).limit(20)).all()
        snaps = analytics.latest_snapshots(db, [s.id for s in rows])
        return [school_row(s, snaps.get(s.id)) for s in rows]
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide an 11-digit code or at least 3 letters")


@router.get("/needs-support")
def needs_support(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    schools = scoped_schools(db, p)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    rows = [r for r in (school_row(s, snaps.get(s.id)) for s in schools) if r["flags"]]
    return sorted(rows, key=lambda r: -len(r["flags"]))


# ---------------------------------------------------------------- insights ----

def _scoped_recs(stmt, p: Principal):
    if p.role == DISTRICT_ADMIN:
        return stmt.where(AIRecommendation.district_id == p.district_id)
    if p.role == BLOCK_ADMIN:
        return stmt.where(AIRecommendation.block_id == p.block_id)
    return stmt


@router.get("/insights")
def list_insights(status_filter: str | None = Query(None, alias="status"), p: Principal = AnyAdmin,
                  db: Session = Depends(get_db)):
    stmt = _scoped_recs(select(AIRecommendation).where(AIRecommendation.audience == "admin"), p)
    if status_filter:
        stmt = stmt.where(AIRecommendation.status == status_filter)
    else:
        stmt = stmt.where(AIRecommendation.status.in_(insights.OPEN))
    return [insights.rec_dict(r) for r in db.scalars(stmt.order_by(AIRecommendation.created_at.desc()).limit(200))]


@router.post("/insights/refresh")
def refresh_insights(request: Request, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    recs = insights.refresh_school_interventions(db, scoped_schools(db, p))
    audit(db, "insights.refreshed", principal=p, request=request, count=len(recs))
    db.commit()
    return {"generated_or_updated": len(recs)}


class ReviewIn(BaseModel):
    decision: Literal["approve", "dismiss"]
    note: str = Field(default="", max_length=1000)


@router.post("/insights/{rec_id}/review")
def review_insight(rec_id: int, body: ReviewIn, request: Request, p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    rec = db.get(AIRecommendation, rec_id)
    if rec is None or rec.audience != "admin" or rec.school_id is None:
        raise not_found("Recommendation")
    get_school_for_admin(db, p, rec.school_id)
    rec.status = "approved" if body.decision == "approve" else "dismissed"
    rec.reviewed_by, rec.reviewed_at, rec.review_note = p.user.id, utcnow(), body.note
    audit(db, "insight.reviewed", principal=p, request=request, entity_type="ai_recommendation",
          entity_id=rec.id, decision=body.decision)
    db.commit()
    return insights.rec_dict(rec)


# ------------------------------------------------------- registry / schools ----

@router.get("/registry/{code}")
def registry_lookup(code: str, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    entry = db.get(SchoolCodeRegistry, normalise_code(code))
    if entry is None:
        raise not_found("Registry entry")
    if p.role == DISTRICT_ADMIN:
        d = db.get(District, p.district_id)
        if entry.district_code != d.code:
            raise not_found("Registry entry")
    elif p.role == BLOCK_ADMIN:
        b = db.get(Block, p.block_id)
        if entry.block_code != b.code:
            raise not_found("Registry entry")
    registered = db.scalar(select(School.id).where(School.official_code == entry.code))
    return {"code": entry.code, "school_name": entry.school_name, "district_code": entry.district_code,
            "block_code": entry.block_code, "locality": entry.locality, "category": entry.category,
            "management": entry.management, "registry_status": entry.registry_status,
            "source": entry.source, "source_reference": entry.source_reference,
            "imported_at": entry.imported_at.isoformat(), "is_demo": entry.is_demo,
            "registered_school_id": registered}


@router.post("/registry/import")
async def registry_import(request: Request, file: UploadFile = File(...),
                          source: str = Form(..., min_length=3, max_length=60),
                          source_reference: str = Form(..., min_length=3, max_length=200),
                          p: Principal = StateOnly, db: Session = Depends(get_db)):
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 5 MB)")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File must be UTF-8 CSV")
    if source.strip().upper() == "DEMO":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use the CLI to load demonstration data")
    result = import_registry_csv(db, text, source=source, source_reference=source_reference,
                                 imported_by=p.user.id)
    audit(db, "registry.imported", principal=p, request=request, entity_type="school_code_registry",
          source=source, source_reference=source_reference, created=result.created,
          updated=result.updated, rejected=len(result.rejected))
    db.commit()
    return {"created": result.created, "updated": result.updated, "rejected": result.rejected[:200]}


class RegisterSchoolIn(BaseModel):
    official_code: str = Field(max_length=20)
    medium: str = Field(default="Hindi", max_length=30)
    lowest_class: int = Field(default=1, ge=1, le=12)
    highest_class: int = Field(default=8, ge=1, le=12)
    locality_type: Literal["rural", "urban"] = "rural"


@router.post("/schools", status_code=201)
def register_school(body: RegisterSchoolIn, request: Request, p: Principal = AnyAdmin,
                    db: Session = Depends(get_db)):
    if body.lowest_class > body.highest_class:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Lowest class must not exceed highest class")
    try:
        entry = validate_for_registration(db, body.official_code)
    except HTTPException as exc:
        audit(db, "school.register_rejected", principal=p, request=request, outcome="denied",
              code=normalise_code(body.official_code), reason=exc.detail)
        db.commit()
        raise
    district, block = resolve_geography(db, entry)
    if not admin_can_see_block(p, block):
        audit(db, "school.register_rejected", principal=p, request=request, outcome="denied",
              code=entry.code, reason="outside scope")
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This school is outside your administrative area")
    school = School(official_code=entry.code, name=entry.school_name, district_id=district.id,
                    block_id=block.id, locality=entry.locality, locality_type=body.locality_type,
                    category=entry.category, medium=body.medium, lowest_class=body.lowest_class,
                    highest_class=body.highest_class, status="pending", created_by=p.user.id,
                    is_demo=entry.is_demo)
    db.add(school)
    db.flush()
    audit(db, "school.registered", principal=p, request=request, entity_type="school", entity_id=school.id,
          code=entry.code)
    db.commit()
    return {"id": school.id, "status": school.status, "official_code": school.official_code}


@router.get("/schools")
def list_schools(status_filter: Literal["pending", "active", "suspended", "closed"] = Query("pending", alias="status"),
                 p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    rows = db.scalars(scope_schools(select(School), p).where(School.status == status_filter)
                      .order_by(School.created_at.desc()).limit(200)).all()
    return [{"id": s.id, "official_code": s.official_code, "name": s.name, "district": s.district.name,
             "block": s.block.name, "status": s.status, "is_demo": s.is_demo,
             "created_at": s.created_at.isoformat(), "created_by_me": s.created_by == p.user.id} for s in rows]


@router.get("/teachers/pending")
def pending_teachers(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    rows = db.scalars(select(TeacherProfile).join(School, School.id == TeacherProfile.school_id)
                      .where(TeacherProfile.verification_status == "pending")
                      .where(School.id.in_(scope_schools(select(School.id), p)))).all()
    return [{"user_id": t.user_id, "name": t.user.full_name, "employee_id": t.employee_id,
             "designation": t.designation, "school": t.school.name, "official_code": t.school.official_code}
            for t in rows]


@router.post("/schools/{school_id}/activate")
def activate_school(school_id: int, request: Request, p: Principal = StateOrDistrict,
                    db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    if s.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"School is {s.status}, not pending")
    if s.created_by == p.user.id and p.role != STATE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Activation needs a second administrator (maker-checker)")
    s.status, s.activated_by, s.activated_at = "active", p.user.id, utcnow()
    audit(db, "school.activated", principal=p, request=request, entity_type="school", entity_id=s.id)
    db.commit()
    return {"id": s.id, "status": s.status}


class SchoolStatusIn(BaseModel):
    status: Literal["active", "suspended", "closed"]
    reason: str = Field(min_length=3, max_length=500)


@router.post("/schools/{school_id}/status")
def set_school_status(school_id: int, body: SchoolStatusIn, request: Request, p: Principal = StateOnly,
                      db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    old = s.status
    s.status = body.status
    audit(db, "school.status_changed", principal=p, request=request, entity_type="school", entity_id=s.id,
          old=old, new=body.status, reason=body.reason)
    db.commit()
    return {"id": s.id, "status": s.status}


class ClassIn(BaseModel):
    grade: int = Field(ge=1, le=12)
    section: str = Field(default="A", pattern="^[A-Z]{1,2}$")
    academic_year: str = Field(pattern=r"^\d{4}-\d{2}$")


@router.post("/schools/{school_id}/classes", status_code=201)
def create_class(school_id: int, body: ClassIn, request: Request, p: Principal = AnyAdmin,
                 db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    if not s.lowest_class <= body.grade <= s.highest_class:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Grade not offered by this school")
    if db.scalar(select(ClassSection.id).where(
            ClassSection.school_id == s.id, ClassSection.grade == body.grade,
            ClassSection.section == body.section, ClassSection.academic_year == body.academic_year)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Class section already exists")
    cs = ClassSection(school_id=s.id, grade=body.grade, section=body.section, academic_year=body.academic_year)
    db.add(cs)
    db.flush()
    audit(db, "class.created", principal=p, request=request, entity_type="class_section", entity_id=cs.id)
    db.commit()
    return {"id": cs.id, "label": cs.label}


# ------------------------------------------------------------- admin users ----

class AdminIn(BaseModel):
    login_id: str = Field(min_length=3, max_length=120)
    full_name: str = Field(min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    role: Literal["district_admin", "block_admin"]
    district_id: int | None = None
    block_id: int | None = None


@router.get("/admins")
def list_admins(p: Principal = StateOnly, db: Session = Depends(get_db)):
    rows = db.execute(select(UserRoleAssignment, User, Role).join(User, User.id == UserRoleAssignment.user_id)
                      .join(Role, Role.id == UserRoleAssignment.role_id)
                      .where(Role.name.in_((STATE_ADMIN, DISTRICT_ADMIN, BLOCK_ADMIN)))
                      .order_by(Role.name, User.full_name)).all()
    out = []
    for a, u, r in rows:
        out.append({"assignment_id": a.id, "user_id": u.id, "name": u.full_name, "login_id": u.login_id,
                    "role": r.name, "active": a.active, "mfa_enabled": u.mfa_enabled,
                    "district": a.district_id and db.get(District, a.district_id).name,
                    "block": a.block_id and db.get(Block, a.block_id).name,
                    "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None})
    return out


@router.post("/admins", status_code=201)
def create_admin(body: AdminIn, request: Request, p: Principal = StateOnly, db: Session = Depends(get_db)):
    if body.role == DISTRICT_ADMIN:
        if body.district_id is None or db.get(District, body.district_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A valid district is required")
        district_id, block_id = body.district_id, None
    else:
        b = db.get(Block, body.block_id) if body.block_id else None
        if b is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A valid block is required")
        district_id, block_id = b.district_id, b.id
    user, temp = accounts.create_user(db, login_id=body.login_id, full_name=body.full_name,
                                      role_name=body.role, granted_by=p.user.id, email=body.email,
                                      phone=body.phone, district_id=district_id, block_id=block_id)
    audit(db, "admin.created", principal=p, request=request, entity_type="user", entity_id=user.id,
          role=body.role, district_id=district_id, block_id=block_id)
    db.commit()
    return {"user_id": user.id, "login_id": user.login_id, "temporary_password": temp,
            "note": "Share the temporary password through an approved channel. It is shown only once."}


@router.post("/admins/{assignment_id}/revoke")
def revoke_admin(assignment_id: int, request: Request, p: Principal = StateOnly, db: Session = Depends(get_db)):
    a = db.get(UserRoleAssignment, assignment_id)
    if a is None or a.role.name not in (DISTRICT_ADMIN, BLOCK_ADMIN):
        raise not_found("Assignment")
    a.active, a.revoked_at = False, utcnow()
    db.execute(update(AuthSession).where(AuthSession.user_id == a.user_id).values(revoked=True))
    audit(db, "admin.revoked", principal=p, request=request, entity_type="user_role_assignment", entity_id=a.id)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- teachers ----

def _teacher_in_scope(db: Session, p: Principal, user_id: int) -> TeacherProfile:
    prof = db.get(TeacherProfile, user_id)
    if prof is None or not admin_can_see_school(p, prof.school):
        raise not_found("Teacher")
    return prof


@router.get("/schools/{school_id}/teachers")
def school_teachers(school_id: int, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    out = []
    for prof in db.scalars(select(TeacherProfile).where(TeacherProfile.school_id == s.id)):
        assigns = db.scalars(select(TeacherClassAssignment).where(
            TeacherClassAssignment.teacher_user_id == prof.user_id, TeacherClassAssignment.active.is_(True))).all()
        out.append({"user_id": prof.user_id, "name": prof.user.full_name, "employee_id": prof.employee_id,
                    "designation": prof.designation, "is_head_teacher": prof.is_head_teacher,
                    "verification_status": prof.verification_status, "account_status": prof.user.status,
                    "assignments": [{"class": a.class_section.label, "subject": a.subject.name} for a in assigns]})
    return out


class TeacherInviteIn(BaseModel):
    employee_id: str = Field(min_length=3, max_length=40)
    full_name: str = Field(min_length=2, max_length=150)
    designation: str = Field(default="Teacher", max_length=80)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)
    is_head_teacher: bool = False


@router.post("/schools/{school_id}/teachers", status_code=201)
def invite_teacher(school_id: int, body: TeacherInviteIn, request: Request, p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    s = get_school_for_admin(db, p, school_id)
    user, temp = accounts.invite_teacher(db, school=s, employee_id=body.employee_id, full_name=body.full_name,
                                         designation=body.designation, email=body.email, phone=body.phone,
                                         invited_by=p.user.id, is_head_teacher=body.is_head_teacher)
    audit(db, "teacher.invited", principal=p, request=request, entity_type="user", entity_id=user.id,
          school_id=s.id)
    db.commit()
    return {"user_id": user.id, "login_id": user.login_id, "temporary_password": temp,
            "verification_status": "pending",
            "note": "The account can sign in only after identity and posting are verified."}


class VerifyIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.post("/teachers/{user_id}/verify")
def verify_teacher(user_id: int, body: VerifyIn, request: Request, p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    prof = _teacher_in_scope(db, p, user_id)
    if prof.verification_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Teacher is already {prof.verification_status}")
    accounts.verify_teacher(db, prof, approve=body.approve, by=p.user.id)
    audit(db, "teacher.verified" if body.approve else "teacher.rejected", principal=p, request=request,
          entity_type="user", entity_id=user_id, note=body.note)
    db.commit()
    return {"user_id": user_id, "verification_status": prof.verification_status}


class TeachAssignIn(BaseModel):
    class_section_id: int
    subject_id: int
    is_class_teacher: bool = False


@router.post("/teachers/{user_id}/assignments", status_code=201)
def assign_teacher(user_id: int, body: TeachAssignIn, request: Request, p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    prof = _teacher_in_scope(db, p, user_id)
    cs = db.get(ClassSection, body.class_section_id)
    if cs is None or cs.school_id != prof.school_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Class must belong to the teacher's school")
    if db.get(Subject, body.subject_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown subject")
    existing = db.scalar(select(TeacherClassAssignment).where(
        TeacherClassAssignment.teacher_user_id == user_id, TeacherClassAssignment.class_section_id == cs.id,
        TeacherClassAssignment.subject_id == body.subject_id))
    if existing is None:
        existing = TeacherClassAssignment(teacher_user_id=user_id, class_section_id=cs.id,
                                          subject_id=body.subject_id)
        db.add(existing)
    existing.active, existing.is_class_teacher = True, body.is_class_teacher
    existing.approved_by, existing.approved_at = p.user.id, utcnow()
    db.flush()
    audit(db, "teacher.assignment_approved", principal=p, request=request,
          entity_type="teacher_class_assignment", entity_id=existing.id)
    db.commit()
    return {"id": existing.id}


class TransferIn(BaseModel):
    school_id: int
    reason: str = Field(min_length=3, max_length=500)


@router.post("/teachers/{user_id}/transfer")
def transfer_teacher(user_id: int, body: TransferIn, request: Request, p: Principal = AnyAdmin,
                     db: Session = Depends(get_db)):
    prof = _teacher_in_scope(db, p, user_id)
    target = get_school_for_admin(db, p, body.school_id)  # must have scope over both schools
    old = prof.school_id
    prof.school_id = target.id
    db.execute(update(TeacherClassAssignment).where(TeacherClassAssignment.teacher_user_id == user_id)
               .values(active=False))
    db.execute(update(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id,
                                                UserRoleAssignment.active.is_(True))
               .values(school_id=target.id))
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id).values(revoked=True))
    audit(db, "teacher.transferred", principal=p, request=request, entity_type="user", entity_id=user_id,
          from_school=old, to_school=target.id, reason=body.reason)
    db.commit()
    return {"user_id": user_id, "school_id": target.id}


@router.post("/teachers/{user_id}/reset-password")
def reset_teacher_password(user_id: int, request: Request, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    prof = _teacher_in_scope(db, p, user_id)
    temp = accounts.reset_to_temporary_password(db, prof.user)
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id).values(revoked=True))
    audit(db, "teacher.password_reset", principal=p, request=request, entity_type="user", entity_id=user_id)
    db.commit()
    return {"temporary_password": temp}


class EnrollIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    guardian_name: str = Field(min_length=2, max_length=150)
    guardian_phone: str | None = Field(default=None, max_length=20)
    guardian_consent: bool
    birth_year: int | None = Field(default=None, ge=2000, le=2025)
    gender: Literal["female", "male", "other"] | None = None
    roll_no: int | None = Field(default=None, ge=1, le=999)


@router.post("/classes/{class_id}/students", status_code=201)
def enroll_student(class_id: int, body: EnrollIn, request: Request, p: Principal = AnyAdmin,
                   db: Session = Depends(get_db)):
    cs = get_class_for_admin(db, p, class_id)
    user, temp = accounts.enroll_student(db, cs=cs, enrolled_by=p.user.id, **body.model_dump())
    audit(db, "student.enrolled", principal=p, request=request, entity_type="user", entity_id=user.id,
          class_id=cs.id)
    db.commit()
    return {"user_id": user.id, "login_id": user.login_id, "temporary_password": temp}


# ------------------------------------------------------- teacher reports in ----

@router.get("/school-reports")
def school_reports(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    ids = [s.id for s in scoped_schools(db, p, active_only=False)]
    rows = db.scalars(select(SchoolReport).where(SchoolReport.school_id.in_(ids or [-1]))
                      .order_by(SchoolReport.submitted_at.desc()).limit(200)).all()
    return [{"id": r.id, "school_id": r.school_id, "school": db.get(School, r.school_id).name,
             "title": r.title, "period": r.period, "body": r.body, "metrics": r.metrics, "status": r.status,
             "submitted_at": r.submitted_at.isoformat()} for r in rows]


@router.post("/school-reports/{report_id}/acknowledge")
def acknowledge_report(report_id: int, request: Request, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    r = db.get(SchoolReport, report_id)
    if r is None:
        raise not_found("Report")
    get_school_for_admin(db, p, r.school_id)
    r.status, r.acknowledged_by = "acknowledged", p.user.id
    audit(db, "school_report.acknowledged", principal=p, request=request, entity_type="school_report",
          entity_id=r.id)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------- reports ----

REPORT_KINDS = ("coverage", "performance", "district-summary", "interventions", "data-quality")


def _pct(v):
    return None if v is None else round(v, 4)


def build_report(db: Session, p: Principal, kind: str, district_id: int | None, block_id: int | None) -> Table:
    _check_narrowing(db, p, district_id, block_id)
    schools = scoped_schools(db, p, district_id=district_id, block_id=block_id, active_only=False)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    scope_label = {STATE_ADMIN: "Chhattisgarh (all districts)",
                   DISTRICT_ADMIN: "District scope", BLOCK_ADMIN: "Block scope"}[p.role]
    if district_id:
        scope_label += f" · district {db.get(District, district_id).name}"
    if block_id:
        scope_label += f" · block {db.get(Block, block_id).name}"
    demo = any(s.is_demo for s in schools)
    notes = [f"Scope: {scope_label}", f"Generated {utcnow():%Y-%m-%d %H:%M} UTC by {p.user.full_name} ({p.role})",
             "Outcome metrics use only schools with current data; '-' means no data reported."]
    if demo:
        notes.insert(0, "DEMONSTRATION DATA - not official government statistics")

    if kind == "coverage":
        rows = []
        for s in schools:
            sn = snaps.get(s.id)
            rows.append([s.official_code, s.name, s.district.name, s.block.name, s.status,
                         analytics.data_status(sn), sn.as_of.isoformat() if sn else None,
                         sn.student_count if sn else None, sn.teacher_count if sn else None])
        return Table("School coverage report", ["UDISE code", "School", "District", "Block", "Status",
                                                "Data status", "Data as of", "Students", "Teachers"], rows, notes)
    if kind == "performance":
        rows = []
        for s in schools:
            sn = snaps.get(s.id)
            st = analytics.data_status(sn)
            cur = sn if st == "current" else None
            rows.append([s.official_code, s.name, s.district.name, s.block.name, st,
                         _pct(cur and cur.student_attendance_rate), _pct(cur and cur.teacher_attendance_rate),
                         _pct(cur and cur.assessment_participation), _pct(cur and cur.avg_score_pct),
                         "; ".join(f["reason"] for f in analytics.support_flags(sn, st)) or None])
        return Table("School performance report", ["UDISE code", "School", "District", "Block", "Data status",
                                                   "Student attendance", "Teacher attendance",
                                                   "Assessment participation", "Average score", "Flags"],
                     rows, notes)
    if kind == "district-summary":
        rows = []
        groups: dict[tuple[str, str], list[School]] = {}
        for s in schools:
            groups.setdefault((s.district.name, s.block.name), []).append(s)
        for (d, b), group in sorted(groups.items()):
            m = analytics.aggregate([s for s in group if s.status == "active"], snaps)
            rows.append([d, b, m["schools"], m["schools_reporting_current"], m["student_attendance_rate"],
                         m["teacher_attendance_rate"], m["assessment_participation"], m["avg_score_pct"]])
        return Table("District and block summary", ["District", "Block", "Active schools", "Reporting current",
                                                    "Student attendance", "Teacher attendance",
                                                    "Participation", "Average score"], rows, notes)
    if kind == "interventions":
        ids = {s.id for s in schools}
        recs = db.scalars(select(AIRecommendation).where(
            AIRecommendation.school_id.in_(ids or [-1]),
            AIRecommendation.audience.in_(("admin", "teacher")),
            AIRecommendation.status.in_(insights.OPEN))).all()
        by_id = {s.id: s for s in schools}
        rows = [[by_id[r.school_id].official_code, by_id[r.school_id].name, r.kind, r.title, r.status,
                 r.generated_by, r.created_at.date().isoformat()] for r in recs]
        notes.append("AI-generated suggestions for review by educators; not decisions.")
        return Table("Learning-gap and intervention report", ["UDISE code", "School", "Type", "Recommendation",
                                                              "Review status", "Generated by", "Date"], rows, notes)
    if kind == "data-quality":
        rows = []
        for s in schools:
            sn = snaps.get(s.id)
            st = analytics.data_status(sn)
            missing = [k for k in ("student_attendance_rate", "teacher_attendance_rate",
                                   "assessment_participation", "avg_score_pct")
                       if sn is None or getattr(sn, k) is None]
            rows.append([s.official_code, s.name, s.block.name, st, sn.period if sn else None,
                         sn.as_of.isoformat() if sn else None, ", ".join(missing) or "complete"])
        return Table("Data quality and reporting completeness", ["UDISE code", "School", "Block", "Data status",
                                                                 "Latest period", "As of", "Missing fields"],
                     rows, notes)
    raise not_found("Report type")


@router.get("/reports/{kind}")
def export_report(kind: str, request: Request, format: Literal["csv", "xlsx", "pdf"] = "csv",
                  district_id: int | None = None, block_id: int | None = None,
                  p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    if kind not in REPORT_KINDS:
        raise not_found("Report type")
    table = build_report(db, p, kind, district_id, block_id)
    audit(db, "report.exported", principal=p, request=request, entity_type="report", entity_id=kind,
          format=format, rows=len(table.rows), district_id=district_id, block_id=block_id)
    db.commit()
    filename = f"hamar-shiksha-{kind}-{date.today().isoformat()}.{format}"
    return Response(render(table, format), media_type=MEDIA_TYPES[format],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


# --------------------------------------------------------------- audit log ----

@router.get("/audit-logs")
def audit_logs(action: str | None = Query(None, max_length=60), user_id: int | None = None,
               outcome: str | None = Query(None, max_length=10), limit: int = Query(100, le=500),
               p: Principal = StateOnly, db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if user_id:
        stmt = stmt.where(AuditLog.actor_user_id == user_id)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    return [{"id": a.id, "at": a.at.isoformat() + "Z", "actor_user_id": a.actor_user_id, "actor_role": a.actor_role,
             "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "outcome": a.outcome,
             "details": a.details, "ip": a.ip} for a in db.scalars(stmt)]


# ------------------------------------------------------- Command Centre ----

def _child_units(db: Session, p: Principal, district_id: int | None, block_id: int | None):
    """Return (level, [(unit_id, name, [schools])]) for the next level down."""
    _check_narrowing(db, p, district_id, block_id)
    schools = scoped_schools(db, p, district_id=district_id, block_id=block_id)
    if block_id or p.role == BLOCK_ADMIN:
        return "school", [(s.id, s.name, [s]) for s in schools]
    if district_id or p.role == DISTRICT_ADMIN:
        groups: dict[int, list[School]] = {}
        for s in schools:
            groups.setdefault(s.block_id, []).append(s)
        return "block", [(bid, db.get(Block, bid).name, ss) for bid, ss in groups.items()]
    groups = {}
    for s in schools:
        groups.setdefault(s.district_id, []).append(s)
    return "district", [(did, db.get(District, did).name, ss) for did, ss in groups.items()]


@router.get("/command/ptl")
def planned_taught_learned(district_id: int | None = None, block_id: int | None = None, p: Principal = AnyAdmin,
                           db: Session = Depends(get_db)):
    from app.services import planning

    level, units = _child_units(db, p, district_id, block_id)
    rows, all_classes = [], []
    for uid, name, schools in units:
        class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.school_id.in_([s.id for s in schools]))))
        all_classes += class_ids
        rows.append({"id": uid, "name": name, **planning.ptl_for_classes(db, class_ids)})
    return {"level": level, "rows": sorted(rows, key=lambda r: r["name"]),
            "total": planning.ptl_for_classes(db, all_classes),
            "definition": "Planned = learning outcomes scheduled up to today; Taught = marked taught by the teacher; "
                          "Learned = taught outcomes whose class mean mastery is at least 60% (students with 3+ answers)."}


@router.get("/command/expertise-gaps")
def expertise_gaps(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    from app.services import planning

    gaps = planning.expertise_gaps(db, [s.id for s in scoped_schools(db, p)])
    by_subject: dict[str, int] = {}
    for g in gaps:
        by_subject[g["subject"]] = by_subject.get(g["subject"], 0) + 1
    return {"by_subject": by_subject, "schools": sorted(gaps, key=lambda g: (g["subject"], g["school"])),
            "definition": "A class-subject taught by a teacher with no recorded qualification and no completed "
                          "micro-course in that subject. Indicates training need, not teacher performance."}


@router.get("/command/correlation")
def attendance_learning(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    schools = scoped_schools(db, p)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    pts = [(s, snaps[s.id]) for s in schools if analytics.data_status(snaps.get(s.id)) == "current"
           and snaps[s.id].student_attendance_rate is not None and snaps[s.id].avg_score_pct is not None]
    r = None
    if len(pts) >= 3:
        xs = [sn.student_attendance_rate for _, sn in pts]
        ys = [sn.avg_score_pct for _, sn in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        r = round(sxy / (sxx * syy) ** 0.5, 3) if sxx and syy else None
    return {"n": len(pts), "pearson_r": r,
            "points": [{"school": s.name, "official_code": s.official_code, "attendance": sn.student_attendance_rate,
                        "avg_score": sn.avg_score_pct} for s, sn in pts],
            "note": "Association across schools with current data only; it does not show cause and effect."}


@router.get("/command/participation")
def participation(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    from datetime import timedelta as _td

    from app.models import LearnerEvent

    schools = scoped_schools(db, p)
    ids = [s.id for s in schools]
    since = utcnow() - _td(days=7)
    teachers = db.scalars(select(TeacherProfile.user_id).where(TeacherProfile.school_id.in_(ids or [-1]),
                                                               TeacherProfile.verification_status == "verified")).all()
    active_t = db.scalar(select(func.count(func.distinct(AuditLog.actor_user_id))).where(
        AuditLog.actor_user_id.in_(teachers or [-1]), AuditLog.at >= since)) or 0
    students = db.scalar(select(func.count(StudentEnrollment.id)).join(ClassSection).where(
        ClassSection.school_id.in_(ids or [-1]), StudentEnrollment.active.is_(True))) or 0
    active_s = db.scalar(select(func.count(func.distinct(LearnerEvent.student_user_id))).where(
        LearnerEvent.school_id.in_(ids or [-1]), LearnerEvent.occurred_at >= since,
        LearnerEvent.event_type.in_(("assessment_result", "activity_completion", "lesson_completed")))) or 0
    return {"window_days": 7, "teachers": len(teachers), "teachers_active": active_t, "students": students,
            "students_active_learning": active_s,
            "definition": "Active teacher = any recorded platform action; active student = a recorded assessment, "
                          "practice or lesson completion in the last 7 days."}


@router.get("/command/devices")
def devices(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    from datetime import timedelta as _td

    from app.models import DeviceRegistry, SynchronizationEvent

    ids = [s.id for s in scoped_schools(db, p, active_only=False)]
    since = utcnow() - _td(days=7)
    out = []
    for d in db.scalars(select(DeviceRegistry).where(DeviceRegistry.school_id.in_(ids or [-1]))
                        .order_by(DeviceRegistry.last_sync_at.desc())):
        problems = db.scalar(select(func.count(SynchronizationEvent.id)).where(
            SynchronizationEvent.device_id == d.id, SynchronizationEvent.received_at >= since,
            SynchronizationEvent.status.in_(("conflict", "rejected")))) or 0
        out.append({"id": d.id, "label": d.label, "profile": d.profile, "status": d.status,
                    "school": db.get(School, d.school_id).name if d.school_id else None,
                    "last_sync_at": d.last_sync_at.isoformat() + "Z" if d.last_sync_at else None,
                    "sync_problems_7d": problems, "app_version": d.app_version})
    return out


@router.post("/command/devices/{device_id}/revoke")
def revoke_device(device_id: int, request: Request, p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    from app.models import DeviceRegistry

    d = db.get(DeviceRegistry, device_id)
    if d is None or d.school_id is None:
        raise not_found("Device")
    get_school_for_admin(db, p, d.school_id)
    d.status = "revoked"
    audit(db, "device.revoked", principal=p, request=request, entity_type="device", entity_id=d.id)
    db.commit()
    return {"ok": True}


def _grade_counts(grades: list[str | None]) -> dict:
    return {g: sum(1 for x in grades if x == g) for g in ("A", "B", "C", "D")} | {
        "none": sum(1 for x in grades if x is None)}


@router.get("/command/progress-grades")
def progress_grades(district_id: int | None = None, block_id: int | None = None, p: Principal = AnyAdmin,
                    db: Session = Depends(get_db)):
    """Milestone-based academic progress grade per school, rolled up to the next level down."""
    from app.services import monitoring

    level, units = _child_units(db, p, district_id, block_id)
    schools = [s for _, _, ss in units for s in ss]
    rows = monitoring.school_grades(db, schools)
    by_id = {r["school_id"]: r for r in rows}
    unit_rows = []
    for uid, name, ss in units:
        rs = [by_id[s.id] for s in ss]
        unit_rows.append({"id": uid, "name": name, "schools": len(ss), "counts": _grade_counts([r["grade"] for r in rs])})
    return {"level": level, "units": sorted(unit_rows, key=lambda u: u["name"]),
            "counts": _grade_counts([r["grade"] for r in rows]),
            "schools": sorted(rows, key=lambda r: ({"D": 0, "C": 1, "B": 2, "A": 3, None: 4}[r["grade"]], r["school"])),
            "definition": monitoring.GRADE_DEFINITION}


@router.get("/command/attendance-risk")
def attendance_risk_summary(district_id: int | None = None, block_id: int | None = None, p: Principal = AnyAdmin,
                            db: Session = Depends(get_db)):
    """Counts only: administrators never see the names of flagged children."""
    from app.services import monitoring

    level, units = _child_units(db, p, district_id, block_id)
    out, all_classes = [], []
    for uid, name, ss in units:
        class_ids = list(db.scalars(select(ClassSection.id).where(ClassSection.school_id.in_([s.id for s in ss]))))
        all_classes += class_ids
        r = monitoring.attendance_risk(db, class_ids, with_students=False)
        out.append({"id": uid, "name": name, "students": r["students"], **r["counts"]})
    total = monitoring.attendance_risk(db, all_classes, with_students=False)
    return {"level": level, "rows": sorted(out, key=lambda r: -(r["high"] / r["students"] if r["students"] else 0)),
            "total": {k: total[k] for k in ("students", "counts", "by_band")},
            "definition": total["definition"], "band_note": total["band_note"]}


@router.get("/command/digital")
def digital_infrastructure(district_id: int | None = None, block_id: int | None = None, p: Principal = AnyAdmin,
                           db: Session = Depends(get_db)):
    from app.services import digital

    level, units = _child_units(db, p, district_id, block_id)
    ids = [s.id for _, _, ss in units for s in ss]
    u = digital.utilisation(db, ids)
    per_unit = []
    school_unit = {s.id: (uid, name) for uid, name, ss in units for s in ss}
    agg: dict = {}
    for r in u["rows"]:
        uid, name = school_unit[r["school_id"]]
        a = agg.setdefault(uid, {"id": uid, "name": name, "resources": 0, "working": 0, "sessions": 0, "target": 0,
                                 "gaps": 0})
        a["resources"] += 1
        a["working"] += r["status"] == "working"
        a["sessions"] += r["sessions"]
        a["target"] += r["target_sessions_per_week"] * digital.WINDOW_WEEKS if r["status"] == "working" else 0
        a["gaps"] += bool(r["gap"])
    for a in agg.values():
        per_unit.append({**a, "utilisation": round(a["sessions"] / a["target"], 4) if a["target"] else None})
    u.pop("rows")
    return {"level": level, **u, "units": sorted(per_unit, key=lambda a: a["name"])}


@router.get("/command/recognition")
def recognition_view(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    """Improvement-based recognition: most improved schools, and their teachers' earned badges."""
    from app.services import recognition

    schools = scoped_schools(db, p)
    by_id = {s.id: s for s in schools}
    imp = sorted(recognition.school_improvement(db, list(by_id)), key=lambda r: -r["change_points"])
    top = [r for r in imp if r["change_points"] > 0][:8]
    teachers = []
    for r in top[:4]:
        for tp in db.scalars(select(TeacherProfile).where(TeacherProfile.school_id == r["school_id"],
                                                          TeacherProfile.verification_status == "verified")):
            badges = [b for b in recognition.teacher_badges(db, tp.user_id) if b["earned"]]
            teachers.append({"user_id": tp.user_id, "name": tp.user.full_name, "school": by_id[r["school_id"]].name,
                             "badges": [{"title": b["title"], "title_hi": b["title_hi"], "icon": b["icon"]} for b in badges]})
    return {"improved_schools": [{**r, "school": by_id[r["school_id"]].name,
                                  "official_code": by_id[r["school_id"]].official_code} for r in top],
            "teachers": sorted(teachers, key=lambda t: -len(t["badges"]))[:12],
            "categories": [{"key": k, "label": v[0], "label_hi": v[1]} for k, v in recognition.TEACHER_CATEGORIES.items()],
            "note": "Ranked by improvement in average score between the earliest and latest monthly figures, "
                    "not by absolute results, so schools that started low can be recognised."}


class AdminAppreciateIn(BaseModel):
    category: str = Field(max_length=20)
    message: str = Field(default="", max_length=300)


@router.post("/teachers/{user_id}/appreciate", status_code=201)
def appreciate_teacher(user_id: int, body: AdminAppreciateIn, request: Request, p: Principal = AnyAdmin,
                       db: Session = Depends(get_db)):
    from app.models import Appreciation
    from app.services import recognition
    from app.services.studenthelp import check_post

    tp = db.get(TeacherProfile, user_id)
    if tp is None:
        raise not_found("Teacher")
    get_school_for_admin(db, p, tp.school_id)
    if body.category not in recognition.TEACHER_CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown category")
    if body.message.strip():
        check_post(body.message)
    a = Appreciation(recipient_user_id=user_id, giver_user_id=p.user.id, giver_role=p.role, category=body.category,
                     message=body.message.strip())
    db.add(a)
    db.flush()
    audit(db, "appreciation.given", principal=p, request=request, entity_type="appreciation", entity_id=a.id)
    db.commit()
    return {"id": a.id}


def _objective_metrics(db: Session, schools: list[School]):
    """Per-school figures for the map: progress grade, digital utilisation and
    attendance follow-up; returns a function that pools them for a group."""
    from app.services import digital, monitoring

    grade = {r["school_id"]: r["grade"] for r in monitoring.school_grades(db, schools)}
    use: dict[int, list[int]] = {}
    for r in digital.utilisation(db, [s.id for s in schools])["rows"]:
        u = use.setdefault(r["school_id"], [0, 0])
        if r["status"] == "working":
            u[0] += r["sessions"]
            u[1] += r["target_sessions_per_week"] * digital.WINDOW_WEEKS
    classes: dict[int, list[int]] = {}
    for cid, sid in db.execute(select(ClassSection.id, ClassSection.school_id).where(
            ClassSection.school_id.in_([s.id for s in schools] or [-1]))):
        classes.setdefault(sid, []).append(cid)

    def pool(group: list[School]) -> dict:
        graded = [grade.get(s.id) for s in group if grade.get(s.id)]
        sess = sum(use.get(s.id, [0, 0])[0] for s in group)
        target = sum(use.get(s.id, [0, 0])[1] for s in group)
        risk = monitoring.attendance_risk(db, [c for s in group for c in classes.get(s.id, [])], with_students=False)
        return {"on_track_share": round(sum(g in ("A", "B") for g in graded) / len(graded), 4) if graded else None,
                "digital_utilisation": round(sess / target, 4) if target else None,
                "followup_rate": round(risk["counts"]["high"] / risk["students"], 4) if risk["students"] else None}
    return pool


@router.get("/map")
def division_map(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    """Division -> district analysis for the map: schools (onboarded and in the
    registry), teachers, students and outcome metrics, within the admin's scope."""
    from app import geo
    from app.models import Division

    schools = scoped_schools(db, p)
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    by_d: dict[int, list[School]] = {}
    for s in schools:
        by_d.setdefault(s.district_id, []).append(s)
    visible = [d for d in db.scalars(select(District).order_by(District.name)) if admin_can_see_district(p, d.id)]
    vis_ids = [d.id for d in visible]
    if p.role == BLOCK_ADMIN:
        reg_rows = db.execute(select(SchoolCodeRegistry.district_code, func.count()).where(
            SchoolCodeRegistry.registry_status == "active", SchoolCodeRegistry.block_code == db.get(Block, p.block_id).code)
            .group_by(SchoolCodeRegistry.district_code)).all()
    else:
        reg_rows = db.execute(select(SchoolCodeRegistry.district_code, func.count()).where(
            SchoolCodeRegistry.registry_status == "active").group_by(SchoolCodeRegistry.district_code)).all()
    registry = dict(reg_rows)
    ids_all = [s.id for s in schools] or [-1]
    teachers = dict(db.execute(select(School.district_id, func.count(TeacherProfile.user_id))
                               .join(School, School.id == TeacherProfile.school_id)
                               .where(School.id.in_(ids_all), TeacherProfile.verification_status == "verified")
                               .group_by(School.district_id)).all())
    students = dict(db.execute(select(School.district_id, func.count(StudentEnrollment.id))
                               .join(ClassSection, ClassSection.id == StudentEnrollment.class_section_id)
                               .join(School, School.id == ClassSection.school_id)
                               .where(School.id.in_(ids_all), StudentEnrollment.active.is_(True))
                               .group_by(School.district_id)).all())
    pending = dict(db.execute(scope_schools(select(School.district_id, func.count(School.id)), p)
                              .where(School.status == "pending").group_by(School.district_id)).all())
    divisions = {d.id: d for d in db.scalars(select(Division))}
    extra = _objective_metrics(db, schools)
    rows = []
    for d in visible:
        info = geo.lookup(d.name)
        ds = by_d.get(d.id, [])
        div = divisions.get(d.division_id)
        rows.append({
            "id": d.id, "code": d.code, "name": d.name, "name_hi": d.name_hi, "is_demo": d.is_demo,
            "division": div.code if div else None,
            "map_shape": info.map_shape if info else None, "created_2022": bool(info and info.created_2022),
            "schools_active": len(ds), "schools_pending": pending.get(d.id, 0),
            "registry_schools": registry.get(d.code, 0), "teachers": teachers.get(d.id, 0),
            "students": students.get(d.id, 0), "metrics": {**analytics.aggregate(ds, snaps), **extra(ds)},
            "needs_support": sum(1 for s in ds if analytics.support_flags(
                snaps.get(s.id), analytics.data_status(snaps.get(s.id))))})
    div_rows = []
    for div in sorted(divisions.values(), key=lambda v: [c for c, _, _ in geo.DIVISIONS].index(v.code)
                      if v.code in [c for c, _, _ in geo.DIVISIONS] else 99):
        members = [r for r in rows if r["division"] == div.code]
        if not members:
            continue
        ds = [s for r in members for s in by_d.get(r["id"], [])]
        div_rows.append({"code": div.code, "name": div.name, "name_hi": div.name_hi,
                         "districts": len(members), "schools_active": len(ds),
                         "registry_schools": sum(r["registry_schools"] for r in members),
                         "teachers": sum(r["teachers"] for r in members),
                         "students": sum(r["students"] for r in members),
                         "needs_support": sum(r["needs_support"] for r in members),
                         "metrics": {**analytics.aggregate(ds, snaps), **extra(ds)}})
    unassigned = [r for r in rows if r["division"] is None]
    return {"divisions": div_rows, "districts": rows, "unassigned_districts": len(unassigned),
            "demo": any(r["is_demo"] for r in rows),
            "boundaries": "/static/data/cg-districts.geojson",
            "boundary_note": "Boundaries: geoBoundaries 2021 (28 districts, ODbL), simplified and indicative only. "
                             "The five districts created in 2022 are drawn inside the district they were formed "
                             "from; their own figures are listed in the table.",
            "generated_at": utcnow().isoformat() + "Z"}


@router.get("/geography")
def geography(p: Principal = AnyAdmin, db: Session = Depends(get_db)):
    """Districts/blocks the admin may use in filters and forms."""
    out = []
    for d in db.scalars(select(District).order_by(District.name)):
        if not admin_can_see_district(p, d.id):
            continue
        out.append({"id": d.id, "name": d.name, "name_hi": d.name_hi,
                    "blocks": [{"id": b.id, "name": b.name, "name_hi": b.name_hi}
                               for b in d.blocks if admin_can_see_block(p, b)]})
    return out
