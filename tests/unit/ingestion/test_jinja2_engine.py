"""Tests for Jinja2MappingEngine (packages/ingestion/mappers/jinja2_engine.py)."""

import pytest

from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine
from packages.ingestion.mappers.mapping_engine import GraphMutation


# ---------------------------------------------------------------------------
# Construction and filter registration
# ---------------------------------------------------------------------------

class TestJinja2MappingEngineInit:
    def test_builtin_filters_registered(self):
        engine = Jinja2MappingEngine()
        # Spot-check a few known filter names
        assert "normalize_interface_name" in engine._env.filters
        assert "to_slug" in engine._env.filters
        assert "mac_format" in engine._env.filters

    def test_register_filter(self):
        engine = Jinja2MappingEngine()
        engine.register_filter("double", lambda x: x * 2)
        assert "double" in engine._env.filters

    def test_register_filters_bulk(self):
        engine = Jinja2MappingEngine()
        engine.register_filters({
            "triple": lambda x: x * 3,
            "negate": lambda x: -x,
        })
        assert "triple" in engine._env.filters
        assert "negate" in engine._env.filters


# ---------------------------------------------------------------------------
# resolve_template
# ---------------------------------------------------------------------------

class TestResolveTemplate:
    def test_simple_variable(self):
        engine = Jinja2MappingEngine()
        result = engine.resolve_template("{{ name }}", {"name": "router1"})
        assert result == "router1"

    def test_parsed_namespace(self):
        engine = Jinja2MappingEngine()
        result = engine.resolve_template(
            "{{ parsed.HOSTNAME }}",
            {"parsed": {"HOSTNAME": "core-rtr-01"}},
        )
        assert result == "core-rtr-01"

    def test_filter_in_template(self):
        engine = Jinja2MappingEngine()
        result = engine.resolve_template(
            "{{ name | to_slug }}",
            {"name": "Cisco IOS-XE"},
        )
        assert result == "cisco_ios_xe"

    def test_interface_filter(self):
        engine = Jinja2MappingEngine()
        result = engine.resolve_template(
            "{{ iface | normalize_interface_name }}",
            {"iface": "Gi0/0/1"},
        )
        assert result == "GigabitEthernet0/0/1"

    def test_strict_undefined_raises(self):
        engine = Jinja2MappingEngine()
        with pytest.raises(Exception):
            engine.resolve_template("{{ nonexistent }}", {})


# ---------------------------------------------------------------------------
# render_mapping — node upserts
# ---------------------------------------------------------------------------

class TestRenderMappingNodes:
    def _make_engine(self):
        return Jinja2MappingEngine()

    def test_basic_node_mapping(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_node_type": "Device",
                    "match_on": ["hostname"],
                    "attributes": {
                        "hostname": "{{ parsed.HOSTNAME }}",
                        "platform": "{{ parsed.PLATFORM }}",
                    },
                }
            ]
        }
        records = [
            {"HOSTNAME": "router1", "PLATFORM": "ios-xe"},
        ]

        result = engine.render_mapping(mapping_def, records)

        assert result.record_count == 1
        assert len(result.mutations) == 1
        assert result.errors == []

        mut = result.mutations[0]
        assert mut.operation == "upsert_node"
        assert mut.node_type == "Device"
        assert mut.match_on == {"hostname": "router1"}
        assert mut.attributes["hostname"] == "router1"
        assert mut.attributes["platform"] == "ios-xe"

    def test_node_mapping_with_filter(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_node_type": "Interface",
                    "match_on": ["name"],
                    "attributes": {
                        "name": "{{ parsed.INTF | normalize_interface_name }}",
                        "speed": "{{ parsed.SPEED }}",
                    },
                }
            ]
        }
        records = [
            {"INTF": "Gi0/0/1", "SPEED": "1000"},
        ]

        result = engine.render_mapping(mapping_def, records)

        assert len(result.mutations) == 1
        mut = result.mutations[0]
        assert mut.attributes["name"] == "GigabitEthernet0/0/1"

    def test_multiple_records(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_node_type": "Device",
                    "match_on": ["hostname"],
                    "attributes": {
                        "hostname": "{{ parsed.HOSTNAME }}",
                    },
                }
            ]
        }
        records = [
            {"HOSTNAME": "router1"},
            {"HOSTNAME": "router2"},
            {"HOSTNAME": "router3"},
        ]

        result = engine.render_mapping(mapping_def, records)

        assert result.record_count == 3
        assert len(result.mutations) == 3
        hostnames = [m.attributes["hostname"] for m in result.mutations]
        assert hostnames == ["router1", "router2", "router3"]


