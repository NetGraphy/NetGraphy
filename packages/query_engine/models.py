"""Query AST — canonical query structure for all graph queries.

Every MCP tool, API query, and UI query builder compiles down to this
AST before execution. The AST is:
- validated against the schema (paths, operators, field types)
- compiled into Cypher by the query compiler
- bounded by pagination and safety limits
- never exposed to raw database syntax

This is the single source of truth for "what can be queried and how."
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Filter Operators                                                            #
# --------------------------------------------------------------------------- #

class FilterOperator(str, Enum):
    """All supported filter operators."""
    # Equality
    EQ = "eq"
    NEQ = "neq"

    # String matching
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"

    # Collection
    IN = "in"
    NOT_IN = "not_in"

    # Comparison (numeric / date)
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"

    # Null checks
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"

    # Relationship existence
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"

    # Relationship count
    COUNT_EQ = "count_eq"
    COUNT_GT = "count_gt"
    COUNT_GTE = "count_gte"
    COUNT_LT = "count_lt"
    COUNT_LTE = "count_lte"


# Operators valid for each attribute type family
OPERATORS_BY_TYPE: dict[str, set[str]] = {
    "string": {
        "eq", "neq", "contains", "not_contains", "starts_with",
        "ends_with", "regex", "in", "not_in", "is_null", "is_not_null",
    },
    "text": {
        "eq", "neq", "contains", "not_contains", "starts_with",
        "ends_with", "in", "is_null", "is_not_null",
    },
    "enum": {"eq", "neq", "in", "not_in", "is_null", "is_not_null"},
    "integer": {
        "eq", "neq", "gt", "gte", "lt", "lte", "between",
        "in", "not_in", "is_null", "is_not_null",
    },
    "float": {
        "eq", "neq", "gt", "gte", "lt", "lte", "between",
        "in", "not_in", "is_null", "is_not_null",
    },
    "boolean": {"eq", "neq", "is_null", "is_not_null"},
    "datetime": {
        "eq", "neq", "gt", "gte", "lt", "lte", "between",
        "is_null", "is_not_null",
    },
    "date": {
        "eq", "neq", "gt", "gte", "lt", "lte", "between",
        "is_null", "is_not_null",
    },
    "ip_address": {
        "eq", "neq", "contains", "starts_with", "in",
        "is_null", "is_not_null",
    },
    "cidr": {"eq", "neq", "contains", "starts_with", "is_null", "is_not_null"},
    "mac_address": {"eq", "neq", "contains", "in", "is_null", "is_not_null"},
    "url": {"eq", "neq", "contains", "starts_with", "is_null", "is_not_null"},
    "email": {"eq", "neq", "contains", "starts_with", "is_null", "is_not_null"},
    "json": {"is_null", "is_not_null"},
    "reference": {"eq", "neq", "in", "is_null", "is_not_null"},
    "list[string]": {"is_null", "is_not_null"},
    "list[integer]": {"is_null", "is_not_null"},
    # Relationship pseudo-types
    "relationship_existence": {"exists", "not_exists"},
    "relationship_count": {"count_eq", "count_gt", "count_gte", "count_lt", "count_lte"},
}


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class LogicalOperator(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


# --------------------------------------------------------------------------- #
#  Filter Conditions                                                           #
# --------------------------------------------------------------------------- #

class FilterCondition(BaseModel):
    """A single filter condition.

    The `path` can be:
    - A direct attribute: "status", "hostname"
    - A relationship path: "located_at.Location.city"
    - A relationship existence: "located_at" (with exists/not_exists operator)
    - A relationship count: "located_at" (with count_* operator)
    - An edge attribute: "located_at.is_primary" (edge property)
    """
    path: str
    operator: FilterOperator
    value: Any = None  # None for is_null/is_not_null/exists/not_exists


class FilterGroup(BaseModel):
    """A group of conditions joined by a logical operator.

    Supports nested groups for complex queries:
    AND(status=active, OR(city=Dallas, city=Austin))
    """
    op: LogicalOperator = LogicalOperator.AND
    conditions: list[FilterCondition | FilterGroup] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Sort & Pagination                                                           #
# --------------------------------------------------------------------------- #

class SortField(BaseModel):
    """A field to sort by."""
    field: str
    direction: SortDirection = SortDirection.ASC


class Pagination(BaseModel):
    """Pagination controls with safety limits."""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
#  Query AST                                                                   #
# --------------------------------------------------------------------------- #

class QueryAST(BaseModel):
    """Canonical query representation.

    Every MCP query tool, API request, and UI query compiles into this
    structure before being validated and compiled to Cypher.
    """
    entity: str  # Node type (e.g., "Device")
    filters: FilterGroup | None = None
    sort: list[SortField] = Field(default_factory=list)
    pagination: Pagination = Field(default_factory=Pagination)
    fields: list[str] | None = None  # None = all default fields
    include_total: bool = True  # Return total count alongside results
    include_relationship_summary: bool = False  # Include edge counts per result


# --------------------------------------------------------------------------- #
#  Resolved Path (internal — output of validation)                             #
# --------------------------------------------------------------------------- #

class ResolvedPathSegment(BaseModel):
    """A single segment in a resolved filter path."""
    edge_type: str | None = None  # None for direct attributes
    direction: str = "outgoing"  # outgoing | incoming
    target_type: str | None = None  # The node type being traversed to
    attribute: str | None = None  # The final attribute being filtered on


class ResolvedPath(BaseModel):
    """Fully resolved filter path with schema-validated segments.

    A path like "located_at.Location.city" resolves to:
    [
        ResolvedPathSegment(edge_type="LOCATED_AT", direction="outgoing", target_type="Location"),
        ResolvedPathSegment(attribute="city"),
    ]
    """
    raw_path: str
    segments: list[ResolvedPathSegment]
    is_relationship_existence: bool = False  # Path refers to edge existence, not attribute
    is_relationship_count: bool = False  # Path refers to edge count


# --------------------------------------------------------------------------- #
#  Query Result                                                                #
# --------------------------------------------------------------------------- #

class QueryResult(BaseModel):
    """Structured result from a compiled and executed query."""
    items: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int | None = None
    page_info: Pagination = Field(default_factory=Pagination)
    entity: str = ""
    fields_returned: list[str] = Field(default_factory=list)
    query_metadata: dict[str, Any] = Field(default_factory=dict)  # timing, plan, etc.
