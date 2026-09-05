"""Pydantic schemas for accounts, authentication, and invitation codes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.security import MIN_PASSWORD_LENGTH

Role = Literal["student", "teacher", "admin"]
# Roles a person may pick for themselves at registration. Admin is deliberately
# absent: admins are created by another admin, or by scripts/create_admin.py.
SelfServeRole = Literal["student", "teacher"]

Username = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")]
Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=72)]


class UserOut(BaseModel):
    """A safe view of an account. Never carries the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: Role
    full_name: str
    is_active: bool
    grade_level: str | None = None
    preferred_language: str = "id"
    accessibility_profile: str = "blind"
    created_at: datetime
    last_login_at: datetime | None = None


class RegisterRequest(BaseModel):
    username: Username
    password: Password
    full_name: str = Field(min_length=1, max_length=200)
    role: SelfServeRole
    invitation_code: str = Field(min_length=1, max_length=32)
    grade_level: str | None = None
    preferred_language: Literal["id", "en"] = "id"

    @field_validator("username")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("invitation_code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class LoginRequest(BaseModel):
    username: Username
    password: str = Field(min_length=1, max_length=72)

    @field_validator("username")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  # OAuth scheme name, not a secret
    expires_in: int  # seconds
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: Password


class UpdateProfileRequest(BaseModel):
    """Self-service edits. Role and username are not changeable here."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    grade_level: str | None = None
    preferred_language: Literal["id", "en"] | None = None
    accessibility_profile: Literal["blind", "low_vision", "standard"] | None = None


# ----------------------------------------------------------------- admin --
class AdminCreateUserRequest(BaseModel):
    """Admin account creation. Unlike registration, any role is allowed."""

    username: Username
    password: Password
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    grade_level: str | None = None
    preferred_language: Literal["id", "en"] = "id"

    @field_validator("username")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class AdminUpdateUserRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    new_password: Password | None = None


class InvitationCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    label: str | None
    max_uses: int
    used_count: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class InvitationCodeCreate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
