"""Tests for schema property validation — the hardened validation system."""

import pytest

from packages.schema_engine.registry import SchemaRegistry


@pytest.fixture
def registry():
    """Sync fixture that loads registry (used synchronously via run loop)."""
    import asyncio
    reg = SchemaRegistry()
    asyncio.get_event_loop().run_until_complete(
        reg.load_from_directories(["schemas/core", "schemas/mixins"])
    )
    return reg


class TestPropertyValidation:
    """Test validate_node_properties with the hardened validator."""

    def test_valid_device(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test-router-01",
            "status": "active",
            "role": "router",
            "management_ip": "10.1.1.1",
        })
        assert errors == []

    def test_missing_required(self, registry):
        errors = registry.validate_node_properties("Device", {
            "status": "active",
            "role": "router",
        })
        assert any("hostname" in e for e in errors)

    def test_unknown_attribute(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test",
            "status": "active",
            "role": "router",
            "nonexistent_field": "value",
        })
        assert any("Unknown attribute" in e for e in errors)

    def test_invalid_enum_value(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test",
            "status": "INVALID_STATUS",
            "role": "router",
        })
        assert any("not in allowed values" in e for e in errors)

    def test_invalid_ip_address(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test",
            "status": "active",
            "role": "router",
            "management_ip": "not-an-ip",
        })
        assert any("not a valid IP address" in e for e in errors)

    def test_valid_ip_address(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test",
            "status": "active",
            "role": "router",
            "management_ip": "192.168.1.1",
        })
        ip_errors = [e for e in errors if "IP address" in e]
        assert ip_errors == []

    def test_string_max_length(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "x" * 300,
            "status": "active",
            "role": "router",
        })
        assert any("max_length" in e for e in errors)

    def test_wrong_type_integer(self, registry):
        errors = registry.validate_node_properties("Interface", {
            "name": "Gi0/0/1",
            "interface_type": "physical",
            "enabled": True,
            "speed_mbps": "not-a-number",
        })
        assert any("expected integer" in e for e in errors)

    def test_boolean_not_treated_as_int(self, registry):
        errors = registry.validate_node_properties("Interface", {
            "name": "Gi0/0/1",
            "interface_type": "physical",
            "enabled": True,
            "speed_mbps": True,  # bool should not be valid as integer
        })
        assert any("expected integer" in e for e in errors)

    def test_list_string_type(self, registry):
        errors = registry.validate_node_properties("Interface", {
            "name": "Gi0/0/1",
            "interface_type": "physical",
            "enabled": True,
            "ip_addresses": ["10.1.1.1/24", "10.1.1.2/24"],
        })
        ip_list_errors = [e for e in errors if "ip_addresses" in e]
        assert ip_list_errors == []

    def test_list_wrong_element_type(self, registry):
        errors = registry.validate_node_properties("Interface", {
            "name": "Gi0/0/1",
            "interface_type": "physical",
            "enabled": True,
            "ip_addresses": [123, 456],
        })
        assert any("expected string" in e for e in errors)

    def test_null_optional_value(self, registry):
        errors = registry.validate_node_properties("Device", {
            "hostname": "test",
            "status": "active",
            "role": "router",
            "serial_number": None,
        })
        null_errors = [e for e in errors if "serial_number" in e and "null" in e.lower()]
        assert null_errors == []

    def test_unknown_node_type(self, registry):
        errors = registry.validate_node_properties("NonexistentType", {})
        assert any("Unknown node type" in e for e in errors)


class TestRequireMethods:
    """Test require_node_type and require_edge_type."""

    def test_require_existing_node_type(self, registry):
        defn = registry.require_node_type("Device")
        assert defn.metadata.name == "Device"

    def test_require_nonexistent_node_type_raises(self, registry):
        from apps.api.netgraphy_api.exceptions import SchemaNotFoundError
        with pytest.raises(SchemaNotFoundError):
            registry.require_node_type("Nonexistent")

    def test_require_existing_edge_type(self, registry):
        defn = registry.require_edge_type("HAS_INTERFACE")
        assert defn.metadata.name == "HAS_INTERFACE"

    def test_get_edges_for_node_type(self, registry):
        edges = registry.get_edges_for_node_type("Device")
        edge_names = [e.metadata.name for e in edges]
        assert "HAS_INTERFACE" in edge_names
        assert "LOCATED_IN" in edge_names


class TestEdgePropertyValidation:
    """Test validate_edge_properties."""

    def test_valid_connected_to_edge(self, registry):
        errors = registry.validate_edge_properties("CONNECTED_TO", {
            "cable_type": "fiber_smf",
        })
        assert errors == []

    def test_invalid_edge_enum(self, registry):
        errors = registry.validate_edge_properties("CONNECTED_TO", {
            "cable_type": "invalid_cable",
        })
        assert any("not in allowed values" in e for e in errors)

    def test_unknown_edge_type(self, registry):
        errors = registry.validate_edge_properties("NONEXISTENT_EDGE", {})
        assert any("Unknown edge type" in e for e in errors)
