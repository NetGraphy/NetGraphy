"""Authentication and RBAC endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/login")
async def login(body: dict[str, Any]):
    """Authenticate and return a JWT token.

    Supports local auth and redirects to OIDC providers.
    """
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")

    # TODO: Validate credentials, generate JWT
    return {
        "data": {
            "access_token": "placeholder",
            "token_type": "bearer",
            "expires_in": 3600,
        }
    }


@router.post("/token")
async def refresh_token(body: dict[str, Any]):
    """Refresh an access token."""
    # TODO: Validate refresh token, issue new access token
    return {"data": {"access_token": "placeholder", "token_type": "bearer"}}


@router.get("/me")
async def get_current_user():
    """Get the current authenticated user's profile."""
    # TODO: Extract user from JWT, return profile
    return {
        "data": {
            "id": "placeholder",
            "username": "admin",
            "role": "admin",
            "email": "admin@netgraphy.local",
        }
    }


@router.get("/rbac/roles")
async def list_roles():
    """List available roles and their permissions."""
    return {
        "data": [
            {"name": "viewer", "description": "Read-only access"},
            {"name": "editor", "description": "Create and update objects"},
            {"name": "operator", "description": "Run jobs and manage automation"},
            {"name": "admin", "description": "Full administrative access"},
        ]
    }
