"""MCP Tool Generator — derives production-grade MCP tool definitions from the schema.

Generates four categories of tools per node type:

1. **CRUD tools** — create, get, update, delete (unchanged from v1)
2. **Query tools** — `query_<entities>` with structured filters, relationship
   traversal, pagination, sorting, and field selection
3. **Convenience tools** — `find_<entities>_by_<relationship>` for common
   traversal patterns; `get_<entity>_by_<field>` for lookups
4. **Aggregate tools** — `count_<entities>` with optional group_by

For edge types, generates connect/disconnect/get_related tools.

The generated tools use the Query AST format for filter inputs. Every filter
path and operator is validated against the schema before execution.
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
from packages.query_engine.models import OPERATORS_BY_TYPE

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


def _build_filter_paths_description(
    nt: NodeTypeDefinition,
    registry: SchemaRegistry,
) -> str:
    """Build a human-readable description of available filter paths for a node type."""
    lines: list[str] = []

    # Direct attribute filters
    direct = []
    for name, attr in nt.attributes.items():
        if attr.query.filterable and not attr.health.sensitive:
            ops = sorted(OPERATORS_BY_TYPE.get(attr.type.value, set()))
            if attr.enum_values:
                direct.append(f"  - {name} ({attr.type.value}, values: {attr.enum_values}, ops: {ops[:4]}...)")
            else:
                direct.append(f"  - {name} ({attr.type.value}, ops: {ops[:4]}...)")
    if direct:
        lines.append("Direct filters:")
        lines.extend(direct[:10])  # Cap for description length
        if len(direct) > 10:
            lines.append(f"  ... and {len(direct) - 10} more")

    # Relationship filters
    rel_lines = []
    for et in registry._edge_types.values():
        if not et.query.traversable:
            continue
        alias = et.query.query_alias or _slugify(et.metadata.name)

        # Check if this node type is a source
        if nt.metadata.name in et.source.node_types:
            for tgt in et.target.node_types:
                tgt_nt = registry.get_node_type(tgt)
                if tgt_nt:
                    key_fields = [
                        n for n, a in tgt_nt.attributes.items()
                        if a.query.filterable and not a.health.sensitive
                    ][:5]
                    if key_fields:
                        rel_lines.append(
                            f"  - {alias}.{tgt}.{{field}} — "
                            f"fields: {key_fields}"
                        )

        # Check if this node type is a target (incoming traversal)
        if nt.metadata.name in et.target.node_types:
            for src in et.source.node_types:
                src_nt = registry.get_node_type(src)
                if src_nt:
                    key_fields = [
                        n for n, a in src_nt.attributes.items()
                        if a.query.filterable and not a.health.sensitive
                    ][:5]
                    if key_fields:
                        rel_lines.append(
                            f"  - {alias}.{src}.{{field}} (incoming) — "
                            f"fields: {key_fields}"
                        )

    if rel_lines:
        lines.append("Relationship filters:")
        lines.extend(rel_lines[:8])
        if len(rel_lines) > 8:
            lines.append(f"  ... and {len(rel_lines) - 8} more")

    return "\n".join(lines)


def _get_relationship_aliases(
    nt: NodeTypeDefinition,
    registry: SchemaRegistry,
) -> list[dict[str, Any]]:
    """Get all relationship aliases for a node type (for convenience tool generation)."""
    aliases: list[dict[str, Any]] = []
    for et in registry._edge_types.values():
        if not et.query.traversable:
            continue
        alias = et.query.query_alias or _slugify(et.metadata.name)

        if nt.metadata.name in et.source.node_types:
            for tgt in et.target.node_types:
                aliases.append({
                    "alias": alias,
                    "edge_type": et.metadata.name,
                    "target_type": tgt,
                    "direction": "outgoing",
                })

        if nt.metadata.name in et.target.node_types:
            for src in et.source.node_types:
                aliases.append({
                    "alias": alias,
                    "edge_type": et.metadata.name,
                    "target_type": src,
                    "direction": "incoming",
                })

    return aliases


# --------------------------------------------------------------------------- #
#  Filter schema for MCP tool inputs                                           #
# --------------------------------------------------------------------------- #

_FILTER_CONDITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Filter path. Direct attribute (e.g., 'status'), "
                "relationship traversal (e.g., 'located_at.Location.city'), "
                "or relationship name for existence/count filters."
            ),
        },
        "operator": {
            "type": "string",
            "enum": [
                "eq", "neq", "contains", "not_contains", "starts_with",
                "ends_with", "in", "not_in", "gt", "gte", "lt", "lte",
                "between", "is_null", "is_not_null",
                "exists", "not_exists",
                "count_eq", "count_gt", "count_gte", "count_lt", "count_lte",
            ],
            "description": "Filter operator. Use 'exists'/'not_exists' for relationship existence. Use 'count_*' for relationship counts.",
        },
        "value": {
            "description": "Filter value. Type depends on field and operator. Arrays for 'in'/'not_in'. [lo,hi] for 'between'. Null for is_null/exists.",
        },
    },
    "required": ["path", "operator"],
}


# --------------------------------------------------------------------------- #
#  Node tool generators                                                        #
# --------------------------------------------------------------------------- #

def generate_node_tools(nt: NodeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate all MCP tool definitions for a node type."""
    if not nt.mcp.exposed:
        return []

    tools: list[dict[str, Any]] = []

    # CRUD tools
    tools.extend(_generate_crud_tools(nt))

    # Query tool (the main production tool)
    tools.extend(_generate_query_tool(nt, registry))

    # Convenience find_by tools
    tools.extend(_generate_find_tools(nt, registry))

    # Lookup tools
    tools.extend(_generate_lookup_tools(nt))

    # Aggregate tools
    tools.extend(_generate_aggregate_tools(nt, registry))

    return tools


