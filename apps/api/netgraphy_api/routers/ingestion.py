"""Ingestion pipeline endpoints.

Ingestion runs are tracked as _IngestionRun nodes in Neo4j.
Each run collects from devices, parses output, maps to graph mutations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

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


# --------------------------------------------------------------------------- #
#  Webhook-triggered Ingestion                                                  #
# --------------------------------------------------------------------------- #


@router.post("/webhook")
async def webhook_trigger(
    request: Request,
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Webhook-triggered ingestion. Validates source and dispatches run."""
    body = await request.json()
    source_id = request.headers.get("X-Webhook-Source")
    signature = request.headers.get("X-Webhook-Signature")

    if not source_id:
        raise HTTPException(status_code=400, detail="Missing X-Webhook-Source header")

    # Look up webhook source
    result = await driver.execute_read(
        "MATCH (w:_WebhookSource {id: $id, is_active: true}) RETURN w",
        {"id": source_id},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Webhook source not found")

    ws = result.rows[0]["w"]

    # Create ingestion run from webhook config
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await driver.execute_write(
        "CREATE (r:_IngestionRun $props) RETURN r",
        {
            "props": {
                "id": run_id,
                "status": "queued",
                "target_query": ws.get("target_query", ""),
                "command_bundle": ws.get("command_bundle", ""),
                "dry_run": False,
                "triggered_by": f"webhook:{source_id}",
                "created_at": now,
            }
        },
    )

    # TODO: dispatch to celery when worker is connected
    return {"data": {"run_id": run_id, "status": "queued", "source": "webhook"}}


# --------------------------------------------------------------------------- #
#  Preview (dry-run)                                                            #
# --------------------------------------------------------------------------- #


@router.post("/preview")
async def preview_ingestion(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Dry-run ingestion that returns mutations without applying."""
    import json as _json

    from netgraphy_api.dependencies import get_event_bus, get_schema_registry
    from packages.ingestion.collectors.base import DeviceTarget
    from packages.ingestion.collectors.mock_collector import MockCollector
    from packages.ingestion.pipeline import IngestionPipeline

    target_query = body.get("target_query", "")
    command_bundle = body.get("command_bundle", "")

    # Build pipeline with mock collector (preview mode)
    registry = get_schema_registry()
    event_bus = get_event_bus()
    collector = MockCollector()

    pipeline = IngestionPipeline(
        driver=driver,
        registry=registry,
        event_bus=event_bus,
        collector=collector,
    )

    # Load command bundle
    bundle_result = await driver.execute_read(
        "MATCH (cb:_CommandBundle {name: $name}) RETURN cb",
        {"name": command_bundle},
    )
    if not bundle_result.rows:
        raise HTTPException(
            status_code=404,
            detail=f"Command bundle '{command_bundle}' not found",
        )

    commands_json = bundle_result.rows[0]["cb"]["commands_json"]
    commands = _json.loads(commands_json)

    # Build targets from query (limit to 5 for preview)
    targets_result = await driver.execute_read(target_query)
    targets: list[DeviceTarget] = []
    for row in targets_result.rows:
        d = row.get("d") or row.get("n") or {}
        targets.append(
            DeviceTarget(
                hostname=d.get("hostname", "unknown"),
                platform_slug=d.get("platform_slug"),
            )
        )

    result = await pipeline.execute("preview", targets[:5], commands, dry_run=True)

    return {
        "data": {
            "devices_processed": result.devices_processed,
            "records_parsed": result.records_parsed,
            "mutations_generated": result.mutations_generated,
            "dry_run_mutations": result.dry_run_mutations or [],
            "errors": result.errors,
        }
    }


# --------------------------------------------------------------------------- #
#  Webhook Source CRUD                                                          #
# --------------------------------------------------------------------------- #


@router.post("/webhooks", status_code=201)
async def create_webhook(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create a webhook source for ingestion triggers."""
    webhook_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")

    await driver.execute_write(
        "CREATE (w:_WebhookSource $props) RETURN w",
        {
            "props": {
                "id": webhook_id,
                "name": name,
                "target_query": body.get("target_query", ""),
                "command_bundle": body.get("command_bundle", ""),
                "is_active": body.get("is_active", True),
                "created_by": actor.user_id,
                "created_at": now,
            }
        },
    )
    return {"data": {"id": webhook_id, "name": name}}


@router.get("/webhooks")
async def list_webhooks(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all webhook sources."""
    result = await driver.execute_read(
        "MATCH (w:_WebhookSource) RETURN w ORDER BY w.name", {}
    )
    return {"data": [row["w"] for row in result.rows]}


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete a webhook source."""
    await driver.execute_write(
        "MATCH (w:_WebhookSource {id: $id}) DELETE w",
        {"id": webhook_id},
    )
