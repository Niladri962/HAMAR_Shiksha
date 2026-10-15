"""Vercel entry point (serverless demo deployment).

Vercel runs this file as a Python function; every request is rewritten here
(see vercel.json). Two database modes:

1. HS_DATABASE_URL is set (recommended): a hosted PostgreSQL database, e.g.
   Neon from the Vercel Marketplace. Seed it once from your own machine:
       HS_DATABASE_URL=postgresql+psycopg://... python -m app.cli seed-demo
2. HS_DATABASE_URL is not set: the bundled compact demo database
   (deploy/demo.db.gz) is copied to /tmp on each cold start. Changes are lost
   when the instance stops, and separate instances do not share sessions, so
   use this only for a quick look.

The Gyan SLM is a local model (Ollama) and does not run on Vercel. Unless
HS_SLM_URL points to an Ollama server you operate, the AI features fall back
to showing the matching textbook passages (clearly labelled, not AI).
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.gettempdir())  # /tmp on Vercel: the only writable directory
sys.path.insert(0, str(ROOT))

# Safe serverless defaults; any value set in the Vercel project settings wins.
os.environ.setdefault("HS_ENVIRONMENT", "demo")
os.environ.setdefault("HS_COOKIE_SECURE", "true")
os.environ.setdefault("HS_KB_DIR", str(TMP / "hs-kb"))
os.environ.setdefault("HS_EMBEDDING_MODEL", "")    # keyword retrieval; no model download
os.environ.setdefault("HS_STT_MODEL", "")          # Whisper is too large for a serverless function
os.environ.setdefault("HS_SLM_RUNTIME", "ollama" if os.environ.get("HS_SLM_URL") else "none")

# Vercel's Neon / Postgres integration sets DATABASE_URL or POSTGRES_URL as postgres://...
_pg = os.environ.get("HS_DATABASE_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if _pg and _pg.startswith(("postgres://", "postgresql://")):
    os.environ["HS_DATABASE_URL"] = "postgresql+psycopg://" + _pg.split("://", 1)[1]

if not os.environ.get("HS_DATABASE_URL"):
    db_path = TMP / "hamar_shiksha_demo.db"
    if not db_path.exists():
        with gzip.open(ROOT / "deploy" / "demo.db.gz", "rb") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    os.environ["HS_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

os.chdir(TMP)  # writable; a developer .env in the project folder is not read here

from app import database  # noqa: E402
from app.main import app  # noqa: E402,F401  (Vercel looks for `app`)

database.init_db()  # migrations + reference data; idempotent (lifespan may not run on every platform)
