"""FastAPI application factory."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from netgraphy_api.config import settings
from netgraphy_api.dependencies import get_graph_driver, get_schema_registry
from netgraphy_api.middleware.request_id import RequestIdMiddleware
from netgraphy_api.routers import (
    audit,
    auth,
    edges,
    git_sources,
    health,
    ingestion,
    jobs,
    nodes,
    parsers,
    queries,
    schema,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("Starting NetGraphy API", version="0.1.0")

    # Initialize Neo4j driver
    driver = get_graph_driver()
    await driver.verify_connectivity()
    logger.info("Neo4j connected", uri=settings.neo4j_uri)

    # Load schema registry from YAML files
    registry = get_schema_registry()
    schema_count = await registry.load_from_directories(settings.schema_dirs)
    logger.info("Schema registry loaded", node_types=schema_count["node_types"],
                edge_types=schema_count["edge_types"])

    # TODO: Connect to NATS for event bus
    # TODO: Connect to Redis for caching
    # TODO: Initialize MinIO client

    yield

    # Shutdown
    await driver.close()
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

    # --- Middleware ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    # --- Routers ---
    prefix = settings.api_prefix
    app.include_router(health.router, tags=["Health"])
    app.include_router(schema.router, prefix=f"{prefix}/schema", tags=["Schema"])
    app.include_router(nodes.router, prefix=f"{prefix}/objects", tags=["Nodes"])
    app.include_router(edges.router, prefix=f"{prefix}/edges", tags=["Edges"])
    app.include_router(queries.router, prefix=f"{prefix}/query", tags=["Query"])
    app.include_router(parsers.router, prefix=f"{prefix}/parsers", tags=["Parsers"])
    app.include_router(ingestion.router, prefix=f"{prefix}/ingestion", tags=["Ingestion"])
    app.include_router(jobs.router, prefix=f"{prefix}/jobs", tags=["Jobs"])
    app.include_router(git_sources.router, prefix=f"{prefix}/git-sources", tags=["Git Sources"])
    app.include_router(auth.router, prefix=f"{prefix}/auth", tags=["Auth"])
    app.include_router(audit.router, prefix=f"{prefix}/audit", tags=["Audit"])

    return app


app = create_app()
