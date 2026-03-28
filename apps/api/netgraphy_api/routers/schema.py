"""Schema discovery and management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends

from netgraphy_api.dependencies import get_schema_registry, get_auth_context
from netgraphy_api.exceptions import SchemaNotFoundError
from packages.auth.models import AuthContext
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


@router.get("/node-types")
async def list_node_types(
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """List all registered node type definitions."""
    return {"data": registry.list_node_types()}


@router.get("/node-types/{name}")
async def get_node_type(
    name: str,
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Get a node type definition with full metadata."""
    node_type = registry.get_node_type(name)
    if not node_type:
        raise SchemaNotFoundError("NodeType", name)
    return {"data": node_type.model_dump()}


@router.get("/edge-types")
async def list_edge_types(
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """List all registered edge type definitions."""
    return {"data": registry.list_edge_types()}


@router.get("/edge-types/{name}")
async def get_edge_type(
    name: str,
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Get an edge type definition."""
    edge_type = registry.get_edge_type(name)
    if not edge_type:
        raise SchemaNotFoundError("EdgeType", name)
    return {"data": edge_type.model_dump()}


@router.get("/ui-metadata")
async def get_ui_metadata(
    registry: SchemaRegistry = Depends(get_schema_registry),
):
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
    payload: dict[str, Any],
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Validate a schema change without applying it."""
    from packages.schema_engine.validators.schema_validator import validate_schema_file
    errors = validate_schema_file(payload)
    return {
        "data": {
            "valid": len(errors) == 0,
            "warnings": [],
            "errors": errors,
        }
    }


@router.post("/migrate")
async def apply_migration(
    payload: dict[str, Any],
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Apply a schema migration. Requires admin role."""
    from packages.auth.rbac import PermissionChecker
    PermissionChecker().require_permission(actor, "manage", "schema")
    # Schema migration is a complex operation — deferred to Phase 2
    return {"data": {"status": "not_implemented", "message": "Schema migration will be available in a future release"}}
