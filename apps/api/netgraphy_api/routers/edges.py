"""Edge (relationship) CRUD endpoints.

All operations go through EdgeService which enforces:
  validate types → validate cardinality → authorize → execute → audit → emit
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from netgraphy_api.dependencies import get_edge_service, get_auth_context
from netgraphy_api.services.edge_service import EdgeService
from packages.auth.models import AuthContext

router = APIRouter()


@router.post("/{edge_type}", status_code=201)
async def create_edge(
    edge_type: str,
    body: dict[str, Any],
    svc: EdgeService = Depends(get_edge_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create a relationship between two nodes.

    Body must include source_id, target_id, and optional edge properties.
    Validates cardinality constraints and source/target node types.
    """
    source_id = body.pop("source_id", None)
    target_id = body.pop("target_id", None)
    if not source_id or not target_id:
        raise HTTPException(status_code=400, detail="source_id and target_id are required")

    edge = await svc.create(
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        properties=body,
        actor=actor,
    )
    return {"data": edge}


@router.patch("/{edge_type}/{edge_id}")
async def update_edge(
    edge_type: str,
    edge_id: str,
    body: dict[str, Any],
    svc: EdgeService = Depends(get_edge_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Update an edge's properties."""
    edge = await svc.update(
        edge_type=edge_type, edge_id=edge_id, properties=body, actor=actor,
    )
    return {"data": edge}


@router.delete("/{edge_type}/{edge_id}", status_code=204)
async def delete_edge(
    edge_type: str,
    edge_id: str,
    svc: EdgeService = Depends(get_edge_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete an edge."""
    await svc.delete(edge_type=edge_type, edge_id=edge_id, actor=actor)
