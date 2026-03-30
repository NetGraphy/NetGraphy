"""Query AST → Cypher compiler — translates validated queries into parameterized Cypher.

This compiler takes a validated QueryAST (with resolved paths from the validator)
and produces parameterized Cypher queries. It handles:

- Direct attribute filters (WHERE n.status = $p0)
- Relationship traversal filters (MATCH (n)-[:LOCATED_AT]->(loc:Location) WHERE loc.city ...)
- Relationship existence filters (WHERE EXISTS { (n)-[:HAS_INTERFACE]->() })
- Relationship count filters (WHERE size([(n)-[:HAS_INTERFACE]->() | 1]) > $p0)
- Edge attribute filters (MATCH (n)-[r:LOCATED_AT]->() WHERE r.is_primary = $p0)
- Compound AND/OR/NOT filter groups
- Pagination, sorting, field selection
- Total count queries (separate COUNT query)

All values are parameter-bound ($param syntax). Never interpolated.
Node type labels and edge types are validated against schema before use.
"""

from __future__ import annotations

from typing import Any

import structlog

from packages.query_engine.models import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    LogicalOperator,
    Pagination,
    QueryAST,
    ResolvedPath,
    ResolvedPathSegment,
    SortDirection,
    SortField,
)

logger = structlog.get_logger()


class CompiledQuery:
    """The output of the compiler — Cypher + params, ready for execution."""

    def __init__(
        self,
        data_query: str,
        data_params: dict[str, Any],
        count_query: str | None = None,
        count_params: dict[str, Any] | None = None,
    ):
        self.data_query = data_query
        self.data_params = data_params
        self.count_query = count_query
        self.count_params = count_params


class _CompilerState:
    """Mutable state accumulated during compilation."""

    def __init__(self) -> None:
        self.match_clauses: list[str] = []
        self.where_clauses: list[str] = []
        self.params: dict[str, Any] = {}
        self.param_counter: int = 0
        # Track relationship variables to avoid duplicates
        self.rel_vars: dict[str, str] = {}  # edge_type+direction → variable name
        self.rel_counter: int = 0

    def next_param(self) -> str:
        name = f"p{self.param_counter}"
        self.param_counter += 1
        return name

    def next_rel_var(self, edge_type: str, direction: str) -> tuple[str, str, bool]:
        """Get or create a variable name for a relationship match.

        Returns (rel_var, target_var, is_new).
        """
        key = f"{edge_type}_{direction}"
        if key in self.rel_vars:
            return self.rel_vars[key], f"t_{key}", False

        self.rel_counter += 1
        rel_var = f"r{self.rel_counter}"
        target_var = f"t{self.rel_counter}"
        self.rel_vars[key] = rel_var
        return rel_var, target_var, True


