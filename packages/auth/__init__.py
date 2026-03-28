"""Auth — RBAC, SSO/OIDC, API tokens, permission enforcement."""

from packages.auth.jwt import (
    AuthenticationError,
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)
from packages.auth.middleware import (
    AuthMiddleware,
    get_auth_context,
    get_optional_auth_context,
)
from packages.auth.models import (
    AuthContext,
    TokenPair,
    TokenPayload,
    UserCreate,
    UserInDB,
)
from packages.auth.rbac import (
    AuthorizationError,
    PermissionChecker,
    get_role_permissions,
)

__all__ = [
    # Models
    "AuthContext",
    "TokenPair",
    "TokenPayload",
    "UserCreate",
    "UserInDB",
    # JWT
    "create_access_token",
    "create_refresh_token",
    "create_token_pair",
    "decode_token",
    "hash_password",
    "verify_password",
    # RBAC
    "PermissionChecker",
    "get_role_permissions",
    # Middleware / dependencies
    "AuthMiddleware",
    "get_auth_context",
    "get_optional_auth_context",
    # Exceptions
    "AuthenticationError",
    "AuthorizationError",
]
