---
title: "Generated Tool Reference"
slug: "generated-tool-reference"
summary: "Reference for all MCP tools auto-generated from the schema"
category: "Reference"
tags: [mcp, tools, ai, reference]
status: published
---

# Generated Tool Reference

NetGraphy automatically generates MCP (Model Context Protocol) tools from the schema. These tools are used by the AI assistant and can be called by external agents via the API.

## Tool Categories

### Query Tools — `query_<entities>`

The primary production tool for each node type. Supports structured filters with relationship traversal, pagination, sorting, and field selection.

**Example:** `query_devices`

```json
{
  "filters": [
    {"path": "status", "operator": "eq", "value": "active"},
    {"path": "located_in.Location.city", "operator": "contains", "value": "Dallas"}
  ],
  "sort": "hostname",
  "limit": 50,
  "fields": ["hostname", "status", "role", "management_ip"]
}
```

**Supported filter operators by type:**

| Type | Operators |
|---|---|
| String | eq, neq, contains, not_contains, starts_with, ends_with, regex, in, not_in, is_null, is_not_null |
| Enum | eq, neq, in, not_in, is_null, is_not_null |
| Integer/Float | eq, neq, gt, gte, lt, lte, between, in, is_null, is_not_null |
| Boolean | eq, neq, is_null, is_not_null |
| DateTime | eq, neq, gt, gte, lt, lte, between, is_null, is_not_null |
| Relationship | exists, not_exists, count_eq, count_gt, count_gte, count_lt, count_lte |

### Find Tools — `find_<entities>_by_<relationship>`

Convenience tools for common relationship-based lookups with simpler input.

**Example:** `find_devices_by_location`

```json
{
  "located_in_filters": [
    {"path": "city", "operator": "contains", "value": "Dallas"}
  ],
  "device_filters": [
    {"path": "status", "operator": "eq", "value": "active"}
  ],
  "limit": 50
}
```

### Count Tools — `count_<entities>`

Aggregate tools for counting objects with optional grouping.

**Example:** `count_devices`

```json
{
  "filters": [
    {"path": "status", "operator": "eq", "value": "active"}
  ],
  "group_by": "role"
}
```

### Lookup Tools — `get_<entity>_by_<field>`

Exact-match lookup by primary or unique fields.

**Example:** `get_device_by_hostname`

```json
{
  "hostname": "DAL-COR-RTR01"
}
```

### CRUD Tools

| Tool | Description |
|---|---|
| `create_<entity>` | Create a new object with schema validation |
| `get_<entity>` | Get an object by ID |
| `update_<entity>` | Partial update of an object's properties |
| `delete_<entity>` | Delete an object (destructive, requires confirmation) |

### Relationship Tools

| Tool | Description |
|---|---|
| `connect_<source>_to_<target>` | Create an edge between two nodes |
| `disconnect_<source>_from_<target>` | Remove an edge between two nodes |
| `get_<source>_<target>_via_<edge>` | Find related nodes via a specific edge type |

## Filter Path Syntax

Filter paths support three formats:

1. **Direct attribute**: `"status"` — filter on the root node's attribute
2. **Relationship traversal**: `"located_in.Location.city"` — traverse an edge, filter on the target's attribute
3. **Relationship existence**: `"has_interface"` with `exists`/`not_exists` operator

## Tool Authorization

Every tool includes auth metadata:
- `required_permission` — the permission needed to call this tool
- `destructive` — whether this tool modifies or deletes data
- `requires_confirmation` — whether the agent must ask the user before executing

The AI assistant filters tools by the acting user's permissions before presenting them to the model. Tools the user cannot use are never visible to the LLM.

## Viewing Available Tools

Browse all generated tools at **Admin > Generated Artifacts > MCP Tools** or via the API:

```
GET /api/v1/generated/mcp-tools
GET /api/v1/generated/mcp-tools?category=query&node_type=Device
GET /api/v1/generated/mcp-tools/query_devices
```
