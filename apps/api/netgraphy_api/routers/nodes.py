"""Dynamic node CRUD endpoints.

Routes are parameterized by {node_type} and validated against the schema registry
at runtime. This allows any schema-defined node type to be managed without
writing type-specific code.

All operations go through NodeService which enforces:
  validate → authorize → execute → audit → emit

The query endpoint (/query/{node_type}) provides the production-grade AST
pipeline with structured filters, relationship traversal, and pagination.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from netgraphy_api.dependencies import (
    get_node_service,
    get_auth_context,
    get_graph_driver,
    get_schema_registry,
)
from netgraphy_api.services.node_service import NodeService
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


@router.get("/{node_type}")
async def list_nodes(
    request: Request,
    node_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List nodes of a given type with filtering and pagination.

    Filter params are extracted from query string based on schema filterable_fields.
    Use `field=value` or `field__operator=value` syntax.
    """
    # Extract filter params from query string (exclude known pagination params)
    reserved = {"page", "page_size", "sort", "fields", "include"}
    filters = {
        k: v for k, v in request.query_params.items()
        if k not in reserved
    }

    result = await svc.list(
        node_type=node_type,
        filters=filters,
        page=page,
        page_size=page_size,
        sort=sort,
        actor=actor,
    )
    return {
        "data": result["items"],
        "meta": {
            "total_count": result["total_count"],
            "page": page,
            "page_size": page_size,
        },
    }


@router.post("/query/{node_type}")
async def query_nodes(
    node_type: str,
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute a structured query against a node type using the AST pipeline.

    Supports:
    - Structured filters with relationship traversal
    - Pagination with safe defaults
    - Sorting and field selection
    - Total count

    Body:
    {
        "filters": [
            {"path": "status", "operator": "eq", "value": "active"},
            {"path": "located_at.Location.city", "operator": "contains", "value": "Dallas"}
        ],
        "sort": "hostname",
        "sort_direction": "asc",
        "limit": 50,
        "offset": 0,
        "fields": ["id", "hostname", "status"],
        "include_total": true
    }
    """
    from packages.query_engine.models import (
        FilterCondition,
        FilterGroup,
        FilterOperator,
        LogicalOperator,
        Pagination,
        QueryAST,
        SortDirection,
        SortField,
    )
    from packages.query_engine.validator import QueryValidationError
    from packages.query_engine.executor import QueryExecutor

    # Build QueryAST from request body
    conditions = []
    for f in body.get("filters", []):
        conditions.append(FilterCondition(
            path=f.get("path", ""),
            operator=FilterOperator(f.get("operator", "eq")),
            value=f.get("value"),
        ))

    filters = FilterGroup(op=LogicalOperator.AND, conditions=conditions) if conditions else None

    sort_fields = []
    if body.get("sort"):
        sort_field = body["sort"]
        direction = SortDirection(body.get("sort_direction", "asc"))
        if sort_field.startswith("-"):
            sort_field = sort_field[1:]
            direction = SortDirection.DESC
        sort_fields.append(SortField(field=sort_field, direction=direction))

    nt = registry.get_node_type(node_type)
    max_page = nt.query.max_page_size if nt else 200

    ast = QueryAST(
        entity=node_type,
        filters=filters,
        sort=sort_fields,
        pagination=Pagination(
            limit=min(body.get("limit", 50), max_page),
            offset=body.get("offset", 0),
        ),
        fields=body.get("fields"),
        include_total=body.get("include_total", True),
    )

    executor = QueryExecutor(driver, registry)

    try:
        result = executor._validator.validate(ast)
    except QueryValidationError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail={"errors": e.errors})

    query_result = await executor.execute_ast(ast)

    return {
        "data": query_result.items,
        "meta": {
            "total_count": query_result.total_count,
            "limit": ast.pagination.limit,
            "offset": ast.pagination.offset,
            "entity": node_type,
            "fields_returned": query_result.fields_returned,
        },
    }


@router.get("/query/{node_type}/filter-paths")
async def get_filter_paths(
    node_type: str,
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Return all valid filter paths and operators for a node type.

    Used by the UI query builder and for MCP tool documentation.
    """
    from packages.query_engine.validator import QueryValidator

    validator = QueryValidator(registry)
    paths = validator.get_allowed_filter_paths(node_type)
    sortable = validator.get_sortable_fields(node_type)
    defaults = validator.get_default_fields(node_type)

    return {
        "data": {
            "entity": node_type,
            "filter_paths": paths,
            "sortable_fields": sortable,
            "default_fields": defaults,
        },
    }


@router.post("/{node_type}", status_code=201)
async def create_node(
    node_type: str,
    body: dict[str, Any],
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create a new node of the given type.

    Request body is validated against the schema-defined attributes.
    """
    node = await svc.create(node_type=node_type, properties=body, actor=actor)
    return {"data": node}


@router.get("/{node_type}/{node_id}")
async def get_node(
    node_type: str,
    node_id: str,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a node by ID."""
    node = await svc.get(node_type=node_type, node_id=node_id, actor=actor)
    return {"data": node}


@router.patch("/{node_type}/{node_id}")
async def update_node(
    node_type: str,
    node_id: str,
    body: dict[str, Any],
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Partial update of a node's properties."""
    node = await svc.update(
        node_type=node_type, node_id=node_id, properties=body, actor=actor,
    )
    return {"data": node}


@router.delete("/{node_type}/{node_id}", status_code=204)
async def delete_node(
    node_type: str,
    node_id: str,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a node and its relationships."""
    await svc.delete(node_type=node_type, node_id=node_id, actor=actor)


@router.get("/{node_type}/{node_id}/relationships")
async def list_relationships(
    node_type: str,
    node_id: str,
    edge_type: str | None = None,
    svc: NodeService = Depends(get_node_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all relationships for a node, optionally filtered by edge type."""
    edges = await svc.get_relationships(
        node_type=node_type, node_id=node_id, edge_type=edge_type, actor=actor,
    )
    return {"data": edges}
