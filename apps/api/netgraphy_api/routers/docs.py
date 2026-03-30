"""Documentation API — CRUD, search, navigation, and schema-driven generation.

Doc pages are stored as _DocPage nodes in Neo4j with markdown content,
frontmatter metadata, and knowledge graph links to schema entities.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
    get_rbac,
    get_schema_registry,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


def _get_doc_service(driver: Neo4jDriver = Depends(get_graph_driver)):
    from packages.docs.service import DocService
    return DocService(driver)


# --------------------------------------------------------------------------- #
#  Pages                                                                       #
# --------------------------------------------------------------------------- #


@router.get("/pages")
async def list_pages(
    category: str | None = None,
    status: str | None = None,
    svc=Depends(_get_doc_service),
):
    """List documentation pages. Public endpoint for reading published docs."""
    pages = await svc.list_pages(category=category, status=status or "published")
    return {"data": pages}


@router.get("/pages/{slug:path}")
async def get_page(slug: str, svc=Depends(_get_doc_service)):
    """Get a single doc page by slug. Returns full markdown content."""
    page = await svc.get_page(slug)
    if not page:
        raise HTTPException(status_code=404, detail=f"Doc page '{slug}' not found")
    return {"data": page}


@router.post("/pages", status_code=201)
async def create_page(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    svc=Depends(_get_doc_service),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a new documentation page."""
    rbac.require_permission(actor, "manage", "schema:*")
    page = await svc.create_page(body, author=actor.username)
    return {"data": page}


@router.patch("/pages/{slug:path}")
async def update_page(
    slug: str,
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    svc=Depends(_get_doc_service),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update a documentation page."""
    rbac.require_permission(actor, "manage", "schema:*")
    page = await svc.update_page(slug, body, author=actor.username)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"data": page}


@router.delete("/pages/{slug:path}", status_code=204)
async def delete_page(
    slug: str,
    actor: AuthContext = Depends(get_auth_context),
    svc=Depends(_get_doc_service),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Delete a documentation page."""
    rbac.require_permission(actor, "manage", "schema:*")
    if not await svc.delete_page(slug):
        raise HTTPException(status_code=404, detail="Page not found")


# --------------------------------------------------------------------------- #
#  Navigation                                                                  #
# --------------------------------------------------------------------------- #


@router.get("/nav")
async def get_navigation(svc=Depends(_get_doc_service)):
    """Get the documentation navigation tree grouped by category."""
    return {"data": await svc.get_nav_tree()}


# --------------------------------------------------------------------------- #
#  Search                                                                      #
# --------------------------------------------------------------------------- #


@router.get("/search")
async def search_docs(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    svc=Depends(_get_doc_service),
):
    """Full-text search across documentation pages."""
    results = await svc.search(q, limit=limit)
    return {"data": results}


# --------------------------------------------------------------------------- #
#  Schema-Linked Docs                                                          #
# --------------------------------------------------------------------------- #


@router.get("/for/{item_type}/{item_name}")
async def get_docs_for_schema_item(
    item_type: str,
    item_name: str,
    svc=Depends(_get_doc_service),
):
    """Find documentation pages linked to a specific schema item."""
    results = await svc.get_docs_for_schema_item(item_type, item_name)
    return {"data": results}


# --------------------------------------------------------------------------- #
#  Documentation Generation                                                    #
# --------------------------------------------------------------------------- #


@router.post("/generate", status_code=201)
async def generate_docs(
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Generate starter documentation from the current schema.

    Creates doc pages for all node types, edge types, and platform
    overview pages. Existing pages with the same slug are skipped.
    """
    rbac.require_permission(actor, "manage", "schema:*")

    from packages.docs.generator import generate_all_docs
    from packages.docs.service import DocService

    svc = DocService(driver)
    all_docs = generate_all_docs(registry)

    created = 0
    skipped = 0
    for doc in all_docs:
        existing = await svc.get_page(doc["slug"])
        if existing:
            skipped += 1
            continue
        await svc.create_page(doc, author=actor.username)
        created += 1

    return {
        "data": {
            "created": created,
            "skipped": skipped,
            "total_generated": len(all_docs),
        }
    }
