"""Role-based access control (RBAC) with hierarchical permission inheritance.

Roles form a strict hierarchy — each higher role inherits every permission
from the roles below it.  The ``PermissionChecker`` resolves wildcard
patterns (``read:node:*``) against concrete resource identifiers
(``read:node:Device``).
"""

from __future__ import annotations

import fnmatch
from typing import Mapping

import structlog

from packages.auth.models import AuthContext

logger = structlog.get_logger()


# --------------------------------------------------------------------------- #
#  Role hierarchy and permission sets                                          #
# --------------------------------------------------------------------------- #

# Permissions granted *directly* at each tier (not including inherited).
_ROLE_OWN_PERMISSIONS: Mapping[str, set[str]] = {
    "viewer": {
        "read:node:*",
        "read:edge:*",
        "read:query:*",
        "read:schema:*",
    },
    "editor": {
        "write:node:*",
        "write:edge:*",
        "execute:query:*",
    },
    "operator": {
        "execute:job:*",
        "manage:sync:*",
        "manage:parser:*",
    },
    "admin": {
        "manage:user:*",
        "manage:role:*",
        "manage:schema:*",
        "execute:cypher",
    },
    "superadmin": {
        "*",
    },
}

# Ordered from least to most privileged — each role inherits everything below.
_ROLE_ORDER: list[str] = ["viewer", "editor", "operator", "admin", "superadmin"]


class AuthorizationError(Exception):
    """Raised when the authenticated user lacks a required permission."""

    def __init__(self, action: str = "", resource: str = ""):
        if action and resource:
            msg = f"Permission denied: {action} on {resource}"
        else:
            msg = "Insufficient permissions"
        self.message = msg
        super().__init__(msg)


# --------------------------------------------------------------------------- #
#  Permission resolution                                                       #
# --------------------------------------------------------------------------- #

def get_role_permissions(role: str) -> set[str]:
    """Return the full permission set for *role*, including inherited ones.

    Args:
        role: One of the recognised role names.

    Returns:
        A :class:`set` of permission strings.  For ``superadmin`` this
        contains the single wildcard ``"*"``.

    Raises:
        ValueError: If *role* is not a known role.
    """
    if role not in _ROLE_ORDER:
        raise ValueError(f"Unknown role: '{role}'")

    permissions: set[str] = set()
    for r in _ROLE_ORDER:
        permissions |= _ROLE_OWN_PERMISSIONS[r]
        if r == role:
            break
    return permissions


def _permission_matches(granted: str, required_action: str, required_resource: str) -> bool:
    """Check whether a single *granted* permission covers the required action + resource.

    The ``granted`` string is in the form ``"action:resource_type:pattern"``
    (e.g. ``"read:node:*"``), a bare ``"action:resource"`` (e.g.
    ``"execute:cypher"``), or the global wildcard ``"*"``.
    """
    # Global wildcard — superadmin.
    if granted == "*":
        return True

    required = f"{required_action}:{required_resource}"
    # fnmatch handles the ``*`` glob in e.g. ``read:node:*``.
    return fnmatch.fnmatch(required, granted)


# --------------------------------------------------------------------------- #
#  PermissionChecker                                                           #
# --------------------------------------------------------------------------- #

class PermissionChecker:
    """Stateless helper that checks an :class:`AuthContext` against the
    role-permission hierarchy.

    Usage::

        checker = PermissionChecker()
        if checker.check_permission(auth_ctx, "read", "node:Device"):
            ...
        checker.require_permission(auth_ctx, "write", "edge:ConnectsTo")
    """

    # ---------------------------------------------------------------------- #
    #  Public API                                                             #
    # ---------------------------------------------------------------------- #

    def check_permission(
        self,
        auth_context: AuthContext,
        action: str,
        resource: str,
    ) -> bool:
        """Return ``True`` if the context's role grants *action* on *resource*.

        Permission matching supports wildcards: a granted permission of
        ``read:node:*`` will match a required ``action="read"`` /
        ``resource="node:Device"``.

        Args:
            auth_context: The current request's authentication context.
            action: The action verb (e.g. ``"read"``, ``"write"``,
                ``"execute"``, ``"manage"``).
            resource: The resource path (e.g. ``"node:Device"``,
                ``"edge:ConnectsTo"``, ``"cypher"``).

        Returns:
            ``True`` when the permission is granted, ``False`` otherwise.
        """
        role_perms = get_role_permissions(auth_context.role)
        return any(
            _permission_matches(perm, action, resource) for perm in role_perms
        )

    def require_permission(
        self,
        auth_context: AuthContext,
        action: str,
        resource: str,
    ) -> None:
        """Assert that the context has the required permission.

        Delegates to :meth:`check_permission` and raises
        :class:`AuthorizationError` when access is denied.

        Args:
            auth_context: The current request's authentication context.
            action: The action verb.
            resource: The resource path.

        Raises:
            AuthorizationError: If the permission is not granted.
        """
        if not self.check_permission(auth_context, action, resource):
            logger.warning(
                "rbac.permission_denied",
                user_id=auth_context.user_id,
                role=auth_context.role,
                action=action,
                resource=resource,
            )
            raise AuthorizationError(action=action, resource=resource)

    @staticmethod
    def get_role_permissions(role: str) -> set[str]:
        """Convenience proxy for the module-level :func:`get_role_permissions`."""
        return get_role_permissions(role)
