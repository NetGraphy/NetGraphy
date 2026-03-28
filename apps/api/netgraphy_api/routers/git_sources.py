"""Git source management and sync endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from netgraphy_api.dependencies import (
    get_graph_driver,
    get_schema_registry,
    get_event_bus,
    get_auth_context,
    get_rbac,
)
from netgraphy_api.exceptions import SyncSourceNotFoundError
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry
from packages.sync_engine.service import GitSource, SyncService

router = APIRouter()


def _get_sync_service(
    registry: SchemaRegistry = Depends(get_schema_registry),
    driver: Neo4jDriver = Depends(get_graph_driver),
    events: EventBus = Depends(get_event_bus),
) -> SyncService:
    return SyncService(schema_registry=registry, graph_driver=driver, event_bus=events)


@router.get("")
async def list_git_sources(
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List registered Git sources."""
    sources = await svc.list_sources()
    return {"data": sources}


@router.post("", status_code=201)
async def register_git_source(
    body: dict[str, Any],
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Register a new Git source for content sync. Requires operator+."""
    rbac.require_permission(actor, "manage", "sync")

    source = GitSource(
        id=str(uuid.uuid4()),
        name=body.get("name", ""),
        description=body.get("description", ""),
        url=body.get("url", ""),
        branch=body.get("branch", "main"),
        auth_type=body.get("auth_type", "token"),
        auth_token=body.get("auth_token"),
        sync_mode=body.get("sync_mode", "polling"),
        poll_interval_seconds=body.get("poll_interval_seconds", 300),
        auto_apply=body.get("auto_apply", False),
        content_mappings=body.get("content_mappings", []),
        created_by=actor.user_id,
    )

    if not source.name or not source.url:
        from netgraphy_api.exceptions import NetGraphyError
        raise NetGraphyError("'name' and 'url' are required")

    registered = await svc.register_source(source)
    return {
        "data": {
            "id": registered.id,
            "name": registered.name,
            "url": registered.url,
            "branch": registered.branch,
            "content_mappings": registered.content_mappings,
        }
    }


@router.get("/{source_id}")
async def get_git_source(
    source_id: str,
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get Git source details including sync status."""
    source = await svc.get_source(source_id)
    if not source:
        raise SyncSourceNotFoundError()
    return {
        "data": {
            "id": source.id,
            "name": source.name,
            "description": source.description,
            "url": source.url,
            "branch": source.branch,
            "sync_mode": source.sync_mode,
            "auto_apply": source.auto_apply,
            "content_mappings": source.content_mappings,
            "last_sync_at": source.last_sync_at,
            "last_sync_commit": source.last_sync_commit,
            "last_sync_status": source.last_sync_status,
        }
    }


@router.delete("/{source_id}", status_code=204)
async def delete_git_source(
    source_id: str,
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Delete a Git source registration."""
    rbac.require_permission(actor, "manage", "sync")
    deleted = await svc.delete_source(source_id)
    if not deleted:
        raise SyncSourceNotFoundError()


@router.post("/{source_id}/sync", status_code=202)
async def trigger_sync(
    source_id: str,
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Manually trigger a sync for this Git source."""
    rbac.require_permission(actor, "manage", "sync")

    result = await svc.sync(source_id)
    return {
        "data": {
            "source_id": result.source_id,
            "status": result.status,
            "commit_sha": result.commit_sha,
            "changes_applied": result.changes_applied,
            "errors": result.errors,
            "domain_results": result.domain_results,
        }
    }


@router.get("/{source_id}/sync-history")
async def list_sync_history(
    source_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
):
    """List sync events for this source."""
    return await svc.get_sync_history(source_id, page=page, page_size=page_size)


@router.get("/{source_id}/preview")
async def preview_sync(
    source_id: str,
    svc: SyncService = Depends(_get_sync_service),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Preview pending changes from the Git source without applying."""
    rbac.require_permission(actor, "manage", "sync")

    diff = await svc.preview(source_id)
    return {
        "data": {
            "additions": diff.additions,
            "modifications": diff.modifications,
            "deletions": diff.deletions,
            "validation_errors": diff.validation_errors,
            "warnings": diff.warnings,
            "total_changes": len(diff.additions) + len(diff.modifications) + len(diff.deletions),
        }
    }
