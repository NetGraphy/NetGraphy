"""Developer Workbench endpoints — template testing, pipeline preview, built-in filter docs.

Provides a safe sandbox for developing and testing Jinja2 templates,
custom filters, TextFSM parsers, and full ingestion pipelines without
touching production data.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_schema_registry
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


@router.get("/builtin-filters")
async def list_builtin_filters(
    actor: AuthContext = Depends(get_auth_context),
):
    """List all built-in Jinja2 filters with their signatures and docstrings."""
    from packages.ingestion.mappers.filters import BUILTIN_FILTERS

    filters = []
    for name, func in sorted(BUILTIN_FILTERS.items()):
        sig = str(inspect.signature(func))
        doc = inspect.getdoc(func) or ""
        filters.append({
            "name": name,
            "signature": sig,
            "description": doc.split("\n")[0] if doc else "",
            "full_doc": doc,
            "category": "built-in",
        })
    return {"data": filters}


@router.post("/render-template")
async def render_template(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Render a Jinja2 template string with provided context data.

    Body:
        template: str — the Jinja2 template string
        context: dict — variables available in the template (e.g. {"parsed": {...}})
        filters: list[str] — optional list of custom filter names to load
    """
    from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine
    from packages.ingestion.mappers.custom_filters import CustomFilterLoader

    template_str = body.get("template", "")
    context = body.get("context", {})
    filter_names = body.get("filters", [])

    if not template_str:
        raise HTTPException(status_code=400, detail="'template' is required")

    engine = Jinja2MappingEngine()

    # Load requested custom filters
    for fname in filter_names:
        result = await driver.execute_read(
            "MATCH (f:_JinjaFilter {name: $name}) RETURN f",
            {"name": fname},
        )
        if result.rows:
            source = result.rows[0]["f"]["python_source"]
            try:
                fn = CustomFilterLoader.load_from_source(fname, source)
                engine.register_filter(fname, fn)
            except Exception as e:
                return {"data": {"error": f"Failed to load filter '{fname}': {e}"}}

    try:
        rendered = engine.resolve_template(template_str, context)
        return {"data": {"rendered": rendered, "template": template_str}}
    except Exception as e:
        return {"data": {"error": str(e), "template": template_str}}


@router.post("/test-pipeline")
async def test_pipeline(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Test the full ingestion pipeline: raw output -> parse -> map -> mutations preview.

    Body:
        raw_output: str — raw command output to parse
        parser_id: str — parser ID or name to use
        mapping_id: str — (optional) mapping ID or name; auto-detected from parser if omitted
        template_override: str — (optional) override parser template
        mapping_override: dict — (optional) override mapping definition
        context: dict — (optional) additional template context variables
    """
    import json as _json

    from packages.ingestion.parsers.textfsm_parser import parse_output_from_string
    from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine
    from packages.ingestion.mappers.custom_filters import CustomFilterLoader

    raw_output = body.get("raw_output", "")
    parser_id = body.get("parser_id", "")
    context = body.get("context", {})

    if not raw_output:
        raise HTTPException(status_code=400, detail="'raw_output' is required")

    # --- Step 1: Load parser template ---
    template_content = body.get("template_override")
    parser_name = parser_id

    if not template_content and parser_id:
        result = await driver.execute_read(
            "MATCH (p:_Parser) WHERE p.id = $id OR p.name = $id RETURN p",
            {"id": parser_id},
        )
        if not result.rows:
            raise HTTPException(status_code=404, detail=f"Parser '{parser_id}' not found")
        template_content = result.rows[0]["p"].get("template", "")
        parser_name = result.rows[0]["p"]["name"]

    if not template_content:
        raise HTTPException(status_code=400, detail="No parser template found or provided")

    # --- Step 2: Parse raw output ---
    try:
        records = parse_output_from_string(template_content, raw_output)
    except Exception as e:
        return {
            "data": {
                "step": "parse",
                "error": str(e),
                "records": [],
                "mutations": [],
            }
        }

    # --- Step 3: Load mapping definition ---
    mapping_def = body.get("mapping_override")

    if not mapping_def:
        mapping_id = body.get("mapping_id", "")
        if mapping_id:
            result = await driver.execute_read(
                "MATCH (m:_MappingDef) WHERE m.id = $id OR m.name = $id RETURN m",
                {"id": mapping_id},
            )
            if result.rows:
                mapping_def = _json.loads(result.rows[0]["m"]["definition_json"])
        else:
            # Auto-detect mapping from parser name
            result = await driver.execute_read(
                "MATCH (m:_MappingDef) WHERE m.parser = $parser RETURN m",
                {"parser": parser_name},
            )
            if result.rows:
                mapping_def = _json.loads(result.rows[0]["m"]["definition_json"])

    # --- Step 4: Apply mapping ---
    mutations: list[dict[str, Any]] = []
    mapping_errors: list[str] = []

    if mapping_def:
        engine = Jinja2MappingEngine()

        # Load all custom filters
        filter_result = await driver.execute_read(
            "MATCH (f:_JinjaFilter) WHERE f.is_active = true RETURN f", {}
        )
        for row in filter_result.rows:
            fname = row["f"]["name"]
            source = row["f"]["python_source"]
            try:
                fn = CustomFilterLoader.load_from_source(fname, source)
                engine.register_filter(fname, fn)
            except Exception:
                pass

        mapped = engine.render_mapping(mapping_def, records, context)
        mutations = [
            {
                "operation": m.operation,
                "node_type": m.node_type,
                "edge_type": m.edge_type,
                "match_on": m.match_on,
                "attributes": m.attributes,
                "source_match": getattr(m, "source_match", None),
                "target_match": getattr(m, "target_match", None),
            }
            for m in mapped.mutations
        ]
        mapping_errors = mapped.errors

    return {
        "data": {
            "step": "complete",
            "records": records,
            "record_count": len(records),
            "headers": list(records[0].keys()) if records else [],
            "mutations": mutations,
            "mutation_count": len(mutations),
            "mapping_errors": mapping_errors,
            "has_mapping": mapping_def is not None,
        }
    }


@router.get("/models")
async def list_models_for_workbench(
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all node types and edge types with their fields for the model explorer."""
    node_types = []
    for nt in registry.list_node_types():
        attrs = []
        for attr_name, attr_def in nt.attributes.items():
            attrs.append({
                "name": attr_name,
                "type": attr_def.type.value if hasattr(attr_def.type, "value") else str(attr_def.type),
                "required": attr_def.required,
                "unique": attr_def.unique,
                "description": attr_def.description,
                "enum_values": attr_def.enum_values,
            })
        node_types.append({
            "name": nt.metadata.name,
            "display_name": nt.metadata.display_name,
            "category": nt.metadata.category,
            "description": nt.metadata.description,
            "color": nt.metadata.color,
            "icon": nt.metadata.icon,
            "attributes": attrs,
        })

    edge_types = []
    for et in registry.list_edge_types():
        attrs = []
        for attr_name, attr_def in et.attributes.items():
            attrs.append({
                "name": attr_name,
                "type": attr_def.type.value if hasattr(attr_def.type, "value") else str(attr_def.type),
                "required": attr_def.required,
                "description": attr_def.description,
            })
        edge_types.append({
            "name": et.metadata.name,
            "display_name": et.metadata.display_name,
            "description": et.metadata.description,
            "source_types": et.source.node_types,
            "target_types": et.target.node_types,
            "cardinality": et.cardinality.value if hasattr(et.cardinality, "value") else str(et.cardinality),
            "inverse_name": et.inverse_name,
            "attributes": attrs,
        })

    return {"data": {"node_types": node_types, "edge_types": edge_types}}
