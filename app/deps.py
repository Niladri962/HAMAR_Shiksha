"""Authentication and authorization dependencies.

Every protected route resolves a `Principal` from the server-side session and
then applies portal, role and data-scope checks here or in `app.scope`.
Nothing the browser sends (URL, school code, request body, local storage) can
widen a principal's scope: scope comes only from active role assignments.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.database import get_db
from app.models import (
    ADMIN_ROLES,
    ROLE_PORTAL,
    AuthSession,
    TeacherProfile,
    User,
    UserRoleAssignment,
    utcnow,
)
from app.security import token_digest

SESSION_COOKIE = "hs_session"
CSRF_COOKIE = "hs_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    session: AuthSession
    portal: str
    role: str
    assignment: UserRoleAssignment | None

    @property
    def district_id(self) -> int | None:
        return self.assignment.district_id if self.assignment else None

    @property
    def block_id(self) -> int | None:
        return self.assignment.block_id if self.assignment else None


def active_assignment_for_portal(db: Session, user_id: int, portal: str) -> UserRoleAssignment | None:
    rows = db.scalars(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id, UserRoleAssignment.active.is_(True))
    ).all()
    # Deterministic precedence if a user ever holds several admin roles.
    order = {name: i for i, name in enumerate((*ADMIN_ROLES, "teacher", "student"))}
    rows = sorted((r for r in rows if ROLE_PORTAL.get(r.role.name) == portal),
                  key=lambda r: order.get(r.role.name, 99))
    return rows[0] if rows else None


def _unauthenticated() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthenticated()
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
    now = utcnow()
    if sess is None or sess.revoked or sess.expires_at <= now:
        raise _unauthenticated()
    user = db.get(User, sess.user_id)
    if user is None or user.status != "active":
        raise _unauthenticated()

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed")

    assignment = active_assignment_for_portal(db, user.id, sess.portal)
    if assignment is None:  # role revoked after sign-in
        sess.revoked = True
        db.commit()
        raise _unauthenticated()

    if now - sess.last_seen_at > timedelta(minutes=1):
        sess.last_seen_at = now
        db.commit()
    return Principal(user=user, session=sess, portal=sess.portal,
                     role=assignment.role.name, assignment=assignment)


def _deny(db: Session, request: Request, principal: Principal, need: str) -> HTTPException:
    audit(db, "access.denied", principal=principal, request=request, outcome="denied",
          path=request.url.path, required=need)
    db.commit()
    return HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this resource")


def require_portal(portal: str):
    def dep(request: Request, principal: Principal = Depends(get_principal),
            db: Session = Depends(get_db)) -> Principal:
        if principal.portal != portal:
            raise _deny(db, request, principal, f"portal:{portal}")
        if principal.user.must_change_password:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required before continuing")
        if portal == "teacher":
            profile = db.get(TeacherProfile, principal.user.id)
            if profile is None or profile.verification_status != "verified" or profile.school.status != "active":
                raise _deny(db, request, principal, "verified-teacher")
        return principal
    return dep


def require_admin(*roles: str):
    allowed = roles or ADMIN_ROLES

    def dep(request: Request, principal: Principal = Depends(require_portal("admin")),
            db: Session = Depends(get_db)) -> Principal:
        if principal.role not in allowed:
            raise _deny(db, request, principal, "role:" + "|".join(allowed))
        return principal
    return dep


require_teacher = require_portal("teacher")
require_student = require_portal("student")
