"""FastAPI dependency injection providers."""

from functools import lru_cache

from neo4j import AsyncGraphDatabase

from netgraphy_api.config import settings
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

_driver: Neo4jDriver | None = None
_registry: SchemaRegistry | None = None


def get_graph_driver() -> Neo4jDriver:
    """Get or create the Neo4j driver singleton."""
    global _driver
    if _driver is None:
        _driver = Neo4jDriver(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            max_connection_pool_size=settings.neo4j_max_connection_pool_size,
        )
    return _driver


def get_schema_registry() -> SchemaRegistry:
    """Get or create the schema registry singleton."""
    global _registry
    if _registry is None:
        _registry = SchemaRegistry()
    return _registry
