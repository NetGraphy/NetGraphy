"""Schema discovery and management endpoints."""

from fastapi import APIRouter, Depends

from netgraphy_api.dependencies import get_schema_registry
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


@router.get("/node-types")
async def list_node_types(registry: SchemaRegistry = Depends(get_schema_registry)):
    """List all registered node type definitions."""
    return {"data": registry.list_node_types()}


@router.get("/node-types/{name}")
async def get_node_type(name: str, registry: SchemaRegistry = Depends(get_schema_registry)):
    """Get a node type definition with full metadata."""
    node_type = registry.get_node_type(name)
    if not node_type:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Node type '{name}' not found")
    return {"data": node_type}


@router.get("/edge-types")
async def list_edge_types(registry: SchemaRegistry = Depends(get_schema_registry)):
    """List all registered edge type definitions."""
    return {"data": registry.list_edge_types()}


@router.get("/edge-types/{name}")
async def get_edge_type(name: str, registry: SchemaRegistry = Depends(get_schema_registry)):
    """Get an edge type definition."""
    edge_type = registry.get_edge_type(name)
    if not edge_type:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Edge type '{name}' not found")
    return {"data": edge_type}


@router.get("/ui-metadata")
async def get_ui_metadata(registry: SchemaRegistry = Depends(get_schema_registry)):
    """Full UI metadata for dynamic frontend rendering.

    Returns all node types, edge types, their attributes, categories,
    and rendering hints needed by the dynamic UI system.
    """
    return {
        "data": {
            "node_types": registry.list_node_types(),
            "edge_types": registry.list_edge_types(),
            "enum_types": registry.list_enum_types(),
            "categories": registry.get_categories(),
        }
    }


@router.post("/validate")
async def validate_schema(
    payload: dict,
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Validate a schema change without applying it."""
    # TODO: Implement schema validation with diff and impact analysis
    return {"data": {"valid": True, "warnings": [], "errors": []}}


@router.post("/migrate")
async def apply_migration(
    payload: dict,
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Apply a schema migration."""
    # TODO: Implement schema migration execution
    return {"data": {"status": "applied", "changes": []}}
