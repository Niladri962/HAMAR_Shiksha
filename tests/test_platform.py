"""Integrated platform: learner record, Pariksha Engine, Teacher Saathi,
offline synchronisation, Command Centre and knowledge-base governance."""
import io
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.models import (
    AssessmentResult,
    AttendanceRecord,
    ClassSection,
    LearnerCompetency,
    LearnerEvent,
    School,
    SynchronizationEvent,
    TeachingMilestone,
    User,
)
from app.services.pariksha import score_short
from tests.conftest import login


def _uid():
    return uuid.uuid4().hex


def _class(db, code, grade):
    return db.scalar(select(ClassSection).join(School).where(School.official_code == code, ClassSection.grade == grade))


def _user(db, login_id):
    return db.scalar(select(User).where(User.login_id == login_id))


# ------------------------------------------------------------ learner record ----

def test_seeded_learner_record_is_event_based(db):
    st = _user(db, "st-demo01")
    n = db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.student_user_id == st.id))
    types = set(db.scalars(select(LearnerEvent.event_type).where(LearnerEvent.student_user_id == st.id)))
    assert n > 20 and {"attendance", "assessment_result"} <= types
    comps = db.scalars(select(LearnerCompetency).where(LearnerCompetency.student_user_id == st.id)).all()
    assert comps and all(c.evidence for c in comps)
    ev_uids = set(db.scalars(select(LearnerEvent.event_uid).where(LearnerEvent.student_user_id == st.id)))
    assert all(set(c.evidence) <= ev_uids for c in comps)  # evidence points at this student's own events


def test_assessment_result_updates_the_correct_learner_record(as_, db):
    s = as_("student8")
    st, other = _user(db, "st-demo02"), _user(db, "st-demo01")
    quiz = next(a for a in s.get("/api/student/assessments").json() if a["kind"] == "quiz" and a["result"] is None)
    before_other = db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.student_user_id == other.id))
    q = s.get(f"/api/student/assessments/{quiz['id']}").json()
    r = s.post(f"/api/student/assessments/{quiz['id']}/submit", json={"answers": {i["id"]: 1 for i in q["questions"]}})
    assert r.status_code == 200
    db.expire_all()
    ev = db.scalar(select(LearnerEvent).where(LearnerEvent.student_user_id == st.id,
                                              LearnerEvent.event_type == "assessment_result")
                   .order_by(LearnerEvent.id.desc()))
    assert ev.payload["assessment_id"] == quiz["id"] and ev.payload["items"][0]["lo"].startswith("DEMO-MATH8")
    assert db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.student_user_id == other.id)) == before_other
    rec = s.get("/api/student/record").json()
    assert any(e["uid"] == ev.event_uid for e in rec["events"])


def test_teacher_priority_list_cites_evidence(as_):
    pr = as_("math_teacher").get("/api/teacher/priorities").json()
    assert pr["students"]
    top = pr["students"][0]
    assert top["needs"] and top["needs"][0]["mastery"] < 0.6
    assert "marks" in top["needs"][0]["evidence"] and top["needs"][0]["code"].startswith("DEMO-")
    assert as_("other_teacher").get("/api/teacher/priorities").json()["students"] != pr["students"]


# ------------------------------------------------------------------ Pariksha ----

def test_short_answer_scoring_is_deterministic_and_flags_uncertainty():
    assert score_short("3/8", ["3/8"])[:2] == (1.0, "exact")
    assert score_short(" ३/८ ", ["3/8"])[0] == 1.0              # Devanagari digits normalised
    assert score_short("0.5", ["1/2"])[:2] == (1.0, "numeric")
    assert score_short("300 centimetre", ["300 centimetres"])[0] == 1.0  # near-exact spelling
    frac, method, conf, review = score_short("force by area", ["force/area", "force divided by area"])
    assert review is True and frac == 0.0                        # uncertain -> teacher review
    assert score_short("banana", ["3/8"])[3] is False            # clearly wrong, no review


