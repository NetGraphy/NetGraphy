---
title: "Canonical Schema Model"
slug: "canonical-schema-model"
summary: "The YAML-defined schema model that drives everything — API, UI, MCP tools, agent capabilities, validation, and observability."
category: "Core Concepts"
tags: [schema, yaml, architecture, generation-engine]
status: published
---

# Canonical Schema Model

NetGraphy's schema is the single source of truth for the entire platform. Every node type, edge type, attribute, constraint, permission, tool, capability, validation rule, and health check is derived from YAML schema definitions. There is no hand-written code per model — the schema drives everything.

## Schema Kinds

The schema model defines four top-level definition types, identified by the `kind` field:

### NodeTypeDefinition

Defines a graph node type with its complete metadata. A `NodeTypeDefinition` includes:

- `metadata` — Name, display name, description, icon, color, category, and tags (via `SchemaMetadata`).
- `attributes` — Dictionary of `AttributeDefinition` entries, each with type, constraints, and UI/query/health metadata.
- `mixins` — List of mixin names to include. Mixin attributes merge into the node type at registry load time (node-level attributes take precedence).
- `detail_tabs` — Custom tabs on the detail page showing related nodes via edge types.
- `search` — Primary search field and search field weights.
- `graph` — Visualization hints: default label field, size field, grouping, color, style.
- `api` — Plural name, filterable/sortable fields, default sort, exposure flag.
- `permissions` — Default read/write/delete role requirements.
- `mcp` — Controls MCP tool generation: which CRUD operations to expose, custom tool name prefix.
- `agent` — Controls agent capability generation: custom capabilities, sensitive flag.
- `health` — Observability configuration: freshness hours, min/max count, orphan alerts, severity.
- `query` — Query engine configuration: default fields, page sizes, traversal depth limits.

### EdgeTypeDefinition

Defines a relationship type between nodes. In addition to metadata and attributes, it specifies:

- `source` / `target` — `EdgeSourceTarget` objects listing which node types are allowed on each end.
- `cardinality` — One of `one_to_one`, `one_to_many`, `many_to_one`, `many_to_many`.
- `inverse_name` — Human-readable name for the reverse direction.
- `constraints` — `unique_source`, `unique_target`, `min_count`, `max_count`.
- `health` — Edge-specific health: required flag, alert if missing, max count alerts.
- `query` — Traversal settings: traversable, query alias, existence/count filter support, row expansion.

### MixinDefinition

A reusable attribute group that can be included in multiple node or edge types. Common mixins include `Timestamped` (adds `created_at`, `updated_at`) and `Auditable` (adds `created_by`, `updated_by`). During registry loading, mixin attributes are merged into each referencing type.

### EnumTypeDefinition

A standalone enumeration that can be referenced by attributes via `enum_ref`. Each value carries a name, optional display name, color, and description. Defining enums as standalone types lets multiple node types share the same value set (e.g., a `Status` enum used by Device, Interface, and Circuit).

## The Schema Registry

At startup, the `SchemaRegistry` loads all YAML files from configured directories, parses them into these model objects, resolves mixin references, and validates cross-references (ensuring every edge type references existing node types). The registry serves as the runtime authority — all components query it to understand the data model.

## The Generation Engine

The `GenerationEngine` reads the registry and produces a `GeneratedManifest` containing:

1. **MCP tool definitions** — CRUD, query, find, lookup, and aggregate tools per type.
2. **Agent capability manifest** — Semantic actions (create, find, modify, remove, connect, detect) per type.
3. **Validation rules** — Required fields, type checks, enum enforcement, regex, network type formats.
4. **Observability rules** — Health checks, metrics, alerts, freshness monitors.
5. **Policy artifacts** — RBAC resources, tool authorization, field visibility, agent boundaries.

All outputs are deterministic. The same schema always produces the same manifest. A schema version hash tracks changes, and the engine can diff two manifests to show what changed.
