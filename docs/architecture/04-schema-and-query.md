# 04 - Schema Specification, Graph/Query Architecture, and Example Schemas

---

## 6. Graph/Query Architecture

All read and write operations against the graph database pass through a query abstraction layer. This layer exists to enforce parameterization, isolate Cypher dialect differences between Neo4j and Apache AGE, and provide a composable API that higher-level services (the structured query builder, the REST API, and the sync engine) can use without constructing raw Cypher strings.

---

### 6.1 Query Abstraction Layer

#### 6.1.1 Design Principles

1. **No string interpolation.** Every value that originates from user input, API parameters, or sync data must be passed as a Cypher parameter (`$param`). The builder never concatenates values into query strings.
2. **Dialect isolation.** Neo4j native Cypher and Apache AGE's Cypher subset differ in syntax for path expressions, list comprehensions, and certain functions. The `CypherBuilder` accepts a `Dialect` enum at construction time and emits the correct syntax for the target backend. All dialect-specific logic lives inside the builder --- no calling code should branch on the backend type.
3. **Immutable chaining.** Each builder method returns a new `CypherBuilder` instance (or `self` for in-place mutation --- the implementation may choose either pattern, but the public contract is a fluent interface). This makes it safe to derive variant queries from a shared base.
4. **Composability.** Complex queries (multi-hop traversals, union queries, subqueries) are built by composing smaller `CypherBuilder` fragments.

#### 6.1.2 Core Types

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Dialect(Enum):
    NEO4J = "neo4j"
    AGE = "age"


@dataclass(frozen=True)
class NodePattern:
    """Represents a node in a MATCH pattern, e.g. (d:Device {status: $status})."""
    variable: str
    labels: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    # property values are parameter names, not literals


@dataclass(frozen=True)
class RelPattern:
    """Represents a relationship in a MATCH pattern, e.g. -[r:HAS_INTERFACE]->."""
    variable: str | None = None
    rel_types: list[str] = field(default_factory=list)
    direction: str = "out"          # "out", "in", "both"
    min_hops: int | None = None     # for variable-length paths
    max_hops: int | None = None


@dataclass(frozen=True)
class MatchPattern:
    """A chain of alternating NodePattern and RelPattern objects.

    Example: (d:Device)-[r:HAS_INTERFACE]->(i:Interface)
    Stored as: elements = [NodePattern, RelPattern, NodePattern, ...]
    """
    elements: list[NodePattern | RelPattern] = field(default_factory=list)


class ConditionOp(Enum):
    EQ = "="
    NEQ = "<>"
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    IN = "IN"
    NOT_IN = "NOT IN"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS WITH"
    ENDS_WITH = "ENDS WITH"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    REGEX = "=~"


@dataclass(frozen=True)
class Condition:
    """A single WHERE predicate."""
    field: str                      # e.g. "d.status"
    op: ConditionOp
    param_name: str | None = None   # name of the parameter; None for IS NULL / IS NOT NULL
    negate: bool = False


class BooleanOp(Enum):
    AND = "AND"
    OR = "OR"


@dataclass
class ConditionGroup:
    """A group of conditions joined by AND or OR, with optional nesting."""
    boolean_op: BooleanOp = BooleanOp.AND
    conditions: list[Condition | ConditionGroup] = field(default_factory=list)


@dataclass(frozen=True)
class ReturnField:
    """A single expression in a RETURN clause."""
    expression: str                 # e.g. "d.hostname", "count(i)", "collect(d)"
    alias: str | None = None        # e.g. "device_count"


@dataclass(frozen=True)
class OrderField:
    expression: str
    descending: bool = False


@dataclass(frozen=True)
class AggregationField:
    """Wraps aggregation functions --- COUNT, COLLECT, SUM, AVG, MIN, MAX."""
    function: str                   # "COUNT", "COLLECT", etc.
    expression: str                 # "d", "d.hostname", "*"
    distinct: bool = False
    alias: str | None = None