class QueryCompiler:
    """Compiles a validated QueryAST into parameterized Cypher."""

    def compile(
        self,
        ast: QueryAST,
        resolved_paths: list[ResolvedPath],
        default_fields: list[str] | None = None,
    ) -> CompiledQuery:
        """Compile a QueryAST into executable Cypher.

        Args:
            ast: The validated query AST.
            resolved_paths: Paths resolved by the validator.
            default_fields: Default fields if ast.fields is None.
        """
        state = _CompilerState()
        entity = ast.entity

        # Primary MATCH
        state.match_clauses.append(f"MATCH (n:{entity})")

        # Build a lookup from raw_path to resolved path
        path_map: dict[str, ResolvedPath] = {rp.raw_path: rp for rp in resolved_paths}

        # Compile filters
        if ast.filters:
            where_expr = self._compile_filter_group(ast.filters, state, path_map)
            if where_expr:
                state.where_clauses.append(where_expr)

        # Build the core query (MATCH + WHERE)
        core = self._build_core(state)

        # --- Data query ---
        fields = ast.fields or default_fields or []
        return_clause = self._build_return(fields)
        order_clause = self._build_order(ast.sort)
        pagination_clause = self._build_pagination(ast.pagination, state)

        data_query = f"{core}\n{return_clause}"
        if order_clause:
            data_query += f"\n{order_clause}"
        data_query += f"\n{pagination_clause}"

        # --- Count query ---
        count_query = None
        count_params = None
        if ast.include_total:
            count_query = f"{core}\nRETURN count(DISTINCT n) AS total"
            count_params = dict(state.params)

        return CompiledQuery(
            data_query=data_query,
            data_params=dict(state.params),
            count_query=count_query,
            count_params=count_params,
        )

    def compile_aggregate(
        self,
        entity: str,
        resolved_paths: list[ResolvedPath],
        filters: FilterGroup | None,
        aggregate_type: str = "count",
        group_by: str | None = None,
    ) -> CompiledQuery:
        """Compile an aggregate query (count, group by).

        Args:
            entity: Node type.
            resolved_paths: Resolved filter paths.
            filters: Optional filter group.
            aggregate_type: "count" (more types can be added).
            group_by: Optional attribute to group by.
        """
        state = _CompilerState()
        state.match_clauses.append(f"MATCH (n:{entity})")

        path_map: dict[str, ResolvedPath] = {rp.raw_path: rp for rp in resolved_paths}

        if filters:
            where_expr = self._compile_filter_group(filters, state, path_map)
            if where_expr:
                state.where_clauses.append(where_expr)

        core = self._build_core(state)

        if group_by:
            query = (
                f"{core}\n"
                f"RETURN n.{group_by} AS {group_by}, count(DISTINCT n) AS count\n"
                f"ORDER BY count DESC"
            )
        else:
            query = f"{core}\nRETURN count(DISTINCT n) AS total"

        return CompiledQuery(data_query=query, data_params=dict(state.params))

    # ---------------------------------------------------------------------- #
    #  Filter compilation                                                      #
    # ---------------------------------------------------------------------- #

    def _compile_filter_group(
        self,
        group: FilterGroup,
        state: _CompilerState,
        path_map: dict[str, ResolvedPath],
    ) -> str:
        """Compile a FilterGroup into a Cypher WHERE expression."""
        parts: list[str] = []

        for condition in group.conditions:
            if isinstance(condition, FilterGroup):
                nested = self._compile_filter_group(condition, state, path_map)
                if nested:
                    parts.append(f"({nested})")
            else:
                expr = self._compile_condition(condition, state, path_map)
                if expr:
                    parts.append(expr)

        if not parts:
            return ""

        if group.op == LogicalOperator.NOT:
            return f"NOT ({' AND '.join(parts)})"

        joiner = f" {group.op.value} "
        return joiner.join(parts)

    def _compile_condition(
        self,
        cond: FilterCondition,
        state: _CompilerState,
        path_map: dict[str, ResolvedPath],
    ) -> str:
        """Compile a single FilterCondition into a Cypher expression."""
        rp = path_map.get(cond.path)

        # If no resolved path, treat as direct attribute on n
        if not rp:
            return self._compile_direct_filter(cond, state, "n")

        # Relationship existence filter
        if rp.is_relationship_existence:
            return self._compile_existence_filter(cond, rp, state)

        # Relationship count filter
        if rp.is_relationship_count:
            return self._compile_count_filter(cond, rp, state)

        # Analyze segments
        segments = rp.segments

        # Direct attribute (single segment with just attribute)
        if len(segments) == 1 and segments[0].attribute and not segments[0].edge_type:
            return self._compile_direct_filter(cond, state, "n")

        # Edge attribute (single segment with edge_type and attribute)
        if len(segments) == 1 and segments[0].edge_type and segments[0].attribute:
            return self._compile_edge_attr_filter(cond, segments[0], state)

        # Relationship traversal (edge segment + attribute segment)
        if len(segments) == 2 and segments[0].edge_type and segments[1].attribute:
            return self._compile_traversal_filter(cond, segments, state)

        logger.warning("unhandled_filter_path", path=cond.path, segments=len(segments))
        return ""

    def _compile_direct_filter(
        self,
        cond: FilterCondition,
        state: _CompilerState,
        node_var: str,
    ) -> str:
        """Compile a direct attribute filter on a node variable."""
        field = cond.path.split(".")[-1]  # Last segment is the attribute name
        return self._operator_to_cypher(f"{node_var}.{field}", cond.operator, cond.value, state)

    def _compile_existence_filter(
        self,
        cond: FilterCondition,
        rp: ResolvedPath,
        state: _CompilerState,
    ) -> str:
        """Compile a relationship existence filter."""
        seg = rp.segments[0]
        edge_type = seg.edge_type

        if seg.direction == "outgoing":
            pattern = f"(n)-[:{edge_type}]->()"
        else:
            pattern = f"(n)<-[:{edge_type}]-()"

        if cond.operator == FilterOperator.EXISTS:
            return f"EXISTS {{ {pattern} }}"
        else:
            return f"NOT EXISTS {{ {pattern} }}"

    def _compile_count_filter(
        self,
        cond: FilterCondition,
        rp: ResolvedPath,
        state: _CompilerState,
    ) -> str:
        """Compile a relationship count filter."""
        seg = rp.segments[0]
        edge_type = seg.edge_type

        if seg.direction == "outgoing":
            pattern = f"(n)-[:{edge_type}]->()"
        else:
            pattern = f"(n)<-[:{edge_type}]-()"

        count_expr = f"size([{pattern} | 1])"
        param = state.next_param()
        state.params[param] = cond.value

        op_map = {
            FilterOperator.COUNT_EQ: "=",
            FilterOperator.COUNT_GT: ">",
            FilterOperator.COUNT_GTE: ">=",
            FilterOperator.COUNT_LT: "<",
            FilterOperator.COUNT_LTE: "<=",
        }
        cypher_op = op_map.get(cond.operator, "=")
        return f"{count_expr} {cypher_op} ${param}"

    def _compile_edge_attr_filter(
        self,
        cond: FilterCondition,
        seg: ResolvedPathSegment,
        state: _CompilerState,
    ) -> str:
        """Compile a filter on an edge attribute."""
        edge_type = seg.edge_type
        attr_name = seg.attribute
        direction = seg.direction

        rel_var, target_var, is_new = state.next_rel_var(edge_type, direction)

        if is_new:
            if direction == "outgoing":
                state.match_clauses.append(
                    f"MATCH (n)-[{rel_var}:{edge_type}]->({target_var})"
                )
            else:
                state.match_clauses.append(
                    f"MATCH (n)<-[{rel_var}:{edge_type}]-({target_var})"
                )

        return self._operator_to_cypher(
            f"{rel_var}.{attr_name}", cond.operator, cond.value, state,
        )

    def _compile_traversal_filter(
        self,
        cond: FilterCondition,
        segments: list[ResolvedPathSegment],
        state: _CompilerState,
    ) -> str:
        """Compile a relationship traversal filter (edge → target attribute)."""
        edge_seg = segments[0]
        attr_seg = segments[1]

        edge_type = edge_seg.edge_type
        target_type = edge_seg.target_type
        attr_name = attr_seg.attribute
        direction = edge_seg.direction

        rel_var, target_var, is_new = state.next_rel_var(edge_type, direction)

        if is_new:
            label = f":{target_type}" if target_type else ""
            if direction == "outgoing":
                state.match_clauses.append(
                    f"MATCH (n)-[{rel_var}:{edge_type}]->({target_var}{label})"
                )
            else:
                state.match_clauses.append(
                    f"MATCH (n)<-[{rel_var}:{edge_type}]-({target_var}{label})"
                )

        return self._operator_to_cypher(
            f"{target_var}.{attr_name}", cond.operator, cond.value, state,
        )

    # ---------------------------------------------------------------------- #
    #  Operator → Cypher expression                                            #
    # ---------------------------------------------------------------------- #

    def _operator_to_cypher(
        self,
        field_expr: str,
        operator: FilterOperator,
        value: Any,
        state: _CompilerState,
    ) -> str:
        """Convert a filter operator to a Cypher expression with parameter binding."""
        param = state.next_param()

        if operator == FilterOperator.EQ:
            state.params[param] = value
            return f"{field_expr} = ${param}"

        if operator == FilterOperator.NEQ:
            state.params[param] = value
            return f"{field_expr} <> ${param}"

        if operator == FilterOperator.CONTAINS:
            state.params[param] = value
            return f"{field_expr} CONTAINS ${param}"

        if operator == FilterOperator.NOT_CONTAINS:
            state.params[param] = value
            return f"NOT {field_expr} CONTAINS ${param}"

        if operator == FilterOperator.STARTS_WITH:
            state.params[param] = value
            return f"{field_expr} STARTS WITH ${param}"

        if operator == FilterOperator.ENDS_WITH:
            state.params[param] = value
            return f"{field_expr} ENDS WITH ${param}"

        if operator == FilterOperator.REGEX:
            state.params[param] = value
            return f"{field_expr} =~ ${param}"

        if operator == FilterOperator.IN:
            state.params[param] = value  # value should be a list
            return f"{field_expr} IN ${param}"

        if operator == FilterOperator.NOT_IN:
            state.params[param] = value
            return f"NOT {field_expr} IN ${param}"

        if operator == FilterOperator.GT:
            state.params[param] = value
            return f"{field_expr} > ${param}"

        if operator == FilterOperator.GTE:
            state.params[param] = value
            return f"{field_expr} >= ${param}"

        if operator == FilterOperator.LT:
            state.params[param] = value
            return f"{field_expr} < ${param}"

        if operator == FilterOperator.LTE:
            state.params[param] = value
            return f"{field_expr} <= ${param}"

        if operator == FilterOperator.BETWEEN:
            # value should be [low, high]
            lo_param = param
            hi_param = state.next_param()
            state.params[lo_param] = value[0]
            state.params[hi_param] = value[1]
            return f"${lo_param} <= {field_expr} <= ${hi_param}"

        if operator == FilterOperator.IS_NULL:
            return f"{field_expr} IS NULL"

        if operator == FilterOperator.IS_NOT_NULL:
            return f"{field_expr} IS NOT NULL"

        # Fallback — should not reach here if validator worked correctly
        state.params[param] = value
        return f"{field_expr} = ${param}"

    # ---------------------------------------------------------------------- #
    #  Query assembly                                                          #
    # ---------------------------------------------------------------------- #

    def _build_core(self, state: _CompilerState) -> str:
        """Assemble MATCH + WHERE clauses."""
        parts = list(state.match_clauses)
        if state.where_clauses:
            parts.append("WHERE " + " AND ".join(state.where_clauses))
        return "\n".join(parts)

    def _build_return(self, fields: list[str]) -> str:
        """Build RETURN clause."""
        if not fields:
            return "RETURN DISTINCT n"

        # Always return the full node to keep things consistent
        # but project specific fields if requested
        field_exprs = []
        for f in fields:
            if f == "id":
                field_exprs.append("n.id AS id")
            else:
                field_exprs.append(f"n.{f} AS {f}")
        return f"RETURN DISTINCT {', '.join(field_exprs)}"

    def _build_order(self, sort: list[SortField]) -> str:
        """Build ORDER BY clause."""
        if not sort:
            return "ORDER BY n.id"

        parts = []
        for sf in sort:
            direction = "DESC" if sf.direction == SortDirection.DESC else ""
            parts.append(f"n.{sf.field} {direction}".strip())
        return "ORDER BY " + ", ".join(parts)

    def _build_pagination(self, pagination: Pagination, state: _CompilerState) -> str:
        """Build SKIP + LIMIT clause."""
        state.params["__skip"] = pagination.offset
        state.params["__limit"] = pagination.limit
        return "SKIP $__skip LIMIT $__limit"
