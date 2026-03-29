"""Schema Registry — runtime store for all loaded schema definitions.

The registry is the central authority for schema metadata. All components
(API routers, graph repository, UI metadata endpoints, validation) consult
the registry to understand what node types, edge types, and attributes exist.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

import structlog

from packages.schema_engine.loaders.yaml_loader import load_directory
from packages.schema_engine.models import (
    AttributeDefinition,
    AttributeType,
    EdgeTypeDefinition,
    EnumTypeDefinition,
    MixinDefinition,
    NodeTypeDefinition,
)

logger = structlog.get_logger()

# Regex patterns for network-specific types
_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}[:\-.]?){5}[0-9a-fA-F]{2}$|^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_URL_RE = re.compile(r"^https?://\S+$")


class SchemaRegistry:
    """In-memory registry of all schema definitions.

    Loaded from YAML files at startup. Refreshed on schema change events
    (Git sync, manual upload). Cached in Redis for worker processes.
    """

    def __init__(self) -> None:
        self._node_types: dict[str, NodeTypeDefinition] = {}
        self._edge_types: dict[str, EdgeTypeDefinition] = {}
        self._mixins: dict[str, MixinDefinition] = {}
        self._enum_types: dict[str, EnumTypeDefinition] = {}

    # ----- Loading --------------------------------------------------------- #

    async def load_from_directories(self, directories: list[str]) -> dict[str, int]:
        """Load schema files from one or more directories.

        Returns a summary dict with counts of loaded types.
        """
        for directory in directories:
            definitions = load_directory(directory)
            for defn in definitions:
                self._register(defn)

        self._resolve_mixins()
        self._validate_references()

        counts = {
            "node_types": len(self._node_types),
            "edge_types": len(self._edge_types),
            "mixins": len(self._mixins),
            "enum_types": len(self._enum_types),
        }
        logger.info("Schema registry loaded", **counts)
        return counts

    def _register(self, defn) -> None:
        """Register a single schema definition."""
        if isinstance(defn, NodeTypeDefinition):
            self._node_types[defn.name] = defn
        elif isinstance(defn, EdgeTypeDefinition):
            self._edge_types[defn.name] = defn
        elif isinstance(defn, MixinDefinition):
            self._mixins[defn.name] = defn
        elif isinstance(defn, EnumTypeDefinition):
            self._enum_types[defn.name] = defn

    def _resolve_mixins(self) -> None:
        """Resolve mixin references and merge attributes into node types.

        Mixin attributes are added to the node type if not already defined
        (node type attributes take precedence over mixin attributes).
        """
        for node_type in self._node_types.values():
            for mixin_name in node_type.mixins:
                mixin = self._mixins.get(mixin_name)
                if not mixin:
                    logger.warning("Mixin not found", mixin=mixin_name,
                                   node_type=node_type.name)
                    continue
                for attr_name, attr_def in mixin.attributes.items():
                    if attr_name not in node_type.attributes:
                        node_type.attributes[attr_name] = attr_def

    def _validate_references(self) -> None:
        """Validate that all cross-references in the schema are resolvable."""
        errors = []

        for edge in self._edge_types.values():
            for source_type in edge.source.node_types:
                if source_type not in self._node_types:
                    errors.append(
                        f"Edge '{edge.name}' references unknown source type '{source_type}'"
                    )
            for target_type in edge.target.node_types:
                if target_type not in self._node_types:
                    errors.append(
                        f"Edge '{edge.name}' references unknown target type '{target_type}'"
                    )

        if errors:
            for error in errors:
                logger.error("Schema validation error", error=error)

    # ----- Queries --------------------------------------------------------- #

    def get_node_type(self, name: str) -> NodeTypeDefinition | None:
        return self._node_types.get(name)

    def get_edge_type(self, name: str) -> EdgeTypeDefinition | None:
        return self._edge_types.get(name)

    def get_mixin(self, name: str) -> MixinDefinition | None:
        return self._mixins.get(name)

    def get_enum_type(self, name: str) -> EnumTypeDefinition | None:
        return self._enum_types.get(name)

    def require_node_type(self, name: str) -> NodeTypeDefinition:
        """Get a node type or raise SchemaNotFoundError."""
        defn = self._node_types.get(name)
        if not defn:
            from apps.api.netgraphy_api.exceptions import SchemaNotFoundError
            raise SchemaNotFoundError("NodeType", name)
        return defn

    def require_edge_type(self, name: str) -> EdgeTypeDefinition:
        """Get an edge type or raise SchemaNotFoundError."""
        defn = self._edge_types.get(name)
        if not defn:
            from apps.api.netgraphy_api.exceptions import SchemaNotFoundError
            raise SchemaNotFoundError("EdgeType", name)
        return defn

    def list_node_types(self) -> list[dict]:
        """Return all node types as serializable dicts."""
        return [nt.model_dump() for nt in self._node_types.values()]

    def list_edge_types(self) -> list[dict]:
        """Return all edge types as serializable dicts."""
        return [et.model_dump() for et in self._edge_types.values()]

    def list_enum_types(self) -> list[dict]:
        """Return all enum types as serializable dicts."""
        return [et.model_dump() for et in self._enum_types.values()]

    def get_categories(self) -> list[dict]:
        """Return node types grouped by category for UI navigation."""
        categories: dict[str, list[str]] = {}
        for nt in self._node_types.values():
            cat = nt.metadata.category or "Other"
            categories.setdefault(cat, []).append(nt.metadata.name)

        return [
            {"name": name, "node_types": sorted(types)}
            for name, types in sorted(categories.items())
        ]

    def get_edges_for_node_type(self, node_type: str) -> list[EdgeTypeDefinition]:
        """Return all edge types that connect to or from a node type."""
        return [
            et for et in self._edge_types.values()
            if node_type in et.source.node_types or node_type in et.target.node_types
        ]

    # ----- Validation ------------------------------------------------------ #

    def validate_node_properties(self, node_type: str, properties: dict) -> list[str]:
        """Validate properties against a node type's schema.

        Performs:
        1. Required attribute presence checks
        2. Unknown attribute rejection
        3. Type validation and coercion
        4. Enum value validation
        5. Regex pattern validation
        6. Network type validation (IP, MAC, CIDR)
        7. Length and range constraints

        Returns a list of error messages (empty if valid).
        """
        defn = self.get_node_type(node_type)
        if not defn:
            return [f"Unknown node type: {node_type}"]

        errors = []

        # Check required attributes (skip auto_set and fields with defaults)
        for attr_name, attr_def in defn.attributes.items():
            if attr_def.required and attr_def.auto_set is None and attr_def.default is None:
                if attr_name not in properties:
                    errors.append(f"Missing required attribute: {attr_name}")

        # Apply defaults for missing attributes that have them
        for attr_name, attr_def in defn.attributes.items():
            if attr_name not in properties and attr_def.default is not None:
                properties[attr_name] = attr_def.default

        # Check unknown attributes (skip internal _-prefixed fields set by the service layer)
        for key in properties:
            if key.startswith("_") or key == "id":
                continue
            if key not in defn.attributes:
                errors.append(f"Unknown attribute: {key}")

        # Validate each provided property against its definition
        for key, value in properties.items():
            if key == "id":
                continue
            attr_def = defn.attributes.get(key)
            if not attr_def:
                continue  # Already reported as unknown
            if value is None:
                if attr_def.required and attr_def.auto_set is None:
                    errors.append(f"Attribute '{key}' cannot be null (required)")
                continue

            attr_errors = _validate_attribute_value(key, value, attr_def)
            errors.extend(attr_errors)

        return errors

    def validate_edge_properties(self, edge_type: str, properties: dict) -> list[str]:
        """Validate edge properties against schema."""
        defn = self.get_edge_type(edge_type)
        if not defn:
            return [f"Unknown edge type: {edge_type}"]

        errors = []
        for attr_name, attr_def in defn.attributes.items():
            if attr_def.required and attr_name not in properties:
                errors.append(f"Missing required edge attribute: {attr_name}")

        for key, value in properties.items():
            if key in ("id", "source_id", "target_id"):
                continue
            attr_def = defn.attributes.get(key)
            if not attr_def:
                errors.append(f"Unknown edge attribute: {key}")
                continue
            if value is not None:
                attr_errors = _validate_attribute_value(key, value, attr_def)
                errors.extend(attr_errors)

        return errors

    def get_indexes_for_type(self, node_type: str) -> list[dict]:
        """Return index definitions needed for a node type."""
        defn = self.get_node_type(node_type)
        if not defn:
            return []

        indexes = []
        for attr_name, attr_def in defn.attributes.items():
            if attr_def.indexed:
                indexes.append({
                    "label": node_type,
                    "property": attr_name,
                    "unique": attr_def.unique,
                })
        return indexes


# --------------------------------------------------------------------------- #
#  Attribute Validation Helpers                                                #
# --------------------------------------------------------------------------- #

def _validate_attribute_value(
    attr_name: str,
    value: Any,
    attr_def: AttributeDefinition,
) -> list[str]:
    """Validate a single attribute value against its definition."""
    errors = []
    attr_type = attr_def.type

    # Type checking
    type_error = _check_type(attr_name, value, attr_type)
    if type_error:
        errors.append(type_error)
        return errors  # Skip further checks if type is wrong

    # Enum validation
    if attr_type == AttributeType.ENUM:
        if attr_def.enum_values and value not in attr_def.enum_values:
            errors.append(
                f"Attribute '{attr_name}': value '{value}' not in allowed values "
                f"{attr_def.enum_values}"
            )

    # String length validation
    if attr_type in (AttributeType.STRING, AttributeType.TEXT) and isinstance(value, str):
        if attr_def.max_length and len(value) > attr_def.max_length:
            errors.append(
                f"Attribute '{attr_name}': length {len(value)} exceeds max_length {attr_def.max_length}"
            )

    # Numeric range validation
    if attr_type in (AttributeType.INTEGER, AttributeType.FLOAT):
        if attr_def.min_value is not None and value < attr_def.min_value:
            errors.append(f"Attribute '{attr_name}': value {value} below min {attr_def.min_value}")
        if attr_def.max_value is not None and value > attr_def.max_value:
            errors.append(f"Attribute '{attr_name}': value {value} above max {attr_def.max_value}")

    # Regex validation
    if attr_def.validation_regex and isinstance(value, str):
        if not re.match(attr_def.validation_regex, value):
            errors.append(
                f"Attribute '{attr_name}': value does not match pattern '{attr_def.validation_regex}'"
            )

    # Network type validation
    if attr_type == AttributeType.IP_ADDRESS:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            errors.append(f"Attribute '{attr_name}': '{value}' is not a valid IP address")

    if attr_type == AttributeType.CIDR:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            errors.append(f"Attribute '{attr_name}': '{value}' is not a valid CIDR notation")

    if attr_type == AttributeType.MAC_ADDRESS:
        if not _MAC_RE.match(str(value)):
            errors.append(f"Attribute '{attr_name}': '{value}' is not a valid MAC address")

    if attr_type == AttributeType.EMAIL:
        if not _EMAIL_RE.match(str(value)):
            errors.append(f"Attribute '{attr_name}': '{value}' is not a valid email address")

    if attr_type == AttributeType.URL:
        if not _URL_RE.match(str(value)):
            errors.append(f"Attribute '{attr_name}': '{value}' is not a valid URL")

    return errors


def _check_type(attr_name: str, value: Any, attr_type: AttributeType) -> str | None:
    """Check if a value matches the expected attribute type. Returns error or None."""
    type_checks = {
        AttributeType.STRING: (str,),
        AttributeType.TEXT: (str,),
        AttributeType.INTEGER: (int,),
        AttributeType.FLOAT: (int, float),
        AttributeType.BOOLEAN: (bool,),
        AttributeType.ENUM: (str,),
        AttributeType.IP_ADDRESS: (str,),
        AttributeType.CIDR: (str,),
        AttributeType.MAC_ADDRESS: (str,),
        AttributeType.URL: (str,),
        AttributeType.EMAIL: (str,),
        AttributeType.REFERENCE: (str,),
        AttributeType.JSON: (dict, list, str),
    }

    expected = type_checks.get(attr_type)
    if expected and not isinstance(value, expected):
        # Allow int for float
        if attr_type == AttributeType.FLOAT and isinstance(value, int):
            return None
        # Don't type-check booleans as int (Python: bool is subclass of int)
        if attr_type == AttributeType.INTEGER and isinstance(value, bool):
            return f"Attribute '{attr_name}': expected integer, got boolean"
        return f"Attribute '{attr_name}': expected {attr_type.value}, got {type(value).__name__}"

    # List type validation
    if attr_type == AttributeType.LIST_STRING:
        if not isinstance(value, list):
            return f"Attribute '{attr_name}': expected list, got {type(value).__name__}"
        for i, item in enumerate(value):
            if not isinstance(item, str):
                return f"Attribute '{attr_name}[{i}]': expected string, got {type(item).__name__}"

    if attr_type == AttributeType.LIST_INTEGER:
        if not isinstance(value, list):
            return f"Attribute '{attr_name}': expected list, got {type(value).__name__}"
        for i, item in enumerate(value):
            if not isinstance(item, int) or isinstance(item, bool):
                return f"Attribute '{attr_name}[{i}]': expected integer, got {type(item).__name__}"

    # Datetime/date are stored as strings in Neo4j
    if attr_type in (AttributeType.DATETIME, AttributeType.DATE):
        if not isinstance(value, str):
            return f"Attribute '{attr_name}': expected ISO 8601 string, got {type(value).__name__}"

    return None