def _generate_crud_tools(nt: NodeTypeDefinition) -> list[dict[str, Any]]:
    """Generate basic CRUD tools (create, get, update, delete)."""
    slug = _slugify(nt.metadata.name)
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    properties: dict[str, Any] = {}
    required_fields: list[str] = []

    for attr_name, attr in nt.attributes.items():
        if attr.health.sensitive:
            continue
        properties[attr_name] = _attr_to_json_schema(attr)
        if attr.required:
            required_fields.append(attr_name)

    tools: list[dict[str, Any]] = []

    # create
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
        })

    # get
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

    # update
    if nt.mcp.allow_update:
        update_props: dict[str, Any] = {"id": {"type": "string", "description": f"{display} ID to update"}}
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

    # delete
    if nt.mcp.allow_delete:
        tools.append({
            "name": f"{prefix}delete_{slug}",
            "description": f"Delete a {display} by its ID. This is destructive and cannot be undone.",
            "category": "crud",
            "node_type": nt.metadata.name,
            "operation": "delete",
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": f"{display} ID"}},
                "required": ["id"],
            },
        })

    return tools


def _generate_query_tool(nt: NodeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate the main query tool for a node type.

    This is the primary production tool that supports:
    - Structured filters with full operator set
    - Relationship traversal filters
    - Pagination with safe defaults
    - Sorting
    - Field selection
    """
    slug = _slugify(nt.metadata.name)
    plural = nt.api.plural_name or f"{slug}s"
    plural_slug = plural.replace("-", "_")
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    filter_paths_desc = _build_filter_paths_description(nt, registry)

    # Build sortable fields list
    sortable = [n for n, a in nt.attributes.items() if a.query.sortable]

    max_page = nt.query.max_page_size
    default_page = nt.query.default_page_size

    description = (
        f"Query {display} objects with powerful filtering, relationship traversal, "
        f"sorting, and pagination. Use this instead of list for filtered searches.\n\n"
        f"Available filter paths:\n{filter_paths_desc}\n\n"
        f"Sortable fields: {sortable[:10]}\n"
        f"Default limit: {default_page}, max: {max_page}"
    )

    return [{
        "name": f"{prefix}query_{plural_slug}",
        "description": description,
        "category": "query",
        "node_type": nt.metadata.name,
        "operation": "query",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "array",
                    "items": _FILTER_CONDITION_SCHEMA,
                    "description": (
                        "Array of filter conditions. Each has path, operator, and value. "
                        "Paths can be direct attributes (e.g., 'status') or relationship "
                        "traversals (e.g., 'located_at.Location.city'). "
                        "Use 'exists'/'not_exists' operators for relationship existence. "
                        "Use 'count_*' operators for relationship counts."
                    ),
                },
                "sort": {
                    "type": "string",
                    "description": f"Field to sort by. Sortable: {sortable[:8]}. Prefix with '-' for descending.",
                },
                "sort_direction": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "default": "asc",
                },
                "limit": {
                    "type": "integer",
                    "default": default_page,
                    "maximum": max_page,
                    "description": f"Max results to return (default {default_page}, max {max_page}).",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Number of results to skip for pagination.",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific fields to return. Omit for default fields.",
                },
                "include_total": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include total count of matching results.",
                },
            },
        },
    }]


def _generate_find_tools(nt: NodeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate convenience find_<entities>_by_<relationship> tools.

    These provide a simpler interface for common relationship-based queries.
    For example, find_devices_by_location accepts location_filters and
    device_filters as separate inputs.
    """
    if not nt.query.relationship_filters_enabled:
        return []

    slug = _slugify(nt.metadata.name)
    plural = nt.api.plural_name or f"{slug}s"
    plural_slug = plural.replace("-", "_")
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    tools: list[dict[str, Any]] = []
    aliases = _get_relationship_aliases(nt, registry)

    # Deduplicate by alias (avoid generating multiple tools for same relationship)
    seen_aliases: set[str] = set()

    for rel in aliases:
        alias = rel["alias"]
        if alias in seen_aliases:
            continue
        seen_aliases.add(alias)

        target_type = rel["target_type"]
        target_nt = registry.get_node_type(target_type)
        if not target_nt:
            continue

        target_display = target_nt.metadata.display_name or target_type
        target_slug = _slugify(target_type)

        # Build filter description for the target type
        target_filterable = [
            n for n, a in target_nt.attributes.items()
            if a.query.filterable and not a.health.sensitive
        ]
        entity_filterable = [
            n for n, a in nt.attributes.items()
            if a.query.filterable and not a.health.sensitive
        ]

        description = (
            f"Find {display} objects by their {alias} relationship to {target_display}. "
            f"Supports filtering on both {target_display} attributes "
            f"({target_filterable[:5]}) and {display} attributes ({entity_filterable[:5]})."
        )

        # Shorthand alias for the relationship name in tool name
        # e.g., find_devices_by_location (not find_devices_by_located_at)
        tool_alias = alias.replace("_", "")
        # Use target type slug for cleaner names
        tool_suffix = target_slug

        tools.append({
            "name": f"{prefix}find_{plural_slug}_by_{tool_suffix}",
            "description": description,
            "category": "query",
            "node_type": nt.metadata.name,
            "operation": "find",
            "relationship_alias": alias,
            "target_type": target_type,
            "inputSchema": {
                "type": "object",
                "properties": {
                    f"{alias}_filters": {
                        "type": "array",
                        "items": _FILTER_CONDITION_SCHEMA,
                        "description": (
                            f"Filters on the related {target_display}. "
                            f"Filterable fields: {target_filterable[:8]}. "
                            f"Use simple field names — no relationship prefix needed."
                        ),
                    },
                    f"{slug}_filters": {
                        "type": "array",
                        "items": _FILTER_CONDITION_SCHEMA,
                        "description": (
                            f"Filters on the {display} itself. "
                            f"Filterable fields: {entity_filterable[:8]}."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "default": nt.query.default_page_size,
                        "maximum": nt.query.max_page_size,
                    },
                    "offset": {"type": "integer", "default": 0},
                    "sort": {"type": "string"},
                    "sort_direction": {"type": "string", "enum": ["asc", "desc"], "default": "asc"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "include_total": {"type": "boolean", "default": True},
                },
            },
        })

    return tools


def _generate_lookup_tools(nt: NodeTypeDefinition) -> list[dict[str, Any]]:
    """Generate get_<entity>_by_<field> lookup tools for primary/unique fields."""
    slug = _slugify(nt.metadata.name)
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    tools: list[dict[str, Any]] = []

    # Generate lookup by primary search field
    lookup_fields = set()
    if nt.search.primary_field:
        lookup_fields.add(nt.search.primary_field)

    # Also generate for unique+indexed fields
    for name, attr in nt.attributes.items():
        if attr.unique and attr.indexed and attr.type.value in ("string", "integer"):
            lookup_fields.add(name)

    for field in lookup_fields:
        attr = nt.attributes.get(field)
        if not attr:
            continue

        field_schema = _attr_to_json_schema(attr)

        tools.append({
            "name": f"{prefix}get_{slug}_by_{field}",
            "description": (
                f"Look up a {display} by its {attr.display_name or field}. "
                f"Returns a single exact match."
            ),
            "category": "lookup",
            "node_type": nt.metadata.name,
            "operation": "lookup",
            "inputSchema": {
                "type": "object",
                "properties": {
                    field: {**field_schema, "description": f"Exact {attr.display_name or field} to look up"},
                },
                "required": [field],
            },
        })

    return tools


def _generate_aggregate_tools(nt: NodeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate count_<entities> aggregate tools."""
    slug = _slugify(nt.metadata.name)
    plural = nt.api.plural_name or f"{slug}s"
    plural_slug = plural.replace("-", "_")
    display = nt.metadata.display_name or nt.metadata.name
    prefix = nt.mcp.tool_name_prefix or ""

    # Enum fields that make good group_by candidates
    group_by_fields = [
        name for name, attr in nt.attributes.items()
        if attr.type == AttributeType.ENUM and attr.enum_values
    ]

    description = (
        f"Count {display} objects, optionally filtered and grouped. "
        f"Use this for questions like 'how many devices are active?' or "
        f"'count sites by country'."
    )
    if group_by_fields:
        description += f"\nGroupable fields: {group_by_fields}"

    return [{
        "name": f"{prefix}count_{plural_slug}",
        "description": description,
        "category": "aggregate",
        "node_type": nt.metadata.name,
        "operation": "count",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "array",
                    "items": _FILTER_CONDITION_SCHEMA,
                    "description": "Optional filters to narrow the count.",
                },
                "group_by": {
                    "type": "string",
                    "description": f"Optional field to group counts by. Good candidates: {group_by_fields[:5]}",
                },
            },
        },
    }]


# --------------------------------------------------------------------------- #
#  Edge tool generators                                                        #
# --------------------------------------------------------------------------- #

def generate_edge_tools(et: EdgeTypeDefinition, registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate MCP tool definitions for an edge type."""
    if not et.mcp.exposed:
        return []

    edge_slug = _slugify(et.metadata.name)
    tools: list[dict[str, Any]] = []

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

            edge_props: dict[str, Any] = {}
            for attr_name, attr in et.attributes.items():
                edge_props[attr_name] = _attr_to_json_schema(attr)

            connect_props = {
                "source_id": {"type": "string", "description": f"{src_display} ID"},
                "target_id": {"type": "string", "description": f"{tgt_display} ID"},
                **edge_props,
            }

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


# --------------------------------------------------------------------------- #
#  Main entry point                                                            #
# --------------------------------------------------------------------------- #

def generate_all_mcp_tools(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete MCP tool manifest from the schema registry."""
    tools: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        tools.extend(generate_node_tools(nt, registry))

    for et in registry._edge_types.values():
        tools.extend(generate_edge_tools(et, registry))

    return tools
