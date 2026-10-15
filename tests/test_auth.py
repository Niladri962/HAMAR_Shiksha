"""Authentication: separate portals, sessions, CSRF, lockout, MFA, password policy."""
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, User
from app.security import totp_now
from tests.conftest import CREDS, login, make_client


def test_each_portal_logs_in_and_redirects_to_its_dashboard():
    for who, expected in [("state", "/admin/dashboard"), ("math_teacher", "/teacher/dashboard"),
                          ("student5", "/student/dashboard")]:
        portal, login_id, pw = CREDS[who]
        c = make_client()
        r = c.post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": pw})
        assert r.status_code == 200
        assert r.json()["redirect"] == expected
        me = c.get("/api/auth/me").json()
        assert me["portal"] == portal
        # The dashboard page is served for the right portal ...
        assert c.get(expected, follow_redirects=False).status_code == 200
        # ... and redirects to that portal's login for the other two.
        for other in {"admin", "teacher", "student"} - {portal}:
            r = c.get(f"/{other}/dashboard", follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == f"/{other}/login"


def test_login_pages_are_distinct():
    c = make_client()
    pages = {p: c.get(f"/{p}/login").text for p in ("admin", "teacher", "student")}
    assert 'data-portal="admin"' in pages["admin"] and "theme-admin" in pages["admin"]
    assert 'data-portal="teacher"' in pages["teacher"] and "theme-teacher" in pages["teacher"]
    assert 'data-portal="student"' in pages["student"] and "theme-student" in pages["student"]


def test_credentials_only_work_on_their_own_portal():
    _, login_id, pw = CREDS["math_teacher"]
    r = make_client().post("/api/auth/admin/login", json={"login_id": login_id, "password": pw})
    assert r.status_code == 403
    _, login_id, pw = CREDS["student5"]
    for portal in ("teacher", "admin"):
        r = make_client().post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": pw})
        assert r.status_code == 403
    _, login_id, pw = CREDS["state"]
    assert make_client().post("/api/auth/student/login", json={"login_id": login_id, "password": pw}).status_code == 403


def test_wrong_password_and_unknown_user_get_the_same_generic_error():
    a = make_client().post("/api/auth/admin/login", json={"login_id": "state.admin", "password": "wrong-password-1"})
    b = make_client().post("/api/auth/admin/login", json={"login_id": "no.such.user", "password": "wrong-password-1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_unauthenticated_api_access_is_rejected(anon):
    for path in ("/api/admin/overview", "/api/teacher/me", "/api/student/me", "/api/auth/me"):
        assert anon.get(path).status_code == 401


def test_state_changing_requests_require_csrf_token():
    c = login("math_teacher")
    c.send_csrf = False
    r = c.post("/api/teacher/assignments", json={"class_section_id": 1, "subject_id": 1, "title": "x" * 5})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]
    r = c.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    c.send_csrf = True
    assert c.post("/api/auth/logout").status_code == 200


def test_logout_revokes_the_server_side_session():
    c = login("student8")
    token = c.cookies.get("hs_session")
    assert c.post("/api/auth/logout").status_code == 200
    c2 = make_client()
    c2.cookies.set("hs_session", token)
    assert c2.get("/api/student/me").status_code == 401


def test_account_locks_after_repeated_failures(db):
    portal, login_id, pw = CREDS["district_south"]
    s = get_settings()
    for _ in range(s.login_max_attempts):
        assert make_client().post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": "bad-pass-123"}).status_code == 401
    # Even the correct password is refused while locked / rate limited.
    r = make_client().post(f"/api/auth/{portal}/login", json={"login_id": login_id, "password": pw})
    assert r.status_code == 429
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.details["login_id"].as_string() == login_id)))
    assert {"login.failed", "login.rate_limited"} <= actions or "login.failed" in actions
    # unlock for other tests
    u = db.scalar(select(User).where(User.login_id == login_id))
    u.locked_until = None
    from app.models import LoginAttempt
    db.query(LoginAttempt).filter(LoginAttempt.identifier == login_id).delete()
    db.commit()


