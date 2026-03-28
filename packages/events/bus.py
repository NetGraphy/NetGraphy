"""Event bus -- NATS JetStream integration for durable event streams.

Provides the central EventBus class that underpins all inter-service
communication in NetGraphy.  When a NATS server is available, events are
published to JetStream streams for durability and replay.  When NATS is
unavailable the bus degrades gracefully to local-only dispatch so that
single-process deployments and test suites continue to work.

Event types follow a dot-delimited hierarchy:

- schema.changed, schema.migrated
- data.created.{node_type}, data.updated.{node_type}, data.deleted.{node_type}
- edge.created.{edge_type}, edge.deleted.{edge_type}
- query.executed
- sync.completed, sync.failed
- job.started, job.completed, job.failed
- audit.{action}
- ingestion.completed
"""

from __future__ import annotations

import fnmatch
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Stream configuration table
# ---------------------------------------------------------------------------

_STREAM_CONFIGS: list[dict[str, Any]] = [
    {
        "name": "AUDIT",
        "subjects": ["netgraphy.audit.>"],
        "max_age_days": 90,
        "description": "Immutable audit trail of all mutations",
    },
    {
        "name": "DATA",
        "subjects": ["netgraphy.data.>"],
        "max_age_days": 7,
        "description": "Node and edge lifecycle events",
    },
    {
        "name": "SCHEMA",
        "subjects": ["netgraphy.schema.>"],
        "max_age_days": 30,
        "description": "Schema evolution events",
    },
    {
        "name": "JOBS",
        "subjects": ["netgraphy.jobs.>"],
        "max_age_days": 30,
        "description": "Background job lifecycle events",
    },
    {
        "name": "SYNC",
        "subjects": ["netgraphy.sync.>"],
        "max_age_days": 30,
        "description": "External source synchronisation events",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nanoseconds(days: int) -> int:
    """Convert days to nanoseconds (NATS max_age unit)."""
    return int(timedelta(days=days).total_seconds() * 1_000_000_000)


def _serialize_datetime(obj: Any) -> Any:
    """JSON serialiser fallback for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _event_to_json(event: Event) -> bytes:
    """Serialise an Event to a UTF-8 JSON byte string."""
    data = asdict(event)
    return json.dumps(data, default=_serialize_datetime, separators=(",", ":")).encode("utf-8")


def _event_to_subject(event: Event) -> str:
    """Derive the NATS subject from an event type.

    Event types use dots as separators already.  We prefix with the
    ``netgraphy.`` namespace so that JetStream subjects match the
    configured stream filters.

    Example::

        "data.created.Device" -> "netgraphy.data.created.Device"
    """
    return f"netgraphy.{event.event_type}"


def _event_headers(event: Event) -> dict[str, str]:
    """Build NATS message headers from event metadata."""
    headers: dict[str, str] = {
        "Nats-Msg-Id": event.correlation_id,
        "NetGraphy-Event-Type": event.event_type,
        "NetGraphy-Actor": event.actor,
        "NetGraphy-Tenant": event.tenant,
        "NetGraphy-Timestamp": event.timestamp.isoformat(),
    }
    return headers


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass
class Event:
    """Envelope for all platform events.

    Parameters
    ----------
    event_type:
        Dot-delimited event type (e.g. ``data.created.Device``).
    timestamp:
        When the event occurred.  Defaults to *now* in UTC.
    actor:
        Identity of the user or system component that triggered the event.
    payload:
        Arbitrary event-specific data.
    correlation_id:
        Groups related events together.  Auto-generated UUID4 when left
        empty.
    tenant:
        Tenant scope for multi-tenancy.
    """

    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    tenant: str = "default"

    def __post_init__(self) -> None:
        if not self.correlation_id:
            self.correlation_id = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """NATS JetStream-backed event bus with local-only fallback.

    The bus operates in two modes:

    1. **Connected** -- events are published to NATS JetStream *and*
       dispatched to local in-process subscribers.
    2. **Local-only** -- when ``connect()`` has not been called or the
       NATS server is unreachable, events are dispatched to local
       subscribers only.  A warning is logged on the first publish so
       operators can diagnose connectivity issues.

    Usage::

        bus = EventBus()
        await bus.connect("nats://localhost:4222")
        await bus.emit_node_created("Device", "dev-1", actor="admin")
        await bus.close()
    """

    def __init__(self) -> None:
        self._nc: Any | None = None  # nats.aio.client.Client
        self._js: Any | None = None  # nats.js.JetStreamContext
        self._subscribers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._js_subscriptions: list[Any] = []
        self._connected: bool = False
        self._warned_disconnected: bool = False

    # -- connection management ----------------------------------------------

    async def connect(self, nats_url: str = "nats://localhost:4222") -> None:
        """Connect to NATS and initialise JetStream streams.

        If the connection fails the bus logs a warning and continues in
        local-only mode -- no exception is raised to the caller.
        """
        try:
            import nats  # noqa: F811

            self._nc = await nats.connect(
                nats_url,
                max_reconnect_attempts=-1,  # unlimited reconnect
                reconnect_time_wait=2,  # seconds between retries
                error_cb=self._on_error,
                disconnected_cb=self._on_disconnected,
                reconnected_cb=self._on_reconnected,
                closed_cb=self._on_closed,
            )
            self._js = self._nc.jetstream()
            self._connected = True
            logger.info("event_bus.connected", url=nats_url)
            await self._ensure_streams()
        except Exception as exc:
            self._nc = None
            self._js = None
            self._connected = False
            logger.warning(
                "event_bus.connect_failed",
                url=nats_url,
                error=str(exc),
                hint="Falling back to local-only event dispatch",
            )

    async def close(self) -> None:
        """Drain outstanding messages and close the NATS connection."""
        for sub in self._js_subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._js_subscriptions.clear()

        if self._nc and not self._nc.is_closed:
            try:
                await self._nc.drain()
            except Exception as exc:
                logger.warning("event_bus.drain_error", error=str(exc))
            finally:
                self._connected = False
                self._nc = None
                self._js = None
        logger.info("event_bus.closed")

    # -- NATS callbacks -----------------------------------------------------

    async def _on_error(self, exc: Exception) -> None:
        logger.error("event_bus.nats_error", error=str(exc))

    async def _on_disconnected(self) -> None:
        self._connected = False
        logger.warning("event_bus.disconnected")

    async def _on_reconnected(self) -> None:
        self._connected = True
        logger.info("event_bus.reconnected")

    async def _on_closed(self) -> None:
        self._connected = False
        logger.info("event_bus.nats_closed")

    # -- stream provisioning ------------------------------------------------

    async def _ensure_streams(self) -> None:
        """Create or update JetStream streams defined in ``_STREAM_CONFIGS``.

        This is idempotent -- existing streams are updated to match the
        desired configuration.
        """
        if not self._js:
            return

        from nats.js.api import StreamConfig, RetentionPolicy

        for cfg in _STREAM_CONFIGS:
            stream_config = StreamConfig(
                name=cfg["name"],
                subjects=cfg["subjects"],
                retention=RetentionPolicy.LIMITS,
                max_age=_nanoseconds(cfg["max_age_days"]),
                description=cfg["description"],
            )
            try:
                await self._js.find_stream_info_by_subject(cfg["subjects"][0])
                # Stream exists -- update to desired config.
                await self._js.update_stream(stream_config)
                logger.debug("event_bus.stream_updated", stream=cfg["name"])
            except Exception:
                # Stream does not exist -- create.
                try:
                    await self._js.add_stream(stream_config)
                    logger.info("event_bus.stream_created", stream=cfg["name"])
                except Exception as exc:
                    logger.error(
                        "event_bus.stream_create_failed",
                        stream=cfg["name"],
                        error=str(exc),
                    )

    # -- publishing ---------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Publish an event to NATS (if connected) and local subscribers.

        Publishing to NATS is fire-and-forget: failures are logged but
        never raised to the caller.
        """
        # Attempt NATS publish (non-blocking best-effort).
        if self._connected and self._js:
            try:
                subject = _event_to_subject(event)
                payload = _event_to_json(event)
                headers = _event_headers(event)
                await self._js.publish(subject, payload, headers=headers)
                logger.debug(
                    "event_bus.published",
                    event_type=event.event_type,
                    subject=subject,
                )
            except Exception as exc:
                logger.warning(
                    "event_bus.publish_failed",
                    event_type=event.event_type,
                    error=str(exc),
                )
        else:
            if not self._warned_disconnected:
                logger.warning(
                    "event_bus.local_only",
                    hint="NATS not connected; dispatching to local subscribers only",
                )
                self._warned_disconnected = True

        # Always dispatch to local subscribers.
        await self._dispatch_local(event)

    async def _dispatch_local(self, event: Event) -> None:
        """Invoke every matching local handler for *event*.

        Patterns registered via :meth:`subscribe` are matched using
        ``fnmatch``-style wildcards so that subscribers can listen to
        broad categories (e.g. ``data.created.*``).
        """
        for pattern, handlers in self._subscribers.items():
            if fnmatch.fnmatch(event.event_type, pattern):
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception as exc:
                        logger.error(
                            "event_bus.handler_error",
                            handler=getattr(handler, "__name__", repr(handler)),
                            event_type=event.event_type,
                            error=str(exc),
                        )

    # -- subscribing --------------------------------------------------------

    def subscribe(
        self,
        event_pattern: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        """Register a local in-process handler for events matching *event_pattern*.

        The pattern supports ``fnmatch``-style wildcards::

            bus.subscribe("data.created.*", on_node_created)
            bus.subscribe("schema.*", on_schema_event)

        Parameters
        ----------
        event_pattern:
            Glob-style pattern matched against ``Event.event_type``.
        handler:
            Async callable receiving a single :class:`Event` argument.
        """
        self._subscribers.setdefault(event_pattern, []).append(handler)
        logger.debug("event_bus.subscribed", pattern=event_pattern, handler=handler.__name__)

    async def subscribe_jetstream(
        self,
        stream: str,
        subject: str,
        durable_name: str,
        handler: Callable[[Event], Awaitable[None]],
    ) -> None:
        """Create a JetStream push subscription with a durable consumer.

        Messages are deserialised into :class:`Event` objects before
        being passed to *handler*.

        Parameters
        ----------
        stream:
            JetStream stream name (e.g. ``"DATA"``).
        subject:
            NATS subject filter (e.g. ``"netgraphy.data.created.>"``).
        durable_name:
            Durable consumer name for resumable delivery.
        handler:
            Async callable receiving a single :class:`Event` argument.

        Raises
        ------
        RuntimeError
            If the bus is not connected to NATS.
        """
        if not self._connected or not self._js:
            raise RuntimeError(
                "Cannot create JetStream subscription: NATS is not connected"
            )

        async def _msg_handler(msg: Any) -> None:
            try:
                data = json.loads(msg.data.decode("utf-8"))
                # Re-hydrate timestamp from ISO string.
                if "timestamp" in data and isinstance(data["timestamp"], str):
                    data["timestamp"] = datetime.fromisoformat(data["timestamp"])
                event = Event(**data)
                await handler(event)
                await msg.ack()
            except Exception as exc:
                logger.error(
                    "event_bus.jetstream_handler_error",
                    subject=subject,
                    durable=durable_name,
                    error=str(exc),
                )
                # NAK so the message can be redelivered.
                try:
                    await msg.nak()
                except Exception:
                    pass

        sub = await self._js.subscribe(
            subject,
            stream=stream,
            durable=durable_name,
            cb=_msg_handler,
        )
        self._js_subscriptions.append(sub)
        logger.info(
            "event_bus.jetstream_subscribed",
            stream=stream,
            subject=subject,
            durable=durable_name,
        )

    # -- convenience emitters -----------------------------------------------

    async def emit_schema_changed(self, changes: list[dict[str, Any]]) -> None:
        """Emit a schema change event."""
        await self.publish(Event(
            event_type="schema.changed",
            payload={"changes": changes},
        ))

    async def emit_node_created(
        self,
        node_type: str,
        node_id: str,
        actor: str = "system",
    ) -> None:
        """Emit a node creation event."""
        await self.publish(Event(
            event_type=f"data.created.{node_type}",
            actor=actor,
            payload={"node_type": node_type, "node_id": node_id},
        ))

    async def emit_node_updated(
        self,
        node_type: str,
        node_id: str,
        changes: dict[str, Any],
        actor: str = "system",
    ) -> None:
        """Emit a node update event with a diff of what changed."""
        await self.publish(Event(
            event_type=f"data.updated.{node_type}",
            actor=actor,
            payload={"node_type": node_type, "node_id": node_id, "changes": changes},
        ))

    async def emit_node_deleted(
        self,
        node_type: str,
        node_id: str,
        actor: str = "system",
    ) -> None:
        """Emit a node deletion event."""
        await self.publish(Event(
            event_type=f"data.deleted.{node_type}",
            actor=actor,
            payload={"node_type": node_type, "node_id": node_id},
        ))

    async def emit_edge_created(
        self,
        edge_type: str,
        edge_id: str,
        source_id: str,
        target_id: str,
        actor: str = "system",
    ) -> None:
        """Emit an edge creation event."""
        await self.publish(Event(
            event_type=f"edge.created.{edge_type}",
            actor=actor,
            payload={
                "edge_type": edge_type,
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
            },
        ))

    async def emit_edge_deleted(
        self,
        edge_type: str,
        edge_id: str,
        actor: str = "system",
    ) -> None:
        """Emit an edge deletion event."""
        await self.publish(Event(
            event_type=f"edge.deleted.{edge_type}",
            actor=actor,
            payload={"edge_type": edge_type, "edge_id": edge_id},
        ))

    async def emit_job_completed(
        self,
        job_name: str,
        execution_id: str,
        status: str,
    ) -> None:
        """Emit a job lifecycle event.

        The *status* value (e.g. ``"completed"``, ``"failed"``) is
        embedded in both the event type and the payload.
        """
        await self.publish(Event(
            event_type=f"jobs.{status}.{job_name}",
            payload={
                "job_name": job_name,
                "execution_id": execution_id,
                "status": status,
            },
        ))

    async def emit_sync_completed(
        self,
        source_name: str,
        status: str,
        changes_applied: int,
    ) -> None:
        """Emit a sync lifecycle event."""
        await self.publish(Event(
            event_type=f"sync.{status}.{source_name}",
            payload={
                "source_name": source_name,
                "status": status,
                "changes_applied": changes_applied,
            },
        ))

    async def emit_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        actor: str,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit an audit trail event.

        Audit events are published to the ``AUDIT`` stream which has a
        90-day retention window.
        """
        payload: dict[str, Any] = {
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
        if changes is not None:
            payload["changes"] = changes
        if metadata is not None:
            payload["metadata"] = metadata

        await self.publish(Event(
            event_type=f"audit.{action}.{resource_type}",
            actor=actor,
            payload=payload,
        ))

    # -- introspection ------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the bus has a live NATS connection."""
        return self._connected

    def __repr__(self) -> str:
        mode = "connected" if self._connected else "local-only"
        subs = sum(len(h) for h in self._subscribers.values())
        return f"<EventBus mode={mode} local_subscribers={subs}>"
