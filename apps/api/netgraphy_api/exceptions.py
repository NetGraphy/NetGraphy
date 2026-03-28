"""Domain exception hierarchy and global FastAPI error handlers.

All domain exceptions inherit from NetGraphyError. The global handlers
convert them to consistent JSON error responses with correlation IDs.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger()


# --------------------------------------------------------------------------- #
#  Base Exception                                                              #
# --------------------------------------------------------------------------- #

class NetGraphyError(Exception):
    """Base exception for all NetGraphy domain errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        self.message = message
        self.details = details or []
        super().__init__(message)


# --------------------------------------------------------------------------- #
#  Schema Errors                                                               #
# --------------------------------------------------------------------------- #

class SchemaValidationError(NetGraphyError):
    """Raised when data fails schema validation."""
    status_code = 422
    error_code = "VALIDATION_ERROR"

    def __init__(self, errors: list[str]):
        details = [{"message": e} for e in errors]
        super().__init__(
            message=f"Validation failed: {len(errors)} error(s)",
            details=details,
        )
        self.validation_errors = errors


class SchemaNotFoundError(NetGraphyError):
    """Raised when a node or edge type doesn't exist in the schema."""
    status_code = 404
    error_code = "SCHEMA_NOT_FOUND"

    def __init__(self, kind: str, name: str):
        super().__init__(message=f"{kind} '{name}' not found in schema registry")


class SchemaMigrationError(NetGraphyError):
    """Raised when a schema migration fails."""
    status_code = 409
    error_code = "MIGRATION_ERROR"


# --------------------------------------------------------------------------- #
#  Data Errors                                                                 #
# --------------------------------------------------------------------------- #

class NodeNotFoundError(NetGraphyError):
    """Raised when a node doesn't exist."""
    status_code = 404
    error_code = "NODE_NOT_FOUND"

    def __init__(self, node_type: str, node_id: str):
        super().__init__(message=f"{node_type} node '{node_id}' not found")


class EdgeNotFoundError(NetGraphyError):
    """Raised when an edge doesn't exist."""
    status_code = 404
    error_code = "EDGE_NOT_FOUND"

    def __init__(self, edge_type: str, edge_id: str):
        super().__init__(message=f"{edge_type} edge '{edge_id}' not found")


class CardinalityViolationError(NetGraphyError):
    """Raised when creating an edge would violate cardinality constraints."""
    status_code = 409
    error_code = "CARDINALITY_VIOLATION"


class DuplicateError(NetGraphyError):
    """Raised when a uniqueness constraint is violated."""
    status_code = 409
    error_code = "DUPLICATE_ERROR"


# --------------------------------------------------------------------------- #
#  Auth Errors                                                                 #
# --------------------------------------------------------------------------- #

class AuthenticationError(NetGraphyError):
    """Raised when authentication fails (bad token, expired, etc.)."""
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message=message)


class AuthorizationError(NetGraphyError):
    """Raised when the authenticated user lacks permission."""
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"

    def __init__(self, action: str = "", resource: str = ""):
        msg = "Insufficient permissions"
        if action and resource:
            msg = f"Permission denied: {action} on {resource}"
        super().__init__(message=msg)


# --------------------------------------------------------------------------- #
#  Sync Errors                                                                 #
# --------------------------------------------------------------------------- #

class SyncConflictError(NetGraphyError):
    """Raised when a Git sync has conflicts."""
    status_code = 409
    error_code = "SYNC_CONFLICT"


class SyncSourceNotFoundError(NetGraphyError):
    """Raised when a Git source doesn't exist."""
    status_code = 404
    error_code = "SYNC_SOURCE_NOT_FOUND"


# --------------------------------------------------------------------------- #
#  Query Errors                                                                #
# --------------------------------------------------------------------------- #

class QueryExecutionError(NetGraphyError):
    """Raised when a Cypher query fails to execute."""
    status_code = 400
    error_code = "QUERY_EXECUTION_ERROR"


# --------------------------------------------------------------------------- #
#  Global Error Handlers                                                       #
# --------------------------------------------------------------------------- #

def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(NetGraphyError)
    async def netgraphy_error_handler(request: Request, exc: NetGraphyError):
        correlation_id = getattr(request.state, "request_id", "unknown")
        logger.warning(
            "Domain error",
            error_code=exc.error_code,
            message=exc.message,
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                    "correlation_id": correlation_id,
                }
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        correlation_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "BAD_REQUEST",
                    "message": str(exc),
                    "details": [],
                    "correlation_id": correlation_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        correlation_id = getattr(request.state, "request_id", "unknown")
        logger.exception(
            "Unhandled error",
            correlation_id=correlation_id,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                    "details": [],
                    "correlation_id": correlation_id,
                }
            },
        )
