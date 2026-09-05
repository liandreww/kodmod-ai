"""
KODMOD AI — Password Hashing and Token Issuance
==============================================

Two small responsibilities, deliberately kept out of the route modules so
there is exactly one way to hash a password and one way to mint a token.

Hashing uses the `bcrypt` package directly rather than `passlib`: passlib
1.7.4 breaks against bcrypt 4.x and has been unmaintained for years.
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from config.settings import settings

# bcrypt silently truncates anything past 72 bytes, so reject longer passwords
# outright instead of accepting a password whose tail does not matter.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

# Invitation codes are read aloud and typed by hand, so the alphabet excludes
# characters that are easy to confuse: O/0, I/1/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def hash_password(plain: str) -> str:
    """Return a bcrypt hash. Raises ValueError if the password is unusable."""
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time check. Returns False rather than raising on a malformed hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:MAX_PASSWORD_BYTES], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, subject: str, role: str) -> str:
    """Mint a signed JWT carrying the user id and role."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def generate_invitation_code(length: int = 8) -> str:
    """A short, unambiguous, cryptographically random code."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def generate_password(length: int = 12) -> str:
    """A random password, used when an admin resets someone's account."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
