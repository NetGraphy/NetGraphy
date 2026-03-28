"""Schema validation — validates schema definitions and detects migration impacts.

This module is responsible for:
1. Validating individual schema files before they enter the registry
2. Diffing two schema states to detect changes
3. Classifying changes by risk level
4. Generating migration plans
"""

from __future__ import annotations

from packages.schema_engine.models import (
    MigrationOperation,
    MigrationPlan,
    RiskLevel,
    SchemaChange,
)
from packages.schema_engine.registry import SchemaRegistry

# Reserved attribute names that cannot be used in schemas
RESERVED_ATTRIBUTES = {"id", "_type", "_labels", "_id", "element_id"}

# Attribute types that support uniqueness constraints
INDEXABLE_TYPES = {"string", "integer", "float", "ip_address", "mac_address", "email", "url"}


def validate_schema_file(raw: dict) -> list[str]:
    """Validate a raw parsed YAML schema file.

    Returns list of error strings (empty if valid).
    """
    errors = []
    kind = raw.get("kind")
    if not kind:
        errors.append("Missing 'kind' field")
        return errors

    metadata = raw.get("metadata", {})
    if not metadata.get("name"):
        errors.append("Missing 'metadata.name'")

    if kind == "NodeType":
        errors.extend(_validate_node_type(raw))
    elif kind == "EdgeType":
        errors.extend(_validate_edge_type(raw))
    elif kind == "Mixin":
        errors.extend(_validate_mixin(raw))
    elif kind == "EnumType":
        errors.extend(_validate_enum_type(raw))
    else:
        errors.append(f"Unknown kind: {kind}")

    return errors


def _validate_node_type(raw: dict) -> list[str]:
    errors = []
    for attr_name, attr_data in raw.get("attributes", {}).items():
        if attr_name in RESERVED_ATTRIBUTES:
            errors.append(f"Reserved attribute name: {attr_name}")
        if attr_data.get("unique") and attr_data.get("type") not in INDEXABLE_TYPES:
            errors.append(
                f"Attribute '{attr_name}' has unique=true but type "
                f"'{attr_data.get('type')}' does not support uniqueness constraints"
            )
        if attr_data.get("type") == "enum" and not attr_data.get("enum_values") and not attr_data.get("enum_ref"):
            errors.append(f"Enum attribute '{attr_name}' must define enum_values or enum_ref")
    return errors


def _validate_edge_type(raw: dict) -> list[str]:
    errors = []
    if not raw.get("source", {}).get("node_types"):
        errors.append("Edge type must define source.node_types")
    if not raw.get("target", {}).get("node_types"):
        errors.append("Edge type must define target.node_types")
    return errors


def _validate_mixin(raw: dict) -> list[str]:
    errors = []
    if not raw.get("attributes"):
        errors.append("Mixin must define at least one attribute")
    return errors


def _validate_enum_type(raw: dict) -> list[str]:
    errors = []
    values = raw.get("values", [])
    if not values:
        errors.append("EnumType must define at least one value")
    names = [v.get("name") for v in values if isinstance(v, dict)]
    if len(names) != len(set(names)):
        errors.append("EnumType has duplicate value names")
    return errors


def diff_schemas(
    old_registry: SchemaRegistry,
    new_registry: SchemaRegistry,
) -> list[SchemaChange]:
    """Compare two schema registries and return a list of changes."""
    changes = []

    # Detect new and modified node types
    for nt in new_registry.list_node_types():
        name = nt["metadata"]["name"]
        old_nt = old_registry.get_node_type(name)
        if old_nt is None:
            changes.append(SchemaChange(
                change_type="add_node_type",
                target=name,
                risk_level=RiskLevel.SAFE,
                description=f"New node type: {name}",
            ))
        else:
            # TODO: Deep diff attributes, detect adds/removes/changes
            pass

    # Detect removed node types
    for nt in old_registry.list_node_types():
        name = nt["metadata"]["name"]
        if new_registry.get_node_type(name) is None:
            changes.append(SchemaChange(
                change_type="remove_node_type",
                target=name,
                risk_level=RiskLevel.DANGEROUS,
                description=f"Removed node type: {name}",
            ))

    # TODO: Same for edge types, enum types

    return changes


def generate_migration_plan(changes: list[SchemaChange]) -> MigrationPlan:
    """Generate a migration plan from a list of schema changes."""
    operations = []
    warnings = []
    max_risk = RiskLevel.SAFE

    for change in changes:
        if change.risk_level == RiskLevel.DANGEROUS:
            max_risk = RiskLevel.DANGEROUS
            warnings.append(f"DANGEROUS: {change.description}")
        elif change.risk_level == RiskLevel.CAUTIOUS and max_risk == RiskLevel.SAFE:
            max_risk = RiskLevel.CAUTIOUS

        # TODO: Generate specific Cypher operations per change type
        # Examples:
        # - add_node_type: CREATE INDEX, CREATE CONSTRAINT
        # - add_attribute with index: CREATE INDEX
        # - remove_node_type: DROP INDEX, DROP CONSTRAINT (data deletion is separate)

    return MigrationPlan(
        changes=changes,
        risk_level=max_risk,
        operations=operations,
        warnings=warnings,
    )
