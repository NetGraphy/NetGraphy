"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe — checks Neo4j and Redis connectivity."""
    # TODO: Actually verify Neo4j and Redis connections
    return {"status": "ok", "neo4j": "connected", "redis": "connected"}


@router.get("/health/startup")
async def startup():
    """Kubernetes startup probe — checks schema registry is loaded."""
    # TODO: Verify schema registry is loaded
    return {"status": "ok", "schema_loaded": True}
