"""Authentication, user management, group management, and SSO endpoints.

Users are ``_User`` nodes, groups are ``_Group`` nodes, object permissions
are ``_ObjectPermission`` nodes linked via ``HAS_PERMISSION`` edges.
Membership is modeled as ``_User -[:MEMBER_OF]-> _Group``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from netgraphy_api.config import settings
from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
    get_rbac,
)
from netgraphy_api.exceptions import AuthenticationError
from packages.auth.jwt import (
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)
from packages.auth.models import (
    AuthContext,
    GroupCreate,
    GroupUpdate,
    ObjectPermissionCreate,
    PasswordChange,
    PasswordReset,
    TokenPair,
    UserCreate,
    UserUpdate,
)
from packages.auth.rbac import PermissionChecker, get_role_permissions
from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
#  Request / response schemas                                                  #
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class CreateApiTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #


async def _find_user_by_username(driver: Neo4jDriver, username: str) -> dict[str, Any] | None:
    result = await driver.execute_read(
        "MATCH (u:_User {username: $username}) RETURN u", {"username": username},
    )
    return result.rows[0].get("u") if result.rows else None


async def _find_user_by_id(driver: Neo4jDriver, user_id: str) -> dict[str, Any] | None:
    result = await driver.execute_read(
        "MATCH (u:_User {id: $id}) RETURN u", {"id": user_id},
    )
    return result.rows[0].get("u") if result.rows else None


async def _count_users(driver: Neo4jDriver) -> int:
    result = await driver.execute_read("MATCH (u:_User) RETURN count(u) AS total")
    return result.rows[0].get("total", 0) if result.rows else 0


async def _create_user_node(driver, *, user_id, username, email, password_hash, role,
                            first_name="", last_name="", auth_backend="local") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    props = {
        "id": user_id, "username": username, "email": email or "",
        "password_hash": password_hash, "role": role, "first_name": first_name,
        "last_name": last_name, "is_active": True, "auth_backend": auth_backend,
        "created_at": now, "updated_at": now,
    }
    await driver.execute_write("CREATE (u:_User $props) RETURN u", {"props": props})
    return props


async def _get_or_create_admin_user(driver: Neo4jDriver) -> dict[str, Any] | None:
    count = await _count_users(driver)
    if count > 0:
        return None
    logger.info("No users found -- seeding default admin account")
    admin = await _create_user_node(
        driver, user_id=str(uuid.uuid4()), username="admin",
        email="admin@netgraphy.local", password_hash=hash_password("admin"),
        role="admin", first_name="Admin", last_name="User",
    )
    logger.info("Default admin user created", user_id=admin["id"])
    return admin


def _build_token_pair(user: dict[str, Any]) -> TokenPair:
    return create_token_pair(
        user_id=user["id"], username=user["username"], role=user["role"],
        secret_key=settings.secret_key,
        access_expire_minutes=settings.access_token_expire_minutes,
        algorithm=settings.algorithm,
    )


def _validate_password(password: str) -> None:
    """Validate password against configured minimum length."""
    min_len = settings.min_password_length
    if len(password) < min_len:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {min_len} characters",
        )


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id", ""),
        "username": user.get("username", ""),
        "email": user.get("email") or None,
        "role": user.get("role", "viewer"),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "is_active": user.get("is_active", True),
        "auth_backend": user.get("auth_backend", "local"),
        "created_at": user.get("created_at", ""),
        "updated_at": user.get("updated_at", ""),
    }


# --------------------------------------------------------------------------- #
#  Authentication                                                              #
# --------------------------------------------------------------------------- #


@router.post("/login")
async def login(body: LoginRequest, driver: Neo4jDriver = Depends(get_graph_driver)):
    """Authenticate with username/password. Tries local then LDAP backends."""
    await _get_or_create_admin_user(driver)

    # Try local authentication first
    from packages.auth.backends import LocalBackend
    local = LocalBackend()
    result = await local.authenticate(body.username, body.password, driver)

    if not result.success:
        # Try LDAP if configured
        ldap_config = await _get_auth_config(driver, "ldap")
        if ldap_config and ldap_config.get("enabled"):
            from packages.auth.backends import LDAPBackend
            ldap = LDAPBackend(ldap_config)
            result = await ldap.authenticate(body.username, body.password, driver)

    if not result.success:
        raise AuthenticationError("Invalid username or password")

    user = result.user_data
    logger.info("auth.login_success", username=body.username, backend=result.backend)
    pair = _build_token_pair(user)
    return {"data": pair.model_dump()}


@router.post("/token")
async def refresh_token(body: RefreshRequest, driver: Neo4jDriver = Depends(get_graph_driver)):
    """Exchange a valid refresh token for a new token pair."""
    try:
        payload = decode_token(body.refresh_token, settings.secret_key,
                               expected_type="refresh", algorithm=settings.algorithm)
    except Exception as exc:
        raise AuthenticationError(f"Invalid refresh token: {exc}") from exc

    user = await _find_user_by_id(driver, payload.sub)
    if user is None:
        raise AuthenticationError("User no longer exists")
    if not user.get("is_active", False):
        raise AuthenticationError("Account is disabled")

    pair = _build_token_pair(user)
    return {"data": pair.model_dump()}


@router.get("/me")
async def get_current_user(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Return current user profile with group memberships."""
    user = await _find_user_by_id(driver, auth.user_id)
    if user is None:
        raise AuthenticationError("User not found")

    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    groups = await svc.get_user_groups(auth.user_id)

    data = _sanitize_user(user)
    data["groups"] = [{"id": g.get("id"), "name": g.get("name")} for g in groups]
    return {"data": data}


