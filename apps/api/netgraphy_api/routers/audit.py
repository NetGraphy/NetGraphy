"""Audit log endpoints.

Audit events are stored as _AuditEvent nodes in Neo4j (Phase 1).
In Phase 4, these migrate to PostgreSQL with time-range partitioning.
"""

from fastapi import APIRouter, Depends, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context
from netgraphy_api.exceptions import NodeNotFoundError
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver

router = APIRouter()


@router.get("/events")
async def list_audit_events(
    action: str | None = None,
    resource_type: str | None = None,
    actor_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    driver: Neo4jDriver = Depends(get_graph_driver),
    auth: AuthContext = Depends(get_auth_context),
):
    """List audit events with filtering."""
    where_parts = []
    params: dict = {}

    if action:
        where_parts.append("e.action = $action")
        params["action"] = action
    if resource_type:
        where_parts.append("e.resource_type = $resource_type")
        params["resource_type"] = resource_type
    if actor_id:
        where_parts.append("e.actor_id = $actor_id")
        params["actor_id"] = actor_id

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    skip = (page - 1) * page_size
    params["skip"] = skip
    params["limit"] = page_size

    count_q = f"MATCH (e:_AuditEvent){where_clause} RETURN count(e) as total"
    count_result = await driver.execute_read(count_q, params)
    total = count_result.rows[0]["total"] if count_result.rows else 0

    data_q = (
        f"MATCH (e:_AuditEvent){where_clause} "
        f"RETURN e ORDER BY e.timestamp DESC SKIP $skip LIMIT $limit"
    )
    data_result = await driver.execute_read(data_q, params)
    items = [row.get("e", {}) for row in data_result.rows]

    return {
        "data": items,
        "meta": {"total_count": total, "page": page, "page_size": page_size},
    }


@router.get("/events/{event_id}")
async def get_audit_event(
    event_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    auth: AuthContext = Depends(get_auth_context),
):
    """Get a specific audit event with full details."""
    result = await driver.execute_read(
        "MATCH (e:_AuditEvent {id: $id}) RETURN e",
        {"id": event_id},
    )
    if not result.rows:
        raise NodeNotFoundError("_AuditEvent", event_id)
    return {"data": result.rows[0].get("e", {})}
