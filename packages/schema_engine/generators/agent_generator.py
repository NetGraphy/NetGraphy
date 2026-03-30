"""Agent Capability Generator — derives semantic AI agent capabilities from the schema.

Agent capabilities are higher-level actions than raw CRUD tools. They describe
what an agent CAN DO in domain terms — "onboard a device", "move a device to
a site", "detect orphaned nodes" — rather than just "create_device".

Each capability references the MCP tools it uses and includes example prompts
the agent can handle.
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _display(name: str, nt: NodeTypeDefinition | None) -> str:
    return nt.metadata.display_name or name if nt else name


def generate_node_capabilities(
    nt: NodeTypeDefinition,
    edges: list[EdgeTypeDefinition],
    registry: SchemaRegistry,
) -> list[dict[str, Any]]:
    """Generate agent capabilities for a node type."""
    if not nt.agent.exposed:
        return []

    slug = _slugify(nt.metadata.name)
    display = nt.metadata.display_name or nt.metadata.name
    plural = nt.api.plural_name or f"{slug}s"
    caps: list[dict[str, Any]] = []

    # --- CRUD Capabilities ---

    if nt.mcp.allow_create:
        req_fields = [a.display_name or a.name for a in nt.attributes.values() if a.required]
        caps.append({
            "name": f"create_{slug}",
            "display_name": f"Create {display}",
            "description": f"Add a new {display} to the system. Required fields: {', '.join(req_fields) or 'none'}.",
            "category": "crud",
            "backing_tools": [f"create_{slug}"],
            "required_inputs": [a.name for a in nt.attributes.values() if a.required],
            "example_prompts": [
                f"Create a new {display.lower()}",
                f"Add a {display.lower()} named ...",
            ],
            "safety": "write",
            "node_type": nt.metadata.name,
        })

    caps.append({
        "name": f"find_{slug}",
        "display_name": f"Find {display}",
        "description": f"Search for {display} objects by attributes or list all.",
        "category": "search",
        "backing_tools": [f"list_{plural.replace('-', '_')}", f"search_{plural.replace('-', '_')}"],
        "example_prompts": [
            f"Show me all {display.lower()}s",
            f"Find {display.lower()} where ...",
            f"How many {display.lower()}s are there?",
        ],
        "safety": "read",
        "node_type": nt.metadata.name,
    })

    if nt.mcp.allow_update:
        caps.append({
            "name": f"modify_{slug}",
            "display_name": f"Modify {display}",
            "description": f"Update properties of an existing {display}.",
            "category": "crud",
            "backing_tools": [f"update_{slug}"],
            "example_prompts": [
                f"Change the status of {display.lower()} ...",
                f"Update the description of ...",
            ],
            "safety": "write",
            "node_type": nt.metadata.name,
        })

    if nt.mcp.allow_delete:
        caps.append({
            "name": f"remove_{slug}",
            "display_name": f"Remove {display}",
            "description": f"Delete a {display} from the system.",
            "category": "crud",
            "backing_tools": [f"delete_{slug}"],
            "example_prompts": [f"Delete {display.lower()} ..."],
            "safety": "destructive",
            "node_type": nt.metadata.name,
        })

    # --- Relationship Capabilities ---

    for et in edges:
        is_source = nt.metadata.name in et.source.node_types
        is_target = nt.metadata.name in et.target.node_types
        et_display = et.metadata.display_name or et.metadata.name

        if is_source:
            for tgt_type in et.target.node_types:
                tgt_nt = registry.get_node_type(tgt_type)
                tgt_display = _display(tgt_type, tgt_nt)
                tgt_slug = _slugify(tgt_type)

                caps.append({
                    "name": f"connect_{slug}_to_{tgt_slug}",
                    "display_name": f"Link {display} to {tgt_display}",
                    "description": f"Create a {et_display} relationship from {display} to {tgt_display}.",
                    "category": "relationship",
                    "backing_tools": [f"connect_{slug}_to_{tgt_slug}"],
                    "example_prompts": [
                        f"Connect {display.lower()} to {tgt_display.lower()}",
                        f"Link ... to ...",
                        f"Associate {display.lower()} with {tgt_display.lower()}",
                    ],
                    "safety": "write",
                    "node_type": nt.metadata.name,
                    "edge_type": et.metadata.name,
                })

                caps.append({
                    "name": f"find_{slug}_{tgt_slug}_via_{_slugify(et.metadata.name)}",
                    "display_name": f"Find {tgt_display} for {display}",
                    "description": f"Find all {tgt_display} objects connected to a {display} via {et_display}.",
                    "category": "traversal",
                    "backing_tools": [f"get_{slug}_{tgt_slug}_via_{_slugify(et.metadata.name)}"],
                    "example_prompts": [
                        f"What {tgt_display.lower()}s are connected to {display.lower()} ...?",
                        f"Show neighbors of ...",
                    ],
                    "safety": "read",
                    "node_type": nt.metadata.name,
                    "edge_type": et.metadata.name,
                })

    # --- Health/Audit Capabilities ---

    if nt.health.alert_on_orphan:
        caps.append({
            "name": f"detect_orphaned_{slug}",
            "display_name": f"Detect Orphaned {display}",
            "description": f"Find {display} nodes with no relationships — potentially stale or misconfigured.",
            "category": "health",
            "backing_tools": [],
            "example_prompts": [
                f"Find orphaned {display.lower()}s",
                f"Are there any {display.lower()}s without connections?",
            ],
            "safety": "read",
            "node_type": nt.metadata.name,
        })

    # Check for required edges
    for et in edges:
        if et.health.required and nt.metadata.name in et.source.node_types:
            for tgt_type in et.target.node_types:
                tgt_display = _display(tgt_type, registry.get_node_type(tgt_type))
                caps.append({
                    "name": f"detect_{slug}_without_{_slugify(tgt_type)}",
                    "display_name": f"Detect {display} without {tgt_display}",
                    "description": f"Find {display} nodes missing the required {et.metadata.name} relationship to {tgt_display}.",
                    "category": "health",
                    "backing_tools": [],
                    "example_prompts": [
                        f"Which {display.lower()}s are missing a {tgt_display.lower()}?",
                        f"Find {display.lower()}s without {tgt_display.lower()}",
                    ],
                    "safety": "read",
                    "node_type": nt.metadata.name,
                })

    # Enum-based audit capabilities
    enum_attrs = [a for a in nt.attributes.values() if a.enum_values and a.ui.filter]
    for attr in enum_attrs[:3]:  # Limit to prevent explosion
        attr_display = attr.display_name or attr.name
        caps.append({
            "name": f"audit_{slug}_by_{attr.name}",
            "display_name": f"Audit {display} by {attr_display}",
            "description": f"Break down {display} counts by {attr_display} ({', '.join(attr.enum_values or [])}).",
            "category": "audit",
            "backing_tools": [f"list_{plural.replace('-', '_')}"],
            "example_prompts": [
                f"How many {display.lower()}s are in each {attr_display.lower()}?",
                f"Show {display.lower()} breakdown by {attr_display.lower()}",
            ],
            "safety": "read",
            "node_type": nt.metadata.name,
        })

    # Custom capabilities from schema
    for cap_name in nt.agent.capabilities:
        caps.append({
            "name": f"{slug}_{cap_name}",
            "display_name": f"{cap_name.replace('_', ' ').title()} {display}",
            "description": f"Custom capability: {cap_name} for {display}.",
            "category": "custom",
            "backing_tools": [],
            "example_prompts": [f"{cap_name.replace('_', ' ')} {display.lower()}"],
            "safety": "write",
            "node_type": nt.metadata.name,
        })

    return caps


def generate_all_capabilities(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete agent capability manifest from the schema registry."""
    caps: list[dict[str, Any]] = []
    edge_list = list(registry._edge_types.values())

    for nt in registry._node_types.values():
        related_edges = [
            et for et in edge_list
            if nt.metadata.name in et.source.node_types or nt.metadata.name in et.target.node_types
        ]
        caps.extend(generate_node_capabilities(nt, related_edges, registry))

    return caps
