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
            records = [record.data() async for record in result]
            summary = await result.consume()

            columns = list(records[0].keys()) if records else []
            nodes, edges = self._extract_graph_elements(records)

            return QueryResult(
                columns=columns,
                rows=records,
                nodes=nodes,
                edges=edges,
                metadata={
                    "result_available_after": summary.result_available_after,
                    "result_consumed_after": summary.result_consumed_after,
                    "row_count": len(records),
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
                records = [record.data() async for record in result]
                summary = await result.consume()
                return records, summary

            records, summary = await session.execute_write(_tx_work)
            columns = list(records[0].keys()) if records else []
            nodes, edges = self._extract_graph_elements(records)

            return QueryResult(
                columns=columns,
                rows=records,
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
        self, records: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Extract distinct nodes and edges from query results for graph rendering.

        Inspects record values for Neo4j Node and Relationship types
        and converts them to simple dicts with id, type, and properties.
        """
        # TODO: Implement extraction of Neo4j Node/Relationship objects
        # from records. For now, return empty lists — the table view
        # always works, and graph extraction will be added when we
        # integrate the graph visualization layer.
        return [], []

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
