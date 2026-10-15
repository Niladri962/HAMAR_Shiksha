"""Chhattisgarh divisions & map analysis; student self-improvement and peer help."""
from sqlalchemy import select

from app import geo
from app.demo_seed import DEMO_PASSWORDS
from app.models import ClassSection, District, LearnerEvent, RevisionItem, School, StudentEnrollment, User
from app.registry import is_demo_code
from tests.conftest import make_client


def _class(db, code, grade):
    return db.scalar(select(ClassSection).join(School).where(School.official_code == code, ClassSection.grade == grade))


def _classmate(db, login_id="st-demo01", offset=1):
    me = db.scalar(select(User).where(User.login_id == login_id))
    cs_id = db.scalar(select(StudentEnrollment.class_section_id).where(StudentEnrollment.student_user_id == me.id))
    ids = list(db.scalars(select(StudentEnrollment.student_user_id).where(StudentEnrollment.class_section_id == cs_id)
                          .order_by(StudentEnrollment.roll_no)))
    return db.get(User, ids[offset])


def _login_student(login_id):
    c = make_client()
    assert c.post("/api/auth/student/login", json={"login_id": login_id, "password": DEMO_PASSWORDS["student"]}).status_code == 200
    return c


# ---------------------------------------------------------------- geography --

def test_reference_geography_has_33_districts_in_5_divisions():
    assert len(geo.DISTRICTS) == 33 and len({d.name for d in geo.DISTRICTS}) == 33
    per_div = {code: sum(d.division == code for d in geo.DISTRICTS) for code, _, _ in geo.DIVISIONS}
    assert per_div == {"RPR": 5, "DRG": 7, "BSP": 8, "SRG": 6, "BST": 7}
    assert sum(d.created_2022 for d in geo.DISTRICTS) == 5
    assert geo.lookup("Kawardha").name == "Kabirdham" and geo.lookup("KANKER").name == "Uttar Bastar Kanker"
    assert geo.lookup("Atlantis") is None
    assert is_demo_code("22600100101") and not is_demo_code("22330100101")


def test_every_demo_district_belongs_to_a_division(db):
    districts = db.scalars(select(District)).all()
    assert len(districts) == 33 and all(d.division_id for d in districts)
    assert {d.name for d in districts} == {d.name for d in geo.DISTRICTS}


def test_map_analysis_by_division_for_state(as_):
    m = as_("state").get("/api/admin/map").json()
    assert [d["code"] for d in m["divisions"]] == ["RPR", "DRG", "BSP", "SRG", "BST"]
    assert len(m["districts"]) == 33 and m["demo"] is True
    assert all(r["map_shape"] for r in m["districts"])
    for div in m["divisions"]:
        rows = [r for r in m["districts"] if r["division"] == div["code"]]
        assert div["districts"] == len(rows)
        assert div["registry_schools"] == sum(r["registry_schools"] for r in rows)
        assert div["students"] == sum(r["students"] for r in rows) > 0
    assert all(r["schools_active"] >= 1 and r["teachers"] >= 1 and r["students"] >= 1 for r in m["districts"])


def test_map_is_scoped_for_district_and_block_admins(as_):
    d = as_("district_north").get("/api/admin/map").json()
    assert [r["name"] for r in d["districts"]] == ["Raipur"] and [v["code"] for v in d["divisions"]] == ["RPR"]
    b = as_("block_amla").get("/api/admin/map").json()
    assert [r["name"] for r in b["districts"]] == ["Raipur"]
    assert b["districts"][0]["registry_schools"] < d["districts"][0]["registry_schools"]


def test_map_boundaries_are_served(anon):
    gj = anon.get("/static/data/cg-districts.geojson").json()
    shapes = {f["properties"]["shape"] for f in gj["features"]}
    assert len(shapes) == 28 and {d.map_shape for d in geo.DISTRICTS} <= shapes
    assert "geoBoundaries" in gj["attribution"]


# ------------------------------------------------------------ self-improvement --