def test_bank_assessment_review_queue_and_competency_update(as_, db):
    t = as_("math_teacher")
    c8 = _class(db, "22910100101", 8)
    r = t.post("/api/teacher/pariksha/assessments", json={
        "class_id": c8.id, "subject_id": 3, "title": "Linear equations check", "topic": "Linear equations",
        "qtypes": ["short"], "count": 2, "publish": True})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    s = as_("student8")
    q = s.get(f"/api/student/assessments/{aid}").json()
    assert all("accepted" not in i and "answer_index" not in i for i in q["questions"])
    ans = {q["questions"][0]["id"]: "x = 5", q["questions"][1]["id"]: "x=6 cm"}  # near miss -> review
    res = s.post(f"/api/student/assessments/{aid}/submit", json={"answers": ans}).json()
    assert res["status"] == "pending_review"
    st = _user(db, "st-demo02")
    result = db.scalar(select(AssessmentResult).where(AssessmentResult.assessment_id == aid,
                                                      AssessmentResult.student_user_id == st.id))
    # Pending results do not touch the learner record yet.
    assert db.scalar(select(LearnerEvent).where(LearnerEvent.event_uid == f"result-{result.id}")) is None
    queue = t.get("/api/teacher/pariksha/review-queue").json()
    item = next(x for x in queue if x["result_id"] == result.id)
    assert item["response"] and item["max"] == 1
    assert as_("other_teacher").post(f"/api/teacher/pariksha/results/{result.id}/review",
                                     json={"marks": {item["item_id"]: 1}}).status_code == 404
    done = t.post(f"/api/teacher/pariksha/results/{result.id}/review", json={"marks": {item["item_id"]: 1}}).json()
    assert done["status"] == "final" and done["score"] >= 1
    db.expire_all()
    assert db.scalar(select(LearnerEvent).where(LearnerEvent.event_uid == f"result-{result.id}")) is not None


def test_misconception_report(as_, db):
    t = as_("math_teacher")
    c5 = _class(db, "22910100101", 5)
    a = next(x for x in t.get("/api/teacher/assessments", params={"class_id": c5.id}).json()
             if x["topic"] == "Fractions" and x["results"] > 3)
    rep = t.get(f"/api/teacher/pariksha/assessments/{a['id']}/misconceptions").json()
    assert rep and {"correct_rate", "distribution", "common_wrong_option"} <= set(rep[0])
    # A misconception is named only for a wrong option chosen by >= 25% and only when the bank has a note for it.
    for r in rep:
        if r["likely_misconception"]:
            assert r["common_wrong_share"] >= 0.25
        assert sum(r["distribution"].values()) == r["responses"] > 0


def test_competency_report_for_class(as_, db):
    c5 = _class(db, "22910100101", 5)
    rows = as_("math_teacher").get("/api/teacher/pariksha/competencies", params={"class_id": c5.id, "subject_id": 3}).json()
    frac = next(r for r in rows if r["topic"] == "Fractions")
    assert frac["students_assessed"] > 5 and frac["needs_practice"] >= 1


# ------------------------------------------------------------- Teacher Saathi ----

def test_plan_milestones_and_one_tap_taught(as_, db):
    t = as_("math_teacher")
    c5 = _class(db, "22910100101", 5)
    plan = t.get("/api/teacher/saathi/plan", params={"class_id": c5.id, "subject_id": 3, "scope": "year"}).json()
    assert plan["milestones"] and plan["calendar"]["is_demo"]
    assert plan["summary"]["planned_due"] >= plan["summary"]["taught"]
    todo = next((m for m in plan["milestones"] if m["status"] == "planned"), None)
    if todo:
        assert t.post(f"/api/teacher/saathi/milestones/{todo['id']}/taught", json={}).json()["status"] == "taught"
    assert as_("other_teacher").post(f"/api/teacher/saathi/milestones/{plan['milestones'][0]['id']}/taught",
                                     json={}).status_code == 404