```

#### 6.1.3 CypherBuilder Class

```python
class CypherBuilder:
    """Constructs parameterized Cypher from structured inputs.

    This is the **single point** where Cypher dialect differences are handled.
    All services that need to query the graph MUST use this builder rather than
    constructing Cypher strings directly.
    """

    def __init__(self, dialect: Dialect = Dialect.NEO4J) -> None:
        self._dialect = dialect
        self._match_patterns: list[MatchPattern] = []
        self._optional_match_patterns: list[MatchPattern] = []
        self._where: ConditionGroup | None = None
        self._with_clauses: list[list[ReturnField]] = []
        self._return_fields: list[ReturnField] = []
        self._order_by: list[OrderField] = []
        self._skip: int | None = None
        self._limit: int | None = None
        self._parameters: dict[str, Any] = {}
        self._create_patterns: list[MatchPattern] = []
        self._set_clauses: list[tuple[str, str]] = []   # (property_path, param_name)
        self._delete_vars: list[str] = []
        self._detach_delete_vars: list[str] = []
        self._merge_patterns: list[MatchPattern] = []
        self._on_create_set: list[tuple[str, str]] = []
        self._on_match_set: list[tuple[str, str]] = []
        self._unwind: tuple[str, str] | None = None     # (param_name, variable)
        self._call_subqueries: list["CypherBuilder"] = []

    # --- Fluent API ---

    def match(self, pattern: MatchPattern) -> "CypherBuilder":
        """Add a MATCH clause."""
        self._match_patterns.append(pattern)
        return self

    def optional_match(self, pattern: MatchPattern) -> "CypherBuilder":
        """Add an OPTIONAL MATCH clause."""
        self._optional_match_patterns.append(pattern)
        return self

    def where(self, conditions: ConditionGroup | list[Condition]) -> "CypherBuilder":
        """Set WHERE conditions. Overwrites any previous WHERE."""
        if isinstance(conditions, list):
            group = ConditionGroup(BooleanOp.AND, conditions)
        else:
            group = conditions
        self._where = group
        return self

    def with_clause(self, fields: list[ReturnField]) -> "CypherBuilder":
        """Add a WITH clause (pipeline stage)."""
        self._with_clauses.append(fields)
        return self

    def return_clause(self, fields: list[ReturnField]) -> "CypherBuilder":
        """Set RETURN fields."""
        self._return_fields = fields
        return self

    def order_by(self, fields: list[OrderField]) -> "CypherBuilder":
        """Set ORDER BY fields."""
        self._order_by = fields
        return self

    def skip(self, n: int) -> "CypherBuilder":
        """Set SKIP for pagination."""
        self._skip = n
        return self

    def limit(self, n: int) -> "CypherBuilder":
        """Set LIMIT for pagination."""
        self._limit = n
        return self

    def param(self, name: str, value: Any) -> "CypherBuilder":
        """Bind a parameter value."""
        self._parameters[name] = value
        return self

    def params(self, values: dict[str, Any]) -> "CypherBuilder":
        """Bind multiple parameter values."""
        self._parameters.update(values)
        return self

    def create(self, pattern: MatchPattern) -> "CypherBuilder":
        """Add a CREATE clause."""
        self._create_patterns.append(pattern)
        return self

    def merge(self, pattern: MatchPattern) -> "CypherBuilder":
        """Add a MERGE clause."""
        self._merge_patterns.append(pattern)
        return self

    def set(self, property_path: str, param_name: str) -> "CypherBuilder":
        """Add a SET clause: SET property_path = $param_name."""
        self._set_clauses.append((property_path, param_name))
        return self

    def on_create_set(self, property_path: str, param_name: str) -> "CypherBuilder":
        """Add ON CREATE SET clause for MERGE."""
        self._on_create_set.append((property_path, param_name))
        return self

    def on_match_set(self, property_path: str, param_name: str) -> "CypherBuilder":
        """Add ON MATCH SET clause for MERGE."""
        self._on_match_set.append((property_path, param_name))
        return self

    def delete(self, *variables: str) -> "CypherBuilder":
        """Add DELETE clause."""
        self._delete_vars.extend(variables)
        return self

    def detach_delete(self, *variables: str) -> "CypherBuilder":
        """Add DETACH DELETE clause."""
        self._detach_delete_vars.extend(variables)
        return self

    def unwind(self, param_name: str, variable: str) -> "CypherBuilder":
        """Add UNWIND $param_name AS variable."""
        self._unwind = (param_name, variable)
        return self

    def call_subquery(self, subquery: "CypherBuilder") -> "CypherBuilder":
        """Add a CALL { subquery } block (Neo4j 4.1+)."""
        self._call_subqueries.append(subquery)
        return self

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile the builder state into a (cypher_string, parameters) tuple.

        The returned Cypher string uses $param_name placeholders. The returned
        dict contains all bound parameter values keyed by name.

        Raises BuilderError if the query is structurally invalid.
        """
        ...

    # --- Dialect helpers (private) ---

    def _render_node(self, node: NodePattern) -> str:
        """Render a NodePattern to Cypher, respecting dialect differences."""
        ...

    def _render_rel(self, rel: RelPattern) -> str:
        """Render a RelPattern to Cypher, respecting dialect differences.

        AGE differences handled here:
        - AGE does not support variable-length paths in all contexts.
        - AGE relationship type syntax may differ.
        """
        ...

    def _render_condition(self, cond: Condition) -> str:
        """Render a single condition to a Cypher predicate string."""
        ...

    def _render_condition_group(self, group: ConditionGroup) -> str:
        """Recursively render a condition group with AND/OR."""
        ...
```

#### 6.1.4 Traversal Builder

For multi-hop graph traversals (e.g., "find all devices two hops from this location"), the builder supports variable-length path patterns and explicit multi-step composition.

```python
class TraversalBuilder:
    """Convenience wrapper over CypherBuilder for path-oriented queries."""

    def __init__(self, dialect: Dialect = Dialect.NEO4J) -> None:
        self._builder = CypherBuilder(dialect)
        self._path_var: str = "p"

    def start(self, node: NodePattern) -> "TraversalBuilder":
        """Set the traversal start node."""
        ...

    def traverse(
        self,
        rel: RelPattern,
        target: NodePattern,
    ) -> "TraversalBuilder":
        """Append a hop to the traversal."""
        ...

    def variable_length(
        self,
        rel_types: list[str],
        target: NodePattern,
        min_hops: int = 1,
        max_hops: int | None = None,
        direction: str = "out",
    ) -> "TraversalBuilder":
        """Add a variable-length path segment: -[:TYPE*min..max]->."""
        ...

    def shortest_path(self, use_all: bool = False) -> "TraversalBuilder":
        """Wrap the pattern in shortestPath() or allShortestPaths()."""
        ...

    def return_paths(self) -> "TraversalBuilder":
        """Return the path variable plus all nodes and relationships in it."""
        ...

    def return_end_nodes(self) -> "TraversalBuilder":
        """Return only the terminal nodes of the traversal."""
        ...

    def build(self) -> tuple[str, dict[str, Any]]:
        return self._builder.build()
```

**Example --- find all devices within 3 hops of a given location:**

```python
query, params = (
    TraversalBuilder(Dialect.NEO4J)
    .start(NodePattern("loc", ["Location"], {"name": "site_name"}))
    .variable_length(
        rel_types=["LOCATED_IN"],
        target=NodePattern("d", ["Device"]),
        min_hops=1,
        max_hops=3,
        direction="in",
    )
    .return_end_nodes()
    .build()
)
# query:  MATCH p = (loc:Location {name: $site_name})<-[:LOCATED_IN*1..3]-(d:Device)
#         RETURN d
# params: {"site_name": "dc-east-1"}
```

#### 6.1.5 Aggregation Support

Aggregation functions are first-class citizens in the builder. They are expressed through `ReturnField` and `AggregationField` objects and rendered as standard Cypher aggregation expressions.

Supported aggregation functions:

| Function   | Description                        | Example                              |
|------------|------------------------------------|--------------------------------------|
| `COUNT`    | Count matching items               | `COUNT(d)`, `COUNT(DISTINCT d.role)` |
| `COLLECT`  | Collect into a list                | `COLLECT(d.hostname)`                |
| `SUM`      | Sum numeric values                 | `SUM(i.speed)`                       |
| `AVG`      | Average numeric values             | `AVG(i.mtu)`                         |
| `MIN`      | Minimum value                      | `MIN(d.created_at)`                  |
| `MAX`      | Maximum value                      | `MAX(d.updated_at)`                  |
| `PERCENTILE_CONT` | Continuous percentile       | `PERCENTILE_CONT(i.speed, 0.95)`    |
| `PERCENTILE_DISC` | Discrete percentile         | `PERCENTILE_DISC(i.speed, 0.50)`    |
| `STDEV`    | Standard deviation                 | `STDEV(i.speed)`                     |

**Example --- count devices by role:**

```python
query, params = (
    CypherBuilder(Dialect.NEO4J)
    .match(MatchPattern([NodePattern("d", ["Device"])]))
    .return_clause([
        ReturnField("d.role", alias="role"),
        ReturnField("count(d)", alias="device_count"),
    ])
    .order_by([OrderField("device_count", descending=True)])
    .build()
)
# MATCH (d:Device)
# RETURN d.role AS role, count(d) AS device_count
# ORDER BY device_count DESC
```

#### 6.1.6 Dialect Differences Handled

The following Neo4j vs. Apache AGE differences are encapsulated inside `CypherBuilder`:

| Feature                      | Neo4j                                    | AGE                                        |
|------------------------------|------------------------------------------|--------------------------------------------|
| Variable-length paths        | `*1..3`                                  | Limited support; builder emits multi-MATCH  |
| `shortestPath()`             | Native function                          | Not supported; builder uses BFS emulation   |
| List comprehensions          | `[x IN list WHERE pred \| expr]`         | Not supported; builder uses UNWIND          |
| `CALL {} IN TRANSACTIONS`    | Supported (Neo4j 4.4+)                   | Not supported; builder batches externally   |
| APOC functions               | Available via plugin                     | Not available; builder substitutes          |
| Parameter syntax             | `$param`                                 | `$param` (same)                            |
| Multi-label nodes            | `(n:Label1:Label2)`                      | Single label only; builder uses properties  |
| Index hints                  | `USING INDEX`                            | Not supported; silently omitted             |
| `MERGE ... ON CREATE SET`    | Supported                                | Limited; builder may use MATCH + CREATE     |
| Temporal types               | Native `datetime()`, `date()`            | Stored as ISO strings; builder converts     |

---

### 6.2 Structured Query Builder (Backend)

The structured query builder is the backend service that converts a `StructuredQuery` JSON object --- produced by the frontend's visual query builder UI --- into a parameterized Cypher query via the `CypherBuilder`.

#### 6.2.1 StructuredQuery Object

The frontend sends a JSON payload that describes the query in abstract, graph-agnostic terms:

```python
@dataclass
class StructuredQuery:
    """Describes a graph query in frontend-friendly terms."""

    # What to find
    root_node_type: str                           # e.g. "Device"

    # Filters on the root node
    filters: list[FieldFilter]                    # e.g. [{"field": "status", "op": "eq", "value": "active"}]

    # Related nodes to include (joins)
    includes: list[IncludeRelation]               # e.g. [{"edge_type": "HAS_INTERFACE", "node_type": "Interface", ...}]

    # Fields to return
    fields: list[str]                             # e.g. ["hostname", "management_ip", "status"]

    # Aggregations (optional)
    group_by: list[str] | None = None
    aggregations: list[AggregationSpec] | None = None

    # Pagination
    sort_by: str | None = None
    sort_order: str = "asc"                       # "asc" or "desc"
    page: int = 1
    page_size: int = 50

    # Output mode
    output_mode: str = "table"                    # "table", "graph", "both"


@dataclass
class FieldFilter:
    field: str
    op: str             # "eq", "neq", "lt", "lte", "gt", "gte", "in", "contains",
                        # "starts_with", "ends_with", "is_null", "is_not_null", "regex"
    value: Any = None   # None for is_null / is_not_null


@dataclass
class IncludeRelation:
    edge_type: str                      # e.g. "HAS_INTERFACE"
    node_type: str                      # e.g. "Interface"
    direction: str = "out"              # "out", "in"
    filters: list[FieldFilter] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    optional: bool = True               # OPTIONAL MATCH vs. MATCH


@dataclass
class AggregationSpec:
    function: str       # "count", "sum", "avg", "min", "max", "collect"
    field: str          # field to aggregate, or "*" for count
    alias: str          # output column name
```

#### 6.2.2 Conversion Pipeline

```
StructuredQuery (JSON from frontend)
    |
    v
[1. Schema Validation]  --- reject unknown node types, edge types, fields
    |
    v
[2. RBAC Filtering]     --- remove unauthorized node types, redact fields
    |
    v
[3. CypherBuilder Calls] --- translate to builder method calls
    |
    v
[4. Parameter Binding]  --- bind filter values as parameters
    |
    v
[5. build()]            --- emit (cypher_string, parameters)
    |
    v
[6. Execute]            --- run against graph database
    |
    v
[7. Result Mapping]     --- map raw result to QueryResult contract
```

**Step 1 --- Schema Validation:**
- Verify `root_node_type` exists in the schema registry.
- Verify every field in `filters` and `fields` is a declared attribute of the node type (or a mixin attribute).
- Verify every `IncludeRelation.edge_type` exists and that its declared `source`/`target` node types are compatible with the query structure.
- Verify aggregation fields reference valid attributes.
- Return a `400 Bad Request` with specific validation errors if any check fails.

**Step 2 --- RBAC Filtering:**
- Look up the requesting user's effective permissions (roles, group memberships).
- If the user lacks `read` permission on the `root_node_type`, reject the query entirely with `403 Forbidden`.
- For each `IncludeRelation`, if the user lacks `read` on the related `node_type`, silently drop the include from the query (do not error --- the user simply does not see those relations).
- For individual fields, if per-field RBAC is configured (e.g., `serial_number` restricted to `asset_manager` role), remove those fields from the `fields` list and any `filters` that reference them.

**Step 3 --- CypherBuilder Translation (pseudocode):**

```python
def structured_to_cypher(
    query: StructuredQuery,
    schema: SchemaRegistry,
    dialect: Dialect,
) -> tuple[str, dict[str, Any]]:

    builder = CypherBuilder(dialect)
    param_idx = 0

    # Root MATCH
    root_var = "n0"
    builder.match(MatchPattern([
        NodePattern(root_var, [query.root_node_type])
    ]))

    # WHERE conditions from filters
    conditions = []
    params = {}
    for f in query.filters:
        param_name = f"p{param_idx}"
        param_idx += 1
        conditions.append(Condition(
            field=f"{root_var}.{f.field}",
            op=_map_op(f.op),
            param_name=param_name,
        ))
        params[param_name] = f.value

    if conditions:
        builder.where(conditions)

    # Includes (joins)
    for idx, inc in enumerate(query.includes, start=1):
        rel_var = f"r{idx}"
        node_var = f"n{idx}"
        pattern = MatchPattern([
            NodePattern(root_var),
            RelPattern(rel_var, [inc.edge_type], direction=inc.direction),
            NodePattern(node_var, [inc.node_type]),
        ])
        if inc.optional:
            builder.optional_match(pattern)
        else:
            builder.match(pattern)

        # Include-level filters
        for f in inc.filters:
            param_name = f"p{param_idx}"
            param_idx += 1
            conditions.append(Condition(
                field=f"{node_var}.{f.field}",
                op=_map_op(f.op),
                param_name=param_name,
            ))
            params[param_name] = f.value

    # RETURN
    return_fields = [ReturnField(f"{root_var}.{f}", alias=f) for f in query.fields]
    builder.return_clause(return_fields)

    # ORDER BY, SKIP, LIMIT
    if query.sort_by:
        builder.order_by([OrderField(
            f"{root_var}.{query.sort_by}",
            descending=(query.sort_order == "desc"),
        )])
    builder.skip((query.page - 1) * query.page_size)
    builder.limit(query.page_size)

    builder.params(params)
    return builder.build()
```

#### 6.2.3 Security Invariants

- The `CypherBuilder` is the only code path that produces Cypher. No raw Cypher strings are accepted from the frontend.
- The structured query builder validates every identifier (node type, edge type, field name) against the schema registry before passing it to the builder. This prevents Cypher injection through crafted field names.
- Parameter values are always bound, never interpolated.
- RBAC enforcement happens before query construction, ensuring that unauthorized data paths are never expressed in the generated Cypher.

---

### 6.3 Saved Query Management

Saved queries allow users to store, share, and re-execute frequently used queries. They can be created through the UI, the API, or synced from Git.

#### 6.3.1 Storage

Saved queries are stored in the primary database (Neo4j as `SavedQuery` nodes, or optionally in a PostgreSQL sidecar for simpler relational management). The recommended approach is PostgreSQL sidecar, keeping the graph database focused on network data.

**Schema (PostgreSQL):**

```sql
CREATE TABLE saved_queries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT,

    -- Query definition
    query_type      VARCHAR(20) NOT NULL DEFAULT 'cypher',
        -- 'cypher' (raw parameterized Cypher)
        -- 'structured' (StructuredQuery JSON, converted at execution time)
    cypher          TEXT,                           -- raw Cypher (for query_type='cypher')
    structured_query JSONB,                         -- StructuredQuery JSON (for query_type='structured')

    -- Parameter definitions (JSON Schema)
    parameters_schema JSONB NOT NULL DEFAULT '{}',
    default_parameters JSONB NOT NULL DEFAULT '{}',

    -- Metadata
    tags            TEXT[] NOT NULL DEFAULT '{}',
    category        VARCHAR(100),

    -- Ownership & visibility
    created_by      UUID NOT NULL REFERENCES users(id),
    visibility      VARCHAR(20) NOT NULL DEFAULT 'personal',
        -- 'personal': only creator can see/execute
        -- 'shared': all authenticated users can see/execute
        -- 'public': visible without authentication (read-only dashboards)

    -- Sync
    source          VARCHAR(20) NOT NULL DEFAULT 'ui',
        -- 'ui': created in the web interface
        -- 'git': synced from a content repository
        -- 'api': created via API
    source_repo     VARCHAR(255),                   -- Git repo URL if source='git'
    source_path     VARCHAR(500),                   -- file path within repo
    source_hash     VARCHAR(64),                    -- Git commit SHA at last sync

    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_executed_at TIMESTAMPTZ,
    execution_count BIGINT NOT NULL DEFAULT 0,

    -- Soft delete
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_saved_queries_slug ON saved_queries(slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_saved_queries_tags ON saved_queries USING GIN(tags);
CREATE INDEX idx_saved_queries_visibility ON saved_queries(visibility) WHERE deleted_at IS NULL;
CREATE INDEX idx_saved_queries_created_by ON saved_queries(created_by) WHERE deleted_at IS NULL;
```

#### 6.3.2 Parameter Schema

Each saved query declares its parameters using JSON Schema. This enables the frontend to render a dynamic form for parameter input and the backend to validate parameter values before execution.

```json
{
  "type": "object",
  "properties": {
    "site_name": {
      "type": "string",
      "title": "Site Name",
      "description": "Name of the site to query",
      "x-ui-widget": "autocomplete",
      "x-ui-source": "Location.name"
    },
    "status": {
      "type": "string",
      "title": "Device Status",
      "enum": ["active", "planned", "staged", "decommissioned", "maintenance"],
      "default": "active"
    },
    "min_interfaces": {
      "type": "integer",
      "title": "Minimum Interfaces",
      "minimum": 0,
      "default": 0
    }
  },
  "required": ["site_name"]
}
```

The `x-ui-widget` and `x-ui-source` extensions tell the frontend how to render input controls (autocomplete backed by a specific node type field, date picker, etc.).

#### 6.3.3 Git Sync

Saved queries can be maintained as YAML files in a Git repository under a `queries/` directory. The sync engine processes them alongside schema files.

**File format (`queries/devices-at-site.yaml`):**

```yaml
kind: SavedQuery
version: v1
metadata:
  name: "Devices at Site"
  slug: devices-at-site
  description: "List all active devices at a given site with their interfaces"
  tags: [inventory, site, devices]
  category: Inventory
  visibility: shared

query_type: cypher
cypher: |
  MATCH (d:Device)-[:LOCATED_IN]->(loc:Location {name: $site_name})
  WHERE d.status = $status
  OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(i:Interface)
  WITH d, count(i) AS iface_count
  WHERE iface_count >= $min_interfaces
  RETURN d.hostname AS hostname,
         d.management_ip AS management_ip,
         d.status AS status,
         d.role AS role,
         iface_count
  ORDER BY d.hostname

parameters_schema:
  type: object
  properties:
    site_name:
      type: string
      title: Site Name
      x-ui-widget: autocomplete
      x-ui-source: Location.name
    status:
      type: string
      title: Device Status
      enum: [active, planned, staged, decommissioned, maintenance]
      default: active
    min_interfaces:
      type: integer
      title: Minimum Interfaces
      minimum: 0
      default: 0
  required: [site_name]

default_parameters:
  status: active
  min_interfaces: 0
```

#### 6.3.4 RBAC on Query Execution

Even if a user can see a saved query, execution is subject to the same RBAC rules as any other query:
- The Cypher or StructuredQuery is analyzed for the node types and edge types it references.
- If the user lacks `read` permission on any referenced type, execution is denied with a `403` and a message indicating which permission is missing.
- For `visibility: public` queries on read-only dashboards, a dedicated service account with scoped permissions executes the query.

---

### 6.4 Query Result Contract

All query results --- whether from the structured query builder, saved queries, or direct Cypher execution (admin only) --- are returned in a unified format that supports both table and graph rendering.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class QueryResult:
    """Unified query result that supports both table and graph rendering."""

    # Table representation
    columns: list[ColumnDefinition]
    rows: list[dict[str, Any]]

    # Graph representation
    nodes: list[NodeResult]
    edges: list[EdgeResult]

    # Metadata
    metadata: QueryMetadata


@dataclass
class ColumnDefinition:
    """Describes a column in the tabular result."""
    name: str
    data_type: str          # "string", "integer", "float", "boolean", "datetime", "ip_address", etc.
    node_type: str | None = None   # which node type this field belongs to, if applicable
    sortable: bool = True
    filterable: bool = True


@dataclass
class NodeResult:
    """A single node in the graph result."""
    id: str                         # internal graph ID (stable identifier)
    node_type: str                  # schema node type name, e.g. "Device"
    label: str                      # display label, e.g. the hostname
    properties: dict[str, Any]      # all returned properties

    # UI hints (populated from schema)
    icon: str | None = None
    color: str | None = None
    group: str | None = None        # grouping value for graph layout


@dataclass
class EdgeResult:
    """A single edge in the graph result."""
    id: str
    edge_type: str                  # schema edge type name, e.g. "HAS_INTERFACE"
    source_id: str                  # id of the source NodeResult
    target_id: str                  # id of the target NodeResult
    properties: dict[str, Any]

    # UI hints (populated from schema)
    style: str | None = None        # "solid", "dashed", "dotted"
    color: str | None = None
    label: str | None = None        # display label on the edge


@dataclass
class QueryMetadata:
    """Metadata about query execution."""
    query_time_ms: float            # time spent executing the Cypher query
    total_time_ms: float            # total time including serialization
    row_count: int                  # number of rows in the tabular result
    node_count: int                 # number of distinct nodes in the graph result
    edge_count: int                 # number of distinct edges in the graph result
    has_more: bool                  # whether there are more results beyond the current page
    total_count: int | None = None  # total matching rows (if count query was executed)
    page: int = 1
    page_size: int = 50
    warnings: list[str] = field(default_factory=list)  # e.g. "Results truncated to 1000 nodes"
    query_id: str | None = None     # unique ID for this execution (for logging/debugging)
    cached: bool = False            # whether this result was served from cache
```

**Dual format rationale:** The same query result feeds both table and graph visualizations in the frontend. The `rows` list provides a flat tabular view suitable for data grids, CSV export, and reporting. The `nodes` and `edges` lists provide the graph topology suitable for force-directed layouts, hierarchical views, and topology diagrams. The backend populates both representations from the raw Cypher result in a single pass, so there is no performance penalty.

**Result size limits:**
- Table results: default page size 50, max 1000 rows per page.
- Graph results: max 5000 nodes and 10000 edges per query. If the raw result exceeds this, the result is truncated and a warning is included in `metadata.warnings`.
- For large result sets, the API supports streaming via Server-Sent Events (SSE) or chunked JSON.

---

## 7. YAML Schema Specification Format

All schema definitions in NetGraphy are expressed as YAML files. These files are the single source of truth for the data model and drive code generation, validation, API routing, UI rendering, and graph database schema management.

---

### 7.1 Schema File Structure

Schema files are organized in directories and loaded by the schema registry at startup and on Git sync events.

**Directory layout:**

```
schemas/
  node_types/
    device.yaml
    interface.yaml
    location.yaml
    vendor.yaml
    hardware_model.yaml
    software_version.yaml
    image.yaml
    platform.yaml
    service.yaml
  edge_types/
    has_interface.yaml
    located_in.yaml
    connected_to.yaml
    runs_version.yaml
    uses_image.yaml
    manufactured_by.yaml
    has_model.yaml
    runs_platform.yaml
    depends_on.yaml
    hosted_on.yaml
  mixins/
    lifecycle_mixin.yaml
    provenance_mixin.yaml
  enums/
    device_status.yaml
    interface_type.yaml
    ...
```

**Loading rules:**
1. All `.yaml` and `.yml` files in the configured schema directories are loaded.
2. Files are parsed and validated against the meta-schema for their `kind`.
3. Mixins and EnumTypes are loaded first (they may be referenced by NodeTypes and EdgeTypes).
4. NodeTypes are loaded next.
5. EdgeTypes are loaded last (they reference NodeTypes).
6. Cross-references are validated after all files are loaded.
7. The merged schema is stored in the schema registry (in-memory, with persistence to the database for runtime lookups).

**Every schema file must have these top-level fields:**

| Field      | Type   | Required | Description                                    |
|------------|--------|----------|------------------------------------------------|
| `kind`     | string | yes      | One of: `NodeType`, `EdgeType`, `Mixin`, `EnumType` |
| `version`  | string | yes      | Schema format version, currently `v1`          |
| `metadata` | object | yes      | Name, description, and display metadata        |

---

### 7.2 Node Type Schema Format

A node type definition describes a class of nodes in the graph: its attributes, display configuration, search behavior, API exposure, and access control.

**Complete field reference:**

```yaml
kind: NodeType
version: v1

metadata:
  name: string              # PascalCase identifier, used as the Neo4j label. Required.
  display_name: string      # Human-readable name for UI. Required.
  description: string       # Markdown-enabled description. Required.
  icon: string              # Icon identifier (Lucide icon name). Required.
  color: string             # Hex color code for graph visualization. Required.
  category: string          # Grouping category for the UI sidebar. Required.
  tags: list[string]        # Freeform tags for filtering and discovery. Optional.

attributes:
  <attribute_name>:         # snake_case identifier. Keys become Neo4j property names.
    type: string            # See Section 7.6 for supported types. Required.
    required: boolean       # Whether the attribute must be set. Default: false.
    unique: boolean         # Whether values must be unique across all nodes of this type. Default: false.
    indexed: boolean        # Whether to create a database index. Default: false.
    default: any            # Default value if not provided. Optional.
    max_length: integer     # Maximum string length (for string/text types). Optional.
    min_length: integer     # Minimum string length. Optional.
    min_value: number       # Minimum numeric value (for integer/float). Optional.
    max_value: number       # Maximum numeric value. Optional.
    pattern: string         # Regex validation pattern (for string types). Optional.
    enum_values: list       # Allowed values (for enum type). Optional.
    enum_ref: string        # Reference to an EnumType name (alternative to inline enum_values). Optional.
    list_item_type: string  # Item type for list types (e.g., "string" for list[string]). Optional.
    description: string     # Human-readable description. Optional.
    examples: list          # Example values for documentation. Optional.
    deprecated: boolean     # Mark attribute as deprecated. Default: false.
    deprecated_message: string # Explanation and migration guidance. Optional.
    sensitive: boolean      # If true, value is masked in logs and non-privileged API responses. Default: false.
    immutable: boolean      # If true, value cannot be changed after creation. Default: false.
    computed: boolean       # If true, value is computed by the system and not user-editable. Default: false.

    # Validation
    validators: list        # Additional validation rules. Optional.
      - type: string        # Validator type: "regex", "ip_network", "cidr_contains", "fqdn", etc.
        params: object      # Validator-specific parameters.

    # UI rendering hints
    ui:
      list_column: boolean          # Show in list/table views. Default: false.
      list_column_order: integer    # Column order in list views (lower = leftmost). Optional.
      list_column_width: string     # "sm", "md", "lg", "xl", or pixel value. Optional.
      detail_visible: boolean       # Show on detail page. Default: true.
      detail_order: integer         # Order on detail page. Optional.
      detail_section: string        # Section grouping on detail page. Optional.
      form_order: integer           # Order in create/edit forms. Optional.
      form_visible: boolean         # Show in create/edit forms. Default: true.
      form_widget: string           # Widget type: "text", "textarea", "select", "autocomplete",
                                    # "ip_input", "mac_input", "number", "toggle", "date_picker",
                                    # "json_editor", "tag_input", "password". Optional.
      form_placeholder: string      # Placeholder text. Optional.
      form_help_text: string        # Help text shown below the input. Optional.
      search_weight: integer        # Weight for full-text search ranking (0 = not searchable). Default: 0.
      filter: boolean               # Show as a filter option in list views. Default: false.
      badge_colors: object          # Mapping of enum values to color names (for enum types). Optional.
      copy_button: boolean          # Show a copy-to-clipboard button. Default: false.
      link: boolean                 # Render as a clickable link. Default: false.
      monospace: boolean            # Render in monospace font. Default: false.
      truncate: integer             # Truncate display to N characters in list views. Optional.

mixins: list[string]        # List of mixin names to include. Optional.

search:
  enabled: boolean          # Whether this node type is included in global search. Default: true.
  primary_field: string     # The main field shown in search results. Required if enabled.
  search_fields: list[string] # Fields indexed for full-text search. Required if enabled.
  boost: float              # Search result ranking boost for this node type. Default: 1.0.

graph:
  default_label_field: string  # Which attribute to display as the node label. Required.
  secondary_label_field: string # Optional secondary label (shown smaller). Optional.
  size_field: string | null    # Attribute to use for dynamic node sizing. Optional.
  size_range: [integer, integer] # Min/max node size in pixels. Default: [20, 60].
  group_by: string | null      # Attribute to use for grouping/clustering. Optional.
  tooltip_fields: list[string] # Fields to show in the hover tooltip. Optional.

api:
  plural_name: string       # URL path segment, e.g., "devices" -> /api/v1/devices. Required.
  filterable_fields: list[string] # Fields that accept query parameter filters. Required.
  sortable_fields: list[string]   # Fields that can be used for sorting. Required.
  default_sort: string       # Default sort field. Required.
  default_sort_order: string # "asc" or "desc". Default: "asc".
  max_page_size: integer     # Maximum allowed page size. Default: 1000.
  bulk_operations: boolean   # Whether bulk create/update/delete is enabled. Default: true.

permissions:
  default_read: string       # Minimum role for read access. Default: "authenticated".
  default_write: string      # Minimum role for create/update. Default: "editor".
  default_delete: string     # Minimum role for delete. Default: "admin".
  field_permissions:         # Per-field permission overrides. Optional.
    <field_name>:
      read: string
      write: string
```

---

### 7.3 Edge Type Schema Format

An edge type defines a relationship between two node types, its direction, cardinality, and optional properties.

```yaml
kind: EdgeType
version: v1

metadata:
  name: string              # UPPER_SNAKE_CASE identifier, used as the Neo4j relationship type. Required.
  display_name: string      # Human-readable name. Required.
  description: string       # Markdown description. Required.
  category: string          # Grouping category. Required.
  tags: list[string]        # Freeform tags. Optional.

source:
  node_types: list[string]  # Allowed source node types. Required. At least one.

target:
  node_types: list[string]  # Allowed target node types. Required. At least one.

cardinality: string         # "one_to_one", "one_to_many", "many_to_one", "many_to_many". Required.

inverse_name: string        # Name of the inverse relationship for bidirectional traversal. Optional.
                            # Used in queries like "Interface INTERFACE_OF Device".

attributes:                 # Same format as NodeType attributes. Optional.
  <attribute_name>:
    type: string
    required: boolean
    # ... (same attribute fields as NodeType attributes)

constraints:
  unique_source: boolean    # Each source can have at most one edge of this type to any target. Default: false.
  unique_target: boolean    # Each target can have at most one edge of this type from any source. Default: false.
  unique_pair: boolean      # The (source, target) pair must be unique. Default: true.
  prevent_self_loop: boolean # Prevent source == target. Default: true.
  cascading_delete: string  # "none", "source" (delete edge when source is deleted),
                            # "target" (delete edge when target is deleted),
                            # "both". Default: "both".
  max_edges_per_source: integer | null  # Maximum edges from a single source. Optional.
  max_edges_per_target: integer | null  # Maximum edges to a single target. Optional.

graph:
  style: string             # "solid", "dashed", "dotted". Default: "solid".
  color: string             # Hex color. Default: "#94A3B8".
  width: integer            # Line width in pixels. Default: 1.
  show_label: boolean       # Show relationship type as label on the edge. Default: false.
  label_field: string       # Attribute to use as edge label (instead of type name). Optional.
  animate: boolean          # Animate the edge (e.g., moving dots for traffic flow). Default: false.
  curve_style: string       # "straight", "bezier", "taxi". Default: "bezier".

api:
  exposed: boolean          # Whether this edge type has dedicated REST endpoints. Default: true.
  filterable_fields: list[string] # Edge attribute fields that accept filters. Optional.
  nested_in_source: boolean # Whether this edge appears as a nested resource under the source. Default: true.
                            # e.g., /api/v1/devices/{id}/interfaces
  nested_in_target: boolean # Whether this edge appears as a nested resource under the target. Default: false.

permissions:
  default_read: string      # Default: inherits from source node type.
  default_write: string     # Default: inherits from source node type.
  default_delete: string    # Default: inherits from source node type.
```

---

### 7.4 Mixin Format

Mixins define reusable sets of attributes that can be included in multiple node types. They reduce duplication and enforce consistent field definitions across the schema.

```yaml
kind: Mixin
version: v1

metadata:
  name: string              # snake_case identifier. Required.
  description: string       # What this mixin provides. Required.
  tags: list[string]        # Optional.

attributes:                 # Same format as NodeType attributes. Required.
  <attribute_name>:
    type: string
    required: boolean
    auto_set: string        # Automatic value assignment trigger. Optional.
                            # "create" - set on node creation only
                            # "update" - set on every update
                            # "actor"  - set to the current user's identifier
                            # "timestamp_create" - set to current timestamp on create
                            # "timestamp_update" - set to current timestamp on update
    # ... (same attribute fields as NodeType attributes)
```

**Mixin composition rules:**
- A node type can include multiple mixins.
- Mixin attributes are merged into the node type's attribute set.
- If two mixins define the same attribute name, the schema loader raises a conflict error at load time.
- A node type can override a mixin attribute by redefining it locally (the local definition wins, but a warning is emitted).
- Mixins cannot include other mixins (no nesting). This prevents circular dependency issues.

---

### 7.5 Enum Type Format

Enum types define reusable sets of allowed values with display metadata. They can be referenced from any attribute using `enum_ref` instead of inline `enum_values`.

```yaml
kind: EnumType
version: v1

metadata:
  name: string              # PascalCase identifier. Required.
  description: string       # Required.
  tags: list[string]        # Optional.

values:
  - name: string            # The stored value (snake_case). Required.
    display_name: string    # Human-readable label. Required.
    color: string           # Color name or hex code for UI badges. Optional.
    description: string     # Tooltip or help text. Optional.
    icon: string            # Icon identifier. Optional.
    sort_order: integer     # Explicit sort order (lower = first). Optional.
    deprecated: boolean     # Mark value as deprecated. Default: false.

  - name: string
    ...

allow_custom: boolean       # Whether users can add values not in this list. Default: false.
                            # If true, the enum acts as a suggested list rather than a strict constraint.
```

---

### 7.6 Supported Attribute Types

| Type            | Storage       | Validation                                     | Example                          |
|-----------------|---------------|-------------------------------------------------|----------------------------------|
| `string`        | String        | `max_length`, `min_length`, `pattern`           | `"core-rtr-01.example.com"`     |
| `text`          | String        | `max_length` (default: 65535)                   | Multi-line free text             |
| `integer`       | Integer       | `min_value`, `max_value`                        | `42`                             |
| `float`         | Float         | `min_value`, `max_value`, `precision`           | `3.14`                           |
| `boolean`       | Boolean       | ---                                             | `true`                           |
| `datetime`      | ISO 8601 str  | Parsed and validated; stored as temporal type in Neo4j, ISO string in AGE | `"2026-03-28T14:30:00Z"` |
| `date`          | ISO 8601 str  | `YYYY-MM-DD` format                            | `"2026-03-28"`                   |
| `json`          | JSON string   | Optionally validated against a JSON Schema      | `{"key": "value"}`              |
| `ip_address`    | String        | Valid IPv4 or IPv6 address                      | `"10.0.1.1"`, `"2001:db8::1"`  |
| `cidr`          | String        | Valid CIDR notation                             | `"10.0.1.0/24"`                 |
| `mac_address`   | String        | Valid MAC address (normalized to `XX:XX:XX:XX:XX:XX`) | `"00:1A:2B:3C:4D:5E"`    |
| `url`           | String        | Valid URL format                                | `"https://example.com"`         |
| `email`         | String        | Valid email format                              | `"admin@example.com"`           |
| `enum`          | String        | Value must be in `enum_values` or `enum_ref`    | `"active"`                       |
| `reference`     | String        | Must be a valid node ID of the referenced type. Soft reference --- not an edge. | `"abc-123"` |
| `list[string]`  | JSON array    | Each item validated as the inner type           | `["eth0", "eth1"]`              |
| `list[integer]` | JSON array    | Each item validated as integer                  | `[1, 2, 3]`                     |
| `list[ip_address]` | JSON array | Each item validated as IP address               | `["10.0.1.1", "10.0.1.2"]`     |

**Network-specific types** (`ip_address`, `cidr`, `mac_address`) have dedicated input widgets in the UI, support specialized search (prefix matching for IPs, subnet containment for CIDRs), and are normalized on write (MAC addresses uppercased and colon-separated, IP addresses canonicalized).

**`reference` type** is for loose cross-references where a full graph edge is inappropriate (e.g., linking to an external system's ID). For actual relationships between nodes, always use EdgeType definitions.

---

### 7.7 Schema Validation Rules

The schema registry validates all loaded schema files against the following rules. Validation is performed at load time and blocks startup if critical rules are violated.

**Structural rules:**

| Rule | Severity | Description |
|------|----------|-------------|
| SV-001 | Error | `kind` must be one of `NodeType`, `EdgeType`, `Mixin`, `EnumType`. |
| SV-002 | Error | `version` must be a supported version (`v1`). |
| SV-003 | Error | `metadata.name` is required and must be non-empty. |
| SV-004 | Error | NodeType `metadata.name` must be PascalCase and contain only alphanumeric characters. |
| SV-005 | Error | EdgeType `metadata.name` must be UPPER_SNAKE_CASE. |
| SV-006 | Error | Mixin `metadata.name` must be snake_case. |
| SV-007 | Error | Attribute names must be snake_case and contain only `[a-z0-9_]`. |
| SV-008 | Error | Attribute `type` must be a supported type (see Section 7.6). |

**Reference integrity rules:**

| Rule | Severity | Description |
|------|----------|-------------|
| SV-010 | Error | All node types referenced in EdgeType `source.node_types` and `target.node_types` must exist. |
| SV-011 | Error | All mixins referenced in NodeType `mixins` must exist. |
| SV-012 | Error | All EnumType names referenced via `enum_ref` must exist. |
| SV-013 | Error | `reference` type attributes must specify a valid `ref_node_type` that exists. |
| SV-014 | Error | No circular mixin dependencies (mixins cannot include other mixins, so this is enforced structurally). |

**Constraint rules:**

| Rule | Severity | Description |
|------|----------|-------------|
| SV-020 | Error | `unique: true` is only valid on indexable types (`string`, `integer`, `ip_address`, `mac_address`, `email`, `url`). |
| SV-021 | Error | `enum_values` must be a non-empty list when `type: enum` is used without `enum_ref`. |
| SV-022 | Error | `enum_values` and `enum_ref` are mutually exclusive. |
| SV-023 | Error | `default` value must be valid for the declared type. |
| SV-024 | Error | `min_value` must be less than or equal to `max_value`. |
| SV-025 | Error | `min_length` must be less than or equal to `max_length`. |
| SV-026 | Warning | `indexed: true` on a field with `unique: true` is redundant (unique implies index). |

**Reserved name rules:**

| Rule | Severity | Description |
|------|----------|-------------|
| SV-030 | Error | Attribute names `id`, `_id`, `_type`, `_labels`, `_node_type`, `_edge_type`, `_source`, `_target` are reserved and rejected. |
| SV-031 | Error | NodeType names `Node`, `Relationship`, `Path`, `Query` are reserved. |
| SV-032 | Warning | Attribute names starting with `_` are reserved for system use and discouraged. |

**Cardinality rules:**

| Rule | Severity | Description |
|------|----------|-------------|
| SV-040 | Error | EdgeType `cardinality` must be one of `one_to_one`, `one_to_many`, `many_to_one`, `many_to_many`. |
| SV-041 | Warning | `one_to_one` cardinality with `unique_pair: false` is contradictory. |
| SV-042 | Warning | `one_to_many` cardinality should set `unique_target: true` or `max_edges_per_target: 1`. |

---

### 7.8 Schema Migration

When schema files change (new files added, existing files modified, files removed), the schema migration system computes the difference, classifies risk, and generates a migration plan.

#### 7.8.1 Change Classification

| Risk Level  | Change Type                                            | Examples                                                |
|-------------|--------------------------------------------------------|---------------------------------------------------------|
| **Safe**    | Additive changes that cannot break existing data       | Add new attribute (optional), add new node type, add new edge type, add new enum value, add new mixin |
| **Cautious**| Changes that may require data backfill or validation   | Make optional attribute required, add unique constraint, add index, change default value, rename display_name |
| **Dangerous**| Changes that may cause data loss or break consumers   | Remove node type, remove edge type, remove attribute, change attribute type, remove enum value, change cardinality |

#### 7.8.2 Migration Plan

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeType(Enum):
    ADD_NODE_TYPE = "add_node_type"
    REMOVE_NODE_TYPE = "remove_node_type"
    ADD_EDGE_TYPE = "add_edge_type"
    REMOVE_EDGE_TYPE = "remove_edge_type"
    ADD_ATTRIBUTE = "add_attribute"
    REMOVE_ATTRIBUTE = "remove_attribute"
    MODIFY_ATTRIBUTE = "modify_attribute"
    ADD_CONSTRAINT = "add_constraint"
    REMOVE_CONSTRAINT = "remove_constraint"
    ADD_INDEX = "add_index"
    REMOVE_INDEX = "remove_index"
    ADD_ENUM_VALUE = "add_enum_value"
    REMOVE_ENUM_VALUE = "remove_enum_value"
    ADD_MIXIN = "add_mixin"
    REMOVE_MIXIN = "remove_mixin"
    MODIFY_CARDINALITY = "modify_cardinality"


@dataclass
class SchemaChange:
    """Describes a single schema change."""
    change_type: ChangeType
    target_kind: str                  # "NodeType", "EdgeType", "Mixin", "EnumType"
    target_name: str                  # e.g., "Device", "HAS_INTERFACE"
    field_name: str | None = None     # e.g., "hostname" (for attribute changes)
    old_value: Any = None             # previous value/definition
    new_value: Any = None             # new value/definition
    risk_level: str = "safe"          # "safe", "cautious", "dangerous"
    description: str = ""             # human-readable description of the change


class MigrationOpType(Enum):
    CREATE_CONSTRAINT = "create_constraint"
    DROP_CONSTRAINT = "drop_constraint"
    CREATE_INDEX = "create_index"
    DROP_INDEX = "drop_index"
    SET_DEFAULT_VALUE = "set_default_value"
    REMOVE_PROPERTY = "remove_property"
    RENAME_PROPERTY = "rename_property"
    MIGRATE_PROPERTY_TYPE = "migrate_property_type"
    CREATE_LABEL = "create_label"
    DROP_LABEL = "drop_label"
    BACKFILL_REQUIRED = "backfill_required"
    VALIDATE_DATA = "validate_data"
    CUSTOM_CYPHER = "custom_cypher"


@dataclass
class MigrationOperation:
    """A single database operation in the migration plan."""
    op_type: MigrationOpType
    target: str                       # label or relationship type
    details: dict[str, Any] = field(default_factory=dict)
    cypher: str | None = None         # generated Cypher statement
    parameters: dict[str, Any] = field(default_factory=dict)
    reversible: bool = True           # whether this operation can be rolled back
    rollback_cypher: str | None = None
    estimated_rows_affected: int | None = None


@dataclass
class DataImpactAssessment:
    """Assessment of how the migration affects existing data."""
    total_nodes_affected: int
    total_edges_affected: int
    nodes_by_type: dict[str, int]     # e.g., {"Device": 1523, "Interface": 8491}
    data_loss_risk: bool              # true if any operation may delete data
    requires_backfill: bool           # true if any new required field needs default values
    estimated_duration_seconds: float # rough estimate based on data volume
    sample_violations: list[str]      # examples of existing data that violates new constraints


@dataclass
class MigrationPlan:
    """Complete migration plan from one schema version to another."""
    plan_id: str                      # unique identifier
    changes: list[SchemaChange]
    risk_level: str                   # overall risk: max of all change risk levels
    operations: list[MigrationOperation]
    warnings: list[str]
    data_impact: DataImpactAssessment
    requires_approval: bool           # true if risk_level is "cautious" or "dangerous"
    created_at: str                   # ISO 8601 timestamp
    created_by: str                   # user or system that triggered the migration
```

#### 7.8.3 Migration Workflow

```
[1. Load New Schema Files]
        |
        v
[2. Diff Against Current Registry]
        |    Compare each NodeType, EdgeType, Mixin, EnumType
        |    Produce list of SchemaChange objects
        v
[3. Classify Changes]
        |    Assign risk_level to each change
        |    Compute overall risk_level
        v
[4. Generate Migration Plan]
        |    Convert changes to MigrationOperation objects
        |    Generate Cypher for each operation
        |    Generate rollback Cypher where possible
        v
[5. Dry-Run Validation]
        |    Sample existing data (up to 10,000 nodes per type)
        |    Check for constraint violations
        |    Estimate rows affected
        |    Produce DataImpactAssessment
        v
[6. Approval Gate]
        |    Safe: auto-approved
        |    Cautious: requires explicit user confirmation via API/CLI
        |    Dangerous: requires admin approval + confirmation prompt
        v
[7. Execute Migration]
        |    Run operations in order within a transaction (where supported)
        |    For large data migrations, batch in chunks of 1000
        |    Log each operation result
        v
[8. Update Registry]
        |    Replace in-memory schema registry
        |    Persist new schema version to database
        |    Emit schema_changed event for cache invalidation
        v
[9. Post-Migration Validation]
        |    Run constraint checks on all affected types
        |    Verify index creation
        |    Log migration completion with timing
```

**Rollback:** Every migration plan records rollback Cypher for reversible operations. If a migration fails partway through, the system attempts to roll back completed operations in reverse order. Irreversible operations (e.g., `REMOVE_PROPERTY` after data deletion) are flagged during planning so the operator knows the risk before approving.

---

## 8. Example Schema Files

The following are complete, production-ready schema definitions for a network source-of-truth deployment.

---

### 8.1 Mixin Definitions

#### 8.1.1 Lifecycle Mixin

```yaml
kind: Mixin
version: v1
metadata:
  name: lifecycle_mixin
  description: "Standard lifecycle tracking fields. Applied to all node types that track creation and modification timestamps and actors."
  tags: [system, audit]

attributes:
  created_at:
    type: datetime
    required: true
    indexed: true
    auto_set: timestamp_create
    description: "Timestamp when this record was created."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Audit"
      detail_order: 90
      form_visible: false
      filter: false

  updated_at:
    type: datetime
    required: true
    indexed: true
    auto_set: timestamp_update
    description: "Timestamp when this record was last modified."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Audit"
      detail_order: 91
      form_visible: false
      filter: false

  created_by:
    type: string
    required: true
    max_length: 255
    auto_set: actor
    description: "Username or service account that created this record."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Audit"
      detail_order: 92
      form_visible: false
      filter: false

  updated_by:
    type: string
    required: true
    max_length: 255
    auto_set: actor
    description: "Username or service account that last modified this record."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Audit"
      detail_order: 93
      form_visible: false
      filter: false
```

#### 8.1.2 Provenance Mixin

```yaml
kind: Mixin
version: v1
metadata:
  name: provenance_mixin
  description: "Data provenance tracking. Records where this data came from and how confident we are in its accuracy."
  tags: [system, provenance, quality]

attributes:
  source_type:
    type: enum
    enum_values: [manual, discovered, synced, imported]
    required: true
    default: manual
    description: >
      How this record entered the system.
      - manual: entered by a human through the UI or API
      - discovered: populated by an automated discovery/polling process
      - synced: synchronized from an external source-of-truth (e.g., IPAM, CMDB)
      - imported: bulk imported from a file (CSV, JSON, etc.)
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Provenance"
      detail_order: 80
      form_visible: false
      filter: true
      badge_colors:
        manual: blue
        discovered: green
        synced: purple
        imported: yellow

  source_id:
    type: string
    required: false
    max_length: 500
    indexed: true
    description: "Identifier of the external source (e.g., discovery job ID, sync source name, import batch ID)."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Provenance"
      detail_order: 81
      form_visible: false

  source_url:
    type: url
    required: false
    description: "URL linking back to the record in the external source system."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Provenance"
      detail_order: 82
      form_visible: false
      link: true

  last_verified_at:
    type: datetime
    required: false
    indexed: true
    description: "Timestamp when this record was last verified against its source (manually or by automated check)."
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Provenance"
      detail_order: 83
      form_visible: false

  confidence_score:
    type: float
    required: false
    min_value: 0.0
    max_value: 1.0
    default: 1.0
    description: >
      Confidence in the accuracy of this record, from 0.0 (no confidence) to 1.0 (fully verified).
      Discovery engines may set lower confidence for inferred data.
      Manual entries default to 1.0.
    ui:
      list_column: false
      detail_visible: true
      detail_section: "Provenance"
      detail_order: 84
      form_visible: false
      form_widget: number
```

---

### 8.2 Node Type Definitions

#### 8.2.1 Device

```yaml
kind: NodeType
version: v1
metadata:
  name: Device
  display_name: Device
  description: >
    A network device such as a router, switch, firewall, load balancer, or wireless controller.
    Devices are the primary objects in the network inventory and serve as anchor points for
    interfaces, software versions, hardware models, and service relationships.
  icon: server
  color: "#3B82F6"
  category: Infrastructure
  tags: [network, inventory, core]

attributes:
  hostname:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    pattern: "^[a-zA-Z0-9][a-zA-Z0-9._-]*$"
    description: "Fully qualified domain name or short hostname. Must be unique across the entire inventory."
    examples: ["core-rtr-01.dc-east.example.com", "sw-access-42"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      form_placeholder: "e.g., core-rtr-01.dc-east.example.com"
      form_help_text: "FQDN or short hostname. Must be unique."
      search_weight: 10
      copy_button: true
      monospace: true

  management_ip:
    type: ip_address
    required: false
    indexed: true
    description: "Primary management IP address (IPv4 or IPv6) used for device access."
    examples: ["10.0.1.1", "2001:db8::1"]
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: md
      detail_order: 2
      detail_section: "General"
      form_order: 3
      form_widget: ip_input
      form_placeholder: "e.g., 10.0.1.1"
      search_weight: 5
      filter: true
      copy_button: true
      monospace: true

  status:
    type: enum
    enum_values: [active, planned, staged, decommissioned, maintenance, failed]
    default: planned
    required: true
    indexed: true
    description: "Operational status of the device."
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: sm
      detail_order: 3
      detail_section: "General"
      form_order: 2
      form_widget: select
      filter: true
      badge_colors:
        active: green
        planned: blue
        staged: yellow
        decommissioned: red
        maintenance: orange
        failed: red

  role:
    type: enum
    enum_values:
      - router
      - core_switch
      - distribution_switch
      - access_switch
      - firewall
      - load_balancer
      - wireless_ap
      - wireless_controller
      - console_server
      - pdu
      - other
    required: true
    indexed: true
    description: "Functional role of the device in the network."
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: md
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: select
      filter: true

  serial_number:
    type: string
    required: false
    unique: true
    indexed: true
    max_length: 100
    description: "Manufacturer serial number."
    examples: ["FDO2145R0PL"]
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Hardware"
      form_order: 10
      search_weight: 8
      copy_button: true
      monospace: true

  asset_tag:
    type: string
    required: false
    unique: true
    indexed: true
    max_length: 100
    description: "Internal asset tracking identifier."
    examples: ["ASSET-2024-001234"]
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Hardware"
      form_order: 11
      search_weight: 7
      copy_button: true

  rack_position:
    type: integer
    required: false
    min_value: 1
    max_value: 48
    description: "Rack unit position (bottom of device)."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Hardware"
      form_order: 12
      form_widget: number
      form_help_text: "Rack unit number (1-48), counted from the bottom."

  rack_height:
    type: integer
    required: false
    min_value: 1
    max_value: 48
    default: 1
    description: "Height in rack units."
    ui:
      list_column: false
      detail_order: 13
      detail_section: "Hardware"
      form_order: 13
      form_widget: number

  primary_ipv4:
    type: ip_address
    required: false
    indexed: true
    description: "Primary IPv4 loopback or router-ID address."
    validators:
      - type: ipv4_only
    ui:
      list_column: false
      detail_order: 5
      detail_section: "General"
      form_order: 5
      form_widget: ip_input
      copy_button: true
      monospace: true

  primary_ipv6:
    type: ip_address
    required: false
    indexed: true
    description: "Primary IPv6 loopback address."
    validators:
      - type: ipv6_only
    ui:
      list_column: false
      detail_order: 6
      detail_section: "General"
      form_order: 6
      form_widget: ip_input
      copy_button: true
      monospace: true

  console_port:
    type: string
    required: false
    max_length: 255
    description: "Console server port identifier (e.g., 'cs01:2003')."
    ui:
      list_column: false
      detail_order: 14
      detail_section: "Hardware"
      form_order: 14
      monospace: true

  config_context:
    type: json
    required: false
    description: >
      Arbitrary JSON data associated with this device, typically used for configuration
      rendering and automation. Merges with context from location, role, and platform.
    ui:
      list_column: false
      detail_order: 30
      detail_section: "Configuration"
      form_order: 30
      form_widget: json_editor
      form_help_text: "Arbitrary key-value data in JSON format."

  notes:
    type: text
    required: false
    max_length: 10000
    description: "Free-form notes about this device. Supports Markdown."
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea
      form_placeholder: "Enter any relevant notes about this device..."

  tags:
    type: list[string]
    required: false
    description: "Freeform tags for ad-hoc categorization and filtering."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "General"
      form_order: 20
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: hostname
  search_fields: [hostname, management_ip, serial_number, asset_tag, notes]
  boost: 2.0

graph:
  default_label_field: hostname
  secondary_label_field: management_ip
  size_field: null
  size_range: [30, 60]
  group_by: role
  tooltip_fields: [hostname, management_ip, status, role]

api:
  plural_name: devices
  filterable_fields: [hostname, status, role, management_ip, serial_number, asset_tag, tags, primary_ipv4, primary_ipv6]
  sortable_fields: [hostname, status, role, management_ip, created_at, updated_at]
  default_sort: hostname
  default_sort_order: asc
  max_page_size: 1000
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
  field_permissions:
    serial_number:
      read: authenticated
      write: asset_manager
    asset_tag:
      read: authenticated
      write: asset_manager
    config_context:
      read: operator
      write: engineer
```

#### 8.2.2 Interface

```yaml
kind: NodeType
version: v1
metadata:
  name: Interface
  display_name: Interface
  description: >
    A physical or logical network interface on a device. Represents Ethernet ports,
    loopback interfaces, VLAN interfaces, port-channels, tunnel interfaces, and
    management interfaces.
  icon: ethernet-port
  color: "#10B981"
  category: Infrastructure
  tags: [network, inventory, interface]

attributes:
  name:
    type: string
    required: true
    indexed: true
    max_length: 255
    description: "Interface name as it appears on the device (e.g., GigabitEthernet0/0/1, Loopback0, Vlan100)."
    examples: ["GigabitEthernet0/0/1", "Loopback0", "Vlan100", "Port-channel1", "eth0"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      form_placeholder: "e.g., GigabitEthernet0/0/1"
      search_weight: 10
      copy_button: true
      monospace: true

  interface_type:
    type: enum
    enum_values:
      - physical
      - virtual
      - lag
      - loopback
      - vlan
      - tunnel
      - bridge
      - management
      - wireless
      - other
    required: true
    indexed: true
    description: "Classification of the interface."
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: sm
      detail_order: 2
      detail_section: "General"
      form_order: 2
      form_widget: select
      filter: true
      badge_colors:
        physical: blue
        virtual: purple
        lag: teal
        loopback: gray
        vlan: yellow
        tunnel: orange
        bridge: cyan
        management: green
        wireless: pink
        other: gray

  enabled:
    type: boolean
    required: true
    default: true
    description: "Administrative state of the interface (true = admin up)."
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: sm
      detail_order: 3
      detail_section: "General"
      form_order: 3
      form_widget: toggle
      filter: true

  description:
    type: string
    required: false
    max_length: 500
    description: "Interface description as configured on the device."
    examples: ["Uplink to core-rtr-02 Gi0/0/1", "Server VLAN"]
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: lg
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_placeholder: "Interface description"
      search_weight: 3
      truncate: 50

  speed:
    type: integer
    required: false
    min_value: 0
    description: "Interface speed in kilobits per second (kbps). 1000000 = 1 Gbps."
    examples: [100000, 1000000, 10000000, 25000000, 40000000, 100000000]
    ui:
      list_column: true
      list_column_order: 5
      list_column_width: sm
      detail_order: 10
      detail_section: "Physical"
      form_order: 10
      form_widget: select
      form_help_text: "Speed in kbps. Common values: 1G=1000000, 10G=10000000, 25G=25000000, 100G=100000000."
      filter: true

  mtu:
    type: integer
    required: false
    min_value: 68
    max_value: 65535
    default: 1500
    description: "Maximum transmission unit in bytes."
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Physical"
      form_order: 11
      form_widget: number
      form_help_text: "Standard Ethernet: 1500, Jumbo frames: 9000-9216."

  mac_address:
    type: mac_address
    required: false
    indexed: true
    description: "Burned-in MAC address of the interface."
    examples: ["00:1A:2B:3C:4D:5E"]
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Physical"
      form_order: 12
      form_widget: mac_input
      search_weight: 7
      copy_button: true
      monospace: true

  ip_addresses:
    type: list[ip_address]
    required: false
    description: "IP addresses assigned to this interface (IPv4 and/or IPv6 with prefix length)."
    examples: [["10.0.1.1/24", "2001:db8::1/64"]]
    ui:
      list_column: false
      detail_order: 5
      detail_section: "Addressing"
      form_order: 5
      form_widget: tag_input
      form_help_text: "Enter IP addresses with prefix length (e.g., 10.0.1.1/24)."
      search_weight: 6

  duplex:
    type: enum
    enum_values: [full, half, auto]
    required: false
    description: "Duplex setting."
    ui:
      list_column: false
      detail_order: 13
      detail_section: "Physical"
      form_order: 13
      form_widget: select

  mode:
    type: enum
    enum_values: [access, trunk, routed, tagged, untagged]
    required: false
    description: "Switchport mode or Layer 3 routed mode."
    ui:
      list_column: false
      detail_order: 6
      detail_section: "Switching"
      form_order: 6
      form_widget: select
      filter: true

  untagged_vlan:
    type: integer
    required: false
    min_value: 1
    max_value: 4094
    description: "Native/untagged VLAN ID."
    ui:
      list_column: false
      detail_order: 7
      detail_section: "Switching"
      form_order: 7
      form_widget: number

  tagged_vlans:
    type: list[integer]
    required: false
    description: "List of tagged/trunk VLAN IDs."
    ui:
      list_column: false
      detail_order: 8
      detail_section: "Switching"
      form_order: 8
      form_widget: tag_input
      form_help_text: "Enter VLAN IDs allowed on this trunk."

  lag_members:
    type: list[string]
    required: false
    description: "Member interface names (for LAG/port-channel interfaces)."
    ui:
      list_column: false
      detail_order: 15
      detail_section: "LAG"
      form_order: 15
      form_widget: tag_input

  tags:
    type: list[string]
    required: false
    description: "Freeform tags."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "General"
      form_order: 20
      form_widget: tag_input
      filter: true

  notes:
    type: text
    required: false
    max_length: 5000
    description: "Free-form notes. Supports Markdown."
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, description, mac_address, ip_addresses]
  boost: 1.5

graph:
  default_label_field: name
  secondary_label_field: description
  size_field: speed
  size_range: [15, 40]
  group_by: interface_type
  tooltip_fields: [name, interface_type, speed, ip_addresses, enabled]

api:
  plural_name: interfaces
  filterable_fields: [name, interface_type, enabled, speed, mode, mac_address, tags]
  sortable_fields: [name, interface_type, speed, enabled, created_at]
  default_sort: name
  default_sort_order: asc
  max_page_size: 5000
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.2.3 Location

```yaml
kind: NodeType
version: v1
metadata:
  name: Location
  display_name: Location
  description: >
    A physical location in the infrastructure hierarchy. Locations form a tree:
    Region > Site > Building > Floor > Room > Rack. Each location has a type that
    determines its position in the hierarchy.
  icon: map-pin
  color: "#F59E0B"
  category: Organization
  tags: [location, site, hierarchy]

attributes:
  name:
    type: string
    required: true
    indexed: true
    max_length: 255
    description: "Location name. Must be unique within its parent."
    examples: ["US-East", "dc-east-1", "Building A", "Floor 3", "MDF-1", "Rack-A01"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      form_placeholder: "e.g., dc-east-1"
      search_weight: 10

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    pattern: "^[a-z0-9][a-z0-9-]*$"
    description: "URL-safe unique identifier. Auto-generated from name if not provided."
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      form_help_text: "URL-safe slug. Auto-generated if left blank."
      monospace: true
      copy_button: true

  location_type:
    type: enum
    enum_values: [region, site, building, floor, room, rack, other]
    required: true
    indexed: true
    description: "Type of location in the hierarchy."
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: sm
      detail_order: 3
      detail_section: "General"
      form_order: 3
      form_widget: select
      filter: true
      badge_colors:
        region: purple
        site: blue
        building: teal
        floor: cyan
        room: green
        rack: yellow
        other: gray

  parent_type:
    type: reference
    required: false
    description: >
      Soft reference to the parent Location's ID. The actual parent relationship
      is modeled as an edge (CHILD_OF), but this field enables quick hierarchy lookups
      without a graph traversal.
    ui:
      list_column: false
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: autocomplete
      form_help_text: "Select the parent location."

  full_path:
    type: string
    required: false
    indexed: true
    max_length: 1000
    computed: true
    description: "Materialized full path in the hierarchy (e.g., 'US-East / dc-east-1 / Building A / Floor 3'). Computed automatically."
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: xl
      detail_order: 5
      detail_section: "General"
      form_visible: false
      search_weight: 5
      truncate: 60

  status:
    type: enum
    enum_values: [active, planned, decommissioned]
    default: active
    required: true
    indexed: true
    description: "Operational status of this location."
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: sm
      detail_order: 6
      detail_section: "General"
      form_order: 5
      form_widget: select
      filter: true
      badge_colors:
        active: green
        planned: blue
        decommissioned: red

  physical_address:
    type: text
    required: false
    max_length: 1000
    description: "Street address of this location."
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Physical"
      form_order: 10
      form_widget: textarea

  latitude:
    type: float
    required: false
    min_value: -90.0
    max_value: 90.0
    description: "GPS latitude."
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Physical"
      form_order: 11

  longitude:
    type: float
    required: false
    min_value: -180.0
    max_value: 180.0
    description: "GPS longitude."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Physical"
      form_order: 12

  timezone:
    type: string
    required: false
    max_length: 50
    description: "IANA timezone identifier."
    examples: ["America/New_York", "Europe/London", "Asia/Tokyo"]
    ui:
      list_column: false
      detail_order: 13
      detail_section: "Physical"
      form_order: 13
      form_widget: autocomplete

  contact_name:
    type: string
    required: false
    max_length: 255
    description: "Name of the primary contact for this location."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "Contact"
      form_order: 20

  contact_email:
    type: email
    required: false
    description: "Email of the primary contact."
    ui:
      list_column: false
      detail_order: 21
      detail_section: "Contact"
      form_order: 21

  contact_phone:
    type: string
    required: false
    max_length: 30
    description: "Phone number of the primary contact."
    ui:
      list_column: false
      detail_order: 22
      detail_section: "Contact"
      form_order: 22

  notes:
    type: text
    required: false
    max_length: 10000
    description: "Free-form notes. Supports Markdown."
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    description: "Freeform tags."
    ui:
      list_column: false
      detail_order: 25
      detail_section: "General"
      form_order: 25
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, slug, full_path, physical_address]
  boost: 1.5

graph:
  default_label_field: name
  secondary_label_field: location_type
  size_field: null
  size_range: [25, 50]
  group_by: location_type
  tooltip_fields: [name, location_type, full_path, status]

api:
  plural_name: locations
  filterable_fields: [name, slug, location_type, status, tags]
  sortable_fields: [name, location_type, status, full_path, created_at]
  default_sort: full_path
  default_sort_order: asc
  max_page_size: 1000
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.2.4 Vendor

```yaml
kind: NodeType
version: v1
metadata:
  name: Vendor
  display_name: Vendor
  description: "A hardware or software manufacturer (e.g., Cisco, Juniper, Arista, Palo Alto Networks)."
  icon: building-2
  color: "#8B5CF6"
  category: Inventory
  tags: [vendor, manufacturer, inventory]

attributes:
  name:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    description: "Vendor name."
    examples: ["Cisco", "Juniper Networks", "Arista Networks", "Palo Alto Networks"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 100
    pattern: "^[a-z0-9][a-z0-9-]*$"
    description: "URL-safe identifier."
    examples: ["cisco", "juniper-networks", "arista-networks"]
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true
      copy_button: true

  website:
    type: url
    required: false
    description: "Vendor website URL."
    ui:
      list_column: false
      detail_order: 3
      detail_section: "General"
      form_order: 3
      link: true

  support_url:
    type: url
    required: false
    description: "Vendor support portal URL."
    ui:
      list_column: false
      detail_order: 4
      detail_section: "General"
      form_order: 4
      link: true

  account_number:
    type: string
    required: false
    max_length: 100
    sensitive: true
    description: "Your organization's account number with this vendor."
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Account"
      form_order: 10

  contract_id:
    type: string
    required: false
    max_length: 100
    description: "Active support contract identifier."
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Account"
      form_order: 11

  notes:
    type: text
    required: false
    max_length: 5000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 20
      detail_section: "General"
      form_order: 20
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, slug]
  boost: 1.0

graph:
  default_label_field: name
  secondary_label_field: null
  size_field: null
  size_range: [20, 40]
  group_by: null
  tooltip_fields: [name, website]

api:
  plural_name: vendors
  filterable_fields: [name, slug, tags]
  sortable_fields: [name, created_at]
  default_sort: name
  default_sort_order: asc
  max_page_size: 500
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
  field_permissions:
    account_number:
      read: asset_manager
      write: admin
```

#### 8.2.5 HardwareModel

```yaml
kind: NodeType
version: v1
metadata:
  name: HardwareModel
  display_name: Hardware Model
  description: >
    A specific hardware model produced by a vendor (e.g., Cisco Catalyst 9300-48P,
    Juniper QFX5120-48Y). Devices reference a hardware model to track what physical
    equipment is deployed.
  icon: cpu
  color: "#EC4899"
  category: Inventory
  tags: [hardware, model, inventory]

attributes:
  model:
    type: string
    required: true
    indexed: true
    max_length: 255
    description: "Model number or name as designated by the vendor."
    examples: ["C9300-48P", "QFX5120-48Y", "PA-5250", "DCS-7280SR-48C6"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10
      copy_button: true
      monospace: true

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    pattern: "^[a-z0-9][a-z0-9-]*$"
    description: "URL-safe unique identifier combining vendor and model."
    examples: ["cisco-c9300-48p", "juniper-qfx5120-48y"]
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true
      copy_button: true

  part_number:
    type: string
    required: false
    indexed: true
    max_length: 100
    description: "Vendor part number for ordering."
    examples: ["C9300-48P-A", "QFX5120-48Y-AFO"]
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: md
      detail_order: 3
      detail_section: "General"
      form_order: 3
      search_weight: 5
      monospace: true

  description:
    type: string
    required: false
    max_length: 500
    description: "Human-readable description of the hardware model."
    examples: ["Catalyst 9300 48-port PoE+ switch"]
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: lg
      detail_order: 4
      detail_section: "General"
      form_order: 4
      search_weight: 3
      truncate: 60

  form_factor:
    type: enum
    enum_values:
      - rack_mount_1u
      - rack_mount_2u
      - rack_mount_4u
      - modular_chassis
      - half_width
      - desktop
      - wall_mount
      - din_rail
      - virtual
      - other
    required: false
    description: "Physical form factor."
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Physical"
      form_order: 10
      form_widget: select
      filter: true

  rack_units:
    type: integer
    required: false
    min_value: 1
    max_value: 48
    description: "Height in rack units."
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Physical"
      form_order: 11

  max_power_watts:
    type: integer
    required: false
    min_value: 0
    description: "Maximum power consumption in watts."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Physical"
      form_order: 12

  weight_kg:
    type: float
    required: false
    min_value: 0.0
    description: "Weight in kilograms."
    ui:
      list_column: false
      detail_order: 13
      detail_section: "Physical"
      form_order: 13

  interface_count:
    type: integer
    required: false
    min_value: 0
    description: "Total number of built-in network interfaces."
    ui:
      list_column: false
      detail_order: 14
      detail_section: "Physical"
      form_order: 14

  is_full_depth:
    type: boolean
    required: false
    default: true
    description: "Whether the device occupies the full depth of the rack."
    ui:
      list_column: false
      detail_order: 15
      detail_section: "Physical"
      form_order: 15
      form_widget: toggle

  end_of_sale:
    type: date
    required: false
    description: "Vendor end-of-sale date."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "Lifecycle"
      form_order: 20
      form_widget: date_picker

  end_of_support:
    type: date
    required: false
    description: "Vendor end-of-support date."
    ui:
      list_column: false
      detail_order: 21
      detail_section: "Lifecycle"
      form_order: 21
      form_widget: date_picker

  notes:
    type: text
    required: false
    max_length: 5000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 25
      detail_section: "General"
      form_order: 25
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: model
  search_fields: [model, slug, part_number, description]
  boost: 1.0

graph:
  default_label_field: model
  secondary_label_field: description
  size_field: null
  size_range: [20, 40]
  group_by: form_factor
  tooltip_fields: [model, part_number, form_factor, rack_units]

api:
  plural_name: hardware-models
  filterable_fields: [model, slug, part_number, form_factor, tags]
  sortable_fields: [model, part_number, form_factor, created_at]
  default_sort: model
  default_sort_order: asc
  max_page_size: 500
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.2.6 SoftwareVersion

```yaml
kind: NodeType
version: v1
metadata:
  name: SoftwareVersion
  display_name: Software Version
  description: >
    A specific version of network operating system software (e.g., IOS-XE 17.9.4a,
    NX-OS 10.3(2), EOS 4.30.1F). Tracks version strings, end-of-life dates, and
    known vulnerability status.
  icon: package
  color: "#06B6D4"
  category: Software
  tags: [software, version, lifecycle]

attributes:
  version:
    type: string
    required: true
    indexed: true
    max_length: 100
    description: "Version string as designated by the vendor."
    examples: ["17.9.4a", "10.3(2)", "4.30.1F", "22.2R1.1"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: md
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10
      copy_button: true
      monospace: true

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    pattern: "^[a-z0-9][a-z0-9._-]*$"
    description: "URL-safe unique identifier combining platform and version."
    examples: ["ios-xe-17.9.4a", "nx-os-10.3.2", "eos-4.30.1f"]
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true
      copy_button: true

  display_name:
    type: string
    required: false
    max_length: 255
    description: "Human-readable display name."
    examples: ["Cisco IOS-XE 17.9.4a", "Arista EOS 4.30.1F"]
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: lg
      detail_order: 3
      detail_section: "General"
      form_order: 3
      search_weight: 5

  release_date:
    type: date
    required: false
    description: "Date this version was released by the vendor."
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: sm
      detail_order: 10
      detail_section: "Lifecycle"
      form_order: 10
      form_widget: date_picker
      filter: true

  end_of_support:
    type: date
    required: false
    indexed: true
    description: "Date vendor support ends for this version."
    ui:
      list_column: true
      list_column_order: 5
      list_column_width: sm
      detail_order: 11
      detail_section: "Lifecycle"
      form_order: 11
      form_widget: date_picker
      filter: true

  end_of_life:
    type: date
    required: false
    indexed: true
    description: "Date this version reaches full end-of-life (no patches, no support)."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Lifecycle"
      form_order: 12
      form_widget: date_picker
      filter: true

  status:
    type: enum
    enum_values: [current, deprecated, end_of_support, end_of_life]
    default: current
    required: true
    indexed: true
    description: "Lifecycle status of this software version."
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: sm
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: select
      filter: true
      badge_colors:
        current: green
        deprecated: yellow
        end_of_support: orange
        end_of_life: red

  is_lts:
    type: boolean
    required: false
    default: false
    description: "Whether this is a Long Term Support (LTS) or Extended Maintenance release."
    ui:
      list_column: false
      detail_order: 5
      detail_section: "General"
      form_order: 5
      form_widget: toggle
      filter: true

  known_cves:
    type: list[string]
    required: false
    description: "List of known CVE identifiers affecting this version."
    examples: [["CVE-2024-20356", "CVE-2024-20359"]]
    ui:
      list_column: false
      detail_order: 20
      detail_section: "Security"
      form_order: 20
      form_widget: tag_input
      monospace: true

  cve_count:
    type: integer
    required: false
    default: 0
    min_value: 0
    computed: true
    description: "Number of known CVEs. Computed from known_cves list length."
    ui:
      list_column: false
      detail_order: 21
      detail_section: "Security"
      form_visible: false

  release_notes_url:
    type: url
    required: false
    description: "URL to the vendor's release notes for this version."
    ui:
      list_column: false
      detail_order: 30
      detail_section: "References"
      form_order: 30
      link: true

  notes:
    type: text
    required: false
    max_length: 5000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 25
      detail_section: "General"
      form_order: 25
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: version
  search_fields: [version, slug, display_name]
  boost: 1.0

graph:
  default_label_field: version
  secondary_label_field: status
  size_field: null
  size_range: [20, 40]
  group_by: status
  tooltip_fields: [version, display_name, status, end_of_support]

api:
  plural_name: software-versions
  filterable_fields: [version, slug, status, is_lts, end_of_support, end_of_life, tags]
  sortable_fields: [version, status, release_date, end_of_support, created_at]
  default_sort: version
  default_sort_order: desc
  max_page_size: 500
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.2.7 Image

```yaml
kind: NodeType
version: v1
metadata:
  name: Image
  display_name: Image
  description: >
    A firmware or software image file that can be deployed to network devices.
    Tracks file metadata (name, size, checksums), storage location, and
    relationships to the software version and platforms it supports.
  icon: file-code
  color: "#14B8A6"
  category: Software
  tags: [software, image, firmware, deployment]

attributes:
  filename:
    type: string
    required: true
    indexed: true
    max_length: 500
    description: "Image filename as stored on the file server."
    examples: ["cat9k_iosxe.17.09.04a.SPA.bin", "nxos64-cs.10.3.2.F.bin"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: xl
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10
      copy_button: true
      monospace: true

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 500
    pattern: "^[a-z0-9][a-z0-9._-]*$"
    description: "URL-safe unique identifier."
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true

  file_size_bytes:
    type: integer
    required: false
    min_value: 0
    description: "Image file size in bytes."
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: md
      detail_order: 10
      detail_section: "File"
      form_order: 10

  md5_checksum:
    type: string
    required: false
    max_length: 32
    pattern: "^[a-f0-9]{32}$"
    description: "MD5 checksum of the image file."
    ui:
      list_column: false
      detail_order: 11
      detail_section: "File"
      form_order: 11
      copy_button: true
      monospace: true

  sha256_checksum:
    type: string
    required: false
    max_length: 64
    pattern: "^[a-f0-9]{64}$"
    description: "SHA-256 checksum of the image file."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "File"
      form_order: 12
      copy_button: true
      monospace: true

  sha512_checksum:
    type: string
    required: false
    max_length: 128
    pattern: "^[a-f0-9]{128}$"
    description: "SHA-512 checksum of the image file."
    ui:
      list_column: false
      detail_order: 13
      detail_section: "File"
      form_order: 13
      copy_button: true
      monospace: true

  storage_url:
    type: url
    required: false
    description: "URL where the image file is stored (e.g., S3 bucket, internal HTTP server, TFTP path)."
    examples: ["s3://network-images/ios-xe/cat9k_iosxe.17.09.04a.SPA.bin"]
    ui:
      list_column: false
      detail_order: 14
      detail_section: "File"
      form_order: 14
      copy_button: true

  image_type:
    type: enum
    enum_values: [system, boot, kickstart, combined, rommon, epld, maintenance, other]
    required: true
    default: system
    description: "Type of image file."
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: sm
      detail_order: 3
      detail_section: "General"
      form_order: 3
      form_widget: select
      filter: true
      badge_colors:
        system: blue
        boot: purple
        kickstart: teal
        combined: green
        rommon: orange
        epld: yellow
        maintenance: gray
        other: gray

  status:
    type: enum
    enum_values: [active, deprecated, recalled]
    default: active
    required: true
    indexed: true
    description: "Availability status of this image."
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: sm
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: select
      filter: true
      badge_colors:
        active: green
        deprecated: yellow
        recalled: red

  compatible_models:
    type: list[string]
    required: false
    description: "List of HardwareModel slugs this image is compatible with."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "Compatibility"
      form_order: 20
      form_widget: tag_input

  minimum_ram_mb:
    type: integer
    required: false
    min_value: 0
    description: "Minimum RAM required in megabytes."
    ui:
      list_column: false
      detail_order: 21
      detail_section: "Compatibility"
      form_order: 21

  minimum_flash_mb:
    type: integer
    required: false
    min_value: 0
    description: "Minimum flash storage required in megabytes."
    ui:
      list_column: false
      detail_order: 22
      detail_section: "Compatibility"
      form_order: 22

  notes:
    type: text
    required: false
    max_length: 5000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 25
      detail_section: "General"
      form_order: 25
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: filename
  search_fields: [filename, slug, md5_checksum, sha256_checksum]
  boost: 0.8

graph:
  default_label_field: filename
  secondary_label_field: image_type
  size_field: file_size_bytes
  size_range: [15, 35]
  group_by: image_type
  tooltip_fields: [filename, image_type, file_size_bytes, status]

api:
  plural_name: images
  filterable_fields: [filename, slug, image_type, status, tags]
  sortable_fields: [filename, image_type, status, file_size_bytes, created_at]
  default_sort: filename
  default_sort_order: asc
  max_page_size: 500
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: engineer
  default_delete: admin
```

#### 8.2.8 Platform

```yaml
kind: NodeType
version: v1
metadata:
  name: Platform
  display_name: Platform
  description: >
    A network operating system platform (e.g., Cisco IOS-XE, Cisco NX-OS, Arista EOS,
    Juniper JunOS, Palo Alto PAN-OS). Platforms group software versions and provide
    context for automation drivers and configuration templates.
  icon: terminal
  color: "#6366F1"
  category: Software
  tags: [platform, os, automation]

attributes:
  name:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 100
    description: "Platform name."
    examples: ["IOS-XE", "NX-OS", "EOS", "JunOS", "PAN-OS", "FortiOS", "ScreenOS", "AOS-CX"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: md
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 100
    pattern: "^[a-z0-9][a-z0-9-]*$"
    description: "URL-safe unique identifier."
    examples: ["ios-xe", "nx-os", "eos", "junos", "pan-os"]
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true
      copy_button: true

  display_name:
    type: string
    required: true
    max_length: 255
    description: "Full display name including vendor."
    examples: ["Cisco IOS-XE", "Cisco NX-OS", "Arista EOS", "Juniper JunOS"]
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: lg
      detail_order: 3
      detail_section: "General"
      form_order: 3
      search_weight: 5

  description:
    type: text
    required: false
    max_length: 2000
    description: "Description of the platform, its use cases, and capabilities."
    ui:
      list_column: false
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: textarea

  napalm_driver:
    type: string
    required: false
    max_length: 50
    description: "NAPALM driver name for this platform."
    examples: ["ios", "nxos", "eos", "junos", "panos"]
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Automation"
      form_order: 10
      monospace: true

  netmiko_device_type:
    type: string
    required: false
    max_length: 50
    description: "Netmiko device_type string for this platform."
    examples: ["cisco_xe", "cisco_nxos", "arista_eos", "juniper_junos", "paloalto_panos"]
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Automation"
      form_order: 11
      monospace: true

  ansible_network_os:
    type: string
    required: false
    max_length: 100
    description: "Ansible network_os value for this platform."
    examples: ["cisco.ios.ios", "cisco.nxos.nxos", "arista.eos.eos", "junipernetworks.junos.junos"]
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Automation"
      form_order: 12
      monospace: true

  nornir_platform:
    type: string
    required: false
    max_length: 50
    description: "Nornir platform identifier."
    examples: ["ios", "nxos", "eos", "junos"]
    ui:
      list_column: false
      detail_order: 13
      detail_section: "Automation"
      form_order: 13
      monospace: true

  config_template_language:
    type: enum
    enum_values: [jinja2, mako, genshi, none]
    default: jinja2
    required: false
    description: "Default template language for configuration rendering."
    ui:
      list_column: false
      detail_order: 14
      detail_section: "Automation"
      form_order: 14

  notes:
    type: text
    required: false
    max_length: 5000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 20
      detail_section: "General"
      form_order: 20
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, slug, display_name, napalm_driver, netmiko_device_type]
  boost: 1.0

graph:
  default_label_field: name
  secondary_label_field: display_name
  size_field: null
  size_range: [25, 45]
  group_by: null
  tooltip_fields: [name, display_name, napalm_driver]

api:
  plural_name: platforms
  filterable_fields: [name, slug, napalm_driver, netmiko_device_type, tags]
  sortable_fields: [name, display_name, created_at]
  default_sort: name
  default_sort_order: asc
  max_page_size: 100
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: engineer
  default_delete: admin
```

#### 8.2.9 Service

```yaml
kind: NodeType
version: v1
metadata:
  name: Service
  display_name: Service
  description: >
    A network service definition representing a logical service running on or
    provided by one or more devices. Examples include DNS, DHCP, NTP, BGP route
    reflectors, load balancer VIPs, VPN tunnels, and application-level services.
    Services can depend on other services, forming a dependency graph.
  icon: globe
  color: "#F97316"
  category: Services
  tags: [service, application, dependency]

attributes:
  name:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    description: "Service name."
    examples: ["DNS-Primary", "NTP-Pool", "BGP-RR-Cluster", "LB-VIP-WebApp", "MPLS-VPN-Customer-A"]
    ui:
      list_column: true
      list_column_order: 1
      list_column_width: lg
      detail_order: 1
      detail_section: "General"
      form_order: 1
      search_weight: 10

  slug:
    type: string
    required: true
    unique: true
    indexed: true
    max_length: 255
    pattern: "^[a-z0-9][a-z0-9-]*$"
    ui:
      list_column: false
      detail_order: 2
      detail_section: "General"
      form_order: 2
      monospace: true
      copy_button: true

  description:
    type: text
    required: false
    max_length: 5000
    description: "Detailed description of the service."
    ui:
      list_column: true
      list_column_order: 3
      list_column_width: lg
      detail_order: 3
      detail_section: "General"
      form_order: 3
      form_widget: textarea
      search_weight: 3
      truncate: 60

  service_type:
    type: enum
    enum_values:
      - infrastructure
      - network
      - security
      - monitoring
      - dns
      - dhcp
      - ntp
      - routing
      - load_balancing
      - vpn
      - application
      - other
    required: true
    indexed: true
    description: "Classification of the service."
    ui:
      list_column: true
      list_column_order: 2
      list_column_width: md
      detail_order: 4
      detail_section: "General"
      form_order: 4
      form_widget: select
      filter: true
      badge_colors:
        infrastructure: blue
        network: teal
        security: red
        monitoring: purple
        dns: cyan
        dhcp: cyan
        ntp: cyan
        routing: green
        load_balancing: orange
        vpn: yellow
        application: pink
        other: gray

  status:
    type: enum
    enum_values: [active, planned, degraded, maintenance, decommissioned]
    default: planned
    required: true
    indexed: true
    description: "Current operational status of the service."
    ui:
      list_column: true
      list_column_order: 4
      list_column_width: sm
      detail_order: 5
      detail_section: "General"
      form_order: 5
      form_widget: select
      filter: true
      badge_colors:
        active: green
        planned: blue
        degraded: orange
        maintenance: yellow
        decommissioned: red

  criticality:
    type: enum
    enum_values: [critical, high, medium, low]
    default: medium
    required: true
    description: "Business criticality level."
    ui:
      list_column: true
      list_column_order: 5
      list_column_width: sm
      detail_order: 6
      detail_section: "General"
      form_order: 6
      form_widget: select
      filter: true
      badge_colors:
        critical: red
        high: orange
        medium: yellow
        low: gray

  protocol:
    type: string
    required: false
    max_length: 50
    description: "Primary protocol (e.g., TCP, UDP, BGP, OSPF, VRRP)."
    examples: ["TCP", "UDP", "BGP", "OSPF", "VRRP", "HSRP"]
    ui:
      list_column: false
      detail_order: 10
      detail_section: "Technical"
      form_order: 10
      filter: true

  ports:
    type: list[integer]
    required: false
    description: "TCP/UDP port numbers associated with this service."
    examples: [[53, 853], [80, 443], [123]]
    ui:
      list_column: false
      detail_order: 11
      detail_section: "Technical"
      form_order: 11
      form_widget: tag_input

  ip_addresses:
    type: list[ip_address]
    required: false
    description: "Service IP addresses (VIPs, anycast addresses, etc.)."
    ui:
      list_column: false
      detail_order: 12
      detail_section: "Technical"
      form_order: 12
      form_widget: tag_input
      search_weight: 5

  owner:
    type: string
    required: false
    max_length: 255
    description: "Team or individual responsible for this service."
    ui:
      list_column: false
      detail_order: 20
      detail_section: "Ownership"
      form_order: 20
      filter: true

  owner_email:
    type: email
    required: false
    description: "Contact email for the service owner."
    ui:
      list_column: false
      detail_order: 21
      detail_section: "Ownership"
      form_order: 21

  sla_target:
    type: float
    required: false
    min_value: 0.0
    max_value: 100.0
    description: "SLA availability target as a percentage (e.g., 99.99)."
    ui:
      list_column: false
      detail_order: 22
      detail_section: "Ownership"
      form_order: 22

  documentation_url:
    type: url
    required: false
    description: "Link to the service's operational documentation."
    ui:
      list_column: false
      detail_order: 30
      detail_section: "References"
      form_order: 30
      link: true

  monitoring_url:
    type: url
    required: false
    description: "Link to the service's monitoring dashboard."
    ui:
      list_column: false
      detail_order: 31
      detail_section: "References"
      form_order: 31
      link: true

  config_context:
    type: json
    required: false
    description: "Arbitrary JSON data for configuration rendering and automation."
    ui:
      list_column: false
      detail_order: 32
      detail_section: "Configuration"
      form_order: 32
      form_widget: json_editor

  notes:
    type: text
    required: false
    max_length: 10000
    ui:
      list_column: false
      detail_order: 40
      detail_section: "Notes"
      form_order: 40
      form_widget: textarea

  tags:
    type: list[string]
    required: false
    ui:
      list_column: false
      detail_order: 25
      detail_section: "General"
      form_order: 25
      form_widget: tag_input
      filter: true

mixins:
  - lifecycle_mixin
  - provenance_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, slug, description, protocol, ip_addresses, owner]
  boost: 1.5

graph:
  default_label_field: name
  secondary_label_field: service_type
  size_field: null
  size_range: [25, 50]
  group_by: service_type
  tooltip_fields: [name, service_type, status, criticality, owner]

api:
  plural_name: services
  filterable_fields: [name, slug, service_type, status, criticality, protocol, owner, tags]
  sortable_fields: [name, service_type, status, criticality, created_at]
  default_sort: name
  default_sort_order: asc
  max_page_size: 500
  bulk_operations: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

---

### 8.3 Edge Type Definitions

#### 8.3.1 HAS_INTERFACE

```yaml
kind: EdgeType
version: v1
metadata:
  name: HAS_INTERFACE
  display_name: "Has Interface"
  description: "A device has one or more physical or logical network interfaces."
  category: Infrastructure
  tags: [core, inventory]

source:
  node_types: [Device]

target:
  node_types: [Interface]

cardinality: one_to_many
inverse_name: INTERFACE_OF

attributes:
  slot_position:
    type: integer
    required: false
    min_value: 0
    description: "Physical slot or module position if applicable."
    ui:
      detail_visible: true
      detail_section: "Physical"

  port_position:
    type: integer
    required: false
    min_value: 0
    description: "Port position within the slot."
    ui:
      detail_visible: true
      detail_section: "Physical"

constraints:
  unique_target: true
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: target
  max_edges_per_target: 1

graph:
  style: solid
  color: "#94A3B8"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: false

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.3.2 LOCATED_IN

```yaml
kind: EdgeType
version: v1
metadata:
  name: LOCATED_IN
  display_name: "Located In"
  description: "A device is physically located in a specific location (site, building, room, rack)."
  category: Organization
  tags: [location, inventory]

source:
  node_types: [Device]

target:
  node_types: [Location]

cardinality: many_to_one
inverse_name: HOSTS_DEVICE

attributes:
  rack_position:
    type: integer
    required: false
    min_value: 1
    max_value: 48
    description: "Rack unit position (overrides device-level rack_position when this edge targets a Rack location)."
    ui:
      detail_visible: true
      detail_section: "Placement"

  rack_face:
    type: enum
    enum_values: [front, rear]
    required: false
    description: "Which face of the rack the device is mounted on."
    ui:
      detail_visible: true
      detail_section: "Placement"

constraints:
  unique_source: false
  unique_target: false
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1

graph:
  style: dashed
  color: "#F59E0B"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: editor
```

#### 8.3.3 CONNECTED_TO

```yaml
kind: EdgeType
version: v1
metadata:
  name: CONNECTED_TO
  display_name: "Connected To"
  description: >
    A physical cable connection between two interfaces. Represents a Layer 1 link.
    Each interface can be connected to at most one other interface (point-to-point).
  category: Infrastructure
  tags: [cable, physical, link]

source:
  node_types: [Interface]

target:
  node_types: [Interface]

cardinality: one_to_one
inverse_name: CONNECTED_TO

attributes:
  cable_type:
    type: enum
    enum_values:
      - copper_cat5e
      - copper_cat6
      - copper_cat6a
      - fiber_singlemode
      - fiber_multimode_om3
      - fiber_multimode_om4
      - dac
      - aoc
      - serial
      - other
    required: false
    description: "Type of physical cable."
    ui:
      detail_visible: true
      detail_section: "Cable"
      form_widget: select

  cable_length_m:
    type: float
    required: false
    min_value: 0.0
    description: "Cable length in meters."
    ui:
      detail_visible: true
      detail_section: "Cable"

  cable_label:
    type: string
    required: false
    max_length: 100
    description: "Cable label or identifier."
    ui:
      detail_visible: true
      detail_section: "Cable"
      copy_button: true

  cable_color:
    type: string
    required: false
    max_length: 30
    description: "Physical cable color for identification."
    ui:
      detail_visible: true
      detail_section: "Cable"

  status:
    type: enum
    enum_values: [active, planned, decommissioned]
    default: active
    required: true
    description: "Status of this cable connection."
    ui:
      detail_visible: true
      badge_colors:
        active: green
        planned: blue
        decommissioned: red

constraints:
  unique_source: true
  unique_target: true
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1
  max_edges_per_target: 1

graph:
  style: solid
  color: "#10B981"
  width: 2
  show_label: false
  label_field: cable_type
  animate: false
  curve_style: straight

api:
  exposed: true
  filterable_fields: [cable_type, status]
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: editor
```

#### 8.3.4 RUNS_VERSION

```yaml
kind: EdgeType
version: v1
metadata:
  name: RUNS_VERSION
  display_name: "Runs Version"
  description: "A device is running a specific software version."
  category: Software
  tags: [software, version]

source:
  node_types: [Device]

target:
  node_types: [SoftwareVersion]

cardinality: many_to_one
inverse_name: INSTALLED_ON

attributes:
  installed_at:
    type: datetime
    required: false
    description: "When this version was installed on the device."
    ui:
      detail_visible: true
      detail_section: "Installation"

  boot_mode:
    type: enum
    enum_values: [install, bundle, other]
    required: false
    description: "How the software is loaded (install mode vs. bundle mode, etc.)."
    ui:
      detail_visible: true
      detail_section: "Installation"

  verified:
    type: boolean
    required: false
    default: false
    description: "Whether the running version has been verified (e.g., via show version)."
    ui:
      detail_visible: true

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1

graph:
  style: solid
  color: "#06B6D4"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: operator
  default_delete: admin
```

#### 8.3.5 USES_IMAGE

```yaml
kind: EdgeType
version: v1
metadata:
  name: USES_IMAGE
  display_name: "Uses Image"
  description: "A software version is delivered via a specific firmware/software image file."
  category: Software
  tags: [software, image]

source:
  node_types: [SoftwareVersion]

target:
  node_types: [Image]

cardinality: many_to_one
inverse_name: IMAGE_FOR

attributes:
  is_primary:
    type: boolean
    required: false
    default: true
    description: "Whether this is the primary image for the version (vs. a supplementary image like kickstart)."
    ui:
      detail_visible: true

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none

graph:
  style: dotted
  color: "#14B8A6"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: false

permissions:
  default_read: authenticated
  default_write: engineer
  default_delete: admin
```

#### 8.3.6 MANUFACTURED_BY

```yaml
kind: EdgeType
version: v1
metadata:
  name: MANUFACTURED_BY
  display_name: "Manufactured By"
  description: "A hardware model is manufactured by a specific vendor."
  category: Inventory
  tags: [vendor, hardware]

source:
  node_types: [HardwareModel]

target:
  node_types: [Vendor]

cardinality: many_to_one
inverse_name: MANUFACTURES

attributes: {}

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1

graph:
  style: solid
  color: "#8B5CF6"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.3.7 HAS_MODEL

```yaml
kind: EdgeType
version: v1
metadata:
  name: HAS_MODEL
  display_name: "Has Model"
  description: "A device is an instance of a specific hardware model."
  category: Inventory
  tags: [hardware, model]

source:
  node_types: [Device]

target:
  node_types: [HardwareModel]

cardinality: many_to_one
inverse_name: MODEL_OF

attributes: {}

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1

graph:
  style: solid
  color: "#EC4899"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.3.8 RUNS_PLATFORM

```yaml
kind: EdgeType
version: v1
metadata:
  name: RUNS_PLATFORM
  display_name: "Runs Platform"
  description: "A device runs a specific network operating system platform."
  category: Software
  tags: [platform, os]

source:
  node_types: [Device]

target:
  node_types: [Platform]

cardinality: many_to_one
inverse_name: PLATFORM_OF

attributes: {}

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none
  max_edges_per_source: 1

graph:
  style: solid
  color: "#6366F1"
  width: 1
  show_label: false
  curve_style: bezier

api:
  exposed: true
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin
```

#### 8.3.9 DEPENDS_ON

```yaml
kind: EdgeType
version: v1
metadata:
  name: DEPENDS_ON
  display_name: "Depends On"
  description: >
    A service depends on another service. This edge forms the service dependency graph,
    which is used for impact analysis ("if service X goes down, what is affected?")
    and change management.
  category: Services
  tags: [service, dependency, impact]

source:
  node_types: [Service]

target:
  node_types: [Service]

cardinality: many_to_many
inverse_name: DEPENDED_ON_BY

attributes:
  dependency_type:
    type: enum
    enum_values: [hard, soft, optional]
    default: hard
    required: true
    description: >
      - hard: the source service cannot function without the target service.
      - soft: the source service is degraded without the target but can still operate.
      - optional: the source service prefers the target but has fallback mechanisms.
    ui:
      detail_visible: true
      badge_colors:
        hard: red
        soft: orange
        optional: gray

  description:
    type: string
    required: false
    max_length: 500
    description: "Description of the dependency relationship."
    ui:
      detail_visible: true

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none

graph:
  style: dashed
  color: "#F97316"
  width: 2
  show_label: true
  label_field: dependency_type
  animate: false
  curve_style: bezier

api:
  exposed: true
  filterable_fields: [dependency_type]
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: editor
```

#### 8.3.10 HOSTED_ON

```yaml
kind: EdgeType
version: v1
metadata:
  name: HOSTED_ON
  display_name: "Hosted On"
  description: >
    A service is hosted on (runs on / is provided by) one or more devices.
    This is the bridge between the logical service layer and the physical
    infrastructure layer.
  category: Services
  tags: [service, hosting, infrastructure]

source:
  node_types: [Service]

target:
  node_types: [Device]

cardinality: many_to_many
inverse_name: HOSTS_SERVICE

attributes:
  role:
    type: enum
    enum_values: [primary, secondary, standby, anycast, member]
    default: member
    required: true
    description: "Role this device plays in hosting the service."
    ui:
      detail_visible: true
      badge_colors:
        primary: green
        secondary: blue
        standby: yellow
        anycast: purple
        member: gray

  priority:
    type: integer
    required: false
    min_value: 0
    max_value: 1000
    description: "Priority/weight for this device in the service (lower = higher priority)."
    ui:
      detail_visible: true

  health_check_url:
    type: url
    required: false
    description: "URL for health-checking this device's contribution to the service."
    ui:
      detail_visible: true
      link: true

constraints:
  unique_pair: true
  prevent_self_loop: true
  cascading_delete: none

graph:
  style: solid
  color: "#F97316"
  width: 1
  show_label: false
  label_field: role
  curve_style: bezier

api:
  exposed: true
  filterable_fields: [role]
  nested_in_source: true
  nested_in_target: true

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: editor
```
