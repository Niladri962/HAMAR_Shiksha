"""AI video lessons: a teacher gives a topic, Gyan drafts a narrated lesson from the
textbook, the teacher edits and publishes it, and students of that class watch it."""
from sqlalchemy import select

from app.demo_seed import SHOWCASE_CODE
from app.models import LearnerEvent, Subject, User
from tests.test_growth_map import _class


def _ids(db, grade=5, code="MATH"):
    return _class(db, SHOWCASE_CODE, grade).id, db.scalar(select(Subject.id).where(Subject.code == code))


def test_teacher_makes_ai_video_lesson_and_students_watch_it(as_, db, fake_slm):
    cid, sid = _ids(db)
    t = as_("math_teacher")
    r = t.post("/api/teacher/video-lessons/generate", json={"class_id": cid, "subject_id": sid, "topic": "Fractions",
                                                             "language": "en", "reason": "teacher_absent"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["ai_generated"] and v["status"] == "draft" and v["model"] == "fake-slm"
    assert len(v["scenes"]) == 3 and all(s["heading"] and s["narration"] for s in v["scenes"])  # malformed scene dropped
    assert "[S1]" not in v["scenes"][0]["narration"]  # citations stay in the source list, not in the spoken text
    assert len(v["quiz"]) == 1 and v["sources"]  # malformed quiz item dropped; textbook sources attached
    assert v["grounding"] is not None and v["grounding"] >= 0.45

    # Not visible to students until published.
    st = as_("student5")
    assert st.get("/api/student/video-lessons").json() == []
    assert st.get(f"/api/student/video-lessons/{v['id']}").status_code == 404

    edited = {"title": "Fractions in daily life", "scenes": [{**s} for s in v["scenes"]], "quiz": v["quiz"]}
    edited["scenes"][0]["narration"] = "A fraction is a part of a whole, like one piece of a roti cut into four."
    assert t.put(f"/api/teacher/video-lessons/{v['id']}", json=edited).json()["title"] == "Fractions in daily life"
    assert t.post(f"/api/teacher/video-lessons/{v['id']}/publish").json()["status"] == "published"

    lessons = st.get("/api/student/video-lessons").json()
    assert [x["id"] for x in lessons] == [v["id"]] and lessons[0]["watched"] is False and "note" not in lessons[0]
    first = st.post(f"/api/student/video-lessons/{v['id']}/watched", json={"quiz_correct": 1, "quiz_total": 1}).json()
    again = st.post(f"/api/student/video-lessons/{v['id']}/watched", json={"quiz_correct": 1, "quiz_total": 1}).json()
    assert first["first_time"] and not again["first_time"]  # counted once
    me = db.scalar(select(User).where(User.login_id == "st-demo01"))
    ev = db.scalar(select(LearnerEvent).where(LearnerEvent.event_uid == f"video-{v['id']}-{me.id}"))
    assert ev.event_type == "lesson_completed" and ev.payload["video_lesson_id"] == v["id"]
    assert st.get("/api/student/video-lessons").json()[0]["watched"] is True
    assert [x for x in t.get("/api/teacher/video-lessons").json() if x["id"] == v["id"]][0]["watched_by"] == 1
    # A Class 8 student does not see a Class 5 lesson.
    assert as_("student8").get(f"/api/student/video-lessons/{v['id']}").status_code == 404


def test_without_a_model_the_lesson_is_built_from_textbook_passages(as_, db):
    cid, sid = _ids(db)
    v = as_("math_teacher").post("/api/teacher/video-lessons/generate", json={
        "class_id": cid, "subject_id": sid, "topic": "Fractions", "language": "hi"}).json()
    assert v["ai_generated"] is False and v["model"] == "textbook-passages"
    assert len(v["scenes"]) >= 3 and v["sources"] and "AI model not available" in v["note"]


def test_head_teacher_covers_any_class_others_only_their_own(as_, db, fake_slm):
    # The head teacher (who teaches languages) covers Class 8 Maths for an absent maths teacher.
    cid, sid = _ids(db, 8, "MATH")
    head = as_("head_teacher")
    opts = head.get("/api/teacher/video-lessons/options").json()
    assert opts["is_head_teacher"] and any(c["id"] == cid and any(s["id"] == sid for s in c["subjects"]) for c in opts["classes"])
    assert head.post("/api/teacher/video-lessons/generate", json={"class_id": cid, "subject_id": sid,
                                                                  "topic": "Linear equations", "language": "en"}).status_code == 201
    # A teacher can only cover their own class-subjects; another school's teacher sees nothing.
    eng = db.scalar(select(Subject.id).where(Subject.code == "ENG"))
    assert as_("math_teacher").post("/api/teacher/video-lessons/generate", json={
        "class_id": cid, "subject_id": eng, "topic": "Nouns"}).status_code == 404
    assert as_("other_teacher").post("/api/teacher/video-lessons/generate", json={
        "class_id": cid, "subject_id": sid, "topic": "Linear equations"}).status_code == 404


def test_unknown_topic_is_refused_honestly(as_, db, fake_slm):
    cid, sid = _ids(db)
    r = as_("math_teacher").post("/api/teacher/video-lessons/generate", json={
        "class_id": cid, "subject_id": sid, "topic": "Quantum chromodynamics of gluon plasma"})
    assert r.status_code == 422 and "No approved textbook passage" in r.json()["detail"]
