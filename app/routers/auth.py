"""Authentication: three portal-bound sign-in endpoints sharing one service."""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.audit import audit, client_ip
from app.config import get_settings
from app.database import get_db
from app.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    active_assignment_for_portal,
    get_principal,
)
from app.models import (
    ADMIN_ROLES,
    PORTALS,
    AuthSession,
    Block,
    District,
    LoginAttempt,
    PasswordResetToken,
    School,
    TeacherProfile,
    User,
    utcnow,
)
from app.security import (
    hash_password,
    needs_rehash,
    new_token,
    new_totp_secret,
    normalise_login_id,
    password_problems,
    token_digest,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("hamar_shiksha.auth")

GENERIC_FAIL = "Invalid login ID or password"


class LoginIn(BaseModel):
    login_id: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, max_length=10)


def _recent_failures(db: Session, *, identifier: str | None = None, ip: str | None = None) -> int:
    since = utcnow() - timedelta(minutes=get_settings().login_window_minutes)
    stmt = select(func.count(LoginAttempt.id)).where(LoginAttempt.success.is_(False), LoginAttempt.at >= since)
    if identifier:  # reset requests are throttled per IP only, so they cannot lock a user out
        stmt = stmt.where(LoginAttempt.identifier == identifier, LoginAttempt.portal != "reset")
    else:
        stmt = stmt.where(LoginAttempt.ip == ip)
    return db.scalar(stmt) or 0


def _fail(db: Session, request: Request, portal: str, login_id: str, user: User | None,
          reason: str, http_status: int = status.HTTP_401_UNAUTHORIZED, message: str = GENERIC_FAIL):
    s = get_settings()
    db.add(LoginAttempt(identifier=login_id, portal=portal, ip=client_ip(request), success=False))
    if user is not None and reason in ("bad_password", "bad_otp"):
        user.failed_login_count += 1
        if user.failed_login_count >= s.login_max_attempts:
            user.locked_until = utcnow() + timedelta(minutes=s.lockout_minutes)
            user.failed_login_count = 0
            audit(db, "account.locked", actor_user_id=user.id, request=request, entity_type="user",
                  entity_id=user.id, outcome="denied")
    audit(db, "login.failed", actor_user_id=user.id if user else None, request=request,
          outcome="denied", portal=portal, reason=reason, login_id=login_id)
    db.commit()
    raise HTTPException(http_status, message)


def _set_session_cookies(response: Response, token: str, csrf: str, max_age: int) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=secure,
                        samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure,
                        samesite="strict", path="/")


