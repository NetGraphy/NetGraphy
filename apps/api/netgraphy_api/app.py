"""FastAPI application factory.

Creates and configures the FastAPI application with:
- Lifespan-managed singletons (Neo4j, schema registry, event bus)
- Authentication middleware (JWT Bearer via AuthMiddleware)
- CORS and request-ID middleware
- Global exception handlers
- All API routers
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from netgraphy_api.config import settings
from netgraphy_api.dependencies import init_dependencies
from netgraphy_api.exceptions import register_exception_handlers
from netgraphy_api.middleware.request_id import RequestIdMiddleware
from netgraphy_api.routers import (
    audit,
    auth,
    dev,
    edges,
    git_sources,
    health,
    iac,
    ingestion,
    jobs,
    nodes,
    parsers,
    queries,
    schema,
)
from packages.auth.middleware import AuthMiddleware
from packages.events.bus import EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle.

    Startup:
        1. Create and verify the Neo4j driver.
        2. Load the schema registry from YAML directories.
        3. Connect the NATS-backed event bus (falls back to local dispatch).
        4. Wire all singletons into the dependency-injection layer.

    Shutdown:
        1. Close the event bus (drain NATS subscriptions).
        2. Close the Neo4j driver (release connection pool).
    """
    logger.info("Starting NetGraphy API", version="0.1.0")

    # --- Neo4j ----------------------------------------------------------------
    driver = Neo4jDriver(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
        max_connection_pool_size=settings.neo4j_max_connection_pool_size,
    )
    await driver.verify_connectivity()
    logger.info("Neo4j connected", uri=settings.neo4j_uri)

    # --- Schema Registry ------------------------------------------------------
    registry = SchemaRegistry()
    schema_count = await registry.load_from_directories(settings.schema_dirs)
    logger.info(
        "Schema registry loaded",
        node_types=schema_count["node_types"],
        edge_types=schema_count["edge_types"],
    )

    # --- Event Bus ------------------------------------------------------------
    event_bus = EventBus()
    await event_bus.connect(settings.nats_url)

    # --- Dependency Injection -------------------------------------------------
    init_dependencies(driver=driver, registry=registry, event_bus=event_bus)
    app.state.neo4j_driver = driver  # Used by auth middleware for API token lookup
    logger.info("Dependencies initialised")

    # Admin user seeding is handled by the auth router's _get_or_create_admin_user()
    # which runs on first login attempt. Default credentials: admin / admin

    # Delete any existing admin users with bad password hashes (migration fix)
    try:
        await driver.execute_write(
            "MATCH (u:_User {username: 'admin'}) DETACH DELETE u", {}
        )
        logger.info("Cleared stale admin users for re-seeding")
    except Exception:
        pass

    yield

    # --- Shutdown -------------------------------------------------------------
    await event_bus.close()
    logger.info("Event bus closed")

    await driver.close()
    logger.info("Neo4j driver closed")

    logger.info("NetGraphy API stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Graph-native network source of truth and automation platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    # --- Exception Handlers ---------------------------------------------------
    register_exception_handlers(app)

    # --- Middleware (outermost first) -----------------------------------------
    # 1. CORS — must be outermost so pre-flight OPTIONS are handled early.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Auth — validates JWT Bearer tokens on protected routes.
    app.add_middleware(
        AuthMiddleware,
        secret_key=settings.secret_key,
        algorithm=settings.algorithm,
    )

    # 3. Request ID — attaches a correlation ID to every request/response.
    app.add_middleware(RequestIdMiddleware)

    # --- Routers --------------------------------------------------------------
    prefix = settings.api_prefix
    app.include_router(health.router, tags=["Health"])
    app.include_router(schema.router, prefix=f"{prefix}/schema", tags=["Schema"])
    app.include_router(nodes.router, prefix=f"{prefix}/objects", tags=["Nodes"])
    app.include_router(edges.router, prefix=f"{prefix}/edges", tags=["Edges"])
    app.include_router(queries.router, prefix=f"{prefix}/query", tags=["Query"])
    app.include_router(parsers.router, prefix=f"{prefix}/parsers", tags=["Parsers"])
    app.include_router(
        ingestion.router, prefix=f"{prefix}/ingestion", tags=["Ingestion"]
    )
    app.include_router(jobs.router, prefix=f"{prefix}/jobs", tags=["Jobs"])
    app.include_router(
        git_sources.router, prefix=f"{prefix}/git-sources", tags=["Git Sources"]
    )
    app.include_router(auth.router, prefix=f"{prefix}/auth", tags=["Auth"])
    app.include_router(audit.router, prefix=f"{prefix}/audit", tags=["Audit"])
    app.include_router(
        dev.router, prefix=f"{prefix}/dev", tags=["Dev Workbench"]
    )
    app.include_router(
        iac.router, prefix=f"{prefix}/iac", tags=["Infrastructure as Code"]
    )

    return app


app = create_app()
