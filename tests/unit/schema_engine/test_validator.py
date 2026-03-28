"""Tests for schema validation."""

from packages.schema_engine.validators.schema_validator import validate_schema_file


class TestSchemaValidator:
    def test_valid_node_type(self):
        raw = {
            "kind": "NodeType",
            "metadata": {"name": "TestNode"},
            "attributes": {
                "name": {"type": "string", "required": True},
            },
        }
        errors = validate_schema_file(raw)
        assert errors == []

    def test_missing_kind(self):
        errors = validate_schema_file({"metadata": {"name": "test"}})
        assert any("kind" in e.lower() for e in errors)

    def test_missing_name(self):
        errors = validate_schema_file({"kind": "NodeType", "metadata": {}})
        assert any("name" in e.lower() for e in errors)

    def test_reserved_attribute_name(self):
        raw = {
            "kind": "NodeType",
            "metadata": {"name": "TestNode"},
            "attributes": {
                "id": {"type": "string"},
            },
        }
        errors = validate_schema_file(raw)
        assert any("reserved" in e.lower() for e in errors)

    def test_unique_on_non_indexable_type(self):
        raw = {
            "kind": "NodeType",
            "metadata": {"name": "TestNode"},
            "attributes": {
                "data": {"type": "json", "unique": True},
            },
        }
        errors = validate_schema_file(raw)
        assert any("unique" in e.lower() for e in errors)

    def test_enum_without_values(self):
        raw = {
            "kind": "NodeType",
            "metadata": {"name": "TestNode"},
            "attributes": {
                "status": {"type": "enum"},
            },
        }
        errors = validate_schema_file(raw)
        assert any("enum" in e.lower() for e in errors)

    def test_edge_missing_source(self):
        raw = {
            "kind": "EdgeType",
            "metadata": {"name": "TEST_EDGE"},
            "target": {"node_types": ["B"]},
        }
        errors = validate_schema_file(raw)
        assert any("source" in e.lower() for e in errors)

    def test_empty_enum_type(self):
        raw = {
            "kind": "EnumType",
            "metadata": {"name": "EmptyEnum"},
            "values": [],
        }
        errors = validate_schema_file(raw)
        assert any("value" in e.lower() for e in errors)
