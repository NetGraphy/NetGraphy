"""Query executor — handles Cypher, structured, and AST-based query execution.

Supports three query modes:
1. Raw Cypher — direct execution with read/write routing
2. Legacy structured queries — JSON DSL (backwards compatible)
3. QueryAST pipeline — validate → compile → execute (production path)
"""

from __future__ import annotations

from typing import Any

import structlog

from packages.graph_db.builders.cypher_builder import (
    CypherBuilder,
    Condition,
    Direction,
    MatchPattern,
    OrderField,
    RelationshipPattern,
    ReturnField,
)
from packages.graph_db.driver import Neo4jDriver
from packages.query_engine.compiler import QueryCompiler
from packages.query_engine.models import QueryAST, QueryResult
from packages.query_engine.validator import QueryValidator, QueryValidationError
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


class QueryExecutor:
    """Executes Cypher and structured queries against the graph."""

    def __init__(self, driver: Neo4jDriver, registry: SchemaRegistry):
        self._driver = driver
        self._registry = registry
        self._validator = QueryValidator(registry)
        self._compiler = QueryCompiler()

    # ---------------------------------------------------------------------- #
    #  AST-based query execution (production path)                             #
    # ---------------------------------------------------------------------- #

    async def execute_ast(self, ast: QueryAST) -> QueryResult:
        """Execute a query through the full AST pipeline.

        1. Validate against schema (paths, operators, limits)
        2. Compile to parameterized Cypher
        3. Execute against Neo4j
        4. Return structured QueryResult
        """
        # Validate
        resolved_paths = self._validator.validate(ast)
        default_fields = self._validator.get_default_fields(ast.entity)

        # Compile
        compiled = self._compiler.compile(ast, resolved_paths, default_fields)

        logger.debug(
            "ast_query_compiled",
            entity=ast.entity,
            cypher=compiled.data_query,
            param_count=len(compiled.data_params),
        )

        # Execute data query
        data_result = await self._driver.execute_read(
            compiled.data_query, compiled.data_params,
        )

        # Extract items
        items = []
        for row in data_result.rows:
            if "n" in row and isinstance(row["n"], dict):
                items.append(row["n"])
            else:
                items.append(row)

        # Execute count query
        total_count = None
        if compiled.count_query and compiled.count_params is not None:
            count_result = await self._driver.execute_read(
                compiled.count_query, compiled.count_params,
            )
            if count_result.rows:
                total_count = count_result.rows[0].get("total", len(items))

        return QueryResult(
            items=items,
            total_count=total_count,
            page_info=ast.pagination,
            entity=ast.entity,
            fields_returned=ast.fields or default_fields,
            query_metadata={
                "cypher": compiled.data_query,
                "param_count": len(compiled.data_params),
            },
        )

    # ---------------------------------------------------------------------- #
    #  Raw Cypher execution                                                    #
    # ---------------------------------------------------------------------- #

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        explain: bool = False,
    ) -> dict[str, Any]:
        """Execute a raw Cypher query.

        Returns dual-format result (table + graph elements).
        """
        if explain:
            plan = await self._driver.execute_query_plan(query, parameters)
            return {"plan": plan}

        query_upper = query.strip().upper()
        is_write = any(
            keyword in query_upper
            for keyword in ["CREATE", "MERGE", "SET", "DELETE", "REMOVE"]
        )

        if is_write:
            result = await self._driver.execute_write(query, parameters)
        else:
            result = await self._driver.execute_read(query, parameters)

        return result.to_dict()

    # ---------------------------------------------------------------------- #
    #  Legacy structured query execution (backwards compatible)                #
    # ---------------------------------------------------------------------- #

    async def execute_structured(
        self,
        structured_query: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a structured query definition to Cypher and execute.

        Legacy format — kept for backwards compatibility with existing
        query workbench and API consumers.
        """
        node_type = structured_query.get("node_type")
        if not node_type:
            raise ValueError("node_type is required")

        if not self._registry.get_node_type(node_type):
            raise ValueError(f"Unknown node type: {node_type}")

        builder = CypherBuilder()
        params: dict[str, Any] = {}

        builder.match(MatchPattern("n", [node_type]))

        conditions = []
        for i, f in enumerate(structured_query.get("filters", [])):
            param_key = f"p_{i}"
            field = f["field"]
            operator = f.get("operator", "eq")
            value = f["value"]

            if operator == "eq":
                conditions.append(Condition(f"n.{field} = ${param_key}"))
            elif operator == "neq":
                conditions.append(Condition(f"n.{field} <> ${param_key}"))
            elif operator == "contains":
                conditions.append(Condition(f"n.{field} CONTAINS ${param_key}"))
            elif operator == "starts_with":
                conditions.append(Condition(f"n.{field} STARTS WITH ${param_key}"))
            elif operator == "in":
                conditions.append(Condition(f"n.{field} IN ${param_key}"))
            elif operator == "gt":
                conditions.append(Condition(f"n.{field} > ${param_key}"))
            elif operator == "lt":
                conditions.append(Condition(f"n.{field} < ${param_key}"))
            elif operator == "gte":
                conditions.append(Condition(f"n.{field} >= ${param_key}"))
            elif operator == "lte":
                conditions.append(Condition(f"n.{field} <= ${param_key}"))
            else:
                raise ValueError(f"Unknown filter operator: {operator}")

            params[param_key] = value

        if conditions:
            builder.where(conditions)

        for j, rel in enumerate(structured_query.get("relationships", [])):
            rel_var = f"r_{j}"
            target_var = f"m_{j}"
            edge_type = rel.get("edge_type")
            direction = Direction(rel.get("direction", "outgoing"))
            target_type = rel.get("target_type")

            builder.match_path(
                MatchPattern("n"),
                RelationshipPattern(rel_var, edge_type, direction),
                MatchPattern(target_var, [target_type] if target_type else None),
            )

            for k, tf in enumerate(rel.get("target_filters", [])):
                param_key = f"tp_{j}_{k}"
                conditions.append(Condition(f"{target_var}.{tf['field']} = ${param_key}"))
                params[param_key] = tf["value"]

        return_fields = structured_query.get("return_fields", [])
        if return_fields:
            builder.return_clause([ReturnField(f"n.{f} as {f}") for f in return_fields])
        else:
            builder.return_clause([ReturnField("n")])

        if structured_query.get("order_by"):
            order = structured_query["order_by"]
            desc = order.startswith("-")
            field_name = order.lstrip("-")
            builder.order_by([OrderField(f"n.{field_name}", descending=desc)])

        if structured_query.get("skip"):
            builder.skip(structured_query["skip"])
        if structured_query.get("limit"):
            builder.limit(structured_query["limit"])

        for k, v in params.items():
            builder.set_param(k, v)

        query, all_params = builder.build()
        logger.debug("Structured query compiled", cypher=query)

        result = await self._driver.execute_read(query, all_params)
        return result.to_dict()
