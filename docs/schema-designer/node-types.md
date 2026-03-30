---
title: "Defining Node Types"
slug: "schema-designer-node-types"
summary: "Complete reference for defining node types in YAML, including metadata, attributes, mixins, search, graph, API, permissions, and query configuration."
category: "Schema Designer"
tags: [schema, node-types, yaml, attributes, mixins]
status: published
---

# Defining Node Types

A node type represents a class of objects in the graph -- devices, locations, interfaces, prefixes, circuits, or any custom type you define. Each node type is a YAML file with `kind: NodeType` that declares everything the platform needs to manage instances of that type.

## Full Example

```yaml
kind: NodeType
version: v1
metadata:
  name: Device
  display_name: Device
  description: "A network device — router, switch, firewall, load balancer, etc."
  icon: server
  color: "#3B82F6"
  category: Infrastructure
  tags: [network, inventory, core]

attributes:
  hostname:
    type: string
    display_name: Hostname
    required: true
    unique: true
    indexed: true
    max_length: 255
    description: "FQDN or hostname of the device"
    ui:
      list_column: true
      list_column_order: 1
      search_weight: 10
      form_order: 1
      filter: true

  status:
    type: enum
    display_name: Status
    enum_values: [active, planned, staged, decommissioned, maintenance, offline]
    default: planned
    required: true
    description: "Operational status of the device"
    ui:
      list_column: true
      list_column_order: 2
      form_order: 2
      filter: true
      badge_colors:
        active: green
        planned: blue
        decommissioned: red

  management_ip:
    type: ip_address
    display_name: Management IP
    required: false
    indexed: true
    description: "Primary management IP address"

mixins:
  - lifecycle_mixin
  - provenance_mixin

detail_tabs:
  - label: Interfaces
    edge_type: HAS_INTERFACE
    target_type: Interface
    columns: [name, interface_type, enabled, oper_status, speed_mbps]
    filters: [interface_type, enabled]
    default_sort: name

search:
  enabled: true
  primary_field: hostname
  search_fields: [hostname, management_ip, serial_number]

graph:
  default_label_field: hostname
  size_field: null
  group_by: role

api:
  plural_name: devices
  filterable_fields: [hostname, status, role, management_ip]
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

agent:
  exposed: true
  capabilities: [onboard, decommission]
  sensitive: false

health:
  enabled: true
  required_for_health: true
  freshness_hours: 24
  alert_on_orphan: true
  alert_severity: warning

query:
  default_list_fields: [hostname, status, role, management_ip]
  default_sort_field: hostname
  default_page_size: 50
  max_page_size: 200
  primary_search_fields: [hostname, management_ip, serial_number]
  relationship_filters_enabled: true
  max_traversal_depth: 3
  max_filter_nesting: 4
```

## Section Reference

### metadata

Identifies the type across the platform. `name` is the canonical identifier used in code, API routes, and graph labels. `display_name` is what users see. `icon` and `color` control rendering in the UI and graph explorer. `category` groups types in the navigation sidebar. `tags` enable filtering in the schema explorer.

### attributes

Each attribute has a `type` drawn from the supported set: `string`, `text`, `integer`, `float`, `boolean`, `datetime`, `date`, `json`, `ip_address`, `cidr`, `mac_address`, `url`, `email`, `enum`, `reference`, `list[string]`, `list[integer]`. Constraints like `required`, `unique`, `indexed`, `max_length`, `min_value`, `max_value`, `enum_values`, and `validation_regex` are enforced at the application layer. The `ui` sub-section controls list columns, form ordering, search weight, badge colors, and filter visibility.

### mixins

References to reusable attribute groups defined in separate YAML files (e.g., `lifecycle_mixin` adds `created_at`, `updated_at`, `created_by`, `updated_by`; `provenance_mixin` adds `source_type`, `source_id`, `last_verified_at`, `confidence_score`). Mixin attributes are merged into the node type at registry load time. Node type attributes take precedence over mixin attributes of the same name.

### detail_tabs

Defines tabs on the detail page that display related nodes via a specific edge type. Each tab specifies which columns to show, which fields to offer as filters, and the default sort order.

### search, graph, api, permissions

These sections control how the type participates in full-text search, graph visualization, REST API exposure, and role-based access control. The `api.plural_name` determines the URL path segment (e.g., `/api/devices`).

### mcp, agent, health

These sections control the generation pipeline. `mcp` determines which CRUD and search tools are generated for LLM consumption. `agent` configures higher-level capabilities and sensitivity flags. `health` defines observability thresholds -- freshness windows, count bounds, orphan alerts, and severity levels.

### query

Configures default list fields, pagination limits, search fields, traversal depth for relationship filters, and filter nesting limits. These settings feed directly into the query engine and the generated API endpoints.
