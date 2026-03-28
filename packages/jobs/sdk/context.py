"""Job SDK — context and result types for job implementations.

Jobs receive a JobContext with everything they need: graph access,
parameters, logging, secrets, and artifact storage. This SDK is the
contract between the job framework and job implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

import structlog


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class JobResult:
    """Result returned by a job execution."""
    status: JobStatus = JobStatus.SUCCESS
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)  # Object storage keys


class ArtifactStore(Protocol):
    """Protocol for artifact storage."""

    async def store(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store an artifact and return the storage key."""
        ...

    async def retrieve(self, key: str) -> bytes:
        """Retrieve an artifact by key."""
        ...


class ProgressReporter(Protocol):
    """Protocol for reporting job progress."""

    async def report(self, current: int, total: int, message: str = "") -> None:
        """Report progress (e.g., 45/100 devices processed)."""
        ...


@dataclass
class JobContext:
    """Context provided to job implementations at runtime.

    Contains everything a job needs to interact with the platform:
    - params: validated job parameters from the execution request
    - graph: GraphRepository for querying/mutating the graph
    - logger: structured logger bound with job metadata
    - secrets: injected secrets from Vault or environment
    - artifacts: storage helper for job artifacts
    - progress: progress reporting helper
    """
    params: dict[str, Any]
    graph: Any  # GraphRepository — typed as Any to avoid circular imports
    logger: structlog.BoundLogger
    secrets: dict[str, str]
    artifacts: ArtifactStore
    progress: ProgressReporter
    job_name: str = ""
    execution_id: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class JobManifest:
    """Job manifest loaded from YAML."""
    name: str
    display_name: str
    description: str
    runtime: str  # "python" or "go"
    entrypoint: str
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedule: dict[str, Any] | None = None
    execution: dict[str, Any] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    @property
    def timeout_seconds(self) -> int:
        return self.execution.get("timeout_seconds", 3600)

    @property
    def max_retries(self) -> int:
        return self.execution.get("max_retries", 0)

    @property
    def concurrency_limit(self) -> int:
        return self.execution.get("concurrency_limit", 10)
