"""Authentication backends — local, LDAP, and SSO.

Each backend implements the same interface: authenticate(username, password)
returns user data or None. The auth router tries backends in order until
one succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


@dataclass
class AuthResult:
    """Result of a backend authentication attempt."""
    success: bool
    user_data: dict[str, Any] = field(default_factory=dict)
    groups: list[str] = field(default_factory=list)
    backend: str = "local"
    error: str = ""


class LocalBackend:
    """Local database authentication using bcrypt-hashed passwords."""

    async def authenticate(
        self,
        username: str,
        password: str,
        driver: Neo4jDriver,
    ) -> AuthResult:
        from packages.auth.jwt import verify_password

        result = await driver.execute_read(
            "MATCH (u:_User {username: $username}) RETURN u",
            {"username": username},
        )
        if not result.rows:
            return AuthResult(success=False, error="User not found")

        user = result.rows[0]["u"]
        if not user.get("is_active", False):
            return AuthResult(success=False, error="Account disabled")

        if not verify_password(password, user.get("password_hash", "")):
            return AuthResult(success=False, error="Invalid password")

        # Load group membership
        groups_result = await driver.execute_read(
            "MATCH (u:_User {id: $id})-[:MEMBER_OF]->(g:_Group) RETURN g.name as name",
            {"id": user["id"]},
        )
        groups = [row["name"] for row in groups_result.rows]

        return AuthResult(
            success=True,
            user_data=user,
            groups=groups,
            backend="local",
        )


class LDAPBackend:
    """LDAP/Active Directory authentication backend.

    Authenticates against an LDAP directory, maps LDAP groups to NetGraphy
    groups, and auto-creates local user records on first login.

    Requires the ``ldap3`` package (optional dependency).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def authenticate(
        self,
        username: str,
        password: str,
        driver: Neo4jDriver,
    ) -> AuthResult:
        if not self.config.get("enabled"):
            return AuthResult(success=False, error="LDAP not enabled")

        try:
            import ldap3
        except ImportError:
            logger.error("ldap3 package not installed — LDAP authentication unavailable")
            return AuthResult(success=False, error="LDAP package not installed")

        server_uri = self.config.get("server_uri", "")
        bind_dn = self.config.get("bind_dn", "")
        bind_password = self.config.get("bind_password", "")
        user_search_base = self.config.get("user_search_base", "")
        user_search_filter = self.config.get("user_search_filter", "(sAMAccountName={username})")
        start_tls = self.config.get("start_tls", False)

        try:
            # Connect to LDAP server
            server = ldap3.Server(server_uri, get_info=ldap3.ALL, use_ssl=server_uri.startswith("ldaps"))
            conn = ldap3.Connection(
                server,
                user=bind_dn,
                password=bind_password,
                auto_bind=True,
            )

            if start_tls:
                conn.start_tls()

            # Search for user
            search_filter = user_search_filter.replace("{username}", username)
            conn.search(
                search_base=user_search_base,
                search_filter=search_filter,
                attributes=ldap3.ALL_ATTRIBUTES,
            )

            if not conn.entries:
                conn.unbind()
                return AuthResult(success=False, error="User not found in LDAP")

            user_entry = conn.entries[0]
            user_dn = str(user_entry.entry_dn)

            # Verify password by binding as the user
            user_conn = ldap3.Connection(server, user=user_dn, password=password)
            if not user_conn.bind():
                conn.unbind()
                return AuthResult(success=False, error="Invalid LDAP password")
            user_conn.unbind()

            # Check required group membership
            require_group = self.config.get("require_group", "")
            if require_group:
                member_of = [str(g) for g in user_entry.get(self.config.get("attr_groups", "memberOf"), [])]
                if require_group not in member_of:
                    conn.unbind()
                    return AuthResult(success=False, error="User not in required LDAP group")

            # Extract user attributes
            attr_map = {
                "username": self.config.get("attr_username", "sAMAccountName"),
                "email": self.config.get("attr_email", "mail"),
                "first_name": self.config.get("attr_first_name", "givenName"),
                "last_name": self.config.get("attr_last_name", "sn"),
            }

            user_data = {}
            for key, attr in attr_map.items():
                val = user_entry.get(attr, None)
                user_data[key] = str(val) if val else ""

            # Extract LDAP groups
            ldap_groups = [str(g) for g in user_entry.get(self.config.get("attr_groups", "memberOf"), [])]

            # Map LDAP groups to role
            role = self.config.get("default_role", "viewer")
            group_role_mapping = self.config.get("group_role_mapping", {})
            for group_dn, mapped_role in group_role_mapping.items():
                if group_dn in ldap_groups:
                    role = mapped_role
                    break

            conn.unbind()

            # Auto-create or update local user
            if self.config.get("auto_create_user", True):
                user_data = await self._ensure_local_user(
                    driver, user_data, role, ldap_groups
                )

            return AuthResult(
                success=True,
                user_data=user_data,
                groups=[g.split(",")[0].split("=")[-1] for g in ldap_groups],
                backend="ldap",
            )

        except Exception as e:
            logger.error("LDAP authentication failed", error=str(e), username=username)
            return AuthResult(success=False, error=f"LDAP error: {e}")

    async def _ensure_local_user(
        self,
        driver: Neo4jDriver,
        user_data: dict[str, Any],
        role: str,
        ldap_groups: list[str],
    ) -> dict[str, Any]:
        """Create or update a local _User record for an LDAP-authenticated user."""
        import uuid
        from datetime import datetime, timezone

        username = user_data.get("username", "")
        now = datetime.now(timezone.utc).isoformat()

        # Check if user exists
        result = await driver.execute_read(
            "MATCH (u:_User {username: $username}) RETURN u",
            {"username": username},
        )

        if result.rows:
            # Update existing user
            user = result.rows[0]["u"]
            await driver.execute_write(
                "MATCH (u:_User {username: $username}) "
                "SET u.email = $email, u.first_name = $first_name, "
                "    u.last_name = $last_name, u.role = $role, "
                "    u.auth_backend = 'ldap', u.updated_at = $now",
                {
                    "username": username,
                    "email": user_data.get("email", ""),
                    "first_name": user_data.get("first_name", ""),
                    "last_name": user_data.get("last_name", ""),
                    "role": role,
                    "now": now,
                },
            )
            user.update(user_data)
            user["role"] = role
            return user
        else:
            # Create new user (no password — LDAP auth only)
            user_id = str(uuid.uuid4())
            props = {
                "id": user_id,
                "username": username,
                "email": user_data.get("email", ""),
                "first_name": user_data.get("first_name", ""),
                "last_name": user_data.get("last_name", ""),
                "password_hash": "",  # No local password — LDAP only
                "role": role,
                "is_active": True,
                "auth_backend": "ldap",
                "created_at": now,
                "updated_at": now,
            }
            await driver.execute_write(
                "CREATE (u:_User $props) RETURN u",
                {"props": props},
            )
            props["id"] = user_id
            return props


