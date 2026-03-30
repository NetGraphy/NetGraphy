"""MCP Tool Generator — derives MCP tool definitions from the schema registry.

For each node type with mcp.exposed=true, generates:
- create_<node>, get_<node>, list_<nodes>, update_<node>, delete_<node>, search_<nodes>

For each edge type with mcp.exposed=true, generates:
- connect_<source>_to_<target>, disconnect_<source>_from_<target>, get_related_<targets>

Tool inputs are derived from schema attributes and constraints. Tool outputs
follow a consistent structured format.
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    AttributeDefinition,
    AttributeType,
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry

# Map AttributeType to JSON Schema types for MCP tool inputs
_TYPE_MAP: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "text": {"type": "string"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "boolean": {"type": "boolean"},
    "datetime": {"type": "string", "format": "date-time"},
    "date": {"type": "string", "format": "date"},
    "json": {"type": "object"},
    "ip_address": {"type": "string", "format": "ipv4"},
    "cidr": {"type": "string"},
    "mac_address": {"type": "string", "pattern": "^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"},
    "url": {"type": "string", "format": "uri"},
    "email": {"type": "string", "format": "email"},
    "enum": {"type": "string"},
    "reference": {"type": "string"},
    "list[string]": {"type": "array", "items": {"type": "string"}},
    "list[integer]": {"type": "array", "items": {"type": "integer"}},
}


def _slugify(name: str) -> str:
    """Convert PascalCase/camelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _attr_to_json_schema(attr: AttributeDefinition) -> dict[str, Any]:
    """Convert an AttributeDefinition to a JSON Schema property."""
    schema = dict(_TYPE_MAP.get(attr.type.value, {"type": "string"}))
    if attr.description:
        schema["description"] = attr.description
    if attr.enum_values:
        schema["enum"] = attr.enum_values
    if attr.max_length:
        schema["maxLength"] = attr.max_length
    if attr.min_value is not None:
        schema["minimum"] = attr.min_value
    if attr.max_value is not None:
        schema["maximum"] = attr.max_value
    if attr.default is not None:
        schema["default"] = attr.default
    return schema


def generate_node_tools(nt: NodeTypeDefinition) -> list[dict[str, Any]]:
    """Generate MCP tool definitions for a node type."""
    if not nt.mcp.exposed:
        return []

    slug = _slugify(nt.metadata.name)
    plural = nt.api.plural_name or f"{slug}s"
    plural_slug = plural.replace("-", "_")
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    # Build input schema from attributes
    properties: dict[str, Any] = {}
    required_fields: list[str] = []
    searchable_fields: list[str] = []
    filterable_fields: list[str] = nt.api.filterable_fields.copy()

    for attr_name, attr in nt.attributes.items():
        if attr.health.sensitive:
            continue  # Don't expose sensitive fields in tool inputs
        properties[attr_name] = _attr_to_json_schema(attr)
        if attr.required:
            required_fields.append(attr_name)
        if attr.health.searchable and attr.indexed:
            searchable_fields.append(attr_name)

    tools: list[dict[str, Any]] = []

    # create_<node>
    if nt.mcp.allow_create:
        tools.append({
            "name": f"{prefix}create_{slug}",
            "description": f"Create a new {display}. {nt.metadata.description or ''}".strip(),
            "category": "crud",
            "node_type": nt.metadata.name,
            "operation": "create",
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required_fields,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": f"ID of the created {display}"},
                    "success": {"type": "boolean"},
                },
            },
        })

    # get_<node>
    tools.append({
        "name": f"{prefix}get_{slug}",
        "description": f"Get a {display} by its ID.",
        "category": "crud",
        "node_type": nt.metadata.name,
        "operation": "get",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": f"{display} ID"}},
            "required": ["id"],
        },
    })

    # list_<nodes>
    list_props: dict[str, Any] = {
        "page": {"type": "integer", "default": 1, "description": "Page number"},
        "page_size": {"type": "integer", "default": 25, "description": "Results per page"},
    }
    for f in filterable_fields:
        if f in properties:
            list_props[f] = {**properties[f], "description": f"Filter by {f}"}

    tools.append({
        "name": f"{prefix}list_{plural_slug}",
        "description": f"List {display} objects with optional filtering and pagination.",
        "category": "crud",
        "node_type": nt.metadata.name,
        "operation": "list",
        "inputSchema": {"type": "object", "properties": list_props},
    })

    # update_<node>
    if nt.mcp.allow_update:
        update_props = {"id": {"type": "string", "description": f"{display} ID to update"}}
        for attr_name, attr in nt.attributes.items():
            if attr.health.editable and not attr.health.sensitive:
                update_props[attr_name] = _attr_to_json_schema(attr)
        tools.append({
            "name": f"{prefix}update_{slug}",
            "description": f"Update an existing {display}. Only provided fields are changed.",
            "category": "crud",
            "node_type": nt.metadata.name,
            "operation": "update",
            "inputSchema": {
                "type": "object",
                "properties": update_props,
                "required": ["id"],
            },
        })

    # delete_<node>
    if nt.mcp.allow_delete:
        tools.append({
            "name": f"{prefix}delete_{slug}",
            "description": f"Delete a {display} by its ID.",
            "category": "crud",
            "node_type": nt.metadata.name,
            "operation": "delete",
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": f"{display} ID"}},
                "required": ["id"],
            },
        })

    # search_<nodes>
    if nt.mcp.allow_search and searchable_fields:
        search_props: dict[str, Any] = {
            "query": {"type": "string", "description": f"Search query across {', '.join(searchable_fields)}"},
            "limit": {"type": "integer", "default": 10},
        }
        tools.append({
            "name": f"{prefix}search_{plural_slug}",
            "description": f"Search for {display} objects by keyword across searchable fields.",
            "category": "search",
            "node_type": nt.metadata.name,
            "operation": "search",
            "inputSchema": {
                "type": "object",
                "properties": search_props,
                "required": ["query"],
            },
        })

    return tools


