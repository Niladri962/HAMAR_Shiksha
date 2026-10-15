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
