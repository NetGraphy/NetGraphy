"""Architecture visualization CRUD and layout persistence.

Manages saved architecture views (_Architecture nodes) and their
associated node layouts (_NodeLayout nodes linked via LAYOUT_IN edges).

Endpoints:
- GET    /                     - list saved architecture views
- POST   /                     - create a new architecture view
- GET    /{architecture_id}    - get architecture with layout data
- PATCH  /{architecture_id}    - update architecture metadata
- DELETE /{architecture_id}    - delete architecture and its layouts
- PUT    /{architecture_id}/layout    - save/update node positions
- POST   /{architecture_id}/from-query - create architecture from Cypher result
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
)
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()
router = APIRouter()


# --------------------------------------------------------------------------- #
#  Enums & Request/Response Models                                             #
# --------------------------------------------------------------------------- #


class ArchitectureType(str, Enum):
    topology = "topology"
    circuit_path = "circuit_path"
    service_map = "service_map"
    wan = "wan"
    custom = "custom"


class LayoutMode(str, Enum):
    hierarchical = "hierarchical"
    force = "force"
    radial = "radial"
    path = "path"
    manual = "manual"
    hybrid = "hybrid"


class LayoutDirection(str, Enum):
    TB = "TB"
    BT = "BT"
    LR = "LR"
    RL = "RL"


class Visibility(str, Enum):
    personal = "personal"
    shared = "shared"


class NodePosition(BaseModel):
    """A single node's layout position within an architecture."""

    node_id: str
    x: float
    y: float
    pinned: bool = False
    hidden: bool = False
    collapsed: bool = False
    group_id: str | None = None
    layer: int | None = None
    interface_mode: str | None = None


class CameraState(BaseModel):
    """Viewport camera state persisted with the layout."""

    x: float = 0
    y: float = 0
    zoom: float = 1


class LayoutUpdateRequest(BaseModel):
    """Payload for PUT /architectures/{id}/layout."""

    positions: list[NodePosition]
    camera: CameraState = Field(default_factory=CameraState)


class ArchitectureCreateRequest(BaseModel):
    """Payload for POST /architectures."""

    name: str
    description: str = ""
    architecture_type: ArchitectureType = ArchitectureType.custom
    scope_query: str | None = None
    layout_mode: LayoutMode = LayoutMode.force
    layout_direction: LayoutDirection = LayoutDirection.TB
    visibility: Visibility = Visibility.personal
    tenant: str | None = None


class ArchitectureUpdateRequest(BaseModel):
    """Payload for PATCH /architectures/{id}."""

    name: str | None = None
    description: str | None = None
    architecture_type: ArchitectureType | None = None
    scope_query: str | None = None
    layout_mode: LayoutMode | None = None
    layout_direction: LayoutDirection | None = None
    visibility: Visibility | None = None
    tenant: str | None = None


class FromQueryRequest(BaseModel):
    """Payload for POST /architectures/{id}/from-query."""

    query: str
    parameters: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deserialize_camera(raw: str | dict | None) -> dict:
    """Safely deserialize camera JSON stored as a string property."""
    if raw is None:
        return {"x": 0, "y": 0, "zoom": 1}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"x": 0, "y": 0, "zoom": 1}


# --------------------------------------------------------------------------- #
#  LIST architectures                                                          #
# --------------------------------------------------------------------------- #


