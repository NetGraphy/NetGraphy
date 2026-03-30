"""Schema definition models — the in-memory representation of YAML schemas.

The schema model is the canonical source of truth for the entire platform.
It drives data structure, APIs, MCP tools, agent capabilities, validation
rules, and observability — all derived programmatically from these models.
"""

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
    """Custom tab on the detail page showing related nodes via an edge type."""
    label: str
    edge_type: str
    target_type: str
    columns: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    default_sort: str | None = None


# --------------------------------------------------------------------------- #
#  Generation Control Metadata                                                 #
# --------------------------------------------------------------------------- #

class MCPMetadata(BaseModel):
    """Controls MCP tool generation from the schema.

    When a node or edge type has mcp.exposed=true, the generation engine
    produces MCP tool definitions (create, get, list, update, delete, search)
    that LLMs and agents can use to interact with the graph.
    """
    exposed: bool = True
    allow_create: bool = True
    allow_update: bool = True
    allow_delete: bool = True
    allow_search: bool = True
    tool_name_prefix: str | None = None  # Override auto-generated tool names


class AgentMetadata(BaseModel):
    """Controls AI agent capability generation from the schema.

    Agent capabilities are higher-level semantic actions built on top of
    MCP tools — e.g., "onboard a device" rather than just "create_device".
    """
    exposed: bool = True
    capabilities: list[str] = Field(
        default_factory=list,
        description="Custom capability names to generate (e.g., 'onboard', 'decommission')",
    )
    sensitive: bool = False  # Suppress from agent unless explicitly allowed


class HealthMetadata(BaseModel):
    """Controls observability rule generation from the schema.

    Defines what 'healthy' looks like for this type — what to count,
    what to alert on, what freshness expectations exist.
    """
    enabled: bool = True
    required_for_health: bool = False  # Include in global health score
    freshness_hours: int | None = None  # Alert if no updates within N hours
    min_count: int | None = None  # Alert if fewer than N exist
    max_count: int | None = None  # Alert if more than N exist
    alert_on_orphan: bool = False  # Alert if node has no relationships
    alert_severity: str = "warning"  # warning | critical


class AttributeHealthMetadata(BaseModel):
    """Per-attribute health/generation control."""
    sensitive: bool = False  # Mask in agent responses, exclude from search
    required_for_health: bool = False  # Alert if this field is empty
    editable: bool = True  # Whether agents/MCP can modify this field
    searchable: bool = True  # Include in search/filter tools
    display_priority: int = 0  # Higher = more prominent in agent responses


# --------------------------------------------------------------------------- #
#  Query Metadata                                                              #
# --------------------------------------------------------------------------- #

class QueryAttributeMetadata(BaseModel):
    """Controls query filter generation for this attribute.

    Determines what filter operators are available when querying this
    attribute via MCP tools or the query API. Sensible defaults are
    derived from the attribute type at generation time.
    """
    filterable: bool = True  # Can be used in WHERE clauses
    sortable: bool = True  # Can be used in ORDER BY
    exact_match: bool = True  # Supports eq/neq
    supports_contains: bool = False  # Supports CONTAINS / starts_with / ends_with
    supports_prefix: bool = False  # Supports STARTS WITH
    supports_range: bool = False  # Supports gt/gte/lt/lte/between
    case_sensitive: bool = True  # Whether text matching is case-sensitive
    default_return_field: bool = False  # Include in default field selection


class QueryNodeMetadata(BaseModel):
    """Controls query generation for this node type.

    Configures pagination defaults, traversal limits, and which fields
    are returned by default. The generation engine uses this to produce
    safe, bounded MCP query tools.
    """
    default_list_fields: list[str] = Field(default_factory=list)
    default_sort_field: str | None = None
    default_page_size: int = 50
    max_page_size: int = 200
    primary_search_fields: list[str] = Field(default_factory=list)
    relationship_filters_enabled: bool = True
    max_traversal_depth: int = 3
    max_filter_nesting: int = 4


class QueryEdgeMetadata(BaseModel):
    """Controls query traversal generation for this edge type.

    Determines whether this relationship can be used as a filter path
    in MCP query tools (e.g., Device -> located_at -> Location).
    """
    traversable: bool = True  # Can be traversed in filter paths
    query_alias: str | None = None  # Override the auto-derived alias (default: snake_case of name)
    supports_existence_filter: bool = True  # Filter by "has/lacks this relationship"
    supports_count_filter: bool = True  # Filter by relationship count


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
    health: AttributeHealthMetadata = Field(default_factory=AttributeHealthMetadata)
    query: QueryAttributeMetadata = Field(default_factory=QueryAttributeMetadata)


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
    """Complete definition of a node type as loaded from YAML.

    This is the canonical source. The generation engine reads these
    definitions and produces MCP tools, agent capabilities, validation
    rules, and observability checks.
    """
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
    mcp: MCPMetadata = Field(default_factory=MCPMetadata)
    agent: AgentMetadata = Field(default_factory=AgentMetadata)
    health: HealthMetadata = Field(default_factory=HealthMetadata)
    query: QueryNodeMetadata = Field(default_factory=QueryNodeMetadata)

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


class EdgeHealthMetadata(BaseModel):
    """Health/observability metadata for edge types."""
    enabled: bool = True
    required: bool = False  # Every source node MUST have this edge
    alert_if_missing: bool = False  # Alert when a node lacks this edge
    alert_severity: str = "warning"
    max_count: int | None = None  # Alert if edge count exceeds


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
    mcp: MCPMetadata = Field(default_factory=MCPMetadata)
    agent: AgentMetadata = Field(default_factory=AgentMetadata)
    health: EdgeHealthMetadata = Field(default_factory=EdgeHealthMetadata)
    query: QueryEdgeMetadata = Field(default_factory=QueryEdgeMetadata)

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
    change_type: str
    target: str
    risk_level: RiskLevel
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


class MigrationOperation(BaseModel):
    """A database operation to execute as part of a migration."""
    operation: str
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
