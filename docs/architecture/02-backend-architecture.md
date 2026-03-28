# 4. Detailed Backend Architecture

## 4.1 FastAPI Application Structure

### Application Factory

The application is constructed via a factory function that wires up all
dependencies before returning a fully configured `FastAPI` instance.  Every
component that requires initialisation at startup (Neo4j driver, NATS client,
schema registry, Redis pool) is created inside the factory's lifespan context
manager so that teardown is deterministic.

```python
# netgraphy/app.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from netgraphy.core.config import Settings
from netgraphy.core.deps import AppState
from netgraphy.db.neo4j import Neo4jPool
from netgraphy.events.nats import NATSClient
from netgraphy.cache.redis import RedisPool
from netgraphy.schema.registry import SchemaRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings

    # --- startup ---
    neo4j = await Neo4jPool.connect(
        uri=settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        max_connection_pool_size=settings.neo4j_pool_size,
    )
    nats = await NATSClient.connect(
        servers=settings.nats_servers,
        stream_prefix=settings.nats_stream_prefix,
    )
    redis = await RedisPool.connect(url=settings.redis_url)

    schema_registry = SchemaRegistry(neo4j=neo4j, redis=redis)
    await schema_registry.load()  # hydrate from Neo4j, cache in Redis

    app.state.ctx = AppState(
        neo4j=neo4j,
        nats=nats,
        redis=redis,
        schema_registry=schema_registry,
    )

    await nats.register_subscribers(app.state.ctx)

    yield

    # --- shutdown ---
    await nats.drain()
    await redis.close()
    await neo4j.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    app = FastAPI(
        title="NetGraphy",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    _register_middleware(app, settings)
    _register_routers(app)

    return app
```

### Router Organisation

Routers live in `netgraphy/api/routers/` and are mounted by domain.  Every
router receives its dependencies through FastAPI's `Depends()` mechanism --
never through module-level globals.

```python
# netgraphy/api/routers/__init__.py

from fastapi import APIRouter
from netgraphy.api.routers import (
    auth,
    audit,
    edges,
    ingestion,
    jobs,
    nodes,
    parsers,
    queries,
    schemas,
    sync,
)

_ROUTERS: list[tuple[str, APIRouter, str]] = [
    ("/auth",       auth.router,       "auth"),
    ("/nodes",      nodes.router,      "nodes"),
    ("/edges",      edges.router,      "edges"),
    ("/queries",    queries.router,    "queries"),
    ("/schemas",    schemas.router,    "schemas"),
    ("/sync",       sync.router,       "sync"),
    ("/jobs",       jobs.router,       "jobs"),
    ("/parsers",    parsers.router,    "parsers"),
    ("/ingestion",  ingestion.router,  "ingestion"),
    ("/audit",      audit.router,      "audit"),
]


def register_all(app):
    for prefix, router, tag in _ROUTERS:
        app.include_router(router, prefix=f"/api/v1{prefix}", tags=[tag])
```

An example router module:

```python
# netgraphy/api/routers/nodes.py

from fastapi import APIRouter, Depends, Query
from netgraphy.api.deps import get_node_service, get_auth_context
from netgraphy.models.domain import NodeInstance
from netgraphy.models.api import (
    NodeCreateRequest,
    NodeUpdateRequest,
    NodeListResponse,
    PaginationParams,
    FilterParams,
)

router = APIRouter()


@router.post("/{node_type}", response_model=NodeInstance, status_code=201)
async def create_node(
    node_type: str,
    body: NodeCreateRequest,
    svc=Depends(get_node_service),
    auth=Depends(get_auth_context),
):
    return await svc.create(node_type, body.properties, actor=auth)


@router.get("/{node_type}/{node_id}", response_model=NodeInstance)
async def get_node(
    node_type: str,
    node_id: str,
    svc=Depends(get_node_service),
    auth=Depends(get_auth_context),
):
    return await svc.get(node_type, node_id, actor=auth)


@router.get("/{node_type}", response_model=NodeListResponse)
async def list_nodes(
    node_type: str,
    pagination: PaginationParams = Depends(),
    filters: FilterParams = Depends(),
    svc=Depends(get_node_service),
    auth=Depends(get_auth_context),
):
    return await svc.list(node_type, filters.to_filter_set(), pagination.to_pagination(), actor=auth)
```

### Dependency Injection

All cross-cutting concerns are provided via `Depends()`.  The dependency
functions pull state from `request.app.state.ctx`, which was populated during
lifespan startup.

```python
# netgraphy/api/deps.py

from fastapi import Depends, Request
from netgraphy.core.deps import AppState
from netgraphy.services.node import NodeService
from netgraphy.services.edge import EdgeService
from netgraphy.services.query import QueryService
from netgraphy.services.schema import SchemaService
from netgraphy.auth.context import AuthContext, extract_auth_context
from netgraphy.graph.repository import GraphRepository


def get_app_state(request: Request) -> AppState:
    return request.app.state.ctx


def get_graph_repo(state: AppState = Depends(get_app_state)) -> GraphRepository:
    return GraphRepository(
        driver=state.neo4j.driver,
        schema_registry=state.schema_registry,
    )


def get_auth_context(request: Request) -> AuthContext:
    return extract_auth_context(request)


def get_node_service(
    repo: GraphRepository = Depends(get_graph_repo),
    state: AppState = Depends(get_app_state),
) -> NodeService:
    return NodeService(
        repo=repo,
        schema_registry=state.schema_registry,
        events=state.nats,
    )


def get_edge_service(
    repo: GraphRepository = Depends(get_graph_repo),
    state: AppState = Depends(get_app_state),
) -> EdgeService:
    return EdgeService(
        repo=repo,
        schema_registry=state.schema_registry,
        events=state.nats,
    )


def get_query_service(
    repo: GraphRepository = Depends(get_graph_repo),
    state: AppState = Depends(get_app_state),
) -> QueryService:
    return QueryService(
        repo=repo,
        redis=state.redis,
        events=state.nats,
    )


def get_schema_service(
    state: AppState = Depends(get_app_state),
) -> SchemaService:
    return SchemaService(
        registry=state.schema_registry,
        neo4j=state.neo4j,
        events=state.nats,
        redis=state.redis,
    )
```

### Middleware Stack

Middleware is applied in LIFO order -- the first added is the outermost wrapper.

```python
# netgraphy/core/middleware.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from netgraphy.middleware.request_id import RequestIDMiddleware
from netgraphy.middleware.audit_log import AuditLogMiddleware
from netgraphy.middleware.auth import AuthMiddleware
from netgraphy.middleware.rate_limit import RateLimitMiddleware


def register_middleware(app: FastAPI, settings) -> None:
    # outermost: assign a unique request ID to every request
    app.add_middleware(RequestIDMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # rate limiting (before auth so brute-force is throttled)
    app.add_middleware(
        RateLimitMiddleware,
        redis_url=settings.redis_url,
        rate=settings.rate_limit_per_minute,
    )

    # authentication: populates request.state.auth_context
    app.add_middleware(
        AuthMiddleware,
        jwks_url=settings.auth_jwks_url,
        audience=settings.auth_audience,
        public_paths={"/api/v1/auth/token", "/health", "/docs", "/openapi.json"},
    )

    # audit logging: records method, path, status, actor, duration
    app.add_middleware(AuditLogMiddleware)
```

`RequestIDMiddleware` generates a UUID v7 (time-sortable) for every inbound
request, stores it in `request.state.request_id`, and returns it in the
`X-Request-ID` response header.  All log records within the request lifecycle
include this correlation ID.

```python
# netgraphy/middleware/request_id.py

import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
```

### Settings Management

All configuration is loaded from environment variables and validated at
startup.  Pydantic-settings provides type coercion, defaults, and early failure
for missing required values.

```python
# netgraphy/core/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NETGRAPHY_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # application
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # neo4j
    neo4j_uri: str = "neo4j://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str  # required -- no default
    neo4j_pool_size: int = 50
    neo4j_database: str = "neo4j"

    # nats
    nats_servers: list[str] = ["nats://localhost:4222"]
    nats_stream_prefix: str = "netgraphy"

    # redis
    redis_url: str = "redis://localhost:6379/0"

    # auth
    auth_jwks_url: str = ""
    auth_audience: str = "netgraphy-api"

    # cors
    cors_origins: list[str] = ["http://localhost:3000"]

    # rate limiting
    rate_limit_per_minute: int = 300
```

---

## 4.2 Graph Repository Pattern

### Core Interface

The `GraphRepository` is the **only** code that generates Cypher.  Application
services never construct Cypher strings; they call typed methods on the
repository, and the repository delegates to a **driver adapter** that can speak
to either Neo4j's Bolt protocol or Apache AGE's SQL/Cypher bridge.

