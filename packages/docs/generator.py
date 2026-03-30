"""Schema-Driven Documentation Generator — creates starter docs from the schema registry.

Generates baseline documentation pages for:
- Each node type (purpose, attributes, relationships, tools, validation)
- Each edge type (purpose, endpoints, cardinality, constraints)
- Each category (overview with all types in that category)
- Platform overview and getting started guides

Generated docs are starting points — authors can enrich, override, and extend them.
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    AttributeDefinition,
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower().replace("_", "-")


def _attr_table(attrs: dict[str, AttributeDefinition]) -> str:
    """Generate a markdown table of attributes."""
    lines = ["| Field | Type | Required | Description |", "| --- | --- | --- | --- |"]
    for name, attr in sorted(attrs.items()):
        req = "Yes" if attr.required else ""
        desc = attr.description or attr.display_name or ""
        type_str = attr.type.value
        if attr.enum_values:
            type_str = f"enum: {', '.join(attr.enum_values[:5])}{'...' if len(attr.enum_values) > 5 else ''}"
        lines.append(f"| `{name}` | {type_str} | {req} | {desc} |")
    return "\n".join(lines)


def generate_node_type_doc(nt: NodeTypeDefinition, edges: list[EdgeTypeDefinition]) -> dict[str, Any]:
    """Generate a documentation page for a node type."""
    display = nt.metadata.display_name or nt.metadata.name
    slug = f"reference/node-types/{_slugify(nt.metadata.name)}"

    # Build relationships section
    rel_lines = []
    for et in edges:
        if nt.metadata.name in et.source.node_types:
            targets = ", ".join(et.target.node_types)
            rel_lines.append(f"- **{et.metadata.name}** -> {targets} ({et.cardinality.value})")
        if nt.metadata.name in et.target.node_types:
            sources = ", ".join(et.source.node_types)
            rel_lines.append(f"- **{et.metadata.name}** <- {sources} ({et.cardinality.value})")

    content = f"""# {display}

{nt.metadata.description or f'A {display} node in the NetGraphy graph.'}

## Overview

**Category:** {nt.metadata.category or 'Uncategorized'}
**Internal Name:** `{nt.metadata.name}`

## Attributes

{_attr_table(nt.attributes)}

## Relationships

{chr(10).join(rel_lines) if rel_lines else 'No relationships defined.'}

## Generated Tools

The following MCP tools are automatically generated for this type:

- `create_{_slugify(nt.metadata.name).replace('-', '_')}` — Create a new {display}
- `get_{_slugify(nt.metadata.name).replace('-', '_')}` — Get by ID
- `list_{(nt.api.plural_name or _slugify(nt.metadata.name) + 's').replace('-', '_')}` — List with filtering
- `update_{_slugify(nt.metadata.name).replace('-', '_')}` — Update properties
- `delete_{_slugify(nt.metadata.name).replace('-', '_')}` — Delete

## Validation Rules

{_validation_summary(nt)}

## Permissions

| Operation | Default Role |
| --- | --- |
| Read | {nt.permissions.default_read} |
| Write | {nt.permissions.default_write} |
| Delete | {nt.permissions.default_delete} |
"""

    return {
        "title": display,
        "slug": slug,
        "summary": nt.metadata.description or f"Reference documentation for the {display} node type.",
        "category": "Reference",
        "content": content,
        "status": "published",
        "tags": ["reference", "node-type", nt.metadata.category or "general"],
        "related_node_types": [nt.metadata.name],
        "nav_order": 500,
    }


def _validation_summary(nt: NodeTypeDefinition) -> str:
    """Generate a validation summary for a node type."""
    lines = []
    for name, attr in nt.attributes.items():
        rules = []
        if attr.required:
            rules.append("required")
        if attr.unique:
            rules.append("unique")
        if attr.enum_values:
            rules.append(f"one of: {', '.join(attr.enum_values[:5])}")
        if attr.validation_regex:
            rules.append(f"matches `{attr.validation_regex}`")
        if rules:
            lines.append(f"- **{name}**: {', '.join(rules)}")
    return "\n".join(lines) if lines else "No special validation rules."


def generate_edge_type_doc(et: EdgeTypeDefinition) -> dict[str, Any]:
    """Generate a documentation page for an edge type."""
    display = et.metadata.display_name or et.metadata.name
    slug = f"reference/edge-types/{_slugify(et.metadata.name)}"

    content = f"""# {display}

{et.metadata.description or f'A {display} relationship in the NetGraphy graph.'}

## Overview

**Internal Name:** `{et.metadata.name}`
**Cardinality:** {et.cardinality.value}
{f'**Inverse:** `{et.inverse_name}`' if et.inverse_name else ''}

## Endpoints

| Direction | Node Types |
| --- | --- |
| Source | {', '.join(et.source.node_types)} |
| Target | {', '.join(et.target.node_types)} |

## Attributes

{_attr_table(et.attributes) if et.attributes else 'This edge type has no attributes.'}

## Constraints

- Unique source: {'Yes' if et.constraints.unique_source else 'No'}
- Unique target: {'Yes' if et.constraints.unique_target else 'No'}
{f'- Min count: {et.constraints.min_count}' if et.constraints.min_count else ''}
{f'- Max count: {et.constraints.max_count}' if et.constraints.max_count else ''}
"""

    return {
        "title": display,
        "slug": slug,
        "summary": et.metadata.description or f"Reference for the {display} edge type.",
        "category": "Reference",
        "content": content,
        "status": "published",
        "tags": ["reference", "edge-type"],
        "related_edge_types": [et.metadata.name],
        "nav_order": 600,
    }


def generate_overview_docs() -> list[dict[str, Any]]:
    """Generate platform overview documentation pages."""
    return [
        {
            "title": "Welcome to NetGraphy",
            "slug": "overview",
            "summary": "Introduction to the NetGraphy platform.",
            "category": "Overview",
            "nav_order": 1,
            "status": "published",
            "content": """# Welcome to NetGraphy

