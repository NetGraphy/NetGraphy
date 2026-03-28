"""Schema service -- domain orchestration for schema inspection and migration.

Handles schema validation, migration application, and Neo4j index/constraint
management driven by the schema registry.
"""

from __future__ import annotations

from typing import Any

import structlog

from apps.api.netgraphy_api.exceptions import (
    SchemaValidationError,
    SchemaMigrationError,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger(__name__)


class SchemaService:
    """Orchestrates schema operations: validation, migration, and index management."""

    def __init__(
        self,
        registry: SchemaRegistry,
        driver: Neo4jDriver,
        events: EventBus,
        rbac: PermissionChecker,
    ) -> None:
        self._registry = registry
        self._driver = driver
        self._events = events
        self._rbac = rbac

    # ------------------------------------------------------------------ #
    #  Validate                                                            #
    # ------------------------------------------------------------------ #

    async def validate_schema(
        self,
        payload: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Validate a proposed schema change without applying it.

        *payload* should contain either:
        - ``node_types``: list of node type definitions to validate
        - ``edge_types``: list of edge type definitions to validate

        Returns a report with validation results.
        """
        self._rbac.require_permission(actor, "manage", "schema:validate")

        log = logger.bind(actor=actor.user_id)
        errors: list[str] = []
        warnings: list[str] = []

        # Validate proposed node types
        for nt in payload.get("node_types", []):
            name = nt.get("metadata", {}).get("name", "<unnamed>")
            existing = self._registry.get_node_type(name)
            if existing:
                warnings.append(f"NodeType '{name}' already exists and will be updated")

            # Validate mixin references
            for mixin_name in nt.get("mixins", []):
                if not self._registry.get_mixin(mixin_name):
                    errors.append(f"NodeType '{name}' references unknown mixin '{mixin_name}'")

        # Validate proposed edge types
        for et in payload.get("edge_types", []):
            name = et.get("metadata", {}).get("name", "<unnamed>")
            source_types = et.get("source", {}).get("node_types", [])
            target_types = et.get("target", {}).get("node_types", [])

            for st in source_types:
                if not self._registry.get_node_type(st):
                    errors.append(
                        f"EdgeType '{name}' references unknown source type '{st}'"
                    )
            for tt in target_types:
                if not self._registry.get_node_type(tt):
                    errors.append(
                        f"EdgeType '{name}' references unknown target type '{tt}'"
                    )

        valid = len(errors) == 0
        log.info("schema.validated", valid=valid, error_count=len(errors))

        return {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------ #
    #  Migrate                                                             #
    # ------------------------------------------------------------------ #

    async def apply_migration(
        self,
        payload: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Apply a schema migration.

        *payload* must contain:
        - ``operations``: list of migration operations, each with
          ``cypher`` and optional ``params``.
        - ``changes``: list of change descriptions for auditing.
        - ``dry_run`` (optional): if ``True``, validate but do not execute.

        Returns a summary of applied operations.
        """
        self._rbac.require_permission(actor, "manage", "schema:migrate")

        log = logger.bind(actor=actor.user_id)
        operations = payload.get("operations", [])
        changes = payload.get("changes", [])
        dry_run = payload.get("dry_run", False)

        if not operations:
            raise SchemaMigrationError("No migration operations provided")

        if dry_run:
            log.info("schema.migration_dry_run", operation_count=len(operations))
            return {
                "dry_run": True,
                "operation_count": len(operations),
                "changes": changes,
            }

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for i, op in enumerate(operations):
            cypher = op.get("cypher", "")
            params = op.get("params", {})
            description = op.get("operation", f"operation_{i}")

            if not cypher:
                failed.append({"index": i, "operation": description, "error": "Empty cypher"})
                continue

            try:
                await self._driver.execute_write(cypher, params)
                applied.append({"index": i, "operation": description})
                log.info("schema.migration_op_applied", index=i, operation=description)
            except Exception as exc:
                error_msg = str(exc)
                failed.append({"index": i, "operation": description, "error": error_msg})
                log.error("schema.migration_op_failed", index=i, operation=description,
                          error=error_msg)

        # Emit schema change event
        await self._events.emit_schema_changed(changes)

        # Audit
        await self._events.emit_audit(
            action="schema_migrated",
            resource_type="schema",
            resource_id="migration",
            actor=actor.user_id,
            metadata={
                "applied_count": len(applied),
                "failed_count": len(failed),
            },
        )

        log.info("schema.migration_complete",
                 applied=len(applied), failed=len(failed))

        return {
            "applied": applied,
            "failed": failed,
            "applied_count": len(applied),
            "failed_count": len(failed),
        }

    # ------------------------------------------------------------------ #
    #  Index management                                                    #
    # ------------------------------------------------------------------ #

    async def ensure_indexes(self) -> dict[str, Any]:
        """Create Neo4j indexes and uniqueness constraints for all schema-defined
        indexed attributes.

        Iterates every registered node type, reads its ``get_indexes_for_type``
        definitions, and ensures corresponding indexes exist in Neo4j.

        Returns a summary of created indexes and constraints.
        """
        log = logger.bind()

        created_indexes: list[dict[str, str]] = []
        created_constraints: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []

        for nt_dict in self._registry.list_node_types():
            node_type = nt_dict.get("metadata", {}).get("name", "")
            if not node_type:
                continue

            index_defs = self._registry.get_indexes_for_type(node_type)
            for idx in index_defs:
                label = idx["label"]
                prop = idx["property"]
                unique = idx.get("unique", False)

                try:
                    await self._driver.create_index(label, prop, unique=unique)
                    entry = {"label": label, "property": prop}
                    if unique:
                        created_constraints.append(entry)
                    else:
                        created_indexes.append(entry)
                    log.info("schema.index_ensured", label=label, property=prop,
                             unique=unique)
                except Exception as exc:
                    errors.append({
                        "label": label,
                        "property": prop,
                        "error": str(exc),
                    })
                    log.error("schema.index_failed", label=label, property=prop,
                              error=str(exc))

        # Always ensure an id uniqueness constraint per node type
        for nt_dict in self._registry.list_node_types():
            node_type = nt_dict.get("metadata", {}).get("name", "")
            if not node_type:
                continue
            try:
                await self._driver.create_index(node_type, "id", unique=True)
                created_constraints.append({"label": node_type, "property": "id"})
            except Exception:
                pass  # Already exists -- safe to ignore

        summary = {
            "indexes_created": len(created_indexes),
            "constraints_created": len(created_constraints),
            "errors": errors,
            "indexes": created_indexes,
            "constraints": created_constraints,
        }

        log.info("schema.ensure_indexes_complete", **{
            k: v for k, v in summary.items() if k != "indexes" and k != "constraints" and k != "errors"
        })

        return summary
