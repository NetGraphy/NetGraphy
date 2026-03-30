---
title: "Schema Reference"
slug: "schema-reference"
summary: "Complete reference for YAML schema definition syntax"
category: "Reference"
tags: [schema, yaml, reference]
status: published
---

# Schema Reference

This is the complete reference for NetGraphy's YAML schema definition language. All platform behavior — APIs, UI, tools, validation, observability — derives from these definitions.

## Schema Kinds

Every YAML schema file must declare a `kind`:

| Kind | Description |
|---|---|
| `NodeType` | Defines a graph node type (e.g., Device, Interface, Location) |
| `EdgeType` | Defines a relationship type between nodes (e.g., LOCATED_IN, HAS_INTERFACE) |
| `Mixin` | Reusable attribute group included in node/edge types |
| `EnumType` | Standalone enumeration for controlled vocabularies |

## NodeType Definition

```yaml
kind: NodeType
version: v1
metadata:
  name: Device                    # Required. PascalCase identifier.
  display_name: Device            # Human-readable name for UI.
  description: "A network device" # Shown in schema explorer and docs.
  icon: server                    # Icon identifier for UI rendering.
  color: "#3B82F6"                # Hex color for graph visualization.
  category: Infrastructure        # Groups types in sidebar navigation.
  tags: [network, core]           # Searchable tags.

attributes:
  hostname:
    type: string                  # See Attribute Types below.
    display_name: Hostname        # UI label.
    required: true                # Enforced on create.
    unique: true                  # Enforced across all instances.
    indexed: true                 # Creates Neo4j index for fast lookup.
    max_length: 255               # String length constraint.
    description: "Device hostname"
    validation_regex: "^[a-zA-Z]" # Regex validation pattern.
    ui:                           # UI rendering hints.
      list_column: true
      list_column_order: 1
      search_weight: 10
      form_order: 1
      filter: true
    query:                        # Query/report generation hints.
      filterable: true
      sortable: true
      reportable: true
      supports_contains: true
      supports_regex: true
      export_default: true
    health:                       # Observability hints.
      sensitive: false
      editable: true
      searchable: true

mixins:
  - lifecycle_mixin               # Adds created_at, updated_at, created_by, updated_by
  - provenance_mixin              # Adds source_type, source_id, last_verified_at

search:
  enabled: true
  primary_field: hostname
  search_fields: [hostname, management_ip, serial_number]

graph:
  default_label_field: hostname
  group_by: role

api:
  plural_name: devices
  filterable_fields: [hostname, status, role]
  sortable_fields: [hostname, status, role, created_at]
  default_sort: hostname

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin

mcp:
  exposed: true
  allow_create: true
  allow_update: true
  allow_delete: true
  allow_search: true

query:
  default_list_fields: [hostname, status, role, management_ip]
  default_sort_field: hostname
  default_page_size: 50
  max_page_size: 200
  max_export_rows: 10000
  relationship_filters_enabled: true
  max_traversal_depth: 3

health:
  enabled: true
  freshness_hours: 168
  alert_on_orphan: true
```

## Attribute Types

| Type | JSON Schema | Description |
|---|---|---|
| `string` | `string` | Text up to max_length |
| `text` | `string` | Long-form text (textarea in forms) |
| `integer` | `integer` | Whole numbers |
| `float` | `number` | Decimal numbers |
| `boolean` | `boolean` | True/false |
| `datetime` | `string (date-time)` | ISO 8601 datetime |
| `date` | `string (date)` | ISO 8601 date |
| `enum` | `string` | Controlled vocabulary (requires `enum_values`) |
| `ip_address` | `string (ipv4)` | IPv4 or IPv6 address |
| `cidr` | `string` | CIDR notation (e.g., 10.0.0.0/24) |
| `mac_address` | `string` | MAC address (XX:XX:XX:XX:XX:XX) |
| `url` | `string (uri)` | Valid URL |
| `email` | `string (email)` | Valid email address |
| `json` | `object` | Arbitrary JSON structure |
| `reference` | `string` | Foreign reference (ID of another node) |
| `list[string]` | `array` | Array of strings |
| `list[integer]` | `array` | Array of integers |

## EdgeType Definition

```yaml
kind: EdgeType
version: v1
metadata:
  name: LOCATED_IN
  display_name: "Located In"
  description: "Device is located at a physical location"
  category: Organization

source:
  node_types: [Device]            # Which node types can be the source.

target:
  node_types: [Location]          # Which node types can be the target.

cardinality: many_to_one          # one_to_one, one_to_many, many_to_one, many_to_many
inverse_name: HOSTS_DEVICE        # Name for the reverse direction.

attributes:                       # Properties on the edge itself.
  rack_position:
    type: integer
    required: false

constraints:
  unique_source: true             # Each source has at most one of this edge.
  unique_target: false            # Multiple sources can point to same target.

query:
  traversable: true               # Can be used in filter paths.
  query_alias: located_in         # Alias for filter paths (default: snake_case of name).
  traversable_in_reports: true    # Target fields appear in report builder.
  supports_existence_filter: true # Filter by "has/lacks this relationship".
  supports_count_filter: true     # Filter by relationship count.
  supports_row_expansion: true    # Can expand into multiple CSV rows.
```

## Cardinality Options

| Value | Meaning |
|---|---|
| `one_to_one` | Each source has exactly one target, and vice versa |
| `one_to_many` | Each source can have many targets (e.g., Device → Interfaces) |
| `many_to_one` | Many sources point to one target (e.g., Devices → Location) |
| `many_to_many` | No restrictions on source-target cardinality |

## Mixin Definition

```yaml
kind: Mixin
version: v1
metadata:
  name: lifecycle_mixin
  description: "Common lifecycle fields"

attributes:
  created_at:
    type: datetime
    auto_set: create
  updated_at:
    type: datetime
    auto_set: update
  created_by:
    type: string
    auto_set: actor
  updated_by:
    type: string
    auto_set: actor
```

Mixins are included in node types via the `mixins` list. Their attributes are merged into the node type at load time.
