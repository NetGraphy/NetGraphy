"""Report compiler — compiles ReportDefinition into Cypher with row expansion.

Handles:
- Root field columns → n.field AS alias
- Related node columns → traverse edge, project target field
- Edge attribute columns → project edge property
- Aggregate columns → count/sum aggregation
- Row expansion for one-to-many relationships (CSV-safe)
- Row flattening for CSV export

The compiler uses the existing QueryValidator for path resolution and extends
the QueryCompiler's filter compilation for the WHERE clause.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from packages.query_engine.compiler import CompiledQuery, QueryCompiler, _CompilerState
from packages.query_engine.models import (
    FilterGroup,
    Pagination,
    ResolvedPath,
    SortDirection,
    SortField,
)
from packages.query_engine.report_models import (
    ColumnSource,
    ReportColumn,
    ReportDefinition,
    ReportResult,
    RowMode,
)
from packages.query_engine.validator import QueryValidator
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class _ResolvedColumn:
    """Internal representation of a resolved report column."""

    def __init__(
        self,
        column: ReportColumn,
        cypher_expr: str,
        csv_header: str,
        requires_match: str | None = None,  # Additional MATCH clause needed
        match_var: str | None = None,
        edge_var: str | None = None,
        is_expansion: bool = False,  # This column causes row expansion
    ):
        self.column = column
        self.cypher_expr = cypher_expr
        self.csv_header = csv_header
        self.requires_match = requires_match
        self.match_var = match_var
        self.edge_var = edge_var
        self.is_expansion = is_expansion


class ReportCompiler:
    """Compiles a ReportDefinition into executable Cypher."""

    def __init__(self, registry: SchemaRegistry):
        self._registry = registry
        self._validator = QueryValidator(registry)
        self._query_compiler = QueryCompiler()

    def compile(self, report: ReportDefinition) -> CompiledQuery:
        """Compile a report definition into Cypher queries.

        Returns data query + optional count query.
        """
        state = _CompilerState()
        entity = report.root_entity

        # Primary MATCH
        state.match_clauses.append(f"MATCH (n:{entity})")

        # Compile filters (reuse the query compiler's filter logic)
        resolved_paths: list[ResolvedPath] = []
        if report.filters:
            from packages.query_engine.models import QueryAST
            # Validate filter paths
            temp_ast = QueryAST(entity=entity, filters=report.filters)
            resolved_paths = self._validator.validate(temp_ast)

            path_map = {rp.raw_path: rp for rp in resolved_paths}
            where_expr = self._query_compiler._compile_filter_group(
                report.filters, state, path_map,
            )
            if where_expr:
                state.where_clauses.append(where_expr)

        # Handle aggregate mode separately
        if report.row_mode == RowMode.AGGREGATE:
            return self._compile_aggregate(report, state)

        # Resolve columns
        resolved_columns = self._resolve_columns(report, state)

        # Build core query
        core = self._build_core(state)

        # Build RETURN clause from resolved columns
        return_parts = []
        csv_headers = []
        for rc in resolved_columns:
            return_parts.append(f"{rc.cypher_expr} AS {rc.csv_header}")
            csv_headers.append(rc.csv_header)

        # Determine if we need DISTINCT (root mode with no expansion)
        has_expansion = any(rc.is_expansion for rc in resolved_columns)
        distinct = "" if has_expansion else "DISTINCT "

        return_clause = f"RETURN {distinct}{', '.join(return_parts)}"

        # Sort
        order_clause = self._build_order(report.sort, resolved_columns)

        # Pagination
        state.params["__skip"] = report.pagination.offset
        state.params["__limit"] = min(report.pagination.limit, report.max_export_rows)
        pagination_clause = "SKIP $__skip LIMIT $__limit"

        data_query = f"{core}\n{return_clause}"
        if order_clause:
            data_query += f"\n{order_clause}"
        data_query += f"\n{pagination_clause}"

        # Count query
        count_query = f"{core}\nRETURN count({'n' if not has_expansion else '*'}) AS total"

        logger.debug("report_compiled", entity=entity, columns=len(resolved_columns),
                     row_mode=report.row_mode, has_expansion=has_expansion)

        return CompiledQuery(
            data_query=data_query,
            data_params=dict(state.params),
            count_query=count_query,
            count_params=dict(state.params),
        )

    def _resolve_columns(
        self,
        report: ReportDefinition,
        state: _CompilerState,
    ) -> list[_ResolvedColumn]:
        """Resolve report columns into Cypher expressions."""
        resolved: list[_ResolvedColumn] = []
        edge_index = self._validator._edge_by_alias
        # Track relationship matches already added
        added_matches: dict[str, tuple[str, str]] = {}  # key → (rel_var, target_var)
        match_counter = 0

        for col in report.columns:
            path_parts = col.path.split(".")

            # --- Root field ---
            if len(path_parts) == 1:
                field = path_parts[0]
                csv_header = col.alias or f"{_slugify(report.root_entity)}_{field}"
                resolved.append(_ResolvedColumn(
                    column=col,
                    cypher_expr=f"n.{field}",
                    csv_header=csv_header,
                ))
                continue

            # --- Edge attribute: alias.edge.field ---
            if len(path_parts) == 3 and path_parts[1] == "edge":
                edge_alias = path_parts[0]
                edge_field = path_parts[2]
                match_key = f"edge_{edge_alias}"

                if match_key not in added_matches:
                    et = self._find_edge(edge_alias, report.root_entity)
                    if not et:
                        continue
                    match_counter += 1
                    rel_var = f"re{match_counter}"
                    target_var = f"te{match_counter}"
                    direction = self._edge_direction(et, report.root_entity)
                    target_type = self._edge_target(et, report.root_entity)
                    label = f":{target_type}" if target_type else ""

                    if direction == "outgoing":
                        match_clause = f"MATCH (n)-[{rel_var}:{et.metadata.name}]->({target_var}{label})"
                    else:
                        match_clause = f"MATCH (n)<-[{rel_var}:{et.metadata.name}]-({target_var}{label})"

                    state.match_clauses.append(match_clause)
                    added_matches[match_key] = (rel_var, target_var)

                rel_var, _ = added_matches[match_key]
                csv_header = col.alias or f"{edge_alias}_{edge_field}"

                # Check cardinality for expansion
                et = self._find_edge(edge_alias, report.root_entity)
                is_expansion = self._is_one_to_many(et, report.root_entity) if et else False

                resolved.append(_ResolvedColumn(
                    column=col,
                    cypher_expr=f"{rel_var}.{edge_field}",
                    csv_header=csv_header,
                    edge_var=rel_var,
                    is_expansion=is_expansion and report.row_mode == RowMode.EXPANDED,
                ))
                continue

            # --- Aggregate: alias.count ---
            if len(path_parts) == 2 and path_parts[1] == "count":
                edge_alias = path_parts[0]
                et = self._find_edge(edge_alias, report.root_entity)
                if not et:
                    continue
                direction = self._edge_direction(et, report.root_entity)
                if direction == "outgoing":
                    pattern = f"(n)-[:{et.metadata.name}]->()"
                else:
                    pattern = f"(n)<-[:{et.metadata.name}]-()"
                csv_header = col.alias or f"{edge_alias}_count"
                resolved.append(_ResolvedColumn(
                    column=col,
                    cypher_expr=f"size([{pattern} | 1])",
                    csv_header=csv_header,
                ))
                continue

            # --- Related node field: alias.NodeType.field or alias.field ---
            edge_alias = path_parts[0]
            if len(path_parts) == 3:
                target_type_name = path_parts[1]
                field = path_parts[2]
            else:
                # Two-part: alias.field — auto-resolve target type
                field = path_parts[1]
                et = self._find_edge(edge_alias, report.root_entity)
                target_type_name = self._edge_target(et, report.root_entity) if et else None
                if not target_type_name:
                    continue

            match_key = f"rel_{edge_alias}_{target_type_name}"

            if match_key not in added_matches:
                et = self._find_edge(edge_alias, report.root_entity)
                if not et:
                    continue
                match_counter += 1
                rel_var = f"re{match_counter}"
                target_var = f"te{match_counter}"
                direction = self._edge_direction(et, report.root_entity)
                label = f":{target_type_name}" if target_type_name else ""

                # Use OPTIONAL MATCH for root row mode to preserve root rows
                # even when no related node exists
                match_type = "MATCH" if report.row_mode == RowMode.EXPANDED else "OPTIONAL MATCH"

                if direction == "outgoing":
                    match_clause = f"{match_type} (n)-[{rel_var}:{et.metadata.name}]->({target_var}{label})"
                else:
                    match_clause = f"{match_type} (n)<-[{rel_var}:{et.metadata.name}]-({target_var}{label})"

                state.match_clauses.append(match_clause)
                added_matches[match_key] = (rel_var, target_var)

            _, target_var = added_matches[match_key]
            csv_header = col.alias or f"{_slugify(target_type_name)}_{field}"

            et = self._find_edge(edge_alias, report.root_entity)
            is_expansion = self._is_one_to_many(et, report.root_entity) if et else False

            resolved.append(_ResolvedColumn(
                column=col,
                cypher_expr=f"{target_var}.{field}",
                csv_header=csv_header,
                match_var=target_var,
                is_expansion=is_expansion and report.row_mode == RowMode.EXPANDED,
            ))

        return resolved

    def _compile_aggregate(
        self,
        report: ReportDefinition,
        state: _CompilerState,
    ) -> CompiledQuery:
        """Compile an aggregate report."""
        core = self._build_core(state)

        if report.group_by:
            group_fields = []
            return_parts = []
            for gb in report.group_by:
                parts = gb.split(".")
                if len(parts) == 1:
                    group_fields.append(f"n.{parts[0]}")
                    return_parts.append(f"n.{parts[0]} AS {parts[0]}")
                # TODO: support group_by on related fields
            group_fields_str = ", ".join(group_fields)
            agg = report.aggregate_function or "count"
            return_parts.append(f"{agg}(n) AS {agg}")

            query = (
                f"{core}\n"
                f"RETURN {', '.join(return_parts)}\n"
                f"ORDER BY {agg} DESC\n"
                f"SKIP $__skip LIMIT $__limit"
            )
        else:
            query = f"{core}\nRETURN count(n) AS total"

        state.params["__skip"] = report.pagination.offset
        state.params["__limit"] = min(report.pagination.limit, report.max_export_rows)

        return CompiledQuery(data_query=query, data_params=dict(state.params))

    def _build_core(self, state: _CompilerState) -> str:
        parts = list(state.match_clauses)
        if state.where_clauses:
            parts.append("WHERE " + " AND ".join(state.where_clauses))
        return "\n".join(parts)

    def _build_order(
        self,
        sort: list[SortField],
        columns: list[_ResolvedColumn],
    ) -> str:
        if not sort:
            return "ORDER BY n.id"
        parts = []
        # Map sort fields to resolved column expressions
        col_map = {rc.column.path: rc.cypher_expr for rc in columns}
        for sf in sort:
            expr = col_map.get(sf.field, f"n.{sf.field}")
            direction = "DESC" if sf.direction == SortDirection.DESC else ""
            parts.append(f"{expr} {direction}".strip())
        return "ORDER BY " + ", ".join(parts)

    def _find_edge(self, alias: str, root_entity: str):
        edges = self._validator._edge_by_alias.get(root_entity, {})
        return edges.get(alias)

    def _edge_direction(self, et, root_entity: str) -> str:
        if root_entity in et.source.node_types:
            return "outgoing"
        return "incoming"

    def _edge_target(self, et, root_entity: str) -> str | None:
        if root_entity in et.source.node_types:
            return et.target.node_types[0] if et.target.node_types else None
        return et.source.node_types[0] if et.source.node_types else None

    def _is_one_to_many(self, et, root_entity: str) -> bool:
        """Check if this relationship produces multiple rows per root entity."""
        from packages.schema_engine.models import Cardinality
        if root_entity in et.source.node_types:
            return et.cardinality in (Cardinality.ONE_TO_MANY, Cardinality.MANY_TO_MANY)
        else:
            return et.cardinality in (Cardinality.MANY_TO_ONE, Cardinality.MANY_TO_MANY)

    def get_available_columns(self, entity: str) -> list[dict[str, Any]]:
        """Return all available report columns for a given root entity.

        Used by the UI report builder to populate column picker.
        """
        nt = self._registry.get_node_type(entity)
        if not nt:
            return []

        columns: list[dict[str, Any]] = []

        # Root fields
        for name, attr in nt.attributes.items():
            if attr.query.reportable and not attr.health.sensitive:
                columns.append({
                    "path": name,
                    "source": "root",
                    "display_label": attr.display_name or name,
                    "data_type": attr.type.value,
                    "formatter_hint": attr.query.formatter_hint,
                    "export_default": attr.query.export_default,
                    "sortable": attr.query.sortable,
                })

        # Related node fields and edge fields
        edges = self._validator._edge_by_alias.get(entity, {})
        for alias, et in edges.items():
            if alias.startswith("inv_") or not et.query.traversable_in_reports:
                continue

            direction = self._edge_direction(et, entity)
            target_type_name = self._edge_target(et, entity)
            if not target_type_name:
                continue

            target_nt = self._registry.get_node_type(target_type_name)
            if not target_nt:
                continue

            is_multi = self._is_one_to_many(et, entity)

            # Target node fields
            for name, attr in target_nt.attributes.items():
                if attr.query.reportable and not attr.health.sensitive:
                    columns.append({
                        "path": f"{alias}.{target_type_name}.{name}",
                        "source": "related",
                        "display_label": f"{target_nt.metadata.display_name or target_type_name} > {attr.display_name or name}",
                        "data_type": attr.type.value,
                        "relationship": alias,
                        "target_type": target_type_name,
                        "causes_expansion": is_multi,
                        "sortable": attr.query.sortable,
                    })

            # Edge attributes
            for name, attr in et.attributes.items():
                columns.append({
                    "path": f"{alias}.edge.{name}",
                    "source": "edge",
                    "display_label": f"{alias} edge > {attr.display_name or name}",
                    "data_type": attr.type.value,
                    "relationship": alias,
                    "causes_expansion": is_multi,
                })

            # Count aggregate
            columns.append({
                "path": f"{alias}.count",
                "source": "aggregate",
                "display_label": f"{alias} count",
                "data_type": "integer",
                "relationship": alias,
            })

        return columns