```python
# netgraphy/graph/repository.py

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from netgraphy.graph.adapters.base import DriverAdapter
from netgraphy.graph.cypher import CypherBuilder
from netgraphy.graph.types import (
    BulkResult,
    Direction,
    EdgeInstance,
    FilterSet,
    NodeInstance,
    Page,
    Pagination,
    QueryResult,
    TraversalResult,
    TraversalSpec,
    UpsertOperation,
)
from netgraphy.schema.registry import SchemaRegistry
from netgraphy.graph.exceptions import (
    SchemaValidationError,
    NodeNotFoundError,
    EdgeNotFoundError,
    CardinalityViolationError,
)


class GraphRepository:
    """
    Typed CRUD abstraction over a Cypher-compatible graph store.

    The repository:
      1. Validates every mutation against the SchemaRegistry.
      2. Generates Cypher via CypherBuilder.
      3. Executes via DriverAdapter (swappable between Neo4j and AGE).
      4. Maps raw records back to domain objects.
    """

    def __init__(
        self,
        adapter: DriverAdapter,
        schema_registry: SchemaRegistry,
    ) -> None:
        self._adapter = adapter
        self._schema = schema_registry
        self._cypher = CypherBuilder()

    # ── node CRUD ──────────────────────────────────────────────

    async def create_node(
        self, node_type: str, properties: dict[str, Any]
    ) -> NodeInstance:
        type_def = self._schema.get_node_type(node_type)
        if type_def is None:
            raise SchemaValidationError(f"Unknown node type: {node_type}")

        validated = type_def.validate_properties(properties)
        node_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        validated.update({"_id": node_id, "_created_at": now, "_updated_at": now})

        query, params = self._cypher.create_node(label=node_type, properties=validated)

        async with self._adapter.write_tx() as tx:
            record = await tx.run_single(query, params)

        return self._map_node(record, node_type)

    async def get_node(self, node_type: str, node_id: str) -> NodeInstance:
        query, params = self._cypher.match_node_by_id(
            label=node_type, node_id=node_id
        )
        async with self._adapter.read_tx() as tx:
            record = await tx.run_single(query, params)

        if record is None:
            raise NodeNotFoundError(node_type=node_type, node_id=node_id)
        return self._map_node(record, node_type)

    async def update_node(
        self, node_type: str, node_id: str, properties: dict[str, Any]
    ) -> NodeInstance:
        type_def = self._schema.get_node_type(node_type)
        if type_def is None:
            raise SchemaValidationError(f"Unknown node type: {node_type}")

        validated = type_def.validate_partial(properties)
        validated["_updated_at"] = datetime.now(timezone.utc)

        query, params = self._cypher.update_node(
            label=node_type, node_id=node_id, properties=validated
        )
        async with self._adapter.write_tx() as tx:
            record = await tx.run_single(query, params)

        if record is None:
            raise NodeNotFoundError(node_type=node_type, node_id=node_id)
        return self._map_node(record, node_type)

    async def delete_node(self, node_type: str, node_id: str) -> None:
        query, params = self._cypher.delete_node(label=node_type, node_id=node_id)
        async with self._adapter.write_tx() as tx:
            summary = await tx.run_consume(query, params)
        if summary.counters.nodes_deleted == 0:
            raise NodeNotFoundError(node_type=node_type, node_id=node_id)

    async def list_nodes(
        self,
        node_type: str,
        filters: FilterSet,
        pagination: Pagination,
    ) -> Page[NodeInstance]:
        self._schema.require_node_type(node_type)

        count_q, count_p = self._cypher.count_nodes(label=node_type, filters=filters)
        list_q, list_p = self._cypher.list_nodes(
            label=node_type, filters=filters, pagination=pagination
        )

        async with self._adapter.read_tx() as tx:
            total = await tx.run_scalar(count_q, count_p)
            records = await tx.run_many(list_q, list_p)

        items = [self._map_node(r, node_type) for r in records]
        return Page(items=items, total=total, pagination=pagination)

    # ── edge CRUD ──────────────────────────────────────────────

    async def create_edge(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any],
    ) -> EdgeInstance:
        type_def = self._schema.get_edge_type(edge_type)
        if type_def is None:
            raise SchemaValidationError(f"Unknown edge type: {edge_type}")

        validated = type_def.validate_properties(properties)
        edge_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        validated.update({"_id": edge_id, "_created_at": now})

        # enforce cardinality constraints before creating
        await self._enforce_cardinality(type_def, source_id, target_id)

        query, params = self._cypher.create_edge(
            rel_type=edge_type,
            source_id=source_id,
            target_id=target_id,
            properties=validated,
        )
        async with self._adapter.write_tx() as tx:
            record = await tx.run_single(query, params)

        return self._map_edge(record, edge_type)

    async def get_edges(
        self, node_id: str, edge_type: str | None, direction: Direction
    ) -> list[EdgeInstance]:
        query, params = self._cypher.match_edges(
            node_id=node_id, rel_type=edge_type, direction=direction
        )
        async with self._adapter.read_tx() as tx:
            records = await tx.run_many(query, params)
        return [self._map_edge(r, edge_type or r["type"]) for r in records]

    async def delete_edge(self, edge_type: str, edge_id: str) -> None:
        query, params = self._cypher.delete_edge(rel_type=edge_type, edge_id=edge_id)
        async with self._adapter.write_tx() as tx:
            summary = await tx.run_consume(query, params)
        if summary.counters.relationships_deleted == 0:
            raise EdgeNotFoundError(edge_type=edge_type, edge_id=edge_id)

    # ── advanced operations ────────────────────────────────────

    async def execute_cypher(
        self, query: str, params: dict[str, Any]
    ) -> QueryResult:
        """Execute an arbitrary read-only Cypher query."""
        async with self._adapter.read_tx() as tx:
            records = await tx.run_many(query, params)
        return QueryResult(records=records)

    async def bulk_upsert(
        self, operations: list[UpsertOperation]
    ) -> BulkResult:
        """
        Apply a batch of upsert operations inside a single write transaction.
        Uses UNWIND for efficient batched writes.
        """
        node_ops = [op for op in operations if op.kind == "node"]
        edge_ops = [op for op in operations if op.kind == "edge"]

        created = updated = 0

        async with self._adapter.write_tx() as tx:
            if node_ops:
                # Group by node type for batched UNWIND queries
                by_type: dict[str, list[dict]] = {}
                for op in node_ops:
                    by_type.setdefault(op.entity_type, []).append(op.to_param_dict())

                for label, batch in by_type.items():
                    self._schema.require_node_type(label)
                    query, params = self._cypher.bulk_merge_nodes(label=label, batch=batch)
                    summary = await tx.run_consume(query, params)
                    created += summary.counters.nodes_created
                    updated += (len(batch) - summary.counters.nodes_created)

            if edge_ops:
                by_type: dict[str, list[dict]] = {}
                for op in edge_ops:
                    by_type.setdefault(op.entity_type, []).append(op.to_param_dict())

                for rel_type, batch in by_type.items():
                    self._schema.require_edge_type(rel_type)
                    query, params = self._cypher.bulk_merge_edges(rel_type=rel_type, batch=batch)
                    summary = await tx.run_consume(query, params)
                    created += summary.counters.relationships_created

        return BulkResult(created=created, updated=updated, total=len(operations))

    async def traverse(
        self, start_id: str, spec: TraversalSpec
    ) -> TraversalResult:
        query, params = self._cypher.traversal(start_id=start_id, spec=spec)
        async with self._adapter.read_tx() as tx:
            records = await tx.run_many(query, params)
        return TraversalResult.from_records(records)

    # ── cardinality enforcement ────────────────────────────────

    async def _enforce_cardinality(self, type_def, source_id: str, target_id: str):
        """Check one-to-one / one-to-many constraints before edge creation."""
        constraints = type_def.cardinality  # e.g. CardinalityConstraint(source="one", target="many")
        if constraints is None:
            return

        if constraints.source_max == 1:
            # target node must not already have an inbound edge of this type
            query, params = self._cypher.count_edges_to(
                rel_type=type_def.name, target_id=target_id
            )
            async with self._adapter.read_tx() as tx:
                count = await tx.run_scalar(query, params)
            if count >= 1:
                raise CardinalityViolationError(
                    edge_type=type_def.name,
                    constraint="source_max=1",
                    target_id=target_id,
                )

        if constraints.target_max == 1:
            query, params = self._cypher.count_edges_from(
                rel_type=type_def.name, source_id=source_id
            )
            async with self._adapter.read_tx() as tx:
                count = await tx.run_scalar(query, params)
            if count >= 1:
                raise CardinalityViolationError(
                    edge_type=type_def.name,
                    constraint="target_max=1",
                    source_id=source_id,
                )

    # ── mapping helpers ────────────────────────────────────────

    def _map_node(self, record: dict[str, Any], node_type: str) -> NodeInstance:
        props = dict(record["n"])
        return NodeInstance(
            id=props.pop("_id"),
            node_type=node_type,
            properties=props,
            created_at=props.pop("_created_at", None),
            updated_at=props.pop("_updated_at", None),
        )

    def _map_edge(self, record: dict[str, Any], edge_type: str) -> EdgeInstance:
        props = dict(record["r"])
        return EdgeInstance(
            id=props.pop("_id"),
            edge_type=edge_type,
            source_id=record["source_id"],
            target_id=record["target_id"],
            properties=props,
            created_at=props.pop("_created_at", None),
        )
```

