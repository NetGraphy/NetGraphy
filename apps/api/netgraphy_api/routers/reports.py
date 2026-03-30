"""Report API — execute, export, and manage saved reports.

Endpoints:
- POST /reports/execute — run a report definition and return results
- POST /reports/export/csv — export a report as CSV
- GET /reports/columns/{entity} — available columns for report builder
- GET /reports/entities — available root entity types
- GET /reports/filters/{entity} — available filter paths
- CRUD for saved reports
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
    get_schema_registry,
)
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()
router = APIRouter()


def _build_report_executor(driver: Neo4jDriver, registry: SchemaRegistry):
    from packages.query_engine.report_executor import ReportExecutor
    return ReportExecutor(driver, registry)


def _parse_report_definition(body: dict[str, Any]):
    """Parse a report definition from request body."""
    from packages.query_engine.models import (
        FilterCondition,
        FilterGroup,
        FilterOperator,
        LogicalOperator,
        Pagination,
        SortField,
        SortDirection,
    )
    from packages.query_engine.report_models import (
        ColumnSource,
        ReportColumn,
        ReportDefinition,
        RowMode,
    )

    # Parse columns
    columns = []
    for col_data in body.get("columns", []):
        columns.append(ReportColumn(
            path=col_data.get("path", ""),
            source=ColumnSource(col_data.get("source", "root")),
            display_label=col_data.get("display_label"),
            alias=col_data.get("alias"),
            formatter=col_data.get("formatter"),
        ))

    # Parse filters
    filters = None
    raw_filters = body.get("filters", [])
    if raw_filters:
        conditions = []
        for f in raw_filters:
            conditions.append(FilterCondition(
                path=f.get("path", ""),
                operator=FilterOperator(f.get("operator", "eq")),
                value=f.get("value"),
            ))
        filters = FilterGroup(op=LogicalOperator.AND, conditions=conditions)

    # Parse sort
    sort_fields = []
    if body.get("sort"):
        sf = body["sort"]
        direction = SortDirection(body.get("sort_direction", "asc"))
        if sf.startswith("-"):
            sf = sf[1:]
            direction = SortDirection.DESC
        sort_fields.append(SortField(field=sf, direction=direction))

    return ReportDefinition(
        root_entity=body.get("root_entity", ""),
        columns=columns,
        filters=filters,
        row_mode=RowMode(body.get("row_mode", "root")),
        sort=sort_fields,
        pagination=Pagination(
            limit=min(body.get("limit", 50), body.get("max_export_rows", 10000)),
            offset=body.get("offset", 0),
        ),
        group_by=body.get("group_by", []),
        aggregate_function=body.get("aggregate_function", "count"),
        max_export_rows=body.get("max_export_rows", 10000),
        name=body.get("name", ""),
        description=body.get("description", ""),
    )


# --------------------------------------------------------------------------- #
#  Report Execution                                                            #
# --------------------------------------------------------------------------- #


@router.post("/execute")
async def execute_report(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute a report definition and return structured results.

    Body:
        root_entity: str — base node type
        columns: [{path, source, display_label, alias}]
        filters: [{path, operator, value}]
        row_mode: "root" | "expanded" | "aggregate"
        sort: str — field to sort by
        limit: int — max rows
        offset: int — pagination offset
        group_by: [str] — for aggregate mode
    """
    report = _parse_report_definition(body)
    if not report.root_entity:
        raise HTTPException(status_code=400, detail="root_entity is required")

    if not registry.get_node_type(report.root_entity):
        raise HTTPException(status_code=400, detail=f"Unknown entity: {report.root_entity}")

    executor = _build_report_executor(driver, registry)

    try:
        result = await executor.execute(report)
    except Exception as e:
        logger.error("report_execution_error", error=str(e), entity=report.root_entity)
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "data": {
            "columns": result.columns,
            "rows": result.rows,
            "total_count": result.total_count,
            "row_mode": result.row_mode.value,
            "csv_headers": result.csv_headers,
        },
        "meta": result.query_metadata,
    }


