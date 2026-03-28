"""Authentication and user management endpoints.

Provides login, token refresh, current-user introspection, RBAC role
listing, and admin-only user creation.  Users are stored as ``_User``
nodes in Neo4j (underscore prefix = internal/system type).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from netgraphy_api.config import settings
from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
    get_rbac,
)
from netgraphy_api.exceptions import AuthenticationError, AuthorizationError
from packages.auth.jwt import (
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)
from packages.auth.models import AuthContext, TokenPair, UserCreate
from packages.auth.rbac import PermissionChecker, get_role_permissions
from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger(__name__)

router = APIRouter()

# --------------------------------------------------------------------------- #
#  Request / response schemas                                                  #
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    """Credentials payload for the login endpoint."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    """Payload for the token refresh endpoint."""

    refresh_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """Public-facing user representation (no password hash)."""

    id: str
    username: str
    email: str | None = None
    role: str
    is_active: bool
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
#  Internal helpers                                                            #
# --------------------------------------------------------------------------- #


async def _find_user_by_username(
    driver: Neo4jDriver,
    username: str,
) -> dict[str, Any] | None:
    """Look up a ``_User`` node by username.  Returns raw properties or None."""
    result = await driver.execute_read(
        "MATCH (u:_User {username: $username}) RETURN u",
        {"username": username},
    )
    if result.rows:
        return result.rows[0].get("u")
    return None


async def _find_user_by_id(
    driver: Neo4jDriver,
    user_id: str,
) -> dict[str, Any] | None:
    """Look up a ``_User`` node by ID.  Returns raw properties or None."""
    result = await driver.execute_read(
        "MATCH (u:_User {id: $id}) RETURN u",
        {"id": user_id},
    )
    if result.rows:
        return result.rows[0].get("u")
    return None


async def _count_users(driver: Neo4jDriver) -> int:
    """Return the total number of ``_User`` nodes."""
    result = await driver.execute_read(
        "MATCH (u:_User) RETURN count(u) AS total",
    )
    if result.rows:
        return result.rows[0].get("total", 0)
    return 0


async def _create_user_node(
    driver: Neo4jDriver,
    *,
    user_id: str,
    username: str,
    email: str | None,
    password_hash: str,
    role: str,
) -> dict[str, Any]:
    """Persist a new ``_User`` node and return its properties."""
    now = datetime.now(timezone.utc).isoformat()
    props = {
        "id": user_id,
        "username": username,
        "email": email or "",
        "password_hash": password_hash,
        "role": role,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    await driver.execute_write(
        "CREATE (u:_User $props) RETURN u",
        {"props": props},
    )
    return props


async def _get_or_create_admin_user(driver: Neo4jDriver) -> dict[str, Any] | None:
    """Seed a default admin user if the database has no users at all.

    This enables first-time setup: the operator can log in with
    ``admin / netgraphy-admin`` and immediately create proper accounts.

    Returns:
        The admin user properties if one was created, or ``None`` if
        users already exist.
    """
    count = await _count_users(driver)
    if count > 0:
        return None

    logger.info("No users found -- seeding default admin account")
    admin = await _create_user_node(
        driver,
        user_id=str(uuid.uuid4()),
        username="admin",
        email="admin@netgraphy.local",
        password_hash=hash_password("netgraphy-admin"),
        role="admin",
    )
    logger.info("Default admin user created", user_id=admin["id"])
    return admin


def _build_token_pair(user: dict[str, Any]) -> TokenPair:
    """Create an access + refresh token pair for *user*."""
    return create_token_pair(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        secret_key=settings.secret_key,
        access_expire_minutes=settings.access_token_expire_minutes,
        algorithm=settings.algorithm,
    )


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive fields from a user dict for API responses."""
    return {
        "id": user.get("id", ""),
        "username": user.get("username", ""),
        "email": user.get("email") or None,
        "role": user.get("role", "viewer"),
        "is_active": user.get("is_active", True),
        "created_at": user.get("created_at", ""),
        "updated_at": user.get("updated_at", ""),
    }


# --------------------------------------------------------------------------- #
#  Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
) -> TokenPair:
    """Authenticate with username and password and receive a token pair.

    On first startup (no users exist) a default ``admin`` account is
    seeded automatically.
    """
    # Ensure at least one user exists.
    await _get_or_create_admin_user(driver)

    user = await _find_user_by_username(driver, body.username)
    if user is None:
        raise AuthenticationError("Invalid username or password")

    if not user.get("is_active", False):
        raise AuthenticationError("Account is disabled")

    if not verify_password(body.password, user["password_hash"]):
        raise AuthenticationError("Invalid username or password")

    logger.info("auth.login_success", username=body.username, user_id=user["id"])
    return _build_token_pair(user)


@router.post("/token", response_model=TokenPair)
async def refresh_token(
    body: RefreshRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
) -> TokenPair:
    """Exchange a valid refresh token for a new access + refresh pair.

    The old refresh token is consumed (single-use by convention).
    """
    try:
        payload = decode_token(
            body.refresh_token,
            settings.secret_key,
            expected_type="refresh",
            algorithm=settings.algorithm,
        )
    except Exception as exc:
        raise AuthenticationError(f"Invalid refresh token: {exc}") from exc

    # Verify the user still exists and is active.
    user = await _find_user_by_id(driver, payload.sub)
    if user is None:
        raise AuthenticationError("User no longer exists")
    if not user.get("is_active", False):
        raise AuthenticationError("Account is disabled")

    logger.info("auth.token_refreshed", user_id=payload.sub)
    return _build_token_pair(user)


@router.get("/me")
async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
) -> dict[str, Any]:
    """Return the profile of the currently authenticated user."""
    user = await _find_user_by_id(driver, auth.user_id)
    if user is None:
        raise AuthenticationError("User not found for current token")

    return {"data": _sanitize_user(user)}


@router.get("/rbac/roles")
async def list_roles() -> dict[str, Any]:
    """List all RBAC roles with their effective permission sets."""
    from packages.auth.models import VALID_ROLES

    roles = []
    descriptions = {
        "viewer": "Read-only access to nodes, edges, queries, and schema",
        "editor": "Create and update nodes and edges; execute queries",
        "operator": "Run jobs, manage syncs and parsers",
        "admin": "Full administrative access including user and schema management",
        "superadmin": "Unrestricted access (global wildcard)",
    }
    for role in VALID_ROLES:
        perms = sorted(get_role_permissions(role))
        roles.append({
            "name": role,
            "description": descriptions.get(role, ""),
            "permissions": perms,
        })

    return {"data": roles}


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
) -> dict[str, Any]:
    """Create a new user account (admin only).

    The password is hashed with bcrypt before storage.  A ``_User``
    node is created in Neo4j with all required properties.
    """
    # Only admins and superadmins may create users.
    rbac.require_permission(auth, "manage", "user:create")

    # Check uniqueness.
    existing = await _find_user_by_username(driver, body.username)
    if existing is not None:
        from netgraphy_api.exceptions import DuplicateError

        raise DuplicateError(f"Username '{body.username}' is already taken")

    user_id = str(uuid.uuid4())
    user = await _create_user_node(
        driver,
        user_id=user_id,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )

    logger.info(
        "auth.user_created",
        user_id=user_id,
        username=body.username,
        role=body.role,
        created_by=auth.user_id,
    )

    return {"data": _sanitize_user(user)}
