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


class VercelPathMiddleware:
    """vercel.json rewrites every request to /api/index?__path=/<original path>.
    Put the original path back before routing (other query parameters are kept).
    Tolerates the different ways a platform may present a rewritten URL.
    `?__hsdebug=1` on any URL shows what the platform passed (no cookies or IPs)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        import json
        from urllib.parse import parse_qsl, urlencode, urlsplit

        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        raw_path = scope.get("raw_path") or scope.get("path", "").encode()
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("latin-1")
        if "?" in path:  # some adapters leave the query inside the path
            path, _, extra = path.partition("?")
            query = "&".join(q for q in (query, extra) if q)
        if "://" in path:  # absolute URL in the path
            u = urlsplit(path)
            path, query = u.path, "&".join(q for q in (query, u.query) if q)
        pairs = parse_qsl(query, keep_blank_values=True)
        if any(k == "__hsdebug" for k, _ in pairs):
            info = {"path": scope.get("path"), "raw_path": raw_path.decode("latin-1"), "root_path": scope.get("root_path"),
                    "query_string": scope.get("query_string", b"").decode("latin-1"),
                    "headers": {k.decode(): v.decode("latin-1") for k, v in scope.get("headers", [])
                                if k.decode().startswith(("x-vercel-", "x-matched", "x-forwarded-", "x-now", "host"))
                                and "ip" not in k.decode() and "for" not in k.decode()},
                    "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA", "")[:7]}
            body = json.dumps(info, indent=1).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": body})
        orig = next((v for k, v in pairs if k == "__path"), None)
        if orig is not None:
            path = "/" + orig.lstrip("/")
        elif path.rstrip("/") in ("/api/index", "/api/index.py", "/api"):
            path = "/"
        elif path.startswith("/api/index/"):
            path = path[len("/api/index"):]
        rest = urlencode([(k, v) for k, v in pairs if k != "__path"])
        scope = {**scope, "path": path, "raw_path": path.encode(), "query_string": rest.encode(), "root_path": ""}
        await self.app(scope, receive, send)
