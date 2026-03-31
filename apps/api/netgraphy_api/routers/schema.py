"""Schema discovery, management, and designer endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from netgraphy_api.dependencies import get_schema_registry, get_auth_context, get_graph_driver
from netgraphy_api.exceptions import SchemaNotFoundError
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver
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
    """Validate a schema definition (parsed JSON/YAML dict) without applying it.

    Runs structural validation, attribute checks, and cross-reference
    validation against the live registry (e.g. verifying that edge
    source/target node types exist).
    """
    from packages.schema_engine.validators.schema_validator import (
        validate_schema_file,
        validate_cross_references,
    )

    errors = validate_schema_file(payload)
    warnings: list[str] = []

    # Cross-reference checks only make sense if the file is structurally valid
    if not errors:
        xref_errors, xref_warnings = validate_cross_references(payload, registry)
        errors.extend(xref_errors)
        warnings.extend(xref_warnings)

    return {
        "data": {
            "valid": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
        }
    }


@router.post("/validate-yaml")
async def validate_schema_yaml(
    payload: dict[str, Any],
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Validate raw YAML text. Expects ``{"yaml": "<yaml string>"}``.

    Parses the YAML, then validates each document found.
    """
    import yaml as _yaml
    from packages.schema_engine.validators.schema_validator import (
        validate_schema_file,
        validate_cross_references,
    )

    raw_yaml = payload.get("yaml", "")
    if not raw_yaml or not raw_yaml.strip():
        return {"data": {"valid": False, "warnings": [], "errors": ["Empty YAML input"]}}

    all_errors: list[str] = []
    all_warnings: list[str] = []
    doc_count = 0

    try:
        docs = list(_yaml.safe_load_all(raw_yaml))
    except _yaml.YAMLError as exc:
        return {"data": {"valid": False, "warnings": [], "errors": [f"YAML parse error: {exc}"]}}

    for doc in docs:
        if doc is None:
            continue
        doc_count += 1
        label = doc.get("metadata", {}).get("name", f"document {doc_count}")

        file_errors = validate_schema_file(doc)
        for e in file_errors:
            all_errors.append(f"[{label}] {e}")

        if not file_errors:
            xref_errors, xref_warnings = validate_cross_references(doc, registry)
            for e in xref_errors:
                all_errors.append(f"[{label}] {e}")
            for w in xref_warnings:
                all_warnings.append(f"[{label}] {w}")

    if doc_count == 0:
        all_errors.append("No YAML documents found")

    return {
        "data": {
            "valid": len(all_errors) == 0,
            "warnings": all_warnings,
            "errors": all_errors,
            "document_count": doc_count,
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


# --------------------------------------------------------------------------- #
#  Schema Designer — saved designs                                             #
# --------------------------------------------------------------------------- #


@router.get("/designs")
async def list_designs(
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List saved schema designs for the current user."""
    result = await driver.execute_read(
        "MATCH (d:_SchemaDesign) WHERE d.owner = $user OR d.visibility = 'shared' "
        "RETURN d ORDER BY d.updated_at DESC",
        {"user": actor.user_id},
    )
    return {"data": [row["d"] for row in result.rows]}


@router.post("/designs", status_code=201)
async def save_design(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Save a schema design."""
    now = datetime.now(timezone.utc).isoformat()
    name = body.get("name", "Untitled Design")

    # Upsert by name + owner
    result = await driver.execute_read(
        "MATCH (d:_SchemaDesign {name: $name, owner: $owner}) RETURN d.id AS id",
        {"name": name, "owner": actor.user_id},
    )

    if result.rows:
        # Update existing
        design_id = result.rows[0]["id"]
        await driver.execute_write(
            "MATCH (d:_SchemaDesign {id: $id}) "
            "SET d.schema = $schema, d.imported_names = $imported, d.updated_at = $now",
            {"id": design_id, "schema": body.get("schema", "{}"),
             "imported": body.get("imported_names", "[]"), "now": now},
        )
    else:
        # Create new
        design_id = str(uuid.uuid4())
        props = {
            "id": design_id,
            "name": name,
            "schema": body.get("schema", "{}"),
            "imported_names": body.get("imported_names", "[]"),
            "owner": actor.user_id,
            "owner_name": actor.username,
            "visibility": "personal",
            "created_at": now,
            "updated_at": now,
        }
        await driver.execute_write("CREATE (d:_SchemaDesign $props)", {"props": props})

    return {"data": {"id": design_id, "name": name, "saved": True}}


@router.delete("/designs/{design_id}", status_code=204)
async def delete_design(
    design_id: str,
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Delete a saved schema design."""
    await driver.execute_write(
        "MATCH (d:_SchemaDesign {id: $id, owner: $owner}) DELETE d",
        {"id": design_id, "owner": actor.user_id},
    )