@router.post("/{portal}/login")
def login(portal: str, body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if portal not in PORTALS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown portal")
    s = get_settings()
    login_id = normalise_login_id(body.login_id)
    ip = client_ip(request)

    if (_recent_failures(db, identifier=login_id) >= s.login_max_attempts
            or _recent_failures(db, ip=ip) >= s.ip_max_attempts):
        audit(db, "login.rate_limited", request=request, outcome="denied", portal=portal, login_id=login_id)
        db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many failed attempts. Please wait and try again.")

    user = db.scalar(select(User).where(User.login_id == login_id))
    password_ok = verify_password(user.password_hash if user else None, body.password)

    if user is not None and user.locked_until and user.locked_until > utcnow():
        _fail(db, request, portal, login_id, user, "locked", status.HTTP_429_TOO_MANY_REQUESTS,
              "Account temporarily locked after failed attempts. Please try later.")
    if user is None or not password_ok:
        _fail(db, request, portal, login_id, user, "bad_password")
    if user.status != "active":
        _fail(db, request, portal, login_id, user, "inactive", status.HTTP_403_FORBIDDEN,
              "This account is not active. Contact your administrator.")

    assignment = active_assignment_for_portal(db, user.id, portal)
    if assignment is None:
        _fail(db, request, portal, login_id, user, "wrong_portal", status.HTTP_403_FORBIDDEN,
              f"This account cannot sign in to the {portal} portal. Please use your own portal's login page.")

    if portal == "teacher":
        profile = db.get(TeacherProfile, user.id)
        if profile is None or profile.verification_status != "verified":
            _fail(db, request, portal, login_id, user, "unverified", status.HTTP_403_FORBIDDEN,
                  "Your teacher account is awaiting verification by the education office.")
        if profile.school.status != "active":
            _fail(db, request, portal, login_id, user, "school_inactive", status.HTTP_403_FORBIDDEN,
                  "Your school is not active on the platform.")

    if portal == "admin":
        if user.mfa_enabled:
            if not body.otp:
                return {"mfa_required": True}
            if not verify_totp(user.mfa_secret, body.otp):
                _fail(db, request, portal, login_id, user, "bad_otp", message="Invalid verification code")
        elif s.admin_mfa_required:
            _fail(db, request, portal, login_id, user, "mfa_not_enrolled", status.HTTP_403_FORBIDDEN,
                  "Two-step verification must be set up for this account. Contact the state administrator.")

    # Success: fresh session (prevents fixation), revoke any session this browser held.
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        db.execute(update(AuthSession).where(AuthSession.token_hash == token_digest(old)).values(revoked=True))
    ttl = s.admin_session_ttl_minutes if portal == "admin" else s.session_ttl_minutes
    token, csrf = new_token(), new_token()
    db.add(AuthSession(token_hash=token_digest(token), csrf_token=csrf, user_id=user.id, portal=portal,
                       expires_at=utcnow() + timedelta(minutes=ttl), ip=ip,
                       user_agent=(request.headers.get("user-agent") or "")[:200]))
    db.add(LoginAttempt(identifier=login_id, portal=portal, ip=ip, success=True))
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    audit(db, "login.success", actor_user_id=user.id, actor_role=assignment.role.name, request=request,
          portal=portal)
    db.commit()
    _set_session_cookies(response, token, csrf, ttl * 60)
    return {"redirect": f"/{portal}/dashboard", "must_change_password": user.must_change_password,
            "role": assignment.role.name}


@router.post("/logout")
def logout(request: Request, response: Response, principal: Principal = Depends(get_principal),
           db: Session = Depends(get_db)):
    principal.session.revoked = True
    audit(db, "logout", principal=principal, request=request)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True, "redirect": f"/{principal.portal}/login"}


@router.get("/me")
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    u = principal.user
    scope = {"level": principal.role}
    if principal.role in ADMIN_ROLES:
        if principal.district_id:
            d = db.get(District, principal.district_id)
            scope["district"] = {"id": d.id, "name": d.name, "name_hi": d.name_hi}
        if principal.block_id:
            b = db.get(Block, principal.block_id)
            scope["block"] = {"id": b.id, "name": b.name, "name_hi": b.name_hi}
    elif principal.assignment and principal.assignment.school_id:
        sc = db.get(School, principal.assignment.school_id)
        scope["school"] = {"name": sc.name, "official_code": sc.official_code}
    return {
        "name": u.full_name, "login_id": u.login_id, "portal": principal.portal, "role": principal.role,
        "scope": scope, "must_change_password": u.must_change_password, "mfa_enabled": u.mfa_enabled,
        "language": u.preferred_language, "demo_mode": get_settings().allow_demo_data,
        "is_demo_account": u.is_demo,
        "session_expires_at": principal.session.expires_at.isoformat() + "Z",
    }


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_db)):
    u = principal.user
    if not verify_password(u.password_hash, body.current_password):
        audit(db, "password.change_failed", principal=principal, request=request, outcome="denied")
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    min_len = 12 if principal.portal == "admin" else (8 if principal.portal == "student" else 10)
    problems = password_problems(body.new_password, min_length=min_len)
    if body.new_password == body.current_password:
        problems.append("must differ from the current password")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "New password " + "; ".join(problems))
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = False
    # Sign out every other session for this user.
    db.execute(update(AuthSession).where(AuthSession.user_id == u.id, AuthSession.id != principal.session.id)
               .values(revoked=True))
    audit(db, "password.changed", principal=principal, request=request, entity_type="user", entity_id=u.id)
    db.commit()
    return {"ok": True}


