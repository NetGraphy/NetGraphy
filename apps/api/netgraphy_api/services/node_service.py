"""Node service -- domain orchestration layer for node CRUD.

Coordinates schema validation, RBAC authorization, repository persistence,
provenance injection, and event emission for every node operation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from apps.api.netgraphy_api.exceptions import (
    NodeNotFoundError,
    SchemaValidationError,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.repositories.node_repository import NodeRepository
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger(__name__)


class NodeService:
    """Orchestrates node lifecycle operations.

    Every public method follows the same pattern:
    validate -> authorize -> execute -> audit -> emit.
    """

    def __init__(
        self,
        repo: NodeRepository,
        registry: SchemaRegistry,
        events: EventBus,
        rbac: PermissionChecker,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._events = events
        self._rbac = rbac

    # ------------------------------------------------------------------ #
    #  Create                                                              #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        node_type: str,
        properties: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Create a new node of *node_type* with the given *properties*.

        Steps:
        1. Require the node type exists in the schema registry.
        2. Validate properties against the schema definition.
        3. Authorize the actor for write access.
        4. Inject provenance metadata.
        5. Persist via the node repository.
        6. Emit a node-created event.
        """
        log = logger.bind(node_type=node_type, actor=actor.user_id)

        # 1. Schema existence
        self._registry.require_node_type(node_type)

        # 2. Property validation
        errors = self._registry.validate_node_properties(node_type, properties)
        if errors:
            log.warning("node.validation_failed", errors=errors)
            raise SchemaValidationError(errors)

        # 3. Authorization
        self._rbac.require_permission(actor, "write", f"node:{node_type}")

        # 4. Lifecycle & provenance metadata (matches mixin attribute names)
        now = datetime.now(timezone.utc).isoformat()
        properties["created_by"] = actor.user_id
        properties["created_at"] = now
        properties["updated_by"] = actor.user_id
        properties["updated_at"] = now

        # 5. Persist
        node = await self._repo.create_node(node_type, properties)
        log.info("node.created", node_id=node["id"])

        # 6. Audit + event
        await self._persist_audit("create", node_type, node["id"], actor)
        await self._events.emit_node_created(node_type, node["id"], actor=actor.user_id)

        return node

    # ------------------------------------------------------------------ #
    #  Read                                                                #
    # ------------------------------------------------------------------ #

    async def get(
        self,
        node_type: str,
        node_id: str,
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Retrieve a single node by type and ID."""
        # 1. Authorization
        self._rbac.require_permission(actor, "read", f"node:{node_type}")

        # 2. Fetch
        node = await self._repo.get_node(node_type, node_id)

        # 3. Existence
        if not node:
            raise NodeNotFoundError(node_type, node_id)

        return node

    # ------------------------------------------------------------------ #
    #  Update                                                              #
    # ------------------------------------------------------------------ #

    async def update(
        self,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Update an existing node's properties (partial update).

        Steps:
        1. Require the node type exists in the schema registry.
        2. Validate the supplied properties.
        3. Authorize write access.
        4. Ensure the target node exists.
        5. Inject update provenance.
        6. Persist the update.
        7. Emit a node-updated event.
        """
        log = logger.bind(node_type=node_type, node_id=node_id, actor=actor.user_id)

        # 1. Schema existence
        self._registry.require_node_type(node_type)

        # 2. Validate (partial -- only the properties being set)
        errors = self._registry.validate_node_properties(node_type, properties)
        if errors:
            log.warning("node.validation_failed", errors=errors)
            raise SchemaValidationError(errors)

        # 3. Authorization
        self._rbac.require_permission(actor, "write", f"node:{node_type}")

        # 4. Existence check
        existing = await self._repo.get_node(node_type, node_id)
        if not existing:
            raise NodeNotFoundError(node_type, node_id)

        # 5. Lifecycle metadata
        properties["updated_by"] = actor.user_id
        properties["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 6. Persist
        node = await self._repo.update_node(node_type, node_id, properties)
        if not node:
            raise NodeNotFoundError(node_type, node_id)

        log.info("node.updated", node_id=node_id)

        # 7. Audit + event
        await self._persist_audit("update", node_type, node_id, actor)
        await self._events.emit_node_updated(
            node_type, node_id, changes=properties, actor=actor.user_id,
        )

        return node

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    async def delete(
        self,
        node_type: str,
        node_id: str,
        actor: AuthContext,
    ) -> None:
        """Delete a node and all its relationships.

        Steps:
        1. Authorize write access.
        2. Ensure the target node exists.
        3. Delete via the repository.
        4. Emit a node-deleted event.
        """
        log = logger.bind(node_type=node_type, node_id=node_id, actor=actor.user_id)

        # 1. Authorization
        self._rbac.require_permission(actor, "write", f"node:{node_type}")

        # 2. Existence check
        existing = await self._repo.get_node(node_type, node_id)
        if not existing:
            raise NodeNotFoundError(node_type, node_id)

        # 3. Delete
        deleted = await self._repo.delete_node(node_type, node_id)
        if not deleted:
            raise NodeNotFoundError(node_type, node_id)

        log.info("node.deleted", node_id=node_id)

        # 4. Audit + event
        await self._persist_audit("delete", node_type, node_id, actor)
        await self._events.emit_node_deleted(node_type, node_id, actor=actor.user_id)

    # ------------------------------------------------------------------ #
    #  List                                                                #
    # ------------------------------------------------------------------ #

    async def list(
        self,
        node_type: str,
        filters: dict[str, Any],
        page: int,
        page_size: int,
        sort: str | None,
        actor: AuthContext,
    ) -> dict[str, Any]:
        """List nodes of a given type with filtering and pagination.

        Returns a dict with ``items``, ``total_count``, ``page``, and
        ``page_size`` keys.
        """
        # 1. Authorization
        self._rbac.require_permission(actor, "read", f"node:{node_type}")

        # 2. Fetch paginated results
        result = await self._repo.list_nodes(
            node_type,
            filters=filters,
            page=page,
            page_size=page_size,
            sort=sort,
        )

        return {
            "items": result["items"],
            "total_count": result["total_count"],
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------ #
    #  Relationships                                                       #
    # ------------------------------------------------------------------ #

    async def get_relationships(
        self,
        node_type: str,
        node_id: str,
        edge_type: str | None,
        actor: AuthContext,
    ) -> list[dict[str, Any]]:
        """Return edges and related nodes for a given node.

        Optionally filtered by *edge_type*.
        """
        # 1. Authorization
        self._rbac.require_permission(actor, "read", f"node:{node_type}")

        # 2. Existence check
        existing = await self._repo.get_node(node_type, node_id)
        if not existing:
            raise NodeNotFoundError(node_type, node_id)

        # 3. Fetch relationships
        return await self._repo.get_relationships(node_id, edge_type=edge_type)

    # ------------------------------------------------------------------ #
    #  Audit persistence                                                   #
    # ------------------------------------------------------------------ #

    async def _persist_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        actor: AuthContext,
    ) -> None:
        """Write an _AuditEvent node to Neo4j."""
        import uuid

        props = {
            "id": str(uuid.uuid4()),
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor": actor.user_id,
            "actor_username": actor.username,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._repo._driver.execute_write(
                "CREATE (e:_AuditEvent $props) RETURN e",
                {"props": props},
            )
        except Exception:
            logger.warning("audit.persist_failed", action=action, resource_id=resource_id)
