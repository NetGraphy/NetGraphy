"""Integration tests for the NetGraphy API.

These tests exercise the full request/response cycle through FastAPI's
TestClient. They require a running Neo4j instance (use docker compose
or testcontainers).

Run with: PYTHONPATH=. pytest tests/integration/ -v
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

# Skip integration tests if NEO4J_URI is not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("NETGRAPHY_NEO4J_URI"),
    reason="Integration tests require NETGRAPHY_NEO4J_URI",
)


@pytest.fixture(scope="module")
def client():
    """Create a FastAPI TestClient with the real app."""
    from fastapi.testclient import TestClient
    from netgraphy_api.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Login and return auth headers."""
    resp = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestHealthEndpoints:
    def test_liveness(self, client):
        resp = client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_readiness(self, client):
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["neo4j"] == "connected"
        assert data["schema_loaded"] is True

    def test_startup(self, client):
        resp = client.get("/health/startup")
        assert resp.status_code == 200
        assert resp.json()["schema_loaded"] is True


class TestSchemaEndpoints:
    def test_list_node_types(self, client):
        resp = client.get("/api/v1/schema/node-types")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 9  # Device, Interface, Location, etc.

    def test_get_node_type(self, client):
        resp = client.get("/api/v1/schema/node-types/Device")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["metadata"]["name"] == "Device"
        assert "hostname" in data["attributes"]

    def test_nonexistent_node_type_returns_404(self, client):
        resp = client.get("/api/v1/schema/node-types/DoesNotExist")
        assert resp.status_code == 404

    def test_ui_metadata(self, client):
        resp = client.get("/api/v1/schema/ui-metadata")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "node_types" in data
        assert "edge_types" in data
        assert "categories" in data
        assert len(data["categories"]) >= 3


class TestAuthEndpoints:
    def test_login_success(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "wrong",
        })
        assert resp.status_code == 401

    def test_me_with_token(self, client, auth_headers):
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        user = resp.json()["data"]
        assert user["username"] == "admin"
        assert user["role"] == "admin"

    def test_me_without_token(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_rbac_roles(self, client, auth_headers):
        resp = client.get("/api/v1/auth/rbac/roles", headers=auth_headers)
        assert resp.status_code == 200
        roles = resp.json()["data"]
        role_names = [r["name"] for r in roles]
        assert "viewer" in role_names
        assert "admin" in role_names


class TestNodeCRUD:
    """Test node create/read/update/delete flow."""

    def test_create_device(self, client, auth_headers):
        resp = client.post("/api/v1/objects/Device", json={
            "hostname": "test-device-001",
            "status": "planned",
            "role": "router",
            "management_ip": "10.99.99.1",
        }, headers=auth_headers)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        data = resp.json()["data"]
        assert data["id"]
        assert data["hostname"] == "test-device-001" or data.get("type") == "Device"

    def test_list_devices(self, client, auth_headers):
        resp = client.get("/api/v1/objects/Device", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "meta" in data

    def test_create_invalid_enum(self, client, auth_headers):
        resp = client.post("/api/v1/objects/Device", json={
            "hostname": "invalid-enum-device",
            "status": "INVALID_STATUS",
            "role": "router",
        }, headers=auth_headers)
        assert resp.status_code == 422  # Validation error

    def test_nonexistent_node_type(self, client, auth_headers):
        resp = client.get("/api/v1/objects/DoesNotExist", headers=auth_headers)
        assert resp.status_code == 404


class TestQueryExecution:
    def test_cypher_query(self, client, auth_headers):
        resp = client.post("/api/v1/query/cypher", json={
            "query": "MATCH (n) RETURN labels(n) as type, count(n) as count",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "rows" in data
        assert "columns" in data

    def test_empty_query_rejected(self, client, auth_headers):
        resp = client.post("/api/v1/query/cypher", json={
            "query": "",
        }, headers=auth_headers)
        assert resp.status_code in (400, 500)