class LanguageIn(BaseModel):
    language: str = Field(pattern="^(en|hi)$")


@router.post("/language")
def set_language(body: LanguageIn, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    principal.user.preferred_language = body.language
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------- MFA ----

@router.post("/mfa/setup")
def mfa_setup(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if principal.portal != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Two-step verification is for administrator accounts")
    if principal.user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step verification is already enabled")
    secret = new_totp_secret()
    principal.user.mfa_secret = secret
    audit(db, "mfa.setup_started", principal=principal, request=request)
    db.commit()
    return {"secret": secret, "otpauth_uri": totp_uri(secret, principal.user.login_id)}


class OtpIn(BaseModel):
    code: str = Field(max_length=10)


@router.post("/mfa/enable")
def mfa_enable(body: OtpIn, request: Request, principal: Principal = Depends(get_principal),
               db: Session = Depends(get_db)):
    u = principal.user
    if principal.portal != "admin" or not u.mfa_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start setup first")
    if not verify_totp(u.mfa_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification code")
    u.mfa_enabled = True
    audit(db, "mfa.enabled", principal=principal, request=request, entity_type="user", entity_id=u.id)
    db.commit()
    return {"ok": True}


# -------------------------------------------------------- password reset ----

class ResetRequestIn(BaseModel):
    login_id: str = Field(max_length=120)


@router.post("/password-reset/request")
def password_reset_request(body: ResetRequestIn, request: Request, db: Session = Depends(get_db)):
    """Self-service reset for staff. Students reset through their school
    (teacher-issued temporary password), never by self-service."""
    generic = {"ok": True, "message": "If the account exists and has a registered contact, "
                                      "reset instructions have been sent."}
    login_id = normalise_login_id(body.login_id)
    if _recent_failures(db, ip=client_ip(request)) >= get_settings().ip_max_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    db.add(LoginAttempt(identifier=login_id, portal="reset", ip=client_ip(request), success=False))
    user = db.scalar(select(User).where(User.login_id == login_id))
    if user is None or not (user.email or user.phone) or user.status != "active":
        db.commit()
        return generic
    if active_assignment_for_portal(db, user.id, "student") is not None:
        db.commit()
        return generic
    token = new_token()
    db.add(PasswordResetToken(token_hash=token_digest(token), user_id=user.id,
                              expires_at=utcnow() + timedelta(minutes=30)))
    audit(db, "password.reset_requested", actor_user_id=user.id, request=request)
    db.commit()
    _deliver_reset(user, token)
    return generic


def _deliver_reset(user: User, token: str) -> None:
    if get_settings().notifier == "log":
        # Development only: production refuses to start with the log notifier.
        log.warning("DEV password reset link for %s: /reset-password#token=%s", user.login_id, token)
    else:  # pragma: no cover - integration point for the approved SMS/email gateway
        raise NotImplementedError("Configure the approved SMS/e-mail gateway in app.routers.auth._deliver_reset")


class ResetConfirmIn(BaseModel):
    token: str = Field(max_length=128)
    new_password: str = Field(max_length=256)


@router.post("/password-reset/confirm")
def password_reset_confirm(body: ResetConfirmIn, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest(body.token)))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")
    user = db.get(User, row.user_id)
    min_len = 12 if active_assignment_for_portal(db, user.id, "admin") else 10
    problems = password_problems(body.new_password, min_length=min_len)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "New password " + "; ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    row.used_at = utcnow()
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(revoked=True))
    audit(db, "password.reset_completed", actor_user_id=user.id, request=request)
    db.commit()
    return {"ok": True}
