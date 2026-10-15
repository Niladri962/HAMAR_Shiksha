"""Alembic environment: uses the application's metadata and HS_DATABASE_URL.
`app.database.init_db()` passes its own connection via config.attributes."""
from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401 - registers every table
from app.config import get_settings
from app.database import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=_url().startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(_url())
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=connection.dialect.name == "sqlite", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
