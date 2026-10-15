"""Credential primitives: password hashing, opaque session tokens, TOTP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters

# Used to make failed lookups for unknown users take as long as real ones.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


COMMON_PASSWORDS = {"password", "password1", "12345678", "123456789", "qwerty123", "admin123",
                    "welcome1", "letmein1", "iloveyou", "abc12345", "shiksha123"}


def password_problems(password: str, *, min_length: int = 10) -> list[str]:
    problems = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters")
    if password.lower() in COMMON_PASSWORDS:
        problems.append("is too common")
    if password.isdigit() or password.isalpha():
        problems.append("must mix letters with digits or symbols")
    return problems


def generate_temporary_password() -> str:
    """Readable one-time password for issued credentials (forced change on first login)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Session/reset tokens are stored only as SHA-256 digests."""
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_login_id(value: str) -> str:
    return value.strip().lower()


# ------------------------------------------------------------------ TOTP ----
# RFC 6238 (SHA-1, 30 s, 6 digits) - compatible with standard authenticator apps.

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((at or time.time()) // 30))


def verify_totp(secret: str | None, code: str | None, *, window: int = 1) -> bool:
    if not secret or not code or not code.strip().isdigit():
        return False
    counter = int(time.time() // 30)
    code = code.strip()
    return any(hmac.compare_digest(_hotp(secret, counter + d), code) for d in range(-window, window + 1))


def totp_uri(secret: str, account: str, issuer: str = "HAMAR SHIKSHA") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret}&issuer={quote(issuer)}&digits=6&period=30")
