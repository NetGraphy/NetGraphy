"""Query execution and saved query management."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import get_graph_driver, get_schema_registry
from packages.graph_db.driver import Neo4jDriver
from packages.query_engine.executor import QueryExecutor
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


@router.post("/cypher")
async def execute_cypher(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Execute a Cypher query and return results in dual format (table + graph).

    Body:
        query: str — the Cypher query string
        parameters: dict — query parameters (never interpolated into the query)
        explain: bool — if true, return query plan instead of results
    """
    query = body.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="'query' field is required")

    parameters = body.get("parameters", {})
    explain = body.get("explain", False)

    # TODO: RBAC check — can this user execute arbitrary Cypher?
    # TODO: Query sanitization — block writes if user lacks permission

    executor = QueryExecutor(driver=driver, registry=registry)
    result = await executor.execute(query=query, parameters=parameters, explain=explain)
    return {"data": result}


@router.post("/structured")
async def execute_structured_query(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Execute a structured query from the visual query builder.

    Body contains a structured query definition that is validated against
    the schema and converted to Cypher for execution.
    """
    executor = QueryExecutor(driver=driver, registry=registry)
    # TODO: Validate structured query against schema
    result = await executor.execute_structured(body)
    return {"data": result}


@router.get("/saved")
async def list_saved_queries(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    tag: str | None = None,
):
    """List saved queries with optional tag filtering."""
    # TODO: Implement saved query storage and retrieval
    return {"data": [], "meta": {"total_count": 0, "page": page, "page_size": page_size}}


@router.post("/saved", status_code=201)
async def save_query(body: dict[str, Any]):
    """Save a query for later reuse."""
    # TODO: Implement saved query creation
    return {"data": {"id": "placeholder", **body}}


@router.get("/saved/{query_id}")
async def get_saved_query(query_id: str):
    """Get a saved query by ID."""
    # TODO: Implement saved query retrieval
    raise HTTPException(status_code=404, detail=f"Query '{query_id}' not found")


@router.delete("/saved/{query_id}", status_code=204)
async def delete_saved_query(query_id: str):
    """Delete a saved query."""
    # TODO: Implement saved query deletion
    pass


@router.post("/saved/{query_id}/execute")
async def execute_saved_query(
    query_id: str,
    body: dict[str, Any] | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Execute a saved query with optional parameter overrides."""
    # TODO: Load saved query, merge params, execute
    raise HTTPException(status_code=404, detail=f"Query '{query_id}' not found")
