"""Validation Rule Generator — derives validation rules from the schema.

Generates structured validation rules that can be:
1. Enforced at API boundaries (before persistence)
2. Used by MCP tools and agent actions
3. Displayed in the UI as constraint documentation
4. Run as batch integrity checks

All validation comes from the schema — no manual rule definitions.
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    AttributeType,
    Cardinality,
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def generate_node_validation_rules(nt: NodeTypeDefinition) -> list[dict[str, Any]]:
    """Generate validation rules for a node type from its attributes and constraints."""
    rules: list[dict[str, Any]] = []

    for attr_name, attr in nt.attributes.items():
        # Required field
        if attr.required:
            rules.append({
                "rule_type": "required_field",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "message": f"{attr.display_name or attr_name} is required",
                "severity": "error",
            })

        # Uniqueness
        if attr.unique:
            rules.append({
                "rule_type": "unique_field",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "message": f"{attr.display_name or attr_name} must be unique",
                "severity": "error",
            })

        # Type validation
        rules.append({
            "rule_type": "type_check",
            "node_type": nt.metadata.name,
            "field": attr_name,
            "expected_type": attr.type.value,
            "message": f"{attr.display_name or attr_name} must be type {attr.type.value}",
            "severity": "error",
        })

        # Enum validation
        if attr.enum_values:
            rules.append({
                "rule_type": "enum_check",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "allowed_values": attr.enum_values,
                "message": f"{attr.display_name or attr_name} must be one of: {', '.join(attr.enum_values)}",
                "severity": "error",
            })

        # Length constraint
        if attr.max_length:
            rules.append({
                "rule_type": "max_length",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "max_length": attr.max_length,
                "message": f"{attr.display_name or attr_name} must be at most {attr.max_length} characters",
                "severity": "error",
            })

        # Range constraints
        if attr.min_value is not None:
            rules.append({
                "rule_type": "min_value",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "min_value": attr.min_value,
                "message": f"{attr.display_name or attr_name} must be >= {attr.min_value}",
                "severity": "error",
            })
        if attr.max_value is not None:
            rules.append({
                "rule_type": "max_value",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "max_value": attr.max_value,
                "message": f"{attr.display_name or attr_name} must be <= {attr.max_value}",
                "severity": "error",
            })

        # Regex validation
        if attr.validation_regex:
            rules.append({
                "rule_type": "regex",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "pattern": attr.validation_regex,
                "message": f"{attr.display_name or attr_name} must match pattern {attr.validation_regex}",
                "severity": "error",
            })

        # Network type validation
        if attr.type in (AttributeType.IP_ADDRESS, AttributeType.CIDR, AttributeType.MAC_ADDRESS, AttributeType.EMAIL, AttributeType.URL):
            rules.append({
                "rule_type": "format_check",
                "node_type": nt.metadata.name,
                "field": attr_name,
                "format": attr.type.value,
                "message": f"{attr.display_name or attr_name} must be a valid {attr.type.value}",
                "severity": "error",
            })

    return rules


def generate_edge_validation_rules(
    et: EdgeTypeDefinition,
    registry: SchemaRegistry,
) -> list[dict[str, Any]]:
    """Generate validation rules for an edge type."""
    rules: list[dict[str, Any]] = []
    edge_name = et.metadata.name

    # Allowed source types
    rules.append({
        "rule_type": "allowed_source_types",
        "edge_type": edge_name,
        "allowed_types": et.source.node_types,
        "message": f"Source of {edge_name} must be one of: {', '.join(et.source.node_types)}",
        "severity": "error",
    })

    # Allowed target types
    rules.append({
        "rule_type": "allowed_target_types",
        "edge_type": edge_name,
        "allowed_types": et.target.node_types,
        "message": f"Target of {edge_name} must be one of: {', '.join(et.target.node_types)}",
        "severity": "error",
    })

    # Cardinality rules
    if et.cardinality == Cardinality.ONE_TO_ONE:
        rules.append({
            "rule_type": "cardinality",
            "edge_type": edge_name,
            "cardinality": "one_to_one",
            "message": f"{edge_name} is one-to-one: source and target can each have at most one",
            "severity": "error",
        })
    elif et.cardinality == Cardinality.ONE_TO_MANY:
        rules.append({
            "rule_type": "cardinality",
            "edge_type": edge_name,
            "cardinality": "one_to_many",
            "message": f"{edge_name} target can only have one source",
            "severity": "error",
        })

    # Unique constraints
    if et.constraints.unique_source:
        rules.append({
            "rule_type": "unique_source",
            "edge_type": edge_name,
            "message": f"Each source node can have at most one {edge_name} edge",
            "severity": "error",
        })
    if et.constraints.unique_target:
        rules.append({
            "rule_type": "unique_target",
            "edge_type": edge_name,
            "message": f"Each target node can have at most one {edge_name} edge",
            "severity": "error",
        })

    # Min/max count constraints
    if et.constraints.min_count is not None:
        rules.append({
            "rule_type": "min_edge_count",
            "edge_type": edge_name,
            "min_count": et.constraints.min_count,
            "message": f"Source must have at least {et.constraints.min_count} {edge_name} edge(s)",
            "severity": "error",
        })
    if et.constraints.max_count is not None:
        rules.append({
            "rule_type": "max_edge_count",
            "edge_type": edge_name,
            "max_count": et.constraints.max_count,
            "message": f"Source can have at most {et.constraints.max_count} {edge_name} edge(s)",
            "severity": "error",
        })

    # Required edge attributes
    for attr_name, attr in et.attributes.items():
        if attr.required:
            rules.append({
                "rule_type": "required_edge_attribute",
                "edge_type": edge_name,
                "field": attr_name,
                "message": f"{attr.display_name or attr_name} is required on {edge_name}",
                "severity": "error",
            })

    # Required relationship (from health metadata)
    if et.health.required:
        for src_type in et.source.node_types:
            rules.append({
                "rule_type": "required_relationship",
                "edge_type": edge_name,
                "source_type": src_type,
                "target_types": et.target.node_types,
                "message": f"Every {src_type} must have a {edge_name} relationship",
                "severity": "warning",
            })

    return rules


def generate_all_validation_rules(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate complete validation rule manifest from the schema."""
    rules: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        rules.extend(generate_node_validation_rules(nt))

    for et in registry._edge_types.values():
        rules.extend(generate_edge_validation_rules(et, registry))

    return rules
