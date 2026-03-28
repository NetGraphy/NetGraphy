"""FastAPI dependency injection providers.

Provides ``Depends()``-compatible callables for injecting singletons
(Neo4j driver, schema registry, event bus, RBAC checker) and per-request
service instances into route handlers.

Singletons are initialised during the application lifespan and stored as
module-level variables.  Service factories compose singletons into
domain-specific orchestrators that enforce the
validate -> authorize -> execute -> audit -> emit pipeline.
"""

from __future__ import annotations

from fastapi import Depends

from packages.auth.middleware import (
    get_auth_context,
    get_optional_auth_context,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.events.bus import EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.graph_db.repositories.edge_repository import EdgeRepository
from packages.graph_db.repositories.node_repository import NodeRepository
from packages.schema_engine.registry import SchemaRegistry

# Re-export auth dependencies so routers can import from a single location.
get_auth_context = get_auth_context
get_optional_auth_context = get_optional_auth_context

# --------------------------------------------------------------------------- #
#  Module-level singletons (set during app lifespan)                           #
# --------------------------------------------------------------------------- #

_driver: Neo4jDriver | None = None
_registry: SchemaRegistry | None = None
_event_bus: EventBus | None = None
_rbac: PermissionChecker | None = None


def init_dependencies(
    driver: Neo4jDriver,
    registry: SchemaRegistry,
    event_bus: EventBus,
) -> None:
    """Initialise module singletons.  Called once from the app lifespan."""
    global _driver, _registry, _event_bus, _rbac
    _driver = driver
    _registry = registry
    _event_bus = event_bus
    _rbac = PermissionChecker()


# --------------------------------------------------------------------------- #
#  Singleton providers                                                         #
# --------------------------------------------------------------------------- #

def get_graph_driver() -> Neo4jDriver:
    """Return the Neo4j driver singleton.

    Raises:
        RuntimeError: If called before ``init_dependencies``.
    """
    if _driver is None:
        raise RuntimeError(
            "Neo4j driver not initialised. "
            "Ensure init_dependencies() is called during app lifespan."
        )
    return _driver


def get_schema_registry() -> SchemaRegistry:
    """Return the schema registry singleton.

    Raises:
        RuntimeError: If called before ``init_dependencies``.
    """
    if _registry is None:
        raise RuntimeError(
            "Schema registry not initialised. "
            "Ensure init_dependencies() is called during app lifespan."
        )
    return _registry


def get_event_bus() -> EventBus:
    """Return the event bus singleton.

    Raises:
        RuntimeError: If called before ``init_dependencies``.
    """
    if _event_bus is None:
        raise RuntimeError(
            "Event bus not initialised. "
            "Ensure init_dependencies() is called during app lifespan."
        )
    return _event_bus


def get_rbac() -> PermissionChecker:
    """Return the RBAC permission checker singleton.

    Raises:
        RuntimeError: If called before ``init_dependencies``.
    """
    if _rbac is None:
        raise RuntimeError(
            "RBAC checker not initialised. "
            "Ensure init_dependencies() is called during app lifespan."
        )
    return _rbac


# --------------------------------------------------------------------------- #
#  Repository factories                                                        #
# --------------------------------------------------------------------------- #

def get_node_repository(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> NodeRepository:
    """Build a NodeRepository for the current request."""
    return NodeRepository(driver=driver, registry=registry)


def get_edge_repository(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
) -> EdgeRepository:
    """Build an EdgeRepository for the current request."""
    return EdgeRepository(driver=driver, registry=registry)


# --------------------------------------------------------------------------- #
#  Service factories                                                           #
# --------------------------------------------------------------------------- #

def get_node_service(
    repo: NodeRepository = Depends(get_node_repository),
    registry: SchemaRegistry = Depends(get_schema_registry),
    events: EventBus = Depends(get_event_bus),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Build a NodeService for the current request.

    Returns:
        A fully-wired :class:`NodeService` instance.
    """
    from netgraphy_api.services.node_service import NodeService

    return NodeService(repo=repo, registry=registry, events=events, rbac=rbac)


def get_edge_service(
    repo: EdgeRepository = Depends(get_edge_repository),
    node_repo: NodeRepository = Depends(get_node_repository),
    registry: SchemaRegistry = Depends(get_schema_registry),
    events: EventBus = Depends(get_event_bus),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Build an EdgeService for the current request.

    The edge service requires a :class:`NodeRepository` to validate
    that source/target nodes exist and match the allowed types for the
    edge definition.

    Returns:
        A fully-wired :class:`EdgeService` instance.
    """
    from netgraphy_api.services.edge_service import EdgeService

    return EdgeService(
        repo=repo, node_repo=node_repo, registry=registry,
        events=events, rbac=rbac,
    )


def get_query_service(
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
    events: EventBus = Depends(get_event_bus),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Build a QueryService for the current request.

    Returns:
        A fully-wired :class:`QueryService` instance.
    """
    from netgraphy_api.services.query_service import QueryService

    return QueryService(driver=driver, registry=registry, events=events, rbac=rbac)
