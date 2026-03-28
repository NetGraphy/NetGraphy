"""Tests for the YAML schema loader."""

import pytest
from pathlib import Path

from packages.schema_engine.loaders.yaml_loader import load_directory, parse_schema_object
from packages.schema_engine.models import NodeTypeDefinition, EdgeTypeDefinition, MixinDefinition


SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent / "schemas"


class TestYAMLLoader:
    """Test schema YAML file loading and parsing."""

    def test_load_core_schemas(self):
        """Core schema directory should load without errors."""
        definitions = load_directory(SCHEMAS_DIR / "core")
        assert len(definitions) > 0

    def test_load_mixins(self):
        """Mixin directory should load mixin definitions."""
        definitions = load_directory(SCHEMAS_DIR / "mixins")
        assert any(isinstance(d, MixinDefinition) for d in definitions)

    def test_device_node_type_loads(self):
        """Device node type should load with expected attributes."""
        definitions = load_directory(SCHEMAS_DIR / "core")
        device_defs = [d for d in definitions if isinstance(d, NodeTypeDefinition) and d.name == "Device"]
        assert len(device_defs) == 1

        device = device_defs[0]
        assert "hostname" in device.attributes
        assert device.attributes["hostname"].required is True
        assert device.attributes["hostname"].unique is True
        assert device.metadata.category == "Infrastructure"

    def test_edge_types_load(self):
        """Edge type definitions should load with source/target types."""
        definitions = load_directory(SCHEMAS_DIR / "core")
        edge_defs = [d for d in definitions if isinstance(d, EdgeTypeDefinition)]
        assert len(edge_defs) > 0

        # Find HAS_INTERFACE edge
        has_interface = [e for e in edge_defs if e.name == "HAS_INTERFACE"]
        assert len(has_interface) == 1
        assert "Device" in has_interface[0].source.node_types
        assert "Interface" in has_interface[0].target.node_types

    def test_nonexistent_directory_returns_empty(self):
        """Loading from a nonexistent directory should return empty list."""
        definitions = load_directory("/nonexistent/path")
        assert definitions == []


class TestParseSchemaObject:
    """Test parsing individual schema objects from raw dicts."""

    def test_parse_node_type(self):
        raw = {
            "kind": "NodeType",
            "version": "v1",
            "metadata": {"name": "TestNode", "description": "A test node"},
            "attributes": {
                "name": {"type": "string", "required": True},
            },
        }
        result = parse_schema_object(raw)
        assert isinstance(result, NodeTypeDefinition)
        assert result.name == "TestNode"
        assert "name" in result.attributes

    def test_parse_unknown_kind_raises(self):
        raw = {"kind": "Unknown", "metadata": {"name": "test"}}
        with pytest.raises(ValueError, match="Unknown schema kind"):
            parse_schema_object(raw)
