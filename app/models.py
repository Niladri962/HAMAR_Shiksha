"""Database schema for HAMAR SHIKSHA.

Portable across SQLite (development/tests) and PostgreSQL (production).
Every table that can hold demonstration rows carries an `is_demo` flag so demo
data is never mistaken for government data and can be purged in one step.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_public_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------- roles ----

STATE_ADMIN = "state_admin"
DISTRICT_ADMIN = "district_admin"
BLOCK_ADMIN = "block_admin"
TEACHER = "teacher"
STUDENT = "student"

ADMIN_ROLES = (STATE_ADMIN, DISTRICT_ADMIN, BLOCK_ADMIN)
ROLE_PORTAL = {
    STATE_ADMIN: "admin",
    DISTRICT_ADMIN: "admin",
    BLOCK_ADMIN: "admin",
    TEACHER: "teacher",
    STUDENT: "student",
}
PORTALS = ("admin", "teacher", "student")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    portal: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(200), default="")


# ------------------------------------------------------------ geography ----

class Division(Base):
    """Revenue division (Raipur, Durg, Bilaspur, Surguja, Bastar): an
    analysis grouping of districts, not an access-control scope."""

    __tablename__ = "divisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    name_hi: Mapped[str] = mapped_column(String(60), default="")


class District(Base):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True)  # UDISE+ state(2)+district(2)
    name: Mapped[str] = mapped_column(String(100))
    name_hi: Mapped[str] = mapped_column(String(100), default="")
    division_id: Mapped[int | None] = mapped_column(ForeignKey("divisions.id"), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    blocks: Mapped[list["Block"]] = relationship(back_populates="district")
    division: Mapped["Division | None"] = relationship()


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("district_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), index=True)
    code: Mapped[str] = mapped_column(String(6), unique=True)  # district code + block(2)
    name: Mapped[str] = mapped_column(String(100))
    name_hi: Mapped[str] = mapped_column(String(100), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    district: Mapped[District] = relationship(back_populates="blocks")


# -------------------------------------------------------- school registry ----

class SchoolCodeRegistry(Base):
    """Authoritative list of official school codes, imported only from an
    approved government source (e.g. a UDISE+ extract). Schools can be
    registered on the platform only for codes present and active here."""

    __tablename__ = "school_code_registry"
    code: Mapped[str] = mapped_column(String(11), primary_key=True)
    school_name: Mapped[str] = mapped_column(String(200))
    district_code: Mapped[str] = mapped_column(String(4), index=True)
    block_code: Mapped[str] = mapped_column(String(6), index=True)
    locality: Mapped[str] = mapped_column(String(150), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    management: Mapped[str] = mapped_column(String(60), default="")
    registry_status: Mapped[str] = mapped_column(String(16), default="active")  # active|closed|merged
    source: Mapped[str] = mapped_column(String(60))  # e.g. "UDISE+ 2025-26 extract", "DEMO"
    source_reference: Mapped[str] = mapped_column(String(200), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class School(Base):
    __tablename__ = "schools"
    __table_args__ = (
        CheckConstraint("lowest_class >= 1 AND highest_class <= 12 AND lowest_class <= highest_class",
                        name="ck_school_classes"),
        CheckConstraint("status IN ('pending','active','suspended','closed')", name="ck_school_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    official_code: Mapped[str] = mapped_column(
        ForeignKey("school_code_registry.code"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"), index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id"), index=True)
    locality: Mapped[str] = mapped_column(String(150), default="")
    locality_type: Mapped[str] = mapped_column(String(10), default="rural")  # rural|urban
    category: Mapped[str] = mapped_column(String(60), default="")
    medium: Mapped[str] = mapped_column(String(30), default="Hindi")
    lowest_class: Mapped[int] = mapped_column(Integer, default=1)
    highest_class: Mapped[int] = mapped_column(Integer, default=8)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    district: Mapped[District] = relationship()
    block: Mapped[Block] = relationship()


# ------------------------------------------------------------------ users ----

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, default=new_public_id)
    login_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)  # normalised
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(12), default="active")  # pending|active|disabled
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_language: Mapped[str] = mapped_column(String(5), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    role_assignments: Mapped[list["UserRoleAssignment"]] = relationship(
        back_populates="user", foreign_keys="UserRoleAssignment.user_id")


class UserRoleAssignment(Base):
    """A role plus its scope. Admin scope columns: state admin -> none,
    district admin -> district_id, block admin -> block_id (+ district_id)."""

    __tablename__ = "user_role_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="role_assignments", foreign_keys=[user_id])
    role: Mapped[Role] = relationship()


class TeacherProfile(Base):
    __tablename__ = "teacher_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(40), unique=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    designation: Mapped[str] = mapped_column(String(80), default="Teacher")
    is_head_teacher: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|verified|rejected
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Subject codes the teacher is qualified/trained in (from HRMS when integrated).
    subject_qualifications: Mapped[list] = mapped_column(JSON, default=list)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    school: Mapped[School] = relationship()


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    # Internal, non-sequential identifier. Never derived from name/roll number.
    student_uid: Mapped[str] = mapped_column(String(32), unique=True, default=new_public_id)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    gender: Mapped[str | None] = mapped_column(String(10))
    birth_year: Mapped[int | None] = mapped_column(Integer)  # data minimisation: no full DOB
    guardian_name: Mapped[str | None] = mapped_column(String(150))
    guardian_phone: Mapped[str | None] = mapped_column(String(20))
    guardian_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    school: Mapped[School] = relationship()


# --------------------------------------------------------------- academics ----

class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    name_hi: Mapped[str] = mapped_column(String(80), default="")


class ClassSection(Base):
    __tablename__ = "class_sections"
    __table_args__ = (
        UniqueConstraint("school_id", "grade", "section", "academic_year"),
        CheckConstraint("grade BETWEEN 1 AND 12", name="ck_grade"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(4), default="A")
    academic_year: Mapped[str] = mapped_column(String(9))  # e.g. 2026-27

    school: Mapped[School] = relationship()

    @property
    def label(self) -> str:
        return f"Class {self.grade}-{self.section}"


class TeacherClassAssignment(Base):
    __tablename__ = "teacher_class_assignments"
    __table_args__ = (UniqueConstraint("teacher_user_id", "class_section_id", "subject_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    is_class_teacher: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    class_section: Mapped[ClassSection] = relationship()
    subject: Mapped[Subject] = relationship()


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    __table_args__ = (UniqueConstraint("class_section_id", "day_of_week", "period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    teacher_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)  # 0=Mon
    period: Mapped[int] = mapped_column(Integer)


class StudentEnrollment(Base):
    __tablename__ = "student_enrollments"
    __table_args__ = (UniqueConstraint("student_user_id", "academic_year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    academic_year: Mapped[str] = mapped_column(String(9))
    roll_no: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    enrolled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    class_section: Mapped[ClassSection] = relationship()
    student: Mapped[User] = relationship(foreign_keys=[student_user_id])


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("person_user_id", "date"),
        Index("ix_att_school_date", "school_id", "date"),
        CheckConstraint("status IN ('present','absent','late','leave')", name="ck_att_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    person_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    person_type: Mapped[str] = mapped_column(String(8))  # student|teacher
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_section_id: Mapped[int | None] = mapped_column(ForeignKey("class_sections.id"))
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="homework")  # homework|worksheet|project
    topic: Mapped[str] = mapped_column(String(120), default="")
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject] = relationship()


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), index=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    feedback: Mapped[str | None] = mapped_column(Text)
    feedback_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Assessment(Base):
    """A quiz/test. `questions` is a list of
    {id, text, options: [..], answer_index, topic}. Answer keys are never sent
    to the student portal."""

    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(20), default="quiz")  # quiz|unit_test|baseline|offline
    max_score: Mapped[float] = mapped_column(Float, default=0)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject] = relationship()
    class_section: Mapped[ClassSection] = relationship()


class AssessmentResult(Base):
    __tablename__ = "assessment_results"
    __table_args__ = (UniqueConstraint("assessment_id", "student_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    answers: Mapped[dict | None] = mapped_column(JSON)
    topic_breakdown: Mapped[dict | None] = mapped_column(JSON)  # {topic: [correct, total]}
    # Per-question outcome: [{id, score, max, method, confidence, needs_review, lo}]
    item_results: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="final")  # final|pending_review
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # null = auto-graded

    assessment: Mapped[Assessment] = relationship()


class LearningActivity(Base):
    """Approved learning content (lesson, exercise) for a grade and subject."""

    __tablename__ = "learning_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer, index=True)
    topic: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="lesson")  # lesson|exercise
    language: Mapped[str] = mapped_column(String(5), default="en")
    content: Mapped[dict] = mapped_column(JSON, default=dict)  # {body, questions?}
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject] = relationship()


class ActivityCompletion(Base):
    __tablename__ = "activity_completions"
    __table_args__ = (UniqueConstraint("activity_id", "student_user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(ForeignKey("learning_activities.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float | None] = mapped_column(Float)  # fraction 0..1 for exercises
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LearningProgress(Base):
    """Rolling per-topic mastery for a student, rebuilt from results and
    completed exercises. Mastery is a working estimate, never a label."""

    __tablename__ = "learning_progress"
    __table_args__ = (UniqueConstraint("student_user_id", "subject_id", "topic"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    topic: Mapped[str] = mapped_column(String(120))
    correct: Mapped[int] = mapped_column(Integer, default=0)
    attempted: Mapped[int] = mapped_column(Integer, default=0)
    mastery: Mapped[float] = mapped_column(Float, default=0.0)  # correct/attempted
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subject: Mapped[Subject] = relationship()


class AIRecommendation(Base):
    """Every AI insight is stored with the evidence it was derived from, so it
    is explainable and reviewable. Status moves pending_review -> approved |
    dismissed by an authorised educator; nothing is acted on automatically."""

    __tablename__ = "ai_recommendations"
    __table_args__ = (Index("ix_rec_target", "target_type", "target_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(12))  # student|class|school|block|district|state
    target_id: Mapped[int | None] = mapped_column(Integer)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), index=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"))
    audience: Mapped[str] = mapped_column(String(10))  # student|teacher|admin
    kind: Mapped[str] = mapped_column(String(30))  # practice|remedial_plan|intervention|...
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    data_sources: Mapped[list] = mapped_column(JSON, default=list)  # [{table, ids}]
    generated_by: Mapped[str] = mapped_column(String(40))  # rules-engine-v1 | llm:<model>
    status: Mapped[str] = mapped_column(String(16), default="pending_review")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AIInteraction(Base):
    """Log of the supervised student assistant, kept for a limited retention
    period so teachers can review flagged exchanges."""

    __tablename__ = "ai_interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    class_section_id: Mapped[int | None] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(60))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SchoolPerformanceSnapshot(Base):
    """Monthly aggregate per school, computed from raw records. Dashboards read
    only these aggregates, so statewide views never touch student identities."""

    __tablename__ = "school_performance_snapshots"
    __table_args__ = (UniqueConstraint("school_id", "period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    as_of: Mapped[date] = mapped_column(Date)  # last date with source data in period
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    teacher_count: Mapped[int] = mapped_column(Integer, default=0)
    student_attendance_rate: Mapped[float | None] = mapped_column(Float)
    teacher_attendance_rate: Mapped[float | None] = mapped_column(Float)
    assessment_participation: Mapped[float | None] = mapped_column(Float)
    avg_score_pct: Mapped[float | None] = mapped_column(Float)
    subject_scores: Mapped[dict] = mapped_column(JSON, default=dict)  # {subject_code: pct}
    grade_scores: Mapped[dict] = mapped_column(JSON, default=dict)  # {grade: pct}
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(40), default="platform-records")
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SchoolReport(Base):
    """Academic report submitted by a teacher to the administration."""

    __tablename__ = "school_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    period: Mapped[str] = mapped_column(String(7))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="submitted")  # submitted|acknowledged
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------- security ----

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    portal: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempt_lookup", "identifier", "at"), Index("ix_login_ip", "ip", "at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(120))
    portal: Mapped[str] = mapped_column(String(10))
    ip: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_at", "at"), Index("ix_audit_entity", "entity_type", "entity_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(10), default="success")  # success|denied|failure
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


# ===================================================== curriculum knowledge base ====

class CurriculumDocument(Base):
    """An authorised source document (textbook, syllabus, LO framework...)."""

    __tablename__ = "curriculum_documents"
    __table_args__ = (UniqueConstraint("checksum"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    doc_type: Mapped[str] = mapped_column(String(30))  # textbook|syllabus|lo_framework|lesson_material|question_paper|training
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    grade: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(5), default="hi")
    curriculum_version: Mapped[str] = mapped_column(String(40))
    publisher: Mapped[str] = mapped_column(String(120))        # e.g. "SCERT Chhattisgarh" or "DEMO"
    source_file: Mapped[str] = mapped_column(String(300))
    checksum: Mapped[str] = mapped_column(String(64))
    approval_status: Mapped[str] = mapped_column(String(16), default="approved")  # approved|pending|withdrawn
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject | None] = relationship()


class CurriculumChunk(Base):
    __tablename__ = "curriculum_chunks"
    __table_args__ = (Index("ix_chunk_filter", "grade", "subject_id", "language"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("curriculum_documents.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    chapter: Mapped[str | None] = mapped_column(String(200))
    grade: Mapped[int | None] = mapped_column(Integer)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    language: Mapped[str] = mapped_column(String(5))

    document: Mapped[CurriculumDocument] = relationship()


class LearningOutcome(Base):
    """Competency / learning outcome from the approved framework."""

    __tablename__ = "learning_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer, index=True)
    chapter_no: Mapped[int] = mapped_column(Integer, default=1)
    chapter_title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    description_hi: Mapped[str] = mapped_column(Text, default="")
    planned_periods: Mapped[int] = mapped_column(Integer, default=6)
    curriculum_version: Mapped[str] = mapped_column(String(40))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("curriculum_documents.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject] = relationship()


class AcademicCalendar(Base):
    __tablename__ = "academic_calendars"
    __table_args__ = (UniqueConstraint("academic_year", "district_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(9))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))  # null = statewide
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    holidays: Mapped[list] = mapped_column(JSON, default=list)       # [{"from","to","name"}]
    exam_windows: Mapped[list] = mapped_column(JSON, default=list)   # [{"name","from","to"}]
    working_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4, 5])
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class LessonPlan(Base):
    __tablename__ = "lesson_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int | None] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    grade: Mapped[int] = mapped_column(Integer)
    learning_outcome_id: Mapped[int | None] = mapped_column(ForeignKey("learning_outcomes.id"))
    topic: Mapped[str] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(5), default="hi")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{chunk_id, citation}]
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|approved|archived
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    subject: Mapped[Subject] = relationship()


class TeachingMilestone(Base):
    """Planned-versus-taught tracking: one row per class x learning outcome."""

    __tablename__ = "teaching_milestones"
    __table_args__ = (UniqueConstraint("class_section_id", "learning_outcome_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    learning_outcome_id: Mapped[int] = mapped_column(ForeignKey("learning_outcomes.id"))
    planned_week_start: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="planned")  # planned|taught
    taught_at: Mapped[datetime | None] = mapped_column(DateTime)
    taught_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    lesson_plan_id: Mapped[int | None] = mapped_column(ForeignKey("lesson_plans.id"))

    learning_outcome: Mapped[LearningOutcome] = relationship()


class ClassSession(Base):
    """A delivered lesson; mode='substitute' when a supervisor launches an
    approved lesson plan because the subject teacher is absent."""

    __tablename__ = "class_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    lesson_plan_id: Mapped[int] = mapped_column(ForeignKey("lesson_plans.id"))
    mode: Mapped[str] = mapped_column(String(12), default="substitute")
    launched_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    lesson_plan: Mapped[LessonPlan] = relationship()


# ============================================================ Pariksha Engine ====

class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_question_lookup", "subject_id", "grade", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    grade: Mapped[int] = mapped_column(Integer)
    learning_outcome_id: Mapped[int | None] = mapped_column(ForeignKey("learning_outcomes.id"), index=True)
    topic: Mapped[str] = mapped_column(String(120))
    qtype: Mapped[str] = mapped_column(String(12))  # mcq|short|descriptive
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=2)  # 1 easy .. 3 hard
    language: Mapped[str] = mapped_column(String(5), default="en")
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft|approved|retired
    source: Mapped[str] = mapped_column(String(20), default="teacher")  # scert|teacher|ai_draft|demo
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    learning_outcome: Mapped[LearningOutcome | None] = relationship()
    answer_key: Mapped["AnswerKey"] = relationship(back_populates="question", uselist=False)


class AnswerKey(Base):
    """Kept apart from questions so keys are never serialised to students."""

    __tablename__ = "answer_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), unique=True)
    correct_option: Mapped[int | None] = mapped_column(Integer)
    accepted_answers: Mapped[list] = mapped_column(JSON, default=list)
    rubric: Mapped[str | None] = mapped_column(Text)
    max_marks: Mapped[float] = mapped_column(Float, default=1)
    misconceptions: Mapped[dict] = mapped_column(JSON, default=dict)  # {option_index: note}

    question: Mapped[Question] = relationship(back_populates="answer_key")


class LearnerCompetency(Base):
    __tablename__ = "learner_competencies"
    __table_args__ = (UniqueConstraint("student_user_id", "learning_outcome_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    learning_outcome_id: Mapped[int] = mapped_column(ForeignKey("learning_outcomes.id"))
    correct: Mapped[float] = mapped_column(Float, default=0)
    attempted: Mapped[float] = mapped_column(Float, default=0)
    mastery: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(16), default="developing")  # developing|needs_practice|achieved
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # last N learner_event uids
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    learning_outcome: Mapped[LearningOutcome] = relationship()


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    learning_outcome_id: Mapped[int | None] = mapped_column(ForeignKey("learning_outcomes.id"))
    topic: Mapped[str] = mapped_column(String(120))
    student_ids: Mapped[list] = mapped_column(JSON, default=list)
    plan_text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default="proposed")  # proposed|approved|completed|dismissed
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_recommendations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class TeacherTrainingModule(Base):
    __tablename__ = "teacher_training_modules"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    title_hi: Mapped[str] = mapped_column(String(200), default="")
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    competency_area: Mapped[str] = mapped_column(String(80))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    content: Mapped[dict] = mapped_column(JSON, default=dict)  # {sections:[{heading, body}], check:[{q, options, answer}]}
    status: Mapped[str] = mapped_column(String(10), default="approved")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class TrainingCompletion(Base):
    __tablename__ = "training_completions"
    __table_args__ = (UniqueConstraint("teacher_user_id", "module_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("teacher_training_modules.id"))
    score: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ============================================= learner record & synchronisation ====

class LearnerEvent(Base):
    """Append-only learner record. Every attendance mark, assessment result,
    activity completion and approved intervention produces one validated row;
    progress and competencies are derived from these events."""

    __tablename__ = "learner_events"
    __table_args__ = (Index("ix_learner_event_student", "student_user_id", "occurred_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_uid: Mapped[str] = mapped_column(String(64), unique=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_section_id: Mapped[int | None] = mapped_column(ForeignKey("class_sections.id"))
    event_type: Mapped[str] = mapped_column(String(30))  # attendance|assessment_result|activity_completion|lesson_completed|intervention
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(10), default="online")  # online|sync|import
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device_registry.id"))


class DeviceRegistry(Base):
    __tablename__ = "device_registry"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_uid: Mapped[str] = mapped_column(String(64), unique=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), index=True)
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(120), default="")
    profile: Mapped[str] = mapped_column(String(16), default="browser")  # school_pc|smart_class|android|browser
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|revoked
    app_version: Mapped[str | None] = mapped_column(String(30))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)


class SynchronizationEvent(Base):
    __tablename__ = "synchronization_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_uid: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device_registry.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    client_created_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(10))  # accepted|duplicate|conflict|rejected
    detail: Mapped[str | None] = mapped_column(String(300))


# ===================================================== student self-improvement ====

class StudentGoal(Base):
    """A weekly goal a student sets for themselves. Progress for the built-in
    kinds is counted from the learner record; "custom" goals are ticked by hand."""

    __tablename__ = "student_goals"
    __table_args__ = (Index("ix_goal_student_week", "student_user_id", "week_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))  # practice|lessons|revision|chapters|helping|custom
    title: Mapped[str] = mapped_column(String(140))
    target: Mapped[int] = mapped_column(Integer, default=3)
    manual_progress: Mapped[int] = mapped_column(Integer, default=0)
    week_start: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RevisionItem(Base):
    """'My mistakes' deck: a question the student got wrong, re-asked on a
    spaced schedule (1, 3, 7 days) until answered correctly twice in a row."""

    __tablename__ = "revision_items"
    __table_args__ = (UniqueConstraint("student_user_id", "item_key"),
                      Index("ix_revision_due", "student_user_id", "mastered", "next_review"))
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_key: Mapped[str] = mapped_column(String(80))  # e.g. "assessment:12:q3"
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    topic: Mapped[str] = mapped_column(String(120), default="")
    question: Mapped[dict] = mapped_column(JSON)  # {text, options, answer_index, explanation?}
    times_wrong: Mapped[int] = mapped_column(Integer, default=1)
    correct_streak: Mapped[int] = mapped_column(Integer, default=0)
    next_review: Mapped[date] = mapped_column(Date)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Doubt(Base):
    """A student's question to their teacher ("teacher") or to the class doubt
    board ("class", answered by classmates and moderated by the teacher)."""

    __tablename__ = "doubts"
    __table_args__ = (Index("ix_doubt_class", "class_section_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    audience: Mapped[str] = mapped_column(String(8))  # teacher|class
    topic: Mapped[str] = mapped_column(String(120), default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|answered|resolved|hidden
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DoubtReply(Base):
    __tablename__ = "doubt_replies"
    id: Mapped[int] = mapped_column(primary_key=True)
    doubt_id: Mapped[int] = mapped_column(ForeignKey("doubts.id"), index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author_role: Mapped[str] = mapped_column(String(8))  # teacher|student
    body: Mapped[str] = mapped_column(Text)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)  # marked helpful by asker or teacher
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)    # removed by the teacher
    reported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class StudyPair(Base):
    """Peer learning pair set up by a teacher: a classmate who is strong in a
    topic helps one who is still practising it."""

    __tablename__ = "study_pairs"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    topic: Mapped[str] = mapped_column(String(120))
    helper_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    learner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|done|ended
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ------------------------------------------------- digital infrastructure ----

DIGITAL_KINDS = ("ict_lab", "smart_class", "digital_library", "language_lab", "tablets")


class DigitalResource(Base):
    """An ICT lab, smart class, digital library, language lab or tablet set
    registered for a school, with the weekly use the school is expected to make."""

    __tablename__ = "digital_resources"
    __table_args__ = (CheckConstraint("kind IN ('ict_lab','smart_class','digital_library','language_lab','tablets')",
                                      name="ck_digital_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), default="working")  # working|not_working
    devices: Mapped[int] = mapped_column(Integer, default=1)
    target_sessions_per_week: Mapped[int] = mapped_column(Integer, default=10)
    installed_year: Mapped[int | None] = mapped_column(Integer)
    status_note: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DigitalUsage(Base):
    """One session in which a class used a digital resource."""

    __tablename__ = "digital_usage"
    __table_args__ = (Index("ix_digital_usage_school_date", "school_id", "used_on"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("digital_resources.id"), index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    learning_outcome_id: Mapped[int | None] = mapped_column(ForeignKey("learning_outcomes.id"))
    teacher_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    used_on: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int] = mapped_column(Integer, default=35)
    activity: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(12), default="teacher")  # teacher|ai_class|device
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ----------------------------------------------------------- video lessons ----

class VideoLesson(Base):
    """A narrated, animated lesson for one class and topic, drafted by Gyan SLM
    from the approved textbook passages (or built from the passages when no
    model is available), edited and published by a teacher. Used when the
    subject teacher is unavailable, or for revision."""

    __tablename__ = "video_lessons"
    __table_args__ = (Index("ix_video_lesson_class", "class_section_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    topic: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(5), default="hi")
    scenes: Mapped[list] = mapped_column(JSON, default=list)   # [{heading, narration, points[], visual}]
    quiz: Mapped[list] = mapped_column(JSON, default=list)     # [{question, options[4], answer_index, explanation}]
    sources: Mapped[list] = mapped_column(JSON, default=list)  # textbook citations
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|published|archived
    reason: Mapped[str] = mapped_column(String(20), default="teacher_absent")  # teacher_absent|revision|catch_up
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(80))
    grounding: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ------------------------------------------------------------- recognition ----

class Appreciation(Base):
    """A note of appreciation from a person (teacher -> student, head teacher
    or administrator -> teacher). System badges are computed, not stored."""

    __tablename__ = "appreciations"
    __table_args__ = (Index("ix_appreciation_recipient", "recipient_user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    giver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    giver_role: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(20))  # effort|improvement|helping|creativity|regularity|innovation|milestones|mentoring
    message: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ------------------------------------------------------------ reference data ----

ROLE_DEFS = [
    (STATE_ADMIN, "admin", "Statewide monitoring and administration"),
    (DISTRICT_ADMIN, "admin", "District-scoped monitoring"),
    (BLOCK_ADMIN, "admin", "Block-scoped monitoring"),
    (TEACHER, "teacher", "Verified teacher at a registered school"),
    (STUDENT, "student", "Student enrolled at a registered school"),
]

SUBJECT_DEFS = [
    ("HIN", "Hindi", "हिंदी"),
    ("ENG", "English", "अंग्रेज़ी"),
    ("MATH", "Mathematics", "गणित"),
    ("EVS", "Environmental Studies", "पर्यावरण अध्ययन"),
    ("SCI", "Science", "विज्ञान"),
    ("SST", "Social Science", "सामाजिक विज्ञान"),
    ("SAN", "Sanskrit", "संस्कृत"),
]


def ensure_reference_data(db: Session) -> None:
    """Idempotently insert roles and the core subject list."""
    have = set(db.scalars(select(Role.name)))
    for name, portal, desc in ROLE_DEFS:
        if name not in have:
            db.add(Role(name=name, portal=portal, description=desc))
    have_subj = set(db.scalars(select(Subject.code)))
    for code, name, name_hi in SUBJECT_DEFS:
        if code not in have_subj:
            db.add(Subject(code=code, name=name, name_hi=name_hi))
