"""Git sync service — manages content synchronization from Git repos.

Handles repo registration (persisted in Neo4j as _GitSource nodes),
branch pinning, token-based auth, content domain handlers for schemas,
queries, parsers, and commands. Supports preview/diff before apply.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
import structlog

logger = structlog.get_logger()


class AuthType(str, Enum):
    TOKEN = "token"
    SSH_KEY = "ssh_key"
    GITHUB_APP = "github_app"
    DEPLOY_KEY = "deploy_key"


class SyncMode(str, Enum):
    WEBHOOK = "webhook"
    POLLING = "polling"


class ContentDomain(str, Enum):
    SCHEMAS = "schemas"
    HELPERS = "helpers"
    QUERIES = "queries"
    PARSERS = "parsers"
    COMMANDS = "commands"
    JOBS = "jobs"


@dataclass
class GitSource:
    """Registration of a Git repository as a content source."""
    id: str
    name: str
    description: str
    url: str
    branch: str = "main"
    auth_type: str = "token"
    auth_token: str | None = None
    sync_mode: str = "polling"
    poll_interval_seconds: int = 300
    auto_apply: bool = False
    content_mappings: list[dict[str, str]] = field(default_factory=list)
    last_sync_at: str | None = None
    last_sync_commit: str | None = None
    last_sync_status: str | None = None
    created_at: str | None = None
    created_by: str | None = None


@dataclass
class SyncDiff:
    """Preview of changes that would be applied by a sync."""
    additions: list[dict[str, Any]] = field(default_factory=list)
    modifications: list[dict[str, Any]] = field(default_factory=list)
    deletions: list[dict[str, Any]] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    source_id: str
    status: str  # "success", "failed", "partial"
    commit_sha: str
    changes_applied: int
    errors: list[str]
    started_at: str
    completed_at: str
    domain_results: dict[str, Any] = field(default_factory=dict)


class SyncService:
    """Orchestrates Git content synchronization.

    Git sources are persisted as _GitSource nodes in Neo4j.
    Sync events are recorded as _SyncEvent nodes.
    """

    def __init__(self, schema_registry, graph_driver, event_bus=None):
        self._registry = schema_registry
        self._driver = graph_driver
        self._events = event_bus

    # ----- Source CRUD (Neo4j persistence) --------------------------------- #

    async def register_source(self, source: GitSource) -> GitSource:
        """Register a new Git source, persisted in Neo4j."""
        source.id = source.id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        source.created_at = source.created_at or now

        props = {
            "id": source.id,
            "name": source.name,
            "description": source.description,
            "url": source.url,
            "branch": source.branch,
            "auth_type": source.auth_type,
            "sync_mode": source.sync_mode,
            "poll_interval_seconds": source.poll_interval_seconds,
            "auto_apply": source.auto_apply,
            "content_mappings_json": _serialize_mappings(source.content_mappings),
            "created_at": source.created_at,
            "created_by": source.created_by or "system",
        }
        # Don't store auth tokens in Neo4j properties directly
        # In production, use a secrets manager reference

        await self._driver.execute_write(
            "CREATE (s:_GitSource $props) RETURN s", {"props": props}
        )
        logger.info("Git source registered", source=source.name, url=source.url)
        return source

    async def get_source(self, source_id: str) -> GitSource | None:
        """Get a Git source by ID."""
        result = await self._driver.execute_read(
            "MATCH (s:_GitSource {id: $id}) RETURN s", {"id": source_id}
        )
        if not result.rows:
            return None
        return _node_to_source(result.rows[0]["s"])

    async def list_sources(self) -> list[dict]:
        """List all registered Git sources."""
        result = await self._driver.execute_read(
            "MATCH (s:_GitSource) RETURN s ORDER BY s.name", {}
        )
        return [_node_to_source_dict(row["s"]) for row in result.rows]

    async def delete_source(self, source_id: str) -> bool:
        """Delete a Git source registration."""
        result = await self._driver.execute_write(
            "MATCH (s:_GitSource {id: $id}) DETACH DELETE s RETURN count(s) as deleted",
            {"id": source_id},
        )
        return result.rows[0].get("deleted", 0) > 0 if result.rows else False

    # ----- Sync Execution -------------------------------------------------- #

    async def sync(self, source_id: str) -> SyncResult:
        """Execute a full sync for a registered source."""
        source = await self.get_source(source_id)
        if not source:
            raise ValueError(f"Unknown source: {source_id}")

        started_at = datetime.now(timezone.utc).isoformat()
        domain_results: dict[str, Any] = {}

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                clone_path = Path(tmpdir) / "repo"
                await self._clone_repo(source, clone_path)
                commit_sha = self._get_head_commit(clone_path)

                changes_applied = 0
                errors = []

                for mapping in source.content_mappings:
                    domain = mapping.get("domain", "")
                    rel_path = mapping.get("path", "")
                    full_path = clone_path / rel_path

                    if not full_path.exists():
                        logger.warning("Content path not found",
                                       path=rel_path, domain=domain)
                        continue

                    try:
                        count = await self._apply_domain(
                            ContentDomain(domain), full_path
                        )
                        changes_applied += count
                        domain_results[domain] = {"applied": count, "status": "success"}
                    except Exception as e:
                        errors.append(f"{domain}: {e}")
                        domain_results[domain] = {"applied": 0, "status": "error",
                                                  "error": str(e)}

            completed_at = datetime.now(timezone.utc).isoformat()
            status = "success" if not errors else "partial"

            # Update source record
            await self._driver.execute_write(
                "MATCH (s:_GitSource {id: $id}) "
                "SET s.last_sync_at = $sync_at, "
                "    s.last_sync_commit = $commit, "
                "    s.last_sync_status = $status "
                "RETURN s",
                {"id": source_id, "sync_at": completed_at,
                 "commit": commit_sha, "status": status},
            )

            # Record sync event
            await self._record_sync_event(
                source_id, commit_sha, status, changes_applied,
                errors, started_at, completed_at,
            )

            # Emit event
            if self._events:
                await self._events.emit_sync_completed(
                    source.name, status, changes_applied
                )

            result = SyncResult(
                source_id=source_id,
                status=status,
                commit_sha=commit_sha,
                changes_applied=changes_applied,
                errors=errors,
                started_at=started_at,
                completed_at=completed_at,
                domain_results=domain_results,
            )
            logger.info("Sync completed", source=source.name, status=status,
                        changes=changes_applied)
            return result

        except Exception as e:
            completed_at = datetime.now(timezone.utc).isoformat()
            await self._record_sync_event(
                source_id, "", "failed", 0, [str(e)], started_at, completed_at,
            )
            raise

    async def preview(self, source_id: str) -> SyncDiff:
        """Preview changes without applying — clone, parse, diff against current."""
        source = await self.get_source(source_id)
        if not source:
            raise ValueError(f"Unknown source: {source_id}")

        diff = SyncDiff()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                clone_path = Path(tmpdir) / "repo"
                await self._clone_repo(source, clone_path)

                for mapping in source.content_mappings:
                    domain = mapping.get("domain", "")
                    rel_path = mapping.get("path", "")
                    full_path = clone_path / rel_path

                    if not full_path.exists():
                        diff.warnings.append(f"Path not found: {rel_path}")
                        continue

                    try:
                        domain_diff = await self._preview_domain(
                            ContentDomain(domain), full_path
                        )
                        diff.additions.extend(domain_diff.get("additions", []))
                        diff.modifications.extend(domain_diff.get("modifications", []))
                    except Exception as e:
                        diff.validation_errors.append(f"{domain}: {e}")

        except Exception as e:
            diff.validation_errors.append(f"Clone failed: {e}")

        return diff

    async def get_sync_history(
        self, source_id: str, page: int = 1, page_size: int = 25,
    ) -> dict:
        """Get sync event history for a source."""
        skip = (page - 1) * page_size
        count_result = await self._driver.execute_read(
            "MATCH (e:_SyncEvent {source_id: $id}) RETURN count(e) as total",
            {"id": source_id},
        )
        total = count_result.rows[0]["total"] if count_result.rows else 0

        data_result = await self._driver.execute_read(
            "MATCH (e:_SyncEvent {source_id: $id}) "
            "RETURN e ORDER BY e.started_at DESC SKIP $skip LIMIT $limit",
            {"id": source_id, "skip": skip, "limit": page_size},
        )
        items = [row.get("e", {}) for row in data_result.rows]

        return {
            "data": items,
            "meta": {"total_count": total, "page": page, "page_size": page_size},
        }

    # ----- Domain Handlers ------------------------------------------------- #

    async def _apply_domain(self, domain: ContentDomain, path: Path) -> int:
        """Dispatch to the appropriate domain handler."""
        handlers = {
            ContentDomain.SCHEMAS: self._apply_schemas,
            ContentDomain.QUERIES: self._apply_queries,
            ContentDomain.PARSERS: self._apply_parsers,
            ContentDomain.COMMANDS: self._apply_commands,
            ContentDomain.HELPERS: self._apply_helpers,
        }
        handler = handlers.get(domain)
        if not handler:
            logger.warning("No handler for domain", domain=domain.value)
            return 0
        return await handler(path)

    async def _apply_schemas(self, path: Path) -> int:
        """Load schema YAML files and update the registry."""
        from packages.schema_engine.loaders.yaml_loader import load_directory
        definitions = load_directory(path)
        for defn in definitions:
            self._registry._register(defn)
        self._registry._resolve_mixins()
        self._registry._validate_references()
        logger.info("Schemas synced", count=len(definitions), path=str(path))
        return len(definitions)

    async def _apply_queries(self, path: Path) -> int:
        """Load saved query YAML files and upsert as SavedQuery nodes."""
        count = 0
        for yaml_file in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
            try:
                with open(yaml_file) as f:
                    docs = list(yaml.safe_load_all(f))
                for doc in docs:
                    if not doc or doc.get("kind") != "SavedQuery":
                        continue
                    meta = doc.get("metadata", {})
                    query_text = doc.get("query", "")
                    params_schema = doc.get("parameters", {})
                    name = meta.get("name", yaml_file.stem)

                    await self._driver.execute_write(
                        "MERGE (q:SavedQuery {name: $name}) "
                        "SET q.display_name = $display_name, "
                        "    q.description = $description, "
                        "    q.query = $query, "
                        "    q.parameters_schema = $params, "
                        "    q.tags = $tags, "
                        "    q.managed_by = 'git', "
                        "    q.updated_at = $now "
                        "ON CREATE SET q.id = $id, q.created_at = $now "
                        "RETURN q",
                        {
                            "name": name,
                            "display_name": meta.get("display_name", name),
                            "description": meta.get("description", ""),
                            "query": query_text,
                            "params": str(params_schema),
                            "tags": meta.get("tags", []),
                            "now": datetime.now(timezone.utc).isoformat(),
                            "id": str(uuid.uuid4()),
                        },
                    )
                    count += 1
            except Exception as e:
                logger.warning("Failed to load query file", file=str(yaml_file), error=str(e))
        logger.info("Queries synced", count=count, path=str(path))
        return count

    async def _apply_parsers(self, path: Path) -> int:
        """Load TextFSM templates and register in Neo4j."""
        count = 0
        # Register .textfsm template files
        for template_file in sorted(path.rglob("*.textfsm")):
            try:
                content = template_file.read_text()
                name = template_file.stem

                await self._driver.execute_write(
                    "MERGE (p:_Parser {name: $name}) "
                    "SET p.template = $template, "
                    "    p.managed_by = 'git', "
                    "    p.updated_at = $now "
                    "ON CREATE SET p.id = $id, p.created_at = $now "
                    "RETURN p",
                    {
                        "name": name,
                        "template": content,
                        "now": datetime.now(timezone.utc).isoformat(),
                        "id": str(uuid.uuid4()),
                    },
                )
                count += 1
            except Exception as e:
                logger.warning("Failed to register parser", file=str(template_file), error=str(e))
        logger.info("Parsers synced", count=count, path=str(path))
        return count

    async def _apply_commands(self, path: Path) -> int:
        """Load command bundle YAML files and register."""
        count = 0
        for yaml_file in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
            try:
                with open(yaml_file) as f:
                    doc = yaml.safe_load(f)
                if not doc or doc.get("kind") != "CommandBundle":
                    continue
                meta = doc.get("metadata", {})
                name = meta.get("name", yaml_file.stem)

                await self._driver.execute_write(
                    "MERGE (cb:_CommandBundle {name: $name}) "
                    "SET cb.platform = $platform, "
                    "    cb.description = $description, "
                    "    cb.commands_json = $commands, "
                    "    cb.managed_by = 'git', "
                    "    cb.updated_at = $now "
                    "ON CREATE SET cb.id = $id, cb.created_at = $now "
                    "RETURN cb",
                    {
                        "name": name,
                        "platform": meta.get("platform", ""),
                        "description": meta.get("description", ""),
                        "commands": str(doc.get("commands", [])),
                        "now": datetime.now(timezone.utc).isoformat(),
                        "id": str(uuid.uuid4()),
                    },
                )
                count += 1
            except Exception as e:
                logger.warning("Failed to register command bundle",
                               file=str(yaml_file), error=str(e))
        logger.info("Command bundles synced", count=count, path=str(path))
        return count

    async def _apply_helpers(self, path: Path) -> int:
        """Load helper/reference data YAML files and upsert as nodes."""
        count = 0
        for yaml_file in sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml")):
            try:
                with open(yaml_file) as f:
                    docs = list(yaml.safe_load_all(f))
                for doc in docs:
                    if not doc or "kind" not in doc:
                        continue
                    node_type = doc.get("kind")
                    data = doc.get("data", {})
                    name = data.get("name") or data.get("hostname") or yaml_file.stem

                    match_field = "name" if "name" in data else "hostname"
                    await self._driver.execute_write(
                        f"MERGE (n:{node_type} {{{match_field}: $match_val}}) "
                        f"SET n += $props, n.managed_by = 'git', n.updated_at = $now "
                        f"ON CREATE SET n.id = $id, n.created_at = $now "
                        f"RETURN n",
                        {
                            "match_val": name,
                            "props": data,
                            "now": datetime.now(timezone.utc).isoformat(),
                            "id": str(uuid.uuid4()),
                        },
                    )
                    count += 1
            except Exception as e:
                logger.warning("Failed to load helper data",
                               file=str(yaml_file), error=str(e))
        logger.info("Helpers synced", count=count, path=str(path))
        return count

    async def _preview_domain(
        self, domain: ContentDomain, path: Path,
    ) -> dict[str, list]:
        """Generate a preview diff for a content domain."""
        additions = []
        modifications = []

        if domain == ContentDomain.SCHEMAS:
            from packages.schema_engine.loaders.yaml_loader import load_directory
            definitions = load_directory(path)
            for defn in definitions:
                name = defn.name
                existing = (self._registry.get_node_type(name)
                            or self._registry.get_edge_type(name)
                            or self._registry.get_mixin(name))
                entry = {"domain": domain.value, "name": name, "kind": defn.kind}
                if existing:
                    modifications.append(entry)
                else:
                    additions.append(entry)

        elif domain == ContentDomain.QUERIES:
            for yaml_file in sorted(path.rglob("*.yaml")):
                with open(yaml_file) as f:
                    docs = list(yaml.safe_load_all(f))
                for doc in (d for d in docs if d and d.get("kind") == "SavedQuery"):
                    name = doc.get("metadata", {}).get("name", yaml_file.stem)
                    result = await self._driver.execute_read(
                        "MATCH (q:SavedQuery {name: $name}) RETURN q",
                        {"name": name},
                    )
                    entry = {"domain": "queries", "name": name, "kind": "SavedQuery"}
                    if result.rows:
                        modifications.append(entry)
                    else:
                        additions.append(entry)

        elif domain == ContentDomain.PARSERS:
            for template_file in sorted(path.rglob("*.textfsm")):
                name = template_file.stem
                result = await self._driver.execute_read(
                    "MATCH (p:_Parser {name: $name}) RETURN p",
                    {"name": name},
                )
                entry = {"domain": "parsers", "name": name, "kind": "Parser"}
                if result.rows:
                    modifications.append(entry)
                else:
                    additions.append(entry)

        return {"additions": additions, "modifications": modifications}

    # ----- Internals ------------------------------------------------------- #

    async def _clone_repo(self, source: GitSource, target: Path) -> None:
        """Clone a Git repo. Supports token auth via URL embedding."""
        url = source.url
        if source.auth_token and source.auth_type == "token":
            # Embed token for HTTPS clones: https://<token>@github.com/...
            if url.startswith("https://"):
                url = url.replace("https://", f"https://{source.auth_token}@")

        cmd = [
            "git", "clone", "--depth", "1",
            "--branch", source.branch,
            url, str(target),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"Git clone failed: {proc.stderr.strip()}")

    def _get_head_commit(self, repo_path: Path) -> str:
        """Get the HEAD commit SHA."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True, text=True,
        )
        return result.stdout.strip()

    async def _record_sync_event(
        self, source_id: str, commit_sha: str, status: str,
        changes: int, errors: list[str], started_at: str, completed_at: str,
    ) -> None:
        """Record a sync event in Neo4j."""
        await self._driver.execute_write(
            "CREATE (e:_SyncEvent $props) RETURN e",
            {"props": {
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "commit_sha": commit_sha,
                "status": status,
                "changes_applied": changes,
                "errors": errors,
                "started_at": started_at,
                "completed_at": completed_at,
            }},
        )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _serialize_mappings(mappings: list[dict[str, str]]) -> str:
    """Serialize content mappings to JSON string for Neo4j storage."""
    import json
    return json.dumps(mappings)


