"""Account provisioning shared by the admin and head-teacher workflows."""
from __future__ import annotations

import secrets

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    STUDENT,
    TEACHER,
    ClassSection,
    Role,
    School,
    StudentEnrollment,
    StudentProfile,
    TeacherProfile,
    User,
    UserRoleAssignment,
    utcnow,
)
from app.security import generate_temporary_password, hash_password, normalise_login_id


def role_id(db: Session, name: str) -> int:
    return db.scalar(select(Role.id).where(Role.name == name))


def _new_student_login(db: Session) -> str:
    """Random, non-sequential student login ID (no name, roll number or school code)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    while True:
        candidate = "st-" + "".join(secrets.choice(alphabet) for _ in range(7))
        if db.scalar(select(User.id).where(User.login_id == candidate)) is None:
            return candidate


def create_user(db: Session, *, login_id: str, full_name: str, role_name: str, granted_by: int | None,
                email: str | None = None, phone: str | None = None, password: str | None = None,
                district_id: int | None = None, block_id: int | None = None,
                school_id: int | None = None, is_demo: bool = False) -> tuple[User, str | None]:
    """Create a user plus role assignment. Returns (user, temporary_password).

    When no password is given a one-time password is issued and must be
    changed at first sign-in. The temporary password is returned once and
    never stored in clear.
    """
    login_id = normalise_login_id(login_id)
    if not login_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Login ID is required")
    if db.scalar(select(User.id).where(User.login_id == login_id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this login ID already exists")
    temp = None
    if password is None:
        temp = password = generate_temporary_password()
    user = User(login_id=login_id, full_name=full_name.strip(), email=email, phone=phone,
                password_hash=hash_password(password), must_change_password=temp is not None,
                is_demo=is_demo)
    db.add(user)
    db.flush()
    db.add(UserRoleAssignment(user_id=user.id, role_id=role_id(db, role_name), district_id=district_id,
                              block_id=block_id, school_id=school_id, granted_by=granted_by))
    db.flush()
    return user, temp


def invite_teacher(db: Session, *, school: School, employee_id: str, full_name: str,
                   designation: str, email: str | None, phone: str | None, invited_by: int,
                   is_head_teacher: bool = False, is_demo: bool = False) -> tuple[User, str]:
    if school.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "School is not active")
    employee_id = employee_id.strip().upper()
    if db.scalar(select(TeacherProfile.user_id).where(TeacherProfile.employee_id == employee_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A teacher with this employee ID already exists")
    user, temp = create_user(db, login_id=employee_id, full_name=full_name, role_name=TEACHER,
                             granted_by=invited_by, email=email, phone=phone, school_id=school.id,
                             is_demo=is_demo)
    db.add(TeacherProfile(user_id=user.id, employee_id=employee_id, school_id=school.id,
                          designation=designation, is_head_teacher=is_head_teacher,
                          verification_status="pending"))
    db.flush()
    return user, temp


def verify_teacher(db: Session, profile: TeacherProfile, *, approve: bool, by: int) -> None:
    profile.verification_status = "verified" if approve else "rejected"
    profile.verified_by = by
    profile.verified_at = utcnow()
    if not approve:
        profile.user.status = "disabled"


def enroll_student(db: Session, *, cs: ClassSection, full_name: str, guardian_name: str,
                   guardian_phone: str | None, guardian_consent: bool, birth_year: int | None,
                   gender: str | None, roll_no: int | None, enrolled_by: int,
                   is_demo: bool = False) -> tuple[User, str]:
    if cs.school.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "School is not active")
    if not guardian_consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Guardian consent must be recorded before a student account is created")
    user, temp = create_user(db, login_id=_new_student_login(db), full_name=full_name,
                             role_name=STUDENT, granted_by=enrolled_by, school_id=cs.school_id,
                             is_demo=is_demo)
    db.add(StudentProfile(user_id=user.id, school_id=cs.school_id, gender=gender, birth_year=birth_year,
                          guardian_name=guardian_name, guardian_phone=guardian_phone,
                          guardian_consent=True, consent_recorded_at=utcnow(),
                          consent_recorded_by=enrolled_by))
    db.add(StudentEnrollment(student_user_id=user.id, class_section_id=cs.id,
                             academic_year=cs.academic_year, roll_no=roll_no, enrolled_by=enrolled_by))
    db.flush()
    return user, temp


def reset_to_temporary_password(db: Session, user: User) -> str:
    temp = generate_temporary_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    return temp