### Cypher Builder

The `CypherBuilder` generates parameterised Cypher strings.  It never
interpolates values into query text.

```python
# netgraphy/graph/cypher.py

from __future__ import annotations
from typing import Any

from netgraphy.graph.types import FilterSet, Pagination, TraversalSpec


class CypherBuilder:
    """Generates parameterised Cypher. All values go through $param bindings."""

    # ── nodes ──────────────────────────────────────────────────

    def create_node(
        self, label: str, properties: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        query = f"CREATE (n:`{label}` $props) RETURN n"
        return query, {"props": properties}

    def match_node_by_id(
        self, label: str, node_id: str
    ) -> tuple[str, dict[str, Any]]:
        query = f"MATCH (n:`{label}` {{_id: $node_id}}) RETURN n"
        return query, {"node_id": node_id}

    def update_node(
        self, label: str, node_id: str, properties: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        query = f"MATCH (n:`{label}` {{_id: $node_id}}) SET n += $props RETURN n"
        return query, {"node_id": node_id, "props": properties}

    def delete_node(
        self, label: str, node_id: str
    ) -> tuple[str, dict[str, Any]]:
        query = f"MATCH (n:`{label}` {{_id: $node_id}}) DETACH DELETE n"
        return query, {"node_id": node_id}

    def count_nodes(
        self, label: str, filters: FilterSet
    ) -> tuple[str, dict[str, Any]]:
        where_clause, params = self._build_where(filters, alias="n")
        query = f"MATCH (n:`{label}`) {where_clause} RETURN count(n) AS total"
        return query, params

    def list_nodes(
        self, label: str, filters: FilterSet, pagination: Pagination
    ) -> tuple[str, dict[str, Any]]:
        where_clause, params = self._build_where(filters, alias="n")
        order = f"n.{pagination.sort_by}" if pagination.sort_by else "n._created_at"
        direction = "DESC" if pagination.sort_desc else "ASC"
        query = (
            f"MATCH (n:`{label}`) {where_clause} "
            f"RETURN n ORDER BY {order} {direction} "
            f"SKIP $skip LIMIT $limit"
        )
        params["skip"] = pagination.offset
        params["limit"] = pagination.limit
        return query, params

    # ── edges ──────────────────────────────────────────────────

    def create_edge(
        self,
        rel_type: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        query = (
            "MATCH (a {_id: $source_id}), (b {_id: $target_id}) "
            f"CREATE (a)-[r:`{rel_type}` $props]->(b) "
            "RETURN r, a._id AS source_id, b._id AS target_id"
        )
        return query, {
            "source_id": source_id,
            "target_id": target_id,
            "props": properties,
        }

    def match_edges(
        self, node_id: str, rel_type: str | None, direction: str
    ) -> tuple[str, dict[str, Any]]:
        rel_spec = f":`{rel_type}`" if rel_type else ""
        if direction == "outbound":
            pattern = f"(a {{_id: $nid}})-[r{rel_spec}]->(b)"
        elif direction == "inbound":
            pattern = f"(b)-[r{rel_spec}]->(a {{_id: $nid}})"
        else:
            pattern = f"(a {{_id: $nid}})-[r{rel_spec}]-(b)"
        query = (
            f"MATCH {pattern} "
            "RETURN r, a._id AS source_id, b._id AS target_id, type(r) AS type"
        )
        return query, {"nid": node_id}

    def delete_edge(
        self, rel_type: str, edge_id: str
    ) -> tuple[str, dict[str, Any]]:
        query = (
            f"MATCH ()-[r:`{rel_type}` {{_id: $edge_id}}]->() DELETE r"
        )
        return query, {"edge_id": edge_id}

    def count_edges_to(
        self, rel_type: str, target_id: str
    ) -> tuple[str, dict[str, Any]]:
        query = (
            f"MATCH ()-[r:`{rel_type}`]->(b {{_id: $tid}}) RETURN count(r) AS cnt"
        )
        return query, {"tid": target_id}

    def count_edges_from(
        self, rel_type: str, source_id: str
    ) -> tuple[str, dict[str, Any]]:
        query = (
            f"MATCH (a {{_id: $sid}})-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
        )
        return query, {"sid": source_id}

    # ── bulk ───────────────────────────────────────────────────

    def bulk_merge_nodes(
        self, label: str, batch: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any]]:
        query = (
            "UNWIND $batch AS row "
            f"MERGE (n:`{label}` {{_id: row._id}}) "
            "ON CREATE SET n = row "
            "ON MATCH SET n += row "
            "RETURN n"
        )
        return query, {"batch": batch}

    def bulk_merge_edges(
        self, rel_type: str, batch: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any]]:
        query = (
            "UNWIND $batch AS row "
            "MATCH (a {_id: row.source_id}), (b {_id: row.target_id}) "
            f"MERGE (a)-[r:`{rel_type}` {{_id: row._id}}]->(b) "
            "ON CREATE SET r = row.props "
            "ON MATCH SET r += row.props "
            "RETURN r"
        )
        return query, {"batch": batch}

    # ── traversal ──────────────────────────────────────────────

    def traversal(
        self, start_id: str, spec: TraversalSpec
    ) -> tuple[str, dict[str, Any]]:
        rel_filter = f":`{spec.edge_type}`" if spec.edge_type else ""
        query = (
            f"MATCH path = (start {{_id: $start_id}})"
            f"-[{rel_filter}*1..{spec.max_depth}]-"
            f"(end) "
            f"RETURN path LIMIT $path_limit"
        )
        return query, {"start_id": start_id, "path_limit": spec.max_paths}

    # ── filter builder ─────────────────────────────────────────

    def _build_where(
        self, filters: FilterSet, alias: str
    ) -> tuple[str, dict[str, Any]]:
        if not filters.conditions:
            return "", {}

        clauses = []
        params = {}
        for i, cond in enumerate(filters.conditions):
            param_name = f"_f{i}"
            prop_ref = f"{alias}.`{cond.field}`"

            match cond.operator:
                case "eq":
                    clauses.append(f"{prop_ref} = ${param_name}")
                case "neq":
                    clauses.append(f"{prop_ref} <> ${param_name}")
                case "gt":
                    clauses.append(f"{prop_ref} > ${param_name}")
                case "gte":
                    clauses.append(f"{prop_ref} >= ${param_name}")
                case "lt":
                    clauses.append(f"{prop_ref} < ${param_name}")
                case "lte":
                    clauses.append(f"{prop_ref} <= ${param_name}")
                case "contains":
                    clauses.append(f"{prop_ref} CONTAINS ${param_name}")
                case "starts_with":
                    clauses.append(f"{prop_ref} STARTS WITH ${param_name}")
                case "in":
                    clauses.append(f"{prop_ref} IN ${param_name}")
                case "is_null":
                    clauses.append(f"{prop_ref} IS NULL")
                    continue  # no param needed
                case "is_not_null":
                    clauses.append(f"{prop_ref} IS NOT NULL")
                    continue

            params[param_name] = cond.value

        where = "WHERE " + " AND ".join(clauses)
        return where, params
```

### Driver Adapter Abstraction

The adapter is the seam that allows Neo4j to be swapped for Apache AGE without
touching the repository or the Cypher builder.

```python
# netgraphy/graph/adapters/base.py

from __future__ import annotations
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


class TxHandle(ABC):
    """Abstract transaction handle returned by a DriverAdapter."""

    @abstractmethod
    async def run_single(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Execute query and return the first record, or None."""

    @abstractmethod
    async def run_many(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute query and return all records."""

    @abstractmethod
    async def run_scalar(self, query: str, params: dict[str, Any]) -> Any:
        """Execute query and return a single scalar value."""

    @abstractmethod
    async def run_consume(self, query: str, params: dict[str, Any]) -> Any:
        """Execute query and return a result summary (with counters)."""


class DriverAdapter(ABC):
    """Abstract interface that graph backends must implement."""

    @abstractmethod
    @asynccontextmanager
    async def read_tx(self) -> AsyncIterator[TxHandle]:
        """Provide a read transaction."""
        yield  # type: ignore[misc]

    @abstractmethod
    @asynccontextmanager
    async def write_tx(self) -> AsyncIterator[TxHandle]:
        """Provide a write transaction."""
        yield  # type: ignore[misc]

    @abstractmethod
    async def close(self) -> None: ...
```

### Neo4j Adapter Implementation

