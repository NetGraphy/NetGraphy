---
title: "Validation Reference"
slug: "validation-reference"
summary: "Reference for schema-derived validation rules"
category: "Reference"
tags: [validation, schema, reference]
status: published
---

# Validation Reference

NetGraphy generates validation rules from the schema. These rules are enforced at the API layer on every create and update operation.

## Validation Rule Types

### Attribute Validation

| Rule | Source | Example |
|---|---|---|
| **Required** | `required: true` | hostname must be provided |
| **Type check** | `type: integer` | ap_count must be a number |
| **Unique** | `unique: true` | hostname must be unique across all devices |
| **Enum** | `enum_values: [...]` | status must be one of active, planned, staged |
| **Length** | `max_length: 255` | hostname cannot exceed 255 characters |
| **Range** | `min_value: 0, max_value: 65535` | vlan_id must be between 0 and 65535 |
| **Regex** | `validation_regex: "^[a-zA-Z]"` | hostname must start with a letter |
| **IP address** | `type: ip_address` | Must be valid IPv4 or IPv6 |
| **CIDR** | `type: cidr` | Must be valid CIDR notation (e.g., 10.0.0.0/24) |
| **MAC address** | `type: mac_address` | Must match XX:XX:XX:XX:XX:XX format |
| **Email** | `type: email` | Must be a valid email address |
| **URL** | `type: url` | Must be a valid URL |

### Edge Validation

| Rule | Source | Example |
|---|---|---|
| **Cardinality** | `cardinality: many_to_one` | Enforced on edge creation |
| **Unique source** | `unique_source: true` | Each device can be in only one location |
| **Unique target** | `unique_target: true` | Each interface belongs to exactly one device |
| **Source type** | `source.node_types: [Device]` | Only Device nodes can be the source |
| **Target type** | `target.node_types: [Location]` | Only Location nodes can be the target |

## Validation Flow

1. Client sends create/update request
2. Schema registry validates properties against the node type definition
3. Type coercion and format validation applied
4. Unique constraints checked against existing data
5. Edge cardinality checked on relationship creation
6. Errors returned as structured validation messages

## Viewing Validation Rules

Browse at **Admin > Generated Artifacts > Validation Rules** or via API:

```
GET /api/v1/generated/validation-rules
```
