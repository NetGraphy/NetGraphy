---
title: "Your First Schema"
slug: "first-schema"
summary: "Walk through creating a new YAML schema file and watch the platform generate the API, UI, and tools for it."
category: "Getting Started"
tags: [schema, yaml, getting-started, node-type]
status: published
---

# Your First Schema

NetGraphy generates its entire runtime behavior from YAML schema files. When you create a new schema file and restart the API server (or trigger a schema reload), the platform automatically produces REST API endpoints, UI list and detail views, search indexing, form fields, filter controls, graph visualization rules, and AI assistant tool definitions. No code changes required.

This guide walks through creating a schema for a `WirelessNetwork` node type.

## Create the Schema File

Create a new file at `schemas/core/wireless_network.yaml`:

```yaml
kind: NodeType
version: v1
metadata:
  name: WirelessNetwork
  display_name: Wireless Network
  description: "A wireless network (SSID) broadcast by one or more access points."
  icon: wifi
  color: "#8B5CF6"
  category: Infrastructure
  tags: [wireless, network, wifi]

attributes:
  ssid:
    type: string
    display_name: SSID
    required: true
    unique: true
    indexed: true
    max_length: 32
    description: "The broadcast SSID name"
    ui:
      list_column: true
      list_column_order: 1
      search_weight: 10
      form_order: 1
      filter: true

  security_mode:
    type: enum
    display_name: Security Mode
    enum_values: [open, wpa2_personal, wpa2_enterprise, wpa3_personal, wpa3_enterprise]
    required: true
    description: "Wireless security protocol"
    ui:
      list_column: true
      list_column_order: 2
      form_order: 2
      filter: true
      badge_colors:
        open: red
        wpa2_personal: yellow
        wpa2_enterprise: green
        wpa3_personal: blue
        wpa3_enterprise: green

  band:
    type: enum
    display_name: Band
    enum_values: [2.4ghz, 5ghz, 6ghz, dual, tri]
    required: false
    description: "Operating frequency band"
    ui:
      list_column: true
      list_column_order: 3
      form_order: 3
      filter: true

  vlan_id:
    type: integer
    display_name: VLAN ID
    required: false
    description: "Associated VLAN for client traffic"
    ui:
      form_order: 4

  hidden:
    type: boolean
    display_name: Hidden SSID
    default: false
    required: false
    description: "Whether the SSID is broadcast or hidden"
    ui:
      form_order: 5

  description:
    type: text
    display_name: Description
    required: false
    ui:
      form_order: 10
      form_widget: textarea

mixins:
  - lifecycle_mixin

search:
  enabled: true
  primary_field: ssid
  search_fields: [ssid, description]

graph:
  default_label_field: ssid
  group_by: security_mode

api:
  plural_name: wireless_networks
  filterable_fields: [ssid, security_mode, band, vlan_id, hidden]
  sortable_fields: [ssid, security_mode, band]
  default_sort: ssid

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

## Understanding the Structure

**`kind` and `version`** identify this as a node type schema using the v1 format.

**`metadata`** defines the display name, description, icon, color, category, and tags. These control how the type appears in the UI navigation, schema explorer, and graph visualization. The `icon` field references a Lucide icon name.

**`attributes`** define the properties that instances of this type carry. Each attribute has a data type, display name, validation rules, and a `ui` block that controls how it renders in list views, forms, and filters. The `list_column` and `list_column_order` fields determine which columns appear in the default list view and in what order.

**`mixins`** include reusable attribute sets. The `lifecycle_mixin` adds `created_at`, `updated_at`, and `created_by` fields automatically.

**`search`** configures which fields are indexed for full-text search and which field serves as the primary display label.

**`graph`** controls graph visualization: which property to use as the node label and how to group nodes visually.

**`api`** sets the plural URL path (`/api/v1/wireless_networks`), which fields support filtering and sorting, and the default sort order.

**`permissions`** define the minimum role required to read, write, and delete instances of this type.

## What Gets Generated

After adding this file and restarting the API server, the following are available without any additional work:

- **REST API** at `/api/v1/wireless_networks` with full CRUD, filtering, sorting, and pagination.
- **List view** in the UI with columns for SSID, Security Mode, and Band, with filter controls.
- **Detail view** showing all attributes, related objects, and a local graph visualization.
- **Create/edit form** with fields ordered by `form_order`, enum dropdowns, and validation.
- **Search indexing** so wireless networks appear in global search results.
- **Graph visualization** rules so wireless network nodes render with the correct color, icon, and label.
- **AI assistant tools** that let the assistant query, create, and traverse wireless network objects.

![Schema Explorer](../assets/screenshots/schema-explorer.png)

The schema explorer in the UI shows all registered types, their attributes, relationships, and metadata. Your new `WirelessNetwork` type will appear there alongside the built-in types as soon as the schema is loaded.
