"""Node repository — typed CRUD operations for graph nodes.

All node operations go through this repository. It handles:
- Cypher generation via parameterized queries (never string interpolation)
- Schema validation before writes
- ID generation
- Pagination and filtering
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


class NodeRepository:
    """Repository for node CRUD operations against Neo4j."""

    def __init__(self, driver: Neo4jDriver, registry: SchemaRegistry):
        self._driver = driver
        self._registry = registry

    async def create_node(
        self,
        node_type: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new node with the given properties.

        Generates a UUID, validates against schema, and creates the node
        with the node_type as its Neo4j label.
        """
        # Validate against schema
        errors = self._registry.validate_node_properties(node_type, properties)
        if errors:
            raise ValueError(f"Validation errors: {'; '.join(errors)}")

        node_id = str(uuid.uuid4())
        properties["id"] = node_id

        # Build parameterized Cypher — NEVER interpolate property values
        query = f"CREATE (n:{node_type} $props) RETURN n"
        result = await self._driver.execute_write(query, {"props": properties})

        if result.rows:
            return {"id": node_id, "type": node_type, **properties}
        raise RuntimeError(f"Failed to create {node_type} node")

    async def get_node(
        self,
        node_type: str,
        node_id: str,
    ) -> dict[str, Any] | None:
        """Get a node by type and ID."""
        query = f"MATCH (n:{node_type} {{id: $id}}) RETURN n"
        result = await self._driver.execute_read(query, {"id": node_id})

        if result.rows:
            node_data = result.rows[0].get("n", {})
            return {"type": node_type, **node_data}
        return None

    async def update_node(
        self,
        node_type: str,
        node_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update a node's properties (partial update)."""
        # Remove id from update payload if present
        properties.pop("id", None)

        # Build SET clause for each property
        set_clauses = ", ".join(f"n.{key} = $props.{key}" for key in properties)
        if not set_clauses:
            return await self.get_node(node_type, node_id)

        query = f"MATCH (n:{node_type} {{id: $id}}) SET {set_clauses} RETURN n"
        result = await self._driver.execute_write(
            query, {"id": node_id, "props": properties}
        )

        if result.rows:
            node_data = result.rows[0].get("n", {})
            return {"type": node_type, **node_data}
        return None

    async def delete_node(
        self,
        node_type: str,
        node_id: str,
    ) -> bool:
        """Delete a node and all its relationships."""
        query = f"MATCH (n:{node_type} {{id: $id}}) DETACH DELETE n RETURN count(n) as deleted"
        result = await self._driver.execute_write(query, {"id": node_id})

        if result.rows:
            return result.rows[0].get("deleted", 0) > 0
        return False

    async def list_nodes(
        self,
        node_type: str,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 25,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """List nodes with filtering, sorting, and pagination.

        Returns dict with 'items' and 'total_count'.
        """
        where_clauses = []
        params: dict[str, Any] = {}

        # Build WHERE clauses from filters
        for i, (key, value) in enumerate((filters or {}).items()):
            param_name = f"filter_{i}"
            if isinstance(value, str) and "%" in value:
                where_clauses.append(f"n.{key} CONTAINS ${param_name}")
                params[param_name] = value.replace("%", "")
            else:
                where_clauses.append(f"n.{key} = ${param_name}")
                params[param_name] = value

        where = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Count query
        count_query = f"MATCH (n:{node_type}){where} RETURN count(n) as total"
        count_result = await self._driver.execute_read(count_query, params)
        total_count = count_result.rows[0]["total"] if count_result.rows else 0

        # Data query with pagination
        order = f" ORDER BY n.{sort}" if sort else " ORDER BY n.id"
        skip = (page - 1) * page_size
        data_query = (
            f"MATCH (n:{node_type}){where}"
            f" RETURN n{order} SKIP $skip LIMIT $limit"
        )
        params["skip"] = skip
        params["limit"] = page_size

        data_result = await self._driver.execute_read(data_query, params)
        items = [
            {"type": node_type, **row.get("n", {})}
            for row in data_result.rows
        ]

        return {"items": items, "total_count": total_count}

    async def get_relationships(
        self,
        node_id: str,
        edge_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all relationships for a node, optionally filtered by edge type.

        Returns each relationship with:
        - edge_type, edge_id, edge_properties
        - related_node (all properties including id)
        - related_type (Neo4j label of the related node)
        - direction ('outgoing' or 'incoming')
        - label (display field for the related node)
        """
        # Use two directional matches to capture direction info
        if edge_type:
            query = (
                f"MATCH (n {{id: $id}})-[r:{edge_type}]->(m) "
                f"RETURN type(r) AS edge_type, properties(r) AS edge_props, "
                f"m, labels(m)[0] AS related_type, 'outgoing' AS direction "
                f"UNION ALL "
                f"MATCH (n {{id: $id}})<-[r:{edge_type}]-(m) "
                f"RETURN type(r) AS edge_type, properties(r) AS edge_props, "
                f"m, labels(m)[0] AS related_type, 'incoming' AS direction"
            )
        else:
            query = (
                "MATCH (n {id: $id})-[r]->(m) "
                "RETURN type(r) AS edge_type, properties(r) AS edge_props, "
                "m, labels(m)[0] AS related_type, 'outgoing' AS direction "
                "UNION ALL "
                "MATCH (n {id: $id})<-[r]-(m) "
                "RETURN type(r) AS edge_type, properties(r) AS edge_props, "
                "m, labels(m)[0] AS related_type, 'incoming' AS direction"
            )

        result = await self._driver.execute_read(query, {"id": node_id})
        rels = []
        for row in result.rows:
            related = row.get("m", {})
            # Pick a human-readable label from the related node
            label = (
                related.get("name")
                or related.get("hostname")
                or related.get("address")
                or related.get("prefix")
                or related.get("version_string")
                or related.get("model")
                or related.get("filename")
                or related.get("asn")
                or related.get("id", "")
            )
            rels.append({
                "edge_type": row.get("edge_type"),
                "edge_properties": row.get("edge_props", {}),
                "related_node": related,
                "related_type": row.get("related_type"),
                "related_id": related.get("id"),
                "direction": row.get("direction"),
                "label": str(label),
            })
        return rels

    async def bulk_upsert(
        self,
        node_type: str,
        items: list[dict[str, Any]],
        match_on: list[str],
        batch_size: int = 1000,
    ) -> dict[str, int]:
        """Bulk upsert nodes using UNWIND for performance.

        Matches existing nodes by match_on fields and creates or updates.
        Processes in batches for memory efficiency.
        """
        created = 0
        updated = 0

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]

            # Build MERGE conditions from match_on fields
            merge_conditions = ", ".join(f"{field}: item.{field}" for field in match_on)
            set_clause = ", ".join(
                f"n.{key} = item.{key}"
                for key in batch[0].keys()
                if key not in match_on
            )

            query = (
                f"UNWIND $items AS item "
                f"MERGE (n:{node_type} {{{merge_conditions}}}) "
            )
            if set_clause:
                query += f"ON CREATE SET n.id = randomUUID(), {set_clause} "
                query += f"ON MATCH SET {set_clause} "
            query += "RETURN count(n) as count"

            result = await self._driver.execute_write(query, {"items": batch})
            if result.metadata.get("counters"):
                created += result.metadata["counters"].get("nodes_created", 0)
                # Approximation — Neo4j doesn't distinguish MERGE create vs match easily
                updated += len(batch) - result.metadata["counters"].get("nodes_created", 0)

        return {"created": created, "updated": updated}
