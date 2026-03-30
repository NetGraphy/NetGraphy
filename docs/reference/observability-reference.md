---
title: "Observability Reference"
slug: "observability-reference"
summary: "Reference for schema-derived health checks, metrics, and alerts"
category: "Reference"
tags: [observability, health, metrics, reference]
status: published
---

# Observability Reference

NetGraphy generates observability rules from schema health metadata. These provide automated health monitoring without manual configuration.

## Health Check Types

### Node Health Checks

| Check | Source | Description |
|---|---|---|
| **Orphan detection** | `alert_on_orphan: true` | Alert when a node has no relationships |
| **Freshness** | `freshness_hours: 168` | Alert when a node hasn't been updated within N hours |
| **Count bounds** | `min_count: 1` | Alert when fewer than N instances exist |
| **Count ceiling** | `max_count: 1000` | Alert when more than N instances exist |

### Edge Health Checks

| Check | Source | Description |
|---|---|---|
| **Required edge** | `required: true` | Alert when a source node lacks this edge |
| **Missing edge** | `alert_if_missing: true` | Warn when expected edges are absent |
| **Count ceiling** | `max_count: 100` | Alert when edge count exceeds threshold |

## Metrics

Generated Prometheus-format metrics include:

- `netgraphy_node_count{type="Device"}` — Count per node type
- `netgraphy_edge_count{type="LOCATED_IN"}` — Count per edge type
- `netgraphy_orphan_count{type="Device"}` — Orphaned nodes per type
- `netgraphy_stale_count{type="Device"}` — Nodes past freshness threshold
- `netgraphy_enum_distribution{type="Device",field="status"}` — Value distribution

## AI Agent Observability

The AI agent runtime supports OpenTelemetry tracing:

- **Endpoint**: Configurable OTLP HTTP endpoint (Phoenix, Jaeger, etc.)
- **Spans**: `agent.run`, `agent.model_call`, `agent.tool.*`
- **Attributes**: Token usage, latency, tool results, errors
- **Configuration**: Admin > AI Configuration > OTel section

## Viewing Health Reports

Browse at **Admin > Generated Artifacts > Health Report** or via API:

```
GET /api/v1/generated/health-report
GET /api/v1/generated/observability-rules
GET /api/v1/generated/metrics  # Prometheus format
```
