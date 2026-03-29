"""YAML schema file loader.

Reads schema YAML files from directories and converts them into typed
schema definition models. Handles mixins, enums, node types, and edge types.
"""

from pathlib import Path
from typing import Any

import yaml

from packages.schema_engine.models import (
    AttributeDefinition,
    EdgeTypeDefinition,
    EnumTypeDefinition,
    MixinDefinition,
    NodeTypeDefinition,
    SchemaKind,
    SchemaMetadata,
    UIAttributeMetadata,
)


def load_schema_file(path: Path) -> list[dict[str, Any]]:
    """Load and parse a YAML schema file, supporting multi-document files."""
    with open(path) as f:
        docs = list(yaml.safe_load_all(f))
    return [doc for doc in docs if doc is not None]


def parse_attributes(raw_attrs: dict[str, Any]) -> dict[str, AttributeDefinition]:
    """Parse raw attribute dictionaries into AttributeDefinition models."""
    attributes = {}
    for attr_name, attr_data in (raw_attrs or {}).items():
        ui_data = attr_data.pop("ui", {})
        ui = UIAttributeMetadata(**ui_data) if ui_data else UIAttributeMetadata()
        attributes[attr_name] = AttributeDefinition(name=attr_name, ui=ui, **attr_data)
    return attributes


def parse_schema_object(raw: dict[str, Any]) -> NodeTypeDefinition | EdgeTypeDefinition | MixinDefinition | EnumTypeDefinition:
    """Parse a raw YAML dict into the appropriate schema definition model."""
    kind = raw.get("kind")
    metadata = SchemaMetadata(**raw.get("metadata", {}))

    if kind == SchemaKind.NODE_TYPE:
        return NodeTypeDefinition(
            kind=kind,
            version=raw.get("version", "v1"),
            metadata=metadata,
            attributes=parse_attributes(raw.get("attributes", {})),
            mixins=raw.get("mixins", []),
            detail_tabs=raw.get("detail_tabs", []),
            search=raw.get("search", {}),
            graph=raw.get("graph", {}),
            api=raw.get("api", {}),
            permissions=raw.get("permissions", {}),
        )

    elif kind == SchemaKind.EDGE_TYPE:
        return EdgeTypeDefinition(
            kind=kind,
            version=raw.get("version", "v1"),
            metadata=metadata,
            source=raw.get("source", {}),
            target=raw.get("target", {}),
            cardinality=raw.get("cardinality", "many_to_many"),
            inverse_name=raw.get("inverse_name"),
            attributes=parse_attributes(raw.get("attributes", {})),
            constraints=raw.get("constraints", {}),
            graph=raw.get("graph", {}),
            api=raw.get("api", {}),
            permissions=raw.get("permissions", {}),
        )

    elif kind == SchemaKind.MIXIN:
        return MixinDefinition(
            kind=kind,
            version=raw.get("version", "v1"),
            metadata=metadata,
            attributes=parse_attributes(raw.get("attributes", {})),
        )

    elif kind == SchemaKind.ENUM_TYPE:
        return EnumTypeDefinition(
            kind=kind,
            version=raw.get("version", "v1"),
            metadata=metadata,
            values=raw.get("values", []),
        )

    else:
        raise ValueError(f"Unknown schema kind: {kind}")


def load_directory(directory: str | Path) -> list:
    """Load all YAML schema files from a directory recursively.

    Returns a list of parsed schema definition objects.
    """
    path = Path(directory)
    if not path.exists():
        return []

    definitions = []
    for yaml_file in sorted(path.rglob("*.yaml")):
        docs = load_schema_file(yaml_file)
        for raw in docs:
            if raw and "kind" in raw:
                definitions.append(parse_schema_object(raw))
    for yml_file in sorted(path.rglob("*.yml")):
        docs = load_schema_file(yml_file)
        for raw in docs:
            if raw and "kind" in raw:
                definitions.append(parse_schema_object(raw))

    return definitions
