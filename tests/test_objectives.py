"""Milestone grades & corrective actions, attendance follow-up, digital
infrastructure use, recognition and data-driven teacher development."""
from sqlalchemy import select

from app.demo_seed import SHOWCASE_CODE
from app.models import (
    Appreciation,
    ClassSection,
    DigitalResource,
    DigitalUsage,
    School,
    TeacherProfile,
    TeachingMilestone,
    User,
)
from app.services import monitoring
from tests.test_growth_map import _class


# --------------------------------------------------- milestone progress grades --

def test_grade_is_the_weaker_band():
    assert monitoring.grade_for(0.95, 0.8) == "A"
    assert monitoring.grade_for(0.95, 0.4) == "C"      # taught on time but not learned
    assert monitoring.grade_for(0.6, None) == "C"      # nothing assessed yet: taught band only
    assert monitoring.grade_for(0.2, 0.9) == "D"
    assert monitoring.grade_for(None, None) is None


def test_teacher_sees_grades_and_actions_for_own_class_subjects(as_):
    d = as_("math_teacher").get("/api/teacher/progress-grades").json()
    assert d["rows"] and all(r["subject"] in ("Mathematics", "Science", "Environmental Studies") or r["subject"]
                             for r in d["rows"])
    for r in d["rows"]:
        assert r["grade"] in ("A", "B", "C", "D", None)
        assert r["taught"] <= r["planned_due"] and r["learned"] <= r["assessed"]
        if r["overdue"]:
            assert any(a["kind"] == "catch_up" for a in r["actions"])
    assert as_("math_teacher").get("/api/teacher/progress-grades?scope=school").status_code == 403
    school = as_("head_teacher").get("/api/teacher/progress-grades?scope=school").json()
    assert school["school"]["official_code"] == SHOWCASE_CODE and len(school["rows"]) >= len(d["rows"])


def test_admin_progress_grades_roll_up_by_scope(as_):
    st = as_("state").get("/api/admin/command/progress-grades").json()
    assert st["level"] == "district" and len(st["units"]) == 33
    assert sum(st["counts"].values()) == len(st["schools"])
    blk = as_("block_amla").get("/api/admin/command/progress-grades").json()
    assert blk["level"] == "school" and all(s["official_code"].startswith("229101") for s in blk["schools"])


# ------------------------------------------------------------- attendance --

def test_attendance_follow_up_lists_children_with_learning_link(as_, db):
    cs = _class(db, SHOWCASE_CODE, 5)
    d = as_("math_teacher").get(f"/api/teacher/classes/{cs.id}/attendance-risk").json()
    flagged = {r["name"]: r for r in d["flagged"]}
    assert any("continuous_absence" in r["flags"] and r["level"] == "high" for r in flagged.values())
    for r in flagged.values():
        assert r["actions"] and "missed_outcomes" in r and r["public_id"]
    assert sum(d["counts"].values()) == d["students"]
    # Another school's teacher cannot read this class.
    assert as_("other_teacher").get(f"/api/teacher/classes/{cs.id}/attendance-risk").status_code == 404


def test_admins_get_counts_never_names(as_):
    r = as_("district_north").get("/api/admin/command/attendance-risk")
    d = r.json()
    assert d["level"] == "block" and d["total"]["students"] > 0
    assert "flagged" not in r.text and "public_id" not in r.text
    assert sum(d["total"]["counts"].values()) == d["total"]["students"]


# ------------------------------------------------------ digital infrastructure --

def _showcase_resource(db, status="working"):
    sid = db.scalar(select(School.id).where(School.official_code == SHOWCASE_CODE))
    r = db.scalar(select(DigitalResource).where(DigitalResource.school_id == sid, DigitalResource.status == status))
    if r is None:
        r = DigitalResource(school_id=sid, kind="smart_class", label=f"Test {status}", status=status, is_demo=True)
        db.add(r)
        db.commit()
    return r


def test_teacher_logs_digital_use_and_marks_milestone_with_resource(as_, db):
    c = as_("math_teacher")
    res = _showcase_resource(db)
    me = c.get("/api/teacher/me").json()
    a = next(x for x in me["assignments"] if x["subject"] == "Mathematics")
    view = c.get("/api/teacher/digital").json()
    assert any(r["id"] == res.id for r in view["resources"])
    los = c.get(f"/api/teacher/learning-outcomes?class_id={a['class_id']}&subject_id={a['subject_id']}").json()
    r = c.post("/api/teacher/digital/usage", json={"resource_id": res.id, "class_id": a["class_id"],
                                                   "subject_id": a["subject_id"], "learning_outcome_id": los[0]["id"],
                                                   "minutes": 40, "activity": "Fraction strips on the smart board"})
    assert r.status_code == 201, r.text
    assert db.get(DigitalUsage, r.json()["id"]).learning_outcome_id == los[0]["id"]

    m = db.scalar(select(TeachingMilestone).where(TeachingMilestone.class_section_id == a["class_id"],
                                                  TeachingMilestone.subject_id == a["subject_id"],
                                                  TeachingMilestone.status == "planned"))
    t = c.post(f"/api/teacher/saathi/milestones/{m.id}/taught", json={"digital_resource_id": res.id}).json()
    db.expire_all()
    u = db.get(DigitalUsage, t["digital_usage_id"])
    assert u.learning_outcome_id == m.learning_outcome_id and u.class_section_id == a["class_id"]


