"""FastAPI / Starlette authentication middleware and request dependencies.

The middleware extracts a Bearer JWT from the ``Authorization`` header,
validates it, and attaches an :class:`AuthContext` to ``request.state``.
It also loads group memberships and object permissions from Neo4j so that
downstream services can enforce schema-driven per-model access control.

Key security invariant:
    An agent acting on behalf of a user inherits the user's permissions
    and may never exceed them. The agent is NOT a privileged superuser.
"""

from __future__ import annotations

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from packages.auth.jwt import AuthenticationError, decode_token
from packages.auth.models import AuthContext
from packages.auth.rbac import get_role_permissions

logger = structlog.get_logger()

# Paths that never require authentication.
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/v1/auth/login",
    "/api/v1/auth/token",
    "/api/v1/auth/settings",
    "/api/v1/auth/rbac/roles",
    "/api/v1/docs",
    "/api/v1/redoc",
    "/api/v1/openapi.json",
    "/api/v1/schema",  # Schema metadata must be public for dynamic UI
    "/api/v1/generated/metrics",  # Prometheus scrape endpoint
    "/api/v1/docs/pages",  # Docs reading is public
    "/api/v1/docs/nav",  # Docs navigation is public
    "/api/v1/docs/search",  # Docs search is public
    "/api/v1/docs/for",  # Schema-linked docs lookup is public
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticates requests via JWT or API tokens and builds full AuthContext.

    After token validation, loads group memberships and object permissions
    from Neo4j so the PermissionChecker can enforce schema-driven per-model
    and per-field access control.
    """

    def __init__(
        self,
        app,
        secret_key: str,
        algorithm: str = "HS256",
        public_paths: tuple[str, ...] | None = None,
    ):
        super().__init__(app)
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._public_paths = _PUBLIC_PATH_PREFIXES + (public_paths or ())

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        if self._is_public(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return self._unauthorized("Missing Authorization header")

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return self._unauthorized("Authorization header must be: Bearer <token>")

        token = parts[1]

        if self._looks_like_jwt(token):
            try:
                payload = decode_token(
                    token,
                    self._secret_key,
                    expected_type="access",
                    algorithm=self._algorithm,
                )
            except AuthenticationError as exc:
                logger.warning("auth.token_invalid", error=exc.message, path=request.url.path)
                return self._unauthorized(exc.message)

            permissions = sorted(get_role_permissions(payload.role))
            auth_context = AuthContext(
                user_id=payload.sub,
                username=payload.username,
                email=None,
                role=payload.role,
                permissions=permissions,
                token_type="access",
            )
        else:
            auth_context = await self._resolve_api_token(request, token)
            if auth_context is None:
                return self._unauthorized("Invalid API token")

        # Load groups and object permissions from Neo4j
        auth_context = await self._enrich_auth_context(request, auth_context)

        request.state.auth_context = auth_context
        return await call_next(request)

    def _is_public(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._public_paths)

    @staticmethod
    def _looks_like_jwt(token: str) -> bool:
        return token.count(".") == 2

    @staticmethod
    async def _enrich_auth_context(request: Request, ctx: AuthContext) -> AuthContext:
        """Load group memberships and object permissions from Neo4j.

        This is the critical step that enables schema-driven per-model
        access control. Without it, object_permissions would be empty
        and group-based RBAC would not work.
        """
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is None:
            return ctx

        try:
            import json

            # Load groups
            groups_result = await driver.execute_read(
                "MATCH (u:_User {id: $uid})-[:MEMBER_OF]->(g:_Group) RETURN g.name as name",
                {"uid": ctx.user_id},
            )
            groups = [row["name"] for row in groups_result.rows]

            # Load object permissions from all groups
            perms_result = await driver.execute_read(
                "MATCH (u:_User {id: $uid})-[:MEMBER_OF]->(g:_Group)"
                "-[:HAS_PERMISSION]->(p:_ObjectPermission) "
                "WHERE p.enabled = true "
                "RETURN DISTINCT p",
                {"uid": ctx.user_id},
            )
            object_perms = []
            for row in perms_result.rows:
                p = row["p"]
                for field in ["object_types", "allowed_jobs"]:
                    val = p.get(field, "[]")
                    if isinstance(val, str):
                        try:
                            p[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            p[field] = []
                object_perms.append(p)

            ctx.groups = groups
            ctx.object_permissions = object_perms

        except Exception as e:
            logger.warning("auth.enrich_failed", user_id=ctx.user_id, error=str(e))

        return ctx

    @staticmethod
    async def _resolve_api_token(request: Request, token: str) -> AuthContext | None:
        import hashlib
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver is None:
            return None

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await driver.execute_read(
            "MATCH (t:_ApiToken {token_hash: $hash, is_active: true})"
            "-[:OWNED_BY]->(u:_User) "
            "RETURN t, u",
            {"hash": token_hash},
        )
        if not result.rows:
            return None

        t = result.rows[0].get("t", {})
        u = result.rows[0].get("u", {})

        from datetime import datetime, timezone
        try:
            await driver.execute_write(
                "MATCH (t:_ApiToken {id: $id}) SET t.last_used_at = $now",
                {"id": t.get("id"), "now": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            pass

        permissions = sorted(get_role_permissions(u.get("role", "viewer")))
        return AuthContext(
            user_id=u.get("id", ""),
            username=u.get("username", ""),
            email=u.get("email"),
            role=u.get("role", "viewer"),
            permissions=permissions,
            token_type="api_token",
            auth_backend=u.get("auth_backend", "local"),
        )

    @staticmethod
    def _unauthorized(message: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "AUTHENTICATION_ERROR",
                    "message": message,
                    "details": [],
                }
            },
        )


# --------------------------------------------------------------------------- #
#  FastAPI Dependencies                                                        #
# --------------------------------------------------------------------------- #

def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency — return the current AuthContext with groups and permissions loaded."""
    auth_context: AuthContext | None = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise AuthenticationError("Authentication required")
    return auth_context


def get_optional_auth_context(request: Request) -> AuthContext | None:
    """FastAPI dependency — return the AuthContext or None."""
    return getattr(request.state, "auth_context", None)
