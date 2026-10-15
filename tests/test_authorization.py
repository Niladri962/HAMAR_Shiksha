"""Role and data-scope isolation, enforced server-side."""
from sqlalchemy import select

from app.models import (
    AuditLog,
    ClassSection,
    School,
    StudentEnrollment,
    User,
)


def _school(db, code):
    return db.scalar(select(School).where(School.official_code == code))


def test_teacher_cannot_use_admin_apis(as_, db):
    t = as_("math_teacher")
    for path in ("/api/admin/overview", "/api/admin/districts", "/api/admin/audit-logs", "/api/admin/reports/coverage"):
        assert t.get(path).status_code == 403
    assert t.post("/api/admin/schools", json={"official_code": "22910100108"}).status_code == 403
    assert db.scalar(select(AuditLog).where(AuditLog.action == "access.denied")) is not None


def test_student_cannot_use_teacher_or_admin_apis(as_):
    s = as_("student5")
    assert s.get("/api/teacher/me").status_code == 403
    assert s.get("/api/admin/overview").status_code == 403
    assert s.get("/api/teacher/classes/1/roster").status_code == 403


def test_admin_cannot_use_student_or_teacher_apis(as_):
    a = as_("state")
    assert a.get("/api/student/me").status_code == 403
    assert a.get("/api/teacher/me").status_code == 403


def test_student_sees_only_own_class_material(as_, db):
    s = as_("student5")
    me = s.get("/api/student/me").json()
    assert me["grade"] == 5
    # An assessment from another class (Class 8) is invisible.
    other_cs = db.scalar(select(ClassSection).join(School).where(School.official_code == "22910100101",
                                                                 ClassSection.grade == 8))
    from app.models import Assessment
    other = db.scalar(select(Assessment).where(Assessment.class_section_id == other_cs.id))
    assert s.get(f"/api/student/assessments/{other.id}").status_code == 404
    assert s.post(f"/api/student/assessments/{other.id}/submit", json={"answers": {}}).status_code == 404
    # Results list contains only this student's own results.
    own = s.get("/api/student/progress").json()["results"]
    st8 = as_("student8").get("/api/student/progress").json()["results"]
    assert own and st8 and {r["assessment"] for r in own}.isdisjoint({r["assessment"] for r in st8})


def test_student_identity_comes_from_session_not_request(as_):
    """No student endpoint accepts a student ID; extra params are ignored."""
    s = as_("student5")
    a = s.get("/api/student/progress").json()
    b = s.get("/api/student/progress", params={"student_id": 1, "user_id": 2}).json()
    assert a == b


def test_teacher_sees_only_assigned_classes_and_students(as_, db):
    t = as_("other_teacher")  # teaches at 22910100102
    showcase_class = db.scalar(select(ClassSection).join(School).where(School.official_code == "22910100101",
                                                                       ClassSection.grade == 5))
    assert t.get(f"/api/teacher/classes/{showcase_class.id}/roster").status_code == 404
    assert t.get(f"/api/teacher/classes/{showcase_class.id}/performance").status_code == 404
    st = db.scalar(select(User).where(User.login_id == "st-demo01"))
    assert t.get(f"/api/teacher/students/{st.public_id}/progress").status_code == 404
    assert t.post(f"/api/teacher/classes/{showcase_class.id}/attendance",
                  json={"date": "2026-01-01", "records": []}).status_code == 404
    # The assigned teacher can.
    own = as_("math_teacher")
    roster = own.get(f"/api/teacher/classes/{showcase_class.id}/roster").json()["students"]
    assert any(r["login_id"] == "st-demo01" or r["login_id"] == "st-demo02" for r in roster)
    assert own.get(f"/api/teacher/students/{st.public_id}/progress").status_code == 200


def test_non_head_teacher_cannot_enrol(as_, db):
    t = as_("math_teacher")
    cs = db.scalar(select(ClassSection).join(School).where(School.official_code == "22910100101"))
    r = t.post(f"/api/teacher/school/classes/{cs.id}/students",
               json={"full_name": "X Y", "guardian_name": "G H", "guardian_consent": True})
    assert r.status_code == 403


