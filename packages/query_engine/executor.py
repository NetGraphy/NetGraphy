"""Query executor — handles Cypher and structured query execution."""

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
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


class QueryExecutor:
    """Executes Cypher and structured queries against the graph."""

    def __init__(self, driver: Neo4jDriver, registry: SchemaRegistry):
        self._driver = driver
        self._registry = registry

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

        # Determine if this is a read or write query
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

    async def execute_structured(
        self,
        structured_query: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert a structured query definition to Cypher and execute.

        Structured query format:
        {
            "node_type": "Device",
            "filters": [
                {"field": "status", "operator": "eq", "value": "active"},
                {"field": "role", "operator": "in", "value": ["router", "switch"]}
            ],
            "relationships": [
                {
                    "edge_type": "LOCATED_IN",
                    "direction": "outgoing",
                    "target_type": "Location",
                    "target_filters": [...]
                }
            ],
            "return_fields": ["hostname", "management_ip", "status"],
            "order_by": "hostname",
            "limit": 50,
            "include_graph": true
        }
        """
        node_type = structured_query.get("node_type")
        if not node_type:
            raise ValueError("node_type is required")

        # Validate node_type exists
        if not self._registry.get_node_type(node_type):
            raise ValueError(f"Unknown node type: {node_type}")

        builder = CypherBuilder()
        params: dict[str, Any] = {}

        # Primary match
        builder.match(MatchPattern("n", [node_type]))

        # Filters
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

        # Relationship traversals
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

            # Target filters
            for k, tf in enumerate(rel.get("target_filters", [])):
                param_key = f"tp_{j}_{k}"
                conditions.append(Condition(f"{target_var}.{tf['field']} = ${param_key}"))
                params[param_key] = tf["value"]

        # Return
        return_fields = structured_query.get("return_fields", [])
        if return_fields:
            builder.return_clause([ReturnField(f"n.{f} as {f}") for f in return_fields])
        else:
            builder.return_clause([ReturnField("n")])

        # Order
        if structured_query.get("order_by"):
            order = structured_query["order_by"]
            desc = order.startswith("-")
            field_name = order.lstrip("-")
            builder.order_by([OrderField(f"n.{field_name}", descending=desc)])

        # Pagination
        if structured_query.get("skip"):
            builder.skip(structured_query["skip"])
        if structured_query.get("limit"):
            builder.limit(structured_query["limit"])

        # Set all params
        for k, v in params.items():
            builder.set_param(k, v)

        query, all_params = builder.build()
        logger.debug("Structured query compiled", cypher=query)

        result = await self._driver.execute_read(query, all_params)
        return result.to_dict()
