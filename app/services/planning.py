"""Teacher Saathi planning: academic calendar -> annual/monthly/weekly plan
of learning-outcome milestones, one-tap "taught" recording, and the
planned-versus-taught-versus-learned measure used by the Command Centre.
All figures are computed deterministically from structured records."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AcademicCalendar,
    ClassSection,
    LearnerCompetency,
    LearningOutcome,
    School,
    StudentEnrollment,
    Subject,
    TeacherClassAssignment,
    TeacherProfile,
    TeachingMilestone,
    TrainingCompletion,
    TeacherTrainingModule,
    utcnow,
)

LEARNED_AT = 0.6  # class mean mastery at which an outcome counts as "learned"


def calendar_for(db: Session, cs: ClassSection) -> AcademicCalendar | None:
    cal = db.scalar(select(AcademicCalendar).where(AcademicCalendar.academic_year == cs.academic_year,
                                                   AcademicCalendar.district_id == cs.school.district_id))
    return cal or db.scalar(select(AcademicCalendar).where(AcademicCalendar.academic_year == cs.academic_year,
                                                           AcademicCalendar.district_id.is_(None)))


def teaching_weeks(cal: AcademicCalendar) -> list[date]:
    """Mondays of weeks that have at least 3 teaching days (holidays and exam windows excluded)."""
    blocked = []
    for h in (cal.holidays or []) + (cal.exam_windows or []):
        blocked.append((date.fromisoformat(h["from"]), date.fromisoformat(h["to"])))
    weeks = []
    monday = cal.start_date - timedelta(days=cal.start_date.weekday())
    while monday <= cal.end_date:
        days = [monday + timedelta(days=i) for i in range(7)]
        teaching = [d for d in days if cal.start_date <= d <= cal.end_date and d.weekday() in cal.working_days
                    and not any(a <= d <= b for a, b in blocked)]
        if len(teaching) >= 3:
            weeks.append(monday)
        monday += timedelta(days=7)
    return weeks


def generate_plan(db: Session, cs: ClassSection, subject_id: int) -> int:
    """Spread the subject's learning outcomes over the year's teaching weeks in
    syllabus order, weighted by planned periods. Idempotent."""
    cal = calendar_for(db, cs)
    if cal is None:
        return 0
    weeks = teaching_weeks(cal)
    los = db.scalars(select(LearningOutcome).where(LearningOutcome.subject_id == subject_id,
                                                   LearningOutcome.grade == cs.grade)
                     .order_by(LearningOutcome.chapter_no, LearningOutcome.code)).all()
    if not weeks or not los:
        return 0
    total = sum(lo.planned_periods for lo in los)
    existing = set(db.scalars(select(TeachingMilestone.learning_outcome_id).where(
        TeachingMilestone.class_section_id == cs.id, TeachingMilestone.subject_id == subject_id)))
    acc, created = 0, 0
    # Leave the last ~15% of weeks for revision.
    usable = weeks[: max(1, int(len(weeks) * 0.85))]
    for lo in los:
        week = usable[min(len(usable) - 1, int(acc / total * len(usable)))]
        acc += lo.planned_periods
        if lo.id in existing:
            continue
        db.add(TeachingMilestone(class_section_id=cs.id, subject_id=subject_id, learning_outcome_id=lo.id,
                                 planned_week_start=week))
        created += 1
    db.flush()
    return created


def plan_view(db: Session, cs: ClassSection, subject_id: int, *, scope: str = "month",
              ref: date | None = None) -> list[dict]:
    ref = ref or date.today()
    stmt = select(TeachingMilestone).where(TeachingMilestone.class_section_id == cs.id,
                                           TeachingMilestone.subject_id == subject_id)
    if scope == "week":
        start = ref - timedelta(days=ref.weekday())
        stmt = stmt.where(TeachingMilestone.planned_week_start == start)
    elif scope == "month":
        start = ref.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        stmt = stmt.where(TeachingMilestone.planned_week_start >= start - timedelta(days=6),
                          TeachingMilestone.planned_week_start < end)
    rows = db.scalars(stmt.order_by(TeachingMilestone.planned_week_start)).all()
    learned = class_learned(db, cs.id, [m.learning_outcome_id for m in rows])
    return [{"id": m.id, "week": m.planned_week_start.isoformat(), "code": m.learning_outcome.code,
             "chapter": m.learning_outcome.chapter_title, "topic": m.learning_outcome.topic,
             "description": m.learning_outcome.description, "description_hi": m.learning_outcome.description_hi,
             "status": m.status, "taught_at": m.taught_at.isoformat() if m.taught_at else None,
             "overdue": m.status == "planned" and m.planned_week_start + timedelta(days=6) < ref,
             "learned": learned.get(m.learning_outcome_id), "lesson_plan_id": m.lesson_plan_id} for m in rows]


def mark_taught(db: Session, m: TeachingMilestone, teacher_id: int, lesson_plan_id: int | None = None,
                at=None) -> bool:
    if m.status == "taught":
        return False
    m.status, m.taught_at, m.taught_by = "taught", at or utcnow(), teacher_id
    if lesson_plan_id:
        m.lesson_plan_id = lesson_plan_id
    return True


def class_learned(db: Session, class_id: int, lo_ids: list[int]) -> dict[int, dict]:
    sids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id == class_id, StudentEnrollment.active.is_(True))))
    out: dict[int, dict] = {}
    rows = db.execute(select(LearnerCompetency.learning_outcome_id, func.avg(LearnerCompetency.mastery),
                             func.count()).where(LearnerCompetency.student_user_id.in_(sids or [-1]),
                                                 LearnerCompetency.learning_outcome_id.in_(lo_ids or [-1]),
                                                 LearnerCompetency.attempted >= 3)
                      .group_by(LearnerCompetency.learning_outcome_id)).all()
    for lo_id, avg, n in rows:
        out[lo_id] = {"avg_mastery": round(avg, 4), "students_assessed": n, "learned": avg >= LEARNED_AT}
    return out


def ptl_for_classes(db: Session, class_ids: list[int], today: date | None = None) -> dict:
    """Planned (due by today) vs taught vs learned, over a set of classes."""
    today = today or date.today()
    ms = db.scalars(select(TeachingMilestone).where(TeachingMilestone.class_section_id.in_(class_ids or [-1]),
                                                    TeachingMilestone.planned_week_start <= today)).all()
    by_class = defaultdict(list)
    for m in ms:
        by_class[m.class_section_id].append(m)
    planned = len(ms)
    taught = sum(1 for m in ms if m.status == "taught")
    learned = 0
    assessed = 0
    for cid, items in by_class.items():
        res = class_learned(db, cid, [m.learning_outcome_id for m in items if m.status == "taught"])
        assessed += len(res)
        learned += sum(1 for v in res.values() if v["learned"])
    return {"planned_due": planned, "taught": taught, "assessed": assessed, "learned": learned,
            "taught_rate": round(taught / planned, 4) if planned else None,
            "learned_rate": round(learned / assessed, 4) if assessed else None,
            "basis": f"{planned} outcomes scheduled up to {today.isoformat()} in {len(by_class)} class-subjects"}


def expertise_gaps(db: Session, school_ids: list[int]) -> list[dict]:
    """Teaching assignments where the teacher has neither a recorded subject
    qualification nor a completed micro-course for that subject."""
    rows = db.execute(select(TeacherClassAssignment, TeacherProfile, Subject, ClassSection, School)
                      .join(TeacherProfile, TeacherProfile.user_id == TeacherClassAssignment.teacher_user_id)
                      .join(Subject, Subject.id == TeacherClassAssignment.subject_id)
                      .join(ClassSection, ClassSection.id == TeacherClassAssignment.class_section_id)
                      .join(School, School.id == ClassSection.school_id)
                      .where(School.id.in_(school_ids or [-1]), TeacherClassAssignment.active.is_(True))).all()
    trained = defaultdict(set)
    for tid, sid in db.execute(select(TrainingCompletion.teacher_user_id, TeacherTrainingModule.subject_id)
                               .join(TeacherTrainingModule, TeacherTrainingModule.id == TrainingCompletion.module_id)):
        if sid:
            trained[tid].add(sid)
    gaps: dict[tuple, dict] = {}
    for a, prof, subj, cs, school in rows:
        if subj.code in (prof.subject_qualifications or []) or subj.id in trained[prof.user_id]:
            continue
        key = (school.id, subj.code)
        g = gaps.setdefault(key, {"school_id": school.id, "school": school.name, "official_code": school.official_code,
                                  "district_id": school.district_id, "block_id": school.block_id,
                                  "subject": subj.name, "subject_code": subj.code, "classes": set(), "teachers": set()})
        g["classes"].add(cs.grade)
        g["teachers"].add(prof.user_id)
    return [{**g, "classes": sorted(g["classes"]), "teachers": len(g["teachers"])} for g in gaps.values()]