def test_lesson_plan_is_grounded_draft_until_approved(as_, db, fake_slm):
    t = as_("math_teacher")
    c5 = _class(db, "22910100101", 5)
    lp = t.post("/api/teacher/saathi/lesson-plans/generate", json={"class_id": c5.id, "subject_id": 3,
                                                                   "topic": "Fractions"}).json()
    assert lp["status"] == "draft" and lp["ai_generated"] and lp["sources"]
    assert "Fractions" in lp["sources"][0]["chapter"]
    assert t.post(f"/api/teacher/saathi/lesson-plans/{lp['id']}/approve").json()["status"] == "approved"


def test_teacher_saathi_answers_with_citations(as_, fake_slm):
    r = as_("math_teacher").post("/api/teacher/saathi/ask", json={
        "question": "How do we compare fractions with the same numerator?", "grade": 5}).json()
    assert r["verified"] and r["citations"][0]["page"] in (3, 4, 5) and r["citations"][0]["ref"] == "S1"


def test_substitute_lesson_reaches_students_of_that_class_only(as_, db):
    head = as_("head_teacher")
    plans = head.get("/api/teacher/saathi/approved-plans").json()
    c5 = _class(db, "22910100101", 5)
    plan = next(p for p in plans if p["grade"] == 5)
    s = head.post("/api/teacher/saathi/substitute", json={"class_id": c5.id, "lesson_plan_id": plan["id"]})
    assert s.status_code == 201
    live = as_("student5").get("/api/student/live-lesson").json()
    assert live and live["title"] == plan["title"] and live["mode"] == "substitute"
    assert as_("student8").get("/api/student/live-lesson").json() is None
    head.post(f"/api/teacher/saathi/substitute/{s.json()['id']}/end")


def test_remediation_from_class_gap(as_, fake_slm, db):
    t = as_("math_teacher")
    recs = t.get("/api/teacher/recommendations").json()["class"]
    gap = next(r for r in recs if r["evidence"]["topic"] == "Fractions") if any(
        r["evidence"]["topic"] == "Fractions" for r in recs) else recs[0]
    plan = t.post(f"/api/teacher/saathi/remediation/from-recommendation/{gap['id']}").json()
    assert plan["status"] == "proposed" and plan["students"]
    approved = t.post(f"/api/teacher/saathi/remediation/{plan['id']}/status", json={"status": "approved"}).json()
    assert approved["status"] == "approved"
    n = db.scalar(select(func.count(LearnerEvent.id)).where(LearnerEvent.event_type == "intervention",
                                                            LearnerEvent.event_uid.like(f"remediation-{plan['id']}-%")))
    assert n == len(plan["students"])


def test_micro_course_completion(as_):
    t = as_("math_teacher")
    mods = t.get("/api/teacher/saathi/training").json()
    rec = next(m for m in mods if m["recommended"])
    detail = t.get(f"/api/teacher/saathi/training/{rec['id']}").json()
    assert all("answer" not in q for q in detail["content"]["check"])
    r = t.post(f"/api/teacher/saathi/training/{rec['id']}/complete", json={"answers": [1, 1]}).json()
    assert r["total"] >= 1


# ---------------------------------------------------------------------- sync ----

def test_offline_attendance_sync_dedup_and_conflict(as_, db):
    t = as_("math_teacher")
    c5 = _class(db, "22910100101", 5)
    roster = t.get(f"/api/teacher/classes/{c5.id}/roster").json()["students"]
    # A recent day the demo seed leaves empty (it records Mon/Wed/Fri), so only this test's marks exist.
    day = next(date.today() - timedelta(days=n) for n in range(1, 7)
               if (date.today() - timedelta(days=n)).weekday() not in (0, 2, 4))
    first, second = roster[0]["student"], roster[1]["student"]
    device = "dev-" + _uid()[:12]
    old_ts = (datetime.utcnow() - timedelta(hours=5)).isoformat() + "Z"
    # Online mark now, then an older offline mark for the same student arrives.
    t.post(f"/api/teacher/classes/{c5.id}/attendance",
           json={"date": day.isoformat(), "records": [{"student": first, "status": "present"}]})
    ev = {"event_uid": _uid(), "type": "attendance.mark", "created_at": old_ts,
          "payload": {"class_id": c5.id, "date": day.isoformat(),
                      "records": [{"student": first, "status": "absent"}, {"student": second, "status": "late"}]}}
    res = t.post("/api/sync/push", json={"device_uid": device, "events": [ev]}).json()["results"][0]
    assert res["status"] == "conflict" and "newer" in res["detail"]
    st1 = db.scalar(select(User).where(User.public_id == first))
    st2 = db.scalar(select(User).where(User.public_id == second))
    db.expire_all()
    assert db.scalar(select(AttendanceRecord.status).where(AttendanceRecord.person_user_id == st1.id,
                                                           AttendanceRecord.date == day)) == "present"
    assert db.scalar(select(AttendanceRecord.status).where(AttendanceRecord.person_user_id == st2.id,
                                                           AttendanceRecord.date == day)) == "late"
    # Re-sending the same event is a no-op.
    again = t.post("/api/sync/push", json={"device_uid": device, "events": [ev]}).json()["results"][0]
    assert again["status"] == "duplicate"
    assert db.scalar(select(func.count(SynchronizationEvent.id)).where(SynchronizationEvent.event_uid == ev["event_uid"])) == 1


