# NetGraphy Architecture Specification -- Part 1

## 1. Executive Architecture Summary

### 1.1 What NetGraphy Is

NetGraphy is a graph-native network source-of-truth (SoT) platform. It models network infrastructure -- devices, interfaces, circuits, IP addresses, VLANs, sites, tenants, and their relationships -- as a property graph rather than a set of relational tables. Every entity is a node, every relationship is a typed, directed edge with its own properties. The graph is the data model, not a view projected on top of a relational schema.

NetGraphy replaces NetBox and Nautobot for organizations that have outgrown the assumptions baked into relational network SoT platforms: rigid schemas that require migrations for every model change, relationship tables that explode in count as connectivity models grow, and query patterns that degrade into multi-join nightmares when answering real operational questions ("show me every device two hops from this failed link, with their BGP sessions and upstream circuits").

### 1.2 Why Graph-Native Matters for Network SoT

Network infrastructure is inherently a graph. A device connects to interfaces. Interfaces form links. Links traverse circuits. Circuits land at sites. Sites belong to regions. IP addresses bind to interfaces. VLANs span trunk groups. BGP sessions peer across ASNs. Every interesting operational question is a traversal.

Relational SoT platforms encode these relationships as foreign keys and many-to-many join tables. This works until:

- **Schema rigidity becomes a bottleneck.** Adding a new relationship type (e.g., "interface X is a member of LAG Y which spans chassis Z") requires a Django migration, a new serializer, new API endpoints, new UI components. In NetGraphy, it is a new edge type in a YAML file.
- **Query complexity explodes.** "Find all devices connected within 3 hops of device X that share a common VLAN" is a recursive CTE or raw SQL in Django. In Cypher, it is a one-line pattern match.
- **Relationship semantics are second-class.** In relational models, a cable connecting two interfaces is a row in a table. It cannot carry rich metadata without yet another join. In a property graph, the edge itself carries properties: cable type, length, color, installation date, provenance.
- **Path analysis is not natively supported.** Relational databases cannot efficiently answer "what is the shortest L2 path between these two hosts" or "what circuits would be affected if this site loses power." Graph databases do this in constant time per hop.

NetGraphy makes the graph the system of record. There is no impedance mismatch between how network engineers think about their infrastructure and how the platform stores it.

### 1.3 Architectural Differentiators

| Capability | NetBox / Nautobot | NetGraphy |
|---|---|---|
| Data model | Fixed Django ORM models, relational | Schema-defined property graph, user-extensible |
| Schema changes | Django migrations, code deploys | YAML schema push, hot-reload, no downtime |
| Relationships | Foreign keys, generic relations, join tables | First-class typed edges with properties |
| Query language | Django ORM / REST filters / limited GraphQL | Cypher (native), structured query builder, GraphQL |
| Extensibility | Python plugins, custom fields | Schema-as-code, custom node/edge types, parser plugins, job manifests |
| Automation | REST/GraphQL webhooks, limited job framework | Event-driven (NATS), job framework with manifests, Git-synced content |
| GitOps | Nautobot Git repositories (partial) | Full GitOps control plane: schemas, content, parsers, jobs all Git-backed |
| Multi-tenancy | Single-tenant with tenant model | Graph-native RBAC with subgraph isolation |
| Path analysis | Not supported | Native graph traversal, shortest path, impact analysis |

### 1.4 High-Level Component Architecture

```
                                  +-----------------------+
                                  |     React + TS Web    |
                                  |      (apps/web)       |
                                  +-----------+-----------+
                                              |
                                         REST / WS
                                              |
+------------------+          +---------------+---------------+
|   Git Repos      |          |         FastAPI Backend       |
| (schemas, content|  sync    |           (apps/api)          |
|  parsers, jobs)  +--------->+                               |
+------------------+          |  +----------+ +-----------+   |
                              |  | Schema   | | Query     |   |
                              |  | Engine   | | Engine    |   |
                              |  +----------+ +-----------+   |
                              |  +----------+ +-----------+   |
                              |  | Auth/    | | Sync      |   |
                              |  | RBAC     | | Engine    |   |
                              |  +----------+ +-----------+   |
                              +-----+----+--------+-----------+
                                    |    |        |
                          +---------+    |        +-----------+
                          |              |                    |
                   +------+------+  +----+-----+   +---------+---------+
                   |   Neo4j     |  |   NATS   |   |  Celery Workers   |
                   | (graph DB)  |  | JetStream|   |   (apps/worker)   |
                   +-------------+  +----+-----+   +---------+---------+
                                         |                    |
                                    event fan-out        +----+----+
                                         |               |  Redis  |
                                  +------+------+        | (broker)|
                                  | Subscribers |        +---------+
                                  | (webhooks,  |
                                  |  jobs, etc) |        +---------+
                                  +-------------+        |  MinIO  |
                                                         | (objects|
                                                         +---------+
```

**Data flow summary:**

