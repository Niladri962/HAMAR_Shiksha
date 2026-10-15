"""Serverless (Vercel) start-up: safe defaults and a writable demo database.

Called before the settings and database are first used, from `app/main.py`
when the VERCEL environment variable is present and from `api/index.py`, so
it works whichever file Vercel uses as the entry point. Values set in the
Vercel project settings always win over these defaults.
"""
from __future__ import annotations

import gzip
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.gettempdir())  # /tmp on Vercel: the only writable directory
_done = False


def prepare() -> None:
    global _done
    if _done:
        return
    _done = True
    os.environ.setdefault("HS_ENVIRONMENT", "demo")
    os.environ.setdefault("HS_COOKIE_SECURE", "true")
    os.environ.setdefault("HS_KB_DIR", str(TMP / "hs-kb"))
    os.environ.setdefault("HS_EMBEDDING_MODEL", "")   # keyword retrieval; no model download
    os.environ.setdefault("HS_STT_MODEL", "")         # Whisper is too large for a serverless function
    os.environ.setdefault("HS_SLM_RUNTIME", "ollama" if os.environ.get("HS_SLM_URL") else "none")

    # Vercel's Neon / Postgres integration sets DATABASE_URL or POSTGRES_URL as postgres://...
    pg = os.environ.get("HS_DATABASE_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if pg and pg.startswith(("postgres://", "postgresql://")):
        os.environ["HS_DATABASE_URL"] = "postgresql+psycopg://" + pg.split("://", 1)[1]
    if not os.environ.get("HS_DATABASE_URL"):
        db_path = TMP / "hamar_shiksha_demo.db"
        if not db_path.exists():
            part = TMP / f"hamar_shiksha_demo.{os.getpid()}.part"
            with gzip.open(ROOT / "deploy" / "demo.db.gz", "rb") as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst)
            part.replace(db_path)  # atomic: a concurrent request never sees a half-written file
        os.environ["HS_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.chdir(TMP)  # writable; a developer .env in the project folder is not read here
