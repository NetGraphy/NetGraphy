"""Parser registry, testing, command bundles, and mapping endpoints.

Parsers are stored as _Parser nodes in Neo4j (synced from Git or registered manually).
Command bundles and mappings are stored as _CommandBundle and _MappingDef nodes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_rbac
from netgraphy_api.exceptions import NodeNotFoundError
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver
from packages.ingestion.parsers.textfsm_parser import (
    parse_output_from_string,
    validate_template,
)

router = APIRouter()


# --------------------------------------------------------------------------- #
#  Parsers                                                                     #
# --------------------------------------------------------------------------- #

@router.get("")
async def list_parsers(
    platform: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List registered TextFSM parser templates."""
    where = ""
    params: dict[str, Any] = {}
    if platform:
        where = " WHERE p.platform = $platform"
        params["platform"] = platform

    skip = (page - 1) * page_size
    params.update({"skip": skip, "limit": page_size})

    count_r = await driver.execute_read(
        f"MATCH (p:_Parser){where} RETURN count(p) as total", params
    )
    total = count_r.rows[0]["total"] if count_r.rows else 0

    data_r = await driver.execute_read(
        f"MATCH (p:_Parser){where} RETURN p ORDER BY p.name SKIP $skip LIMIT $limit",
        params,
    )
    items = [row["p"] for row in data_r.rows]

    return {"data": items, "meta": {"total_count": total, "page": page, "page_size": page_size}}


