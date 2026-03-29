"""Schema definition models — the in-memory representation of YAML schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Enums                                                                       #
# --------------------------------------------------------------------------- #

class AttributeType(str, Enum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    DATE = "date"
    JSON = "json"
    IP_ADDRESS = "ip_address"
    CIDR = "cidr"
    MAC_ADDRESS = "mac_address"
    URL = "url"
    EMAIL = "email"
    ENUM = "enum"
    REFERENCE = "reference"
    LIST_STRING = "list[string]"
    LIST_INTEGER = "list[integer]"


class Cardinality(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class SchemaKind(str, Enum):
    NODE_TYPE = "NodeType"
    EDGE_TYPE = "EdgeType"
    MIXIN = "Mixin"
    ENUM_TYPE = "EnumType"


class RiskLevel(str, Enum):
    SAFE = "safe"
    CAUTIOUS = "cautious"
    DANGEROUS = "dangerous"


# --------------------------------------------------------------------------- #
#  UI Metadata                                                                 #
# --------------------------------------------------------------------------- #

class UIAttributeMetadata(BaseModel):
    """UI rendering hints for an attribute."""
    list_column: bool = False
    list_column_order: int | None = None
    search_weight: int = 0
    form_order: int | None = None
    form_widget: str | None = None
    form_visible: bool = True
    badge_colors: dict[str, str] | None = None
    filter: bool = False


class SearchMetadata(BaseModel):
    """Search configuration for a node type."""
    enabled: bool = True
    primary_field: str | None = None
    search_fields: list[str] = Field(default_factory=list)


class GraphMetadata(BaseModel):
    """Graph visualization hints for a node or edge type."""
    default_label_field: str | None = None
    size_field: str | None = None
    group_by: str | None = None
    style: str = "solid"
    color: str | None = None
    show_label: bool = True


class APIMetadata(BaseModel):
    """API exposure configuration for a node type."""
    plural_name: str | None = None
    filterable_fields: list[str] = Field(default_factory=list)
    sortable_fields: list[str] = Field(default_factory=list)
    default_sort: str | None = None
    exposed: bool = True


class PermissionsMetadata(BaseModel):
    """Permission defaults for a type."""
    default_read: str = "authenticated"
    default_write: str = "editor"
    default_delete: str = "admin"


class DetailTabDefinition(BaseModel):
    """Custom tab on the detail page for a node type.

    Allows the schema to define dedicated tabs that show related nodes
    via a specific edge type in a table view with filterable columns.

    Example YAML::

        detail_tabs:
          - label: Interfaces
            edge_type: HAS_INTERFACE
            target_type: Interface
            columns: [name, interface_type, enabled, oper_status, speed_mbps, ip_addresses]
            filters: [interface_type, enabled, oper_status]
            default_sort: name
    """
    label: str
    edge_type: str
    target_type: str
    columns: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    default_sort: str | None = None


# --------------------------------------------------------------------------- #
#  Core Definitions                                                            #
# --------------------------------------------------------------------------- #

class AttributeDefinition(BaseModel):
    """Definition of a single attribute on a node or edge type."""
    name: str
    type: AttributeType
    display_name: str | None = None
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any = None
    description: str | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None
    enum_ref: str | None = None
    reference_node_type: str | None = None
    auto_set: str | None = None  # "create", "update", "actor"
    validation_regex: str | None = None
    ui: UIAttributeMetadata = Field(default_factory=UIAttributeMetadata)


class SchemaMetadata(BaseModel):
    """Metadata common to all schema objects."""
    name: str
    display_name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class NodeTypeDefinition(BaseModel):
    """Complete definition of a node type as loaded from YAML."""
    kind: str = SchemaKind.NODE_TYPE
    version: str = "v1"
    metadata: SchemaMetadata
    attributes: dict[str, AttributeDefinition] = Field(default_factory=dict)
    mixins: list[str] = Field(default_factory=list)
    detail_tabs: list[DetailTabDefinition] = Field(default_factory=list)
    search: SearchMetadata = Field(default_factory=SearchMetadata)
    graph: GraphMetadata = Field(default_factory=GraphMetadata)
    api: APIMetadata = Field(default_factory=APIMetadata)
    permissions: PermissionsMetadata = Field(default_factory=PermissionsMetadata)

    @property
    def name(self) -> str:
        return self.metadata.name


class EdgeSourceTarget(BaseModel):
    """Allowed source or target node types for an edge."""
    node_types: list[str]


class EdgeConstraints(BaseModel):
    """Constraints on edge relationships."""
    unique_target: bool = False
    unique_source: bool = False
    min_count: int | None = None
    max_count: int | None = None


class EdgeTypeDefinition(BaseModel):
    """Complete definition of an edge type as loaded from YAML."""
    kind: str = SchemaKind.EDGE_TYPE
    version: str = "v1"
    metadata: SchemaMetadata
    source: EdgeSourceTarget
    target: EdgeSourceTarget
    cardinality: Cardinality = Cardinality.MANY_TO_MANY
    inverse_name: str | None = None
    attributes: dict[str, AttributeDefinition] = Field(default_factory=dict)
    constraints: EdgeConstraints = Field(default_factory=EdgeConstraints)
    graph: GraphMetadata = Field(default_factory=GraphMetadata)
    api: APIMetadata = Field(default_factory=APIMetadata)
    permissions: PermissionsMetadata = Field(default_factory=PermissionsMetadata)

    @property
    def name(self) -> str:
        return self.metadata.name


class MixinDefinition(BaseModel):
    """Reusable attribute group that can be included in node/edge types."""
    kind: str = SchemaKind.MIXIN
    version: str = "v1"
    metadata: SchemaMetadata
    attributes: dict[str, AttributeDefinition] = Field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.metadata.name


class EnumValue(BaseModel):
    """Single value in an enum type."""
    name: str
    display_name: str | None = None
    color: str | None = None
    description: str | None = None


class EnumTypeDefinition(BaseModel):
    """Standalone enum type that can be referenced by attributes."""
    kind: str = SchemaKind.ENUM_TYPE
    version: str = "v1"
    metadata: SchemaMetadata
    values: list[EnumValue]

    @property
    def name(self) -> str:
        return self.metadata.name


# --------------------------------------------------------------------------- #
#  Migration Models                                                            #
# --------------------------------------------------------------------------- #

class SchemaChange(BaseModel):
    """A single change detected between schema versions."""
    change_type: str  # "add_node_type", "add_attribute", "remove_attribute", etc.
    target: str  # e.g., "Device.hostname" or "HAS_INTERFACE"
    risk_level: RiskLevel
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


class MigrationOperation(BaseModel):
    """A database operation to execute as part of a migration."""
    operation: str  # "create_index", "drop_index", "create_constraint", etc.
    cypher: str
    params: dict[str, Any] = Field(default_factory=dict)
    reversible: bool = True
    rollback_cypher: str | None = None


class MigrationPlan(BaseModel):
    """Complete migration plan generated from schema diff."""
    changes: list[SchemaChange]
    risk_level: RiskLevel
    operations: list[MigrationOperation]
    warnings: list[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)
