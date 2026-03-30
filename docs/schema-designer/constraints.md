---
title: "Constraints Reference"
slug: "schema-designer-constraints"
summary: "All attribute and edge constraints available in schema definitions, including type validation, uniqueness, ranges, and cardinality enforcement."
category: "Schema Designer"
tags: [schema, constraints, validation, cardinality, attributes]
status: published
---

# Constraints Reference

Constraints enforce data integrity at the application layer. They are declared in YAML schema definitions and checked by the schema registry's validation logic every time a node or edge is created or updated.

## Attribute Constraints

These constraints apply to individual attributes on node types and edge types.

| Constraint | Applies To | Description |
|---|---|---|
| `required` | All types | Attribute must be present and non-null. Attributes with `auto_set` or `default` are exempt from user-facing required checks. |
| `unique` | All types | No two nodes of the same type can share this value. Enforced via database constraint and application-layer validation. |
| `indexed` | All types | Creates a database index for faster lookups and filter queries. Always set `indexed: true` on fields used in filters or search. |
| `max_length` | `string`, `text` | Maximum character count. Validation rejects values exceeding this length. |
| `min_value` | `integer`, `float` | Minimum numeric value (inclusive). |
| `max_value` | `integer`, `float` | Maximum numeric value (inclusive). |
| `enum_values` | `enum` | Exhaustive list of allowed string values. Any value not in the list is rejected. |
| `validation_regex` | `string`, `text` | Regular expression pattern the value must match. Useful for enforcing naming conventions (e.g., `^[a-z][a-z0-9-]+$` for slugs). |

### Type-Specific Validation

Beyond explicit constraints, the schema engine validates values against their declared type. `ip_address` values are checked with Python's `ipaddress.ip_address()`. `cidr` values are validated with `ipaddress.ip_network()`. `mac_address` values are matched against standard MAC formats (colon-separated, dash-separated, and dot-separated). `email` and `url` types are checked against format patterns.

## Edge Constraints

Edge constraints control the structure of relationships in the graph.

| Constraint | Description |
|---|---|
| `unique_source` | Each source node can have at most one edge of this type. Used when a node belongs to exactly one parent (e.g., a device has one location). |
| `unique_target` | Each target node can have at most one edge of this type pointing to it. Used when a child belongs to exactly one parent (e.g., an interface belongs to one device). |
| `min_count` | Minimum number of edges of this type that a source node must have. Useful for enforcing "every device must have at least one interface." |
| `max_count` | Maximum number of edges of this type allowed per source node. Prevents unbounded fan-out. |

### Cardinality and Constraints Together

Cardinality (`one_to_one`, `one_to_many`, `many_to_one`, `many_to_many`) sets the broad relationship pattern. The `unique_source` and `unique_target` constraints provide fine-grained enforcement within that pattern. For example, `many_to_one` cardinality with `unique_source: true` ensures each device is located in exactly one location, while allowing each location to host many devices.

All constraint violations produce clear error messages returned through the API, so users and automation can identify and fix issues without inspecting logs.
