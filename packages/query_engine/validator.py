"""Schema-aware query validator — resolves filter paths and validates operators.

Every query must pass through this validator before compilation. It:
1. Resolves filter paths against the schema registry (direct attrs, relationship paths)
2. Validates operators are legal for the field type
3. Enforces pagination and nesting limits
4. Rejects invalid paths before they reach the query compiler
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from packages.query_engine.models import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    LogicalOperator,
    OPERATORS_BY_TYPE,
    Pagination,
    QueryAST,
    ResolvedPath,
    ResolvedPathSegment,
    SortField,
)
from packages.schema_engine.models import (
    AttributeDefinition,
    AttributeType,
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


def _slugify(name: str) -> str:
    """Convert PascalCase/UPPER_CASE to snake_case for alias matching."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class QueryValidationError(Exception):
    """Raised when a query fails schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Query validation failed: {'; '.join(errors)}")


class QueryValidator:
    """Validates a QueryAST against the schema registry."""

    def __init__(self, registry: SchemaRegistry):
        self._registry = registry
        # Pre-compute edge lookup tables for fast path resolution
        self._edge_by_alias: dict[str, dict[str, EdgeTypeDefinition]] = {}
        self._build_edge_index()

    def _build_edge_index(self) -> None:
        """Build edge type lookup indexed by source node type and alias."""
        for et in self._registry._edge_types.values():
            alias = et.query.query_alias or _slugify(et.metadata.name)
            for src in et.source.node_types:
                if src not in self._edge_by_alias:
                    self._edge_by_alias[src] = {}
                self._edge_by_alias[src][alias] = et
            # Also index by target (for incoming traversals)
            for tgt in et.target.node_types:
                inv_alias = f"inv_{alias}"
                if tgt not in self._edge_by_alias:
                    self._edge_by_alias[tgt] = {}
                self._edge_by_alias[tgt][inv_alias] = et

    def validate(self, ast: QueryAST) -> list[ResolvedPath]:
        """Validate a QueryAST and return resolved filter paths.

        Raises QueryValidationError if any validation fails.
        """
        errors: list[str] = []

        # 1. Validate entity type exists
        nt = self._registry.get_node_type(ast.entity)
        if not nt:
            raise QueryValidationError([f"Unknown entity type: {ast.entity}"])

        # 2. Validate pagination limits
        query_meta = nt.query
        if ast.pagination.limit > query_meta.max_page_size:
            errors.append(
                f"Limit {ast.pagination.limit} exceeds max_page_size "
                f"{query_meta.max_page_size} for {ast.entity}"
            )

        # 3. Validate sort fields
        for sf in ast.sort:
            attr = nt.attributes.get(sf.field)
            if not attr:
                errors.append(f"Cannot sort by unknown field: {ast.entity}.{sf.field}")
            elif not attr.query.sortable:
                errors.append(f"Field {ast.entity}.{sf.field} is not sortable")

        # 4. Validate field selection
        if ast.fields:
            for f in ast.fields:
                if f not in nt.attributes and f != "id":
                    errors.append(f"Unknown return field: {ast.entity}.{f}")

        # 5. Validate and resolve filter paths
        resolved_paths: list[ResolvedPath] = []
        if ast.filters:
            self._validate_filter_group(
                ast.filters, nt, resolved_paths, errors, depth=0,
                max_depth=query_meta.max_filter_nesting,
            )

        if errors:
            raise QueryValidationError(errors)

        return resolved_paths

    def _validate_filter_group(
        self,
        group: FilterGroup,
        node_type: NodeTypeDefinition,
        resolved: list[ResolvedPath],
        errors: list[str],
        depth: int,
        max_depth: int,
    ) -> None:
        """Recursively validate a filter group."""
        if depth > max_depth:
            errors.append(f"Filter nesting exceeds maximum depth of {max_depth}")
            return

        for condition in group.conditions:
            if isinstance(condition, FilterGroup):
                self._validate_filter_group(
                    condition, node_type, resolved, errors, depth + 1, max_depth,
                )
            else:
                rp = self._resolve_filter_path(condition, node_type, errors)
                if rp:
                    resolved.append(rp)

    def _resolve_filter_path(
        self,
        condition: FilterCondition,
        node_type: NodeTypeDefinition,
        errors: list[str],
    ) -> ResolvedPath | None:
        """Resolve a single filter condition's path against the schema.

        Handles:
        - Direct attributes: "status" → attribute on the node
        - Relationship paths: "located_at.Location.city" → traverse edge then filter
        - Relationship existence: "located_at" with exists/not_exists operator
        - Relationship count: "located_at" with count_* operator
        """
        path = condition.path
        operator = condition.operator
        parts = path.split(".")

        # --- Case 1: Direct attribute (no dots) ---
        if len(parts) == 1:
            attr_name = parts[0]

            # Check if it's a relationship existence/count filter
            if operator in (
                FilterOperator.EXISTS, FilterOperator.NOT_EXISTS,
                FilterOperator.COUNT_EQ, FilterOperator.COUNT_GT,
                FilterOperator.COUNT_GTE, FilterOperator.COUNT_LT,
                FilterOperator.COUNT_LTE,
            ):
                return self._resolve_relationship_filter(
                    attr_name, operator, node_type, errors,
                )

            # Direct attribute filter
            attr = node_type.attributes.get(attr_name)
            if not attr:
                errors.append(
                    f"Unknown attribute: {node_type.metadata.name}.{attr_name}"
                )
                return None

            if not attr.query.filterable:
                errors.append(
                    f"Attribute {node_type.metadata.name}.{attr_name} is not filterable"
                )
                return None

            # Validate operator for attribute type
            self._validate_operator(attr, operator, node_type.metadata.name, errors)

            return ResolvedPath(
                raw_path=path,
                segments=[ResolvedPathSegment(attribute=attr_name)],
            )

        # --- Case 2: Relationship path (dots present) ---
        # Format: edge_alias.TargetType.attribute
        # or: edge_alias.attribute (edge property)
        if len(parts) == 2:
            edge_alias, attr_or_type = parts
            return self._resolve_two_part_path(
                edge_alias, attr_or_type, operator, node_type, errors, path,
            )

        if len(parts) == 3:
            edge_alias, target_type_name, attr_name = parts
            return self._resolve_three_part_path(
                edge_alias, target_type_name, attr_name, operator,
                node_type, errors, path,
            )

        errors.append(f"Filter path too deep: {path} (max 3 segments)")
        return None

    def _resolve_relationship_filter(
        self,
        alias: str,
        operator: FilterOperator,
        node_type: NodeTypeDefinition,
        errors: list[str],
    ) -> ResolvedPath | None:
        """Resolve a relationship existence or count filter."""
        edges = self._edge_by_alias.get(node_type.metadata.name, {})
        et = edges.get(alias)
        if not et:
            errors.append(
                f"Unknown relationship alias '{alias}' for {node_type.metadata.name}"
            )
            return None

        if not et.query.traversable:
            errors.append(f"Relationship '{alias}' is not traversable for queries")
            return None

        is_existence = operator in (FilterOperator.EXISTS, FilterOperator.NOT_EXISTS)
        is_count = operator.value.startswith("count_")

        if is_existence and not et.query.supports_existence_filter:
            errors.append(
                f"Relationship '{alias}' does not support existence filters"
            )
            return None

        if is_count and not et.query.supports_count_filter:
            errors.append(
                f"Relationship '{alias}' does not support count filters"
            )
            return None

        # Determine direction
        direction = "outgoing"
        target_types = et.target.node_types
        if node_type.metadata.name in et.target.node_types:
            direction = "incoming"
            target_types = et.source.node_types

        return ResolvedPath(
            raw_path=alias,
            segments=[
                ResolvedPathSegment(
                    edge_type=et.metadata.name,
                    direction=direction,
                    target_type=target_types[0] if target_types else None,
                ),
            ],
            is_relationship_existence=is_existence,
            is_relationship_count=is_count,
        )

    def _resolve_two_part_path(
        self,
        edge_alias: str,
        attr_or_type: str,
        operator: FilterOperator,
        node_type: NodeTypeDefinition,
        errors: list[str],
        raw_path: str,
    ) -> ResolvedPath | None:
        """Resolve a two-part path: edge_alias.attribute (edge property)."""
        edges = self._edge_by_alias.get(node_type.metadata.name, {})
        et = edges.get(edge_alias)
        if not et:
            errors.append(
                f"Unknown relationship alias '{edge_alias}' for {node_type.metadata.name}"
            )
            return None

        if not et.query.traversable:
            errors.append(f"Relationship '{edge_alias}' is not traversable for queries")
            return None

        # Check if attr_or_type is an edge attribute
        edge_attr = et.attributes.get(attr_or_type)
        if edge_attr:
            self._validate_operator(edge_attr, operator, f"edge:{et.metadata.name}", errors)
            direction = "outgoing"
            if node_type.metadata.name in et.target.node_types:
                direction = "incoming"

            return ResolvedPath(
                raw_path=raw_path,
                segments=[
                    ResolvedPathSegment(
                        edge_type=et.metadata.name,
                        direction=direction,
                        attribute=attr_or_type,
                    ),
                ],
            )

        # Otherwise check if it's a target type's attribute — try to find the target
        # by checking all target types for this attribute
        direction = "outgoing"
        target_types = et.target.node_types
        if node_type.metadata.name in et.target.node_types:
            direction = "incoming"
            target_types = et.source.node_types

        for tt_name in target_types:
            tt = self._registry.get_node_type(tt_name)
            if tt and attr_or_type in tt.attributes:
                attr = tt.attributes[attr_or_type]
                self._validate_operator(attr, operator, tt_name, errors)
                return ResolvedPath(
                    raw_path=raw_path,
                    segments=[
                        ResolvedPathSegment(
                            edge_type=et.metadata.name,
                            direction=direction,
                            target_type=tt_name,
                        ),
                        ResolvedPathSegment(attribute=attr_or_type),
                    ],
                )

        errors.append(
            f"Unknown attribute '{attr_or_type}' on edge or target "
            f"of relationship '{edge_alias}'"
        )
        return None

    def _resolve_three_part_path(
        self,
        edge_alias: str,
        target_type_name: str,
        attr_name: str,
        operator: FilterOperator,
        node_type: NodeTypeDefinition,
        errors: list[str],
        raw_path: str,
    ) -> ResolvedPath | None:
        """Resolve a three-part path: edge_alias.TargetType.attribute."""
        edges = self._edge_by_alias.get(node_type.metadata.name, {})
        et = edges.get(edge_alias)
        if not et:
            errors.append(
                f"Unknown relationship alias '{edge_alias}' for {node_type.metadata.name}"
            )
            return None

        if not et.query.traversable:
            errors.append(f"Relationship '{edge_alias}' is not traversable for queries")
            return None

        # Validate target type
        direction = "outgoing"
        valid_targets = et.target.node_types
        if node_type.metadata.name in et.target.node_types:
            direction = "incoming"
            valid_targets = et.source.node_types

        if target_type_name not in valid_targets:
            errors.append(
                f"Target type '{target_type_name}' is not a valid target for "
                f"relationship '{edge_alias}' from {node_type.metadata.name}"
            )
            return None

        # Validate attribute on target type
        target_nt = self._registry.get_node_type(target_type_name)
        if not target_nt:
            errors.append(f"Unknown target node type: {target_type_name}")
            return None

        attr = target_nt.attributes.get(attr_name)
        if not attr:
            errors.append(f"Unknown attribute: {target_type_name}.{attr_name}")
            return None

        if not attr.query.filterable:
            errors.append(
                f"Attribute {target_type_name}.{attr_name} is not filterable"
            )
            return None

        self._validate_operator(attr, operator, target_type_name, errors)

        return ResolvedPath(
            raw_path=raw_path,
            segments=[
                ResolvedPathSegment(
                    edge_type=et.metadata.name,
                    direction=direction,
                    target_type=target_type_name,
                ),
                ResolvedPathSegment(attribute=attr_name),
            ],
        )

    def _validate_operator(
        self,
        attr: AttributeDefinition,
        operator: FilterOperator,
        context: str,
        errors: list[str],
    ) -> None:
        """Validate that an operator is legal for the given attribute type."""
        type_key = attr.type.value
        allowed = OPERATORS_BY_TYPE.get(type_key, set())

        if operator.value not in allowed:
            errors.append(
                f"Operator '{operator.value}' is not supported for "
                f"{context}.{attr.name} (type: {type_key}). "
                f"Allowed: {sorted(allowed)}"
            )

    def get_allowed_filter_paths(self, entity: str) -> list[dict[str, Any]]:
        """Return all valid filter paths for a node type.

        Used by the MCP generator to document available filters in tool schemas.
        """
        nt = self._registry.get_node_type(entity)
        if not nt:
            return []

        paths: list[dict[str, Any]] = []

        # Direct attributes
        for attr_name, attr in nt.attributes.items():
            if attr.query.filterable:
                type_key = attr.type.value
                ops = sorted(OPERATORS_BY_TYPE.get(type_key, set()))
                paths.append({
                    "path": attr_name,
                    "type": type_key,
                    "operators": ops,
                    "description": attr.description or f"Filter by {attr_name}",
                    "enum_values": attr.enum_values,
                })

        # Relationship traversal paths
        edges = self._edge_by_alias.get(entity, {})
        for alias, et in edges.items():
            if alias.startswith("inv_") or not et.query.traversable:
                continue

            # Determine target type(s)
            direction = "outgoing"
            target_types = et.target.node_types
            if entity in et.target.node_types and entity not in et.source.node_types:
                direction = "incoming"
                target_types = et.source.node_types

            # Relationship existence
            if et.query.supports_existence_filter:
                paths.append({
                    "path": alias,
                    "type": "relationship_existence",
                    "operators": ["exists", "not_exists"],
                    "description": f"Filter by existence of {alias} relationship",
                })

            # Relationship count
            if et.query.supports_count_filter:
                paths.append({
                    "path": alias,
                    "type": "relationship_count",
                    "operators": ["count_eq", "count_gt", "count_gte", "count_lt", "count_lte"],
                    "description": f"Filter by count of {alias} relationships",
                })

            # Target type attributes
            for tt_name in target_types:
                tt = self._registry.get_node_type(tt_name)
                if not tt:
                    continue
                for attr_name, attr in tt.attributes.items():
                    if attr.query.filterable:
                        type_key = attr.type.value
                        ops = sorted(OPERATORS_BY_TYPE.get(type_key, set()))
                        paths.append({
                            "path": f"{alias}.{tt_name}.{attr_name}",
                            "type": type_key,
                            "operators": ops,
                            "description": (
                                f"Filter by {attr_name} on related {tt_name} "
                                f"via {alias}"
                            ),
                        })

            # Edge attributes
            for attr_name, attr in et.attributes.items():
                type_key = attr.type.value
                ops = sorted(OPERATORS_BY_TYPE.get(type_key, set()))
                paths.append({
                    "path": f"{alias}.{attr_name}",
                    "type": type_key,
                    "operators": ops,
                    "description": f"Filter by edge property {attr_name} on {alias}",
                })

        return paths

    def get_sortable_fields(self, entity: str) -> list[str]:
        """Return all sortable field names for a node type."""
        nt = self._registry.get_node_type(entity)
        if not nt:
            return []
        return [
            name for name, attr in nt.attributes.items()
            if attr.query.sortable
        ]

    def get_default_fields(self, entity: str) -> list[str]:
        """Return default return fields for a node type."""
        nt = self._registry.get_node_type(entity)
        if not nt:
            return ["id"]

        # Use explicit default_list_fields if set
        if nt.query.default_list_fields:
            return ["id"] + nt.query.default_list_fields

        # Fall back to list_column fields from UI metadata
        columns = []
        for name, attr in nt.attributes.items():
            if attr.ui.list_column:
                columns.append((attr.ui.list_column_order or 999, name))
        columns.sort()

        if columns:
            return ["id"] + [name for _, name in columns]

        # Last resort: return all non-sensitive fields
        return ["id"] + [
            name for name, attr in nt.attributes.items()
            if not attr.health.sensitive
        ]