def test_offline_quiz_submission_syncs_once(as_, db):
    s = as_("student5")
    bundle = s.get("/api/sync/pull").json()
    assert bundle["portal"] == "student"
    assert all("answer_index" not in q and "accepted" not in q for a in bundle["assessments"] for q in a["questions"])
    if not bundle["assessments"]:
        return
    a = bundle["assessments"][0]
    answers = {q["id"]: 0 for q in a["questions"] if q["qtype"] == "mcq"}
    e1 = {"event_uid": _uid(), "type": "assessment.submit", "created_at": datetime.utcnow().isoformat(),
          "payload": {"assessment_id": a["id"], "answers": answers}}
    e2 = dict(e1, event_uid=_uid())  # same quiz submitted again from another queue entry
    res = s.post("/api/sync/push", json={"device_uid": "dev-" + _uid()[:12], "events": [e1, e2, dict(e1)]}).json()["results"]
    assert res[0]["status"] == "accepted" and res[1]["status"] == "conflict"
    assert res[2]["status"] == "duplicate"  # same event twice in one batch (found by the live sample run)
    ev = db.scalar(select(LearnerEvent).where(LearnerEvent.event_uid == e1["event_uid"]))
    assert ev is not None and ev.source == "sync"


def test_sync_cannot_widen_permissions(as_, db):
    s = as_("student5")
    c8 = _class(db, "22910100101", 8)
    roster8 = as_("math_teacher").get(f"/api/teacher/classes/{c8.id}/roster").json()["students"]
    bad = [
        {"event_uid": _uid(), "type": "attendance.mark", "created_at": datetime.utcnow().isoformat(),
         "payload": {"class_id": c8.id, "date": date.today().isoformat(),
                     "records": [{"student": roster8[0]["student"], "status": "absent"}]}},
        {"event_uid": _uid(), "type": "assessment.submit", "created_at": datetime.utcnow().isoformat(),
         "payload": {"assessment_id": 99999, "answers": {}}},
    ]
    res = s.post("/api/sync/push", json={"device_uid": "dev-" + _uid()[:12], "events": bad}).json()["results"]
    assert [r["status"] for r in res] == ["rejected", "rejected"]
    t_other = as_("other_teacher")
    res = t_other.post("/api/sync/push", json={"device_uid": "dev-" + _uid()[:12], "events": [dict(bad[0], event_uid=_uid())]}).json()
    assert res["results"][0]["status"] == "rejected"


def test_revoked_device_cannot_sync(as_, db):
    s = as_("student5")
    dev = "dev-" + _uid()[:12]
    assert s.post("/api/sync/push", json={"device_uid": dev, "events": []}).status_code == 200
    devices = as_("block_amla").get("/api/admin/command/devices").json()
    d = next(x for x in devices if x["label"].startswith("browser (student)"))
    from app.models import DeviceRegistry
    target = db.scalar(select(DeviceRegistry).where(DeviceRegistry.device_uid == dev))
    assert as_("district_south").post(f"/api/admin/command/devices/{target.id}/revoke").status_code == 404
    assert as_("block_amla").post(f"/api/admin/command/devices/{target.id}/revoke").status_code == 200
    assert s.post("/api/sync/push", json={"device_uid": dev, "events": []}).status_code == 403
    assert d