@router.post("/export/csv")
async def export_csv(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Export a report as a streaming CSV download."""
    report = _parse_report_definition(body)
    if not report.root_entity:
        raise HTTPException(status_code=400, detail="root_entity is required")

    executor = _build_report_executor(driver, registry)

    try:
        csv_content = await executor.export_csv(report)
    except Exception as e:
        logger.error("csv_export_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    filename = f"{report.root_entity.lower()}_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --------------------------------------------------------------------------- #
#  Report Builder Metadata                                                     #
# --------------------------------------------------------------------------- #


@router.get("/entities")
async def list_report_entities(
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all entity types available as report roots."""
    from packages.query_engine.report_executor import ReportExecutor
    # Use a dummy driver since we only need registry
    executor = ReportExecutor(None, registry)  # type: ignore
    return {"data": executor.get_available_entities()}


@router.get("/columns/{entity}")
async def get_report_columns(
    entity: str,
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get available columns for a given root entity.

    Returns root fields, related node fields, edge fields, and aggregate fields.
    Used by the report builder UI to populate the column picker.
    """
    if not registry.get_node_type(entity):
        raise HTTPException(status_code=404, detail=f"Unknown entity: {entity}")

    from packages.query_engine.report_executor import ReportExecutor
    executor = ReportExecutor(None, registry)  # type: ignore
    columns = executor.get_available_columns(entity)
    return {"data": columns}


@router.get("/filters/{entity}")
async def get_report_filters(
    entity: str,
    registry: SchemaRegistry = Depends(get_schema_registry),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get available filter paths and operators for a given entity."""
    from packages.query_engine.validator import QueryValidator
    validator = QueryValidator(registry)
    paths = validator.get_allowed_filter_paths(entity)
    sortable = validator.get_sortable_fields(entity)
    return {"data": {"filter_paths": paths, "sortable_fields": sortable}}


# --------------------------------------------------------------------------- #
#  Saved Reports CRUD                                                          #
# --------------------------------------------------------------------------- #


@router.get("/saved")
async def list_saved_reports(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List saved reports visible to the current user."""
    result = await driver.execute_read(
        "MATCH (r:_SavedReport) "
        "WHERE r.owner = $user OR r.visibility IN ['shared', 'tenant'] "
        "RETURN r ORDER BY r.updated_at DESC",
        {"user": actor.user_id},
    )
    reports = [row["r"] for row in result.rows]
    return {"data": reports}


@router.post("/saved", status_code=201)
async def save_report(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Save a report definition."""
    import json

    report_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    props = {
        "id": report_id,
        "name": body.get("name", "Untitled Report"),
        "description": body.get("description", ""),
        "root_entity": body.get("root_entity", ""),
        "definition": json.dumps(body.get("definition", {})),
        "owner": actor.user_id,
        "owner_name": actor.username,
        "visibility": body.get("visibility", "personal"),
        "tags": body.get("tags", []),
        "folder": body.get("folder"),
        "favorited": body.get("favorited", False),
        "created_at": now,
        "updated_at": now,
        "last_run_at": None,
        "run_count": 0,
    }

    await driver.execute_write("CREATE (r:_SavedReport $props)", {"props": props})
    return {"data": props}


@router.get("/saved/{report_id}")
async def get_saved_report(
    report_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a saved report by ID."""
    result = await driver.execute_read(
        "MATCH (r:_SavedReport {id: $id}) RETURN r",
        {"id": report_id},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Report not found")

    import json
    report = result.rows[0]["r"]
    if isinstance(report.get("definition"), str):
        report["definition"] = json.loads(report["definition"])
    return {"data": report}


@router.patch("/saved/{report_id}")
async def update_saved_report(
    report_id: str,
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Update a saved report."""
    import json

    updates = {k: v for k, v in body.items() if k not in ("id", "owner", "created_at")}
    if "definition" in updates and isinstance(updates["definition"], dict):
        updates["definition"] = json.dumps(updates["definition"])
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clauses = ", ".join(f"r.{k} = ${k}" for k in updates)
    result = await driver.execute_write(
        f"MATCH (r:_SavedReport {{id: $id, owner: $owner}}) SET {set_clauses} RETURN r",
        {"id": report_id, "owner": actor.user_id, **updates},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Report not found")

    report = result.rows[0]["r"]
    if isinstance(report.get("definition"), str):
        report["definition"] = json.loads(report["definition"])
    return {"data": report}


@router.delete("/saved/{report_id}", status_code=204)
async def delete_saved_report(
    report_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a saved report."""
    await driver.execute_write(
        "MATCH (r:_SavedReport {id: $id, owner: $owner}) DELETE r",
        {"id": report_id, "owner": actor.user_id},
    )
