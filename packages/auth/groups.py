"""Group management service — CRUD for groups, membership, and object permissions.

Groups are stored as ``_Group`` nodes in Neo4j. Membership is modeled as
``_User -[:MEMBER_OF]-> _Group`` edges. Object permissions are stored as
``_ObjectPermission`` nodes linked to groups via ``_Group -[:HAS_PERMISSION]-> _ObjectPermission``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


class GroupService:
    """Manages groups, membership, and object permissions in Neo4j."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------ #
    #  Groups CRUD                                                        #
    # ------------------------------------------------------------------ #

    async def list_groups(self) -> list[dict[str, Any]]:
        """List all groups with member counts."""
        result = await self._driver.execute_read(
            "MATCH (g:_Group) "
            "OPTIONAL MATCH (u:_User)-[:MEMBER_OF]->(g) "
            "RETURN g, count(u) as member_count "
            "ORDER BY g.name",
            {},
        )
        groups = []
        for row in result.rows:
            g = row["g"]
            g["member_count"] = row["member_count"]
            groups.append(g)
        return groups

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        """Get a group by ID with members and permissions."""
        result = await self._driver.execute_read(
            "MATCH (g:_Group {id: $id}) "
            "OPTIONAL MATCH (u:_User)-[:MEMBER_OF]->(g) "
            "OPTIONAL MATCH (g)-[:HAS_PERMISSION]->(p:_ObjectPermission) "
            "RETURN g, collect(DISTINCT {id: u.id, username: u.username, role: u.role, "
            "  email: u.email, is_active: u.is_active}) as members, "
            "  collect(DISTINCT p) as permissions",
            {"id": group_id},
        )
        if not result.rows:
            return None

        row = result.rows[0]
        group = row["g"]
        group["members"] = [m for m in row["members"] if m.get("id")]
        group["permissions"] = row["permissions"]
        return group

    async def get_group_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a group by name."""
        result = await self._driver.execute_read(
            "MATCH (g:_Group {name: $name}) RETURN g",
            {"name": name},
        )
        return result.rows[0]["g"] if result.rows else None

    async def create_group(
        self,
        name: str,
        description: str = "",
        created_by: str = "",
    ) -> dict[str, Any]:
        """Create a new group."""
        group_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._driver.execute_write(
            "CREATE (g:_Group {id: $id, name: $name, description: $desc, "
            "  created_at: $now, updated_at: $now, created_by: $created_by}) "
            "RETURN g",
            {
                "id": group_id,
                "name": name,
                "desc": description,
                "now": now,
                "created_by": created_by,
            },
        )
        logger.info("group.created", group_id=group_id, name=name)
        return {"id": group_id, "name": name, "description": description}

    async def update_group(self, group_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update a group's properties."""
        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now

        set_clauses = ", ".join(f"g.{k} = ${k}" for k in updates)
        result = await self._driver.execute_write(
            f"MATCH (g:_Group {{id: $id}}) SET {set_clauses} RETURN g",
            {"id": group_id, **updates},
        )
        return result.rows[0]["g"] if result.rows else None

    async def delete_group(self, group_id: str) -> bool:
        """Delete a group and all its permission relationships."""
        result = await self._driver.execute_write(
            "MATCH (g:_Group {id: $id}) "
            "OPTIONAL MATCH (g)-[:HAS_PERMISSION]->(p:_ObjectPermission) "
            "DETACH DELETE g, p "
            "RETURN count(g) as deleted",
            {"id": group_id},
        )
        return result.rows[0]["deleted"] > 0 if result.rows else False

    # ------------------------------------------------------------------ #
    #  Membership                                                         #
    # ------------------------------------------------------------------ #

    async def add_member(self, group_id: str, user_id: str) -> bool:
        """Add a user to a group."""
        result = await self._driver.execute_write(
            "MATCH (u:_User {id: $user_id}), (g:_Group {id: $group_id}) "
            "MERGE (u)-[:MEMBER_OF]->(g) "
            "RETURN u.username as username",
            {"user_id": user_id, "group_id": group_id},
        )
        if result.rows:
            logger.info("group.member_added", group_id=group_id, user_id=user_id)
            return True
        return False

    async def remove_member(self, group_id: str, user_id: str) -> bool:
        """Remove a user from a group."""
        result = await self._driver.execute_write(
            "MATCH (u:_User {id: $user_id})-[r:MEMBER_OF]->(g:_Group {id: $group_id}) "
            "DELETE r RETURN u.username as username",
            {"user_id": user_id, "group_id": group_id},
        )
        if result.rows:
            logger.info("group.member_removed", group_id=group_id, user_id=user_id)
            return True
        return False

    async def get_user_groups(self, user_id: str) -> list[dict[str, Any]]:
        """Get all groups a user belongs to."""
        result = await self._driver.execute_read(
            "MATCH (u:_User {id: $user_id})-[:MEMBER_OF]->(g:_Group) "
            "RETURN g ORDER BY g.name",
            {"user_id": user_id},
        )
        return [row["g"] for row in result.rows]

    async def get_group_members(self, group_id: str) -> list[dict[str, Any]]:
        """Get all members of a group."""
        result = await self._driver.execute_read(
            "MATCH (u:_User)-[:MEMBER_OF]->(g:_Group {id: $group_id}) "
            "RETURN u ORDER BY u.username",
            {"group_id": group_id},
        )
        return [
            {
                "id": row["u"].get("id"),
                "username": row["u"].get("username"),
                "email": row["u"].get("email"),
                "role": row["u"].get("role"),
                "is_active": row["u"].get("is_active"),
            }
            for row in result.rows
        ]

    # ------------------------------------------------------------------ #
    #  Object Permissions                                                  #
    # ------------------------------------------------------------------ #

    async def create_object_permission(
        self,
        group_id: str,
        permission: dict[str, Any],
    ) -> dict[str, Any]:
        """Create an object permission and link it to a group."""
        import json

        perm_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Serialize list fields for Neo4j
        props = {
            "id": perm_id,
            "name": permission.get("name", ""),
            "description": permission.get("description", ""),
            "enabled": permission.get("enabled", True),
            "can_read": permission.get("can_read", False),
            "can_create": permission.get("can_create", False),
            "can_update": permission.get("can_update", False),
            "can_delete": permission.get("can_delete", False),
            "object_types": json.dumps(permission.get("object_types", [])),
            "can_execute_jobs": permission.get("can_execute_jobs", False),
            "allowed_jobs": json.dumps(permission.get("allowed_jobs", [])),
            "created_at": now,
        }

        await self._driver.execute_write(
            "MATCH (g:_Group {id: $group_id}) "
            "CREATE (p:_ObjectPermission $props) "
            "CREATE (g)-[:HAS_PERMISSION]->(p) "
            "RETURN p",
            {"group_id": group_id, "props": props},
        )
        logger.info("permission.created", perm_id=perm_id, group_id=group_id)
        return props

    async def update_object_permission(
        self,
        perm_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update an object permission."""
        import json

        # Serialize lists
        for field in ["object_types", "allowed_jobs"]:
            if field in updates and isinstance(updates[field], list):
                updates[field] = json.dumps(updates[field])

        set_clauses = ", ".join(f"p.{k} = ${k}" for k in updates)
        result = await self._driver.execute_write(
            f"MATCH (p:_ObjectPermission {{id: $id}}) SET {set_clauses} RETURN p",
            {"id": perm_id, **updates},
        )
        return result.rows[0]["p"] if result.rows else None

    async def delete_object_permission(self, perm_id: str) -> bool:
        """Delete an object permission."""
        result = await self._driver.execute_write(
            "MATCH (p:_ObjectPermission {id: $id}) DETACH DELETE p "
            "RETURN count(p) as deleted",
            {"id": perm_id},
        )
        return result.rows[0]["deleted"] > 0 if result.rows else False

    async def get_group_permissions(self, group_id: str) -> list[dict[str, Any]]:
        """Get all object permissions for a group."""
        import json

        result = await self._driver.execute_read(
            "MATCH (g:_Group {id: $group_id})-[:HAS_PERMISSION]->(p:_ObjectPermission) "
            "RETURN p ORDER BY p.name",
            {"group_id": group_id},
        )
        perms = []
        for row in result.rows:
            p = row["p"]
            # Deserialize list fields
            for field in ["object_types", "allowed_jobs"]:
                val = p.get(field, "[]")
                if isinstance(val, str):
                    try:
                        p[field] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        p[field] = []
            perms.append(p)
        return perms

    async def get_user_object_permissions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all object permissions for a user (via group membership).

        Returns the union of all permissions from all groups the user belongs to.
        """
        import json

        result = await self._driver.execute_read(
            "MATCH (u:_User {id: $user_id})-[:MEMBER_OF]->(g:_Group)"
            "-[:HAS_PERMISSION]->(p:_ObjectPermission) "
            "WHERE p.enabled = true "
            "RETURN DISTINCT p",
            {"user_id": user_id},
        )
        perms = []
        for row in result.rows:
            p = row["p"]
            for field in ["object_types", "allowed_jobs"]:
                val = p.get(field, "[]")
                if isinstance(val, str):
                    try:
                        p[field] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        p[field] = []
            perms.append(p)
        return perms
