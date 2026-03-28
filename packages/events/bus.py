"""Event bus — NATS JetStream integration for durable event streams.

Event types:
- schema.changed, schema.migrated
- data.created.{node_type}, data.updated.{node_type}, data.deleted.{node_type}
- edge.created.{edge_type}, edge.deleted.{edge_type}
- query.executed
- sync.completed, sync.failed
- job.started, job.completed, job.failed
- ingestion.completed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger()


@dataclass
class Event:
    """Event envelope for all platform events."""
    event_type: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    actor: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    tenant: str = "default"


class EventBus:
    """NATS-based event bus.

    Uses NATS JetStream for durable streams (audit, data changes)
    and core NATS for ephemeral notifications (UI updates, cache invalidation).
    """

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        self._nats_url = nats_url
        self._connection = None
        self._jetstream = None
        self._subscribers: dict[str, list[Callable]] = {}

    async def connect(self) -> None:
        """Connect to NATS and initialize JetStream."""
        # TODO: Import nats and establish connection
        # import nats
        # self._connection = await nats.connect(self._nats_url)
        # self._jetstream = self._connection.jetstream()
        logger.info("Event bus connected", url=self._nats_url)

    async def close(self) -> None:
        """Close the NATS connection."""
        if self._connection:
            # await self._connection.close()
            pass
        logger.info("Event bus closed")

    async def publish(self, event: Event) -> None:
        """Publish an event to the appropriate stream/subject."""
        subject = event.event_type.replace(".", "_")
        # TODO: Serialize and publish via JetStream
        logger.debug("Event published", event_type=event.event_type, subject=subject)

        # Also dispatch to local subscribers (for in-process consumers)
        for handler in self._subscribers.get(event.event_type, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error("Event handler error", handler=handler.__name__, error=str(e))

    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> None:
        """Subscribe a handler to an event type."""
        self._subscribers.setdefault(event_type, []).append(handler)

    async def emit_schema_changed(self, changes: list[dict]) -> None:
        """Convenience method for schema change events."""
        await self.publish(Event(
            event_type="schema.changed",
            payload={"changes": changes},
        ))

    async def emit_node_created(self, node_type: str, node_id: str, actor: str = "system") -> None:
        await self.publish(Event(
            event_type=f"data.created.{node_type}",
            actor=actor,
            payload={"node_type": node_type, "node_id": node_id},
        ))

    async def emit_node_updated(self, node_type: str, node_id: str, changes: dict, actor: str = "system") -> None:
        await self.publish(Event(
            event_type=f"data.updated.{node_type}",
            actor=actor,
            payload={"node_type": node_type, "node_id": node_id, "changes": changes},
        ))

    async def emit_job_completed(self, job_name: str, execution_id: str, status: str) -> None:
        await self.publish(Event(
            event_type=f"job.{status}.{job_name}",
            payload={"job_name": job_name, "execution_id": execution_id, "status": status},
        ))