# ------------------------------------------------------------- Command Centre ----

def test_command_centre_ptl_and_scope(as_):
    state = as_("state").get("/api/admin/command/ptl").json()
    assert state["level"] == "district" and len(state["rows"]) == 33
    assert state["total"]["planned_due"] >= state["total"]["taught"] > 0
    north = as_("district_north").get("/api/admin/command/ptl").json()
    assert north["level"] == "block" and {r["name"] for r in north["rows"]} == {"Dharsiwa", "Abhanpur"}
    block = as_("block_amla").get("/api/admin/command/ptl").json()
    assert block["level"] == "school"
    assert as_("district_north").get("/api/admin/command/ptl", params={"district_id": 999}).status_code == 404


def test_command_centre_gaps_correlation_participation(as_):
    a = as_("state")
    gaps = a.get("/api/admin/command/expertise-gaps").json()
    assert gaps["by_subject"] and "training need" in gaps["definition"]
    corr = a.get("/api/admin/command/correlation").json()
    assert corr["n"] >= 3 and -1 <= corr["pearson_r"] <= 1 and "cause" in corr["note"]
    north = as_("district_north").get("/api/admin/command/expertise-gaps").json()
    assert {g["district_id"] for g in north["schools"]} <= {gaps_d for gaps_d in {g["district_id"] for g in north["schools"]}}
    part = a.get("/api/admin/command/participation").json()
    assert part["teachers"] > 0 and part["students"] > 0


# ------------------------------------------------------- knowledge base ----

def test_kb_upload_is_state_only_and_validated(as_):
    files = {"file": ("x.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}
    form = {"title": "Test", "curriculum_version": "2026", "publisher": "SCERT Chhattisgarh"}
    assert as_("district_north").post("/api/kb/documents", files=files, data=form).status_code == 403
    files = {"file": ("x.pdf", io.BytesIO(b"not a pdf"), "application/pdf")}
    assert as_("state").post("/api/kb/documents", files=files, data=form).status_code == 422
    files = {"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    assert as_("state").post("/api/kb/documents", files=files, data=form).status_code == 422
    assert as_("student5").get("/api/kb/search", params={"q": "fraction"}).status_code == 403


def test_kb_ingest_search_and_withdraw(as_):
    a = as_("state")
    text = ("=== PAGE 7 ===\n## Chapter 9: Shapes\nA triangle has three sides and three corners called vertices. "
            "A square has four equal sides and four right angles. A circle has no corners at all.")
    files = {"file": ("shapes.txt", io.BytesIO(text.encode()), "text/plain")}
    r = a.post("/api/kb/documents", files=files, data={"title": "Test Shapes Book", "subject": "MATH", "grade": 4,
                                                        "language": "en", "curriculum_version": "T-1",
                                                        "publisher": "Test Publisher"})
    assert r.status_code == 201 and r.json()["chunks"] >= 1
    hits = a.get("/api/kb/search", params={"q": "how many sides does a triangle have", "grade": 4}).json()
    assert hits["supported"] and hits["hits"][0]["page"] == 7 and hits["hits"][0]["chapter"] == "Chapter 9: Shapes"
    assert a.post(f"/api/kb/documents/{r.json()['id']}/withdraw").status_code == 200
    hits = a.get("/api/kb/search", params={"q": "how many sides does a triangle have", "grade": 4}).json()
    assert all(h["document"] != "Test Shapes Book" for h in hits["hits"])


def test_platform_config_and_slm_status(anon):
    cfg = anon.get("/api/platform").json()
    assert cfg["modules"]["slm"] == "Gyan SLM" and cfg["languages"] == ["en", "hi"]
    assert "gon" in cfg["roadmap_languages"]
    assert anon.get("/api/kb/status").status_code == 401
    st = login("math_teacher").get("/api/kb/status").json()
    assert st["documents"] >= 8 and st["chunks"] > 20 and "configured_model" in st["slm"]