def test_growth_level_goals_and_custom_tick(as_):
    s = as_("student5")
    g = s.get("/api/student/growth").json()
    assert g["level"]["xp"] > 0 and g["level"]["level"] >= 1 and len(g["goals"]) >= 2
    goal = s.post("/api/student/goals", json={"kind": "custom", "title": "Read 2 stories at home", "target": 2}).json()
    assert goal["progress"] == 0 and goal["manual"]
    assert s.post(f"/api/student/goals/{goal['id']}/tick").json()["progress"] == 1
    auto = next(x for x in g["goals"] if x["kind"] == "practice")
    assert s.post(f"/api/student/goals/{auto['id']}/tick").status_code == 422  # counted automatically
    assert as_("student8").post(f"/api/student/goals/{goal['id']}/tick").status_code == 404
    assert s.post("/api/student/goals", json={"kind": "custom", "title": "call 9876543210", "target": 1}).status_code == 422


def test_revision_deck_spaced_review(as_, db):
    s = as_("student5")
    r = s.get("/api/student/revision").json()
    assert r["summary"]["open"] > 0 and r["items"] and "answer_index" not in r["items"][0]
    item = r["items"][0]
    row = db.get(RevisionItem, item["id"])
    right, wrong = row.question["answer_index"], (row.question["answer_index"] + 1) % len(item["options"])
    out = s.post(f"/api/student/revision/{item['id']}/answer", json={"choice": wrong}).json()
    assert out["correct"] is False and out["correct_streak"] == 0
    out = s.post(f"/api/student/revision/{item['id']}/answer", json={"choice": right}).json()
    assert out["correct"] and not out["mastered"]
    out = s.post(f"/api/student/revision/{item['id']}/answer", json={"choice": right}).json()
    assert out["mastered"]
    assert as_("student8").post(f"/api/student/revision/{item['id']}/answer", json={"choice": 0}).status_code == 404


def test_wrong_quiz_answers_enter_the_revision_deck(as_, db):
    from app.models import Assessment, Subject

    c5 = _class(db, "22910100101", 5)
    qs = [{"id": "q1", "qtype": "mcq", "text": "2 + 2 = ?", "options": ["3", "4", "5"], "answer_index": 1, "topic": "Addition"},
          {"id": "q2", "qtype": "mcq", "text": "5 - 3 = ?", "options": ["2", "1", "8"], "answer_index": 0, "topic": "Addition"}]
    teacher = db.scalar(select(User).where(User.login_id == "demo-t-002"))
    quiz = Assessment(class_section_id=c5.id, subject_id=db.scalar(select(Subject.id).where(Subject.code == "MATH")),
                      created_by=teacher.id, title="Revision capture check", topic="Addition", kind="quiz",
                      max_score=2.0, questions=qs, published=True)
    db.add(quiz)
    db.commit()
    s = as_("student5")
    r = s.post(f"/api/student/assessments/{quiz.id}/submit", json={"answers": {"q1": 0, "q2": 0}})  # q1 wrong, q2 right
    assert r.status_code == 200, r.text
    me = db.scalar(select(User).where(User.login_id == "st-demo01"))
    db.expire_all()
    keys = set(db.scalars(select(RevisionItem.item_key).where(RevisionItem.student_user_id == me.id)))
    assert f"assessment:{quiz.id}:q1" in keys and f"assessment:{quiz.id}:q2" not in keys


def test_textbook_library_reading(as_, db):
    s = as_("student5")
    lib = s.get("/api/student/library").json()
    assert lib["grade"] == 5 and lib["books"]
    book = lib["books"][0]
    sec = book["sections"][0]
    page = s.get(f"/api/student/library/{book['id']}", params={"key": sec["key"]}).json()
    assert page["passages"] and page["passages"][0]["text"]
    assert s.post(f"/api/student/library/{book['id']}/read", json={"key": sec["key"]}).status_code == 200
    again = s.get("/api/student/library").json()
    assert next(x for x in next(b for b in again["books"] if b["id"] == book["id"])["sections"] if x["key"] == sec["key"])["read"]
    other = as_("student8").get("/api/student/library").json()
    assert book["id"] not in {b["id"] for b in other["books"]}
    assert as_("student8").get(f"/api/student/library/{book['id']}", params={"key": sec["key"]}).status_code == 404


# ------------------------------------------------------------------- peer help --