NetGraphy is a **graph-native, schema-driven, agent-powered network source of truth**.

## What Makes NetGraphy Different

- **Graph-First**: Network infrastructure is naturally a graph. NetGraphy models it that way from the start.
- **Schema-Driven**: Define your data model in YAML. The platform automatically generates APIs, tools, validation, and observability.
- **Agent-Native**: A built-in AI assistant uses generated tools to help you manage your infrastructure.
- **GitOps-Ready**: Schemas, parsers, templates, and config contexts all sync from Git repositories.

## Key Concepts

- **Node Types**: Entities in your network (Devices, Interfaces, Prefixes, VLANs, etc.)
- **Edge Types**: Relationships between entities (CONNECTED_TO, HAS_INTERFACE, IP_ON_INTERFACE)
- **Schema**: The YAML definitions that drive everything — APIs, UI, tools, validation
- **Generated Tools**: MCP-compatible tools automatically created from your schema
- **Agent Capabilities**: Semantic actions the AI assistant can perform on your behalf
- **Infrastructure as Code**: Config backup, compliance, and device transformation

## Getting Started

1. Log in with your credentials
2. Explore the dashboard
3. Browse your data model in the Schema Explorer
4. Try the AI Assistant (click the "AI" button in the header)
5. Review generated artifacts under Administration > Generated Artifacts
""",
        },
        {
            "title": "Getting Started",
            "slug": "getting-started",
            "summary": "Quick start guide for new NetGraphy users.",
            "category": "Getting Started",
            "nav_order": 2,
            "status": "published",
            "content": """# Getting Started

## First Steps

### 1. Log In
Use the credentials provided by your administrator. The default admin account is `admin`.

### 2. Explore the Data Model
Navigate to **Schema Explorer** in the sidebar to see all available node types and edge types.

### 3. Create Your First Object
Click any node type in the sidebar (e.g., **Devices**) and click **Create New**.

### 4. Use the AI Assistant
Click the **AI** button in the top bar to open the chat panel. Ask questions like:
- "Show me all devices"
- "What node types are available?"
- "Create a new device called router1"

### 5. Query the Graph
Open the **Query Workbench** to write Cypher queries against your graph data.

## Key Navigation

| Section | Purpose |
| --- | --- |
| Dashboard | Platform overview and statistics |
| Schema Explorer | Browse node and edge type definitions |
| Dev Workbench | Test parsers, filters, and templates |
| Graph Explorer | Visual graph traversal |
| Query Workbench | Cypher query editor |
| Infrastructure as Code | Config management and compliance |
| Administration | Users, groups, permissions, AI config |
""",
        },
        {
            "title": "Core Concepts",
            "slug": "core-concepts",
            "summary": "Understanding the graph-first, schema-driven architecture.",
            "category": "Core Concepts",
            "nav_order": 10,
            "status": "published",
            "content": """# Core Concepts

## Graph-First Modeling

NetGraphy stores all infrastructure data as a property graph in Neo4j. This means:

- **Nodes** represent entities (Device, Interface, Prefix, VLAN, etc.)
- **Edges** represent relationships (CONNECTED_TO, HAS_INTERFACE, IP_IN_PREFIX)
- **Properties** are key-value pairs on both nodes and edges

Unlike relational systems, relationships are first-class citizens with their own attributes, constraints, and cardinality rules.

## Schema as Source of Truth

Every node type and edge type is defined in YAML schema files. The schema drives:

- **Data APIs**: CRUD endpoints are generated automatically
- **UI**: List, detail, create, and edit views are generated from schema metadata
- **MCP Tools**: AI-usable tool definitions with input/output schemas
- **Agent Capabilities**: Semantic actions the AI can perform
- **Validation**: Required fields, enums, uniqueness, cardinality
- **Observability**: Health checks, metrics, and alerts
- **Permissions**: Per-model read/write/delete defaults

## Generated Artifacts

When you define a schema, NetGraphy automatically generates:

| Artifact | Description |
| --- | --- |
| MCP Tools | create, get, list, update, delete, search per type |
| Agent Capabilities | Semantic actions (onboard, detect orphans, audit) |
| Validation Rules | Required fields, enums, cardinality, format checks |
| Observability Rules | Metrics, health checks, alerts |
| RBAC Resources | Permission definitions per type |

## Mixins

Reusable attribute groups (like `lifecycle_mixin` for created_at/updated_at) that can be included in any node type.
""",
        },
    ]


def generate_all_docs(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete starter documentation from the schema."""
    docs: list[dict[str, Any]] = []

    # Platform overview docs
    docs.extend(generate_overview_docs())

    # Node type reference docs
    all_edges = list(registry._edge_types.values())
    for nt in sorted(registry._node_types.values(), key=lambda x: x.metadata.name):
        related_edges = [
            et for et in all_edges
            if nt.metadata.name in et.source.node_types or nt.metadata.name in et.target.node_types
        ]
        docs.append(generate_node_type_doc(nt, related_edges))

    # Edge type reference docs
    for et in sorted(registry._edge_types.values(), key=lambda x: x.metadata.name):
        docs.append(generate_edge_type_doc(et))

    return docs
