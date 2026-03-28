"""Dynamic node CRUD endpoints.

Routes are parameterized by {node_type} and validated against the schema registry
at runtime. This allows any schema-defined node type to be managed without
writing type-specific code.

All operations go through NodeService which enforces:
  validate → authorize → execute → audit → emit
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from netgraphy_api.dependencies import get_node_service, get_auth_context
from netgraphy_api.services.node_service import NodeService
from packages.auth.models import AuthContext

router = APIRouter()


@router.get("/{node_type}")
async def list_nodes(
    request: Request,
    node_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List nodes of a given type with filtering and pagination.

    Filter params are extracted from query string based on schema filterable_fields.
    Use `field=value` or `field__operator=value` syntax.
    """
    # Extract filter params from query string (exclude known pagination params)
    reserved = {"page", "page_size", "sort", "fields", "include"}
    filters = {
        k: v for k, v in request.query_params.items()
        if k not in reserved
    }

    result = await svc.list(
        node_type=node_type,
        filters=filters,
        page=page,
        page_size=page_size,
        sort=sort,
        actor=actor,
    )
    return {
        "data": result["items"],
        "meta": {
            "total_count": result["total_count"],
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/{node_type}", status_code=201)
async def create_node(
    node_type: str,
    body: dict[str, Any],
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create a new node of the given type.

    Request body is validated against the schema-defined attributes.
    """
    node = await svc.create(node_type=node_type, properties=body, actor=actor)
    return {"data": node}


@router.get("/{node_type}/{node_id}")
async def get_node(
    node_type: str,
    node_id: str,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a node by ID."""
    node = await svc.get(node_type=node_type, node_id=node_id, actor=actor)
    return {"data": node}


@router.patch("/{node_type}/{node_id}")
async def update_node(
    node_type: str,
    node_id: str,
    body: dict[str, Any],
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Partial update of a node's properties."""
    node = await svc.update(
        node_type=node_type, node_id=node_id, properties=body, actor=actor,
    )
    return {"data": node}


@router.delete("/{node_type}/{node_id}", status_code=204)
async def delete_node(
    node_type: str,
    node_id: str,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a node and its relationships."""
    await svc.delete(node_type=node_type, node_id=node_id, actor=actor)


@router.get("/{node_type}/{node_id}/relationships")
async def list_relationships(
    node_type: str,
    node_id: str,
    edge_type: str | None = None,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all relationships for a node, optionally filtered by edge type."""
    edges = await svc.get_relationships(
        node_type=node_type, node_id=node_id, edge_type=edge_type, actor=actor,
    )
    return {"data": edges}
