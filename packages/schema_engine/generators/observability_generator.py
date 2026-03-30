"""Observability Rule Generator — derives health checks, alerts, and metrics from the schema.

Generates:
1. Health signals: node counts, invalid nodes, missing fields
2. Integrity checks: orphans, broken edges, cardinality violations
3. Alerts: schema-author-defined alert conditions
4. Prometheus-compatible metrics definitions
5. Health report structure
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def generate_node_health_rules(nt: NodeTypeDefinition) -> list[dict[str, Any]]:
    """Generate observability rules for a node type."""
    if not nt.health.enabled:
        return []

    slug = _slugify(nt.metadata.name)
    display = nt.metadata.display_name or nt.metadata.name
    rules: list[dict[str, Any]] = []

    # Node count metric
    rules.append({
        "rule_type": "metric",
        "metric_name": f"netgraphy_node_count",
        "labels": {"type": nt.metadata.name},
        "description": f"Total count of {display} nodes",
        "query": f"MATCH (n:{nt.metadata.name}) RETURN count(n) as value",
        "category": nt.metadata.category or "uncategorized",
    })

    # Invalid nodes (missing required fields)
    required_attrs = [a for a in nt.attributes.values() if a.required]
    if required_attrs:
        conditions = " OR ".join(
            f"n.{a.name} IS NULL" for a in required_attrs
        )
        rules.append({
            "rule_type": "metric",
            "metric_name": f"netgraphy_invalid_node_count",
            "labels": {"type": nt.metadata.name},
            "description": f"Count of {display} nodes missing required fields",
            "query": f"MATCH (n:{nt.metadata.name}) WHERE {conditions} RETURN count(n) as value",
        })

        rules.append({
            "rule_type": "health_check",
            "check_name": f"{slug}_required_fields",
            "description": f"Check all {display} nodes have required fields ({', '.join(a.name for a in required_attrs)})",
            "query": f"MATCH (n:{nt.metadata.name}) WHERE {conditions} RETURN n.id as id, n.{nt.search.primary_field or 'id'} as label",
            "severity": "error",
            "category": "validation",
        })

    # Orphan detection
    if nt.health.alert_on_orphan:
        rules.append({
            "rule_type": "health_check",
            "check_name": f"{slug}_orphan",
            "description": f"Detect {display} nodes with no relationships",
            "query": f"MATCH (n:{nt.metadata.name}) WHERE NOT (n)--() RETURN n.id as id, n.{nt.search.primary_field or 'id'} as label",
            "severity": nt.health.alert_severity,
            "category": "integrity",
        })

        rules.append({
            "rule_type": "metric",
            "metric_name": f"netgraphy_orphan_node_count",
            "labels": {"type": nt.metadata.name},
            "description": f"Count of orphaned {display} nodes",
            "query": f"MATCH (n:{nt.metadata.name}) WHERE NOT (n)--() RETURN count(n) as value",
        })

    # Min/max count alerts
    if nt.health.min_count is not None:
        rules.append({
            "rule_type": "alert",
            "alert_name": f"{slug}_below_minimum",
            "description": f"Alert when {display} count drops below {nt.health.min_count}",
            "condition": f"count < {nt.health.min_count}",
            "query": f"MATCH (n:{nt.metadata.name}) RETURN count(n) as count",
            "severity": nt.health.alert_severity,
            "category": "capacity",
        })

    if nt.health.max_count is not None:
        rules.append({
            "rule_type": "alert",
            "alert_name": f"{slug}_above_maximum",
            "description": f"Alert when {display} count exceeds {nt.health.max_count}",
            "condition": f"count > {nt.health.max_count}",
            "query": f"MATCH (n:{nt.metadata.name}) RETURN count(n) as count",
            "severity": nt.health.alert_severity,
            "category": "capacity",
        })

    # Freshness check
    if nt.health.freshness_hours:
        rules.append({
            "rule_type": "health_check",
            "check_name": f"{slug}_freshness",
            "description": f"Detect {display} nodes not updated within {nt.health.freshness_hours} hours",
            "query": (
                f"MATCH (n:{nt.metadata.name}) "
                f"WHERE n.updated_at < datetime() - duration({{hours: {nt.health.freshness_hours}}}) "
                f"RETURN n.id as id, n.{nt.search.primary_field or 'id'} as label, n.updated_at as last_updated"
            ),
            "severity": "warning",
            "category": "freshness",
        })

    # Per-attribute health checks
    for attr in nt.attributes.values():
        if attr.health.required_for_health:
            rules.append({
                "rule_type": "health_check",
                "check_name": f"{slug}_{attr.name}_health",
                "description": f"Detect {display} nodes with missing {attr.display_name or attr.name} (health-critical)",
                "query": f"MATCH (n:{nt.metadata.name}) WHERE n.{attr.name} IS NULL RETURN n.id as id, n.{nt.search.primary_field or 'id'} as label",
                "severity": "critical",
                "category": "data_quality",
            })

    # Enum distribution metric
    enum_attrs = [a for a in nt.attributes.values() if a.enum_values and a.ui.filter]
    for attr in enum_attrs[:2]:  # Top 2 to prevent metric explosion
        rules.append({
            "rule_type": "metric",
            "metric_name": f"netgraphy_node_count_by_{attr.name}",
            "labels": {"type": nt.metadata.name},
            "description": f"Count of {display} nodes by {attr.display_name or attr.name}",
            "query": f"MATCH (n:{nt.metadata.name}) RETURN n.{attr.name} as {attr.name}, count(n) as value",
        })

    return rules


def generate_edge_health_rules(
    et: EdgeTypeDefinition,
    registry: SchemaRegistry,
) -> list[dict[str, Any]]:
    """Generate observability rules for an edge type."""
    if not et.health.enabled:
        return []

    slug = _slugify(et.metadata.name)
    display = et.metadata.display_name or et.metadata.name
    rules: list[dict[str, Any]] = []

    # Edge count metric
    rules.append({
        "rule_type": "metric",
        "metric_name": f"netgraphy_edge_count",
        "labels": {"type": et.metadata.name},
        "description": f"Total count of {display} edges",
        "query": f"MATCH ()-[r:{et.metadata.name}]->() RETURN count(r) as value",
    })

    # Required edge check
    if et.health.required or et.health.alert_if_missing:
        for src_type in et.source.node_types:
            src_display = src_type
            src_nt = registry.get_node_type(src_type)
            if src_nt and src_nt.metadata.display_name:
                src_display = src_nt.metadata.display_name
            primary = src_nt.search.primary_field if src_nt else "id"

            rules.append({
                "rule_type": "health_check",
                "check_name": f"{_slugify(src_type)}_missing_{slug}",
                "description": f"Detect {src_display} nodes without a {display} relationship",
                "query": (
                    f"MATCH (n:{src_type}) "
                    f"WHERE NOT (n)-[:{et.metadata.name}]->() "
                    f"RETURN n.id as id, n.{primary} as label"
                ),
                "severity": et.health.alert_severity,
                "category": "integrity",
            })

            rules.append({
                "rule_type": "metric",
                "metric_name": f"netgraphy_missing_edge_count",
                "labels": {"source_type": src_type, "edge_type": et.metadata.name},
                "description": f"Count of {src_display} nodes missing {display}",
                "query": (
                    f"MATCH (n:{src_type}) "
                    f"WHERE NOT (n)-[:{et.metadata.name}]->() "
                    f"RETURN count(n) as value"
                ),
            })

    return rules


def generate_all_observability_rules(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete observability rule manifest from the schema."""
    rules: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        rules.extend(generate_node_health_rules(nt))

    for et in registry._edge_types.values():
        rules.extend(generate_edge_health_rules(et, registry))

    return rules