```python
# netgraphy/graph/adapters/neo4j_adapter.py

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncSession

from netgraphy.graph.adapters.base import DriverAdapter, TxHandle


class Neo4jTxHandle(TxHandle):
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def run_single(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        result = await self._tx.run(query, params)
        record = await result.single()
        return dict(record) if record else None

    async def run_many(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self._tx.run(query, params)
        return [dict(r) for r in await result.fetch(1000)]

    async def run_scalar(self, query: str, params: dict[str, Any]) -> Any:
        result = await self._tx.run(query, params)
        record = await result.single()
        return record[0] if record else None

    async def run_consume(self, query: str, params: dict[str, Any]) -> Any:
        result = await self._tx.run(query, params)
        return await result.consume()


class Neo4jAdapter(DriverAdapter):
    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    @asynccontextmanager
    async def read_tx(self) -> AsyncIterator[TxHandle]:
        async with self._driver.session(database=self._database) as session:
            async with session.begin_transaction() as tx:
                handle = Neo4jTxHandle(tx)
                yield handle
                # read-only: no commit needed, implicit rollback is fine

    @asynccontextmanager
    async def write_tx(self) -> AsyncIterator[TxHandle]:
        async with self._driver.session(database=self._database) as session:
            async with session.begin_transaction() as tx:
                handle = Neo4jTxHandle(tx)
                yield handle
                await tx.commit()

    async def close(self) -> None:
        await self._driver.close()
```

### Apache AGE Adapter (Future)

When Apache AGE support is added, the adapter translates the same Cypher
into AGE-compatible SQL.  The key difference: AGE runs Cypher inside a
`SELECT * FROM cypher('graph_name', $$ ... $$) AS (result agtype)` wrapper.

```python
# netgraphy/graph/adapters/age_adapter.py  (sketch)

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from netgraphy.graph.adapters.base import DriverAdapter, TxHandle


class AGETxHandle(TxHandle):
    def __init__(self, conn: asyncpg.Connection, graph_name: str) -> None:
        self._conn = conn
        self._graph = graph_name

    def _wrap(self, cypher: str) -> str:
        """Wrap Cypher in AGE's SQL function call."""
        return f"SELECT * FROM cypher('{self._graph}', $cypher${cypher}$cypher$) AS (result agtype)"

    async def run_single(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        # AGE does not support $param binding in the same way;
        # parameters must be injected via the SET clause or via
        # a preceding `SELECT set_config(...)` call per parameter.
        sql = self._wrap(self._inject_params(query, params))
        row = await self._conn.fetchrow(sql)
        return self._parse_agtype(row) if row else None

    # ... remaining methods follow the same pattern ...

    def _inject_params(self, query: str, params: dict[str, Any]) -> str:
        """
        Replace $param_name tokens with AGE-compatible literal syntax.
        Uses proper escaping to prevent injection.
        """
        import json
        result = query
        for key, value in params.items():
            token = f"${key}"
            if isinstance(value, str):
                safe = value.replace("'", "\\'")
                literal = f"'{safe}'"
            elif isinstance(value, (list, dict)):
                literal = json.dumps(value)
            elif value is None:
                literal = "null"
            else:
                literal = str(value)
            result = result.replace(token, literal)
        return result


class AGEAdapter(DriverAdapter):
    def __init__(self, pool: asyncpg.Pool, graph_name: str) -> None:
        self._pool = pool
        self._graph = graph_name

    @asynccontextmanager
    async def read_tx(self) -> AsyncIterator[TxHandle]:
        async with self._pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                await conn.execute("SET search_path = ag_catalog, '$user', public")
                yield AGETxHandle(conn, self._graph)

    @asynccontextmanager
    async def write_tx(self) -> AsyncIterator[TxHandle]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET search_path = ag_catalog, '$user', public")
                yield AGETxHandle(conn, self._graph)

    async def close(self) -> None:
        await self._pool.close()
```

### Schema Validation Before Writes

Every mutation goes through the schema registry before Cypher is generated.
The `NodeTypeDefinition.validate_properties` method enforces required fields,
type checking, enum constraints, and regex patterns.

```python
# Inside SchemaRegistry / NodeTypeDefinition (abridged)

class NodeTypeDefinition:
    name: str
    attributes: dict[str, AttributeDefinition]

    def validate_properties(self, props: dict[str, Any]) -> dict[str, Any]:
        """Full validation for create. Raises SchemaValidationError."""
        errors = []
        validated = {}

        # check required attributes are present
        for attr_name, attr_def in self.attributes.items():
            if attr_def.required and attr_name not in props:
                errors.append(f"Missing required attribute: {attr_name}")

        # validate each supplied property
        for key, value in props.items():
            attr_def = self.attributes.get(key)
            if attr_def is None:
                errors.append(f"Unknown attribute: {key}")
                continue
            try:
                validated[key] = attr_def.coerce_and_validate(value)
            except ValueError as e:
                errors.append(f"Attribute '{key}': {e}")

        if errors:
            raise SchemaValidationError(errors=errors)
        return validated

    def validate_partial(self, props: dict[str, Any]) -> dict[str, Any]:
        """Partial validation for update -- required check is skipped."""
        errors = []
        validated = {}
        for key, value in props.items():
            attr_def = self.attributes.get(key)
            if attr_def is None:
                errors.append(f"Unknown attribute: {key}")
                continue
            try:
                validated[key] = attr_def.coerce_and_validate(value)
            except ValueError as e:
                errors.append(f"Attribute '{key}': {e}")
        if errors:
            raise SchemaValidationError(errors=errors)
        return validated
```

### Transaction Boundary Management

Transactions are scoped by the `DriverAdapter` context manager.  The
repository opens one transaction per public method call.  For `bulk_upsert`,
the entire batch runs inside a single write transaction so that it is atomic.

For operations that span multiple repository calls (e.g. the service layer
creating a node and then an edge in a single logical operation), a
`TransactionScope` is provided:

```python
# netgraphy/graph/transaction.py

from contextlib import asynccontextmanager
from netgraphy.graph.adapters.base import DriverAdapter, TxHandle


class TransactionScope:
    """
    Allows a service to group multiple repository operations into a single
    database transaction.  When active, the repository re-uses the provided
    TxHandle instead of opening a new transaction.
    """

    def __init__(self, adapter: DriverAdapter) -> None:
        self._adapter = adapter
        self._tx: TxHandle | None = None

    @asynccontextmanager
    async def begin(self):
        async with self._adapter.write_tx() as tx:
            self._tx = tx
            yield self
            # commit happens when the adapter context exits
        self._tx = None

    @property
    def tx(self) -> TxHandle:
        if self._tx is None:
            raise RuntimeError("No active transaction scope")
        return self._tx
```

---

## 4.3 Domain Services Layer

Every service follows the same lifecycle for mutations:
**validate -> authorise -> execute -> audit -> emit event**.

### NodeService

```python
# netgraphy/services/node.py

from __future__ import annotations
from netgraphy.auth.context import AuthContext
from netgraphy.events.nats import NATSClient
from netgraphy.graph.repository import GraphRepository
from netgraphy.graph.types import FilterSet, NodeInstance, Page, Pagination
from netgraphy.schema.registry import SchemaRegistry


class NodeService:
    def __init__(
        self,
        repo: GraphRepository,
        schema_registry: SchemaRegistry,
        events: NATSClient,
    ) -> None:
        self._repo = repo
        self._schema = schema_registry
        self._events = events

    async def create(
        self, node_type: str, properties: dict, actor: AuthContext
    ) -> NodeInstance:
        # 1. validate: schema check happens inside repo.create_node
        # 2. authorise
        actor.require_permission("node:create", resource=node_type)

        # 3. execute
        node = await self._repo.create_node(node_type, properties)

        # 4. audit + 5. emit
        await self._events.publish(
            "node.created",
            {
                "node_type": node_type,
                "node_id": node.id,
                "properties": properties,
            },
            actor=actor,
        )
        return node

    async def get(
        self, node_type: str, node_id: str, actor: AuthContext
    ) -> NodeInstance:
        actor.require_permission("node:read", resource=node_type)
        return await self._repo.get_node(node_type, node_id)

    async def update(
        self, node_type: str, node_id: str, properties: dict, actor: AuthContext
    ) -> NodeInstance:
        actor.require_permission("node:update", resource=node_type)

        node = await self._repo.update_node(node_type, node_id, properties)

        await self._events.publish(
            "node.updated",
            {
                "node_type": node_type,
                "node_id": node_id,
                "changes": properties,
            },
            actor=actor,
        )
        return node

    async def delete(
        self, node_type: str, node_id: str, actor: AuthContext
    ) -> None:
        actor.require_permission("node:delete", resource=node_type)

        await self._repo.delete_node(node_type, node_id)

        await self._events.publish(
            "node.deleted",
            {"node_type": node_type, "node_id": node_id},
            actor=actor,
        )

    async def list(
        self,
        node_type: str,
        filters: FilterSet,
        pagination: Pagination,
        actor: AuthContext,
    ) -> Page[NodeInstance]:
        actor.require_permission("node:read", resource=node_type)
        return await self._repo.list_nodes(node_type, filters, pagination)
```

### EdgeService

