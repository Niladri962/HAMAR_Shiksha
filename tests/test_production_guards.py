"""Production safety: no demo data, no insecure defaults."""
import pytest

from app.config import Settings, get_settings
from app.demo_seed import DemoDisabled, seed_demo


def test_production_refuses_insecure_configuration():
    s = Settings(environment="production")
    problems = " ".join(s.validate_for_production())
    for needle in ("HS_SECRET_KEY", "HS_ALLOW_DEMO_DATA", "HS_COOKIE_SECURE", "PostgreSQL", "HS_NOTIFIER"):
        assert needle in problems


def test_production_accepts_hardened_configuration():
    s = Settings(environment="production", secret_key="x" * 40, allow_demo_data=False, cookie_secure=True,
                 database_url="postgresql+psycopg://hs@db/hs", notifier="sms-gateway")
    assert s.validate_for_production() == []


def test_demo_seed_refuses_when_demo_disabled(db):
    s = get_settings()
    s.allow_demo_data = False
    try:
        with pytest.raises(DemoDisabled):
            seed_demo(db)
    finally:
        s.allow_demo_data = True


def test_all_seeded_rows_are_marked_demo(db):
    from sqlalchemy import select

    from app.models import School, SchoolCodeRegistry, User
    assert all(db.scalars(select(School.is_demo)))
    assert all(r.is_demo for r in db.scalars(select(SchoolCodeRegistry)) if r.code[2:4] >= "91")
    demo_users = db.scalars(select(User).where(User.login_id.in_(["state.admin", "st-demo01", "demo-t-001"]))).all()
    assert len(demo_users) == 3 and all(u.is_demo for u in demo_users)


def test_portable_session_survives_moving_to_another_instance(db):
    """Serverless demo: an instance that never saw the session restores it from the
    signed ticket; a missing or altered ticket is refused."""
    from sqlalchemy import delete

    from app.config import get_settings
    from app.models import AuthSession
    from app.security import token_digest
    from tests.conftest import make_client

    s = get_settings()
    s.portable_sessions = True
    try:
        c = make_client()
        assert c.post("/api/auth/admin/login", json={"login_id": "state.admin", "password": "Demo@State2026"}).status_code == 200
        assert c.cookies.get("hs_ticket")
        # "Another instance": the session row does not exist there.
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(c.cookies.get("hs_session"))))
        db.commit()
        assert c.get("/api/auth/me").status_code == 200
        assert c.post("/api/auth/language", json={"language": "en"}).status_code == 200  # CSRF restored too
        ticket = c.cookies.get("hs_ticket")
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(c.cookies.get("hs_session"))))
        db.commit()
        bad = make_client()
        bad.cookies.set("hs_session", c.cookies.get("hs_session"))
        bad.cookies.set("hs_ticket", ticket[:-4] + "0000")
        assert bad.get("/api/auth/me").status_code == 401
    finally:
        s.portable_sessions = False
