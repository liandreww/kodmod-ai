"""
KODMOD AI — Authentication Routes
=================================

Register, log in, inspect and edit your own account.

Registration is gated by an invitation code an admin minted. A code is generic:
it does not carry a role, and the person registering picks student or teacher
for themselves. Admin accounts are never self-serve.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import current_user, db_session
from api.security import create_access_token, hash_password, verify_password
from config.settings import settings
from database.models import InvitationCode, User
from models.user import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# One message for "no such user" and for "wrong password", so the endpoint
# cannot be used to discover which usernames exist.
_BAD_CREDENTIALS = "Username or password is incorrect."


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id), role=user.role),
        expires_in=settings.JWT_EXPIRE_MIN * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    session: AsyncSession = Depends(db_session),
) -> TokenResponse:
    """Create an account by redeeming an invitation code, then log straight in."""
    # Lock the code row for the rest of the transaction so two people redeeming
    # the last use of the same code cannot both succeed.
    code = (
        await session.execute(
            select(InvitationCode)
            .where(InvitationCode.code == body.invitation_code)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if code is None or not code.is_redeemable():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That invitation code is not valid. Ask your administrator for a new one.",
        )

    try:
        password_hash = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    user = User(
        username=body.username,
        password_hash=password_hash,
        role=body.role,
        full_name=body.full_name,
        grade_level=body.grade_level,
        preferred_language=body.preferred_language,
        accessibility_profile=settings.ACCESSIBILITY_DEFAULT_PROFILE
        if body.role == "student"
        else "standard",
    )
    session.add(user)
    code.used_count += 1

    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is already taken.") from e

    await session.refresh(user)
    log.info("Registered %s as %s", user.username, user.role)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(db_session),
) -> TokenResponse:
    """Exchange a username and password for an access token."""
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_CREDENTIALS)
    if not user.is_active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This account is disabled. Contact your administrator.",
        )

    user.last_login_at = datetime.now(UTC)
    await session.flush()
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    """The signed-in account."""
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> User:
    """Update your own name, language, or accessibility preference."""
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    session.add(user)
    await session.flush()
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Change your own password. Requires the current one."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    try:
        user.password_hash = hash_password(body.new_password)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    session.add(user)
    await session.flush()


@router.get("/username-available")
async def username_available(
    username: str,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Lets the registration form tell someone a name is taken before they submit."""
    taken = (
        await session.execute(
            select(func.count()).select_from(User).where(User.username == username.lower())
        )
    ).scalar_one()
    return {"username": username.lower(), "available": taken == 0}
