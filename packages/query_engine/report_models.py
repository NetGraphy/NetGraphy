"""Report definition models — canonical structure for saved reports and report execution.

A report consists of:
1. Root entity type (e.g., Device)
2. Filter AST (same as QueryAST filters)
3. Selected columns from root, related nodes, and edges
4. Row mode (root, expanded, aggregate)
5. Sort, pagination, and export settings
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from packages.query_engine.models import FilterGroup, Pagination, SortField


# --------------------------------------------------------------------------- #
#  Column definitions                                                          #
# --------------------------------------------------------------------------- #

class ColumnSource(str, Enum):
    """Where a report column's data comes from."""
    ROOT = "root"  # Direct attribute on the root entity
    RELATED = "related"  # Attribute on a related node via edge traversal
    EDGE = "edge"  # Attribute on the edge itself
    AGGREGATE = "aggregate"  # Computed aggregate (count, sum, etc.)


class ReportColumn(BaseModel):
    """A single column in a report.

    The `path` determines where data comes from:
    - Root field: "hostname" → Device.hostname
    - Related field: "located_in.Location.city" → traverse edge, get target field
    - Edge field: "has_interface.edge.admin_state" → edge attribute
    - Aggregate: "has_interface.count" → count of relationships
    """
    path: str  # Filter-style path (e.g., "hostname", "located_in.Location.city")
    source: ColumnSource = ColumnSource.ROOT
    display_label: str | None = None  # Override column header
    alias: str | None = None  # Programmatic alias for CSV header
    formatter: str | None = None  # Display formatter hint
    sort_enabled: bool = True
    export_enabled: bool = True


# --------------------------------------------------------------------------- #
#  Row modes                                                                   #
# --------------------------------------------------------------------------- #

class RowMode(str, Enum):
    """How rows are shaped in the report output."""
    ROOT = "root"  # One row per root entity (collapse related)
    EXPANDED = "expanded"  # One row per root + matched related entity
    AGGREGATE = "aggregate"  # One row per group key


# --------------------------------------------------------------------------- #
#  Report definition                                                           #
# --------------------------------------------------------------------------- #

class ReportDefinition(BaseModel):
    """Complete report definition — can be saved and re-executed."""
    # Identity
    id: str | None = None
    name: str = ""
    description: str = ""

    # Structure
    root_entity: str  # Node type (e.g., "Device")
    columns: list[ReportColumn] = Field(default_factory=list)
    filters: FilterGroup | None = None
    row_mode: RowMode = RowMode.ROOT
    sort: list[SortField] = Field(default_factory=list)
    pagination: Pagination = Field(default_factory=Pagination)

    # Aggregation (for RowMode.AGGREGATE)
    group_by: list[str] = Field(default_factory=list)
    aggregate_function: str = "count"  # count, sum, avg, min, max

    # Export settings
    max_export_rows: int = 10000
    export_format: str = "csv"  # csv, json

    # Ownership
    owner: str | None = None
    tenant: str | None = None
    visibility: str = "personal"  # personal, shared, tenant
    tags: list[str] = Field(default_factory=list)
    folder: str | None = None
    favorited: bool = False

    # Metadata
    created_at: str | None = None
    updated_at: str | None = None
    last_run_at: str | None = None
    run_count: int = 0


# --------------------------------------------------------------------------- #
#  Report result                                                               #
# --------------------------------------------------------------------------- #

class ReportResult(BaseModel):
    """Result of executing a report."""
    columns: list[dict[str, Any]] = Field(default_factory=list)  # Column metadata
    rows: list[dict[str, Any]] = Field(default_factory=list)  # Flattened row data
    total_count: int | None = None
    row_mode: RowMode = RowMode.ROOT
    csv_headers: list[str] = Field(default_factory=list)  # Deterministic CSV column names
    query_metadata: dict[str, Any] = Field(default_factory=dict)