@router.get("")
async def list_architectures(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    architecture_type: ArchitectureType | None = None,
    visibility: Visibility | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List saved architecture views visible to the current user.

    Supports filtering by architecture_type and visibility.
    Returns architectures owned by the user or shared with them.
    """
    where_clauses = ["(a.owner = $user_id OR a.visibility = 'shared')"]
    params: dict[str, Any] = {
        "user_id": actor.user_id,
        "skip": (page - 1) * page_size,
        "limit": page_size,
    }

    if architecture_type is not None:
        where_clauses.append("a.architecture_type = $arch_type")
        params["arch_type"] = architecture_type.value
    if visibility is not None:
        where_clauses.append("a.visibility = $vis")
        params["vis"] = visibility.value

    where = " AND ".join(where_clauses)

    count_result = await driver.execute_read(
        f"MATCH (a:_Architecture) WHERE {where} RETURN count(a) AS total",
        params,
    )
    total = count_result.rows[0]["total"] if count_result.rows else 0

    result = await driver.execute_read(
        f"MATCH (a:_Architecture) WHERE {where} "
        "RETURN a ORDER BY a.updated_at DESC "
        "SKIP $skip LIMIT $limit",
        params,
    )
    items = [row["a"] for row in result.rows]

    return {
        "data": items,
        "meta": {
            "total_count": total,
            "page": page,
            "page_size": page_size,
        },
    }


# --------------------------------------------------------------------------- #
#  CREATE architecture                                                         #
# --------------------------------------------------------------------------- #


@router.post("", status_code=201)
async def create_architecture(
    body: ArchitectureCreateRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Create a new architecture view."""
    arch_id = str(uuid.uuid4())
    now = _now_iso()

    props = {
        "id": arch_id,
        "name": body.name,
        "description": body.description,
        "architecture_type": body.architecture_type.value,
        "scope_query": body.scope_query,
        "layout_mode": body.layout_mode.value,
        "layout_direction": body.layout_direction.value,
        "owner": actor.user_id,
        "owner_name": actor.username,
        "visibility": body.visibility.value,
        "tenant": body.tenant,
        "camera": json.dumps({"x": 0, "y": 0, "zoom": 1}),
        "created_at": now,
        "updated_at": now,
    }

    await driver.execute_write(
        "CREATE (a:_Architecture $props)",
        {"props": props},
    )

    logger.info(
        "architecture.created",
        architecture_id=arch_id,
        name=body.name,
        owner=actor.user_id,
    )
    return {"data": props}


# --------------------------------------------------------------------------- #
#  GET single architecture (with layouts)                                      #
# --------------------------------------------------------------------------- #


@router.get("/{architecture_id}")
async def get_architecture(
    architecture_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get an architecture view with its node layout data."""
    # Fetch the architecture node
    arch_result = await driver.execute_read(
        "MATCH (a:_Architecture {id: $id}) "
        "WHERE a.owner = $user_id OR a.visibility = 'shared' "
        "RETURN a",
        {"id": architecture_id, "user_id": actor.user_id},
    )
    if not arch_result.rows:
        raise HTTPException(status_code=404, detail="Architecture not found")

    architecture = arch_result.rows[0]["a"]
    architecture["camera"] = _deserialize_camera(architecture.get("camera"))

    # Fetch associated node layouts
    layout_result = await driver.execute_read(
        "MATCH (nl:_NodeLayout)-[:LAYOUT_IN]->(a:_Architecture {id: $id}) "
        "RETURN nl",
        {"id": architecture_id},
    )
    layouts = [row["nl"] for row in layout_result.rows]

    return {
        "data": {
            **architecture,
            "layouts": layouts,
        },
    }


# --------------------------------------------------------------------------- #
#  PATCH architecture metadata                                                 #
# --------------------------------------------------------------------------- #


@router.patch("/{architecture_id}")
async def update_architecture(
    architecture_id: str,
    body: ArchitectureUpdateRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Update architecture metadata (name, description, layout settings, etc.)."""
    # Build SET clauses from non-None fields
    updates: dict[str, Any] = {}
    for field_name, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, Enum):
            updates[field_name] = value.value
        else:
            updates[field_name] = value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = _now_iso()

    set_clauses = ", ".join(f"a.{k} = ${k}" for k in updates)
    result = await driver.execute_write(
        f"MATCH (a:_Architecture {{id: $id, owner: $owner}}) "
        f"SET {set_clauses} RETURN a",
        {"id": architecture_id, "owner": actor.user_id, **updates},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Architecture not found")

    architecture = result.rows[0]["a"]
    architecture["camera"] = _deserialize_camera(architecture.get("camera"))

    logger.info(
        "architecture.updated",
        architecture_id=architecture_id,
        fields=list(updates.keys()),
    )
    return {"data": architecture}


# --------------------------------------------------------------------------- #
#  DELETE architecture                                                         #
# --------------------------------------------------------------------------- #


@router.delete("/{architecture_id}", status_code=204)
async def delete_architecture(
    architecture_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Delete an architecture and all associated node layouts."""
    # Delete layout nodes first, then the architecture itself
    await driver.execute_write(
        "MATCH (nl:_NodeLayout)-[:LAYOUT_IN]->(a:_Architecture {id: $id, owner: $owner}) "
        "DETACH DELETE nl",
        {"id": architecture_id, "owner": actor.user_id},
    )
    await driver.execute_write(
        "MATCH (a:_Architecture {id: $id, owner: $owner}) "
        "DETACH DELETE a",
        {"id": architecture_id, "owner": actor.user_id},
    )

    logger.info(
        "architecture.deleted",
        architecture_id=architecture_id,
        owner=actor.user_id,
    )


# --------------------------------------------------------------------------- #
#  PUT layout (save/update node positions)                                     #
# --------------------------------------------------------------------------- #


@router.put("/{architecture_id}/layout")
async def save_layout(
    architecture_id: str,
    body: LayoutUpdateRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Save or update node positions for an architecture.

    This is an idempotent operation. Existing _NodeLayout nodes for the
    architecture are replaced with the provided positions. The camera
    state is persisted on the _Architecture node itself.
    """
    # Verify ownership
    arch_result = await driver.execute_read(
        "MATCH (a:_Architecture {id: $id, owner: $owner}) RETURN a",
        {"id": architecture_id, "owner": actor.user_id},
    )
    if not arch_result.rows:
        raise HTTPException(status_code=404, detail="Architecture not found")

    # Remove existing layouts for this architecture
    await driver.execute_write(
        "MATCH (nl:_NodeLayout)-[:LAYOUT_IN]->(a:_Architecture {id: $id}) "
        "DETACH DELETE nl",
        {"id": architecture_id},
    )

    # Create new layout nodes and edges in a single batch
    if body.positions:
        layout_params = []
        for pos in body.positions:
            layout_params.append({
                "id": str(uuid.uuid4()),
                "node_id": pos.node_id,
                "x": pos.x,
                "y": pos.y,
                "pinned": pos.pinned,
                "hidden": pos.hidden,
                "collapsed": pos.collapsed,
                "group_id": pos.group_id,
                "layer": pos.layer,
                "interface_mode": pos.interface_mode,
            })

        await driver.execute_write(
            "MATCH (a:_Architecture {id: $arch_id}) "
            "UNWIND $layouts AS layout "
            "CREATE (nl:_NodeLayout) SET nl = layout "
            "CREATE (nl)-[:LAYOUT_IN]->(a)",
            {"arch_id": architecture_id, "layouts": layout_params},
        )

    # Persist camera state and update timestamp on architecture
    await driver.execute_write(
        "MATCH (a:_Architecture {id: $id}) "
        "SET a.camera = $camera, a.updated_at = $updated_at",
        {
            "id": architecture_id,
            "camera": json.dumps(body.camera.model_dump()),
            "updated_at": _now_iso(),
        },
    )

    logger.info(
        "architecture.layout_saved",
        architecture_id=architecture_id,
        node_count=len(body.positions),
    )
    return {
        "data": {
            "architecture_id": architecture_id,
            "node_count": len(body.positions),
            "camera": body.camera.model_dump(),
        },
    }


# --------------------------------------------------------------------------- #
#  POST from-query (create architecture from Cypher result)                    #
# --------------------------------------------------------------------------- #


@router.post("/{architecture_id}/from-query")
async def create_from_query(
    architecture_id: str,
    body: FromQueryRequest,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Populate an architecture's layout from a Cypher query result.

    Executes the provided Cypher query and extracts all nodes from the
    result. Each node is assigned an initial _NodeLayout position (auto-
    arranged) and linked to the architecture via a LAYOUT_IN edge.

    The architecture must already exist.  The scope_query is also updated
    on the architecture node for future refresh operations.
    """
    # Verify ownership
    arch_result = await driver.execute_read(
        "MATCH (a:_Architecture {id: $id, owner: $owner}) RETURN a",
        {"id": architecture_id, "owner": actor.user_id},
    )
    if not arch_result.rows:
        raise HTTPException(status_code=404, detail="Architecture not found")

    # Execute the user's query to discover nodes
    try:
        query_result = await driver.execute_read(
            body.query,
            body.parameters,
        )
    except Exception as e:
        logger.warning(
            "architecture.from_query_failed",
            architecture_id=architecture_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=400,
            detail=f"Query execution failed: {e}",
        )

    # Extract unique node IDs from the query result.
    # We look for nodes that have an 'id' property in each returned row.
    discovered_node_ids: set[str] = set()
    for row in query_result.rows:
        for value in row.values():
            if isinstance(value, dict) and "id" in value:
                discovered_node_ids.add(value["id"])

    if not discovered_node_ids:
        raise HTTPException(
            status_code=400,
            detail="Query returned no nodes with 'id' properties",
        )

    # Remove existing layouts
    await driver.execute_write(
        "MATCH (nl:_NodeLayout)-[:LAYOUT_IN]->(a:_Architecture {id: $id}) "
        "DETACH DELETE nl",
        {"id": architecture_id},
    )

    # Auto-arrange nodes in a grid pattern for initial layout
    layout_params = []
    grid_cols = max(1, int(len(discovered_node_ids) ** 0.5))
    spacing = 200

    for idx, node_id in enumerate(sorted(discovered_node_ids)):
        col = idx % grid_cols
        row_num = idx // grid_cols
        layout_params.append({
            "id": str(uuid.uuid4()),
            "node_id": node_id,
            "x": float(col * spacing),
            "y": float(row_num * spacing),
            "pinned": False,
            "hidden": False,
            "collapsed": False,
            "group_id": None,
            "layer": None,
            "interface_mode": None,
        })

    await driver.execute_write(
        "MATCH (a:_Architecture {id: $arch_id}) "
        "UNWIND $layouts AS layout "
        "CREATE (nl:_NodeLayout) SET nl = layout "
        "CREATE (nl)-[:LAYOUT_IN]->(a)",
        {"arch_id": architecture_id, "layouts": layout_params},
    )

    # Update scope_query and timestamp on the architecture
    await driver.execute_write(
        "MATCH (a:_Architecture {id: $id}) "
        "SET a.scope_query = $scope_query, a.updated_at = $updated_at",
        {
            "id": architecture_id,
            "scope_query": body.query,
            "updated_at": _now_iso(),
        },
    )

    logger.info(
        "architecture.from_query",
        architecture_id=architecture_id,
        nodes_discovered=len(discovered_node_ids),
    )
    return {
        "data": {
            "architecture_id": architecture_id,
            "nodes_discovered": len(discovered_node_ids),
            "scope_query": body.query,
        },
    }
