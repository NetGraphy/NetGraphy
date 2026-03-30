---
title: "Attributes"
slug: "attributes"
summary: "Typed, constrained properties on nodes and edges — with metadata for UI rendering, query filtering, and health monitoring."
category: "Core Concepts"
tags: [schema, validation, data-model, attributes]
status: published
---

# Attributes

An **attribute** is a typed property on a node or edge, defined by an `AttributeDefinition` in the YAML schema. Attributes are not free-form key-value pairs — every attribute has a declared type, optional constraints, and three layers of metadata that control how it behaves across the platform.

## Attribute Types

NetGraphy supports a rich set of types designed for network infrastructure modeling:

| Type | Description | Example |
|------|-------------|---------|
| `string` | Short text | Hostname, serial number |
| `text` | Long-form text | Description, notes |
| `integer` | Whole number | VLAN ID, ASN, port number |
| `float` | Decimal number | Latitude, longitude |
| `boolean` | True/false | Enabled, managed |
| `datetime` | ISO 8601 timestamp | Created at, last seen |
| `date` | ISO 8601 date | Install date |
| `json` | Arbitrary structured data | Custom metadata |
| `ip_address` | IPv4 or IPv6 address | Management IP |
| `cidr` | Network prefix notation | 10.0.0.0/24 |
| `mac_address` | Hardware address | Interface MAC |
| `url` | HTTP/HTTPS URL | Documentation link |
| `email` | Email address | Owner contact |
| `enum` | Constrained string from a set | Status, role, platform |
| `reference` | Foreign reference by ID | Pointer to another node |
| `list[string]` | Array of strings | Tags, aliases |
| `list[integer]` | Array of integers | VLAN trunk allowed list |

## Constraints

Each attribute can declare constraints enforced on every create and update operation:

- **`required`** — Must be present and non-null (unless `auto_set` or `default` is configured).
- **`unique`** — No two nodes of the same type can share this value.
- **`indexed`** — Creates a database index for faster lookups and queries.
- **`max_length`** — Maximum character count for string/text fields.
- **`min_value` / `max_value`** — Numeric range bounds.
- **`validation_regex`** — Custom regex pattern the value must match.
- **`enum_values`** — Inline list of allowed values for enum types.
- **`enum_ref`** — Reference to a standalone `EnumTypeDefinition` for shared enums.
- **`default`** — Value applied when the attribute is omitted on creation.
- **`auto_set`** — System-managed field: `"create"` (set once), `"update"` (set on every write), or `"actor"` (set to current user).

## UI Metadata

The `ui` block on each attribute controls how it appears in the generated frontend:

- `list_column` / `list_column_order` — Whether and where to show in list views.
- `search_weight` — Relevance boost for full-text search.
- `form_order` / `form_widget` / `form_visible` — Form rendering hints.
- `badge_colors` — Color map for enum values displayed as badges.
- `filter` — Whether the attribute appears as a filter option in list views.

## Query Metadata

The `query` block controls filtering and reporting behavior:

- `filterable` / `sortable` / `reportable` — Whether the field participates in queries, sorting, and CSV exports.
- `supports_contains`, `supports_prefix`, `supports_range`, `supports_regex` — Which filter operators are available beyond exact match.
- `default_return_field` / `export_default` — Whether to include by default in query results and exports.

## Health Metadata

The `health` block on each attribute controls observability and agent behavior:

- `sensitive` — Masked in agent responses, excluded from search indexes, visible only to admins.
- `required_for_health` — Generates a critical health check alert if this field is empty.
- `editable` — Whether agents and MCP tools can modify this field.
- `searchable` — Whether to include in search and filter tools.
- `display_priority` — Prominence ranking in agent responses.