```python
# netgraphy/services/edge.py

from __future__ import annotations
from netgraphy.auth.context import AuthContext
from netgraphy.events.nats import NATSClient
from netgraphy.graph.repository import GraphRepository
from netgraphy.graph.types import Direction, EdgeInstance
from netgraphy.schema.registry import SchemaRegistry


class EdgeService:
    def __init__(
        self,
        repo: GraphRepository,
        schema_registry: SchemaRegistry,
        events: NATSClient,
    ) -> None:
        self._repo = repo
        self._schema = schema_registry
        self._events = events

    async def create(
        self,
        edge_type: str,
        source_id: str,
        target_id: str,
        properties: dict,
        actor: AuthContext,
    ) -> EdgeInstance:
        actor.require_permission("edge:create", resource=edge_type)

        # Validate endpoint types match schema definition
        edge_def = self._schema.get_edge_type(edge_type)
        await self._validate_endpoint_types(edge_def, source_id, target_id)

        # Cardinality enforcement happens inside repo.create_edge
        edge = await self._repo.create_edge(edge_type, source_id, target_id, properties)

        await self._events.publish(
            "edge.created",
            {
                "edge_type": edge_type,
                "edge_id": edge.id,
                "source_id": source_id,
                "target_id": target_id,
            },
            actor=actor,
        )
        return edge

    async def get_for_node(
        self,
        node_id: str,
        edge_type: str | None,
        direction: Direction,
        actor: AuthContext,
    ) -> list[EdgeInstance]:
        actor.require_permission("edge:read")
        return await self._repo.get_edges(node_id, edge_type, direction)

    async def delete(
        self, edge_type: str, edge_id: str, actor: AuthContext
    ) -> None:
        actor.require_permission("edge:delete", resource=edge_type)
        await self._repo.delete_edge(edge_type, edge_id)
        await self._events.publish(
            "edge.deleted",
            {"edge_type": edge_type, "edge_id": edge_id},
            actor=actor,
        )

    async def _validate_endpoint_types(self, edge_def, source_id: str, target_id: str):
        """Ensure source and target nodes match the edge's allowed endpoint types."""
        source_node = await self._repo.get_node(edge_def.source_type, source_id)
        target_node = await self._repo.get_node(edge_def.target_type, target_id)
        # get_node raises NodeNotFoundError if the node doesn't exist
        # or if its label doesn't match -- which is exactly the check we need.
```

### QueryService

```python
# netgraphy/services/query.py

from __future__ import annotations
import hashlib
import json
from netgraphy.auth.context import AuthContext
from netgraphy.cache.redis import RedisPool
from netgraphy.events.nats import NATSClient
from netgraphy.graph.repository import GraphRepository
from netgraphy.graph.types import QueryResult


class QueryService:
    CACHE_TTL_SECONDS = 30

    def __init__(
        self,
        repo: GraphRepository,
        redis: RedisPool,
        events: NATSClient,
    ) -> None:
        self._repo = repo
        self._redis = redis
        self._events = events

    async def execute(
        self,
        cypher: str,
        params: dict,
        actor: AuthContext,
        use_cache: bool = True,
    ) -> QueryResult:
        actor.require_permission("query:execute")

        # Check cache
        cache_key = None
        if use_cache:
            cache_key = self._cache_key(cypher, params)
            cached = await self._redis.get(cache_key)
            if cached is not None:
                return QueryResult.model_validate_json(cached)

        result = await self._repo.execute_cypher(cypher, params)

        if cache_key:
            await self._redis.set(
                cache_key,
                result.model_dump_json(),
                ex=self.CACHE_TTL_SECONDS,
            )

        await self._events.publish(
            "query.executed",
            {"cypher_hash": hashlib.sha256(cypher.encode()).hexdigest()},
            actor=actor,
        )
        return result

    def _cache_key(self, cypher: str, params: dict) -> str:
        raw = json.dumps({"q": cypher, "p": params}, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return f"qcache:{digest}"
```

### SchemaService

```python
# netgraphy/services/schema.py

from __future__ import annotations
from netgraphy.auth.context import AuthContext
from netgraphy.cache.redis import RedisPool
from netgraphy.db.neo4j import Neo4jPool
from netgraphy.events.nats import NATSClient
from netgraphy.models.schema import MigrationPlan, SchemaChangeSet
from netgraphy.schema.registry import SchemaRegistry


class SchemaService:
    def __init__(
        self,
        registry: SchemaRegistry,
        neo4j: Neo4jPool,
        events: NATSClient,
        redis: RedisPool,
    ) -> None:
        self._registry = registry
        self._neo4j = neo4j
        self._events = events
        self._redis = redis

    async def apply_changeset(
        self, changeset: SchemaChangeSet, actor: AuthContext
    ) -> MigrationPlan:
        actor.require_permission("schema:write")

        # 1. Validate the changeset against current schema
        plan = self._registry.plan_migration(changeset)

        # 2. Apply index and constraint changes to Neo4j
        async with self._neo4j.session() as session:
            for stmt in plan.index_statements:
                await session.run(stmt)
            for stmt in plan.constraint_statements:
                await session.run(stmt)

        # 3. Persist the new schema definitions as meta-nodes in Neo4j
        await self._registry.persist(changeset)

        # 4. Reload the in-memory registry
        await self._registry.load()

        # 5. Emit event so caches everywhere are invalidated
        await self._events.publish(
            "schema.changed",
            {"changeset_id": changeset.id, "summary": plan.summary},
            actor=actor,
        )
        return plan
```

### SyncService

```python
# netgraphy/services/sync.py

from __future__ import annotations
from netgraphy.auth.context import AuthContext
from netgraphy.events.nats import NATSClient
from netgraphy.graph.repository import GraphRepository
from netgraphy.models.sync import SyncSource, SyncResult


class SyncService:
    def __init__(
        self,
        repo: GraphRepository,
        events: NATSClient,
    ) -> None:
        self._repo = repo
        self._events = events

    async def sync(self, source: SyncSource, actor: AuthContext) -> SyncResult:
        actor.require_permission("sync:execute")

        # 1. Clone or pull the git repo to a temp directory
        work_dir = await self._clone_or_pull(source)

        # 2. Parse files into UpsertOperations
        operations = await self._parse_source(work_dir, source)

        # 3. Bulk upsert into the graph
        bulk_result = await self._repo.bulk_upsert(operations)

        result = SyncResult(
            source_id=source.id,
            created=bulk_result.created,
            updated=bulk_result.updated,
            total=bulk_result.total,
        )

        await self._events.publish(
            "sync.completed",
            result.model_dump(),
            actor=actor,
        )
        return result
```

### JobService

```python
# netgraphy/services/job.py

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from netgraphy.auth.context import AuthContext
from netgraphy.events.nats import NATSClient
from netgraphy.models.job import JobExecution, JobManifest, JobStatus


class JobService:
    def __init__(self, events: NATSClient) -> None:
        self._events = events
        # In production, job state is persisted to PostgreSQL or Neo4j meta-nodes.
        # In-memory dict shown here for clarity.
        self._executions: dict[str, JobExecution] = {}

    async def submit(
        self, manifest: JobManifest, actor: AuthContext
    ) -> JobExecution:
        actor.require_permission("job:submit")

        execution = JobExecution(
            id=str(uuid.uuid4()),
            manifest=manifest,
            status=JobStatus.PENDING,
            submitted_at=datetime.now(timezone.utc),
            submitted_by=actor.user_id,
        )
        self._executions[execution.id] = execution

        await self._events.publish(
            "job.started",
            {"job_id": execution.id, "job_type": manifest.job_type},
            actor=actor,
        )

        # Dispatch to NATS for worker pickup
        await self._events.publish_to_queue(
            f"jobs.{manifest.job_type}",
            execution.model_dump(),
        )
        return execution

    async def complete(
        self, job_id: str, success: bool, result: dict | None = None
    ) -> None:
        execution = self._executions[job_id]
        execution.status = JobStatus.COMPLETED if success else JobStatus.FAILED
        execution.completed_at = datetime.now(timezone.utc)
        execution.result = result

        await self._events.publish(
            "job.completed",
            {
                "job_id": job_id,
                "status": execution.status.value,
            },
        )

    async def get(self, job_id: str, actor: AuthContext) -> JobExecution:
        actor.require_permission("job:read")
        return self._executions[job_id]
```

---

## 4.4 Data Models (Pydantic)

All models use Pydantic v2 with strict validation.  Internal (domain) models
and external (API) models are kept separate; API models handle serialisation
concerns (camelCase aliases, field exclusion) while domain models are the
canonical shapes used by services and repositories.

