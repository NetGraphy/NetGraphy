"""Tests for the schema registry."""

import pytest

from packages.schema_engine.registry import SchemaRegistry


@pytest.fixture
async def loaded_registry():
    """Registry loaded with core schemas and mixins."""
    registry = SchemaRegistry()
    await registry.load_from_directories(["schemas/core", "schemas/mixins"])
    return registry


class TestSchemaRegistry:
    """Test schema registry loading and queries."""

    @pytest.mark.asyncio
    async def test_load_returns_counts(self):
        registry = SchemaRegistry()
        counts = await registry.load_from_directories(["schemas/core", "schemas/mixins"])
        assert counts["node_types"] > 0
        assert counts["edge_types"] > 0
        assert counts["mixins"] > 0

    @pytest.mark.asyncio
    async def test_get_node_type(self, loaded_registry):
        registry = await loaded_registry
        device = registry.get_node_type("Device")
        assert device is not None
        assert device.metadata.name == "Device"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, loaded_registry):
        registry = await loaded_registry
        assert registry.get_node_type("DoesNotExist") is None

    @pytest.mark.asyncio
    async def test_mixin_resolution(self, loaded_registry):
        """Mixin attributes should be merged into node types."""
        registry = await loaded_registry
        device = registry.get_node_type("Device")
        # lifecycle_mixin should add created_at, updated_at, etc.
        assert "created_at" in device.attributes
        assert "updated_at" in device.attributes

    @pytest.mark.asyncio
    async def test_categories(self, loaded_registry):
        registry = await loaded_registry
        categories = registry.get_categories()
        assert len(categories) > 0
        category_names = [c["name"] for c in categories]
        assert "Infrastructure" in category_names

    @pytest.mark.asyncio
    async def test_validate_node_properties(self, loaded_registry):
        registry = await loaded_registry
        # Missing required hostname
        errors = registry.validate_node_properties("Device", {"status": "active", "role": "router"})
        assert any("hostname" in e for e in errors)

        # Valid properties
        errors = registry.validate_node_properties("Device", {
            "hostname": "test-device",
            "status": "active",
            "role": "router",
        })
        # Should have no errors for missing required (hostname is present)
        hostname_errors = [e for e in errors if "hostname" in e.lower() and "missing" in e.lower()]
        assert len(hostname_errors) == 0

    @pytest.mark.asyncio
    async def test_get_indexes(self, loaded_registry):
        registry = await loaded_registry
        indexes = registry.get_indexes_for_type("Device")
        assert len(indexes) > 0
        indexed_props = [idx["property"] for idx in indexes]
        assert "hostname" in indexed_props
