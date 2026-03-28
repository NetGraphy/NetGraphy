"""Git source management and sync endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("")
async def list_git_sources():
    """List registered Git sources."""
    # TODO: Retrieve from sync engine storage
    return {"data": []}


@router.post("", status_code=201)
async def register_git_source(body: dict[str, Any]):
    """Register a new Git source for content sync."""
    # TODO: Validate repo URL, auth, store registration
    return {"data": {"id": "placeholder", **body}}


@router.get("/{source_id}")
async def get_git_source(source_id: str):
    """Get Git source details including sync status."""
    # TODO: Retrieve source with latest sync status
    raise HTTPException(status_code=404, detail=f"Git source '{source_id}' not found")


@router.post("/{source_id}/sync", status_code=202)
async def trigger_sync(source_id: str):
    """Manually trigger a sync for this Git source."""
    # TODO: Dispatch sync job to worker
    return {"data": {"source_id": source_id, "status": "syncing"}}


@router.get("/{source_id}/sync-history")
async def list_sync_history(
    source_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """List sync events for this source."""
    # TODO: Retrieve sync history
    return {"data": [], "meta": {"total_count": 0, "page": page, "page_size": page_size}}


@router.get("/{source_id}/preview")
async def preview_sync(source_id: str):
    """Preview pending changes from the Git source without applying."""
    # TODO: Fetch latest, diff against current state, return preview
    return {"data": {"changes": [], "additions": 0, "modifications": 0, "deletions": 0}}
