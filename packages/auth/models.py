"""Pydantic models for authentication and authorization.

Defines the data shapes for user management, group management, per-model
object permissions, JWT tokens, and the request-scoped authentication
context used throughout the platform.
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
    groups: list[str] = Field(
        default_factory=list,
        description="Group names the user belongs to.",
    )
    object_permissions: list[dict] = Field(
        default_factory=list,
        description="Per-model object permissions from group membership.",
    )
    token_type: Literal["access", "api_token", "system"] = Field(
        ...,
        description="How the caller authenticated.",
    )
    auth_backend: str = Field(
        default="local",
        description="Authentication backend used (local, ldap, saml, oidc).",
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
        min_length=1,
        description="Plain-text password (will be hashed before storage).",
    )
    role: RoleType = Field(default="viewer", description="Initial RBAC role.")
    first_name: str = Field(default="", description="First name.")
    last_name: str = Field(default="", description="Last name.")
    is_active: bool = Field(default=True, description="Whether account is enabled.")


class UserUpdate(BaseModel):
    """Payload for updating an existing user."""

    email: str | None = None
    role: RoleType | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    """Payload for admin-initiated password reset."""

    new_password: str = Field(..., min_length=1)


class PasswordChange(BaseModel):
    """Payload for user-initiated password change."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


class UserInDB(BaseModel):
    """User record as persisted in the data store."""

    id: str = Field(..., description="Primary key (UUID).")
    username: str
    email: str | None = None
    role: RoleType
    first_name: str = ""
    last_name: str = ""
    password_hash: str = Field(..., description="Bcrypt hash of the password.")
    is_active: bool = Field(default=True, description="Soft-delete / disable flag.")
    auth_backend: str = Field(default="local", description="local, ldap, saml, oidc")
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
#  Groups                                                                      #
# --------------------------------------------------------------------------- #

class GroupCreate(BaseModel):
    """Payload for creating a group."""

    name: str = Field(..., min_length=1, description="Unique group name.")
    description: str = Field(default="", description="Group description.")


class GroupUpdate(BaseModel):
    """Payload for updating a group."""

    description: str | None = None


# --------------------------------------------------------------------------- #
#  Object Permissions                                                          #
# --------------------------------------------------------------------------- #

class ObjectPermissionCreate(BaseModel):
    """Payload for creating a per-model object permission.

    Object permissions grant granular read/edit/delete access to specific
    node types. They are assigned to groups and resolved at request time.
    """

    name: str = Field(..., min_length=1, description="Permission rule name.")
    description: str = Field(default="")
    enabled: bool = Field(default=True)

    # What actions are allowed
    can_read: bool = Field(default=False, description="Allow reading objects.")
    can_create: bool = Field(default=False, description="Allow creating objects.")
    can_update: bool = Field(default=False, description="Allow updating objects.")
    can_delete: bool = Field(default=False, description="Allow deleting objects.")

    # What models this permission applies to (empty = all)
    object_types: list[str] = Field(
        default_factory=list,
        description="Node type names this permission applies to (empty = all types).",
    )

    # Job execution permissions
    can_execute_jobs: bool = Field(default=False, description="Allow executing jobs.")
    allowed_jobs: list[str] = Field(
        default_factory=list,
        description="Job names allowed (empty = all jobs if can_execute_jobs is true).",
    )


# --------------------------------------------------------------------------- #
#  LDAP / SSO Configuration                                                    #
# --------------------------------------------------------------------------- #

class LDAPConfig(BaseModel):
    """LDAP integration configuration."""

    enabled: bool = False
    server_uri: str = Field(default="", description="LDAP server URI (ldap://host:389)")
    bind_dn: str = Field(default="", description="Bind DN for LDAP queries")
    bind_password: str = Field(default="", description="Bind password (stored encrypted)")
    user_search_base: str = Field(default="", description="Base DN for user searches")
    user_search_filter: str = Field(
        default="(sAMAccountName={username})",
        description="LDAP filter template for user lookup",
    )
    group_search_base: str = Field(default="", description="Base DN for group searches")
    group_search_filter: str = Field(
        default="(member={user_dn})",
        description="LDAP filter template for group membership",
    )
    require_group: str = Field(
        default="",
        description="LDAP group DN required for access (empty = any authenticated user)",
    )
    # Attribute mappings
    attr_username: str = Field(default="sAMAccountName")
    attr_email: str = Field(default="mail")
    attr_first_name: str = Field(default="givenName")
    attr_last_name: str = Field(default="sn")
    attr_groups: str = Field(default="memberOf")
    # Behavior
    default_role: RoleType = Field(
        default="viewer",
        description="Default role for LDAP-authenticated users without group mapping",
    )
    group_role_mapping: dict[str, RoleType] = Field(
        default_factory=dict,
        description="Map LDAP group DNs to NetGraphy roles",
    )
    auto_create_user: bool = Field(
        default=True,
        description="Automatically create local user on first LDAP login",
    )
    auto_sync_groups: bool = Field(
        default=True,
        description="Sync LDAP group membership to NetGraphy groups on login",
    )
    start_tls: bool = Field(default=False)
    verify_ssl: bool = Field(default=True)


class SSOConfig(BaseModel):
    """SSO (SAML/OIDC) integration configuration."""

    enabled: bool = False
    provider_type: Literal["saml", "oidc", "none"] = Field(default="none")

    # SAML settings
    saml_idp_metadata_url: str = Field(default="", description="IdP metadata URL")
    saml_idp_sso_url: str = Field(default="", description="IdP SSO endpoint")
    saml_idp_cert: str = Field(default="", description="IdP X.509 certificate (PEM)")
    saml_sp_entity_id: str = Field(default="", description="Service Provider entity ID")

    # OIDC settings
    oidc_discovery_url: str = Field(default="", description="OIDC discovery URL (.well-known)")
    oidc_client_id: str = Field(default="")
    oidc_client_secret: str = Field(default="", description="Stored encrypted")
    oidc_scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])

    # Common settings
    default_role: RoleType = Field(default="viewer")
    group_claim: str = Field(
        default="groups",
        description="SAML attribute or OIDC claim containing group names",
    )
    group_role_mapping: dict[str, RoleType] = Field(
        default_factory=dict,
        description="Map SSO group names to NetGraphy roles",
    )
    auto_create_user: bool = Field(default=True)
    auto_sync_groups: bool = Field(default=True)


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
