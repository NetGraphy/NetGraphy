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


VALID_ATTRIBUTE_TYPES = {
    "string", "text", "integer", "float", "boolean", "datetime", "date",
    "json", "ip_address", "cidr", "mac_address", "url", "email", "enum",
    "reference", "list[string]", "list[integer]",
}

VALID_CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}


def _validate_node_type_deep(raw: dict) -> tuple[list[str], list[str]]:
    """Extended validation for node types — attribute types, UI metadata, etc."""
    errors: list[str] = []
    warnings: list[str] = []
    metadata = raw.get("metadata", {})

    if not metadata.get("category"):
        warnings.append("Missing metadata.category — node type will not appear in sidebar navigation")
    if not metadata.get("display_name"):
        warnings.append("Missing metadata.display_name — will fall back to metadata.name in the UI")

    for attr_name, attr_data in raw.get("attributes", {}).items():
        attr_type = attr_data.get("type")
        if attr_type and attr_type not in VALID_ATTRIBUTE_TYPES:
            errors.append(f"Attribute '{attr_name}' has invalid type: '{attr_type}'")
        if attr_data.get("indexed") and attr_type not in INDEXABLE_TYPES:
            warnings.append(f"Attribute '{attr_name}' has indexed=true but type '{attr_type}' may not support indexing efficiently")
        if not attr_data.get("type"):
            errors.append(f"Attribute '{attr_name}' is missing required 'type' field")

    # Validate detail_tabs
    for tab in raw.get("detail_tabs", []):
        if not isinstance(tab, dict):
            errors.append("detail_tabs entries must be objects")
            continue
        if not tab.get("label"):
            errors.append("detail_tab is missing required 'label' field")
        if not tab.get("edge_type"):
            errors.append(f"detail_tab '{tab.get('label', '?')}' is missing required 'edge_type' field")
        if not tab.get("target_type"):
            errors.append(f"detail_tab '{tab.get('label', '?')}' is missing required 'target_type' field")

        # Check display_name
        if not attr_data.get("display_name"):
            warnings.append(f"Attribute '{attr_name}' is missing display_name — column headers will show raw name")

    # Check search config
    search = raw.get("search", {})
    if search.get("enabled") and not search.get("primary_field"):
        warnings.append("search.enabled is true but no primary_field defined")

    # Check API config
    api = raw.get("api", {})
    if not api.get("plural_name"):
        warnings.append("Missing api.plural_name — API routes may not work correctly")

    return errors, warnings


def _validate_edge_type_deep(raw: dict) -> tuple[list[str], list[str]]:
    """Extended validation for edge types."""
    errors: list[str] = []
    warnings: list[str] = []

    cardinality = raw.get("cardinality")
    if cardinality and cardinality not in VALID_CARDINALITIES:
        errors.append(f"Invalid cardinality: '{cardinality}'")
    if not cardinality:
        errors.append("Missing required 'cardinality' field")

    if not raw.get("metadata", {}).get("display_name"):
        warnings.append("Missing metadata.display_name")

    # Validate edge attributes
    for attr_name, attr_data in raw.get("attributes", {}).items():
        attr_type = attr_data.get("type")
        if attr_type and attr_type not in VALID_ATTRIBUTE_TYPES:
            errors.append(f"Edge attribute '{attr_name}' has invalid type: '{attr_type}'")

    return errors, warnings


def validate_cross_references(raw: dict, registry: SchemaRegistry) -> tuple[list[str], list[str]]:
    """Validate cross-references against the live schema registry.

    Checks:
    - Edge source/target node types exist in the registry
    - Referenced mixins exist
    - enum_ref references resolve
    - reference_node_type attributes point to known types
    """
    errors: list[str] = []
    warnings: list[str] = []
    kind = raw.get("kind")

    if kind == "NodeType":
        deep_errors, deep_warnings = _validate_node_type_deep(raw)
        errors.extend(deep_errors)
        warnings.extend(deep_warnings)

        # Check mixin references
        for mixin_name in raw.get("mixins", []):
            if not registry.get_mixin(mixin_name):
                errors.append(f"Referenced mixin '{mixin_name}' does not exist in the registry")

        # Check attribute references
        for attr_name, attr_data in raw.get("attributes", {}).items():
            ref_type = attr_data.get("reference_node_type")
            if ref_type and not registry.get_node_type(ref_type):
                errors.append(f"Attribute '{attr_name}' references unknown node type: '{ref_type}'")

        # Check detail_tabs cross-references
        for tab in raw.get("detail_tabs", []):
            if not isinstance(tab, dict):
                continue
            edge_type = tab.get("edge_type")
            target_type = tab.get("target_type")
            label = tab.get("label", "?")
            if edge_type and not registry.get_edge_type(edge_type):
                warnings.append(f"detail_tab '{label}' references edge type '{edge_type}' not yet in registry")
            if target_type and not registry.get_node_type(target_type):
                warnings.append(f"detail_tab '{label}' references target type '{target_type}' not yet in registry")
            # Validate columns exist on target type
            if target_type:
                target_def = registry.get_node_type(target_type)
                if target_def:
                    for col in tab.get("columns", []):
                        if col not in target_def.attributes:
                            warnings.append(f"detail_tab '{label}' column '{col}' not found in {target_type} attributes")

    elif kind == "EdgeType":
        deep_errors, deep_warnings = _validate_edge_type_deep(raw)
        errors.extend(deep_errors)
        warnings.extend(deep_warnings)

        for nt in raw.get("source", {}).get("node_types", []):
            if not registry.get_node_type(nt):
                errors.append(f"Source node type '{nt}' does not exist in the registry")
        for nt in raw.get("target", {}).get("node_types", []):
            if not registry.get_node_type(nt):
                errors.append(f"Target node type '{nt}' does not exist in the registry")

    return errors, warnings


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