# ---------------------------------------------------------------------------
# render_mapping — edge upserts
# ---------------------------------------------------------------------------

class TestRenderMappingEdges:
    def _make_engine(self):
        return Jinja2MappingEngine()

    def test_basic_edge_mapping(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_edge_type": "HAS_INTERFACE",
                    "source": {
                        "match_on": {
                            "hostname": "{{ parsed.HOSTNAME }}",
                        },
                    },
                    "target": {
                        "match_on": {
                            "name": "{{ parsed.INTF }}",
                        },
                    },
                }
            ]
        }
        records = [
            {"HOSTNAME": "router1", "INTF": "Gi0/0/1"},
        ]

        result = engine.render_mapping(mapping_def, records)

        assert len(result.mutations) == 1
        mut = result.mutations[0]
        assert mut.operation == "upsert_edge"
        assert mut.edge_type == "HAS_INTERFACE"
        assert mut.source_match == {"hostname": "router1"}
        assert mut.target_match == {"name": "Gi0/0/1"}

    def test_edge_with_attributes(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_edge_type": "CONNECTED_TO",
                    "source": {
                        "match_on": {"name": "{{ parsed.LOCAL_INTF }}"},
                    },
                    "target": {
                        "match_on": {"name": "{{ parsed.REMOTE_INTF }}"},
                    },
                    "attributes": {
                        "protocol": "{{ parsed.PROTOCOL }}",
                    },
                }
            ]
        }
        records = [
            {"LOCAL_INTF": "Gi0/0/1", "REMOTE_INTF": "Gi0/0/2", "PROTOCOL": "lldp"},
        ]

        result = engine.render_mapping(mapping_def, records)

        assert len(result.mutations) == 1
        mut = result.mutations[0]
        assert mut.attributes == {"protocol": "lldp"}


# ---------------------------------------------------------------------------
# render_mapping — context and error handling
# ---------------------------------------------------------------------------

class TestRenderMappingContext:
    def _make_engine(self):
        return Jinja2MappingEngine()

    def test_context_variables_available(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_node_type": "Device",
                    "match_on": ["hostname"],
                    "attributes": {
                        "hostname": "{{ parsed.HOSTNAME }}",
                        "source_job": "{{ job_id }}",
                    },
                }
            ]
        }
        records = [{"HOSTNAME": "router1"}]
        context = {"job_id": "run-42"}

        result = engine.render_mapping(mapping_def, records, context)

        assert len(result.mutations) == 1
        assert result.mutations[0].attributes["source_job"] == "run-42"

    def test_errors_collected_not_raised(self):
        engine = self._make_engine()
        mapping_def = {
            "mappings": [
                {
                    "target_node_type": "Device",
                    "match_on": ["hostname"],
                    "attributes": {
                        "hostname": "{{ parsed.NONEXISTENT }}",
                    },
                }
            ]
        }
        records = [{"HOSTNAME": "router1"}]

        result = engine.render_mapping(mapping_def, records)

        # StrictUndefined should cause an error, caught and collected
        assert len(result.errors) == 1
        assert result.record_count == 1
        assert len(result.mutations) == 0

    def test_empty_records(self):
        engine = self._make_engine()
        mapping_def = {"mappings": [{"target_node_type": "Device", "match_on": ["hostname"], "attributes": {"hostname": "{{ parsed.HOSTNAME }}"}}]}

        result = engine.render_mapping(mapping_def, [])

        assert result.record_count == 0
        assert result.mutations == []
        assert result.errors == []

    def test_empty_mappings(self):
        engine = self._make_engine()
        result = engine.render_mapping({"mappings": []}, [{"HOSTNAME": "x"}])

        assert result.record_count == 1
        assert result.mutations == []


# ---------------------------------------------------------------------------
# render_mapping — backward compatibility with resolve_template
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify that the Jinja2 engine produces the same results as the
    original regex-based mapping engine for simple {{ parsed.X }} templates."""

    def test_matches_original_resolve_template(self):
        from packages.ingestion.mappers.mapping_engine import resolve_template

        record = {"HOSTNAME": "router1", "PLATFORM": "ios"}

        # The original function gets the record as flat dict with "parsed." prefix
        result_original = resolve_template("{{ parsed.HOSTNAME }}", record)

        engine = Jinja2MappingEngine()
        result_jinja2 = engine.resolve_template(
            "{{ parsed.HOSTNAME }}", {"parsed": record}
        )

        assert result_original == result_jinja2 == "router1"
