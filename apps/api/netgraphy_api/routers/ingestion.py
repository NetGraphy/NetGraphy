"""Ingestion pipeline endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.post("/run", status_code=202)
async def trigger_ingestion_run(body: dict[str, Any]):
    """Trigger an ingestion run.

    Body:
        target_query: str — Cypher query to select target devices
        command_bundle: str — command bundle name to execute
        dry_run: bool — preview mutations without applying
    """
    # TODO: Dispatch ingestion job to worker queue
    return {
        "data": {
            "run_id": "placeholder",
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
):
    """List ingestion runs with status filtering."""
    # TODO: Retrieve ingestion run history
    return {"data": [], "meta": {"total_count": 0, "page": page, "page_size": page_size}}


@router.get("/runs/{run_id}")
async def get_ingestion_run(run_id: str):
    """Get details of a specific ingestion run including per-device results."""
    # TODO: Retrieve run details with device-level results
    raise HTTPException(status_code=404, detail=f"Ingestion run '{run_id}' not found")
