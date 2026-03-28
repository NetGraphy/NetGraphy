"""Edge service -- domain orchestration layer for edge (relationship) CRUD.

Coordinates schema validation, endpoint-type validation, RBAC authorization,
repository persistence, and event emission for every edge operation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from apps.api.netgraphy_api.exceptions import (
    EdgeNotFoundError,
    SchemaValidationError,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.repositories.edge_repository import EdgeRepository
from packages.graph_db.repositories.node_repository import NodeRepository
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger(__name__)


class EdgeService:
    """Orchestrates edge lifecycle operations.

    Every public method follows the pattern:
    validate -> authorize -> execute -> audit -> emit.
    """

    def __init__(
        self,
        repo: EdgeRepository,
        node_repo: NodeRepository,
        registry: SchemaRegistry,
        events: EventBus,
        rbac: PermissionChecker,
    ) -> None:
        self._repo = repo
        self._node_repo = node_repo
        self._registry = registry
        self._events = events
        self._rbac = rbac

    # ------------------------------------------------------------------ #
    #  Create                                                              #
    # ------------------------------------------------------------------ #

    async def create(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Create a new edge between two nodes.

        Steps:
        1. Require the edge type exists in the schema registry.
        2. Validate that source and target nodes exist and their types
           are allowed by the edge definition.
        3. Validate edge properties against the schema.
        4. Authorize write access.
        5. Inject provenance metadata.
        6. Persist via the edge repository (which enforces cardinality).
        7. Emit an edge-created event.
        """
        log = logger.bind(edge_type=edge_type, source_id=source_id,
                          target_id=target_id, actor=actor.user_id)

        # 1. Schema existence
        edge_def = self._registry.require_edge_type(edge_type)

        # 2. Validate source/target node existence and type compatibility
        await self._validate_endpoints(edge_def, source_id, target_id)

        # 3. Property validation
        errors = self._registry.validate_edge_properties(edge_type, properties)
        if errors:
            log.warning("edge.validation_failed", errors=errors)
            raise SchemaValidationError(errors)

        # 4. Authorization
        self._rbac.require_permission(actor, "write", f"edge:{edge_type}")

        # 5. Provenance
        now = datetime.now(timezone.utc).isoformat()
        properties["_created_by"] = actor.user_id
        properties["_created_at"] = now
        properties["_source"] = "manual"

        # 6. Persist (repo handles cardinality enforcement)
        edge = await self._repo.create_edge(edge_type, source_id, target_id, properties)
        log.info("edge.created", edge_id=edge["id"])

        # 7. Event
        await self._events.emit_edge_created(
            edge_type, edge["id"], source_id, target_id, actor=actor.user_id,
        )

        return edge

    # ------------------------------------------------------------------ #
    #  Update                                                              #
    # ------------------------------------------------------------------ #

    async def update(
        self,
        edge_type: str,
        edge_id: str,
        properties: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Update an existing edge's properties.

        Steps:
        1. Require the edge type exists in the schema registry.
        2. Validate the supplied properties.
        3. Authorize write access.
        4. Inject update provenance.
        5. Persist the update.
        6. Emit an edge-updated event (via audit).
        """
        log = logger.bind(edge_type=edge_type, edge_id=edge_id, actor=actor.user_id)

        # 1. Schema existence
        self._registry.require_edge_type(edge_type)

        # 2. Property validation
        errors = self._registry.validate_edge_properties(edge_type, properties)
        if errors:
            log.warning("edge.validation_failed", errors=errors)
            raise SchemaValidationError(errors)

        # 3. Authorization
        self._rbac.require_permission(actor, "write", f"edge:{edge_type}")

        # 4. Provenance
        properties["_updated_by"] = actor.user_id
        properties["_updated_at"] = datetime.now(timezone.utc).isoformat()

        # 5. Persist
        edge = await self._repo.update_edge(edge_type, edge_id, properties)
        if not edge:
            raise EdgeNotFoundError(edge_type, edge_id)

        log.info("edge.updated", edge_id=edge_id)

        # 6. Audit event
        await self._events.emit_audit(
            action="update",
            resource_type="edge",
            resource_id=edge_id,
            actor=actor.user_id,
            changes=properties,
        )

        return edge

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    async def delete(
        self,
        edge_type: str,
        edge_id: str,
        actor: AuthContext,
    ) -> None:
        """Delete an edge by type and ID.

        Steps:
        1. Authorize write access.
        2. Delete via the repository.
        3. Emit an edge-deleted event.
        """
        log = logger.bind(edge_type=edge_type, edge_id=edge_id, actor=actor.user_id)

        # 1. Authorization
        self._rbac.require_permission(actor, "write", f"edge:{edge_type}")

        # 2. Delete
        deleted = await self._repo.delete_edge(edge_type, edge_id)
        if not deleted:
            raise EdgeNotFoundError(edge_type, edge_id)

        log.info("edge.deleted", edge_id=edge_id)

        # 3. Event
        await self._events.emit_edge_deleted(edge_type, edge_id, actor=actor.user_id)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    async def _validate_endpoints(
        self,
        edge_def: Any,
        source_id: str,
        target_id: str,
    ) -> None:
        """Verify that source and target nodes exist and their types match
        the allowed types defined in the edge schema.

        Raises :class:`SchemaValidationError` on mismatch and
        :class:`NodeNotFoundError` (via SchemaValidationError) when a
        node cannot be found.
        """
        errors: list[str] = []

        # Check each allowed source type until we find the node
        source_node: dict[str, Any] | None = None
        for allowed_type in edge_def.source.node_types:
            source_node = await self._node_repo.get_node(allowed_type, source_id)
            if source_node:
                break

        if not source_node:
            errors.append(
                f"Source node '{source_id}' not found among allowed types "
                f"{edge_def.source.node_types}"
            )

        # Check each allowed target type until we find the node
        target_node: dict[str, Any] | None = None
        for allowed_type in edge_def.target.node_types:
            target_node = await self._node_repo.get_node(allowed_type, target_id)
            if target_node:
                break

        if not target_node:
            errors.append(
                f"Target node '{target_id}' not found among allowed types "
                f"{edge_def.target.node_types}"
            )

        if errors:
            raise SchemaValidationError(errors)
