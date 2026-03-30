---
title: "Observability"
slug: "observability"
summary: "Schema-derived health checks, Prometheus metrics, alerts, and data quality monitoring — all configured in YAML, not code."
category: "Core Concepts"
tags: [observability, health, metrics, prometheus, alerts]
status: published
---

# Observability

NetGraphy's observability system is generated entirely from the schema. The `HealthMetadata` block on each node type and the `EdgeHealthMetadata` on each edge type define what "healthy" looks like. The observability generator reads these definitions and produces health checks, Prometheus-compatible metrics, alerts, and data quality rules — no manual instrumentation required.

## Health Checks

Health checks are named queries that detect problems and return affected nodes. The generator produces checks for:

- **Required field completeness** — Finds nodes missing required attributes. Severity: `error`. Generated for every node type that has required fields.
- **Orphan detection** — Finds nodes with no relationships at all. Enabled per type via `health.alert_on_orphan: true`. This catches devices that were created but never connected to a location, or interfaces not attached to any device.
- **Freshness monitoring** — Finds nodes not updated within the configured `health.freshness_hours` window. Useful for detecting stale discovery data — if a device hasn't been seen by the ingestion pipeline in 48 hours, something may be wrong.
- **Missing required edges** — Finds source nodes that lack a required relationship. Configured via `edge.health.required: true`. Example: every Device should have a LOCATED_IN edge; devices without one are flagged.
- **Per-attribute health** — Attributes marked `health.required_for_health: true` generate critical-severity checks for empty values. Use this for fields that must have data for the system to function (e.g., management IP on a device).

## Prometheus Metrics

The generator produces metric definitions compatible with Prometheus scraping:

- **`netgraphy_node_count`** — Total count per node type, labeled by type. The fundamental inventory metric.
- **`netgraphy_invalid_node_count`** — Count of nodes missing required fields, per type.
- **`netgraphy_orphan_node_count`** — Count of orphaned nodes, per type (when orphan detection is enabled).
- **`netgraphy_edge_count`** — Total count per edge type.
- **`netgraphy_missing_edge_count`** — Count of nodes missing a required relationship, labeled by source type and edge type.
- **`netgraphy_node_count_by_<field>`** — Distribution metrics for filterable enum attributes (e.g., device count by status). Limited to two enum attributes per type to prevent metric explosion.

## Alerts

Count-based alerts fire when node populations drift outside configured bounds:

- **Below minimum** — `health.min_count` triggers when a type's population drops too low. Example: if you expect at least 10 core routers, an alert fires when the count falls below.
- **Above maximum** — `health.max_count` triggers when a type exceeds its expected population. Useful for detecting runaway automated creation.

Each alert carries a configurable severity (`warning` or `critical`) and is categorized for routing to the appropriate on-call team.

## Configuration

All observability is configured through YAML schema — the `health` block on node types, the `health` block on edge types, and the `health` block on individual attributes. Setting `health.enabled: false` on a type suppresses all observability generation for it. Setting `health.required_for_health: true` on a type includes it in the global platform health score.