1. The **FastAPI backend** is the single entry point for all API operations. It validates requests against the **Schema Engine**, builds graph queries via the **Query Engine**, and dispatches mutations through the **Graph Repository** layer.
2. **Neo4j** is the primary data store. All network entities and relationships are stored as a labeled property graph. The backend never constructs raw Cypher strings; it uses the query builder and repository pattern from `packages/graph-db` and `packages/query-engine`.
3. **NATS with JetStream** handles all asynchronous event distribution. Every graph mutation emits an event. Subscribers consume these for webhooks, job triggers, cache invalidation, and external integrations. NATS is chosen over RabbitMQ and Redis Streams for reasons detailed in Section 2.5.
4. **Celery with Redis** handles job execution. Jobs are defined as manifests (YAML) and implementations (Python or Go). The worker process (`apps/worker`) pulls from Redis-backed queues and executes jobs in isolated contexts.
5. **MinIO** stores raw artifacts: command outputs, parser results, backup snapshots, file attachments. The API returns pre-signed URLs for direct client access.
6. **Git repositories** are the source of truth for schemas, content data, parser templates, and job definitions. The **Sync Engine** watches configured repos, computes content-addressable diffs, and applies changes to the running system without restarts.
7. The **React frontend** consumes the REST API and a WebSocket connection for real-time updates (fed by NATS). It renders entirely from schema metadata -- the UI for a custom node type is generated from its YAML definition, not from bespoke React components.

---

## 2. Domain Model and Core Design Decisions

### 2.1 Fundamental Domain Concepts

#### Node Types

A node type defines a category of network entity: `Device`, `Interface`, `IPAddress`, `Circuit`, `Site`, `VLAN`, `Prefix`, `BGPSession`, `Tenant`, etc. Each node type is declared in YAML under `schemas/core/` or in a user-provided schema repository. A node type declaration specifies:

- **name**: PascalCase identifier, used as the Neo4j label.
- **namespace**: Scoping mechanism for multi-tenant or plugin-provided types (e.g., `netgraphy.core`, `acme.custom`).
- **attributes**: Typed fields with constraints (see Attributes below).
- **mixins**: References to reusable attribute groups (e.g., `Contactable`, `Locatable`).
- **edges**: Allowed outbound edge types from this node type.
- **display**: Hints for UI rendering (icon, color, summary fields).
- **uniqueness_constraints**: Attribute combinations that form unique identifiers.

Example (abbreviated):

```yaml
# schemas/core/device.yaml
name: Device
namespace: netgraphy.core
mixins:
  - Contactable
  - Taggable
attributes:
  hostname:
    type: string
    required: true
    indexed: true
  platform:
    type: enum
    enum_ref: platforms
  status:
    type: enum
    values: [active, planned, staged, decommissioned]
    default: planned
  serial_number:
    type: string
    unique: true
edges:
  - type: HAS_INTERFACE
    target: Interface
    cardinality: one_to_many
  - type: LOCATED_AT
    target: Site
    cardinality: many_to_one
uniqueness_constraints:
  - [hostname]
```

#### Edge Types

An edge type defines a relationship between two node types. Edges are first-class citizens with their own properties. They are directed, labeled, and carry metadata. An edge type declaration specifies:

- **name**: UPPER_SNAKE_CASE identifier, used as the Neo4j relationship type.
- **source / target**: The node types this edge connects.
- **attributes**: Properties on the relationship itself.
- **cardinality**: `one_to_one`, `one_to_many`, `many_to_one`, `many_to_many`.
- **constraints**: Validation rules (e.g., an interface can only have one `MEMBER_OF_LAG` edge).

Example:

```yaml
# schemas/core/edges/connected_to.yaml
name: CONNECTED_TO
source: Interface
target: Interface
attributes:
  cable_type:
    type: enum
    values: [fiber_smf, fiber_mmf, cat6, cat6a, dac, aoc]
  cable_id:
    type: string
  speed_gbps:
    type: integer
cardinality: one_to_one
symmetric: true  # A connected_to B implies B connected_to A
```

#### Attributes

Attributes are typed, constrained fields on nodes and edges. Supported types:

| Type | Description | Neo4j Storage |
|---|---|---|
| `string` | UTF-8 text | `String` |
| `integer` | 64-bit signed integer | `Long` |
| `float` | IEEE 754 double | `Double` |
| `boolean` | true/false | `Boolean` |
| `datetime` | ISO 8601 timestamp | `DateTime` |
| `enum` | Constrained string from a defined set | `String` (validated at write) |
| `json` | Arbitrary JSON blob | `String` (serialized) |
| `list[T]` | Homogeneous list of a primitive type | Neo4j list |
| `reference` | Soft reference to another node by ID | `String` (UUID) |

Each attribute supports: `required`, `default`, `unique`, `indexed`, `immutable`, `description`, `regex` (for strings), `min`/`max` (for numbers), `max_length` (for strings).

#### Schema Registry

The Schema Registry is the runtime representation of all loaded node types, edge types, mixins, and enum definitions. It is the single authority for "what entities and relationships exist in this system."

Key behaviors:

- **Hot-reload**: Schema changes from Git sync or API push are applied without process restart. The registry is versioned; each schema state has a content-addressable hash.
- **Backward compatibility checks**: The registry rejects changes that would orphan existing data (e.g., removing a required attribute that has values, changing a type incompatibly).
- **Derivation**: The API (OpenAPI spec), GraphQL schema, UI forms, validation rules, search indexes, and Cypher query templates are all derived from the registry. There is no hand-written code per entity type.

