"""Query service -- domain orchestration for Cypher and structured queries.

Handles authorization, write-query blocking for non-admins, query execution,
saved-query management, and event emission.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from apps.api.netgraphy_api.exceptions import (
    AuthorizationError,
    NodeNotFoundError,
    QueryExecutionError,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger(__name__)

# Regex that matches Cypher write keywords at word boundaries.
_WRITE_KEYWORDS_RE = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH\s+DELETE|REMOVE|DROP|CALL\s*\{)\b",
    re.IGNORECASE,
)


class QueryService:
    """Orchestrates query execution with authorization and auditing."""

    def __init__(
        self,
        driver: Neo4jDriver,
        registry: SchemaRegistry,
        events: EventBus,
        rbac: PermissionChecker,
    ) -> None:
        self._driver = driver
        self._registry = registry
        self._events = events
        self._rbac = rbac

    # ------------------------------------------------------------------ #
    #  Raw Cypher execution                                                #
    # ------------------------------------------------------------------ #

    async def execute_cypher(
        self,
        query: str,
        parameters: dict[str, Any],
        actor: AuthContext,
        explain: bool = False,
    ) -> dict[str, Any]:
        """Execute a raw Cypher query.

        Steps:
        1. Require ``execute:cypher`` permission (operator+ only).
        2. For non-admin roles, reject write queries.
        3. If *explain* is ``True``, return the query plan instead.
        4. Execute via the Neo4j driver.
        5. Emit a ``query.executed`` audit event.
        """
        log = logger.bind(actor=actor.user_id)

        # 1. Authorization -- only operator+ can run raw Cypher
        self._rbac.require_permission(actor, "execute", "cypher")

        # 2. Block write queries for non-admin users
        is_write = _WRITE_KEYWORDS_RE.search(query) is not None
        if is_write and actor.role not in ("admin", "superadmin"):
            log.warning("query.write_blocked", role=actor.role)
            raise AuthorizationError(
                action="execute_write",
                resource="cypher",
            )

        try:
            # 3. Explain mode
            if explain:
                plan = await self._driver.execute_query_plan(query, parameters)
                return {"explain": True, "plan": plan}

            # 4. Execute
            if is_write:
                result = await self._driver.execute_write(query, parameters)
            else:
                result = await self._driver.execute_read(query, parameters)

            log.info(
                "query.executed",
                row_count=result.metadata.get("row_count", len(result.rows)),
                is_write=is_write,
            )

        except Exception as exc:
            log.error("query.execution_error", error=str(exc))
            raise QueryExecutionError(str(exc))

        # 5. Audit
        await self._events.emit_audit(
            action="query_executed",
            resource_type="cypher",
            resource_id="ad-hoc",
            actor=actor.user_id,
            metadata={"query_preview": query[:200], "is_write": is_write},
        )

        return result.to_dict()

    # ------------------------------------------------------------------ #
    #  Structured query execution                                          #
    # ------------------------------------------------------------------ #

    async def execute_structured(
        self,
        structured_query: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Validate and execute a structured (non-Cypher) query.

        Structured queries are safe-by-construction: they reference only
        known node/edge types and are translated to parameterised Cypher
        internally.

        Expected *structured_query* shape::

            {
                "node_type": "Device",
                "filters": {"status": "active"},
                "return_fields": ["hostname", "ip_address"],
                "limit": 50,
                "order_by": "hostname"
            }
        """
        log = logger.bind(actor=actor.user_id)

        # Authorization -- read access to the target node type
        node_type = structured_query.get("node_type", "")
        self._rbac.require_permission(actor, "read", f"node:{node_type}")

        # Validate the node type exists
        self._registry.require_node_type(node_type)

        # Build Cypher from structured query
        filters = structured_query.get("filters", {})
        return_fields = structured_query.get("return_fields")
        limit = structured_query.get("limit", 25)
        order_by = structured_query.get("order_by")

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        for i, (key, value) in enumerate(filters.items()):
            param_name = f"p_{i}"
            where_clauses.append(f"n.{key} = ${param_name}")
            params[param_name] = value

        where = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        if return_fields:
            return_expr = ", ".join(f"n.{f} AS {f}" for f in return_fields)
        else:
            return_expr = "n"

        order = f" ORDER BY n.{order_by}" if order_by else ""

        query = f"MATCH (n:{node_type}){where} RETURN {return_expr}{order} LIMIT $limit"
        params["limit"] = limit

        try:
            result = await self._driver.execute_read(query, params)
        except Exception as exc:
            log.error("structured_query.execution_error", error=str(exc))
            raise QueryExecutionError(str(exc))

        log.info("structured_query.executed", node_type=node_type, row_count=len(result.rows))

        return result.to_dict()

    # ------------------------------------------------------------------ #
    #  Saved queries                                                       #
    # ------------------------------------------------------------------ #

    async def list_saved_queries(
        self,
        actor: AuthContext,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Return a paginated list of saved queries visible to the actor."""
        self._rbac.require_permission(actor, "read", "query:saved")

        skip = (page - 1) * page_size
        count_query = "MATCH (q:SavedQuery) RETURN count(q) AS total"
        count_result = await self._driver.execute_read(count_query)
        total = count_result.rows[0]["total"] if count_result.rows else 0

        data_query = (
            "MATCH (q:SavedQuery) RETURN q "
            "ORDER BY q.updated_at DESC SKIP $skip LIMIT $limit"
        )
        data_result = await self._driver.execute_read(
            data_query, {"skip": skip, "limit": page_size},
        )

        items = [row.get("q", {}) for row in data_result.rows]

        return {
            "items": items,
            "total_count": total,
            "page": page,
            "page_size": page_size,
        }

    async def save_query(
        self,
        data: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Persist a new saved query.

        Required fields in *data*: ``name``, ``cypher``.
        Optional: ``description``, ``parameters``, ``tags``.
        """
        self._rbac.require_permission(actor, "execute", "query:saved")

        query_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        props = {
            "id": query_id,
            "name": data["name"],
            "cypher": data["cypher"],
            "description": data.get("description", ""),
            "parameters": str(data.get("parameters", {})),
            "tags": data.get("tags", []),
            "created_by": actor.user_id,
            "created_at": now,
            "updated_at": now,
        }

        create_query = "CREATE (q:SavedQuery $props) RETURN q"
        result = await self._driver.execute_write(create_query, {"props": props})

        logger.info("saved_query.created", query_id=query_id, actor=actor.user_id)

        return {"id": query_id, **props}

    async def get_saved_query(
        self,
        query_id: str,
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Retrieve a saved query by ID."""
        self._rbac.require_permission(actor, "read", "query:saved")

        query = "MATCH (q:SavedQuery {id: $id}) RETURN q"
        result = await self._driver.execute_read(query, {"id": query_id})

        if not result.rows:
            raise NodeNotFoundError("SavedQuery", query_id)

        return result.rows[0].get("q", {})

    async def delete_saved_query(
        self,
        query_id: str,
        actor: AuthContext,
    ) -> None:
        """Delete a saved query by ID."""
        self._rbac.require_permission(actor, "execute", "query:saved")

        query = (
            "MATCH (q:SavedQuery {id: $id}) "
            "DELETE q RETURN count(q) AS deleted"
        )
        result = await self._driver.execute_write(query, {"id": query_id})
        deleted = result.rows[0].get("deleted", 0) if result.rows else 0

        if not deleted:
            raise NodeNotFoundError("SavedQuery", query_id)

        logger.info("saved_query.deleted", query_id=query_id, actor=actor.user_id)

    async def execute_saved_query(
        self,
        query_id: str,
        params: dict[str, Any],
        actor: AuthContext,
    ) -> dict[str, Any]:
        """Load a saved query and execute it with the supplied parameters.

        The saved query's Cypher is executed as a read-only query.
        """
        # Fetch the saved query
        saved = await self.get_saved_query(query_id, actor)

        # Execute the cypher (read-only for saved queries)
        self._rbac.require_permission(actor, "execute", "query:saved")

        cypher = saved.get("cypher", "")
        if not cypher:
            raise QueryExecutionError("Saved query has no Cypher statement")

        try:
            result = await self._driver.execute_read(cypher, params)
        except Exception as exc:
            logger.error("saved_query.execution_error", query_id=query_id, error=str(exc))
            raise QueryExecutionError(str(exc))

        # Audit
        await self._events.emit_audit(
            action="query_executed",
            resource_type="saved_query",
            resource_id=query_id,
            actor=actor.user_id,
        )

        logger.info("saved_query.executed", query_id=query_id, actor=actor.user_id)

        return result.to_dict()
