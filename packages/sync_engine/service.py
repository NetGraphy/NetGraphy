"""Git sync service — manages content synchronization from Git repos.

Handles repo registration, branch pinning, webhook/polling sync,
content validation, diff preview, and transactional application.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

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
    auth_type: AuthType = AuthType.TOKEN
    auth_secret_ref: str | None = None
    sync_mode: SyncMode = SyncMode.POLLING
    poll_interval_seconds: int = 300
    auto_apply: bool = False
    content_mappings: list[dict[str, str]] = field(default_factory=list)
    last_sync_at: datetime | None = None
    last_sync_commit: str | None = None


@dataclass
class SyncDiff:
    """Preview of changes that would be applied by a sync."""
    additions: list[dict[str, Any]]
    modifications: list[dict[str, Any]]
    deletions: list[dict[str, Any]]
    validation_errors: list[str]
    warnings: list[str]


@dataclass
class SyncResult:
    """Result of a sync operation."""
    source_id: str
    status: str  # "success", "failed", "partial"
    commit_sha: str
    changes_applied: int
    errors: list[str]
    started_at: datetime
    completed_at: datetime


class SyncService:
    """Orchestrates Git content synchronization.

    Sync process:
    1. Clone/fetch latest from registered repo and branch
    2. Identify changed files by content domain
    3. Validate each changed file against its domain schema
    4. Generate diff preview
    5. If auto_apply or approved: apply changes transactionally
    6. Record sync event in audit log
    7. Emit sync.completed event
    """

    def __init__(self, schema_registry, graph_driver):
        self._registry = schema_registry
        self._driver = graph_driver
        self._sources: dict[str, GitSource] = {}

    async def register_source(self, source: GitSource) -> GitSource:
        """Register a new Git source."""
        self._sources[source.id] = source
        # TODO: Persist to database
        logger.info("Git source registered", source=source.name, url=source.url)
        return source

    async def sync(self, source_id: str) -> SyncResult:
        """Execute a sync for a registered source."""
        source = self._sources.get(source_id)
        if not source:
            raise ValueError(f"Unknown source: {source_id}")

        started_at = datetime.utcnow()

        # Clone/fetch into temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_path = Path(tmpdir) / "repo"
            await self._clone_repo(source, clone_path)

            # Get current commit
            commit_sha = self._get_head_commit(clone_path)

            # Process each content domain
            changes_applied = 0
            errors = []

            for mapping in source.content_mappings:
                domain = ContentDomain(mapping["domain"])
                path = clone_path / mapping["path"]

                if not path.exists():
                    logger.warning("Content path not found", path=str(path), domain=domain)
                    continue

                try:
                    count = await self._apply_domain(domain, path)
                    changes_applied += count
                except Exception as e:
                    errors.append(f"{domain}: {e}")

        # Update source state
        source.last_sync_at = datetime.utcnow()
        source.last_sync_commit = commit_sha

        result = SyncResult(
            source_id=source_id,
            status="success" if not errors else "partial",
            commit_sha=commit_sha,
            changes_applied=changes_applied,
            errors=errors,
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

        # TODO: Emit sync.completed event via NATS
        logger.info("Sync completed", source=source.name, **result.__dict__)
        return result

    async def preview(self, source_id: str) -> SyncDiff:
        """Preview changes that would be applied without actually applying."""
        # TODO: Clone, diff against current state, return preview
        return SyncDiff(
            additions=[], modifications=[], deletions=[],
            validation_errors=[], warnings=[],
        )

    async def _clone_repo(self, source: GitSource, target: Path) -> None:
        """Clone a Git repo to a local path."""
        # TODO: Handle auth types (token, SSH, GitHub App)
        cmd = ["git", "clone", "--depth", "1", "--branch", source.branch, source.url, str(target)]
        subprocess.run(cmd, check=True, capture_output=True)

    def _get_head_commit(self, repo_path: Path) -> str:
        """Get the HEAD commit SHA."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    async def _apply_domain(self, domain: ContentDomain, path: Path) -> int:
        """Apply content from a domain directory."""
        if domain == ContentDomain.SCHEMAS:
            return await self._apply_schemas(path)
        elif domain == ContentDomain.QUERIES:
            return await self._apply_queries(path)
        elif domain == ContentDomain.PARSERS:
            return await self._apply_parsers(path)
        # TODO: Implement other domains
        return 0

    async def _apply_schemas(self, path: Path) -> int:
        """Load schema files and update the registry."""
        from packages.schema_engine.loaders.yaml_loader import load_directory
        definitions = load_directory(path)
        for defn in definitions:
            self._registry._register(defn)
        self._registry._resolve_mixins()
        self._registry._validate_references()
        return len(definitions)

    async def _apply_queries(self, path: Path) -> int:
        """Load saved queries from YAML files."""
        # TODO: Parse query YAML files and upsert into saved queries store
        return 0

    async def _apply_parsers(self, path: Path) -> int:
        """Load parser templates from directory."""
        # TODO: Register TextFSM templates
        return 0