The Schema Engine (`packages/schema-engine`) owns loading YAML files, resolving mixin inheritance, validating schema definitions, computing diffs between schema versions, and exposing the registry via an in-process API.

#### Provenance

Every node and edge carries provenance metadata:

- `_created_by`: The actor (user, API token, job, sync process) that created the entity.
- `_created_at`: ISO 8601 creation timestamp.
- `_updated_by`: The actor that last modified the entity.
- `_updated_at`: ISO 8601 last-modification timestamp.
- `_source`: The system of record that asserted this data (`manual`, `sync:git:repo-name`, `job:discovery:run-id`, `import:csv:filename`).
- `_confidence`: Float 0.0--1.0 indicating how trustworthy this data is (manual entry = 1.0, automated discovery = configurable, stale data decays).

Provenance is stored as properties on the Neo4j node/edge. It is not optional. Every write path sets provenance. This is enforced at the repository layer, not by convention.

#### Audit Events

Every mutation (create, update, delete) to the graph emits an audit event. Audit events are:

- Published to NATS on subject `netgraphy.audit.{entity_type}.{action}` (e.g., `netgraphy.audit.device.updated`).
- Persisted to a JetStream stream with configurable retention (default: 90 days).
- Queryable via the API with filters on entity type, actor, time range, and action.

