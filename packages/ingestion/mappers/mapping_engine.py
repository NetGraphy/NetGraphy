"""Mapping Engine — transforms parsed records into graph mutations.

Reads YAML mapping definitions and applies them to parsed command output
to produce node and edge upsert operations for the graph database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


@dataclass
class GraphMutation:
    """A single graph mutation to apply."""
    operation: str  # "upsert_node", "upsert_edge"
    node_type: str | None = None
    edge_type: str | None = None
    match_on: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    source_match: dict[str, Any] | None = None
    target_match: dict[str, Any] | None = None


@dataclass
class MappingResult:
    """Result of applying mappings to parsed records."""
    mutations: list[GraphMutation]
    errors: list[str]
    record_count: int


def load_mapping(path: str) -> dict[str, Any]:
    """Load a YAML mapping definition file."""
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_template(template: str, parsed_record: dict[str, Any]) -> str:
    """Resolve a Jinja-like template expression against parsed data.

    Supports simple {{ parsed.field_name }} syntax.
    """
    def replacer(match):
        expr = match.group(1).strip()
        if expr.startswith("parsed."):
            field_name = expr[len("parsed."):]
            value = parsed_record.get(field_name, "")
            return str(value) if value is not None else ""
        return match.group(0)

    return re.sub(r"\{\{\s*(.+?)\s*\}\}", replacer, template)


def apply_mapping(
    mapping_def: dict[str, Any],
    parsed_records: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> MappingResult:
    """Apply a mapping definition to parsed records.

    Args:
        mapping_def: The loaded YAML mapping definition.
        parsed_records: List of parsed records from TextFSM.
        context: Additional context (e.g., device hostname, job run ID).

    Returns:
        MappingResult with list of GraphMutation operations.
    """
    mutations: list[GraphMutation] = []
    errors: list[str] = []
    context = context or {}

    for record in parsed_records:
        # Merge context into record for template resolution
        full_record = {**context, **record}

        for mapping in mapping_def.get("mappings", []):
            try:
                mutation = _process_mapping_entry(mapping, full_record)
                if mutation:
                    mutations.append(mutation)
            except Exception as e:
                errors.append(f"Mapping error for record {record}: {e}")

    return MappingResult(
        mutations=mutations,
        errors=errors,
        record_count=len(parsed_records),
    )


def _process_mapping_entry(
    mapping: dict[str, Any],
    record: dict[str, Any],
) -> GraphMutation | None:
    """Process a single mapping entry against a record."""

    if "target_node_type" in mapping:
        # Node upsert mapping
        match_on = {}
        for field_name in mapping.get("match_on", []):
            match_on[field_name] = resolve_template(
                mapping["attributes"].get(field_name, f"{{{{ parsed.{field_name} }}}}"),
                record,
            )

        attributes = {}
        for attr_name, template in mapping.get("attributes", {}).items():
            attributes[attr_name] = resolve_template(template, record)

        return GraphMutation(
            operation="upsert_node",
            node_type=mapping["target_node_type"],
            match_on=match_on,
            attributes=attributes,
        )

    elif "target_edge_type" in mapping:
        # Edge upsert mapping
        source = mapping.get("source", {})
        target = mapping.get("target", {})

        source_match = {}
        for field_name, template in source.get("match_on", {}).items():
            source_match[field_name] = resolve_template(template, record)

        target_match = {}
        for field_name, template in target.get("match_on", {}).items():
            target_match[field_name] = resolve_template(template, record)

        return GraphMutation(
            operation="upsert_edge",
            edge_type=mapping["target_edge_type"],
            source_match=source_match,
            target_match=target_match,
        )

    return None