```python
# netgraphy/models/domain.py

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field


# ── graph instances ────────────────────────────────────────────

class NodeInstance(BaseModel):
    id: str
    node_type: str
    properties: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EdgeInstance(BaseModel):
    id: str
    edge_type: str
    source_id: str
    target_id: str
    properties: dict[str, Any]
    created_at: datetime | None = None


# ── schema definitions ─────────────────────────────────────────

class AttributeType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    JSON = "json"
    IP_ADDRESS = "ip_address"
    IP_NETWORK = "ip_network"
    MAC_ADDRESS = "mac_address"
    ENUM = "enum"
    LIST = "list"


class AttributeDefinition(BaseModel):
    name: str
    attr_type: AttributeType
    required: bool = False
    default: Any = None
    description: str = ""
    unique: bool = False
    indexed: bool = False
    enum_values: list[str] | None = None
    pattern: str | None = None  # regex pattern for string validation
    list_item_type: AttributeType | None = None

    def coerce_and_validate(self, value: Any) -> Any:
        """Coerce the value to the correct type and validate constraints."""
        import ipaddress
        import re

        match self.attr_type:
            case AttributeType.STRING:
                if not isinstance(value, str):
                    raise ValueError(f"Expected string, got {type(value).__name__}")
                if self.pattern and not re.match(self.pattern, value):
                    raise ValueError(f"Value does not match pattern: {self.pattern}")
                return value
            case AttributeType.INTEGER:
                return int(value)
            case AttributeType.FLOAT:
                return float(value)
            case AttributeType.BOOLEAN:
                return bool(value)
            case AttributeType.IP_ADDRESS:
                return str(ipaddress.ip_address(value))
            case AttributeType.IP_NETWORK:
                return str(ipaddress.ip_network(value, strict=False))
            case AttributeType.MAC_ADDRESS:
                if not re.match(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$", value):
                    raise ValueError(f"Invalid MAC address: {value}")
                return value.upper()
            case AttributeType.ENUM:
                if self.enum_values and value not in self.enum_values:
                    raise ValueError(f"Value must be one of: {self.enum_values}")
                return value
            case AttributeType.LIST:
                if not isinstance(value, list):
                    raise ValueError("Expected a list")
                return value
            case _:
                return value


class CardinalityConstraint(BaseModel):
    source_min: int = 0
    source_max: int | None = None  # None = unbounded
    target_min: int = 0
    target_max: int | None = None


class NodeTypeDefinition(BaseModel):
    name: str
    label: str  # display label
    description: str = ""
    attributes: dict[str, AttributeDefinition]
    icon: str | None = None
    color: str | None = None


class EdgeTypeDefinition(BaseModel):
    name: str
    label: str
    description: str = ""
    source_type: str  # node type name
    target_type: str  # node type name
    attributes: dict[str, AttributeDefinition] = {}
    cardinality: CardinalityConstraint | None = None


# ── filtering and pagination ───────────────────────────────────

class FilterOperator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    IN = "in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class FilterCondition(BaseModel):
    field: str
    operator: FilterOperator
    value: Any = None


class FilterSet(BaseModel):
    conditions: list[FilterCondition] = []


class Pagination(BaseModel):
    offset: int = 0
    limit: int = 50
    sort_by: str | None = None
    sort_desc: bool = False


T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    pagination: Pagination


# ── queries ────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    cypher: str
    params: dict[str, Any] = {}
    use_cache: bool = True


class QueryResult(BaseModel):
    records: list[dict[str, Any]]
    execution_time_ms: float | None = None


# ── schema changes ─────────────────────────────────────────────

class SchemaOperationType(str, Enum):
    ADD_NODE_TYPE = "add_node_type"
    REMOVE_NODE_TYPE = "remove_node_type"
    ADD_EDGE_TYPE = "add_edge_type"
    REMOVE_EDGE_TYPE = "remove_edge_type"
    ADD_ATTRIBUTE = "add_attribute"
    REMOVE_ATTRIBUTE = "remove_attribute"
    MODIFY_ATTRIBUTE = "modify_attribute"


class SchemaOperation(BaseModel):
    operation: SchemaOperationType
    target: str  # e.g. "Device" or "Device.hostname"
    definition: dict[str, Any] | None = None  # new/modified definition


class SchemaChangeSet(BaseModel):
    id: str
    description: str
    operations: list[SchemaOperation]


class MigrationPlan(BaseModel):
    changeset_id: str
    summary: str
    index_statements: list[str] = []
    constraint_statements: list[str] = []
    data_migration_queries: list[str] = []
    breaking: bool = False
    warnings: list[str] = []


# ── jobs ───────────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobManifest(BaseModel):
    job_type: str  # e.g. "ingestion", "sync", "export"
    params: dict[str, Any] = {}
    schedule: str | None = None  # cron expression for recurring jobs


class JobExecution(BaseModel):
    id: str
    manifest: JobManifest
    status: JobStatus
    submitted_at: datetime
    submitted_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobLog(BaseModel):
    job_id: str
    timestamp: datetime
    level: str  # "info", "warning", "error"
    message: str
    data: dict[str, Any] | None = None


# ── audit ──────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    id: str
    timestamp: datetime
    actor_id: str
    actor_name: str | None = None
    action: str  # e.g. "node.created", "schema.changed"
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = {}
    request_id: str | None = None
    source_ip: str | None = None


# ── sync ───────────────────────────────────────────────────────

class SyncSourceType(str, Enum):
    GIT = "git"
    HTTP = "http"
    S3 = "s3"


class SyncSource(BaseModel):
    id: str
    name: str
    source_type: SyncSourceType
    url: str
    branch: str = "main"
    path_glob: str = "**/*"
    parser: str = "auto"  # parser plugin name
    schedule: str | None = None  # cron expression
    credentials_ref: str | None = None  # reference to secret store


class SyncResult(BaseModel):
    source_id: str
    created: int
    updated: int
    total: int
    errors: list[str] = []
    duration_seconds: float | None = None
```

---

## 4.5 Neo4j Integration

### Connection Pooling

The `Neo4jPool` wraps the official async driver and exposes a
request-scoped session factory.

```python
# netgraphy/db/neo4j.py

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import AsyncIterator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession


class Neo4jPool:
    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    @classmethod
    async def connect(
        cls,
        uri: str,
        auth: tuple[str, str],
        max_connection_pool_size: int = 50,
        database: str = "neo4j",
    ) -> Neo4jPool:
        driver = AsyncGraphDatabase.driver(
            uri,
            auth=auth,
            max_connection_pool_size=max_connection_pool_size,
            connection_acquisition_timeout=10.0,
            max_transaction_retry_time=5.0,
        )
        # Verify connectivity at startup
        await driver.verify_connectivity()
        return cls(driver, database)

    @property
    def driver(self) -> AsyncDriver:
        return self._driver

    @asynccontextmanager
    async def session(self, **kwargs) -> AsyncIterator[AsyncSession]:
        async with self._driver.session(
            database=self._database, **kwargs
        ) as session:
            yield session

    async def close(self) -> None:
        await self._driver.close()

    async def health_check(self) -> bool:
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            return False
```

### Index and Constraint Management from Schema

When the schema registry loads or changes, indexes and constraints are
synchronised with Neo4j.

