---
title: "Validation"
slug: "validation"
summary: "Schema-derived validation rules enforced at every API boundary — required fields, type checking, enum enforcement, regex, and network type validation."
category: "Core Concepts"
tags: [validation, schema, data-quality, api]
status: published
---

# Validation

All validation in NetGraphy is derived from the schema. There are no hand-written validation rules — the validation generator reads each `NodeTypeDefinition` and `EdgeTypeDefinition` and produces a structured rule set that is enforced at API boundaries, used by MCP tools, and available for batch integrity checks.

## What Gets Validated

### Node Attributes

On every create and update operation, the schema registry's `validate_node_properties` method runs the following checks in order:

1. **Required fields** — Every attribute marked `required: true` must be present and non-null, unless it has a `default` or `auto_set` configured.
2. **Unknown attributes** — Properties not defined in the schema are rejected. This prevents typos and schema drift.
3. **Type checking** — Each value is checked against its declared `AttributeType`. Strings must be strings, integers must be integers (and not booleans, since Python's `bool` is a subclass of `int`), lists must contain the correct element type.
4. **Enum enforcement** — Enum attributes are checked against the `enum_values` list or the referenced `EnumTypeDefinition`. Values outside the allowed set are rejected.
5. **String length** — Fields with `max_length` are checked for character count.
6. **Numeric range** — Fields with `min_value` or `max_value` bounds are range-checked.
7. **Regex patterns** — Fields with `validation_regex` are matched against the pattern.
8. **Network type validation** — Specialized format checks for `ip_address` (parsed via Python's `ipaddress.ip_address`), `cidr` (parsed via `ipaddress.ip_network`), `mac_address` (validated against multiple MAC formats including colon, dash, and dot notation), `email`, and `url`.

### Edge Attributes and Constraints

Edge properties are validated through `validate_edge_properties` with the same type, enum, and format checks. Additionally, the validation generator produces rules for:

- **Allowed source/target types** — The source and target node types must match the edge definition.
- **Cardinality** — `one_to_one` and `one_to_many` constraints are checked before edge creation.
- **Unique source/target** — `unique_source` and `unique_target` constraints prevent duplicate edges.
- **Edge count bounds** — `min_count` and `max_count` constraints on the number of edges per node.
- **Required relationships** — Edges marked `health.required: true` generate warning-level rules.

## When Validation Runs

Validation executes synchronously at the API layer before any data reaches the graph database. The `validate_node_properties` and `validate_edge_properties` methods return a list of error messages — an empty list means the data is valid. MCP tools and agent actions go through the same validation path. There is no way to bypass schema validation and write invalid data to the graph.

## Generated Validation Rules

The validation generator also produces a structured `validation_rules` manifest used for documentation, UI constraint display, and batch integrity checks. Each rule carries a `rule_type` (e.g., `required_field`, `type_check`, `enum_check`, `format_check`, `cardinality`), the target field or edge, a human-readable message, and a severity level.