# --------------------------------------------------------------------------- #
#  User Management                                                             #
# --------------------------------------------------------------------------- #


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """List all users (admin only)."""
    rbac.require_permission(auth, "manage", "user:list")

    skip = (page - 1) * page_size
    count_r = await driver.execute_read("MATCH (u:_User) RETURN count(u) as total")
    total = count_r.rows[0]["total"] if count_r.rows else 0

    result = await driver.execute_read(
        "MATCH (u:_User) "
        "OPTIONAL MATCH (u)-[:MEMBER_OF]->(g:_Group) "
        "RETURN u, collect(g.name) as groups "
        "ORDER BY u.username SKIP $skip LIMIT $limit",
        {"skip": skip, "limit": page_size},
    )
    users = []
    for row in result.rows:
        u = _sanitize_user(row["u"])
        u["groups"] = row["groups"]
        users.append(u)

    return {"data": users, "meta": {"total_count": total, "page": page, "page_size": page_size}}


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a new user account (admin only)."""
    rbac.require_permission(auth, "manage", "user:create")
    _validate_password(body.password)

    existing = await _find_user_by_username(driver, body.username)
    if existing is not None:
        from netgraphy_api.exceptions import DuplicateError
        raise DuplicateError(f"Username '{body.username}' is already taken")

    user_id = str(uuid.uuid4())
    user = await _create_user_node(
        driver, user_id=user_id, username=body.username, email=body.email,
        password_hash=hash_password(body.password), role=body.role,
        first_name=body.first_name, last_name=body.last_name,
    )
    logger.info("auth.user_created", user_id=user_id, username=body.username, created_by=auth.user_id)
    return {"data": _sanitize_user(user)}


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Get user details with group memberships."""
    rbac.require_permission(auth, "manage", "user:read")

    user = await _find_user_by_id(driver, user_id)
    if not user:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_User", user_id)

    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    groups = await svc.get_user_groups(user_id)

    data = _sanitize_user(user)
    data["groups"] = [{"id": g.get("id"), "name": g.get("name")} for g in groups]
    return {"data": data}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update user properties (admin only)."""
    rbac.require_permission(auth, "manage", "user:update")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"data": "No changes"}

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clauses = ", ".join(f"u.{k} = ${k}" for k in updates)

    result = await driver.execute_write(
        f"MATCH (u:_User {{id: $id}}) SET {set_clauses} RETURN u",
        {"id": user_id, **updates},
    )
    if not result.rows:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_User", user_id)

    logger.info("auth.user_updated", user_id=user_id, updated_by=auth.user_id, fields=list(updates.keys()))
    return {"data": _sanitize_user(result.rows[0]["u"])}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Disable a user account (soft delete)."""
    rbac.require_permission(auth, "manage", "user:delete")
    if user_id == auth.user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    await driver.execute_write(
        "MATCH (u:_User {id: $id}) SET u.is_active = false, u.updated_at = $now",
        {"id": user_id, "now": datetime.now(timezone.utc).isoformat()},
    )
    logger.info("auth.user_disabled", user_id=user_id, disabled_by=auth.user_id)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    body: PasswordReset,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Admin-initiated password reset."""
    rbac.require_permission(auth, "manage", "user:update")
    _validate_password(body.new_password)

    result = await driver.execute_write(
        "MATCH (u:_User {id: $id}) "
        "SET u.password_hash = $hash, u.updated_at = $now "
        "RETURN u.username as username",
        {"id": user_id, "hash": hash_password(body.new_password),
         "now": datetime.now(timezone.utc).isoformat()},
    )
    if not result.rows:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_User", user_id)

    logger.info("auth.password_reset", user_id=user_id, reset_by=auth.user_id)
    return {"data": {"message": "Password reset successfully"}}


@router.post("/change-password")
async def change_password(
    body: PasswordChange,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """User-initiated password change (requires current password)."""
    user = await _find_user_by_id(driver, auth.user_id)
    if not user:
        raise AuthenticationError("User not found")

    if not verify_password(body.current_password, user.get("password_hash", "")):
        raise AuthenticationError("Current password is incorrect")
    _validate_password(body.new_password)

    await driver.execute_write(
        "MATCH (u:_User {id: $id}) "
        "SET u.password_hash = $hash, u.updated_at = $now",
        {"id": auth.user_id, "hash": hash_password(body.new_password),
         "now": datetime.now(timezone.utc).isoformat()},
    )
    logger.info("auth.password_changed", user_id=auth.user_id)
    return {"data": {"message": "Password changed successfully"}}


# --------------------------------------------------------------------------- #
#  Group Management                                                            #
# --------------------------------------------------------------------------- #


@router.get("/groups")
async def list_groups(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List all groups with member counts."""
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    return {"data": await svc.list_groups()}