class SSOBackend:
    """SSO (SAML/OIDC) authentication backend.

    Validates SSO assertions/tokens and maps external identity to local
    users. Full SSO flow (redirects, callbacks) is handled by the auth router.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def validate_sso_response(
        self,
        response_data: dict[str, Any],
        driver: Neo4jDriver,
    ) -> AuthResult:
        """Validate an SSO response (SAML assertion or OIDC token).

        This is called after the SSO callback endpoint receives the response
        from the identity provider.
        """
        if not self.config.get("enabled"):
            return AuthResult(success=False, error="SSO not enabled")

        provider_type = self.config.get("provider_type", "none")

        if provider_type == "oidc":
            return await self._validate_oidc(response_data, driver)
        elif provider_type == "saml":
            return await self._validate_saml(response_data, driver)
        else:
            return AuthResult(success=False, error=f"Unknown SSO provider: {provider_type}")

    async def _validate_oidc(
        self,
        token_data: dict[str, Any],
        driver: Neo4jDriver,
    ) -> AuthResult:
        """Validate an OIDC ID token and extract user claims."""
        # In production, this would verify the JWT signature against the IdP's JWKS
        # For now, we trust validated claims passed from the callback handler

        username = token_data.get("preferred_username") or token_data.get("sub", "")
        email = token_data.get("email", "")
        first_name = token_data.get("given_name", "")
        last_name = token_data.get("family_name", "")
        groups = token_data.get(self.config.get("group_claim", "groups"), [])

        if not username:
            return AuthResult(success=False, error="No username in OIDC claims")

        # Map groups to role
        role = self.config.get("default_role", "viewer")
        for group_name, mapped_role in self.config.get("group_role_mapping", {}).items():
            if group_name in groups:
                role = mapped_role
                break

        # Ensure local user
        if self.config.get("auto_create_user", True):
            ldap_backend = LDAPBackend({})
            user_data = await ldap_backend._ensure_local_user(
                driver,
                {"username": username, "email": email, "first_name": first_name, "last_name": last_name},
                role,
                [],
            )
        else:
            result = await driver.execute_read(
                "MATCH (u:_User {username: $username}) RETURN u",
                {"username": username},
            )
            user_data = result.rows[0]["u"] if result.rows else {}

        return AuthResult(
            success=bool(user_data),
            user_data=user_data,
            groups=groups if isinstance(groups, list) else [],
            backend="oidc",
        )

    async def _validate_saml(
        self,
        saml_data: dict[str, Any],
        driver: Neo4jDriver,
    ) -> AuthResult:
        """Validate a SAML assertion. Follows same pattern as OIDC."""
        # SAML assertion would be validated using pysaml2 or similar
        # For the framework, we extract attributes from the validated assertion
        username = saml_data.get("NameID", "")
        attributes = saml_data.get("Attributes", {})
        email = attributes.get("email", [""])[0] if isinstance(attributes.get("email"), list) else attributes.get("email", "")
        groups = attributes.get(self.config.get("group_claim", "groups"), [])

        if not username:
            return AuthResult(success=False, error="No NameID in SAML assertion")

        role = self.config.get("default_role", "viewer")
        for group_name, mapped_role in self.config.get("group_role_mapping", {}).items():
            if group_name in groups:
                role = mapped_role
                break

        return AuthResult(
            success=True,
            user_data={"username": username, "email": email},
            groups=groups if isinstance(groups, list) else [],
            backend="saml",
        )
