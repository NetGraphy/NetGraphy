"""Dynamic node CRUD endpoints.

Routes are parameterized by {node_type} and validated against the schema registry
at runtime. This allows any schema-defined node type to be managed without
writing type-specific code.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import get_graph_driver, get_schema_registry
from packages.graph_db.driver import Neo4jDriver
from packages.graph_db.repositories.node_repository import NodeRepository
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


def _get_node_repo(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> NodeRepository:
    return NodeRepository(driver=driver, registry=registry)


@router.get("/{node_type}")
async def list_nodes(
    node_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    fields: str | None = None,
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """List nodes of a given type with filtering and pagination.

    Supports query parameters for filtering based on the node type's
    filterable_fields defined in the schema.
    """
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    # TODO: Parse filter params from query string based on schema filterable_fields
    result = await repo.list_nodes(
        node_type=node_type,
        filters={},
        page=page,
        page_size=page_size,
        sort=sort,
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
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Create a new node of the given type.

    Request body is validated against the schema-defined attributes
    for this node type.
    """
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    # TODO: Validate body against schema, emit audit event
    node = await repo.create_node(node_type=node_type, properties=body)
    return {"data": node}


@router.get("/{node_type}/{node_id}")
async def get_node(
    node_type: str,
    node_id: str,
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Get a node by ID."""
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    node = await repo.get_node(node_type=node_type, node_id=node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    return {"data": node}


@router.patch("/{node_type}/{node_id}")
async def update_node(
    node_type: str,
    node_id: str,
    body: dict[str, Any],
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Partial update of a node's properties."""
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    # TODO: Validate body against schema, compute diff, emit audit event
    node = await repo.update_node(node_type=node_type, node_id=node_id, properties=body)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    return {"data": node}


@router.delete("/{node_type}/{node_id}", status_code=204)
async def delete_node(
    node_type: str,
    node_id: str,
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Delete a node and its relationships."""
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    # TODO: Check for dependent edges, emit audit event
    deleted = await repo.delete_node(node_type=node_type, node_id=node_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")


@router.get("/{node_type}/{node_id}/relationships")
async def list_relationships(
    node_type: str,
    node_id: str,
    edge_type: str | None = None,
    repo: NodeRepository = Depends(_get_node_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """List all relationships for a node, optionally filtered by edge type."""
    if not registry.get_node_type(node_type):
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    # TODO: Implement relationship listing via graph traversal
    edges = await repo.get_relationships(node_id=node_id, edge_type=edge_type)
    return {"data": edges}
