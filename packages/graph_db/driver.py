"""Neo4j async driver wrapper.

Provides connection pooling, session management, and a clean interface
for executing Cypher queries. Designed to be swappable with an AGE driver
in the future — the key abstraction point.
"""

from __future__ import annotations

from typing import Any

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

logger = structlog.get_logger()


class QueryResult:
    """Unified query result that supports both table and graph rendering.

    Attributes:
        columns: Column names from the query result.
        rows: List of dicts for table rendering.
        nodes: Extracted node data for graph rendering.
        edges: Extracted edge data for graph rendering.
        metadata: Query execution metadata (timing, counts).
    """

    def __init__(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.columns = columns
        self.rows = rows
        self.nodes = nodes or []
        self.edges = edges or []
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "nodes": self.nodes,
            "edges": self.edges,
            "metadata": self.metadata,
        }


class Neo4jDriver:
    """Async Neo4j driver wrapper with connection pooling.

    This is the primary abstraction point for future AGE support.
    All Cypher execution flows through this class.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        max_connection_pool_size: int = 50,
    ):
        self._uri = uri
        self._database = database
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_connection_pool_size,
        )

    async def verify_connectivity(self) -> None:
        """Verify that the Neo4j instance is reachable."""
        await self._driver.verify_connectivity()

    async def close(self) -> None:
        """Close the driver and release all connections."""
        await self._driver.close()

    def session(self, **kwargs) -> AsyncSession:
        """Get a new async session."""
        return self._driver.session(database=self._database, **kwargs)

    async def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a read-only Cypher query."""
        async with self.session() as session:
            result = await session.run(query, parameters or {})
            raw_records = [record async for record in result]
            summary = await result.consume()

            rows = [record.data() for record in raw_records]
            columns = list(rows[0].keys()) if rows else []
            nodes, edges = self._extract_graph_elements(raw_records)

            return QueryResult(
                columns=columns,
                rows=rows,
                nodes=nodes,
                edges=edges,
                metadata={
                    "result_available_after": summary.result_available_after,
                    "result_consumed_after": summary.result_consumed_after,
                    "row_count": len(rows),
                },
            )

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a write Cypher query within a transaction."""
        async with self.session() as session:

            async def _tx_work(tx):
                result = await tx.run(query, parameters or {})
                raw_records = [record async for record in result]
                summary = await result.consume()
                return raw_records, summary

            raw_records, summary = await session.execute_write(_tx_work)
            rows = [record.data() for record in raw_records]
            columns = list(rows[0].keys()) if rows else []
            nodes, edges = self._extract_graph_elements(raw_records)

            return QueryResult(
                columns=columns,
                rows=rows,
                nodes=nodes,
                edges=edges,
                metadata={
                    "counters": {
                        "nodes_created": summary.counters.nodes_created,
                        "nodes_deleted": summary.counters.nodes_deleted,
                        "relationships_created": summary.counters.relationships_created,
                        "relationships_deleted": summary.counters.relationships_deleted,
                        "properties_set": summary.counters.properties_set,
                    },
                },
            )

    def _extract_graph_elements(
        self, raw_records: list,
    ) -> tuple[list[dict], list[dict]]:
        """Extract distinct nodes and edges from query results for graph rendering.

        Inspects record values for Neo4j Node and Relationship objects
        and converts them to simple dicts. Deduplicates by element ID.
        """
        from neo4j.graph import Node, Relationship, Path

        seen_node_ids: set[str] = set()
        seen_edge_ids: set[str] = set()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        def _process_node(node: Node) -> None:
            eid = str(node.element_id)
            if eid in seen_node_ids:
                return
            seen_node_ids.add(eid)
            labels = list(node.labels)
            props = dict(node)
            nodes.append({
                "id": props.get("id", eid),
                "element_id": eid,
                "node_type": labels[0] if labels else "Unknown",
                "labels": labels,
                "label": props.get("hostname") or props.get("name") or props.get("id", eid),
                "properties": props,
            })

        def _process_relationship(rel: Relationship) -> None:
            eid = str(rel.element_id)
            if eid in seen_edge_ids:
                return
            seen_edge_ids.add(eid)

            # Source/target IDs must match node IDs used above.
            # Nodes use props["id"] (application UUID) with element_id as fallback.
            # We must resolve the same way here.
            src_eid = str(rel.start_node.element_id) if rel.start_node else ""
            tgt_eid = str(rel.end_node.element_id) if rel.end_node else ""
            src_id = dict(rel.start_node).get("id", src_eid) if rel.start_node else src_eid
            tgt_id = dict(rel.end_node).get("id", tgt_eid) if rel.end_node else tgt_eid

            edges.append({
                "id": dict(rel).get("id", eid),
                "element_id": eid,
                "edge_type": rel.type,
                "source_id": src_id,
                "target_id": tgt_id,
                "properties": dict(rel),
            })

        def _process_value(value: Any) -> None:
            if isinstance(value, Node):
                _process_node(value)
            elif isinstance(value, Relationship):
                _process_relationship(value)
                if value.start_node:
                    _process_node(value.start_node)
                if value.end_node:
                    _process_node(value.end_node)
            elif isinstance(value, Path):
                for node in value.nodes:
                    _process_node(node)
                for rel in value.relationships:
                    _process_relationship(rel)
            elif isinstance(value, list):
                for item in value:
                    _process_value(item)

        for record in raw_records:
            for value in record.values():
                _process_value(value)

        return nodes, edges

    async def execute_query_plan(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute EXPLAIN or PROFILE on a query and return the plan."""
        explain_query = f"EXPLAIN {query}"
        async with self.session() as session:
            result = await session.run(explain_query, parameters or {})
            summary = await result.consume()
            return {
                "plan": str(summary.plan) if summary.plan else None,
                "profile": str(summary.profile) if summary.profile else None,
            }

    async def create_index(self, label: str, property_name: str, unique: bool = False) -> None:
        """Create an index on a node label and property."""
        if unique:
            query = f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{property_name} IS UNIQUE"
        else:
            query = f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{property_name})"
        await self.execute_write(query)

    async def drop_index(self, label: str, property_name: str) -> None:
        """Drop an index. Handles both regular and unique constraint indexes."""
        # Neo4j 5 syntax
        query = f"DROP INDEX ON :{label}({property_name}) IF EXISTS"
        try:
            await self.execute_write(query)
        except Exception:
            logger.warning("Failed to drop index, may not exist",
                           label=label, property=property_name)
