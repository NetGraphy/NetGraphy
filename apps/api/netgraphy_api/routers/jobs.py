"""Job management and execution endpoints.

Job manifests are loaded from YAML files in the jobs/ directory.
Job executions are tracked as _JobExecution nodes in Neo4j.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_rbac
from netgraphy_api.exceptions import NodeNotFoundError
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver

router = APIRouter()

# Load job manifests from jobs/ directory at import time
_JOB_MANIFESTS: dict[str, dict] = {}


def _load_manifests() -> None:
    """Load all job manifest YAML files from the jobs directory."""
    jobs_dir = Path("jobs")
    if not jobs_dir.exists():
        return
    for yaml_file in sorted(jobs_dir.rglob("*.yaml")) + sorted(jobs_dir.rglob("*.yml")):
        try:
            with open(yaml_file) as f:
                doc = yaml.safe_load(f)
            if doc and doc.get("kind") == "Job":
                name = doc.get("metadata", {}).get("name", yaml_file.stem)
                _JOB_MANIFESTS[name] = doc
        except Exception:
            pass


_load_manifests()


@router.get("")
async def list_jobs(
    actor: AuthContext = Depends(get_auth_context),
):
    """List registered job definitions from manifests."""
    jobs = []
    for name, manifest in _JOB_MANIFESTS.items():
        meta = manifest.get("metadata", {})
        jobs.append({
            "name": name,
            "display_name": meta.get("display_name", name),
            "description": meta.get("description", ""),
            "runtime": manifest.get("runtime", "python"),
            "tags": meta.get("tags", []),
            "schedule": manifest.get("schedule", {}),
            "parameters": manifest.get("parameters", {}),
        })
    return {"data": jobs}


@router.get("/{job_name}")
async def get_job(
    job_name: str,
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a job definition with its manifest and parameter schema."""
    manifest = _JOB_MANIFESTS.get(job_name)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Job '{job_name}' not found")
    return {"data": manifest}


@router.post("/{job_name}/execute", status_code=202)
async def execute_job(
    job_name: str,
    body: dict[str, Any] | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Trigger a job execution with parameters.

    Creates a _JobExecution record and dispatches to worker queue.
    Returns immediately with an execution ID for tracking.
    """
    rbac.require_permission(actor, "execute", f"job:{job_name}")

    manifest = _JOB_MANIFESTS.get(job_name)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Job '{job_name}' not found")

    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Create execution record
    await driver.execute_write(
        "CREATE (e:_JobExecution $props) RETURN e",
        {"props": {
            "id": execution_id,
            "job_name": job_name,
            "status": "queued",
            "parameters": str(body or {}),
            "triggered_by": actor.user_id,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
        }},
    )

    # TODO: Dispatch to Celery worker queue
    # from apps.worker.main import execute_job as celery_task
    # celery_task.delay(job_name, execution_id, body or {})

    return {
        "data": {
            "execution_id": execution_id,
            "job_name": job_name,
            "status": "queued",
            "parameters": body or {},
        }
    }


@router.get("/{job_name}/executions")
async def list_executions(
    job_name: str,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List job executions with optional status filtering."""
    where_parts = ["e.job_name = $job_name"]
    params: dict[str, Any] = {"job_name": job_name}

    if status:
        where_parts.append("e.status = $status")
        params["status"] = status

    where = " WHERE " + " AND ".join(where_parts)
    skip = (page - 1) * page_size
    params.update({"skip": skip, "limit": page_size})

    count_r = await driver.execute_read(
        f"MATCH (e:_JobExecution){where} RETURN count(e) as total", params
    )
    total = count_r.rows[0]["total"] if count_r.rows else 0

    data_r = await driver.execute_read(
        f"MATCH (e:_JobExecution){where} RETURN e ORDER BY e.created_at DESC SKIP $skip LIMIT $limit",
        params,
    )
    items = [row["e"] for row in data_r.rows]

    return {"data": items, "meta": {"total_count": total, "page": page, "page_size": page_size}}


@router.get("/{job_name}/executions/{execution_id}")
async def get_execution(
    job_name: str,
    execution_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get execution details including status, timing, and summary."""
    result = await driver.execute_read(
        "MATCH (e:_JobExecution {id: $id}) RETURN e",
        {"id": execution_id},
    )
    if not result.rows:
        raise NodeNotFoundError("_JobExecution", execution_id)
    return {"data": result.rows[0]["e"]}


@router.get("/{job_name}/executions/{execution_id}/logs")
async def get_execution_logs(
    job_name: str,
    execution_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get execution logs."""
    # TODO: Retrieve logs from log storage / MinIO
    return {"data": {"logs": [], "execution_id": execution_id}}
