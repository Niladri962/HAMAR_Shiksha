"""Vercel entry point (serverless demo deployment).

Vercel runs this file as a Python function; every request is rewritten here
(see vercel.json). Start-up defaults live in app/serverless.py. Database:

1. HS_DATABASE_URL / DATABASE_URL set (recommended): hosted PostgreSQL, e.g.
   Neon from the Vercel Marketplace, seeded once from your own machine.
2. Not set: the bundled compact demo database (deploy/demo.db.gz) is unpacked
   to /tmp on each cold start (changes are lost; instances do not share
   sessions). Fine for a quick look.

If start-up fails, every request answers with the reason (secrets redacted)
instead of an opaque FUNCTION_INVOCATION_FAILED. See docs/DEPLOY_VERCEL.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _failure_app(text: str):
    import re

    body = re.sub(r"://[^/\s:@]+:[^@\s]+@", "://***:***@", text)
    body = ("HAMAR SHIKSHA could not start on this deployment.\n"
            "See docs/DEPLOY_VERCEL.md (Troubleshooting).\n\n" + body).encode()

    async def failed(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})
    return failed


def _restore_path(inner):
    """vercel.json rewrites every request to /api/index?__path=/<original path>.
    Put the original path back so FastAPI routes it; other query parameters are kept."""
    from urllib.parse import parse_qsl, urlencode

    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            pairs = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
            orig = next((v for k, v in pairs if k == "__path"), None)
            if orig is not None:
                path = "/" + orig.lstrip("/")
                rest = urlencode([(k, v) for k, v in pairs if k != "__path"])
                scope = {**scope, "path": path, "raw_path": path.encode(), "query_string": rest.encode()}
            elif scope.get("path", "").rstrip("/") == "/api/index":
                scope = {**scope, "path": "/", "raw_path": b"/"}
        await inner(scope, receive, send)
    return wrapped


try:
    from app import serverless

    serverless.prepare()
    from app import database
    from app.main import app as _app

    database.init_db()  # migrations + reference data; idempotent (lifespan may not run on every platform)
    app = _restore_path(_app)
except Exception:  # noqa: BLE001 - shown in the browser and the function log
    import traceback

    _trace = traceback.format_exc()
    print(_trace, file=sys.stderr)
    app = _failure_app(_trace)
