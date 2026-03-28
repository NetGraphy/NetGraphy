"""Audit log endpoints."""

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/events")
async def list_audit_events(
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List audit events with filtering.

    Supports filtering by action, resource_type, and actor.
    """
    # TODO: Query audit storage (PostgreSQL sidecar or Neo4j)
    return {"data": [], "meta": {"total_count": 0, "page": page, "page_size": page_size}}


@router.get("/events/{event_id}")
async def get_audit_event(event_id: str):
    """Get a specific audit event with full details."""
    # TODO: Retrieve from audit storage
    raise HTTPException(status_code=404, detail=f"Audit event '{event_id}' not found")
