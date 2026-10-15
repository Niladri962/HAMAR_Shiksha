"""HAMAR SHIKSHA web application."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

if os.environ.get("VERCEL"):  # serverless: set defaults before settings/database are first read
    from app import serverless

    serverless.prepare()

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from app import database
from app.config import get_settings
from app.deps import SESSION_COOKIE
from app.models import PORTALS, AuthSession, utcnow
from app.routers import admin, auth, engage, growth, kb, pariksha, saathi, student, sync, teacher, voice
from app.security import token_digest

WEB = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("hamar_shiksha")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = get_settings().validate_for_production()
    if problems:
        raise RuntimeError("Refusing to start in production:\n - " + "\n - ".join(problems))
    database.init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="HAMAR SHIKSHA API", version="1.0.0", lifespan=lifespan,
                  docs_url=None if settings.is_production else "/api/docs",
                  redoc_url=None, openapi_url=None if settings.is_production else "/api/openapi.json")

    app.add_middleware(GZipMiddleware, minimum_size=1024)  # low-bandwidth friendly

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=(), payment=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/") and "Cache-Control" not in h:
            h["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # never leak stack traces
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal error"}, status_code=500)

    for r in (auth.router, admin.router, teacher.router, saathi.router, pariksha.router, student.router,
              sync.router, kb.router, voice.router, growth.router, engage.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        with database.SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "environment": settings.environment, "demo_data_enabled": settings.allow_demo_data}

    # ------------------------------------------------------------- pages ----
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

    def page(name: str) -> FileResponse:
        return FileResponse(WEB / "pages" / name, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def index():
        return page("index.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(WEB / "static" / "js" / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(WEB / "static" / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/reset-password", include_in_schema=False)
    def reset_page():
        return page("reset.html")

    def session_portal(request: Request) -> str | None:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return None
        with database.SessionLocal() as db:
            s = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
            if s is None or s.revoked or s.expires_at <= utcnow():
                return None
            return s.portal

    for portal in PORTALS:
        def login_page(portal=portal):
            return page(f"{portal}-login.html")

        def dashboard_page(request: Request, portal=portal):
            # Server-side gate; the APIs enforce authorization independently.
            if session_portal(request) != portal:
                return RedirectResponse(f"/{portal}/login", status_code=303)
            return page(f"{portal}-dashboard.html")

        app.add_api_route(f"/{portal}/login", login_page, include_in_schema=False)
        app.add_api_route(f"/{portal}/dashboard", dashboard_page, include_in_schema=False)

    return app


app = create_app()
