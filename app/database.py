from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite does not enforce FKs unless asked
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure(url: str) -> None:
    """Re-point the module at another database (used by tests and the CLI)."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)


ROOT = Path(__file__).resolve().parent.parent


def alembic_config():
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def init_db() -> None:
    """Bring the schema to the latest migration, then insert reference data."""
    from alembic import command

    from app import models  # noqa: F401  (register tables)

    tables = set(inspect(engine).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        raise RuntimeError("This database was created before migrations were introduced. Recreate it "
                           "(development) or run `alembic stamp <revision>` after verifying the schema.")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with SessionLocal() as db:
        models.ensure_reference_data(db)
        db.commit()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