def test_digital_use_is_school_scoped_and_needs_a_working_resource(as_, db):
    res = _showcase_resource(db)
    broken = _showcase_resource(db, "not_working")
    c = as_("other_teacher")
    me = c.get("/api/teacher/me").json()
    a = me["assignments"][0]
    assert c.post("/api/teacher/digital/usage", json={"resource_id": res.id, "class_id": a["class_id"],
                                                      "subject_id": a["subject_id"]}).status_code == 404
    m = as_("math_teacher")
    a2 = m.get("/api/teacher/me").json()["assignments"][0]
    assert m.post("/api/teacher/digital/usage", json={"resource_id": broken.id, "class_id": a2["class_id"],
                                                      "subject_id": a2["subject_id"]}).status_code == 409
    # Only the head teacher registers resources; any teacher may report a fault.
    assert m.post("/api/teacher/digital/resources", json={"kind": "ict_lab", "label": "Lab 2"}).status_code == 403
    assert as_("head_teacher").post("/api/teacher/digital/resources",
                                    json={"kind": "language_lab", "label": "Language lab"}).status_code == 201


def test_admin_digital_utilisation_and_gaps(as_):
    d = as_("state").get("/api/admin/command/digital").json()
    assert d["resources"] > 0 and d["by_kind"] and d["sessions"] > 0
    assert {g["gap"] for g in d["gaps"]} <= {"not_working", "unused", "under_used"}
    assert [g["group"] for g in d["impact"]["groups"]] == ["regular", "occasional", "none"]
    blk = as_("block_amla").get("/api/admin/command/digital").json()
    assert all(g["official_code"].startswith("229101") for g in blk["gaps"])


# ------------------------------------------------------------- recognition --

def test_student_badges_reward_improvement_and_show_progress(as_):
    d = as_("student5").get("/api/student/recognition").json()
    keys = [b["key"] for b in d["badges"]]
    assert {"rising_star", "attendance_up", "streak7", "helper"} <= set(keys)
    assert all("why" in b and "target" in b for b in d["badges"])
    assert d["challenge"]["target"] >= 1 and d["certificate"]["name"]
    assert any(a["category"] == "improvement" for a in d["appreciations"])  # seeded demo note


def test_teacher_appreciates_own_student_only_and_messages_are_screened(as_, db):
    c = as_("math_teacher")
    st = db.scalar(select(User).where(User.login_id == "st-demo01"))
    assert c.post(f"/api/teacher/students/{st.public_id}/appreciate",
                  json={"category": "effort", "message": "Well done on the quiz!"}).status_code == 201
    assert c.post(f"/api/teacher/students/{st.public_id}/appreciate",
                  json={"category": "effort", "message": "call me on 9876543210"}).status_code == 422
    assert c.post(f"/api/teacher/students/{st.public_id}/appreciate", json={"category": "bogus"}).status_code == 422
    assert as_("other_teacher").post(f"/api/teacher/students/{st.public_id}/appreciate",
                                     json={"category": "effort"}).status_code == 404
    got = as_("student5").get("/api/student/recognition").json()["appreciations"]
    assert any(a["message"] == "Well done on the quiz!" for a in got)


def test_head_teacher_and_admins_appreciate_teachers_within_scope(as_, db):
    head = as_("head_teacher")
    rec = head.get("/api/teacher/recognition").json()
    assert rec["badges"] and rec["colleagues"]
    colleague = rec["colleagues"][0]["public_id"]
    assert head.post(f"/api/teacher/colleagues/{colleague}/appreciate", json={"category": "innovation"}).status_code == 201
    assert as_("math_teacher").post(f"/api/teacher/colleagues/{colleague}/appreciate",
                                    json={"category": "innovation"}).status_code == 403

    view = as_("state").get("/api/admin/command/recognition").json()
    assert "improved_schools" in view and all(s["change_points"] > 0 for s in view["improved_schools"])
    t2 = db.scalar(select(User).where(User.login_id == "demo-t-002"))
    assert as_("block_amla").post(f"/api/admin/teachers/{t2.id}/appreciate",
                                  json={"category": "milestones"}).status_code == 201
    # A teacher outside the district admin's scope is invisible.
    far = db.scalar(select(TeacherProfile).join(School, School.id == TeacherProfile.school_id)
                    .where(School.district_id != db.scalar(select(School.district_id).where(
                        School.official_code == SHOWCASE_CODE))).limit(1))
    assert as_("district_north").post(f"/api/admin/teachers/{far.user_id}/appreciate",
                                      json={"category": "milestones"}).status_code == 404
    assert db.scalar(select(Appreciation).where(Appreciation.recipient_user_id == far.user_id)) is None


# ------------------------------------------------------ teacher development --

def test_micro_courses_explain_why_they_are_recommended(as_):
    mods = as_("math_teacher").get("/api/teacher/saathi/training").json()
    assert mods and all("reasons" in m for m in mods)
    assert all(m["reasons"] for m in mods if m["recommended"])
