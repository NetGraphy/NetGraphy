"""Schema Registry — runtime store for all loaded schema definitions.

The registry is the central authority for schema metadata. All components
(API routers, graph repository, UI metadata endpoints, validation) consult
the registry to understand what node types, edge types, and attributes exist.
"""

from __future__ import annotations

import structlog

from packages.schema_engine.loaders.yaml_loader import load_directory
from packages.schema_engine.models import (
    EdgeTypeDefinition,
    EnumTypeDefinition,
    MixinDefinition,
    NodeTypeDefinition,
)

logger = structlog.get_logger()


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
            # TODO: Decide whether to raise or continue with warnings

    # ----- Queries --------------------------------------------------------- #

    def get_node_type(self, name: str) -> NodeTypeDefinition | None:
        return self._node_types.get(name)

    def get_edge_type(self, name: str) -> EdgeTypeDefinition | None:
        return self._edge_types.get(name)

    def get_mixin(self, name: str) -> MixinDefinition | None:
        return self._mixins.get(name)

    def get_enum_type(self, name: str) -> EnumTypeDefinition | None:
        return self._enum_types.get(name)

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

    # ----- Validation ------------------------------------------------------ #

    def validate_node_properties(self, node_type: str, properties: dict) -> list[str]:
        """Validate properties against a node type's schema.

        Returns a list of error messages (empty if valid).
        """
        defn = self.get_node_type(node_type)
        if not defn:
            return [f"Unknown node type: {node_type}"]

        errors = []
        for attr_name, attr_def in defn.attributes.items():
            if attr_def.required and attr_def.auto_set is None:
                if attr_name not in properties:
                    errors.append(f"Missing required attribute: {attr_name}")

        for key in properties:
            if key not in defn.attributes and key != "id":
                errors.append(f"Unknown attribute: {key}")

        # TODO: Type validation, enum validation, regex validation, uniqueness checks
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