def test_class_doubt_board_peer_answer_and_moderation(as_, db):
    me = as_("student5")
    mate = _classmate(db)
    peer = _login_student(mate.login_id)
    d = me.post("/api/student/doubts", json={"audience": "class", "topic": "Fractions",
                                              "body": "How do I add 1/4 and 2/4?"}).json()
    assert d["status"] == "open"
    seen = [x for x in peer.get("/api/student/doubts").json() if x["id"] == d["id"]]
    assert seen and seen[0]["asker"] == me.get("/api/student/me").json()["name"].split()[0]  # first name only
    d2 = peer.post(f"/api/student/doubts/{d['id']}/replies", json={"body": "Add the tops: 1+2 = 3, so 3/4."}).json()
    reply = d2["replies"][-1]
    assert peer.post(f"/api/student/replies/{reply['id']}/accept").status_code == 403  # only the asker
    assert me.post(f"/api/student/replies/{reply['id']}/accept").json()["status"] == "answered"
    assert db.scalar(select(LearnerEvent.id).where(LearnerEvent.student_user_id == mate.id,
                                                   LearnerEvent.event_type == "peer_help")) is not None
    # Students in another class cannot see or answer it.
    assert as_("student8").post(f"/api/student/doubts/{d['id']}/replies", json={"body": "hello there"}).status_code == 404
    # Teacher moderation: a hidden reply disappears for students.
    t = as_("math_teacher")
    assert any(x["id"] == d["id"] for x in t.get("/api/teacher/help/doubts").json())
    t.post(f"/api/teacher/help/replies/{reply['id']}/hide")
    mine = next(x for x in me.get("/api/student/doubts").json() if x["id"] == d["id"])
    assert all(r["id"] != reply["id"] for r in mine["replies"])
    assert as_("other_teacher").post(f"/api/teacher/help/replies/{reply['id']}/hide").status_code == 404


def test_posts_are_screened_for_safety(as_, db):
    s = as_("student5")
    for body in ("call me on 9876543210 after school", "join my whatsapp group", "you are stupid"):
        r = s.post("/api/student/doubts", json={"audience": "class", "body": body})
        assert r.status_code == 422, body
    r = s.post("/api/student/doubts", json={"audience": "class", "body": "I want to hurt myself"})
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "wellbeing"
    flagged = [x for x in as_("math_teacher").get("/api/teacher/help/doubts").json() if x["topic"].startswith("Wellbeing")]
    assert flagged and flagged[0]["audience"] == "teacher"  # private to the teacher, never on the class board
    mate = _login_student(_classmate(db).login_id)
    assert not any(x["topic"].startswith("Wellbeing") for x in mate.get("/api/student/doubts").json())


def test_ask_teacher_privately(as_, db):
    me = as_("student5")
    d = me.post("/api/student/doubts", json={"audience": "teacher", "body": "Please explain improper fractions again."}).json()
    mate = _login_student(_classmate(db, offset=2).login_id)
    assert all(x["id"] != d["id"] for x in mate.get("/api/student/doubts").json())
    t = as_("math_teacher")
    out = t.post(f"/api/teacher/help/doubts/{d['id']}/replies", json={"body": "An improper fraction has a top bigger than the bottom, like 5/4."}).json()
    assert out["status"] == "answered" and out["replies"][-1]["role"] == "teacher"


def test_study_pairs_suggested_and_created_by_teacher(as_, db):
    t = as_("math_teacher")
    c5 = _class(db, "22910100101", 5)
    data = t.get(f"/api/teacher/help/classes/{c5.id}/pairs").json()
    assert data["pairs"]  # the seeded pair
    assert "rule" in data and isinstance(data["suggestions"], list)
    mates = [_classmate(db, offset=i) for i in (3, 4)]
    r = t.post(f"/api/teacher/help/classes/{c5.id}/pairs", json={"helper": mates[0].public_id, "learner": mates[1].public_id,
                                                                  "topic": "Place value", "note": "Practise together"})
    assert r.status_code == 201
    buddy = _login_student(mates[1].login_id).get("/api/student/study-buddies").json()
    assert any(b["topic"] == "Place value" and b["role"] == "learner" for b in buddy)
    assert as_("other_teacher").get(f"/api/teacher/help/classes/{c5.id}/pairs").status_code == 404
    s8 = db.scalar(select(User).where(User.login_id == "st-demo02"))
    assert t.post(f"/api/teacher/help/classes/{c5.id}/pairs", json={"helper": s8.public_id, "learner": mates[1].public_id,
                                                                     "topic": "x1"}).status_code == 404