def generate_edge_tools(et: EdgeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate MCP tool definitions for an edge type."""
    if not et.mcp.exposed:
        return []

    edge_slug = _slugify(et.metadata.name)
    tools: list[dict[str, Any]] = []

    # Generate connect/disconnect for each source→target pair
    for src_type in et.source.node_types:
        for tgt_type in et.target.node_types:
            src_slug = _slugify(src_type)
            tgt_slug = _slugify(tgt_type)
            src_display = src_type
            tgt_display = tgt_type

            nt = registry.get_node_type(src_type)
            if nt and nt.metadata.display_name:
                src_display = nt.metadata.display_name
            nt_tgt = registry.get_node_type(tgt_type)
            if nt_tgt and nt_tgt.metadata.display_name:
                tgt_display = nt_tgt.metadata.display_name

            # Edge attribute properties
            edge_props: dict[str, Any] = {}
            for attr_name, attr in et.attributes.items():
                edge_props[attr_name] = _attr_to_json_schema(attr)

            connect_props = {
                "source_id": {"type": "string", "description": f"{src_display} ID"},
                "target_id": {"type": "string", "description": f"{tgt_display} ID"},
                **edge_props,
            }

            # connect_<source>_to_<target>
            if et.mcp.allow_create:
                tools.append({
                    "name": f"connect_{src_slug}_to_{tgt_slug}",
                    "description": f"Create a {et.metadata.display_name or et.metadata.name} relationship from {src_display} to {tgt_display}.",
                    "category": "relationship",
                    "edge_type": et.metadata.name,
                    "operation": "connect",
                    "inputSchema": {
                        "type": "object",
                        "properties": connect_props,
                        "required": ["source_id", "target_id"],
                    },
                })

            # disconnect_<source>_from_<target>
            if et.mcp.allow_delete:
                tools.append({
                    "name": f"disconnect_{src_slug}_from_{tgt_slug}",
                    "description": f"Remove the {et.metadata.display_name or et.metadata.name} relationship between {src_display} and {tgt_display}.",
                    "category": "relationship",
                    "edge_type": et.metadata.name,
                    "operation": "disconnect",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string", "description": f"{src_display} ID"},
                            "target_id": {"type": "string", "description": f"{tgt_display} ID"},
                        },
                        "required": ["source_id", "target_id"],
                    },
                })

            # get_related_<targets>
            tools.append({
                "name": f"get_{src_slug}_{tgt_slug}_via_{edge_slug}",
                "description": f"Find all {tgt_display} objects related to a {src_display} via {et.metadata.name}.",
                "category": "traversal",
                "edge_type": et.metadata.name,
                "operation": "get_related",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "description": f"{src_display} ID"},
                    },
                    "required": ["source_id"],
                },
            })

    return tools


def generate_all_mcp_tools(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete MCP tool manifest from the schema registry."""
    tools: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        tools.extend(generate_node_tools(nt))

    for et in registry._edge_types.values():
        tools.extend(generate_edge_tools(et, registry))

    return tools
