"""MCP Tool Executor — routes MCP tool calls through the query engine.

This is the runtime execution layer for all schema-generated MCP tools.
When an agent calls a tool like `query_devices` or `find_devices_by_location`,
this executor:

1. Parses the tool input into a QueryAST
2. Validates against the schema
3. Compiles to Cypher
4. Executes against Neo4j
5. Returns structured results

It also handles CRUD tool calls (create, get, update, delete) by delegating
to the node/edge repositories.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver
from packages.graph_db.repositories.node_repository import NodeRepository
from packages.graph_db.repositories.edge_repository import EdgeRepository
from packages.query_engine.compiler import CompiledQuery, QueryCompiler
from packages.query_engine.models import (
    FilterCondition,
    FilterGroup,
    FilterOperator,
    LogicalOperator,
    Pagination,
    QueryAST,
    QueryResult,
    SortField,
    SortDirection,
)
from packages.query_engine.validator import QueryValidationError, QueryValidator
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class ToolExecutionError(Exception):
    """Raised when a tool call fails."""

    def __init__(self, message: str, tool_name: str = ""):
        self.tool_name = tool_name
        super().__init__(message)


class MCPToolExecutor:
    """Executes MCP tool calls against the graph database."""

    def __init__(
        self,
        driver: Neo4jDriver,
        registry: SchemaRegistry,
        node_repo: NodeRepository | None = None,
        edge_repo: EdgeRepository | None = None,
    ):
        self._driver = driver
        self._registry = registry
        self._node_repo = node_repo or NodeRepository(driver, registry)
        self._edge_repo = edge_repo or EdgeRepository(driver, registry)
        self._validator = QueryValidator(registry)
        self._compiler = QueryCompiler()

    async def execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an MCP tool call and return structured results.

        Routes to the appropriate handler based on tool name pattern.
        """
        try:
            # --- Query tools: query_<entities> ---
            if tool_name.startswith("query_"):
                return await self._execute_query_tool(tool_name, tool_input)

            # --- Find tools: find_<entities>_by_<relationship> ---
            if tool_name.startswith("find_"):
                return await self._execute_find_tool(tool_name, tool_input)

            # --- Count tools: count_<entities> ---
            if tool_name.startswith("count_"):
                return await self._execute_count_tool(tool_name, tool_input)

            # --- Lookup tools: get_<entity>_by_<field> ---
            if tool_name.startswith("get_") and "_by_" in tool_name:
                return await self._execute_lookup_tool(tool_name, tool_input)

            # --- CRUD tools ---
            if tool_name.startswith("create_"):
                return await self._execute_create(tool_name, tool_input)
            if tool_name.startswith("get_"):
                return await self._execute_get(tool_name, tool_input)
            if tool_name.startswith("list_"):
                return await self._execute_list(tool_name, tool_input)
            if tool_name.startswith("update_"):
                return await self._execute_update(tool_name, tool_input)
            if tool_name.startswith("delete_"):
                return await self._execute_delete(tool_name, tool_input)

            # --- Relationship tools ---
            if tool_name.startswith("connect_"):
                return await self._execute_connect(tool_name, tool_input)
            if tool_name.startswith("disconnect_"):
                return await self._execute_disconnect(tool_name, tool_input)

            raise ToolExecutionError(f"Unknown tool: {tool_name}", tool_name)

        except QueryValidationError as e:
            logger.warning("tool_validation_error", tool=tool_name, errors=e.errors)
            return {
                "error": True,
                "message": f"Query validation failed: {'; '.join(e.errors)}",
                "validation_errors": e.errors,
                "hint": (
                    "Try a different approach: "
                    "1) Search for the related object first using a direct query, "
                    "2) Then use the object's ID to find connected nodes. "
                    "For example, first query_locations with a name/city filter, "
                    "then use the location ID to query_devices with a direct filter."
                ),
            }
        except ToolExecutionError:
            raise
        except Exception as e:
            logger.error("tool_execution_failed", tool=tool_name, error=str(e))
            return {
                "error": True,
                "message": f"Tool execution failed: {e}",
                "hint": (
                    "Try a simpler approach: use direct attribute filters or "
                    "search for objects individually rather than relationship traversal."
                ),
            }

    # ---------------------------------------------------------------------- #
    #  Query tool execution                                                    #
    # ---------------------------------------------------------------------- #

    async def _execute_query_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a query_<entities> tool call.

        If validation fails for relationship filters, falls back to
        direct attribute-only query to still return useful results.
        """
        entity = self._resolve_entity_from_tool(tool_name, prefix="query_")

        # Build QueryAST from tool input
        ast = self._build_query_ast(entity, tool_input)

        # Validate — with fallback for relationship filter failures
        try:
            resolved_paths = self._validator.validate(ast)
        except QueryValidationError as e:
            logger.warning("query_validation_fallback", entity=entity, errors=e.errors)
            # Try falling back to direct filters only (strip relationship paths)
            direct_conditions = []
            for f in tool_input.get("filters", []):
                path = f.get("path", "")
                if "." not in path:  # Direct attribute only
                    direct_conditions.append(f)

            if direct_conditions:
                fallback_input = {**tool_input, "filters": direct_conditions}
                fallback_ast = self._build_query_ast(entity, fallback_input)
                try:
                    resolved_paths = self._validator.validate(fallback_ast)
                    ast = fallback_ast
                except QueryValidationError:
                    raise e  # Re-raise original error
            else:
                # No direct filters available — do NOT fall back to unfiltered.
                # Return the error with guidance for the agent.
                raise e
        default_fields = self._validator.get_default_fields(entity)

        # Compile
        compiled = self._compiler.compile(ast, resolved_paths, default_fields)

        # Execute
        return await self._execute_compiled(compiled, entity)

    async def _execute_find_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a find_<entities>_by_<relationship> tool call.

        Convenience tools like find_devices_by_location accept simpler inputs:
        {
            "location_filters": [{"path": "city", "operator": "contains", "value": "Dallas"}],
            "device_filters": [{"path": "status", "operator": "eq", "value": "active"}],
            "limit": 50
        }
        """
        # Parse tool name: find_<entities>_by_<relationship>
        match = re.match(r"find_(\w+)_by_(\w+)", tool_name)
        if not match:
            raise ToolExecutionError(f"Cannot parse find tool name: {tool_name}", tool_name)

        entity_plural = match.group(1)
        rel_alias = match.group(2)

        entity = self._resolve_entity_from_plural(entity_plural)

        # Build filters combining relationship and direct filters
        conditions: list[FilterCondition | FilterGroup] = []

        # Relationship-side filters (e.g., location_filters)
        rel_filters = tool_input.get(f"{rel_alias}_filters", [])
        for f in rel_filters:
            # Prefix each filter path with the relationship alias
            path = f.get("path", "")
            if "." not in path:
                # Auto-resolve: if it's a direct attribute, prefix with rel_alias
                # The validator will resolve this against the target type
                edge_alias = rel_alias
                # Find the target type for this edge
                edges = self._validator._edge_by_alias.get(entity, {})
                et = edges.get(edge_alias)
                if et:
                    target_types = et.target.node_types
                    if entity in et.target.node_types:
                        target_types = et.source.node_types
                    if target_types:
                        path = f"{edge_alias}.{target_types[0]}.{path}"
                    else:
                        path = f"{edge_alias}.{path}"
                else:
                    path = f"{edge_alias}.{path}"

            conditions.append(FilterCondition(
                path=path,
                operator=FilterOperator(f.get("operator", "eq")),
                value=f.get("value"),
            ))

        # Entity-side filters (e.g., device_filters)
        entity_slug = _slugify(entity)
        direct_filters = tool_input.get(f"{entity_slug}_filters", tool_input.get("filters", []))
        for f in direct_filters:
            conditions.append(FilterCondition(
                path=f.get("path", ""),
                operator=FilterOperator(f.get("operator", "eq")),
                value=f.get("value"),
            ))

        ast = QueryAST(
            entity=entity,
            filters=FilterGroup(op=LogicalOperator.AND, conditions=conditions) if conditions else None,
            pagination=Pagination(
                limit=min(tool_input.get("limit", 50), 200),
                offset=tool_input.get("offset", 0),
            ),
            sort=self._parse_sort(tool_input),
            fields=tool_input.get("fields"),
            include_total=tool_input.get("include_total", True),
        )

        resolved_paths = self._validator.validate(ast)
        default_fields = self._validator.get_default_fields(entity)
        compiled = self._compiler.compile(ast, resolved_paths, default_fields)
        return await self._execute_compiled(compiled, entity)

    async def _execute_count_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a count_<entities> tool call."""
        entity = self._resolve_entity_from_tool(tool_name, prefix="count_")

        conditions: list[FilterCondition | FilterGroup] = []
        for f in tool_input.get("filters", []):
            conditions.append(FilterCondition(
                path=f.get("path", ""),
                operator=FilterOperator(f.get("operator", "eq")),
                value=f.get("value"),
            ))

        filters = FilterGroup(op=LogicalOperator.AND, conditions=conditions) if conditions else None

        # Validate the filters
        ast = QueryAST(entity=entity, filters=filters)
        resolved_paths = self._validator.validate(ast)

        group_by = tool_input.get("group_by")
        compiled = self._compiler.compile_aggregate(
            entity, resolved_paths, filters,
            aggregate_type="count", group_by=group_by,
        )

        result = await self._driver.execute_read(
            compiled.data_query, compiled.data_params,
        )

        if group_by:
            return {
                "entity": entity,
                "group_by": group_by,
                "groups": [
                    {group_by: row.get(group_by), "count": row.get("count")}
                    for row in result.rows
                ],
            }
        else:
            total = result.rows[0]["total"] if result.rows else 0
            return {"entity": entity, "total": total}

    async def _execute_lookup_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a get_<entity>_by_<field> lookup tool."""
        # Parse: get_device_by_hostname → entity=Device, field=hostname
        match = re.match(r"get_(\w+)_by_(\w+)", tool_name)
        if not match:
            raise ToolExecutionError(f"Cannot parse lookup tool: {tool_name}", tool_name)

        entity_slug = match.group(1)
        field = match.group(2)
        value = tool_input.get("value") or tool_input.get(field)

        if value is None:
            raise ToolExecutionError(f"Missing required field: {field}", tool_name)

        entity = self._resolve_entity_from_slug(entity_slug)

        ast = QueryAST(
            entity=entity,
            filters=FilterGroup(conditions=[
                FilterCondition(path=field, operator=FilterOperator.EQ, value=value),
            ]),
            pagination=Pagination(limit=1, offset=0),
            include_total=False,
        )

        resolved_paths = self._validator.validate(ast)
        default_fields = self._validator.get_default_fields(entity)
        compiled = self._compiler.compile(ast, resolved_paths, default_fields)

        result = await self._driver.execute_read(
            compiled.data_query, compiled.data_params,
        )

        if result.rows:
            item = result.rows[0]
            # If result is a full node object under 'n', unwrap
            if "n" in item and isinstance(item["n"], dict):
                return {"found": True, "data": item["n"]}
            return {"found": True, "data": item}

        return {"found": False, "data": None, "message": f"No {entity} found with {field}={value}"}

    # ---------------------------------------------------------------------- #
    #  CRUD tool execution                                                     #
    # ---------------------------------------------------------------------- #

    async def _execute_create(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        entity = self._resolve_entity_from_tool(tool_name, prefix="create_")
        node = await self._node_repo.create_node(entity, tool_input)
        return {"success": True, "data": node}

    async def _execute_get(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        entity = self._resolve_entity_from_tool(tool_name, prefix="get_")
        node_id = tool_input.get("id")
        if not node_id:
            raise ToolExecutionError("Missing required field: id", tool_name)
        node = await self._node_repo.get_node(entity, node_id)
        if not node:
            return {"found": False, "data": None}
        return {"found": True, "data": node}

    async def _execute_list(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a list tool — delegates to query tool for consistency."""
        entity = self._resolve_entity_from_tool(tool_name, prefix="list_")
        return await self._execute_query_tool(f"query_{_slugify(entity)}s", tool_input)

    async def _execute_update(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        entity = self._resolve_entity_from_tool(tool_name, prefix="update_")
        node_id = tool_input.pop("id", None)
        if not node_id:
            raise ToolExecutionError("Missing required field: id", tool_name)
        node = await self._node_repo.update_node(entity, node_id, tool_input)
        if not node:
            return {"success": False, "message": f"{entity} not found"}
        return {"success": True, "data": node}

    async def _execute_delete(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        entity = self._resolve_entity_from_tool(tool_name, prefix="delete_")
        node_id = tool_input.get("id")
        if not node_id:
            raise ToolExecutionError("Missing required field: id", tool_name)
        deleted = await self._node_repo.delete_node(entity, node_id)
        return {"success": deleted}

    async def _execute_connect(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        source_id = tool_input.get("source_id")
        target_id = tool_input.get("target_id")
        if not source_id or not target_id:
            raise ToolExecutionError("Missing source_id or target_id", tool_name)

        # Parse: connect_device_to_location → find the edge type
        match = re.match(r"connect_(\w+)_to_(\w+)", tool_name)
        if not match:
            raise ToolExecutionError(f"Cannot parse connect tool: {tool_name}", tool_name)

        src_slug = match.group(1)
        tgt_slug = match.group(2)

        # Find edge type
        edge_type = self._find_edge_type(src_slug, tgt_slug)
        if not edge_type:
            raise ToolExecutionError(
                f"No edge type found for {src_slug} → {tgt_slug}", tool_name
            )

        props = {k: v for k, v in tool_input.items() if k not in ("source_id", "target_id")}
        edge = await self._edge_repo.create_edge(edge_type, source_id, target_id, props)
        return {"success": True, "data": edge}

    async def _execute_disconnect(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        source_id = tool_input.get("source_id")
        target_id = tool_input.get("target_id")
        if not source_id or not target_id:
            raise ToolExecutionError("Missing source_id or target_id", tool_name)

        match = re.match(r"disconnect_(\w+)_from_(\w+)", tool_name)
        if not match:
            raise ToolExecutionError(f"Cannot parse disconnect tool: {tool_name}", tool_name)

        src_slug = match.group(1)
        tgt_slug = match.group(2)
        edge_type = self._find_edge_type(src_slug, tgt_slug)
        if not edge_type:
            raise ToolExecutionError(
                f"No edge type found for {src_slug} → {tgt_slug}", tool_name
            )

        # Delete matching edge
        query = (
            f"MATCH (s {{id: $src}})-[r:{edge_type}]->(t {{id: $tgt}}) "
            f"DELETE r RETURN count(r) as deleted"
        )
        result = await self._driver.execute_write(
            query, {"src": source_id, "tgt": target_id}
        )
        deleted = result.rows[0].get("deleted", 0) if result.rows else 0
        return {"success": deleted > 0}

    # ---------------------------------------------------------------------- #
    #  Helpers                                                                 #
    # ---------------------------------------------------------------------- #

    def _build_query_ast(self, entity: str, tool_input: dict[str, Any]) -> QueryAST:
        """Build a QueryAST from tool input."""
        conditions: list[FilterCondition | FilterGroup] = []

        for f in tool_input.get("filters", []):
            conditions.append(FilterCondition(
                path=f.get("path", ""),
                operator=FilterOperator(f.get("operator", "eq")),
                value=f.get("value"),
            ))

        filters = FilterGroup(op=LogicalOperator.AND, conditions=conditions) if conditions else None

        nt = self._registry.get_node_type(entity)
        max_page = nt.query.max_page_size if nt else 200
        default_page = nt.query.default_page_size if nt else 50

        return QueryAST(
            entity=entity,
            filters=filters,
            sort=self._parse_sort(tool_input),
            pagination=Pagination(
                limit=min(tool_input.get("limit", default_page), max_page),
                offset=tool_input.get("offset", 0),
            ),
            fields=tool_input.get("fields"),
            include_total=tool_input.get("include_total", True),
            include_relationship_summary=tool_input.get("include_relationship_summary", False),
        )

    def _parse_sort(self, tool_input: dict[str, Any]) -> list[SortField]:
        sort_field = tool_input.get("sort")
        if not sort_field:
            return []
        direction = SortDirection(tool_input.get("sort_direction", "asc"))
        if sort_field.startswith("-"):
            sort_field = sort_field[1:]
            direction = SortDirection.DESC
        return [SortField(field=sort_field, direction=direction)]

    async def _execute_compiled(
        self,
        compiled: CompiledQuery,
        entity: str,
    ) -> dict[str, Any]:
        """Execute a compiled query and return structured results."""
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

        # Execute count query if present
        total_count = None
        if compiled.count_query and compiled.count_params is not None:
            count_result = await self._driver.execute_read(
                compiled.count_query, compiled.count_params,
            )
            if count_result.rows:
                total_count = count_result.rows[0].get("total", len(items))

        return {
            "entity": entity,
            "items": items,
            "total_count": total_count if total_count is not None else len(items),
            "count": len(items),
        }

    def _resolve_entity_from_tool(self, tool_name: str, prefix: str) -> str:
        """Resolve a node type name from a tool name like 'query_devices'."""
        slug = tool_name[len(prefix):]
        return self._resolve_entity_from_plural(slug)

    def _resolve_entity_from_plural(self, plural_slug: str) -> str:
        """Resolve a node type from a plural slug like 'devices'."""
        # Check direct matches first
        for nt in self._registry._node_types.values():
            nt_slug = _slugify(nt.metadata.name)
            plural = nt.api.plural_name or f"{nt_slug}s"
            plural_normalized = plural.replace("-", "_")
            if plural_normalized == plural_slug or nt_slug == plural_slug:
                return nt.metadata.name

        # Try removing trailing 's' and matching
        singular = plural_slug.rstrip("s")
        return self._resolve_entity_from_slug(singular)

    def _resolve_entity_from_slug(self, slug: str) -> str:
        """Resolve a node type from a slug like 'device'."""
        for nt in self._registry._node_types.values():
            if _slugify(nt.metadata.name) == slug:
                return nt.metadata.name

        # Fuzzy: try case-insensitive
        slug_lower = slug.lower().replace("_", "")
        for nt in self._registry._node_types.values():
            if nt.metadata.name.lower().replace("_", "") == slug_lower:
                return nt.metadata.name

        raise ToolExecutionError(f"Cannot resolve entity type from: {slug}")

    def _find_edge_type(self, src_slug: str, tgt_slug: str) -> str | None:
        """Find an edge type name from source/target slugs."""
        for et in self._registry._edge_types.values():
            for src in et.source.node_types:
                for tgt in et.target.node_types:
                    if _slugify(src) == src_slug and _slugify(tgt) == tgt_slug:
                        return et.metadata.name
        return None