def test_district_admin_cannot_see_other_districts(as_, db):
    a = as_("district_north")
    south = _school(db, "22920100101")
    north = _school(db, "22910100101")
    assert a.get(f"/api/admin/schools/{south.id}").status_code == 404
    assert a.get(f"/api/admin/schools/{north.id}").status_code == 200
    # Code search gives an identical answer for "outside scope" and "not registered".
    r1 = a.get("/api/admin/search/schools", params={"code": south.official_code})
    r2 = a.get("/api/admin/search/schools", params={"code": "22910100177"})
    assert r1.status_code == r2.status_code == 404 and r1.json() == r2.json()
    assert a.get(f"/api/admin/districts/{south.district_id}/blocks").status_code == 404
    assert a.get(f"/api/admin/blocks/{south.block_id}/schools").status_code == 404
    other_class = db.scalar(select(ClassSection).where(ClassSection.school_id == south.id))
    assert a.get(f"/api/admin/classes/{other_class.id}").status_code == 404
    # Tampering with filter parameters does not widen scope.
    assert a.get("/api/admin/overview", params={"district_id": south.district_id}).status_code == 404
    assert a.get("/api/admin/reports/coverage", params={"district_id": south.district_id}).status_code == 404
    districts = a.get("/api/admin/districts").json()
    assert [d["code"] for d in districts] == ["2291"]
    names = {s["name"] for s in a.get("/api/admin/needs-support").json()}
    assert all(_name_in_district(db, n, "2291") for n in names)


def _name_in_district(db, name, district_code):
    s = db.scalar(select(School).where(School.name == name))
    return s.district.code == district_code


def test_block_admin_limited_to_block(as_, db):
    a = as_("block_amla")
    other_block = _school(db, "22910200101")  # same district, other block
    assert a.get(f"/api/admin/schools/{other_block.id}").status_code == 404
    assert a.get(f"/api/admin/schools/{_school(db, '22910100102').id}").status_code == 200
    blocks = a.get(f"/api/admin/districts/{other_block.district_id}/blocks").json()["blocks"]
    assert [b["code"] for b in blocks] == ["229101"]
    assert a.get("/api/admin/overview").json()["totals"]["blocks"] == 1


def test_state_admin_sees_all_active_schools(as_, db):
    a = as_("state")
    active = db.scalars(select(School).where(School.status == "active")).all()
    ov = a.get("/api/admin/overview").json()
    assert ov["totals"]["schools_active"] == len(active)
    assert ov["totals"]["districts"] == 33
    south = _school(db, "22920100101")
    assert a.get(f"/api/admin/schools/{south.id}").status_code == 200


def test_only_state_admin_manages_admins_and_audit(as_):
    d = as_("district_north")
    assert d.get("/api/admin/admins").status_code == 403
    assert d.get("/api/admin/audit-logs").status_code == 403
    assert d.post("/api/admin/admins", json={"login_id": "x.y.z", "full_name": "X", "role": "block_admin",
                                             "block_id": 1}).status_code == 403
    assert as_("state").get("/api/admin/audit-logs").status_code == 200


def test_revoked_role_ends_existing_session(as_, db):
    state = as_("state")
    r = state.post("/api/admin/admins", json={"login_id": "temp.block", "full_name": "Temp Block Officer",
                                              "role": "block_admin", "block_id": _school(db, "22920100101").block_id})
    assert r.status_code == 201
    from tests.conftest import make_client
    c = make_client()
    assert c.post("/api/auth/admin/login", json={"login_id": "temp.block",
                                                 "password": r.json()["temporary_password"]}).status_code == 200
    from app.models import UserRoleAssignment
    assignment = db.scalar(select(UserRoleAssignment).where(UserRoleAssignment.user_id == r.json()["user_id"]))
    assert state.post(f"/api/admin/admins/{assignment.id}/revoke").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_enrolment_requires_guardian_consent(as_, db):
    a = as_("district_north")
    cs = db.scalar(select(ClassSection).join(School).where(School.official_code == "22910100102"))
    r = a.post(f"/api/admin/classes/{cs.id}/students",
               json={"full_name": "New Student", "guardian_name": "Guardian", "guardian_consent": False})
    assert r.status_code == 422
    r = a.post(f"/api/admin/classes/{cs.id}/students",
               json={"full_name": "New Student", "guardian_name": "Guardian", "guardian_consent": True})
    assert r.status_code == 201
    login_id = r.json()["login_id"]
    assert login_id.startswith("st-") and "new" not in login_id.lower()
    enr = db.scalar(select(StudentEnrollment).where(StudentEnrollment.student_user_id == r.json()["user_id"]))
    assert enr.class_section_id == cs.id