```python
# netgraphy/schema/index_manager.py

from __future__ import annotations
from netgraphy.models.domain import NodeTypeDefinition, EdgeTypeDefinition


class IndexManager:
    """Generates Cypher statements for indexes and constraints from schema definitions."""

    def generate_index_statements(
        self, node_types: list[NodeTypeDefinition]
    ) -> list[str]:
        statements = []
        for nt in node_types:
            # Always index the _id property
            statements.append(
                f"CREATE INDEX IF NOT EXISTS FOR (n:`{nt.name}`) ON (n._id)"
            )
            for attr_name, attr_def in nt.attributes.items():
                if attr_def.indexed:
                    statements.append(
                        f"CREATE INDEX IF NOT EXISTS FOR (n:`{nt.name}`) ON (n.`{attr_name}`)"
                    )
        return statements

    def generate_constraint_statements(
        self, node_types: list[NodeTypeDefinition]
    ) -> list[str]:
        statements = []
        for nt in node_types:
            # _id is always unique
            statements.append(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{nt.name}`) "
                f"REQUIRE n._id IS UNIQUE"
            )
            for attr_name, attr_def in nt.attributes.items():
                if attr_def.unique:
                    statements.append(
                        f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{nt.name}`) "
                        f"REQUIRE n.`{attr_name}` IS UNIQUE"
                    )
        return statements

    def generate_drop_statements(
        self, removed_types: list[str]
    ) -> list[str]:
        """Generate drop statements when a type is removed from schema."""
        statements = []
        for name in removed_types:
            statements.append(f"DROP INDEX ON :`{name}`(_id) IF EXISTS")
            statements.append(
                f"DROP CONSTRAINT ON (n:`{name}`) ASSERT n._id IS UNIQUE IF EXISTS"
            )
        return statements
```

### Query Result Mapping

Raw Neo4j records are mapped into domain objects via lightweight mapper
functions.  The `Neo4jTxHandle.run_many` method (shown in section 4.2) returns
plain dictionaries.  The repository's `_map_node` and `_map_edge` methods
convert those dictionaries into `NodeInstance` and `EdgeInstance` Pydantic
models.

For path results returned by traversal queries, the mapping is more involved:

```python
# netgraphy/graph/mappers.py

from neo4j.graph import Node, Relationship, Path
from netgraphy.models.domain import NodeInstance, EdgeInstance


def map_path(path: Path) -> dict:
    """Map a Neo4j Path to a dictionary of nodes and edges."""
    nodes = []
    edges = []

    for node in path.nodes:
        nodes.append(NodeInstance(
            id=node["_id"],
            node_type=list(node.labels)[0],
            properties={k: v for k, v in dict(node).items() if not k.startswith("_")},
            created_at=node.get("_created_at"),
            updated_at=node.get("_updated_at"),
        ))

    for rel in path.relationships:
        edges.append(EdgeInstance(
            id=rel["_id"],
            edge_type=rel.type,
            source_id=rel.start_node["_id"],
            target_id=rel.end_node["_id"],
            properties={k: v for k, v in dict(rel).items() if not k.startswith("_")},
            created_at=rel.get("_created_at"),
        ))

    return {"nodes": nodes, "edges": edges}
```

### Performance: EXPLAIN/PROFILE Support

The query service supports an `explain` mode for development and debugging:

```python
# netgraphy/services/query.py  (additional method)

    async def explain(
        self, cypher: str, params: dict, actor: AuthContext, profile: bool = False
    ) -> dict:
        actor.require_permission("query:execute")
        prefix = "PROFILE" if profile else "EXPLAIN"
        result = await self._repo.execute_cypher(f"{prefix} {cypher}", params)
        return result.records
```

---

## 4.6 Event System (NATS)

### NATS JetStream Configuration

All events are published to durable JetStream streams so that subscribers
can recover from downtime without losing events.

```python
# netgraphy/events/nats.py

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import nats
from nats.aio.client import Client as NATSConnection
from nats.js import JetStreamContext


class NATSClient:
    """Manages NATS connection, JetStream streams, and event publishing."""

    # All event types and their stream assignments
    STREAMS = {
        "GRAPH_EVENTS": {
            "subjects": [
                "netgraphy.node.>",
                "netgraphy.edge.>",
            ],
            "retention": "limits",
            "max_age": 7 * 24 * 60 * 60 * 10**9,  # 7 days in nanoseconds
            "storage": "file",
        },
        "SCHEMA_EVENTS": {
            "subjects": ["netgraphy.schema.>"],
            "retention": "limits",
            "max_age": 30 * 24 * 60 * 60 * 10**9,  # 30 days
            "storage": "file",
        },
        "JOB_EVENTS": {
            "subjects": [
                "netgraphy.job.>",
                "netgraphy.sync.>",
                "netgraphy.ingestion.>",
            ],
            "retention": "limits",
            "max_age": 14 * 24 * 60 * 60 * 10**9,  # 14 days
            "storage": "file",
        },
        "AUDIT_EVENTS": {
            "subjects": ["netgraphy.audit.>"],
            "retention": "limits",
            "max_age": 90 * 24 * 60 * 60 * 10**9,  # 90 days
            "storage": "file",
        },
        "QUERY_EVENTS": {
            "subjects": ["netgraphy.query.>"],
            "retention": "limits",
            "max_age": 1 * 24 * 60 * 60 * 10**9,  # 1 day
            "storage": "memory",  # high volume, short retention
        },
    }

    def __init__(self, nc: NATSConnection, js: JetStreamContext, prefix: str) -> None:
        self._nc = nc
        self._js = js
        self._prefix = prefix

    @classmethod
    async def connect(cls, servers: list[str], stream_prefix: str) -> NATSClient:
        nc = await nats.connect(servers=servers)
        js = nc.jetstream()

        client = cls(nc, js, stream_prefix)
        await client._ensure_streams()
        return client

    async def _ensure_streams(self) -> None:
        """Create or update JetStream streams on startup."""
        for stream_name, config in self.STREAMS.items():
            try:
                await self._js.find_stream_name_by_subject(config["subjects"][0])
            except Exception:
                await self._js.add_stream(
                    name=stream_name,
                    subjects=config["subjects"],
                    retention=config["retention"],
                    max_age=config["max_age"],
                    storage=config["storage"],
                )

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: Any | None = None,
    ) -> None:
        """Publish an event to the appropriate JetStream subject."""
        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor_id=getattr(actor, "user_id", None),
            tenant_id=getattr(actor, "tenant_id", None),
            correlation_id=getattr(actor, "request_id", None),
            payload=payload,
        )
        subject = f"{self._prefix}.{event_type}"
        data = json.dumps(envelope.to_dict()).encode()
        await self._js.publish(subject, data)

    async def publish_to_queue(self, subject: str, payload: dict) -> None:
        """Publish to a work queue (for job distribution)."""
        data = json.dumps(payload).encode()
        await self._js.publish(f"{self._prefix}.{subject}", data)

    async def subscribe(
        self,
        subject: str,
        durable_name: str,
        handler: Callable[[dict], Awaitable[None]],
        deliver_policy: str = "new",
    ) -> None:
        """Subscribe to a JetStream subject with a durable consumer."""
        sub = await self._js.subscribe(
            f"{self._prefix}.{subject}",
            durable=durable_name,
            deliver_policy=deliver_policy,
        )

        async def _wrapper(msg):
            data = json.loads(msg.data.decode())
            try:
                await handler(data)
                await msg.ack()
            except Exception:
                await msg.nak()

        # NOTE: in production this runs in a background task
        self._subscriptions.append((sub, _wrapper))

    async def register_subscribers(self, app_state) -> None:
        """Register all built-in event subscribers."""
        from netgraphy.events.subscribers import (
            audit_logger,
            cache_invalidator,
            webhook_dispatcher,
        )

        await self.subscribe(
            "*.>", "audit-logger", audit_logger(app_state)
        )
        await self.subscribe(
            "node.>", "cache-invalidator-nodes", cache_invalidator(app_state, "node")
        )
        await self.subscribe(
            "edge.>", "cache-invalidator-edges", cache_invalidator(app_state, "edge")
        )
        await self.subscribe(
            "schema.changed", "cache-invalidator-schema", cache_invalidator(app_state, "schema")
        )
        await self.subscribe(
            "*.>", "webhook-dispatcher", webhook_dispatcher(app_state)
        )

    async def drain(self) -> None:
        await self._nc.drain()


class EventEnvelope:
    """Standard event wrapper that all events conform to."""

    def __init__(
        self,
        event_id: str,
        event_type: str,
        timestamp: str,
        payload: dict[str, Any],
        actor_id: str | None = None,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.event_id = event_id
        self.event_type = event_type
        self.timestamp = timestamp
        self.actor_id = actor_id
        self.tenant_id = tenant_id
        self.correlation_id = correlation_id
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "actor_id": self.actor_id,
            "tenant_id": self.tenant_id,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
        }
```

### Event Subscribers

```python
# netgraphy/events/subscribers.py

from __future__ import annotations
from typing import Any, Callable, Awaitable
import logging

logger = logging.getLogger(__name__)


def audit_logger(app_state) -> Callable[[dict], Awaitable[None]]:
    """Persists every event to the audit log store."""
    async def handler(envelope: dict) -> None:
        from netgraphy.models.domain import AuditEvent
        import uuid
        from datetime import datetime

        event = AuditEvent(
            id=str(uuid.uuid4()),
            timestamp=datetime.fromisoformat(envelope["timestamp"]),
            actor_id=envelope.get("actor_id", "system"),
            action=envelope["event_type"],
            details=envelope.get("payload", {}),
            request_id=envelope.get("correlation_id"),
        )
        # Persist to Neo4j as an AuditLog node or to a dedicated store
        async with app_state.neo4j.session() as session:
            await session.run(
                "CREATE (a:_AuditLog $props)",
                {"props": event.model_dump(mode="json")},
            )
    return handler


def cache_invalidator(app_state, domain: str) -> Callable[[dict], Awaitable[None]]:
    """Invalidates Redis caches when graph data or schema changes."""
    async def handler(envelope: dict) -> None:
        redis = app_state.redis
        match domain:
            case "schema":
                await redis.delete("schema:registry")
                logger.info("Invalidated schema registry cache")
            case "node" | "edge":
                # Invalidate all query caches (prefix scan + delete)
                keys = await redis.keys("qcache:*")
                if keys:
                    await redis.delete(*keys)
                logger.info(f"Invalidated {len(keys)} query cache entries")
    return handler


def webhook_dispatcher(app_state) -> Callable[[dict], Awaitable[None]]:
    """Dispatches events to registered webhook endpoints."""
    async def handler(envelope: dict) -> None:
        # Load webhook registrations from config/database
        # POST the envelope to each registered URL
        # Retry with exponential backoff on failure
        pass  # implementation depends on webhook registration model
    return handler
```

### WebSocket Bridge for UI Push

Events are forwarded to connected browser clients via a WebSocket endpoint
that subscribes to NATS subjects matching the client's interest.

```python
# netgraphy/api/routers/ws.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from netgraphy.api.deps import get_app_state

router = APIRouter()


@router.websocket("/ws/events")
async def event_stream(ws: WebSocket, state=Depends(get_app_state)):
    await ws.accept()
    queue = asyncio.Queue()

    # Subscribe to all events, forward to this client's queue
    async def _forward(envelope: dict):
        await queue.put(envelope)

    sub = await state.nats._js.subscribe(
        f"{state.nats._prefix}.>",
        deliver_policy="new",
    )

    try:
        async for msg in sub.messages:
            import json
            data = json.loads(msg.data.decode())
            await ws.send_json(data)
            await msg.ack()
    except WebSocketDisconnect:
        await sub.unsubscribe()
```

---

## 4.7 Caching Strategy

### Redis Cache Layout

| Key pattern | Content | TTL | Invalidation trigger |
|---|---|---|---|
| `schema:registry` | JSON-serialised schema registry | 1 hour | `schema.changed` event |
| `schema:type:{name}` | Single type definition | 1 hour | `schema.changed` event |
| `qcache:{sha256}` | Serialised `QueryResult` | 30 seconds | Any `node.*` or `edge.*` event |
| `session:{token_hash}` | Auth context JSON | Matches token expiry | Token revocation |
| `ratelimit:{ip}:{window}` | Request count | 60 seconds | Automatic TTL expiry |

### Cache-Aside with Event-Driven Invalidation

```python
# netgraphy/cache/redis.py

from __future__ import annotations
from typing import Any
import redis.asyncio as redis


class RedisPool:
    def __init__(self, pool: redis.Redis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> RedisPool:
        pool = redis.from_url(url, decode_responses=True)
        await pool.ping()
        return cls(pool)

    async def get(self, key: str) -> str | None:
        return await self._pool.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        await self._pool.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._pool.delete(*keys)

    async def keys(self, pattern: str) -> list[str]:
        return await self._pool.keys(pattern)

    async def incr(self, key: str) -> int:
        return await self._pool.incr(key)

    async def expire(self, key: str, seconds: int) -> None:
        await self._pool.expire(key, seconds)

    async def close(self) -> None:
        await self._pool.close()
```

### Schema Registry Cache Integration

```python
# netgraphy/schema/registry.py  (cache-relevant methods)

class SchemaRegistry:
    CACHE_KEY = "schema:registry"
    CACHE_TTL = 3600  # 1 hour

    def __init__(self, neo4j, redis) -> None:
        self._neo4j = neo4j
        self._redis = redis
        self._node_types: dict[str, NodeTypeDefinition] = {}
        self._edge_types: dict[str, EdgeTypeDefinition] = {}

    async def load(self) -> None:
        """Load schema from cache, falling back to Neo4j."""
        cached = await self._redis.get(self.CACHE_KEY)
        if cached:
            self._deserialise(cached)
            return

        # Load from Neo4j meta-nodes
        async with self._neo4j.session() as session:
            result = await session.run(
                "MATCH (s:_SchemaType) RETURN s"
            )
            records = [dict(r["s"]) async for r in result]

        self._load_from_records(records)

        # Populate cache
        await self._redis.set(
            self.CACHE_KEY,
            self._serialise(),
            ex=self.CACHE_TTL,
        )

    def get_node_type(self, name: str) -> NodeTypeDefinition | None:
        return self._node_types.get(name)

    def get_edge_type(self, name: str) -> EdgeTypeDefinition | None:
        return self._edge_types.get(name)

    def require_node_type(self, name: str) -> NodeTypeDefinition:
        td = self.get_node_type(name)
        if td is None:
            raise SchemaValidationError(f"Unknown node type: {name}")
        return td

    def require_edge_type(self, name: str) -> EdgeTypeDefinition:
        td = self.get_edge_type(name)
        if td is None:
            raise SchemaValidationError(f"Unknown edge type: {name}")
        return td
```

---

## 4.8 Error Handling

### Domain Exception Hierarchy

```python
# netgraphy/graph/exceptions.py

from __future__ import annotations
from typing import Any


class NetGraphyError(Exception):
    """Base exception for all NetGraphy domain errors."""
    error_code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SchemaValidationError(NetGraphyError):
    error_code = "SCHEMA_VALIDATION_ERROR"
    status_code = 400

    def __init__(self, message: str = "Schema validation failed", errors: list[str] | None = None) -> None:
        super().__init__(message, details={"errors": errors or []})
        self.errors = errors or []


class CardinalityViolationError(NetGraphyError):
    error_code = "CARDINALITY_VIOLATION"
    status_code = 409

    def __init__(
        self,
        edge_type: str,
        constraint: str,
        source_id: str | None = None,
        target_id: str | None = None,
    ) -> None:
        msg = f"Cardinality constraint '{constraint}' violated for edge type '{edge_type}'"
        super().__init__(msg, details={
            "edge_type": edge_type,
            "constraint": constraint,
            "source_id": source_id,
            "target_id": target_id,
        })


class NodeNotFoundError(NetGraphyError):
    error_code = "NODE_NOT_FOUND"
    status_code = 404

    def __init__(self, node_type: str, node_id: str) -> None:
        super().__init__(
            f"Node '{node_type}/{node_id}' not found",
            details={"node_type": node_type, "node_id": node_id},
        )


class EdgeNotFoundError(NetGraphyError):
    error_code = "EDGE_NOT_FOUND"
    status_code = 404

    def __init__(self, edge_type: str, edge_id: str) -> None:
        super().__init__(
            f"Edge '{edge_type}/{edge_id}' not found",
            details={"edge_type": edge_type, "edge_id": edge_id},
        )


class AuthorizationError(NetGraphyError):
    error_code = "AUTHORIZATION_ERROR"
    status_code = 403

    def __init__(self, action: str, resource: str | None = None) -> None:
        msg = f"Not authorized to perform '{action}'"
        if resource:
            msg += f" on '{resource}'"
        super().__init__(msg, details={"action": action, "resource": resource})


class SyncConflictError(NetGraphyError):
    error_code = "SYNC_CONFLICT"
    status_code = 409

    def __init__(self, source_id: str, message: str = "Sync conflict detected") -> None:
        super().__init__(message, details={"source_id": source_id})


class QueryExecutionError(NetGraphyError):
    error_code = "QUERY_EXECUTION_ERROR"
    status_code = 400

    def __init__(self, message: str, cypher: str | None = None) -> None:
        super().__init__(message, details={"cypher": cypher})


class RateLimitExceededError(NetGraphyError):
    error_code = "RATE_LIMIT_EXCEEDED"
    status_code = 429

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(
            "Rate limit exceeded",
            details={"retry_after_seconds": retry_after},
        )
```

### Consistent Error Response Format

All domain exceptions are caught by a global exception handler and mapped to a
uniform JSON structure.

```python
# netgraphy/api/error_handlers.py

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from netgraphy.graph.exceptions import NetGraphyError
import logging

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(NetGraphyError)
    async def handle_domain_error(request: Request, exc: NetGraphyError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                },
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled exception", extra={"request_id": request_id})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": {},
                    "request_id": request_id,
                },
            },
        )
```

Example error responses:

```json
// 400 - Schema Validation
{
  "error": {
    "code": "SCHEMA_VALIDATION_ERROR",
    "message": "Schema validation failed",
    "details": {
      "errors": [
        "Missing required attribute: hostname",
        "Attribute 'ip_address': invalid IPv4 address"
      ]
    },
    "request_id": "01914a3b-7c4e-7f8a-b2d1-3e4f5a6b7c8d"
  }
}

// 404 - Node Not Found
{
  "error": {
    "code": "NODE_NOT_FOUND",
    "message": "Node 'Device/abc-123' not found",
    "details": {
      "node_type": "Device",
      "node_id": "abc-123"
    },
    "request_id": "01914a3b-8d5f-7f8a-b2d1-4e5f6a7b8c9d"
  }
}

// 409 - Cardinality Violation
{
  "error": {
    "code": "CARDINALITY_VIOLATION",
    "message": "Cardinality constraint 'source_max=1' violated for edge type 'PRIMARY_INTERFACE'",
    "details": {
      "edge_type": "PRIMARY_INTERFACE",
      "constraint": "source_max=1",
      "source_id": null,
      "target_id": "iface-456"
    },
    "request_id": "01914a3b-9e60-7f8a-b2d1-5f6a7b8c9d0e"
  }
}
```

### Request Correlation

Every request carries a correlation ID from the `RequestIDMiddleware`. This ID
propagates through:

1. **Logs** -- Structured log records include `request_id` via a logging filter.
2. **Events** -- The `EventEnvelope.correlation_id` field carries the request ID.
3. **Error responses** -- The `request_id` is returned in every error body.
4. **Downstream calls** -- If NetGraphy calls external services, the request ID is forwarded as `X-Request-ID`.

```python
# netgraphy/core/logging.py

import logging
import contextvars

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    root.addFilter(RequestIDFilter())
```

The `AuthMiddleware` sets the context variable so that all log output within a
request automatically includes the correlation ID:

```python
# Inside AuthMiddleware.dispatch():
from netgraphy.core.logging import request_id_var

request_id_var.set(request.state.request_id)
```
