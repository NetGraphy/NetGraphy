"""Documentation Service — CRUD, versioning, search, and knowledge graph integration.

DocPages are stored as _DocPage nodes in Neo4j with markdown content, frontmatter
metadata, and relationships to schema entities (node types, edge types, tools).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


class DocService:
    """Manages documentation pages, navigation, search, and knowledge graph links."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------ #
    #  Pages CRUD                                                         #
    # ------------------------------------------------------------------ #

    async def list_pages(
        self,
        category: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List doc pages with optional filtering."""
        wheres: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if category:
            wheres.append("d.category = $category")
            params["category"] = category
        if status:
            wheres.append("d.status = $status")
            params["status"] = status
        where = (" WHERE " + " AND ".join(wheres)) if wheres else ""

        result = await self._driver.execute_read(
            f"MATCH (d:_DocPage){where} "
            "RETURN d ORDER BY d.nav_order, d.title LIMIT $limit",
            params,
        )
        return [self._sanitize_page(row["d"]) for row in result.rows]

    async def get_page(self, slug: str) -> dict[str, Any] | None:
        """Get a page by slug with full content."""
        result = await self._driver.execute_read(
            "MATCH (d:_DocPage {slug: $slug}) RETURN d",
            {"slug": slug},
        )
        if not result.rows:
            return None
        return result.rows[0]["d"]

    async def get_page_by_id(self, page_id: str) -> dict[str, Any] | None:
        result = await self._driver.execute_read(
            "MATCH (d:_DocPage {id: $id}) RETURN d", {"id": page_id}
        )
        return result.rows[0]["d"] if result.rows else None

    async def create_page(self, page_data: dict[str, Any], author: str = "") -> dict[str, Any]:
        """Create a new documentation page."""
        import json

        page_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        props = {
            "id": page_id,
            "title": page_data.get("title", ""),
            "slug": page_data.get("slug", ""),
            "summary": page_data.get("summary", ""),
            "category": page_data.get("category", "general"),
            "content": page_data.get("content", ""),
            "status": page_data.get("status", "draft"),
            "tags": json.dumps(page_data.get("tags", [])),
            "related_node_types": json.dumps(page_data.get("related_node_types", [])),
            "related_edge_types": json.dumps(page_data.get("related_edge_types", [])),
            "related_tools": json.dumps(page_data.get("related_tools", [])),
            "plugin_owner": page_data.get("plugin_owner", ""),
            "nav_order": page_data.get("nav_order", 999),
            "parent_slug": page_data.get("parent_slug", ""),
            "author": author,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

        await self._driver.execute_write(
            "CREATE (d:_DocPage $props) RETURN d", {"props": props}
        )

        # Create knowledge graph links
        await self._link_to_schema(page_id, page_data)

        logger.info("docs.page_created", page_id=page_id, slug=props["slug"])
        return props

    async def update_page(self, slug: str, updates: dict[str, Any], author: str = "") -> dict[str, Any] | None:
        """Update a page's content and metadata."""
        import json

        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now
        updates["updated_by"] = author

        # Serialize list fields
        for field in ["tags", "related_node_types", "related_edge_types", "related_tools"]:
            if field in updates and isinstance(updates[field], list):
                updates[field] = json.dumps(updates[field])

        # Increment version
        updates["version"] = "d.version + 1"

        set_parts = []
        params: dict[str, Any] = {"slug": slug}
        for k, v in updates.items():
            if k == "version":
                set_parts.append("d.version = d.version + 1")
            else:
                set_parts.append(f"d.{k} = ${k}")
                params[k] = v

        result = await self._driver.execute_write(
            f"MATCH (d:_DocPage {{slug: $slug}}) SET {', '.join(set_parts)} RETURN d",
            params,
        )
        if not result.rows:
            return None

        # Update knowledge graph links
        page = result.rows[0]["d"]
        if "related_node_types" in updates or "related_edge_types" in updates:
            await self._link_to_schema(page.get("id", ""), updates)

        return page

    async def delete_page(self, slug: str) -> bool:
        result = await self._driver.execute_write(
            "MATCH (d:_DocPage {slug: $slug}) DETACH DELETE d RETURN count(d) as deleted",
            {"slug": slug},
        )
        return result.rows[0]["deleted"] > 0 if result.rows else False

    # ------------------------------------------------------------------ #
    #  Navigation tree                                                     #
    # ------------------------------------------------------------------ #

    async def get_nav_tree(self) -> list[dict[str, Any]]:
        """Build the documentation navigation tree from page categories and ordering."""
        result = await self._driver.execute_read(
            "MATCH (d:_DocPage) WHERE d.status = 'published' OR d.status = 'draft' "
            "RETURN d.title as title, d.slug as slug, d.category as category, "
            "  d.parent_slug as parent_slug, d.nav_order as nav_order, d.status as status "
            "ORDER BY d.nav_order, d.title",
            {},
        )

        # Group by category
        categories: dict[str, list[dict]] = {}
        for row in result.rows:
            cat = row.get("category", "general")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append({
                "title": row["title"],
                "slug": row["slug"],
                "parent_slug": row.get("parent_slug", ""),
                "status": row.get("status", "draft"),
            })

        return [{"category": cat, "pages": pages} for cat, pages in categories.items()]

    # ------------------------------------------------------------------ #
    #  Search                                                              #
    # ------------------------------------------------------------------ #

    async def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across doc pages."""
        result = await self._driver.execute_read(
            "MATCH (d:_DocPage) "
            "WHERE toLower(d.title) CONTAINS toLower($q) "
            "   OR toLower(d.content) CONTAINS toLower($q) "
            "   OR toLower(d.summary) CONTAINS toLower($q) "
            "RETURN d.title as title, d.slug as slug, d.summary as summary, "
            "  d.category as category "
            "ORDER BY CASE WHEN toLower(d.title) CONTAINS toLower($q) THEN 0 ELSE 1 END "
            "LIMIT $limit",
            {"q": query, "limit": limit},
        )
        return [dict(row) for row in result.rows]

    # ------------------------------------------------------------------ #
    #  Knowledge graph links                                               #
    # ------------------------------------------------------------------ #

    async def _link_to_schema(self, page_id: str, page_data: dict[str, Any]) -> None:
        """Create knowledge graph edges from doc page to schema entities."""
        import json

        # Link to node types
        node_types = page_data.get("related_node_types", [])
        if isinstance(node_types, str):
            try:
                node_types = json.loads(node_types)
            except Exception:
                node_types = []

        for nt in node_types:
            await self._driver.execute_write(
                "MATCH (d:_DocPage {id: $page_id}) "
                "MERGE (d)-[:DOCUMENTS]->(ref:_DocReference {ref_type: 'node_type', ref_name: $name}) ",
                {"page_id": page_id, "name": nt},
            )

        # Link to edge types
        edge_types = page_data.get("related_edge_types", [])
        if isinstance(edge_types, str):
            try:
                edge_types = json.loads(edge_types)
            except Exception:
                edge_types = []

        for et in edge_types:
            await self._driver.execute_write(
                "MATCH (d:_DocPage {id: $page_id}) "
                "MERGE (d)-[:DOCUMENTS]->(ref:_DocReference {ref_type: 'edge_type', ref_name: $name}) ",
                {"page_id": page_id, "name": et},
            )

    async def get_docs_for_schema_item(self, item_type: str, item_name: str) -> list[dict[str, Any]]:
        """Find all doc pages that document a specific schema item."""
        result = await self._driver.execute_read(
            "MATCH (d:_DocPage)-[:DOCUMENTS]->(ref:_DocReference {ref_type: $type, ref_name: $name}) "
            "RETURN d.title as title, d.slug as slug, d.summary as summary",
            {"type": item_type, "name": item_name},
        )
        return [dict(row) for row in result.rows]

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _sanitize_page(self, page: dict[str, Any]) -> dict[str, Any]:
        """Return page without full content (for list views)."""
        return {
            "id": page.get("id", ""),
            "title": page.get("title", ""),
            "slug": page.get("slug", ""),
            "summary": page.get("summary", ""),
            "category": page.get("category", ""),
            "status": page.get("status", "draft"),
            "nav_order": page.get("nav_order", 999),
            "parent_slug": page.get("parent_slug", ""),
            "author": page.get("author", ""),
            "updated_at": page.get("updated_at", ""),
            "version": page.get("version", 1),
        }
