"""Query execution and saved query management.

Supports three modes:
1. Raw Cypher execution (RBAC-gated to operator+)
2. Structured query from the visual builder
3. Saved parameterized queries
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from netgraphy_api.dependencies import get_query_service, get_auth_context
from netgraphy_api.services.query_service import QueryService
from packages.auth.models import AuthContext

router = APIRouter()


@router.post("/cypher")
async def execute_cypher(
    body: dict[str, Any],
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute a Cypher query and return results in dual format (table + graph).

    Body:
        query: str — the Cypher query string
        parameters: dict — query parameters (never interpolated)
        explain: bool — return query plan instead of results
    """
    from netgraphy_api.exceptions import NetGraphyError
    query_str = body.get("query")
    if not query_str:
        raise NetGraphyError("'query' field is required")
    parameters = body.get("parameters", {})
    explain = body.get("explain", False)

    result = await svc.execute_cypher(
        query=query_str, parameters=parameters, actor=actor, explain=explain,
    )
    return {"data": result}


@router.post("/structured")
async def execute_structured_query(
    body: dict[str, Any],
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute a structured query from the visual query builder."""
    result = await svc.execute_structured(structured_query=body, actor=actor)
    return {"data": result}


@router.get("/saved")
async def list_saved_queries(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    tag: str | None = None,
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List saved queries with optional tag filtering."""
    result = await svc.list_saved_queries(actor=actor, page=page, page_size=page_size)
    return result


@router.post("/saved", status_code=201)
async def save_query(
    body: dict[str, Any],
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Save a query for later reuse."""
    saved = await svc.save_query(data=body, actor=actor)
    return {"data": saved}


@router.get("/saved/{query_id}")
async def get_saved_query(
    query_id: str,
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a saved query by ID."""
    query = await svc.get_saved_query(query_id=query_id, actor=actor)
    return {"data": query}


@router.delete("/saved/{query_id}", status_code=204)
async def delete_saved_query(
    query_id: str,
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a saved query."""
    await svc.delete_saved_query(query_id=query_id, actor=actor)


@router.post("/saved/{query_id}/execute")
async def execute_saved_query(
    query_id: str,
    body: dict[str, Any] | None = None,
    svc: QueryService = Depends(get_query_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute a saved query with optional parameter overrides."""
    result = await svc.execute_saved_query(
        query_id=query_id, params=body or {}, actor=actor,
    )
    return {"data": result}
