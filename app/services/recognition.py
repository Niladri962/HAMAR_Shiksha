"""Motivation and recognition for students and teachers.

Badges are computed from the learning record each time they are shown, so
nothing extra is entered and nothing can drift. Most badges reward
*improvement, effort and regularity* rather than absolute marks, so a child
who started low can earn as many as a topper. Appreciations are short notes
from a person (teacher -> student, head teacher / administrator -> teacher).
A certificate is a printable view of an earned badge.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Appreciation,
    AssessmentResult,
    Assessment,
    AttendanceRecord,
    DigitalUsage,
    DoubtReply,
    LearnerCompetency,
    LearnerEvent,
    RevisionItem,
    TeacherClassAssignment,
    TrainingCompletion,
    User,
)

STUDENT_CATEGORIES = {"effort": ("Great effort", "बढ़िया मेहनत"), "improvement": ("Big improvement", "शानदार सुधार"),
                      "helping": ("Helping others", "दूसरों की मदद"), "creativity": ("Creative work", "रचनात्मक काम"),
                      "regularity": ("Regular and punctual", "नियमित और समय पर")}
TEACHER_CATEGORIES = {"milestones": ("Milestones on track", "मील के पत्थर समय पर"),
                      "innovation": ("Classroom innovation", "कक्षा में नवाचार"),
                      "improvement": ("Students improving", "विद्यार्थियों में सुधार"),
                      "mentoring": ("Supporting colleagues", "सहकर्मियों का सहयोग"),
                      "regularity": ("Regular and dedicated", "नियमित और समर्पित")}


def _badge(key, title, title_hi, icon, current, target, why, kind="effort") -> dict:
    earned = current is not None and current >= target
    return {"key": key, "title": title, "title_hi": title_hi, "icon": icon, "kind": kind, "earned": earned,
            "current": round(current, 2) if isinstance(current, float) else current, "target": target, "why": why}


def _attendance(db: Session, uid: int, start: date, end: date) -> float | None:
    rows = db.scalars(select(AttendanceRecord.status).where(AttendanceRecord.person_user_id == uid,
                                                            AttendanceRecord.date > start,
                                                            AttendanceRecord.date <= end)).all()
    return sum(1 for s in rows if s in ("present", "late")) / len(rows) if len(rows) >= 6 else None


def score_change(db: Session, student_id: int, today: date) -> tuple[float | None, int]:
    """Points gained between the earlier and the later half of the last 120
    days of results (needs at least 2 results in each half)."""
    since = datetime.combine(today - timedelta(days=120), datetime.min.time())
    rows = db.execute(select(AssessmentResult.submitted_at, AssessmentResult.score, AssessmentResult.max_score).where(
        AssessmentResult.student_user_id == student_id, AssessmentResult.status == "final",
        AssessmentResult.submitted_at >= since).order_by(AssessmentResult.submitted_at)).all()
    vals = [s / m for _, s, m in rows if m]
    if len(vals) < 4:
        return None, len(vals)
    half = len(vals) // 2
    a, b = vals[:half], vals[half:]
    return round((sum(b) / len(b) - sum(a) / len(a)) * 100, 1), len(vals)


def student_badges(db: Session, student_id: int, today: date | None = None) -> list[dict]:
    from app.services import studenthelp

    today = today or date.today()
    gain, n_results = score_change(db, student_id, today)
    att_now = _attendance(db, student_id, today - timedelta(days=30), today)
    att_before = _attendance(db, student_id, today - timedelta(days=60), today - timedelta(days=30))
    att_gain = round((att_now - att_before) * 100, 1) if att_now is not None and att_before is not None else None
    streak = studenthelp.level_and_streak(db, student_id, today)["streak_days"]
    mastered = db.scalar(select(func.count(RevisionItem.id)).where(RevisionItem.student_user_id == student_id,
                                                                   RevisionItem.mastered.is_(True))) or 0
    helped = db.scalar(select(func.count(DoubtReply.id)).where(DoubtReply.author_user_id == student_id,
                                                               DoubtReply.accepted.is_(True),
                                                               DoubtReply.hidden.is_(False))) or 0
    achieved = db.scalar(select(func.count(LearnerCompetency.id)).where(
        LearnerCompetency.student_user_id == student_id, LearnerCompetency.status == "achieved")) or 0
    chapters = db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.student_user_id == student_id,
                                                                   LearnerEvent.event_type == "chapter_read")) or 0
    practice = db.scalar(select(func.count(LearnerEvent.id)).where(
        LearnerEvent.student_user_id == student_id,
        LearnerEvent.event_type.in_(("activity_completion", "assessment_result")),
        LearnerEvent.occurred_at >= datetime.combine(today - timedelta(days=30), datetime.min.time()))) or 0
    return [
        _badge("rising_star", "Rising star", "उभरता सितारा", "📈", gain, 10,
               (f"Average score up {gain} points (earlier vs recent results)" if gain >= 0
                else f"Recent average {abs(gain)} points lower; raise it by 10 points to earn this") if gain is not None
               else f"Needs 4 results in the last 120 days ({n_results} so far)", "improvement"),
        _badge("attendance_up", "Coming back strong", "नियमितता में सुधार", "🔼", att_gain, 10,
               (f"Attendance up {att_gain} points this month" if att_gain >= 0
                else f"Attendance {abs(att_gain)} points lower this month; come back strong!") if att_gain is not None
               else "Needs two months of attendance", "improvement"),
        _badge("regular", "Regular learner", "नियमित विद्यार्थी", "📅", round(att_now * 100) if att_now is not None else None,
               90, f"Attendance {round(att_now * 100)}% in the last 30 days" if att_now is not None else "No attendance yet",
               "regularity"),
        _badge("streak7", "7-day streak", "7 दिन लगातार", "🔥", streak, 7, f"{streak} day(s) of learning in a row"),
        _badge("practice20", "Practice hero", "अभ्यास वीर", "✍️", practice, 20, f"{practice} quizzes/practice sets in 30 days"),
        _badge("reviser", "Revision master", "दोहराई में माहिर", "🔁", mastered, 5, f"{mastered} past mistakes now mastered"),
        _badge("reader", "Textbook explorer", "पाठ्यपुस्तक खोजी", "📖", chapters, 5, f"{chapters} textbook sections read"),
        _badge("helper", "Helping hand", "मददगार", "🤝", helped, 3, f"{helped} answer{'' if helped == 1 else 's'} marked helpful by classmates or teacher",
               "helping"),
        _badge("outcomes", "Outcome achiever", "लक्ष्य प्राप्तकर्ता", "🎯", achieved, 5, f"{achieved} learning outcomes achieved",
               "mastery"),
    ]


# Weekly challenge: the same for the whole class in a week, rotating, so
# classmates can cheer each other on. Progress comes from the learner record.
CHALLENGES = [
    ("practice", "Answer 3 practice sets this week", "इस सप्ताह 3 अभ्यास सेट हल करें", ("activity_completion",), 3),
    ("revision", "Review 5 revision cards this week", "इस सप्ताह 5 दोहराई कार्ड देखें", ("revision_review",), 5),
    ("reading", "Read 3 textbook sections this week", "इस सप्ताह पाठ्यपुस्तक के 3 भाग पढ़ें", ("chapter_read",), 3),
    ("helping", "Help a classmate on the class board", "कक्षा बोर्ड पर किसी सहपाठी की मदद करें", ("peer_help",), 1),
]


def weekly_challenge(db: Session, student_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    key, title, title_hi, types, target = CHALLENGES[monday.isocalendar()[1] % len(CHALLENGES)]
    done = db.scalar(select(func.count(LearnerEvent.id)).where(
        LearnerEvent.student_user_id == student_id, LearnerEvent.event_type.in_(types),
        LearnerEvent.occurred_at >= datetime.combine(monday, datetime.min.time()))) or 0
    return {"key": key, "title": title, "title_hi": title_hi, "target": target, "done": min(done, target),
            "complete": done >= target, "ends": (monday + timedelta(days=6)).isoformat()}


def teacher_badges(db: Session, teacher_id: int, today: date | None = None) -> list[dict]:
    from app.services import monitoring

    today = today or date.today()
    assigns = db.scalars(select(TeacherClassAssignment).where(TeacherClassAssignment.teacher_user_id == teacher_id,
                                                              TeacherClassAssignment.active.is_(True))).all()
    class_ids = list({a.class_section_id for a in assigns})
    progress = [r for r in monitoring.class_subject_progress(db, class_ids, today, {a.subject_id for a in assigns})
                if (r["class_id"], r["subject_id"]) in {(a.class_section_id, a.subject_id) for a in assigns}]
    planned = sum(r["planned_due"] for r in progress)
    taught = sum(r["taught"] for r in progress)
    on_track = round(taught / planned * 100) if planned else None
    gains = []
    for cid in class_ids:
        rows = db.execute(select(AssessmentResult.student_user_id, AssessmentResult.submitted_at, AssessmentResult.score,
                                 AssessmentResult.max_score).join(Assessment).where(
            Assessment.class_section_id == cid, Assessment.subject_id.in_([a.subject_id for a in assigns
                                                                            if a.class_section_id == cid]),
            AssessmentResult.status == "final",
            AssessmentResult.submitted_at >= datetime.combine(today - timedelta(days=120), datetime.min.time()))
            .order_by(AssessmentResult.submitted_at)).all()
        vals = [s / m for _, _, s, m in rows if m]
        if len(vals) >= 20:
            half = len(vals) // 2
            gains.append((sum(vals[half:]) / (len(vals) - half) - sum(vals[:half]) / half) * 100)
    gain = round(max(gains), 1) if gains else None
    courses = db.scalar(select(func.count(TrainingCompletion.id)).where(
        TrainingCompletion.teacher_user_id == teacher_id)) or 0
    digital = db.scalar(select(func.count(DigitalUsage.id)).where(
        DigitalUsage.teacher_user_id == teacher_id, DigitalUsage.used_on > today - timedelta(weeks=4))) or 0
    att = _attendance(db, teacher_id, today - timedelta(days=30), today)
    answers = db.scalar(select(func.count(DoubtReply.id)).where(DoubtReply.author_user_id == teacher_id)) or 0
    return [
        _badge("on_track", "Milestones on track", "मील के पत्थर समय पर", "🗓️", on_track, 90,
               f"{taught} of {planned} outcomes due so far are taught" if planned else "No milestones due yet", "milestones"),
        _badge("class_gain", "Learning gains", "सीखने में बढ़त", "📈", gain, 5,
               f"A class's average score rose {gain} points (earlier vs recent results)" if gain is not None
               else "Needs 20+ recent results in one class", "improvement"),
        _badge("learner", "Lifelong learner", "आजीवन सीखने वाले", "🎓", courses, 2, f"{courses} micro-course(s) completed"),
        _badge("digital", "Digital champion", "डिजिटल चैंपियन", "💻", digital, 8, f"{digital} digital-resource sessions in 4 weeks",
               "innovation"),
        _badge("regular", "Always there", "सदैव उपस्थित", "📅", round(att * 100) if att is not None else None, 95,
               f"Attendance {round(att * 100)}% in 30 days" if att is not None else "No attendance yet", "regularity"),
        _badge("doubt_solver", "Doubt solver", "शंका समाधानकर्ता", "💬", answers, 5, f"{answers} student doubts answered",
               "helping"),
    ]


def appreciation_dict(db: Session, a: Appreciation, *, show_giver: bool = True) -> dict:
    # Teacher -> student notes use the student categories; everything else is to a teacher.
    cats = STUDENT_CATEGORIES if a.giver_role == "teacher" else TEACHER_CATEGORIES
    giver = db.get(User, a.giver_user_id) if show_giver else None
    return {"id": a.id, "category": a.category, "title": cats.get(a.category, (a.category, a.category))[0],
            "title_hi": cats.get(a.category, (a.category, a.category))[1], "message": a.message,
            "from": giver.full_name if giver else None, "from_role": a.giver_role,
            "at": a.created_at.isoformat() + "Z", "is_demo": a.is_demo}


def appreciations_for(db: Session, user_id: int, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(Appreciation).where(Appreciation.recipient_user_id == user_id)
                      .order_by(Appreciation.created_at.desc()).limit(limit)).all()
    return [appreciation_dict(db, a) for a in rows]


def improvers(db: Session, student_ids: list[int], today: date | None = None, limit: int = 5) -> list[tuple[int, float]]:
    """Students with the largest score gains (for the teacher's 'appreciate' prompts)."""
    today = today or date.today()
    out = []
    for sid in student_ids:
        g, _ = score_change(db, sid, today)
        if g is not None and g >= 5:
            out.append((sid, g))
    return sorted(out, key=lambda x: -x[1])[:limit]


def school_improvement(db: Session, school_ids: list[int]) -> list[dict]:
    """Change in average score between the earliest and latest monthly snapshot."""
    from app.models import SchoolPerformanceSnapshot

    by_school: dict[int, list] = defaultdict(list)
    for sid, period, score in db.execute(select(SchoolPerformanceSnapshot.school_id, SchoolPerformanceSnapshot.period,
                                                SchoolPerformanceSnapshot.avg_score_pct).where(
            SchoolPerformanceSnapshot.school_id.in_(school_ids or [-1]))):
        if score is not None:
            by_school[sid].append((period, score))
    out = []
    for sid, pts in by_school.items():
        if len(pts) < 3:
            continue
        pts.sort()
        out.append({"school_id": sid, "from_period": pts[0][0], "to_period": pts[-1][0],
                    "change_points": round((pts[-1][1] - pts[0][1]) * 100, 1)})
    return out
