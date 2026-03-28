"""Edge repository — typed CRUD for graph relationships."""

from __future__ import annotations

import uuid
from typing import Any

from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry


class EdgeRepository:
    """Repository for edge (relationship) CRUD operations."""

    def __init__(self, driver: Neo4jDriver, registry: SchemaRegistry):
        self._driver = driver
        self._registry = registry

    async def create_edge(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a relationship between two nodes.

        Validates cardinality constraints before creation.
        """
        edge_def = self._registry.get_edge_type(edge_type)
        if not edge_def:
            raise ValueError(f"Unknown edge type: {edge_type}")

        # Enforce cardinality
        await self._check_cardinality(edge_type, source_id, target_id, edge_def)

        props = properties or {}
        props["id"] = str(uuid.uuid4())

        # Build parameterized query — source and target matched by id property
        query = (
            f"MATCH (a {{id: $source_id}}), (b {{id: $target_id}}) "
            f"CREATE (a)-[r:{edge_type} $props]->(b) "
            f"RETURN r"
        )
        result = await self._driver.execute_write(
            query,
            {"source_id": source_id, "target_id": target_id, "props": props},
        )

        return {
            "id": props["id"],
            "edge_type": edge_type,
            "source_id": source_id,
            "target_id": target_id,
            "properties": props,
        }

    async def update_edge(
        self,
        edge_type: str,
        edge_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update an edge's properties."""
        properties.pop("id", None)
        set_clauses = ", ".join(f"r.{key} = $props.{key}" for key in properties)
        if not set_clauses:
            return None

        query = (
            f"MATCH ()-[r:{edge_type} {{id: $id}}]->() "
            f"SET {set_clauses} RETURN r"
        )
        result = await self._driver.execute_write(
            query, {"id": edge_id, "props": properties}
        )

        if result.rows:
            return {
                "id": edge_id,
                "edge_type": edge_type,
                "properties": result.rows[0].get("r", {}),
            }
        return None

    async def delete_edge(
        self,
        edge_type: str,
        edge_id: str,
    ) -> bool:
        """Delete a relationship by type and ID."""
        query = (
            f"MATCH ()-[r:{edge_type} {{id: $id}}]->() "
            f"DELETE r RETURN count(r) as deleted"
        )
        result = await self._driver.execute_write(query, {"id": edge_id})
        if result.rows:
            return result.rows[0].get("deleted", 0) > 0
        return False

    async def _check_cardinality(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        edge_def,
    ) -> None:
        """Enforce cardinality constraints before creating an edge.

        Raises ValueError if the new edge would violate cardinality.
        """
        cardinality = edge_def.cardinality.value

        if cardinality in ("one_to_one", "many_to_one"):
            # Target should not already have an inbound edge of this type
            if edge_def.constraints.unique_target:
                query = (
                    f"MATCH ()-[r:{edge_type}]->(b {{id: $target_id}}) "
                    f"RETURN count(r) as count"
                )
                result = await self._driver.execute_read(
                    query, {"target_id": target_id}
                )
                if result.rows and result.rows[0].get("count", 0) > 0:
                    raise ValueError(
                        f"Cardinality violation: target node already has a "
                        f"{edge_type} relationship (unique_target constraint)"
                    )

        if cardinality in ("one_to_one", "one_to_many"):
            # Source should not already have an outbound edge of this type (for 1:1)
            if edge_def.constraints.unique_source:
                query = (
                    f"MATCH (a {{id: $source_id}})-[r:{edge_type}]->() "
                    f"RETURN count(r) as count"
                )
                result = await self._driver.execute_read(
                    query, {"source_id": source_id}
                )
                if result.rows and result.rows[0].get("count", 0) > 0:
                    raise ValueError(
                        f"Cardinality violation: source node already has a "
                        f"{edge_type} relationship (unique_source constraint)"
                    )