@router.post("/groups", status_code=201)
async def create_group(
    body: GroupCreate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a new group (admin only)."""
    rbac.require_permission(auth, "manage", "group:create")

    from packages.auth.groups import GroupService
    svc = GroupService(driver)

    existing = await svc.get_group_by_name(body.name)
    if existing:
        from netgraphy_api.exceptions import DuplicateError
        raise DuplicateError(f"Group '{body.name}' already exists")

    group = await svc.create_group(body.name, body.description, auth.user_id)
    return {"data": group}


@router.get("/groups/{group_id}")
async def get_group(
    group_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Get group details with members and permissions."""
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    group = await svc.get_group(group_id)
    if not group:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_Group", group_id)
    return {"data": group}


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update group properties."""
    rbac.require_permission(auth, "manage", "group:update")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    updates = body.model_dump(exclude_none=True)
    group = await svc.update_group(group_id, updates)
    if not group:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_Group", group_id)
    return {"data": group}


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Delete a group and its permissions."""
    rbac.require_permission(auth, "manage", "group:delete")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    if not await svc.delete_group(group_id):
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_Group", group_id)


# --------------------------------------------------------------------------- #
#  Group Membership                                                            #
# --------------------------------------------------------------------------- #


@router.post("/groups/{group_id}/members")
async def add_group_member(
    group_id: str,
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Add a user to a group."""
    rbac.require_permission(auth, "manage", "group:update")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    user_id = body.get("user_id", "")
    if not user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="user_id is required")
    success = await svc.add_member(group_id, user_id)
    return {"data": {"added": success}}


@router.delete("/groups/{group_id}/members/{user_id}", status_code=204)
async def remove_group_member(
    group_id: str,
    user_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Remove a user from a group."""
    rbac.require_permission(auth, "manage", "group:update")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    await svc.remove_member(group_id, user_id)


@router.get("/groups/{group_id}/members")
async def list_group_members(
    group_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List members of a group."""
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    return {"data": await svc.get_group_members(group_id)}


# --------------------------------------------------------------------------- #
#  Object Permissions                                                          #
# --------------------------------------------------------------------------- #


@router.get("/groups/{group_id}/permissions")
async def list_group_permissions(
    group_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List object permissions for a group."""
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    return {"data": await svc.get_group_permissions(group_id)}


@router.post("/groups/{group_id}/permissions", status_code=201)
async def create_group_permission(
    group_id: str,
    body: ObjectPermissionCreate,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create an object permission for a group."""
    rbac.require_permission(auth, "manage", "group:update")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    perm = await svc.create_object_permission(group_id, body.model_dump())
    return {"data": perm}


@router.patch("/permissions/{perm_id}")
async def update_permission(
    perm_id: str,
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update an object permission."""
    rbac.require_permission(auth, "manage", "group:update")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    perm = await svc.update_object_permission(perm_id, body)
    if not perm:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_ObjectPermission", perm_id)
    return {"data": perm}


@router.delete("/permissions/{perm_id}", status_code=204)
async def delete_permission(
    perm_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Delete an object permission."""
    rbac.require_permission(auth, "manage", "group:delete")
    from packages.auth.groups import GroupService
    svc = GroupService(driver)
    await svc.delete_object_permission(perm_id)


# --------------------------------------------------------------------------- #
#  Roles                                                                       #
# --------------------------------------------------------------------------- #


@router.get("/settings")
async def get_auth_settings():
    """Get public auth settings (password policy, etc.)."""
    return {"data": {"min_password_length": settings.min_password_length}}


@router.get("/rbac/roles")
async def list_roles():
    """List all RBAC roles with their effective permission sets."""
    from packages.auth.models import VALID_ROLES
    descriptions = {
        "viewer": "Read-only access to nodes, edges, queries, and schema",
        "editor": "Create and update nodes and edges; execute queries",
        "operator": "Run jobs, manage syncs, parsers, and IaC operations",
        "admin": "Full administrative access including user, group, and schema management",
        "superadmin": "Unrestricted access (global wildcard)",
    }
    roles = []
    for role in VALID_ROLES:
        perms = sorted(get_role_permissions(role))
        roles.append({"name": role, "description": descriptions.get(role, ""), "permissions": perms})
    return {"data": roles}


# --------------------------------------------------------------------------- #
#  Auth Configuration (LDAP / SSO)                                             #
# --------------------------------------------------------------------------- #


async def _get_auth_config(driver: Neo4jDriver, config_type: str) -> dict[str, Any] | None:
    """Load auth backend configuration from Neo4j."""
    result = await driver.execute_read(
        "MATCH (c:_AuthConfig {config_type: $type}) RETURN c",
        {"type": config_type},
    )
    if result.rows:
        import json
        config = result.rows[0]["c"]
        # Deserialize JSON fields
        for field in ["group_role_mapping", "oidc_scopes"]:
            val = config.get(field, "")
            if isinstance(val, str) and val:
                try:
                    config[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return config
    return None


@router.get("/config/ldap")
async def get_ldap_config(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Get LDAP configuration (admin only, passwords masked)."""
    rbac.require_permission(auth, "manage", "user:*")
    config = await _get_auth_config(driver, "ldap") or {"enabled": False}
    config.pop("bind_password", None)  # Never expose
    return {"data": config}


@router.put("/config/ldap")
async def update_ldap_config(
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update LDAP configuration (admin only)."""
    rbac.require_permission(auth, "manage", "user:*")
    import json
    now = datetime.now(timezone.utc).isoformat()

    # Serialize complex fields
    for field in ["group_role_mapping", "oidc_scopes"]:
        if field in body and isinstance(body[field], (dict, list)):
            body[field] = json.dumps(body[field])

    body["config_type"] = "ldap"
    body["updated_at"] = now

    await driver.execute_write(
        "MERGE (c:_AuthConfig {config_type: 'ldap'}) SET c += $props",
        {"props": body},
    )
    logger.info("auth.ldap_config_updated", updated_by=auth.user_id)
    return {"data": {"message": "LDAP configuration updated"}}


@router.get("/config/sso")
async def get_sso_config(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Get SSO configuration (admin only, secrets masked)."""
    rbac.require_permission(auth, "manage", "user:*")
    config = await _get_auth_config(driver, "sso") or {"enabled": False}
    config.pop("oidc_client_secret", None)
    config.pop("saml_idp_cert", None)
    return {"data": config}


@router.put("/config/sso")
async def update_sso_config(
    body: dict[str, Any],
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update SSO configuration (admin only)."""
    rbac.require_permission(auth, "manage", "user:*")
    import json
    now = datetime.now(timezone.utc).isoformat()

    for field in ["group_role_mapping", "oidc_scopes"]:
        if field in body and isinstance(body[field], (dict, list)):
            body[field] = json.dumps(body[field])

    body["config_type"] = "sso"
    body["updated_at"] = now

    await driver.execute_write(
        "MERGE (c:_AuthConfig {config_type: 'sso'}) SET c += $props",
        {"props": body},
    )
    logger.info("auth.sso_config_updated", updated_by=auth.user_id)
    return {"data": {"message": "SSO configuration updated"}}


# --------------------------------------------------------------------------- #
#  API Tokens                                                                  #
# --------------------------------------------------------------------------- #


@router.post("/api-tokens", status_code=201)
async def create_api_token(
    body: CreateApiTokenRequest,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Create a new API token for the current user."""
    import hashlib
    import secrets

    raw_token = f"ngy_{secrets.token_urlsafe(48)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await driver.execute_write(
        "MATCH (u:_User {id: $user_id}) "
        "CREATE (t:_ApiToken {id: $id, name: $name, description: $description, "
        "  token_hash: $hash, token_prefix: $prefix, "
        "  is_active: true, created_at: $now, last_used_at: null"
        "})-[:OWNED_BY]->(u) RETURN t",
        {"user_id": auth.user_id, "id": token_id, "name": body.name,
         "description": body.description, "hash": token_hash,
         "prefix": raw_token[:12] + "...", "now": now},
    )
    return {"data": {"id": token_id, "name": body.name, "token": raw_token,
                     "prefix": raw_token[:12] + "...", "created_at": now,
                     "message": "Save this token — it will not be shown again."}}


@router.get("/api-tokens")
async def list_api_tokens(
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List API tokens for the current user."""
    result = await driver.execute_read(
        "MATCH (t:_ApiToken)-[:OWNED_BY]->(u:_User {id: $user_id}) "
        "RETURN t ORDER BY t.created_at DESC",
        {"user_id": auth.user_id},
    )
    tokens = []
    for row in result.rows:
        t = row.get("t", {})
        tokens.append({
            "id": t.get("id"), "name": t.get("name"),
            "description": t.get("description", ""),
            "prefix": t.get("token_prefix", ""),
            "is_active": t.get("is_active", True),
            "created_at": t.get("created_at"), "last_used_at": t.get("last_used_at"),
        })
    return {"data": tokens}


@router.delete("/api-tokens/{token_id}", status_code=204)
async def revoke_api_token(
    token_id: str,
    auth: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Revoke an API token."""
    result = await driver.execute_write(
        "MATCH (t:_ApiToken {id: $id})-[:OWNED_BY]->(u:_User {id: $user_id}) "
        "SET t.is_active = false RETURN t",
        {"id": token_id, "user_id": auth.user_id},
    )
    if not result.rows:
        from netgraphy_api.exceptions import NodeNotFoundError
        raise NodeNotFoundError("_ApiToken", token_id)
