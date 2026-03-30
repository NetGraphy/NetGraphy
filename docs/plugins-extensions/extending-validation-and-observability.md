---
title: "Extending Validation and Observability"
slug: "plugins-extensions-extending-validation-and-observability"
summary: "Add health metadata, attribute constraints, and freshness checks to plugin schema files for automated validation and monitoring."
category: "Plugins and Extensions"
tags: [validation, observability, health, constraints, freshness, plugins]
status: published
---

# Extending Validation and Observability

Plugin schema files can include validation and observability metadata that the platform uses to enforce data quality and monitor system health. These are defined inline in the schema, not in separate configuration files.

## Attribute Constraints

Each attribute in a schema definition supports constraint fields that are enforced at write time:

- `required` -- The attribute must be present on create.
- `unique` -- No two nodes of this type may share the same value.
- `min_length` / `max_length` -- String length bounds.
- `pattern` -- A regular expression the value must match.
- `choices` -- An explicit set of allowed values (enum).
- `min_value` / `max_value` -- Numeric range bounds.

These constraints are validated by the repository layer before any write reaches the graph database. Validation errors return structured error responses with the failing field, constraint, and provided value.

## Health Metadata

The `health` block on a node type definition declares monitoring rules:

```yaml
health:
  freshness:
    field: updated_at
    max_age: 24h
    severity: warning
  required_attributes:
    - hostname
    - status
    - management_ip
  count_threshold:
    min: 1
    severity: critical
    message: "No instances of this type exist"
```

- **Freshness** -- Alerts when instances have not been updated within the specified window. Useful for types populated by ingestion pipelines where stale data indicates a collection failure.
- **Required attributes** -- Flags instances missing attributes that should always be populated, even if the attribute is not strictly `required` at creation time (for example, fields populated by post-ingestion enrichment).
- **Count threshold** -- Alerts when the total instance count falls below or exceeds expected bounds.

## Dashboard Integration

Health checks generated from plugin schema appear in the system health dashboard alongside core type checks. Each check displays the type name, severity level, current status, and a link to the affected instances. The observability engine evaluates these checks on a configurable schedule and emits OpenTelemetry metrics for external alerting integration.
