"""JWT token creation, validation, and password hashing utilities.

All functions accept cryptographic material (secret keys) as explicit
parameters so the package remains independent of any application config.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext

from packages.auth.models import TokenPair, TokenPayload

logger = structlog.get_logger()

# Bcrypt context — only scheme we support.
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Default signing algorithm.
_ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
#  Exceptions                                                                  #
# --------------------------------------------------------------------------- #

class AuthenticationError(Exception):
    """Raised when a token is missing, malformed, expired, or otherwise invalid."""

    def __init__(self, message: str = "Authentication required"):
        self.message = message
        super().__init__(message)


# --------------------------------------------------------------------------- #
#  Token Creation                                                              #
# --------------------------------------------------------------------------- #

def create_access_token(
    user_id: str,
    username: str,
    role: str,
    secret_key: str,
    expire_minutes: int = 60,
    algorithm: str = _ALGORITHM,
) -> str:
    """Create a signed JWT access token.

    Args:
        user_id: Subject claim (``sub``).
        username: Human-readable login name.
        role: RBAC role embedded in the token.
        secret_key: HMAC signing key.
        expire_minutes: Token lifetime in minutes.
        algorithm: JWT signing algorithm.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "exp": now + timedelta(minutes=expire_minutes),
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_refresh_token(
    user_id: str,
    username: str,
    role: str,
    secret_key: str,
    expire_days: int = 7,
    algorithm: str = _ALGORITHM,
) -> str:
    """Create a signed JWT refresh token.

    Args:
        user_id: Subject claim (``sub``).
        username: Human-readable login name.
        role: RBAC role embedded in the token.
        secret_key: HMAC signing key.
        expire_days: Token lifetime in days.
        algorithm: JWT signing algorithm.

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "refresh",
        "exp": now + timedelta(days=expire_days),
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_token_pair(
    user_id: str,
    username: str,
    role: str,
    secret_key: str,
    access_expire_minutes: int = 60,
    refresh_expire_days: int = 7,
    algorithm: str = _ALGORITHM,
) -> TokenPair:
    """Create an access + refresh token pair suitable for login responses.

    Args:
        user_id: Subject claim (``sub``).
        username: Human-readable login name.
        role: RBAC role embedded in both tokens.
        secret_key: HMAC signing key.
        access_expire_minutes: Access token lifetime in minutes.
        refresh_expire_days: Refresh token lifetime in days.
        algorithm: JWT signing algorithm.

    Returns:
        A :class:`TokenPair` with both tokens and expiry metadata.
    """
    access = create_access_token(
        user_id, username, role, secret_key,
        expire_minutes=access_expire_minutes,
        algorithm=algorithm,
    )
    refresh = create_refresh_token(
        user_id, username, role, secret_key,
        expire_days=refresh_expire_days,
        algorithm=algorithm,
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=access_expire_minutes * 60,
    )


# --------------------------------------------------------------------------- #
#  Token Decoding / Validation                                                 #
# --------------------------------------------------------------------------- #

def decode_token(
    token: str,
    secret_key: str,
    expected_type: str = "access",
    algorithm: str = _ALGORITHM,
) -> TokenPayload:
    """Decode and validate a JWT token.

    Checks signature, expiration, and that the ``type`` claim matches
    *expected_type*.

    Args:
        token: Raw JWT string.
        secret_key: HMAC key used to verify the signature.
        expected_type: Expected value of the ``type`` claim
            (``"access"`` or ``"refresh"``).
        algorithm: JWT signing algorithm.

    Returns:
        Parsed :class:`TokenPayload`.

    Raises:
        AuthenticationError: On any validation failure (expired, bad
            signature, wrong type, malformed payload, etc.).
    """
    try:
        raw = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as exc:
        logger.warning("jwt.decode_failed", error=str(exc))
        raise AuthenticationError(f"Invalid token: {exc}") from exc

    # Validate the type claim.
    token_type = raw.get("type")
    if token_type != expected_type:
        raise AuthenticationError(
            f"Invalid token type: expected '{expected_type}', got '{token_type}'"
        )

    # Ensure all required claims are present.
    required = ("sub", "username", "role", "type", "exp", "iat", "jti")
    missing = [k for k in required if k not in raw]
    if missing:
        raise AuthenticationError(f"Token missing required claims: {missing}")

    return TokenPayload(
        sub=raw["sub"],
        username=raw["username"],
        role=raw["role"],
        type=raw["type"],
        exp=datetime.fromtimestamp(raw["exp"], tz=timezone.utc),
        iat=datetime.fromtimestamp(raw["iat"], tz=timezone.utc),
        jti=raw["jti"],
    )


# --------------------------------------------------------------------------- #
#  Password Hashing                                                            #
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return _pwd_ctx.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify *plain_password* against a bcrypt *hashed_password*."""
    return _pwd_ctx.verify(plain_password, hashed_password)