@router.post("", status_code=201)
async def register_parser(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Register a new TextFSM parser template."""
    rbac.require_permission(actor, "manage", "parser")

    name = body.get("name", "")
    template = body.get("template", "")
    if not name or not template:
        raise HTTPException(status_code=400, detail="'name' and 'template' are required")

    # Validate template syntax
    errors = validate_template(template)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    now = datetime.now(timezone.utc).isoformat()
    parser_id = str(uuid.uuid4())

    await driver.execute_write(
        "MERGE (p:_Parser {name: $name}) "
        "SET p.template = $template, p.platform = $platform, "
        "    p.command = $command, p.description = $description, "
        "    p.updated_at = $now, p.managed_by = 'manual' "
        "ON CREATE SET p.id = $id, p.created_at = $now "
        "RETURN p",
        {
            "name": name,
            "id": parser_id,
            "template": template,
            "platform": body.get("platform", ""),
            "command": body.get("command", ""),
            "description": body.get("description", ""),
            "now": now,
        },
    )
    return {"data": {"id": parser_id, "name": name}}


@router.get("/{parser_id}")
async def get_parser(
    parser_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a parser template with its metadata."""
    result = await driver.execute_read(
        "MATCH (p:_Parser {id: $id}) RETURN p", {"id": parser_id}
    )
    if not result.rows:
        # Try by name
        result = await driver.execute_read(
            "MATCH (p:_Parser {name: $name}) RETURN p", {"name": parser_id}
        )
    if not result.rows:
        raise NodeNotFoundError("_Parser", parser_id)
    return {"data": result.rows[0]["p"]}


@router.post("/{parser_id}/test")
async def test_parser(
    parser_id: str,
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Test a parser against raw command output.

    Body:
        raw_output: str — the raw command output to parse
        template: str — (optional) template content to use instead of stored
    """
    raw_output = body.get("raw_output", "")
    if not raw_output:
        raise HTTPException(status_code=400, detail="'raw_output' is required")

    template_content = body.get("template")

    if not template_content:
        # Load from registry
        result = await driver.execute_read(
            "MATCH (p:_Parser) WHERE p.id = $id OR p.name = $id RETURN p",
            {"id": parser_id},
        )
        if not result.rows:
            raise NodeNotFoundError("_Parser", parser_id)
        template_content = result.rows[0]["p"].get("template", "")

    if not template_content:
        raise HTTPException(status_code=400, detail="No template found or provided")

    try:
        records = parse_output_from_string(template_content, raw_output)
        return {
            "data": {
                "parsed_records": records,
                "record_count": len(records),
                "headers": list(records[0].keys()) if records else [],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse error: {e}")


# --------------------------------------------------------------------------- #
#  Command Bundles                                                             #
# --------------------------------------------------------------------------- #

@router.get("/command-bundles", tags=["Command Bundles"])
async def list_command_bundles(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List registered command bundles."""
    result = await driver.execute_read(
        "MATCH (cb:_CommandBundle) RETURN cb ORDER BY cb.name", {}
    )
    return {"data": [row["cb"] for row in result.rows]}


@router.get("/mappings", tags=["Mappings"])
async def list_mappings(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List mapping definitions."""
    result = await driver.execute_read(
        "MATCH (m:_MappingDef) RETURN m ORDER BY m.name", {}
    )
    return {"data": [row["m"] for row in result.rows]}


# --------------------------------------------------------------------------- #
#  Custom Jinja2 Filters                                                       #
# --------------------------------------------------------------------------- #


@router.get("/filters")
async def list_filters(
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List all custom Jinja2 filters."""
    result = await driver.execute_read(
        "MATCH (f:_JinjaFilter) RETURN f ORDER BY f.name", {}
    )
    filters = [
        {
            "id": row["f"]["id"],
            "name": row["f"]["name"],
            "description": row["f"].get("description", ""),
            "python_source": row["f"]["python_source"],
            "is_active": row["f"].get("is_active", True),
            "created_at": row["f"].get("created_at"),
        }
        for row in result.rows
    ]
    return {"data": filters}


@router.post("/filters", status_code=201)
async def create_filter(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create or update a custom Jinja2 filter. Validates Python source via AST."""
    from packages.ingestion.mappers.custom_filters import CustomFilterLoader

    name = body.get("name", "")
    source = body.get("python_source", "")
    description = body.get("description", "")

    # Validate AST safety
    errors = CustomFilterLoader.validate_filter_source(source)
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    # Test compilation
    try:
        CustomFilterLoader.load_from_source(name, source)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"compilation_error": str(e)})

    # Upsert to Neo4j
    filter_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await driver.execute_write(
        "MERGE (f:_JinjaFilter {name: $name}) "
        "ON CREATE SET f.id = $id, f.created_at = $now "
        "SET f.python_source = $source, f.description = $desc, "
        "    f.is_active = true, f.updated_at = $now, f.updated_by = $user",
        {
            "name": name,
            "id": filter_id,
            "source": source,
            "desc": description,
            "now": now,
            "user": actor.username,
        },
    )
    return {"data": {"name": name, "message": "Filter saved"}}


@router.delete("/filters/{filter_name}", status_code=204)
async def delete_filter(
    filter_name: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a custom filter."""
    await driver.execute_write(
        "MATCH (f:_JinjaFilter {name: $name}) DELETE f",
        {"name": filter_name},
    )


@router.post("/filters/{filter_name}/test")
async def test_filter(
    filter_name: str,
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Test a filter with sample input."""
    from packages.ingestion.mappers.custom_filters import CustomFilterLoader

    # Load filter source from Neo4j
    result = await driver.execute_read(
        "MATCH (f:_JinjaFilter {name: $name}) RETURN f",
        {"name": filter_name},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Filter not found")

    source = result.rows[0]["f"]["python_source"]
    fn = CustomFilterLoader.load_from_source(filter_name, source)

    test_input = body.get("input", "")
    test_args = body.get("args", {})
    try:
        output = fn(test_input, **test_args)
        return {"data": {"input": test_input, "output": output}}
    except Exception as e:
        return {"data": {"input": test_input, "error": str(e)}}


# --------------------------------------------------------------------------- #
#  Test Mapping Chain                                                           #
# --------------------------------------------------------------------------- #


@router.post("/{parser_id}/test-mapping")
async def test_parser_mapping(
    parser_id: str,
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Test the full parse -> map chain. Returns parsed records and generated mutations."""
    import json as _json

    from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine

    raw_output = body.get("raw_output", "")

    # Load parser template
    result = await driver.execute_read(
        "MATCH (p:_Parser) WHERE p.id = $id OR p.name = $id RETURN p",
        {"id": parser_id},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Parser not found")

    template = body.get("template") or result.rows[0]["p"]["template"]
    parser_name = result.rows[0]["p"]["name"]

    # Parse
    records = parse_output_from_string(template, raw_output)

    # Load mapping if available
    mapping_result = await driver.execute_read(
        "MATCH (m:_MappingDef) WHERE m.parser = $parser RETURN m",
        {"parser": parser_name},
    )

    mutations: list[dict[str, Any]] = []
    if mapping_result.rows:
        mapping_def = _json.loads(mapping_result.rows[0]["m"]["definition_json"])
        engine = Jinja2MappingEngine()
        mapped = engine.render_mapping(mapping_def, records)
        mutations = [
            {
                "operation": m.operation,
                "node_type": m.node_type,
                "edge_type": m.edge_type,
                "match_on": m.match_on,
                "attributes": m.attributes,
            }
            for m in mapped.mutations
        ]

    return {
        "data": {
            "records": records,
            "record_count": len(records),
            "mutations": mutations,
        }
    }
