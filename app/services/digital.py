"""Use of existing digital infrastructure (ICT labs, smart classes, digital
libraries, language labs, tablet sets).

Usage is recorded with the least possible effort: one tap when a milestone is
marked taught, an automatic entry when an AI class runs on a smart class, or a
short form. From those records the platform derives utilisation against the
school's own weekly target, alignment with learning outcomes, utilisation gaps
and an (associational) comparison with learning results.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DIGITAL_KINDS,
    AssessmentResult,
    Assessment,
    ClassSection,
    DigitalResource,
    DigitalUsage,
    School,
    Subject,
)

KIND_LABEL = {"ict_lab": ("ICT lab", "आईसीटी लैब"), "smart_class": ("Smart class", "स्मार्ट क्लास"),
              "digital_library": ("Digital library", "डिजिटल लाइब्रेरी"),
              "language_lab": ("Language lab", "भाषा प्रयोगशाला"), "tablets": ("Tablet set", "टैबलेट सेट")}
WINDOW_WEEKS = 4
UNDER_USED = 0.5
ACTIVE_CLASS_SESSIONS = 4   # sessions in the window for a class to count as a regular digital user
DEFINITION = (f"Last {WINDOW_WEEKS} weeks. Utilisation = sessions recorded ÷ the school's weekly target × "
              f"{WINDOW_WEEKS}. Gap = not working, unused, or below {int(UNDER_USED * 100)}% of target. Aligned = "
              "session linked to a curriculum learning outcome.")


def resource_dict(r: DigitalResource) -> dict:
    return {"id": r.id, "school_id": r.school_id, "kind": r.kind, "kind_label": KIND_LABEL[r.kind][0],
            "kind_label_hi": KIND_LABEL[r.kind][1], "label": r.label, "status": r.status, "devices": r.devices,
            "target_sessions_per_week": r.target_sessions_per_week, "installed_year": r.installed_year,
            "status_note": r.status_note, "is_demo": r.is_demo}


def log_usage(db: Session, *, resource: DigitalResource, class_section: ClassSection, teacher_id: int | None,
              subject_id: int | None, learning_outcome_id: int | None = None, minutes: int = 35,
              activity: str = "", used_on: date | None = None, source: str = "teacher") -> DigitalUsage:
    if resource.school_id != class_section.school_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That resource belongs to another school")
    if resource.status != "working":
        raise HTTPException(status.HTTP_409_CONFLICT, "This resource is marked not working. Update its status first.")
    u = DigitalUsage(resource_id=resource.id, school_id=resource.school_id, class_section_id=class_section.id,
                     subject_id=subject_id, learning_outcome_id=learning_outcome_id, teacher_user_id=teacher_id,
                     used_on=used_on or date.today(), minutes=minutes, activity=activity[:200], source=source)
    db.add(u)
    db.flush()
    return u


def utilisation(db: Session, school_ids: list[int], today: date | None = None) -> dict:
    today = today or date.today()
    since = today - timedelta(weeks=WINDOW_WEEKS)
    resources = list(db.scalars(select(DigitalResource).where(DigitalResource.school_id.in_(school_ids or [-1]))))
    usage = db.execute(select(DigitalUsage.resource_id, DigitalUsage.class_section_id, DigitalUsage.subject_id,
                              DigitalUsage.learning_outcome_id, DigitalUsage.minutes).where(
        DigitalUsage.school_id.in_(school_ids or [-1]), DigitalUsage.used_on > since,
        DigitalUsage.used_on <= today)).all()
    per_res: dict[int, dict] = defaultdict(lambda: {"sessions": 0, "minutes": 0, "aligned": 0, "classes": set()})
    per_class: dict[int, int] = defaultdict(int)
    per_subject: dict[int, int] = defaultdict(int)
    for rid, cid, sid, lo, mins in usage:
        a = per_res[rid]
        a["sessions"] += 1
        a["minutes"] += mins
        a["aligned"] += 1 if lo else 0
        a["classes"].add(cid)
        per_class[cid] += 1
        if sid:
            per_subject[sid] += 1
    schools = {s.id: s for s in db.scalars(select(School).where(School.id.in_(school_ids or [-1])))}
    rows, gaps = [], []
    by_kind: dict[str, dict] = {k: {"kind": k, "label": KIND_LABEL[k][0], "label_hi": KIND_LABEL[k][1], "resources": 0,
                                    "working": 0, "sessions": 0, "target": 0, "schools": set()} for k in DIGITAL_KINDS}
    for r in resources:
        a = per_res.get(r.id, {"sessions": 0, "minutes": 0, "aligned": 0, "classes": set()})
        target = r.target_sessions_per_week * WINDOW_WEEKS
        util = a["sessions"] / target if target else None
        gap = None
        if r.status != "working":
            gap = "not_working"
        elif a["sessions"] == 0:
            gap = "unused"
        elif util is not None and util < UNDER_USED:
            gap = "under_used"
        k = by_kind[r.kind]
        k["resources"] += 1
        k["schools"].add(r.school_id)
        if r.status == "working":
            k["working"] += 1
            k["target"] += target
        k["sessions"] += a["sessions"]
        s = schools.get(r.school_id)
        row = {**resource_dict(r), "school": s.name if s else "", "official_code": s.official_code if s else "",
               "district_id": s.district_id if s else None, "block_id": s.block_id if s else None,
               "sessions": a["sessions"], "minutes": a["minutes"], "classes_using": len(a["classes"]),
               "aligned_rate": round(a["aligned"] / a["sessions"], 4) if a["sessions"] else None,
               "utilisation": round(util, 4) if util is not None else None, "gap": gap}
        rows.append(row)
        if gap:
            gaps.append(row)
    kinds = []
    for k in by_kind.values():
        if not k["resources"]:
            continue
        kinds.append({**{x: y for x, y in k.items() if x != "schools"}, "schools": len(k["schools"]),
                      "utilisation": round(k["sessions"] / k["target"], 4) if k["target"] else None})
    subjects = {s.id: s for s in db.scalars(select(Subject))}
    total_sessions = sum(a["sessions"] for a in per_res.values())
    aligned = sum(a["aligned"] for a in per_res.values())
    return {"window_weeks": WINDOW_WEEKS, "definition": DEFINITION,
            "resources": len(resources), "working": sum(1 for r in resources if r.status == "working"),
            "schools_with_resources": len({r.school_id for r in resources}), "schools_in_scope": len(school_ids),
            "sessions": total_sessions, "aligned_rate": round(aligned / total_sessions, 4) if total_sessions else None,
            "by_kind": kinds,
            "by_subject": sorted([{"subject": subjects[s].name, "subject_hi": subjects[s].name_hi, "sessions": n}
                                  for s, n in per_subject.items()], key=lambda x: -x["sessions"]),
            "gaps": sorted(gaps, key=lambda g: ({"not_working": 0, "unused": 1, "under_used": 2}[g["gap"]], g["school"])),
            "rows": rows, "impact": _impact(db, school_ids, per_class, since, today)}


def _impact(db: Session, school_ids: list[int], per_class: dict[int, int], since: date, today: date) -> dict:
    """Mean recent score of classes that use digital resources regularly vs.
    classes that do not, within schools that have at least one resource."""
    with_res = set(db.scalars(select(DigitalResource.school_id).where(DigitalResource.school_id.in_(school_ids or [-1]))))
    classes = db.execute(select(ClassSection.id).where(ClassSection.school_id.in_(with_res or [-1]))).scalars().all()
    scores: dict[int, list[float]] = defaultdict(list)
    for cid, sc, mx in db.execute(select(Assessment.class_section_id, AssessmentResult.score, AssessmentResult.max_score)
                                  .join(Assessment, Assessment.id == AssessmentResult.assessment_id).where(
            Assessment.class_section_id.in_(classes or [-1]), AssessmentResult.status == "final",
            AssessmentResult.submitted_at >= since - timedelta(days=30))):
        if mx:
            scores[cid].append(sc / mx)
    groups = {"regular": [], "occasional": [], "none": []}
    for cid in classes:
        if not scores.get(cid):
            continue
        n = per_class.get(cid, 0)
        key = "regular" if n >= ACTIVE_CLASS_SESSIONS else ("occasional" if n else "none")
        groups[key].append(sum(scores[cid]) / len(scores[cid]))
    out = []
    for key, label in (("regular", f"{ACTIVE_CLASS_SESSIONS}+ sessions"), ("occasional", f"1-{ACTIVE_CLASS_SESSIONS - 1} sessions"),
                       ("none", "no sessions")):
        v = groups[key]
        out.append({"group": key, "label": label, "classes": len(v),
                    "avg_score": round(sum(v) / len(v), 4) if len(v) >= 3 else None})
    return {"groups": out,
            "note": "Classes in schools that have digital resources, by sessions in the window; average of recent "
                    "assessment scores (groups under 3 classes hidden). An association only: classes that use the "
                    "lab more may differ in other ways."}
