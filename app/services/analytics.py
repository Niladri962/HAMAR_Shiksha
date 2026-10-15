"""Aggregation layer for dashboards and reports.

Raw records (attendance, results) are rolled up into monthly
`school_performance_snapshots`. Admin dashboards read only these aggregates;
outcome metrics use only schools whose data is *current*, and the response
always says how many schools were current, stale or missing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Assessment,
    AssessmentResult,
    AttendanceRecord,
    ClassSection,
    LearningProgress,
    School,
    SchoolPerformanceSnapshot,
    StudentEnrollment,
    Subject,
    TeacherProfile,
    utcnow,
)

MIN_GROUP = 5  # suppress class-level aggregates for smaller groups (re-identification risk)

THRESHOLDS = {
    "student_attendance_rate": (0.75, "Student attendance below 75%"),
    "teacher_attendance_rate": (0.85, "Teacher attendance below 85%"),
    "assessment_participation": (0.60, "Assessment participation below 60%"),
    "avg_score_pct": (0.45, "Average assessment score below 45%"),
}


# ---------------------------------------------------------------- periods ----

def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def period_bounds(period: str) -> tuple[date, date]:
    y, m = map(int, period.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def recent_periods(n: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


# -------------------------------------------------------------- snapshots ----

def _rate(present: int, total: int) -> float | None:
    return round(present / total, 4) if total else None


def compute_school_snapshot(db: Session, school: School, period: str) -> SchoolPerformanceSnapshot | None:
    start, end = period_bounds(period)
    start_dt, end_dt = datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time())
    class_rows = db.execute(select(ClassSection.id, ClassSection.grade)
                            .where(ClassSection.school_id == school.id)).all()
    class_ids = [c.id for c in class_rows]
    grade_of = {c.id: c.grade for c in class_rows}

    student_count = db.scalar(select(func.count(StudentEnrollment.id)).where(
        StudentEnrollment.class_section_id.in_(class_ids), StudentEnrollment.active.is_(True))) or 0
    teacher_count = db.scalar(select(func.count(TeacherProfile.user_id)).where(
        TeacherProfile.school_id == school.id, TeacherProfile.verification_status == "verified")) or 0

    att = defaultdict(lambda: [0, 0])
    last_dates: list[date] = []
    for ptype, status, n, last in db.execute(
        select(AttendanceRecord.person_type, AttendanceRecord.status, func.count(), func.max(AttendanceRecord.date))
        .where(AttendanceRecord.school_id == school.id, AttendanceRecord.date >= start,
               AttendanceRecord.date < end)
        .group_by(AttendanceRecord.person_type, AttendanceRecord.status)
    ):
        att[ptype][1] += n
        if status in ("present", "late"):
            att[ptype][0] += n
        last_dates.append(last)

    results = db.execute(
        select(AssessmentResult.student_user_id, AssessmentResult.score, AssessmentResult.max_score,
               AssessmentResult.submitted_at, Assessment.class_section_id, Subject.code)
        .join(Assessment, Assessment.id == AssessmentResult.assessment_id)
        .join(Subject, Subject.id == Assessment.subject_id)
        .where(Assessment.class_section_id.in_(class_ids), AssessmentResult.submitted_at >= start_dt,
               AssessmentResult.submitted_at < end_dt)).all()

    if not last_dates and not results:
        return None  # no source data at all for this period -> "missing"

    participants = {r.student_user_id for r in results}
    pcts = [r.score / r.max_score for r in results if r.max_score]
    by_subject: dict[str, list[float]] = defaultdict(list)
    by_grade: dict[str, list[float]] = defaultdict(list)
    for r in results:
        if r.max_score:
            by_subject[r.code].append(r.score / r.max_score)
            by_grade[str(grade_of[r.class_section_id])].append(r.score / r.max_score)
    last_dates += [r.submitted_at.date() for r in results]

    snap = db.scalar(select(SchoolPerformanceSnapshot).where(
        SchoolPerformanceSnapshot.school_id == school.id, SchoolPerformanceSnapshot.period == period))
    if snap is None:
        snap = SchoolPerformanceSnapshot(school_id=school.id, period=period, as_of=start)
        db.add(snap)
    snap.as_of = max(last_dates)
    snap.student_count = student_count
    snap.teacher_count = teacher_count
    snap.student_attendance_rate = _rate(*att["student"])
    snap.teacher_attendance_rate = _rate(*att["teacher"])
    snap.assessment_participation = (round(min(1.0, len(participants) / student_count), 4)
                                     if student_count and results else None)
    snap.avg_score_pct = round(sum(pcts) / len(pcts), 4) if pcts else None
    snap.subject_scores = {k: round(sum(v) / len(v), 4) for k, v in by_subject.items()}
    snap.grade_scores = {k: round(sum(v) / len(v), 4) for k, v in by_grade.items()}
    snap.is_estimate = False
    snap.source = "platform-records"
    snap.computed_at = utcnow()
    return snap


def recompute_snapshots(db: Session, periods: list[str] | None = None,
                        school_ids: list[int] | None = None) -> int:
    periods = periods or recent_periods(1)
    stmt = select(School).where(School.status == "active")
    if school_ids:
        stmt = stmt.where(School.id.in_(school_ids))
    n = 0
    for school in db.scalars(stmt):
        for p in periods:
            if compute_school_snapshot(db, school, p) is not None:
                n += 1
    db.flush()
    return n


# ------------------------------------------------------------ data status ----

def data_status(snap: SchoolPerformanceSnapshot | None, today: date | None = None) -> str:
    """current | stale | missing | estimated"""
    if snap is None:
        return "missing"
    if snap.is_estimate:
        return "estimated"
    today = today or date.today()
    if snap.as_of >= today - timedelta(days=get_settings().data_current_days):
        return "current"
    return "stale"


def latest_snapshots(db: Session, school_ids: list[int]) -> dict[int, SchoolPerformanceSnapshot]:
    if not school_ids:
        return {}
    latest = (select(SchoolPerformanceSnapshot.school_id, func.max(SchoolPerformanceSnapshot.period).label("p"))
              .where(SchoolPerformanceSnapshot.school_id.in_(school_ids))
              .group_by(SchoolPerformanceSnapshot.school_id).subquery())
    rows = db.scalars(select(SchoolPerformanceSnapshot).join(
        latest, and_(latest.c.school_id == SchoolPerformanceSnapshot.school_id,
                     latest.c.p == SchoolPerformanceSnapshot.period)))
    return {s.school_id: s for s in rows}


def support_flags(snap: SchoolPerformanceSnapshot | None, status: str) -> list[dict]:
    flags = []
    if status in ("missing", "stale"):
        flags.append({"type": "operational", "metric": "reporting",
                      "reason": "No data reported" if status == "missing" else "Data not updated recently"})
    if snap is not None and status == "current":
        for metric, (limit, reason) in THRESHOLDS.items():
            value = getattr(snap, metric)
            if value is not None and value < limit:
                flags.append({"type": "academic" if metric in ("avg_score_pct", "assessment_participation")
                              else "operational", "metric": metric, "value": value,
                              "threshold": limit, "reason": reason})
    return flags


def snapshot_dict(snap: SchoolPerformanceSnapshot | None) -> dict | None:
    if snap is None:
        return None
    return {
        "id": snap.id, "period": snap.period, "as_of": snap.as_of.isoformat(),
        "student_count": snap.student_count, "teacher_count": snap.teacher_count,
        "student_attendance_rate": snap.student_attendance_rate,
        "teacher_attendance_rate": snap.teacher_attendance_rate,
        "assessment_participation": snap.assessment_participation,
        "avg_score_pct": snap.avg_score_pct, "subject_scores": snap.subject_scores,
        "grade_scores": snap.grade_scores, "is_estimate": snap.is_estimate, "source": snap.source,
    }


def _weighted(pairs: list[tuple[float | None, int]]) -> float | None:
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    total = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / total, 4) if total else None


def aggregate(schools: list[School], snaps: dict[int, SchoolPerformanceSnapshot],
              today: date | None = None) -> dict:
    """Roll a set of schools up into one metrics block (current data only)."""
    status_counts = {"current": 0, "stale": 0, "missing": 0, "estimated": 0}
    current = []
    for s in schools:
        st = data_status(snaps.get(s.id), today)
        status_counts[st] += 1
        if st == "current":
            current.append(snaps[s.id])
    subj: dict[str, list[tuple[float, int]]] = defaultdict(list)
    grade: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for sn in current:
        for k, v in (sn.subject_scores or {}).items():
            subj[k].append((v, sn.student_count))
        for k, v in (sn.grade_scores or {}).items():
            grade[k].append((v, sn.student_count))
    ids = {s.id for s in schools}
    in_scope = [sn for sn in snaps.values() if sn.school_id in ids]
    return {
        "schools": len(schools),
        "data_status": status_counts,
        "schools_reporting_current": status_counts["current"],
        # Counts below come from all latest snapshots (stale ones included) and are labelled so.
        "students_on_record": sum(sn.student_count for sn in in_scope),
        "teachers_on_record": sum(sn.teacher_count for sn in in_scope),
        "metrics_basis": f"{len(current)} of {len(schools)} schools with current data",
        "student_attendance_rate": _weighted([(sn.student_attendance_rate, sn.student_count) for sn in current]),
        "teacher_attendance_rate": _weighted([(sn.teacher_attendance_rate, sn.teacher_count) for sn in current]),
        "assessment_participation": _weighted([(sn.assessment_participation, sn.student_count) for sn in current]),
        "avg_score_pct": _weighted([(sn.avg_score_pct, sn.student_count) for sn in current]),
        "subject_scores": {k: _weighted(v) for k, v in sorted(subj.items())},
        "grade_scores": {k: _weighted(v) for k, v in sorted(grade.items(), key=lambda kv: int(kv[0]))},
    }


def trend(db: Session, school_ids: list[int], months: int = 6) -> list[dict]:
    periods = recent_periods(months)
    if not school_ids:
        return [{"period": p, "schools_reporting": 0} for p in periods]
    rows = db.scalars(select(SchoolPerformanceSnapshot).where(
        SchoolPerformanceSnapshot.school_id.in_(school_ids),
        SchoolPerformanceSnapshot.period.in_(periods),
        SchoolPerformanceSnapshot.is_estimate.is_(False))).all()
    by_p: dict[str, list] = defaultdict(list)
    for r in rows:
        by_p[r.period].append(r)
    out = []
    for p in periods:
        sn = by_p.get(p, [])
        out.append({
            "period": p, "schools_reporting": len(sn),
            "student_attendance_rate": _weighted([(s.student_attendance_rate, s.student_count) for s in sn]),
            "teacher_attendance_rate": _weighted([(s.teacher_attendance_rate, s.teacher_count) for s in sn]),
            "avg_score_pct": _weighted([(s.avg_score_pct, s.student_count) for s in sn]),
            "assessment_participation": _weighted([(s.assessment_participation, s.student_count) for s in sn]),
        })
    return out


# ------------------------------------------------------------- class level ----

def class_summary(db: Session, cs: ClassSection, *, include_students: bool,
                  days: int = 30) -> dict:
    """Subject- and topic-level summary for one class section.

    include_students=False (admin views) returns aggregates only and suppresses
    groups under MIN_GROUP. include_students=True is for the class's own teachers.
    """
    enrolled = db.scalars(select(StudentEnrollment).where(
        StudentEnrollment.class_section_id == cs.id, StudentEnrollment.active.is_(True))).all()
    student_ids = [e.student_user_id for e in enrolled]
    n = len(student_ids)
    suppressed = not include_students and n < MIN_GROUP

    since = date.today() - timedelta(days=days)
    att_total = att_present = 0
    if student_ids:
        for status, cnt in db.execute(select(AttendanceRecord.status, func.count()).where(
                AttendanceRecord.class_section_id == cs.id, AttendanceRecord.person_type == "student",
                AttendanceRecord.date >= since).group_by(AttendanceRecord.status)):
            att_total += cnt
            att_present += cnt if status in ("present", "late") else 0

    subjects = []
    res_rows = db.execute(
        select(Subject.id, Subject.code, Subject.name, AssessmentResult.student_user_id,
               AssessmentResult.score, AssessmentResult.max_score)
        .join(Assessment, Assessment.subject_id == Subject.id)
        .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.id)
        .where(Assessment.class_section_id == cs.id)).all()
    by_subj: dict[int, dict] = {}
    for r in res_rows:
        d = by_subj.setdefault(r.id, {"subject_id": r.id, "code": r.code, "name": r.name,
                                      "pcts": [], "students": set()})
        if r.max_score:
            d["pcts"].append(r.score / r.max_score)
        d["students"].add(r.student_user_id)

    topic_rows = db.execute(
        select(LearningProgress.subject_id, LearningProgress.topic,
               func.avg(LearningProgress.mastery), func.count(LearningProgress.id),
               func.sum(LearningProgress.attempted))
        .where(LearningProgress.student_user_id.in_(student_ids or [-1]))
        .group_by(LearningProgress.subject_id, LearningProgress.topic)).all()
    topics_by_subj: dict[int, list] = defaultdict(list)
    for subj_id, topic, avg_m, cnt, attempts in topic_rows:
        if not include_students and cnt < MIN_GROUP:
            continue
        topics_by_subj[subj_id].append({"topic": topic, "avg_mastery": round(avg_m, 4),
                                        "students": cnt, "attempts": int(attempts or 0)})

    for sid, d in by_subj.items():
        subjects.append({
            "subject_id": sid, "code": d["code"], "name": d["name"],
            "avg_score_pct": None if suppressed or not d["pcts"] else round(sum(d["pcts"]) / len(d["pcts"]), 4),
            "participation": None if suppressed or not n else round(len(d["students"]) / n, 4),
            "topics": [] if suppressed else sorted(topics_by_subj.get(sid, []), key=lambda t: t["avg_mastery"]),
        })
    return {
        "class_id": cs.id, "label": cs.label, "grade": cs.grade, "section": cs.section,
        "academic_year": cs.academic_year, "students": n,
        "suppressed": suppressed,
        "suppression_note": f"Values hidden: fewer than {MIN_GROUP} students" if suppressed else None,
        "attendance_rate_30d": None if suppressed else _rate(att_present, att_total),
        "subjects": sorted(subjects, key=lambda s: s["code"]),
    }