def test_admin_mfa_enrolment_and_login(db):
    c = login("block_amla")
    setup = c.post("/api/auth/mfa/setup").json()
    assert c.post("/api/auth/mfa/enable", json={"code": "000000"}).status_code == 400
    assert c.post("/api/auth/mfa/enable", json={"code": totp_now(setup["secret"])}).status_code == 200
    _, login_id, pw = CREDS["block_amla"]
    first = make_client().post("/api/auth/admin/login", json={"login_id": login_id, "password": pw})
    assert first.status_code == 200 and first.json() == {"mfa_required": True}
    assert make_client().post("/api/auth/admin/login", json={"login_id": login_id, "password": pw, "otp": "123456"}).status_code in (401,)
    ok = make_client().post("/api/auth/admin/login", json={"login_id": login_id, "password": pw, "otp": totp_now(setup["secret"])})
    assert ok.status_code == 200 and ok.json()["redirect"] == "/admin/dashboard"
    # MFA setup is not offered to other portals
    assert login("student8").post("/api/auth/mfa/setup").status_code == 403
    # restore for other tests
    u = db.scalar(select(User).where(User.login_id == login_id))
    u.mfa_enabled, u.mfa_secret = False, None
    db.commit()


def test_new_teacher_must_be_verified_and_change_password(as_):
    admin = as_("district_north")
    schools = admin.get("/api/admin/search/schools", params={"code": "22910100101"}).json()
    r = admin.post(f"/api/admin/schools/{schools[0]['id']}/teachers",
                   json={"employee_id": "TEST-T-900", "full_name": "Test Teacher"})
    assert r.status_code == 201
    created = r.json()
    temp = created["temporary_password"]
    # Pending verification -> cannot sign in
    r = make_client().post("/api/auth/teacher/login", json={"login_id": "TEST-T-900", "password": temp})
    assert r.status_code == 403 and "verification" in r.json()["detail"]
    assert admin.post(f"/api/admin/teachers/{created['user_id']}/verify", json={"approve": True}).status_code == 200
    t = make_client()
    r = t.post("/api/auth/teacher/login", json={"login_id": "test-t-900", "password": temp})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    # Portal APIs are blocked until the password is changed
    assert t.get("/api/teacher/me").status_code == 403
    weak = t.post("/api/auth/change-password", json={"current_password": temp, "new_password": "short"})
    assert weak.status_code == 422
    assert t.post("/api/auth/change-password",
                  json={"current_password": temp, "new_password": "Strong-pass-2026"}).status_code == 200
    assert t.get("/api/teacher/me").status_code == 200


def test_security_headers_present(anon):
    r = anon.get("/admin/login")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    c = login("student8")
    r = c.get("/api/student/me")
    assert r.headers["cache-control"] == "no-store"
    assert "httponly" in c.post("/api/auth/student/login", json={"login_id": "st-demo02", "password": CREDS["student8"][2]}) \
        .headers["set-cookie"].lower()


def test_password_reset_flow_for_staff(db, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="hamar_shiksha.auth")
    u = db.scalar(select(User).where(User.login_id == "demo-t-005"))
    u.email = "teacher@example.invalid"
    db.commit()
    anon = make_client()
    r = anon.post("/api/auth/password-reset/request", json={"login_id": "DEMO-T-005"})
    assert r.status_code == 200
    token = caplog.text.split("token=")[1].split()[0]
    assert anon.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "weak"}).status_code == 422
    assert anon.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Reset-pass-2026"}).status_code == 200
    assert anon.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "Reset-pass-2027"}).status_code == 400
    assert make_client().post("/api/auth/teacher/login", json={"login_id": "DEMO-T-005", "password": "Reset-pass-2026"}).status_code == 200
    # restore for other tests
    from app.security import hash_password
    u = db.scalar(select(User).where(User.login_id == "demo-t-005"))
    db.refresh(u)
    u.password_hash = hash_password(CREDS["other_teacher"][2])
    db.commit()
    # Students cannot self-reset: generic response, no token issued
    caplog.clear()
    anon.post("/api/auth/password-reset/request", json={"login_id": "st-demo01"})
    assert "token=" not in caplog.text
