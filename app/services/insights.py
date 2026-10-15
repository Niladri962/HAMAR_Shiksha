"""Explainable recommendation engine ("rules-engine-v1").

Each recommendation stores the evidence and source row IDs it was derived
from. Recommendations are suggestions only: they never change a student's
grade or status, never rate teachers, and wording avoids labels ("may benefit
from more practice", not "weak student"). Recommendations expire and are
superseded when newer evidence shows improvement.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AIRecommendation,
    Assessment,
    AssessmentResult,
    ClassSection,
    LearningActivity,
    LearningProgress,
    School,
    StudentEnrollment,
    Subject,
    utcnow,
)
from app.services import analytics

ENGINE = "rules-engine-v1"
PRACTICE_BELOW = 0.6        # topic mastery that triggers a practice suggestion
RESOLVED_AT = 0.75          # mastery at which a pending suggestion is superseded
MIN_ATTEMPTS = 3            # minimum answered questions before any suggestion
CLASS_GAP_BELOW = 0.6       # class-average mastery that triggers a remedial plan
OPEN = ("pending_review", "approved")


# ------------------------------------------------------- learning progress ----

def apply_result(db: Session, result: AssessmentResult) -> None:
    """Fold one result's per-topic breakdown into the student's progress."""
    assessment = result.assessment
    for topic, (correct, total) in (result.topic_breakdown or {}).items():
        _bump_progress(db, result.student_user_id, assessment.subject_id, topic, correct, total)
    db.flush()
    refresh_student_recommendations(db, result.student_user_id)


def apply_exercise(db: Session, student_id: int, activity: LearningActivity, correct: int, total: int) -> None:
    _bump_progress(db, student_id, activity.subject_id, activity.topic, correct, total)
    db.flush()
    refresh_student_recommendations(db, student_id)


def _bump_progress(db: Session, student_id: int, subject_id: int, topic: str, correct: int, total: int) -> None:
    if total <= 0:
        return
    lp = db.scalar(select(LearningProgress).where(
        LearningProgress.student_user_id == student_id, LearningProgress.subject_id == subject_id,
        LearningProgress.topic == topic))
    if lp is None:
        lp = LearningProgress(student_user_id=student_id, subject_id=subject_id, topic=topic,
                              correct=0, attempted=0)
        db.add(lp)
    lp.correct += int(correct)
    lp.attempted += int(total)
    lp.mastery = round(lp.correct / lp.attempted, 4)
    lp.last_activity_at = utcnow()


def _upsert(db: Session, key: str, **fields) -> AIRecommendation:
    """One open recommendation per dedupe key; refresh evidence in place."""
    existing = db.scalars(select(AIRecommendation).where(
        AIRecommendation.target_type == fields["target_type"],
        AIRecommendation.target_id == fields["target_id"],
        AIRecommendation.kind == fields["kind"],
        AIRecommendation.status.in_(OPEN))).all()
    for rec in existing:
        if (rec.evidence or {}).get("key") == key:
            for k, v in fields.items():
                setattr(rec, k, v)
            rec.evidence = {**fields["evidence"], "key": key}
            rec.created_at = utcnow()
            return rec
    rec = AIRecommendation(generated_by=ENGINE, **fields)
    rec.evidence = {**fields["evidence"], "key": key}
    db.add(rec)
    return rec


# ---------------------------------------------------------------- students ----

def refresh_student_recommendations(db: Session, student_id: int) -> list[AIRecommendation]:
    enrollment = db.scalar(select(StudentEnrollment).where(
        StudentEnrollment.student_user_id == student_id, StudentEnrollment.active.is_(True)))
    if enrollment is None:
        return []
    cs = enrollment.class_section
    out = []
    for lp in db.scalars(select(LearningProgress).where(LearningProgress.student_user_id == student_id)):
        key = f"practice:{lp.subject_id}:{lp.topic.lower()}"
        if lp.attempted >= MIN_ATTEMPTS and lp.mastery < PRACTICE_BELOW:
            source_ids = _result_ids_for_topic(db, student_id, lp.subject_id, lp.topic)
            activities = db.scalars(select(LearningActivity.id).where(
                LearningActivity.subject_id == lp.subject_id, LearningActivity.grade == cs.grade,
                LearningActivity.approved.is_(True))
                .where(LearningActivity.topic.ilike(lp.topic))).all()
            out.append(_upsert(
                db, key, target_type="student", target_id=student_id, school_id=cs.school_id,
                district_id=cs.school.district_id, block_id=cs.school.block_id, audience="student",
                kind="practice", title=f"More practice: {lp.topic}",
                summary=(f"You answered {lp.correct} of {lp.attempted} questions on '{lp.topic}' "
                         f"correctly. A little more practice on this topic may help."),
                evidence={"subject_id": lp.subject_id, "subject": lp.subject.name, "topic": lp.topic,
                          "correct": lp.correct, "attempted": lp.attempted, "mastery": lp.mastery,
                          "rule": f"mastery < {PRACTICE_BELOW} after >= {MIN_ATTEMPTS} attempts",
                          "suggested_activity_ids": list(activities)},
                data_sources=[{"table": "learning_progress", "ids": [lp.id]},
                              {"table": "assessment_results", "ids": source_ids}],
            ))
        elif lp.mastery >= RESOLVED_AT:
            for rec in db.scalars(select(AIRecommendation).where(
                    AIRecommendation.target_type == "student", AIRecommendation.target_id == student_id,
                    AIRecommendation.kind == "practice", AIRecommendation.status.in_(OPEN))):
                if (rec.evidence or {}).get("key") == key:
                    rec.status = "superseded"
                    rec.review_note = f"Mastery improved to {lp.mastery:.0%}"
    db.flush()
    return out


def _result_ids_for_topic(db: Session, student_id: int, subject_id: int, topic: str) -> list[int]:
    rows = db.execute(select(AssessmentResult.id, AssessmentResult.topic_breakdown)
                      .join(Assessment, Assessment.id == AssessmentResult.assessment_id)
                      .where(AssessmentResult.student_user_id == student_id,
                             Assessment.subject_id == subject_id)).all()
    return [r.id for r in rows if topic in (r.topic_breakdown or {})]


# ---------------------------------------------------------------- classes ----

def refresh_class_recommendations(db: Session, cs: ClassSection, subject_ids: set[int]) -> list[AIRecommendation]:
    """Topic-level gaps across a class -> remedial plan suggestions for its teachers."""
    student_ids = list(db.scalars(select(StudentEnrollment.student_user_id).where(
        StudentEnrollment.class_section_id == cs.id, StudentEnrollment.active.is_(True))))
    if not student_ids:
        return []
    groups: dict[tuple[int, str], list[LearningProgress]] = defaultdict(list)
    for lp in db.scalars(select(LearningProgress).where(
            LearningProgress.student_user_id.in_(student_ids), LearningProgress.subject_id.in_(subject_ids))):
        groups[(lp.subject_id, lp.topic)].append(lp)

    out = []
    for (subject_id, topic), lps in groups.items():
        assessed = [lp for lp in lps if lp.attempted >= MIN_ATTEMPTS]
        if len(assessed) < 3:
            continue  # too little evidence for a class-level statement
        avg = sum(lp.mastery for lp in assessed) / len(assessed)
        below = [lp for lp in assessed if lp.mastery < PRACTICE_BELOW]
        if avg >= CLASS_GAP_BELOW:
            continue
        subject = db.get(Subject, subject_id)
        out.append(_upsert(
            db, f"gap:{cs.id}:{subject_id}:{topic.lower()}", target_type="class", target_id=cs.id,
            school_id=cs.school_id, district_id=cs.school.district_id, block_id=cs.school.block_id,
            audience="teacher", kind="remedial_plan",
            title=f"{cs.label} · {subject.name}: revisit '{topic}'",
            summary=(f"Class average on '{topic}' is {avg:.0%} across {len(assessed)} assessed students; "
                     f"{len(below)} may benefit from small-group practice. Suggested: a 10-minute "
                     "re-teach with a worked example, then paired practice using the linked exercises, "
                     "and a 3-question check the next week."),
            evidence={"class_id": cs.id, "subject_id": subject_id, "subject": subject.name, "topic": topic,
                      "class_average_mastery": round(avg, 4), "students_assessed": len(assessed),
                      "students_below_threshold": len(below),
                      "student_ids_below_threshold": [lp.student_user_id for lp in below],
                      "rule": f"class mean mastery < {CLASS_GAP_BELOW} (students with >= {MIN_ATTEMPTS} attempts)"},
            data_sources=[{"table": "learning_progress", "ids": [lp.id for lp in assessed]}],
        ))
    db.flush()
    return out


# ---------------------------------------------------------------- schools ----

def refresh_school_interventions(db: Session, schools: list[School]) -> list[AIRecommendation]:
    snaps = analytics.latest_snapshots(db, [s.id for s in schools])
    out = []
    for school in schools:
        snap = snaps.get(school.id)
        status = analytics.data_status(snap)
        flags = analytics.support_flags(snap, status)
        if not flags:
            continue
        reasons = "; ".join(f["reason"] for f in flags)
        actions = []
        if any(f["metric"] == "reporting" for f in flags):
            actions.append("confirm the school's data entry access and follow up on missing reports")
        if any(f["metric"] in ("student_attendance_rate",) for f in flags):
            actions.append("review attendance with the head teacher and SMC; consider community outreach")
        if any(f["metric"] == "teacher_attendance_rate" for f in flags):
            actions.append("check teacher vacancy/deputation status for the school")
        if any(f["type"] == "academic" for f in flags):
            actions.append("plan a cluster resource person (CAC) visit focused on the lowest subjects")
        out.append(_upsert(
            db, f"school:{school.id}", target_type="school", target_id=school.id, school_id=school.id,
            district_id=school.district_id, block_id=school.block_id, audience="admin",
            kind="intervention", title=f"{school.name} ({school.official_code}) may need support",
            summary=f"Signals: {reasons}. Suggested follow-up: " + "; ".join(actions) + ".",
            evidence={"data_status": status, "flags": flags,
                      "snapshot": analytics.snapshot_dict(snap)},
            data_sources=[{"table": "school_performance_snapshots", "ids": [snap.id] if snap else []}],
        ))
    db.flush()
    return out


def expire_old(db: Session, days: int = 60) -> int:
    cutoff = utcnow() - timedelta(days=days)
    n = 0
    for rec in db.scalars(select(AIRecommendation).where(
            AIRecommendation.status == "pending_review", AIRecommendation.created_at < cutoff)):
        rec.status = "expired"
        n += 1
    return n


def rec_dict(rec: AIRecommendation, *, include_student_ids: bool = False) -> dict:
    evidence = dict(rec.evidence or {})
    evidence.pop("key", None)
    if not include_student_ids:
        evidence.pop("student_ids_below_threshold", None)
    return {
        "id": rec.id, "target_type": rec.target_type, "target_id": rec.target_id, "kind": rec.kind,
        "title": rec.title, "summary": rec.summary, "evidence": evidence, "data_sources": rec.data_sources,
        "generated_by": rec.generated_by, "status": rec.status, "created_at": rec.created_at.isoformat(),
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "review_note": rec.review_note, "is_ai_generated": True,
    }