An audit event contains:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-03-28T12:00:00Z",
  "actor": {"type": "user", "id": "uuid", "name": "jmercer"},
  "action": "update",
  "entity_type": "Device",
  "entity_id": "uuid",
  "changes": {
    "status": {"old": "planned", "new": "active"}
  },
  "provenance": {
    "source": "manual",
    "confidence": 1.0
  },
  "request_id": "uuid"
}
```

Audit events are immutable. They are append-only in JetStream and are never modified after emission.

### 2.2 Graph Database: Neo4j Community Edition (Initial), Apache AGE (Future)

**Initial choice: Neo4j Community Edition 5.x**

Rationale:

- Mature property graph database with the most complete Cypher implementation.
- Community Edition is free and sufficient for single-instance deployments (no clustering, which is acceptable for initial release).
- Excellent Python driver (`neo4j` package) with async support, connection pooling, and transaction management.
- Native support for indexes, uniqueness constraints, full-text search, and APOC procedures.
- Well-understood operational characteristics: backup, restore, monitoring, tuning.

Limitations acknowledged:

- Community Edition lacks multi-database, role-based access control at the DB level, and clustering. Multi-tenancy and RBAC are implemented at the application layer.
- Vendor lock-in risk. Neo4j's licensing has shifted over time.

**Future migration path: Apache AGE**

Apache AGE is a PostgreSQL extension that adds openCypher query support to Postgres. The migration path is:

1. All Cypher generation goes through the `packages/query-engine` module, which produces parameterized Cypher strings and parameter maps.
2. All graph I/O goes through the `packages/graph-db` repository layer, which abstracts connection management, transaction boundaries, and result mapping.
3. When Apache AGE reaches production maturity, a new `graph-db` backend is implemented against AGE's `ag_catalog` schema. The query engine requires minor dialect adjustments (AGE's openCypher has some deviations from Neo4j's Cypher).
4. The graph abstraction layer defines a `GraphBackend` protocol (Python `Protocol` class) with methods: `execute_read`, `execute_write`, `begin_transaction`, `create_constraint`, `create_index`. Neo4j and AGE each implement this protocol.

This is not speculative architecture astronautics. The abstraction exists from day one because the query builder and repository pattern are independently justified by testability (the backend can be swapped for an in-memory fake in tests) and by separating query construction from execution.

### 2.3 Backend: Python with FastAPI

**FastAPI** over Django REST Framework (the NetBox/Nautobot choice):

- NetBox and Nautobot are built on Django because they use the Django ORM for their data model. NetGraphy does not use an ORM; the data model lives in Neo4j. Django's primary value proposition (ORM, admin, migrations) is irrelevant here.
- FastAPI provides native async support, which matters for a system that frequently waits on Neo4j queries, NATS publishes, and external API calls.
- Pydantic v2 for request/response validation aligns with the schema-driven architecture. Pydantic models are generated from the Schema Registry at startup and on schema reload.
- Automatic OpenAPI spec generation. The spec is augmented with schema-derived endpoints for each node type.
- Dependency injection for authentication, authorization, database sessions, and schema registry access.

The API layer is intentionally thin. It handles HTTP concerns (routing, serialization, auth, rate limiting) and delegates all business logic to the package layer (`packages/*`). An API endpoint for creating a device:

1. Validates the request body against the Pydantic model generated from the `Device` schema.
2. Calls `SchemaEngine.validate_node(node_type="Device", data=payload)` for cross-field validation.
3. Calls `GraphRepository.create_node(node_type="Device", data=validated, provenance=ctx.provenance)`.
4. The repository constructs Cypher via `QueryEngine`, executes it, and returns the created node.
5. The API publishes an audit event via `EventBus.publish(...)`.
6. Returns the serialized response.

### 2.4 Frontend: React + TypeScript

The frontend is a single-page application built with React and TypeScript. Key architectural decisions:

- **Schema-driven rendering.** The frontend fetches the schema registry from the API at load time and on WebSocket schema-change notifications. List views, detail views, create/edit forms, and search facets are all generated from schema metadata. Adding a new node type requires zero frontend code changes.
- **Graph visualization.** A dedicated graph explorer component renders subgraphs using a force-directed layout (likely `react-force-graph` or `d3-force`). Users can explore the graph visually, expand neighbors, filter by type, and run saved queries.
- **Real-time updates.** A WebSocket connection receives NATS-bridged events for live updates to list views, detail pages, and job status.
- **TypeScript types generated from schema.** A build step generates TypeScript interfaces from the YAML schemas, ensuring compile-time type safety for API interactions.

### 2.5 Eventing: NATS with JetStream

**NATS** is the event backbone. Every graph mutation, job lifecycle event, schema change, and sync operation publishes a message to NATS.

**Why NATS over RabbitMQ:**

- **Operational simplicity.** NATS is a single static binary with zero external dependencies. RabbitMQ requires Erlang, has complex clustering semantics, and demands careful tuning of memory alarms, flow control, and queue mirroring.
- **Cloud-native design.** NATS was built for distributed systems from the start. It supports leaf nodes, gateway connections, and multi-cluster topologies natively. RabbitMQ's federation and shovel plugins are bolt-on complexity.
- **Subject-based routing.** NATS subjects (e.g., `netgraphy.audit.device.created`) provide hierarchical topic routing with wildcard subscriptions (`netgraphy.audit.>`, `netgraphy.audit.device.*`) without exchange/binding configuration. RabbitMQ requires explicit exchange-to-queue bindings.
- **JetStream for persistence.** JetStream provides at-least-once delivery, message replay, consumer groups, and retention policies. This covers the audit log, webhook delivery, and job trigger use cases without a separate durable queue system.
- **Protocol efficiency.** NATS protocol is text-based and trivial to debug. The client libraries for Python (`nats-py`) and Go (`nats.go`) are first-party, well-maintained, and async-native.

**Why NATS over Redis Streams:**

- Redis Streams are a feature of Redis, not a purpose-built messaging system. Using Redis for both job brokering (Celery) and eventing creates a single point of failure and conflates two different operational concerns.
- Redis Streams lack native subject-based routing. Consumer groups exist but topic hierarchies must be hand-rolled with key patterns.
- NATS provides clustering, multi-tenancy (accounts), and security (TLS, NKeys, JWT auth) as first-class features. Redis requires Sentinel or Cluster mode for HA, which adds operational overhead.

### 2.6 Job Queue: Celery with Redis

**Celery** handles long-running and scheduled tasks: device discovery, data collection, parser execution, report generation, schema validation, Git sync, and bulk operations.

**Why Celery with Redis broker (not NATS for job queuing):**

- Celery is the most mature Python distributed task queue. It supports task retry, rate limiting, task chaining, chord/group primitives, scheduled (crontab) tasks, and task result storage.
- NATS JetStream could theoretically serve as a task queue, but Celery's task abstraction (decorators, automatic serialization, result backends, Flower monitoring) provides significantly more out-of-the-box functionality for the job framework.
- Redis as broker is lightweight, fast, and well-tested with Celery. The operational cost of running Redis alongside NATS is minimal compared to the development cost of building a bespoke task queue on NATS.

The job framework (`packages/jobs`) provides:

- **Job manifests** (YAML): Declare a job's name, description, input schema, schedule, timeout, retry policy, and required permissions.
- **Job implementations**: Python functions decorated with `@netgraphy_job` that receive validated inputs and a job context (graph access, event publishing, artifact storage).
- **Go job support**: For performance-critical jobs (bulk parsing, large-scale discovery), Go implementations communicate via gRPC with the worker process. The worker dispatches to Go binaries defined in job manifests.

### 2.7 Object Storage: MinIO

**MinIO** stores binary artifacts that do not belong in the graph or in Git:

- Raw command outputs from device collection.
- Parser results before graph ingestion.
- Export files (CSV, JSON, YAML dumps).
- Backup snapshots.
- User-uploaded attachments.

MinIO is S3-compatible, self-hosted, and operationally simple. In production deployments on cloud infrastructure, it can be swapped for native S3/GCS/Azure Blob via the standard S3 API.

Objects are referenced from graph nodes via a `_artifacts` property containing S3 keys. The API returns pre-signed URLs for direct browser download, avoiding proxying large files through the backend.

### 2.8 Schema-Driven Everything

This is the most important architectural decision in NetGraphy. The YAML schema registry is the single source of truth for the entire system's behavior:

| Concern | How it derives from schema |
|---|---|
| **API endpoints** | Each node type gets CRUD endpoints auto-registered at startup. Request/response Pydantic models are generated from attribute definitions. |
| **API validation** | Field types, required/optional, regex, min/max, enum constraints all come from schema. |
| **Cypher queries** | The query engine generates `CREATE`, `MATCH`, `SET`, `DELETE` patterns from node/edge type definitions. Indexes and constraints are created from schema declarations. |
| **GraphQL schema** | GraphQL types, queries, mutations, and input types are generated from the schema registry. |
| **UI forms** | The frontend renders create/edit forms from schema attribute metadata. Field types, validation, enum dropdowns, relationship pickers all derive from schema. |
| **UI list views** | Column definitions, sort options, and filter facets are derived from indexed/displayed attributes in schema. |
| **Search indexes** | Full-text search indexes are created on attributes marked `indexed: true` or `searchable: true`. |
| **RBAC policies** | Permission scopes are defined per node type and per attribute. Schema changes automatically extend the permission model. |
| **Documentation** | API docs, schema reference, and relationship diagrams are generated from the registry. |

This means adding a new entity type to NetGraphy -- say, `WirelessAccessPoint` -- requires:

1. Write a YAML schema file.
2. Push it to the schema Git repo (or POST it to the API).
3. The system hot-reloads: new API endpoints appear, new UI views render, new Cypher patterns are available, search indexes are created.

No Python code. No database migration. No frontend code. No deployment.

### 2.9 Graph Repository Pattern

All graph database access goes through a repository layer (`packages/graph-db`). This is not a generic ORM. It is a set of typed operations that map domain actions to Cypher queries:

```python
class GraphRepository:
    async def create_node(self, node_type: str, data: dict, provenance: Provenance) -> Node
    async def get_node(self, node_type: str, node_id: UUID) -> Node | None
    async def update_node(self, node_type: str, node_id: UUID, data: dict, provenance: Provenance) -> Node
    async def delete_node(self, node_type: str, node_id: UUID) -> None
    async def create_edge(self, edge_type: str, source_id: UUID, target_id: UUID, data: dict, provenance: Provenance) -> Edge
    async def traverse(self, start_id: UUID, pattern: TraversalPattern) -> list[Path]
    async def query(self, query: StructuredQuery) -> QueryResult
    async def execute_cypher(self, cypher: str, params: dict) -> list[Record]
```

The repository:

- Delegates Cypher generation to `packages/query-engine`. It never constructs Cypher strings directly.
- Manages Neo4j driver sessions and transactions.
- Injects provenance metadata on every write.
- Emits audit events on every mutation.
- Validates data against the Schema Registry before writes.
- Applies RBAC filters to reads (subgraph isolation).

The `execute_cypher` method is an escape hatch for advanced users and saved queries. It is audited and permission-gated.

### 2.10 Content-Addressable Sync for Git-Backed Content

NetGraphy syncs four categories of content from Git repositories:

1. **Schemas** (`schemas/`): Node types, edge types, mixins, enums.
2. **Content data** (`content/`): Reference data (vendor lists, platform catalogs), seed data, saved queries.
3. **Parsers** (`parsers/`): TextFSM templates, command bundles, parse-to-graph mappings.
4. **Jobs** (`jobs/`): Job manifests and implementations.

The Sync Engine (`packages/sync-engine`) implements content-addressable synchronization:

- Each file in a Git repo is identified by its path and its SHA-256 content hash.
- On sync, the engine computes the content manifest (path -> hash) for the current Git HEAD and compares it against the last-synced manifest stored in the database.
- Only changed files are processed. Adds, modifications, and deletions are computed as a diff.
- Schema changes go through the Schema Engine's compatibility checker before application.
- Content data changes are applied as graph upserts (create-or-update by unique key).
- Parser and job changes update the in-memory registries.

The sync process is:

1. `git fetch` + `git diff` against last-synced commit.
2. Compute file-level diff.
3. Validate changed files (schema validation, YAML parsing, template compilation).
4. Apply changes in a transaction (all-or-nothing for schemas; per-file for content).
5. Update the sync state record with the new commit SHA and content manifest.
6. Publish sync events to NATS.

Sync can be triggered by: Git webhook, manual API call, polling schedule, or NATS event.

---

## 3. Monorepo Layout

### 3.1 Why a Monorepo

NetGraphy uses a single repository for all components. The justification is specific and practical:

- **Shared types.** The schema engine defines types (node type definitions, attribute descriptors, validation rules) consumed by the API, worker, query engine, frontend type generator, and SDK. In a polyrepo, these shared types require a published package with versioning, release coordination, and compatibility matrices. In a monorepo, they are imported directly. A change to a schema type definition is immediately visible to all consumers, and CI catches breakage atomically.
- **Atomic cross-cutting changes.** Adding a new feature often touches schemas, the API, the frontend, and tests simultaneously. A monorepo ensures these changes land in a single commit, are reviewed together, and are tested together. In a polyrepo, this is a coordinated multi-repo PR with ordering dependencies.
- **Single CI pipeline.** One pipeline builds, tests, and deploys all components. Integration tests that exercise the API against Neo4j, the worker against NATS, and the frontend against the API run in a single CI job. There is no "works in repo A's CI but breaks repo B" problem.
- **Easier onboarding.** A new contributor clones one repo, runs `docker compose up`, and has the entire system running. No hunting across repositories for the right versions of dependent services.
- **Consistent tooling.** Linting, formatting, type checking, and dependency management are configured once. A single `pyproject.toml` (or workspace-level config) governs Python packages. A single `package.json` workspace governs frontend packages.

The monorepo uses **Python namespace packages** for `packages/*` and **npm workspaces** for frontend packages. Each subdirectory under `packages/` is an installable Python package with its own `pyproject.toml`, but they are installed in editable mode (`pip install -e`) from the workspace root.

### 3.2 Directory Reference

```
netgraphy/
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
├── packages/
│   ├── schema-engine/
│   ├── graph-db/
│   ├── query-engine/
│   ├── sync-engine/
│   ├── ingestion/
│   ├── jobs/
│   ├── auth/
│   ├── events/
│   └── sdk/
├── schemas/
│   ├── core/
│   ├── examples/
│   └── mixins/
├── content/
│   ├── helpers/
│   ├── queries/
│   └── seed/
├── parsers/
│   ├── templates/
│   ├── commands/
│   ├── mappings/
│   └── fixtures/
├── jobs/
│   ├── python/
│   └── go/
├── infra/
│   ├── docker/
│   ├── compose/
│   ├── k8s/
│   └── ci/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
└── docs/
    ├── architecture/
    ├── api/
    ├── schema-spec/
    └── user-guide/
```

#### `apps/` -- Deployable Applications

These are the runnable processes. Each has a `Dockerfile`, an entrypoint, and configuration loading. They are thin orchestration layers that wire together packages.

**`apps/api/`** -- FastAPI Backend

The HTTP API server. Contains:

- `main.py`: FastAPI application factory. Initializes the schema registry, graph connection pool, NATS client, and middleware stack.
- `routes/`: Route modules organized by domain (nodes, edges, schemas, jobs, auth, search). Routes are largely auto-generated from the schema registry; hand-written routes exist for auth flows, bulk operations, and system endpoints.
- `middleware/`: Request ID injection, authentication, rate limiting, CORS, request logging.
- `dependencies/`: FastAPI dependency injection providers for database sessions, current user, schema registry, event bus.
- `config.py`: Pydantic settings loaded from environment variables.

**`apps/web/`** -- React Frontend

The single-page application. Contains:

- Standard React + TypeScript + Vite project structure.
- `src/schema/`: Schema-driven component generators. Given a node type definition, produces list views, detail views, forms, and filter panels.
- `src/graph/`: Graph visualization components (explorer, topology view, path viewer).
- `src/api/`: Generated API client (from OpenAPI spec) and WebSocket event handler.
- `src/types/`: TypeScript interfaces generated from YAML schemas at build time.

**`apps/worker/`** -- Celery Worker Process

The background task executor. Contains:

- `main.py`: Celery application factory. Configures broker (Redis), result backend, task discovery, and concurrency.
- `tasks/`: Task registration that auto-discovers job implementations from `packages/jobs` and `jobs/python/`.
- Connects to Neo4j, NATS, and MinIO independently from the API process.

#### `packages/` -- Shared Libraries

These are internal Python packages. Each is independently importable and testable but not published to PyPI. They contain the core business logic.

**`packages/schema-engine/`** -- Schema Loader, Validator, Registry

Responsibilities:

- Parse YAML schema files into a typed internal representation (`NodeTypeDefinition`, `EdgeTypeDefinition`, `MixinDefinition`, `EnumDefinition`).
- Resolve mixin inheritance (a node type that includes `Taggable` gets `tags: list[string]` merged into its attributes).
- Validate schema definitions: type correctness, referential integrity (edge targets exist), constraint validity, naming conventions.
- Compute diffs between schema versions for hot-reload and compatibility checking.
- Expose the `SchemaRegistry` object: an in-memory, thread-safe, versioned snapshot of all loaded types.
- Generate Pydantic models, GraphQL types, and OpenAPI schema fragments from the registry.

**`packages/graph-db/`** -- Neo4j Abstraction and Repository Pattern

Responsibilities:

- Manage the Neo4j driver instance (connection pool, retry logic, health checks).
- Implement the `GraphBackend` protocol that abstracts read/write operations.
- Implement the `GraphRepository` class with typed CRUD, traversal, and query methods.
- Handle transaction management (read vs. write transactions, explicit transactions for multi-step operations).
- Inject provenance metadata on writes.
- Apply RBAC subgraph filters on reads.
- Map Neo4j `Record` objects to domain types (`Node`, `Edge`, `Path`, `QueryResult`).

**`packages/query-engine/`** -- Cypher Generation and Structured Query Builder

Responsibilities:

- Provide a Python DSL for constructing Cypher queries without string interpolation.
- Generate `CREATE`, `MERGE`, `MATCH`, `SET`, `DELETE`, `RETURN` clauses from typed inputs.
- Build parameterized queries (never inline values into Cypher strings).
- Support structured queries: filtering, sorting, pagination, field selection, relationship traversal depth.
- Generate `CREATE CONSTRAINT` and `CREATE INDEX` statements from schema definitions.
- Validate query structure against the schema registry (cannot filter on a non-existent attribute).

Example usage:

```python
query = (
    QueryBuilder()
    .match(node_type="Device", alias="d")
    .where("d.status", "=", "active")
    .with_related("d", edge_type="HAS_INTERFACE", alias="i", direction="out")
    .where("i.speed_gbps", ">=", 100)
    .return_fields("d.hostname", "i.name", "i.speed_gbps")
    .order_by("d.hostname")
    .limit(50)
    .build()
)
# Produces parameterized Cypher:
# MATCH (d:Device) WHERE d.status = $p0
# MATCH (d)-[:HAS_INTERFACE]->(i:Interface) WHERE i.speed_gbps >= $p1
# RETURN d.hostname, i.name, i.speed_gbps ORDER BY d.hostname LIMIT 50
# params: {"p0": "active", "p1": 100}
```

**`packages/sync-engine/`** -- Git Sync and Content Management

Responsibilities:

- Clone and fetch configured Git repositories.
- Compute content-addressable manifests (path -> SHA-256 hash).
- Diff current HEAD against last-synced state.
- Dispatch changed files to the appropriate handler (schema engine, content loader, parser registry, job registry).
- Manage sync state persistence (last commit SHA, manifest, sync timestamp, status).
- Handle webhook payloads from GitHub/GitLab/Gitea.
- Support branch selection, path filtering, and authentication (SSH keys, tokens).

**`packages/ingestion/`** -- Parser Registry, Mapping Engine, Collection

Responsibilities:

- Load and register TextFSM templates and command bundle definitions.
- Execute command bundles against devices (via Netmiko/NAPALM/Scrapli, abstracted behind a connection interface).
- Parse raw command output through TextFSM templates into structured data.
- Apply parse-to-graph mappings: transform structured parser output into node/edge create/update operations.
- Manage the parser lifecycle: template validation, version tracking, test fixture execution.

**`packages/jobs/`** -- Job Framework, Manifests, Execution

Responsibilities:

- Load job manifests (YAML) that declare job metadata, input schemas, schedules, and resource requirements.
- Provide the `@netgraphy_job` decorator for Python job implementations.
- Provide a `JobContext` object giving jobs access to the graph repository, event bus, artifact storage, and logger.
- Handle job lifecycle: queued, running, succeeded, failed, retrying.
- Dispatch Go jobs to compiled binaries via subprocess with structured I/O (JSON over stdin/stdout).
- Manage job schedules via Celery Beat.

**`packages/auth/`** -- RBAC, SSO, Permissions

Responsibilities:

- Authenticate requests via JWT tokens (issued by the API's auth endpoints).
- Support SSO providers via OIDC (Okta, Azure AD, Keycloak).
- Implement RBAC with roles, permissions, and scopes.
- Scopes are defined per node type (e.g., `device:read`, `device:write`, `device:delete`) and auto-generated from the schema registry.
- Subgraph isolation: tenants can only see/modify nodes and edges within their permission boundary.
- API token management with scoping and expiration.

**`packages/events/`** -- Event Bus and NATS Integration

Responsibilities:

- Abstract NATS connection management (connect, reconnect, drain, close).
- Provide typed event publishing: `EventBus.publish(subject, event)` with serialization.
- Provide typed subscriptions: `EventBus.subscribe(subject_pattern, handler)` with deserialization.
- Manage JetStream streams and consumers for durable event processing.
- Bridge NATS events to WebSocket connections for the frontend.
- Handle dead letter subjects for failed event processing.

**`packages/sdk/`** -- Shared Types, Utilities, Client SDK

Responsibilities:

- Define shared domain types used across all packages: `Node`, `Edge`, `Path`, `QueryResult`, `Provenance`, `AuditEvent`, `SchemaDefinition`, etc.
- Provide utility functions: ID generation (UUIDs), timestamp formatting, slug generation, diff computation.
- Provide a Python client SDK for external consumers of the NetGraphy API (used in job implementations, external integrations, and testing).

#### `schemas/` -- Schema Definitions

This directory contains the YAML files that define the data model. It is both part of the repository and a reference implementation of what a user's schema repository looks like.

**`schemas/core/`** -- Built-in Node and Edge Definitions

The core network SoT schema: `Device`, `Interface`, `IPAddress`, `Prefix`, `VLAN`, `VRF`, `Circuit`, `Site`, `Region`, `Tenant`, `Rack`, `RackUnit`, `Platform`, `Manufacturer`, `BGPSession`, `ASN`, `RouteTarget`, `L2VPN`, `WirelessNetwork`, etc. Also contains edge types: `HAS_INTERFACE`, `CONNECTED_TO`, `ASSIGNED_TO`, `LOCATED_AT`, `MEMBER_OF`, `PEERS_WITH`, etc.

These are the schemas that ship with NetGraphy and provide feature parity with NetBox's core models, expressed as graph types.

**`schemas/examples/`** -- Example Custom Schemas

Demonstrates how users extend the model: custom device roles, service catalog nodes, overlay network types, compliance check types. These are not loaded by default; they serve as documentation and starting points.

**`schemas/mixins/`** -- Reusable Attribute Groups

Mixins are attribute bundles that can be included in multiple node types:

- `Taggable`: `tags: list[string]`
- `Contactable`: `contact_name: string`, `contact_email: string`, `contact_phone: string`
- `Locatable`: `latitude: float`, `longitude: float`, `address: string`
- `Timestamped`: `_created_at: datetime`, `_updated_at: datetime` (this one is automatically applied to all types)

#### `content/` -- Reference Data and Seed Content

**`content/helpers/`** -- Reference Data

Static reference data that populates enum-like choices and lookup tables: vendor names and their platforms, interface type catalogs, cable type specifications, standard community strings, well-known ASNs. Stored as YAML files, synced to the graph as reference nodes.

**`content/queries/`** -- Saved Cypher Queries

Curated Cypher queries for common operational questions: "devices with no management IP," "interfaces with speed mismatch across a link," "circuits with single points of failure." These are loadable from the UI query explorer.

**`content/seed/`** -- Development Seed Data

Sample data for development and demonstration: a fictional multi-site network with devices, links, IPs, and circuits. Loaded by `docker compose` for local development.

#### `parsers/` -- Network Device Parsers

**`parsers/templates/`** -- TextFSM Templates

TextFSM templates organized by platform and command: `cisco_ios/show_interfaces.textfsm`, `arista_eos/show_bgp_summary.textfsm`, etc. These parse raw CLI output into structured tabular data. Community templates (NTC Templates) can be vendored or referenced.

**`parsers/commands/`** -- Command Bundle Definitions

YAML files defining command bundles: groups of CLI commands to execute on a device, the platform they apply to, and which TextFSM template parses each command's output.

```yaml
# parsers/commands/cisco_ios_discovery.yaml
name: cisco_ios_discovery
platform: cisco_ios
commands:
  - command: "show interfaces"
    template: cisco_ios/show_interfaces.textfsm
    mapping: interface_to_graph
  - command: "show ip bgp summary"
    template: cisco_ios/show_bgp_summary.textfsm
    mapping: bgp_session_to_graph
```

**`parsers/mappings/`** -- Parse-to-Graph Mapping Definitions

YAML files that define how parsed tabular data maps to graph operations. A mapping specifies which columns become node attributes, how to derive edge relationships, and how to handle upsert logic.

**`parsers/fixtures/`** -- Test Fixtures for Parsers

Raw command output samples and expected parsed results for each template. Used in CI to verify that templates produce correct output. Each fixture is a pair: `show_interfaces.raw` and `show_interfaces.expected.json`.

#### `jobs/` -- Job Implementations

**`jobs/python/`** -- Python Job Implementations

Python modules containing job functions decorated with `@netgraphy_job`. Each file typically implements one job. Examples: `discovery.py` (device discovery via SNMP/CLI), `compliance_check.py` (validate device config against policy), `topology_sync.py` (reconcile topology from collected data).

**`jobs/go/`** -- Go Job Implementations

Go modules for performance-critical jobs. Each is a standalone Go binary that reads job input from stdin (JSON), performs work, writes results to stdout (JSON), and exits. The worker process invokes these as subprocesses. Examples: bulk ICMP reachability checks, large-scale SNMP polling, config diff computation.

#### `infra/` -- Infrastructure Configuration

**`infra/docker/`** -- Dockerfiles

Dockerfiles for each deployable component: `api.Dockerfile`, `web.Dockerfile`, `worker.Dockerfile`. Multi-stage builds with dependency caching.

**`infra/compose/`** -- Docker Compose Files

- `compose.yaml`: Full development stack (API, web, worker, Neo4j, NATS, Redis, MinIO).
- `compose.deps.yaml`: Dependencies only (Neo4j, NATS, Redis, MinIO) for running apps locally outside containers.
- `compose.test.yaml`: Test dependencies (ephemeral Neo4j, NATS, Redis instances with fixed ports).

**`infra/k8s/`** -- Kubernetes Manifests

Kustomize base and overlays for deploying to Kubernetes. Includes: Deployments, Services, ConfigMaps, Secrets, Ingress, PersistentVolumeClaims, and HorizontalPodAutoscalers for each component.

**`infra/ci/`** -- CI/CD Pipeline Definitions

GitHub Actions workflows (or GitLab CI, depending on hosting choice): lint, type-check, unit test, integration test, build containers, push to registry, deploy to staging. A single pipeline that builds and tests the entire monorepo, with path-based job filtering to skip unchanged components.

#### `tests/` -- Test Suites

**`tests/unit/`** -- Unit Tests

Tests for individual packages in isolation. The graph-db package is tested with a fake in-memory backend. The schema engine is tested with fixture YAML files. The query engine is tested by asserting generated Cypher strings and parameters.

**`tests/integration/`** -- Integration Tests

Tests that exercise real external dependencies. The API is tested against a real Neo4j instance and NATS server (started by `compose.test.yaml`). The sync engine is tested against a real Git repository (created in a temp directory). The ingestion pipeline is tested end-to-end: raw output in, graph nodes out.

**`tests/e2e/`** -- End-to-End Tests

Full-stack tests that exercise the system from HTTP request to graph state. Use the API client from `packages/sdk` to perform operations and verify results. Cover critical user workflows: create device, add interfaces, connect devices, run discovery job, verify topology.

**`tests/fixtures/`** -- Shared Test Fixtures

Reusable test data: sample schema files, device data, command outputs, expected graph states. Shared across unit, integration, and e2e tests.

#### `docs/` -- Documentation

**`docs/architecture/`** -- Architecture specifications (this document and its sequels).

**`docs/api/`** -- API documentation supplements. The primary API docs are auto-generated from OpenAPI, but this directory holds conceptual guides, authentication documentation, and advanced usage patterns.

**`docs/schema-spec/`** -- The schema language specification. Defines the complete YAML schema format, supported types, constraints, inheritance rules, and compatibility guarantees.

**`docs/user-guide/`** -- End-user documentation: installation, configuration, first-steps tutorials, operational guides.
