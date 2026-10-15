"""Data-scope rules. Out-of-scope objects are reported as 404 so that a
principal cannot even confirm the existence of records it may not see."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import (
    BLOCK_ADMIN,
    DISTRICT_ADMIN,
    STATE_ADMIN,
    Block,
    ClassSection,
    School,
    StudentEnrollment,
    TeacherClassAssignment,
)


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# ------------------------------------------------------------------ admins ----

def scope_schools(stmt: Select, principal: Principal) -> Select:
    """Restrict a statement that selects from `School` to the admin's scope."""
    if principal.role == STATE_ADMIN:
        return stmt
    if principal.role == DISTRICT_ADMIN and principal.district_id:
        return stmt.where(School.district_id == principal.district_id)
    if principal.role == BLOCK_ADMIN and principal.block_id:
        return stmt.where(School.block_id == principal.block_id)
    return stmt.where(False)  # misconfigured assignment -> sees nothing


def admin_can_see_school(principal: Principal, school: School) -> bool:
    if principal.role == STATE_ADMIN:
        return True
    if principal.role == DISTRICT_ADMIN:
        return principal.district_id is not None and school.district_id == principal.district_id
    if principal.role == BLOCK_ADMIN:
        return principal.block_id is not None and school.block_id == principal.block_id
    return False


def admin_can_see_district(principal: Principal, district_id: int) -> bool:
    if principal.role == STATE_ADMIN:
        return True
    return principal.district_id == district_id and principal.role in (DISTRICT_ADMIN, BLOCK_ADMIN)


def admin_can_see_block(principal: Principal, block: Block) -> bool:
    if principal.role == STATE_ADMIN:
        return True
    if principal.role == DISTRICT_ADMIN:
        return block.district_id == principal.district_id
    if principal.role == BLOCK_ADMIN:
        return block.id == principal.block_id
    return False


def get_school_for_admin(db: Session, principal: Principal, school_id: int) -> School:
    school = db.get(School, school_id)
    if school is None or not admin_can_see_school(principal, school):
        raise not_found("School")
    return school


def get_class_for_admin(db: Session, principal: Principal, class_id: int) -> ClassSection:
    cs = db.get(ClassSection, class_id)
    if cs is None or not admin_can_see_school(principal, cs.school):
        raise not_found("Class")
    return cs


# ---------------------------------------------------------------- teachers ----

def teacher_assignments(db: Session, teacher_id: int) -> list[TeacherClassAssignment]:
    return list(db.scalars(select(TeacherClassAssignment).where(
        TeacherClassAssignment.teacher_user_id == teacher_id,
        TeacherClassAssignment.active.is_(True))))


def teacher_class_ids(db: Session, teacher_id: int) -> set[int]:
    return {a.class_section_id for a in teacher_assignments(db, teacher_id)}


def get_class_for_teacher(db: Session, principal: Principal, class_id: int,
                          subject_id: int | None = None) -> ClassSection:
    stmt = select(TeacherClassAssignment).where(
        TeacherClassAssignment.teacher_user_id == principal.user.id,
        TeacherClassAssignment.class_section_id == class_id,
        TeacherClassAssignment.active.is_(True))
    if subject_id is not None:
        stmt = stmt.where(TeacherClassAssignment.subject_id == subject_id)
    if db.scalar(stmt.limit(1)) is None:
        raise not_found("Class")
    return db.get(ClassSection, class_id)


def teacher_can_see_student(db: Session, teacher_id: int, student_id: int) -> bool:
    class_ids = teacher_class_ids(db, teacher_id)
    if not class_ids:
        return False
    return db.scalar(select(StudentEnrollment.id).where(
        StudentEnrollment.student_user_id == student_id,
        StudentEnrollment.active.is_(True),
        StudentEnrollment.class_section_id.in_(class_ids)).limit(1)) is not None


# ---------------------------------------------------------------- students ----

def current_enrollment(db: Session, student_id: int) -> StudentEnrollment | None:
    return db.scalar(select(StudentEnrollment).where(
        StudentEnrollment.student_user_id == student_id,
        StudentEnrollment.active.is_(True)).order_by(StudentEnrollment.academic_year.desc()).limit(1))
