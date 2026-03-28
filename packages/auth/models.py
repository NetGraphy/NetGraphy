"""Pydantic models for authentication and authorization.

Defines the data shapes for user management, JWT tokens, and the
request-scoped authentication context used throughout the platform.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Roles                                                                       #
# --------------------------------------------------------------------------- #

VALID_ROLES = ("viewer", "editor", "operator", "admin", "superadmin")
"""All recognised role names, ordered from least to most privileged."""

RoleType = Literal["viewer", "editor", "operator", "admin", "superadmin"]


# --------------------------------------------------------------------------- #
#  Request-scoped Auth Context                                                 #
# --------------------------------------------------------------------------- #

class AuthContext(BaseModel):
    """Authenticated user context attached to every protected request.

    Built from a decoded JWT (or API-token lookup) in the auth middleware
    and made available via ``request.state.auth_context``.
    """

    user_id: str = Field(..., description="Unique user identifier (UUID).")
    username: str = Field(..., description="Human-readable login name.")
    email: str | None = Field(default=None, description="Optional email address.")
    role: RoleType = Field(..., description="Assigned RBAC role.")
    permissions: list[str] = Field(
        default_factory=list,
        description="Expanded permission strings derived from the role.",
    )
    token_type: Literal["access", "api_token", "system"] = Field(
        ...,
        description="How the caller authenticated.",
    )


# --------------------------------------------------------------------------- #
#  User Management                                                             #
# --------------------------------------------------------------------------- #

class UserCreate(BaseModel):
    """Payload for creating a new user account."""

    username: str = Field(..., min_length=1, description="Unique login name.")
    email: str | None = Field(default=None, description="Optional email address.")
    password: str = Field(
        ...,
        min_length=8,
        description="Plain-text password (will be hashed before storage).",
    )
    role: RoleType = Field(default="viewer", description="Initial RBAC role.")


class UserInDB(BaseModel):
    """User record as persisted in the data store."""

    id: str = Field(..., description="Primary key (UUID).")
    username: str
    email: str | None = None
    role: RoleType
    password_hash: str = Field(..., description="Bcrypt hash of the password.")
    is_active: bool = Field(default=True, description="Soft-delete / disable flag.")
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
#  Tokens                                                                      #
# --------------------------------------------------------------------------- #

class TokenPair(BaseModel):
    """Access + refresh token pair returned on login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access-token lifetime in seconds.")


class TokenPayload(BaseModel):
    """Decoded contents of a JWT issued by the platform.

    Fields map 1-to-1 with the registered and private JWT claims.
    """

    sub: str = Field(..., description="Subject — the user_id.")
    username: str
    role: RoleType
    type: Literal["access", "refresh"] = Field(
        ...,
        description="Token purpose (access or refresh).",
    )
    exp: datetime = Field(..., description="Expiration time.")
    iat: datetime = Field(..., description="Issued-at time.")
    jti: str = Field(..., description="Unique token ID (UUID) for revocation.")
