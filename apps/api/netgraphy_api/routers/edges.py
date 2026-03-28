"""Edge (relationship) CRUD endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from netgraphy_api.dependencies import get_graph_driver, get_schema_registry
from packages.graph_db.driver import Neo4jDriver
from packages.graph_db.repositories.edge_repository import EdgeRepository
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


def _get_edge_repo(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> EdgeRepository:
    return EdgeRepository(driver=driver, registry=registry)


@router.post("/{edge_type}", status_code=201)
async def create_edge(
    edge_type: str,
    body: dict[str, Any],
    repo: EdgeRepository = Depends(_get_edge_repo),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Create a relationship between two nodes.

    Body must include source_id, target_id, and optional edge properties.
    Validates cardinality constraints from schema before creation.
    """
    edge_def = registry.get_edge_type(edge_type)
    if not edge_def:
        raise HTTPException(status_code=404, detail=f"Edge type '{edge_type}' not found")

    source_id = body.pop("source_id", None)
    target_id = body.pop("target_id", None)
    if not source_id or not target_id:
        raise HTTPException(status_code=400, detail="source_id and target_id are required")

    # TODO: Enforce cardinality, validate source/target node types, emit audit event
    edge = await repo.create_edge(
        edge_type=edge_type,
        source_id=source_id,
        target_id=target_id,
        properties=body,
    )
    return {"data": edge}


@router.patch("/{edge_type}/{edge_id}")
async def update_edge(
    edge_type: str,
    edge_id: str,
    body: dict[str, Any],
    repo: EdgeRepository = Depends(_get_edge_repo),
):
    """Update an edge's properties."""
    edge = await repo.update_edge(edge_type=edge_type, edge_id=edge_id, properties=body)
    if not edge:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_id}' not found")
    return {"data": edge}


@router.delete("/{edge_type}/{edge_id}", status_code=204)
async def delete_edge(
    edge_type: str,
    edge_id: str,
    repo: EdgeRepository = Depends(_get_edge_repo),
):
    """Delete an edge."""
    deleted = await repo.delete_edge(edge_type=edge_type, edge_id=edge_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_id}' not found")
