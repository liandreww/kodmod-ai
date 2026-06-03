"""
KODMOD AI — FastAPI Dependencies
================================

Reusable dependency callables: auth, current student/teacher, DB session.
Kept here so route modules import a small, stable surface.
"""

from __future__ import annotations

import logging
import uuid
from typing import AsyncIterator, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database.models import Student, Teacher
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


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


async def current_student(
    authorization: Optional[str] = Header(None),
    session: AsyncSession = Depends(db_session),
) -> Student:
    payload = _decode_jwt(_bearer(authorization))
    sub = payload.get("sub")
    role = payload.get("role")
    if not sub or role != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a student token")
    student = await session.get(Student, uuid.UUID(sub))
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


async def current_teacher(
    authorization: Optional[str] = Header(None),
    session: AsyncSession = Depends(db_session),
) -> Teacher:
    payload = _decode_jwt(_bearer(authorization))
    sub = payload.get("sub")
    role = payload.get("role")
    if not sub or role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a teacher token")
    teacher = await session.get(Teacher, uuid.UUID(sub))
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    return teacher


async def authenticate_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
) -> Student:
    """For WebSockets: token is passed as a query param to avoid header gymnastics."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    payload = _decode_jwt(token)
    sub = payload.get("sub")
    if not sub or payload.get("role") != "student":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a student token")

    # Look up the student in a one-shot session.
    from database.session import async_session

    async with async_session() as session:
        student = await session.get(Student, uuid.UUID(sub))
    if student is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


# ---------------------------------------------------- dev convenience --
async def optional_student(
    authorization: Optional[str] = Header(None),
    session: AsyncSession = Depends(db_session),
) -> Optional[Student]:
    """Allows endpoints that work for guests but enrich for logged-in users."""
    if not authorization:
        return None
    try:
        return await current_student(authorization=authorization, session=session)
    except HTTPException:
        return None
