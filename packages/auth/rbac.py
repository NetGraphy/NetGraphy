"""Role-based access control (RBAC) with group-based per-model permissions.

Two layers of authorization:

1. **Role-based** — hierarchical roles (viewer → editor → operator → admin →
   superadmin) grant broad action categories. This is the baseline.

2. **Object permissions** — granular per-model read/create/update/delete
   permissions assigned to groups. Users inherit permissions from all groups
   they belong to. Object permissions are additive (union of all groups).

Permission resolution order:
1. Superadmin bypasses all checks.
2. Check role-based permissions (broad action:resource patterns).
3. Check group-based object permissions (per-model granular access).
"""

from __future__ import annotations

import fnmatch
from typing import Any, Mapping

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
        "manage:iac:*",
    },
    "admin": {
        "manage:user:*",
        "manage:group:*",
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
    """Check whether a single *granted* permission covers the required action + resource."""
    # Global wildcard — superadmin.
    if granted == "*":
        return True

    required = f"{required_action}:{required_resource}"
    return fnmatch.fnmatch(required, granted)


# --------------------------------------------------------------------------- #
#  PermissionChecker                                                           #
# --------------------------------------------------------------------------- #

class PermissionChecker:
    """Checks an AuthContext against role-based and group-based permissions.

    Role-based permissions provide the baseline. Group-based object
    permissions add granular per-model control. Both are checked — if
    either grants access, the request is allowed.

    Usage::

        checker = PermissionChecker()
        checker.require_permission(auth_ctx, "read", "node:Device")
        checker.require_object_permission(auth_ctx, "read", "Device")
    """

    # ---------------------------------------------------------------------- #
    #  Role-based checks                                                     #
    # ---------------------------------------------------------------------- #

    def check_permission(
        self,
        auth_context: AuthContext,
        action: str,
        resource: str,
    ) -> bool:
        """Return True if the context's role grants action on resource.

        Also checks group-based object permissions as a fallback.
        """
        # Superadmin bypasses everything
        if auth_context.role == "superadmin":
            return True

        # Check role-based permissions
        role_perms = get_role_permissions(auth_context.role)
        if any(_permission_matches(perm, action, resource) for perm in role_perms):
            return True

        # Check group-based object permissions
        return self._check_object_permissions(auth_context, action, resource)

    def require_permission(
        self,
        auth_context: AuthContext,
        action: str,
        resource: str,
    ) -> None:
        """Assert that the context has the required permission.

        Raises AuthorizationError when access is denied.
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

    # ---------------------------------------------------------------------- #
    #  Object permission checks (group-based, per-model)                     #
    # ---------------------------------------------------------------------- #

    def _check_object_permissions(
        self,
        auth_context: AuthContext,
        action: str,
        resource: str,
    ) -> bool:
        """Check if any group-based object permission grants the action.

        Object permissions are structured as:
        {
            "can_read": bool, "can_create": bool, "can_update": bool, "can_delete": bool,
            "object_types": ["Device", "Interface"],  # empty = all
            "can_execute_jobs": bool,
            "allowed_jobs": ["job_name"],  # empty = all
        }
        """
        if not auth_context.object_permissions:
            return False

        # Parse action and resource
        # resource format: "node:Device", "edge:ConnectsTo", "job:backup", "iac", etc.
        parts = resource.split(":", 1)
        resource_type = parts[0] if parts else ""
        resource_name = parts[1] if len(parts) > 1 else ""

        for perm in auth_context.object_permissions:
            if not perm.get("enabled", True):
                continue

            # Job execution check
            if action == "execute" and resource_type == "job":
                if perm.get("can_execute_jobs"):
                    allowed = perm.get("allowed_jobs", [])
                    if not allowed or resource_name in allowed or "*" in allowed:
                        return True
                continue

            # Node/edge CRUD checks
            if resource_type in ("node", "edge"):
                object_types = perm.get("object_types", [])
                # Empty object_types means all types
                type_matches = not object_types or resource_name in object_types

                if not type_matches:
                    continue

                if action == "read" and perm.get("can_read"):
                    return True
                if action == "write" and (perm.get("can_create") or perm.get("can_update")):
                    return True
                if action == "delete" and perm.get("can_delete"):
                    return True

        return False

    def check_object_permission(
        self,
        auth_context: AuthContext,
        action: str,
        node_type: str,
    ) -> bool:
        """Check per-model object permission for a specific node type.

        Args:
            action: One of "read", "create", "update", "delete".
            node_type: The node type name (e.g., "Device").
        """
        if auth_context.role == "superadmin":
            return True

        # Map action to permission field
        action_map = {
            "read": "can_read",
            "create": "can_create",
            "update": "can_update",
            "delete": "can_delete",
        }
        perm_field = action_map.get(action)
        if not perm_field:
            return False

        for perm in auth_context.object_permissions:
            if not perm.get("enabled", True):
                continue
            object_types = perm.get("object_types", [])
            if object_types and node_type not in object_types:
                continue
            if perm.get(perm_field):
                return True

        return False

    def check_job_permission(
        self,
        auth_context: AuthContext,
        job_name: str,
    ) -> bool:
        """Check if the user can execute a specific job."""
        if auth_context.role == "superadmin":
            return True

        # Check role-based
        role_perms = get_role_permissions(auth_context.role)
        if any(_permission_matches(p, "execute", f"job:{job_name}") for p in role_perms):
            return True

        # Check group-based
        for perm in auth_context.object_permissions:
            if not perm.get("enabled", True):
                continue
            if perm.get("can_execute_jobs"):
                allowed = perm.get("allowed_jobs", [])
                if not allowed or job_name in allowed:
                    return True

        return False

    @staticmethod
    def get_role_permissions(role: str) -> set[str]:
        """Convenience proxy for the module-level get_role_permissions."""
        return get_role_permissions(role)
