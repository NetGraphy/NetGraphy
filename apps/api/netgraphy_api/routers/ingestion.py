"""Ingestion pipeline endpoints.

Ingestion runs are tracked as _IngestionRun nodes in Neo4j.
Each run collects from devices, parses output, maps to graph mutations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_rbac
from netgraphy_api.exceptions import NodeNotFoundError
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver

router = APIRouter()


@router.post("/run", status_code=202)
async def trigger_ingestion_run(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Trigger an ingestion run.

    Body:
        target_query: str — Cypher query to select target devices
        command_bundle: str — command bundle name to execute
        dry_run: bool — preview mutations without applying
    """
    rbac.require_permission(actor, "execute", "job:ingestion")

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    await driver.execute_write(
        "CREATE (r:_IngestionRun $props) RETURN r",
        {"props": {
            "id": run_id,
            "status": "queued",
            "target_query": body.get("target_query", ""),
            "command_bundle": body.get("command_bundle", ""),
            "dry_run": body.get("dry_run", False),
            "triggered_by": actor.user_id,
            "created_at": now,
            "device_count": 0,
            "records_parsed": 0,
            "mutations_applied": 0,
            "errors": [],
        }},
    )

    # TODO: Dispatch to Celery worker
    # from apps.worker.main import execute_ingestion
    # execute_ingestion.delay(run_id, body.get("target_query"), body.get("command_bundle"))

    return {
        "data": {
            "run_id": run_id,
            "status": "queued",
            "target_query": body.get("target_query"),
            "command_bundle": body.get("command_bundle"),
        }
    }


@router.get("/runs")
async def list_ingestion_runs(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List ingestion runs with status filtering."""
    where = ""
    params: dict[str, Any] = {}
    if status:
        where = " WHERE r.status = $status"
        params["status"] = status

    skip = (page - 1) * page_size
    params.update({"skip": skip, "limit": page_size})

    count_r = await driver.execute_read(
        f"MATCH (r:_IngestionRun){where} RETURN count(r) as total", params
    )
    total = count_r.rows[0]["total"] if count_r.rows else 0

    data_r = await driver.execute_read(
        f"MATCH (r:_IngestionRun){where} RETURN r ORDER BY r.created_at DESC SKIP $skip LIMIT $limit",
        params,
    )
    items = [row["r"] for row in data_r.rows]

    return {"data": items, "meta": {"total_count": total, "page": page, "page_size": page_size}}


@router.get("/runs/{run_id}")
async def get_ingestion_run(
    run_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get details of a specific ingestion run."""
    result = await driver.execute_read(
        "MATCH (r:_IngestionRun {id: $id}) RETURN r", {"id": run_id}
    )
    if not result.rows:
        raise NodeNotFoundError("_IngestionRun", run_id)
    return {"data": result.rows[0]["r"]}
