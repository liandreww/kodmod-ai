"""
KODMOD AI — FastAPI Dependencies
================================

Reusable dependency callables: DB session, the authenticated user, and role
gates. Route modules import a small, stable surface from here.

Authorization is role-based and centralized. A route asks for what it needs:

    student: User = Depends(require_student)
    teacher: User = Depends(require_teacher)
    staff:   User = Depends(require_roles("teacher", "admin"))

There is no per-route hand-rolled role check anywhere else in the codebase.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, Header, HTTPException, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database.models import User
from database.session import get_db

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------- DB --
async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in get_db():
        yield s


# --------------------------------------------------------------- auth --
def _decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _sub_uuid(sub: object) -> uuid.UUID:
    """Parse a JWT ``sub`` claim as a UUID, 401 on anything malformed."""
    try:
        return uuid.UUID(str(sub))
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid subject claim") from e


async def _load_user(session: AsyncSession, token: str) -> User:
    """Decode a token and load the account it names, or raise."""
    payload = _decode_jwt(token)
    user = await session.get(User, _sub_uuid(payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    # The role lives on the row, not the token, so an admin demoting someone
    # takes effect immediately instead of when their token expires.
    if payload.get("role") != user.role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token no longer matches this account")
    return user


async def current_user(
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(db_session),
) -> User:
    """The authenticated account, whatever its role."""
    return await _load_user(session, _bearer(authorization))


def require_roles(*roles: str):
    """Build a dependency that admits only the listed roles."""
    allowed = frozenset(roles)

    async def _dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action requires the {' or '.join(sorted(allowed))} role.",
            )
        return user

    _dep.__name__ = f"require_{'_or_'.join(sorted(allowed))}"
    return _dep


require_student = require_roles("student")
require_teacher = require_roles("teacher")
require_admin = require_roles("admin")
require_staff = require_roles("teacher", "admin")


async def authenticate_ws(websocket: WebSocket) -> User:
    """Authenticate a WS upgrade, admitting students only.

    The JWT is read from the ``?token=`` query param (browsers cannot set
    headers on a WebSocket handshake); an ``Authorization: Bearer`` header is
    accepted as a fallback. Any failure closes the socket with 1008 *before*
    ``accept()``, so a rejected client never sees an open socket.
    """
    token = websocket.query_params.get("token")
    if not token:
        auth = websocket.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")

    from database.session import async_session

    try:
        async with async_session() as session:
            user = await _load_user(session, token)
        if user.role != "student":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a student token")
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise
    return user
