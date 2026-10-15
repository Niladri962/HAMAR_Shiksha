"""Milestone-based progress grades with corrective actions, and attendance
risk linked to learning.

Everything here is computed from records the platform already holds
(teaching milestones, competencies, attendance, results), so teachers enter
nothing extra. Grades describe the academic *progress of a class or school
against its plan*; they are not a rating of any teacher. Attendance signals
are prompts for a caring follow-up, never labels on a child.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AssessmentResult,
    AttendanceRecord,
    ClassSection,
    LearnerCompetency,
    LearningOutcome,
    School,
    StudentEnrollment,
    Subject,
    TeachingMilestone,
    User,
)
from app.services.planning import LEARNED_AT

# Grade = the weaker of the "taught" band and the "learned" band.
TAUGHT_BANDS = ((0.9, "A"), (0.75, "B"), (0.5, "C"))
LEARNED_BANDS = ((0.7, "A"), (0.5, "B"), (0.3, "C"))
GRADE_LABEL = {"A": ("On track", "समय पर"), "B": ("Slightly behind", "थोड़ा पीछे"),
               "C": ("Behind plan", "योजना से पीछे"), "D": ("Needs support", "सहायता आवश्यक")}
GRADE_DEFINITION = ("Grade = the weaker of two bands, over outcomes whose planned week has ended (learned counts once 2+ taught outcomes are assessed; with "
                    "fewer than 3 outcomes due the grade is marked provisional). Taught (share of outcomes due to date that are marked taught): "
                    "A ≥ 90%, B ≥ 75%, C ≥ 50%, else D. Learned (share of taught & assessed outcomes with class mean "
                    "mastery ≥ 60%): A ≥ 70%, B ≥ 50%, C ≥ 30%, else D. It grades progress against the plan, "
                    "not teachers.")
OVERDUE_GRACE_DAYS = 14
MIN_ASSESSED = 2   # learned band needs at least this many assessed outcomes
MIN_PLANNED = 3    # fewer due outcomes -> grade shown as provisional


def _band(rate: float | None, bands) -> str | None:
    if rate is None:
        return None
    return next((g for cut, g in bands if rate >= cut), "D")


def grade_for(taught_rate: float | None, learned_rate: float | None) -> str | None:
    bands = [b for b in (_band(taught_rate, TAUGHT_BANDS), _band(learned_rate, LEARNED_BANDS)) if b]
    return max(bands) if bands else None


def _mastery_by_class_lo(db: Session, class_ids: list[int], lo_ids: set[int]) -> dict[tuple[int, int], tuple[float, int]]:
    enr = db.execute(select(StudentEnrollment.class_section_id, StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True))).all()
    class_of = {sid: cid for cid, sid in enr}
    acc: dict[tuple[int, int], list[float]] = defaultdict(list)
    sids = list(class_of)
    for i in range(0, len(sids), 900):
        for sid, lo, m in db.execute(select(LearnerCompetency.student_user_id, LearnerCompetency.learning_outcome_id,
                                            LearnerCompetency.mastery).where(
                LearnerCompetency.student_user_id.in_(sids[i:i + 900]),
                LearnerCompetency.learning_outcome_id.in_(lo_ids or [-1]), LearnerCompetency.attempted >= 3)):
            acc[(class_of[sid], lo)].append(m)
    return {k: (sum(v) / len(v), len(v)) for k, v in acc.items()}


def class_subject_progress(db: Session, class_ids: list[int], today: date | None = None,
                           subject_ids: set[int] | None = None) -> list[dict]:
    """One row per class x subject with planned/taught/learned, weeks behind,
    grade and rule-based corrective actions."""
    today = today or date.today()
    q = select(TeachingMilestone, LearningOutcome).join(
        LearningOutcome, LearningOutcome.id == TeachingMilestone.learning_outcome_id).where(
        # Due = its planned week has ended; a teacher is not "behind" on this week's outcome.
        TeachingMilestone.class_section_id.in_(class_ids or [-1]),
        TeachingMilestone.planned_week_start <= today - timedelta(days=7))
    if subject_ids is not None:
        q = q.where(TeachingMilestone.subject_id.in_(subject_ids or [-1]))
    rows = db.execute(q).all()
    mastery = _mastery_by_class_lo(db, class_ids, {lo.id for _, lo in rows})
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for m, lo in rows:
        groups[(m.class_section_id, m.subject_id)].append((m, lo))
    classes = {c.id: c for c in db.scalars(select(ClassSection).where(ClassSection.id.in_(class_ids or [-1])))}
    subjects = {s.id: s for s in db.scalars(select(Subject))}
    out = []
    for (cid, sid), items in groups.items():
        planned = len(items)
        taught = [(m, lo) for m, lo in items if m.status == "taught"]
        overdue = sorted([(m, lo) for m, lo in items if m.status != "taught"
                          and m.planned_week_start < today - timedelta(days=OVERDUE_GRACE_DAYS)],
                         key=lambda x: x[0].planned_week_start)
        assessed = [(m, lo, mastery[(cid, lo.id)]) for m, lo in taught if (cid, lo.id) in mastery]
        not_learned = [(m, lo, mv) for m, lo, mv in assessed if mv[0] < LEARNED_AT]
        taught_rate = len(taught) / planned if planned else None
        learned_rate = (len(assessed) - len(not_learned)) / len(assessed) if assessed else None
        weeks_behind = (today - overdue[0][0].planned_week_start).days // 7 if overdue else 0
        # One or two assessed outcomes make "learned" all-or-nothing; use it only from MIN_ASSESSED.
        grade = grade_for(taught_rate, learned_rate if len(assessed) >= MIN_ASSESSED else None)
        provisional = planned < MIN_PLANNED or 0 < len(assessed) < MIN_ASSESSED
        actions = []
        if overdue:
            actions.append({"kind": "catch_up", "text":
                            f"{len(overdue)} outcome(s) overdue, oldest {weeks_behind} week(s). Teach next: "
                            + "; ".join(lo.code for _, lo in overdue[:3])
                            + ". Use an approved lesson plan or the AI class to cover them; combine with revision periods.",
                            "outcomes": [lo.code for _, lo in overdue[:5]]})
        if not_learned:
            worst = sorted(not_learned, key=lambda x: x[2][0])[:3]
            actions.append({"kind": "reteach", "text":
                            "Taught but not yet learned: " + "; ".join(f"{lo.code} ({round(mv[0] * 100)}%)" for _, lo, mv in worst)
                            + ". Re-teach with a worksheet or remediation plan, then re-check with a short quiz.",
                            "outcomes": [lo.code for _, lo, _ in worst]})
        if taught and not assessed:
            actions.append({"kind": "assess", "text": "Taught outcomes have no assessment evidence yet. "
                                                      "A 5-question quiz from the question bank will show what was learned."})
        cs = classes.get(cid)
        out.append({"class_id": cid, "class": cs.label if cs else str(cid), "grade_level": cs.grade if cs else None,
                    "school_id": cs.school_id if cs else None, "subject_id": sid,
                    "subject": subjects[sid].name, "subject_hi": subjects[sid].name_hi,
                    "planned_due": planned, "taught": len(taught), "assessed": len(assessed),
                    "learned": len(assessed) - len(not_learned), "overdue": len(overdue), "weeks_behind": weeks_behind,
                    "taught_rate": round(taught_rate, 4) if taught_rate is not None else None,
                    "learned_rate": round(learned_rate, 4) if learned_rate is not None else None,
                    "grade": grade, "provisional": provisional,
                    "label": GRADE_LABEL[grade][0] if grade else "No milestones due",
                    "label_hi": GRADE_LABEL[grade][1] if grade else "", "actions": actions})
    return sorted(out, key=lambda r: (r["grade_level"] or 0, r["class"], r["subject"]))


def school_grades(db: Session, schools: list[School], today: date | None = None) -> list[dict]:
    """School-level grade from the pooled class-subject figures."""
    class_rows = db.execute(select(ClassSection.id, ClassSection.school_id).where(
        ClassSection.school_id.in_([s.id for s in schools] or [-1]))).all()
    rows = class_subject_progress(db, [c for c, _ in class_rows], today)
    by_school: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_school[r["school_id"]].append(r)
    out = []
    for s in schools:
        rs = by_school.get(s.id, [])
        planned = sum(r["planned_due"] for r in rs)
        taught = sum(r["taught"] for r in rs)
        assessed = sum(r["assessed"] for r in rs)
        learned = sum(r["learned"] for r in rs)
        tr = taught / planned if planned else None
        lr = learned / assessed if assessed else None
        g = grade_for(tr, lr if assessed >= MIN_ASSESSED else None)
        behind = [r for r in rs if r["grade"] in ("C", "D")]
        action = None
        if behind:
            subj = defaultdict(int)
            for r in behind:
                subj[r["subject"]] += 1
            top = sorted(subj.items(), key=lambda kv: -kv[1])[:2]
            action = (f"{len(behind)} class-subject(s) behind plan, mostly " + ", ".join(k for k, _ in top)
                      + ". Suggested: block-level academic support visit, AI-class cover for overdue outcomes, "
                        "and the subject micro-course for the teachers concerned.")
        out.append({"school_id": s.id, "school": s.name, "official_code": s.official_code,
                    "district_id": s.district_id, "block_id": s.block_id,
                    "planned_due": planned, "taught_rate": round(tr, 4) if tr is not None else None,
                    "learned_rate": round(lr, 4) if lr is not None else None, "grade": g,
                    "provisional": planned < MIN_PLANNED,
                    "label": GRADE_LABEL[g][0] if g else "No milestones due",
                    "class_subjects": len(rs), "behind": len(behind), "action": action})
    return out


# ------------------------------------------------------------ attendance ----

RISK_WINDOW_DAYS = 60
IRREGULAR_BELOW = 0.75
LONG_ABSENCE_RUN = 4          # consecutive recorded school days absent, ending at the latest record
DECLINE_POINTS = 0.15
RISK_DEFINITION = (f"Over the last {RISK_WINDOW_DAYS} days of recorded attendance. Irregular: below "
                   f"{int(IRREGULAR_BELOW * 100)}%. Continuous absence: absent on the last {LONG_ABSENCE_RUN}+ recorded "
                   f"school days. Falling: the last 30 days are {int(DECLINE_POINTS * 100)}+ points below the 30 days "
                   "before. High = continuous absence, or irregular and also falling or below 60%. These are prompts for "
                   "a caring follow-up (call or home visit), not a prediction or a label.")
_PRESENT = ("present", "late")


def _student_attendance(recs: list[tuple[date, str]], today: date) -> dict:
    recs = sorted(recs)
    n = len(recs)
    present = sum(1 for _, s in recs if s in _PRESENT)
    mid = today - timedelta(days=30)
    recent = [s for d, s in recs if d > mid]
    earlier = [s for d, s in recs if d <= mid]
    rate = present / n if n else None
    r_recent = sum(1 for s in recent if s in _PRESENT) / len(recent) if recent else None
    r_earlier = sum(1 for s in earlier if s in _PRESENT) / len(earlier) if earlier else None
    run = 0
    for _, s in reversed(recs):
        if s == "absent":
            run += 1
        else:
            break
    flags = []
    if rate is not None and rate < IRREGULAR_BELOW:
        flags.append("irregular")
    if run >= LONG_ABSENCE_RUN:
        flags.append("continuous_absence")
    if r_recent is not None and r_earlier is not None and len(recent) >= 4 and r_earlier - r_recent >= DECLINE_POINTS:
        flags.append("falling")
    if "continuous_absence" in flags or ("irregular" in flags and ("falling" in flags or (rate or 0) < 0.6)):
        level = "high"
    elif flags:
        level = "watch"
    else:
        level = "none"
    return {"days_recorded": n, "days_present": present, "rate": round(rate, 4) if rate is not None else None,
            "rate_last_30": round(r_recent, 4) if r_recent is not None else None,
            "rate_prev_30": round(r_earlier, 4) if r_earlier is not None else None,
            "absent_run": run, "flags": flags, "level": level,
            "absent_days": [d for d, s in recs if s == "absent"]}


def attendance_risk(db: Session, class_ids: list[int], today: date | None = None, *,
                    with_students: bool = True, min_group: int = 5) -> dict:
    """Per-student attendance signals, each linked to the outcomes taught while
    the child was away and to their recent scores."""
    today = today or date.today()
    since = today - timedelta(days=RISK_WINDOW_DAYS)
    enr = db.execute(select(StudentEnrollment.class_section_id, StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id.in_(class_ids or [-1]), StudentEnrollment.active.is_(True))).all()
    class_of = {sid: cid for cid, sid in enr}
    sids = list(class_of)
    att: dict[int, list] = defaultdict(list)
    scores: dict[int, list[float]] = defaultdict(list)
    for i in range(0, len(sids), 900):
        chunk = sids[i:i + 900]
        for pid, d, s in db.execute(select(AttendanceRecord.person_user_id, AttendanceRecord.date,
                                           AttendanceRecord.status).where(
                AttendanceRecord.person_user_id.in_(chunk), AttendanceRecord.date >= since,
                AttendanceRecord.date <= today)):
            att[pid].append((d, s))
        for sid, sc, mx in db.execute(select(AssessmentResult.student_user_id, AssessmentResult.score,
                                             AssessmentResult.max_score).where(
                AssessmentResult.student_user_id.in_(chunk), AssessmentResult.status == "final",
                AssessmentResult.submitted_at >= since - timedelta(days=30))):
            if mx:
                scores[sid].append(sc / mx)

    stats = {sid: _student_attendance(att.get(sid, []), today) for sid in sids}
    # Learning link at class level: mean score by attendance band.
    bands = (("90%+", 0.9, 1.01), ("75-90%", 0.75, 0.9), ("60-75%", 0.6, 0.75), ("below 60%", 0.0, 0.6))
    band_rows = []
    for name, lo, hi in bands:
        group = [sid for sid in sids if stats[sid]["rate"] is not None and lo <= stats[sid]["rate"] < hi and scores.get(sid)]
        vals = [sum(scores[s]) / len(scores[s]) for s in group]
        band_rows.append({"band": name, "students": len(group),
                          "avg_score": round(sum(vals) / len(vals), 4) if len(vals) >= min_group else None})
    counts = {"high": 0, "watch": 0, "none": 0}
    for st in stats.values():
        counts[st["level"]] += 1
    result = {"window_days": RISK_WINDOW_DAYS, "students": len(sids), "counts": counts, "by_band": band_rows,
              "definition": RISK_DEFINITION,
              "band_note": f"Average score by attendance band (groups under {min_group} students hidden). An association, "
                           "not proof that absence caused lower scores."}
    if not with_students:
        return result

    flagged = [sid for sid in sids if stats[sid]["level"] != "none"]
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_(flagged or [-1]))).all())
    pids = dict(db.execute(select(User.id, User.public_id).where(User.id.in_(flagged or [-1]))).all())
    taught = db.execute(select(TeachingMilestone.class_section_id, TeachingMilestone.taught_at, LearningOutcome.id,
                               LearningOutcome.code, LearningOutcome.description).join(
        LearningOutcome, LearningOutcome.id == TeachingMilestone.learning_outcome_id).where(
        TeachingMilestone.class_section_id.in_(class_ids or [-1]), TeachingMilestone.status == "taught",
        TeachingMilestone.taught_at >= since)).all()
    comp = {(sid, lo): m for sid, lo, m in db.execute(select(
        LearnerCompetency.student_user_id, LearnerCompetency.learning_outcome_id, LearnerCompetency.mastery).where(
        LearnerCompetency.student_user_id.in_(flagged or [-1])))}
    rows = []
    for sid in flagged:
        st = stats[sid]
        recs_by_week: dict[date, list[str]] = defaultdict(list)
        for d, s in att.get(sid, []):
            recs_by_week[d - timedelta(days=d.weekday())].append(s)
        missed = []
        for cid, at, lo_id, code, desc in taught:
            if cid != class_of[sid] or at is None:
                continue
            wk = recs_by_week.get(at.date() - timedelta(days=at.date().weekday()), [])
            if wk and sum(1 for s in wk if s == "absent") * 2 > len(wk):
                m = comp.get((sid, lo_id))
                missed.append({"code": code, "outcome": desc,
                               "mastery": round(m, 2) if m is not None else None,
                               "needs_catch_up": m is None or m < LEARNED_AT})
        sc = scores.get(sid)
        avg = sum(sc) / len(sc) if sc else None
        action = []
        if "continuous_absence" in st["flags"]:
            action.append(f"Absent on the last {st['absent_run']} school days: call the guardian today; "
                          "arrange a home visit with the head teacher / SMC if not reachable.")
        elif st["level"] == "high":
            action.append("Talk with the child and guardian this week about what is keeping them away.")
        else:
            action.append("Keep an eye on attendance; a word of encouragement helps.")
        if any(m["needs_catch_up"] for m in missed):
            action.append("Catch-up: " + ", ".join(m["code"] for m in missed if m["needs_catch_up"])[:200]
                          + " were taught in weeks they were mostly absent. Assign the matching practice or pair "
                            "them with a study buddy.")
        if avg is not None and avg < 0.4:
            action.append("Recent scores are low; add to the remedial group.")
        rows.append({"public_id": pids.get(sid), "name": names.get(sid, ""), "class_id": class_of[sid],
                     **{k: v for k, v in st.items() if k != "absent_days"},
                     "last_absent": st["absent_days"][-1].isoformat() if st["absent_days"] else None,
                     "avg_score": round(avg, 4) if avg is not None else None,
                     "missed_outcomes": missed[:8], "actions": action})
    rows.sort(key=lambda r: (r["level"] != "high", r["rate"] if r["rate"] is not None else 1))
    result["flagged"] = rows
    return result
