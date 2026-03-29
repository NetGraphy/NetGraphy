"""FastAPI / Starlette authentication middleware and request dependencies.

The middleware extracts a Bearer JWT from the ``Authorization`` header,
validates it, and attaches an :class:`AuthContext` to ``request.state``
so that downstream route handlers and dependencies can retrieve it
without repeating token logic.

Configuration (``secret_key``, ``algorithm``) is injected at middleware
instantiation time — this package never imports application config
directly.
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
    "/api/v1/docs",
    "/api/v1/redoc",
    "/api/v1/openapi.json",
    "/api/v1/schema",  # Schema metadata must be public for dynamic UI
)


# --------------------------------------------------------------------------- #
#  Middleware                                                                   #
# --------------------------------------------------------------------------- #

class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that authenticates requests via JWT Bearer tokens.

    Args:
        app: The ASGI application to wrap.
        secret_key: HMAC key used to verify token signatures.
        algorithm: JWT signing algorithm (default ``"HS256"``).
        public_paths: Additional path prefixes that should be publicly
            accessible without a token.
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

    # ------------------------------------------------------------------ #

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Extract and validate the JWT, then forward the request."""

        # Always allow CORS preflight (OPTIONS) through — CORSMiddleware handles these.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow public endpoints through without authentication.
        if self._is_public(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return self._unauthorized("Missing Authorization header")

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return self._unauthorized("Authorization header must be: Bearer <token>")

        token = parts[1]

        # Try JWT first, then fall back to API token lookup
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
            # API token: resolve from Neo4j via app state
            auth_context = await self._resolve_api_token(request, token)
            if auth_context is None:
                return self._unauthorized("Invalid API token")

        request.state.auth_context = auth_context
        return await call_next(request)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _is_public(self, path: str) -> bool:
        """Return ``True`` if *path* matches a public prefix."""
        return any(path.startswith(prefix) for prefix in self._public_paths)

    @staticmethod
    def _looks_like_jwt(token: str) -> bool:
        """JWTs have 3 dot-separated base64 segments."""
        return token.count(".") == 2

    @staticmethod
    async def _resolve_api_token(request: Request, token: str) -> AuthContext | None:
        """Look up an API token in Neo4j and return an AuthContext."""
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

        # Update last_used timestamp (fire and forget)
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
        )

    @staticmethod
    def _unauthorized(message: str) -> JSONResponse:
        """Return a 401 JSON response."""
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
    """FastAPI dependency — return the current :class:`AuthContext`.

    Must be used on protected routes (behind :class:`AuthMiddleware`).

    Raises:
        AuthenticationError: If no auth context is present on the request.
    """
    auth_context: AuthContext | None = getattr(request.state, "auth_context", None)
    if auth_context is None:
        raise AuthenticationError("Authentication required")
    return auth_context


def get_optional_auth_context(request: Request) -> AuthContext | None:
    """FastAPI dependency — return the :class:`AuthContext` or ``None``.

    Useful for endpoints that behave differently for authenticated vs.
    anonymous callers.
    """
    return getattr(request.state, "auth_context", None)
