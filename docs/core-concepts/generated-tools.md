---
title: "Generated MCP Tools"
slug: "generated-tools"
summary: "Schema-derived MCP tools that let AI agents and automation interact with the graph — CRUD, query, find, lookup, and aggregate."
category: "Core Concepts"
tags: [mcp, ai, tools, schema, generation-engine]
status: published
---

# Generated MCP Tools

NetGraphy automatically generates [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) tool definitions from the YAML schema. These tools give AI agents and automation systems a structured, type-safe interface to the graph. No tool is hand-written — the MCP generator reads each `NodeTypeDefinition` and `EdgeTypeDefinition` in the schema registry and produces a complete tool manifest.

## Tool Categories

### CRUD Tools

For each exposed node type, the generator produces up to four tools:

- **`create_<entity>`** — Create a new node. Input schema includes all non-sensitive attributes with their types, constraints, and descriptions. Required fields are enforced.
- **`get_<entity>`** — Retrieve a single node by its ID.
- **`update_<entity>`** — Update specific fields on an existing node. Only editable, non-sensitive fields appear in the input schema. Only provided fields are changed.
- **`delete_<entity>`** — Delete a node by ID. Marked as destructive; requires confirmation when invoked by an agent.

Which CRUD operations are generated depends on the `mcp` metadata block: `allow_create`, `allow_update`, and `allow_delete` can each be toggled independently.

### Query Tools

The most powerful generated tool is **`query_<entities>`**. It accepts structured filters, pagination, sorting, and field selection. The tool description includes the full list of available filter paths so agents know what they can query.

**Filter paths** support four patterns:

1. **Direct attribute** — Filter on the node's own properties. Example: `{"path": "status", "operator": "eq", "value": "active"}`.
2. **Relationship traversal** — Filter through an edge to a related node's attributes. Example: `{"path": "located_in.Location.city", "operator": "eq", "value": "London"}`. The path format is `<edge_alias>.<TargetType>.<field>`.
3. **Existence filter** — Check whether a relationship exists or does not. Example: `{"path": "has_interface", "operator": "exists"}`.
4. **Count filter** — Filter by the number of relationships. Example: `{"path": "has_interface", "operator": "count_gte", "value": 4}`.

Available operators per field type include `eq`, `neq`, `contains`, `starts_with`, `ends_with`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `between`, `is_null`, and `is_not_null`. The generator restricts operators to those valid for each attribute type.

### Convenience Find Tools

**`find_<entities>_by_<target_type>`** tools provide a simpler interface for common relationship-based queries. Instead of constructing traversal filter paths manually, the agent provides separate filter arrays for the source entity and the related entity. For example, `find_devices_by_location` accepts `located_in_filters` (filters on the Location) and `device_filters` (filters on the Device itself).

These are generated for every traversable relationship on the node type, deduplicated by relationship alias.

### Lookup Tools

**`get_<entity>_by_<field>`** tools provide single-record lookups on primary or unique fields. If a `Device` type has `hostname` marked as the primary search field and unique+indexed, the generator produces `get_device_by_hostname`. These return a single exact match.

### Aggregate Tools

**`count_<entities>`** tools count nodes with optional filters and grouping. The `group_by` parameter accepts enum fields, enabling questions like "how many devices per status?" The tool description lists which fields make good group-by candidates.

### Edge Tools

For each exposed edge type and each valid source/target combination, the generator produces:

- **`connect_<source>_to_<target>`** — Create a relationship, optionally with edge properties.
- **`disconnect_<source>_from_<target>`** — Remove a relationship. Marked as destructive.
- **`get_<source>_<target>_via_<edge>`** — Find all target nodes related to a source node via this edge type.

## Authorization Enrichment

After generation, the engine enriches every tool with authorization metadata from the policy generator: `required_permission`, `required_role`, `destructive` flag, `requires_confirmation`, and `agent_callable`. This metadata is evaluated at runtime before tool execution.
