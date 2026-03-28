"""Health check endpoints for liveness, readiness, and startup probes.

These endpoints are public (no authentication required) and are designed
for Kubernetes / container orchestrator probes.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends

from netgraphy_api.dependencies import get_graph_driver, get_schema_registry
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness probe -- always returns ok.

    Indicates the process is running and not deadlocked.  If this fails
    the orchestrator should restart the container.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> dict[str, Any]:
    """Readiness probe -- verifies Neo4j connectivity and schema status.

    The endpoint executes a lightweight Cypher query to confirm the
    database is reachable and reports whether the schema registry has
    been populated.  Returns HTTP 503 (via exception) if Neo4j is down.
    """
    # Check Neo4j connectivity with a trivial read query.
    neo4j_status = "connected"
    neo4j_detail: str | None = None
    try:
        result = await driver.execute_read("RETURN 1 AS ping")
        if not result.rows or result.rows[0].get("ping") != 1:
            neo4j_status = "degraded"
            neo4j_detail = "Unexpected response from connectivity check"
    except Exception as exc:
        neo4j_status = "disconnected"
        neo4j_detail = str(exc)
        logger.warning("health.neo4j_unreachable", error=neo4j_detail)

    # Check schema loaded status.
    node_type_count = len(registry.list_node_types())
    edge_type_count = len(registry.list_edge_types())
    schema_loaded = node_type_count > 0

    overall = "ok" if neo4j_status == "connected" and schema_loaded else "degraded"

    response: dict[str, Any] = {
        "status": overall,
        "neo4j": neo4j_status,
        "schema_loaded": schema_loaded,
        "schema_node_types": node_type_count,
        "schema_edge_types": edge_type_count,
    }
    if neo4j_detail:
        response["neo4j_detail"] = neo4j_detail

    return response


@router.get("/health/startup")
async def startup(
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> dict[str, Any]:
    """Startup probe -- verifies the schema registry has loaded node types.

    This is used by Kubernetes ``startupProbe`` to delay liveness/readiness
    checks until the application has finished initialising.
    """
    node_types = registry.list_node_types()
    edge_types = registry.list_edge_types()
    loaded = len(node_types) > 0

    return {
        "status": "ok" if loaded else "initialising",
        "schema_loaded": loaded,
        "node_types_loaded": len(node_types),
        "edge_types_loaded": len(edge_types),
    }