def _deserialize_mappings(json_str: str) -> list[dict[str, str]]:
    """Deserialize content mappings from JSON string."""
    import json
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []


def _node_to_source(node: dict) -> GitSource:
    """Convert a Neo4j _GitSource node dict to a GitSource dataclass."""
    return GitSource(
        id=node.get("id", ""),
        name=node.get("name", ""),
        description=node.get("description", ""),
        url=node.get("url", ""),
        branch=node.get("branch", "main"),
        auth_type=node.get("auth_type", "token"),
        sync_mode=node.get("sync_mode", "polling"),
        poll_interval_seconds=node.get("poll_interval_seconds", 300),
        auto_apply=node.get("auto_apply", False),
        content_mappings=_deserialize_mappings(node.get("content_mappings_json", "[]")),
        last_sync_at=node.get("last_sync_at"),
        last_sync_commit=node.get("last_sync_commit"),
        last_sync_status=node.get("last_sync_status"),
        created_at=node.get("created_at"),
        created_by=node.get("created_by"),
    )


def _node_to_source_dict(node: dict) -> dict:
    """Convert to a serializable dict for API responses."""
    source = _node_to_source(node)
    return {
        "id": source.id,
        "name": source.name,
        "description": source.description,
        "url": source.url,
        "branch": source.branch,
        "auth_type": source.auth_type,
        "sync_mode": source.sync_mode,
        "auto_apply": source.auto_apply,
        "content_mappings": source.content_mappings,
        "last_sync_at": source.last_sync_at,
        "last_sync_commit": source.last_sync_commit,
        "last_sync_status": source.last_sync_status,
        "created_at": source.created_at,
    }
