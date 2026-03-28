# NetGraphy Architecture Specification -- Part 6

## 14. API Design

### 14.1 REST API Structure

All API endpoints are served under the base URL `/api/v1`. Routes are versioned so that breaking changes can be introduced under `/api/v2` without disrupting existing integrations. The API is implemented in FastAPI, which provides automatic request validation via Pydantic, async request handling, and OpenAPI schema generation.

Every route group below maps to a dedicated FastAPI router module under `apps/api/routers/`.

---

#### 14.1.1 Schema Discovery

Schema discovery endpoints expose the full schema registry to API consumers and the frontend. These are the foundation for dynamic UI rendering -- the web app calls these at startup to know what node types exist, what attributes they carry, and how to render forms and tables.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/schema/node-types` | List all node type definitions. Returns name, label, category, icon, and summary metadata for each type. Supports `?category=infrastructure` filtering. |
| `GET` | `/schema/node-types/{name}` | Get a single node type definition with full metadata: all attributes (with types, constraints, UI hints), edge definitions, display configuration, and schema version. |
| `GET` | `/schema/edge-types` | List all edge type definitions. Returns name, label, source/target type constraints, and cardinality. |
| `GET` | `/schema/edge-types/{name}` | Get a single edge type definition with full attribute schema and constraints. |
| `GET` | `/schema/ui-metadata` | Full UI metadata bundle for dynamic rendering. Returns all node types, edge types, navigation categories, icons, color mappings, and form layout hints in a single payload. The frontend caches this and invalidates on `schema.changed` events. |
| `POST` | `/schema/validate` | Validate a proposed schema change without applying it. Accepts a YAML or JSON schema document. Returns validation result with errors, warnings, and a migration plan preview. Used by the Git sync preview flow and the schema editor. |
| `POST` | `/schema/migrate` | Apply a schema migration. Requires `schema:admin` permission. Accepts a validated migration plan (output of `/schema/validate`). Applies changes to Neo4j (constraints, indexes) and updates the schema registry. Emits `schema.migrated` event. |

---

#### 14.1.2 Node CRUD (Dynamic Routes)

Node routes are registered dynamically at API startup. The schema registry is loaded, and for each node type, a set of CRUD routes is registered under `/objects/{node_type}`. The `{node_type}` path parameter is the schema-defined node type name in snake_case (e.g., `device`, `interface`, `ip_address`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/objects/{node_type}` | List nodes of the given type. Supports filtering, pagination, sorting, field selection, and relationship inclusion (see Section 14.3). Returns paginated results with metadata. |
| `POST` | `/objects/{node_type}` | Create a new node. Request body is validated against the Pydantic model generated from the schema definition. Returns the created node with its generated `id`. Emits `data.created.{node_type}` event. |
| `GET` | `/objects/{node_type}/{id}` | Get a single node by ID. Supports `?include=interfaces,location` to embed related nodes. Supports `?fields=hostname,status` to select specific attributes. |
| `PATCH` | `/objects/{node_type}/{id}` | Partial update of a node. Only fields present in the request body are updated. Validates against schema constraints. Emits `data.updated.{node_type}` event. Returns the updated node. |
| `DELETE` | `/objects/{node_type}/{id}` | Delete a node. By default, also deletes all edges connected to this node (cascade). Supports `?cascade=false` to fail if edges exist. Emits `data.deleted.{node_type}` event. |

---

#### 14.1.3 Edge CRUD

Edges are managed both through the node relationship sub-resource (for reading) and through dedicated edge routes (for writing). This separation keeps the read path intuitive (fetch a device's interfaces) while keeping the write path explicit (create an edge with typed source/target).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/objects/{node_type}/{id}/relationships` | List all relationships for a node, grouped by edge type. Returns edge type name, direction (inbound/outbound), count, and the first page of related nodes for each type. |
| `GET` | `/objects/{node_type}/{id}/relationships/{edge_type}` | List relationships of a specific edge type for a node. Returns the related nodes with edge properties. Supports pagination and filtering on edge attributes. |
| `POST` | `/edges/{edge_type}` | Create a new edge. Request body must include `source_id`, `source_type`, `target_id`, `target_type`, and any edge attributes. Validates that source/target types match the edge type definition. Emits `data.created.{edge_type}` event. |
| `PATCH` | `/edges/{edge_type}/{id}` | Update edge attributes. The edge's source and target are immutable -- to change endpoints, delete and recreate. Emits `data.updated.{edge_type}` event. |
| `DELETE` | `/edges/{edge_type}/{id}` | Delete an edge. Emits `data.deleted.{edge_type}` event. |

---

#### 14.1.4 Query

The query API provides three ways to interrogate the graph: raw Cypher for power users, structured queries for the visual builder, and saved queries for reuse.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query/cypher` | Execute a Cypher query. RBAC-gated: the query is parsed and checked against the user's type-level permissions before execution. Supports `?timeout=30` to cap execution time. Read-only by default; write queries require `query:write` permission. Returns results as rows with column metadata. |
| `POST` | `/query/structured` | Execute a structured query built from the visual query builder. The request body is a JSON representation of the query graph pattern (nodes, edges, filters, projections). The backend translates this to Cypher via CypherBuilder and executes it. This endpoint never allows write operations. |
| `GET` | `/query/saved` | List saved queries. Supports `?tags=bgp,troubleshooting` and `?shared=true` filtering. Returns query metadata without the full query body. |
| `POST` | `/query/saved` | Save a query. Accepts name, description, query (Cypher or structured), parameter definitions, and tags. Queries can be marked as `shared: true` to be visible to other users. |
| `GET` | `/query/saved/{id}` | Get a saved query with its full definition, including parameter schema. |
| `DELETE` | `/query/saved/{id}` | Delete a saved query. Only the owner or a user with `query:admin` permission can delete. |
| `POST` | `/query/saved/{id}/execute` | Execute a saved query with parameter values. Parameters are validated against the saved parameter schema. Returns results in the same format as `/query/cypher`. |

---

#### 14.1.5 Parsers

Parser management endpoints cover TextFSM templates, command bundles (which commands to run on which platforms), and mappings (how parsed output becomes graph mutations).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/parsers` | List parser templates. Supports `?platform=cisco_ios&command=show+interfaces` filtering. Returns template metadata: platform, command, version, record count from last test. |
| `POST` | `/parsers` | Register a new parser template. Accepts the TextFSM template content, platform, command, and optional test fixtures. Validates template syntax on submission. |
| `GET` | `/parsers/{id}` | Get parser detail including template content, associated command bundle, mapping, and test history. |
| `POST` | `/parsers/{id}/test` | Test a parser against raw input text. Accepts `raw_output` in the request body. Returns parsed records as structured JSON. Does not persist anything -- purely a dry run. |
| `GET` | `/command-bundles` | List command bundles. A command bundle defines a set of commands to execute on a device platform (e.g., `cisco_ios_facts: [show version, show inventory, show interfaces]`). |
| `POST` | `/command-bundles` | Register a new command bundle. |
| `GET` | `/mappings` | List mapping definitions. A mapping defines how parsed records from a specific parser are translated into graph mutations (node upserts, edge creates, attribute updates). |
| `POST` | `/mappings` | Register a new mapping definition. Validates that referenced node/edge types exist in the schema. |

---

#### 14.1.6 Ingestion

Ingestion runs are the execution unit for the collect-parse-map-upsert pipeline.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingestion/run` | Trigger an ingestion run. Accepts a target selector (Cypher query or explicit device list), a command bundle reference, and optional parameters. Returns the run ID immediately; the run executes asynchronously via the job framework. |
| `GET` | `/ingestion/runs` | List ingestion runs. Supports `?status=completed&since=2026-03-01` filtering. Returns run metadata: status, device count, records parsed, mutations applied, duration. |
| `GET` | `/ingestion/runs/{id}` | Get detailed run results. Includes per-device breakdown: raw output reference (MinIO path), parsed record count, mutations applied (with before/after for updates), and any errors. |

---

#### 14.1.7 Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/jobs` | List job definitions loaded from manifests. Returns name, description, platform (Python/Go), schedule, last execution status. |
| `GET` | `/jobs/{name}` | Get job definition detail. Returns full manifest including parameter schema, target selector, platform, timeout, and resource requirements. |
| `POST` | `/jobs/{name}/execute` | Trigger a job execution. Accepts parameter values (validated against manifest schema) and optional target override. Returns execution ID. The job runs asynchronously via Celery (Python) or the Go worker. |
| `GET` | `/jobs/{name}/executions` | List executions for a job. Supports `?status=failed&since=2026-03-01` filtering. |
| `GET` | `/jobs/{name}/executions/{id}` | Get execution detail: status, start/end times, duration, parameters used, target list, result summary, artifact references. |
| `GET` | `/jobs/{name}/executions/{id}/logs` | Stream execution logs. Supports `Accept: text/event-stream` for SSE streaming while the job is running. Falls back to full log download for completed jobs. Logs are stored in MinIO and indexed by execution ID. |

---

#### 14.1.8 Git Sources

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/git-sources` | List registered Git sources. Returns repo URL, branch, content domains (schemas, parsers, jobs, etc.), sync status, last sync timestamp. |
| `POST` | `/git-sources` | Register a new Git source. Accepts repo URL, branch, authentication (SSH key reference or token), content domain mapping (which directories map to which content types), and sync schedule. Triggers an initial sync on creation. |
| `GET` | `/git-sources/{id}` | Get source detail including full configuration and sync statistics. |
| `POST` | `/git-sources/{id}/sync` | Trigger an immediate sync. Pulls latest from the remote, diffs against the current state, validates changes, and applies them. Returns a sync result summary. Emits `sync.{source_name}.completed` or `sync.{source_name}.failed` event. |
| `GET` | `/git-sources/{id}/sync-history` | List sync events for this source. Each event records: commit SHA, files changed, content types affected, validation results, apply results, duration. |
| `GET` | `/git-sources/{id}/preview` | Preview pending changes without applying. Fetches the remote, computes the diff, validates proposed changes, and returns a structured preview: files changed, schema migrations needed, parser updates, job manifest changes. No side effects. |

---

#### 14.1.9 Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/login` | Authenticate. For local auth, accepts username/password and returns a JWT. For OIDC, returns a redirect URL to the identity provider. The JWT contains the user ID, roles, and token expiry. |
| `POST` | `/auth/token` | Get or refresh an API token. Accepts a valid JWT or refresh token. Returns a new access token and refresh token pair. API tokens can also be long-lived (for automation), created with explicit scopes and expiry. |
| `GET` | `/auth/me` | Get the current user's profile: username, display name, email, roles, permissions, and preferences. Used by the frontend to initialize the session. |
| `GET` | `/rbac/roles` | List all RBAC roles with their permission sets. Requires `rbac:read` permission. |
| `GET` | `/rbac/permissions` | List all available permissions. Permissions are structured as `{resource}:{action}` (e.g., `device:create`, `schema:admin`, `query:write`). |

---

#### 14.1.10 Audit

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/audit/events` | List audit events. Supports rich filtering: `?action=update&resource_type=device&user=jmercer&since=2026-03-01&until=2026-03-28`. Returns events with actor, action, resource, timestamp, and change summary. Paginated, sorted by timestamp descending. |
| `GET` | `/audit/events/{id}` | Get full audit event detail including the complete before/after diff of the affected resource, the request metadata (IP, user agent, API token ID), and correlation ID for tracing related events. |

---

### 14.2 API Response Format

All successful responses follow a consistent envelope format. Single-resource responses wrap the resource in `data`. Collection responses include pagination metadata in `meta`.

**Single resource response:**

```json
{
  "data": {
    "id": "d7f3a1b2-4c5e-6f7a-8b9c-0d1e2f3a4b5c",
    "type": "device",
    "attributes": {
      "hostname": "core-rtr-01.sea",
      "status": "active",
      "management_ip": "10.0.1.1",
      "platform": "cisco_iosxe",
      "role": "core_router"
    },
    "relationships": {
      "location": {
        "data": {"id": "loc-001", "type": "location"},
        "links": {"related": "/api/v1/objects/location/loc-001"}
      }
    },
    "meta": {
      "created_at": "2026-01-15T10:30:00Z",
      "updated_at": "2026-03-20T14:22:00Z",
      "created_by": "jmercer",
      "provenance": "manual"
    }
  }
}
```

**Collection response:**

```json
{
  "data": [
    {"id": "...", "type": "device", "attributes": {"hostname": "core-rtr-01.sea", "...": "..."}},
    {"id": "...", "type": "device", "attributes": {"hostname": "core-rtr-02.sea", "...": "..."}}
  ],
  "meta": {
    "total_count": 150,
    "page": 1,
    "page_size": 25,
    "next": "/api/v1/objects/device?page=2",
    "previous": null
  }
}
```

**Error response:**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Hostname is required",
    "details": [
      {"field": "hostname", "message": "This field is required"},
      {"field": "management_ip", "message": "Invalid IPv4 address format"}
    ],
    "correlation_id": "abc-123-def-456"
  }
}
```

Error codes are machine-readable constants. The full error code vocabulary:

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `VALIDATION_ERROR` | 422 | Request body failed schema validation. `details` contains per-field errors. |
| `NOT_FOUND` | 404 | The requested resource does not exist. |
| `CONFLICT` | 409 | A resource with the same unique key already exists (e.g., duplicate hostname). |
| `UNAUTHORIZED` | 401 | No valid authentication token provided. |
| `FORBIDDEN` | 403 | Authenticated but lacking the required permission. |
| `QUERY_TIMEOUT` | 408 | Cypher query exceeded the configured timeout. |
| `QUERY_ERROR` | 400 | Cypher syntax error or invalid structured query. |
| `SCHEMA_ERROR` | 400 | Schema validation failed (for `/schema/validate` and `/schema/migrate`). |
| `DEPENDENCY_ERROR` | 409 | Cannot delete because dependent edges exist (when `cascade=false`). |
| `INTERNAL_ERROR` | 500 | Unexpected server error. `correlation_id` maps to structured logs. |

---

### 14.3 Filtering and Pagination

All collection endpoints support a consistent filtering, pagination, and sorting interface. This is implemented as a shared dependency in FastAPI that parses query parameters and translates them into Cypher `WHERE` clauses via CypherBuilder.

**Filtering:**

Filters use the `{field}__{operator}` syntax on query parameters. If no operator is specified, exact match is assumed.

```
GET /api/v1/objects/device?hostname__contains=core&status=active&role__in=router,switch
```

Supported operators:

| Operator | Example | Cypher Translation |
|----------|---------|-------------------|
| (none) / `exact` | `?status=active` | `n.status = 'active'` |
| `contains` | `?hostname__contains=core` | `n.hostname CONTAINS 'core'` |
| `startswith` | `?hostname__startswith=core-rtr` | `n.hostname STARTS WITH 'core-rtr'` |
| `endswith` | `?hostname__endswith=.sea` | `n.hostname ENDS WITH '.sea'` |
| `in` | `?role__in=router,switch` | `n.role IN ['router', 'switch']` |
| `gt` / `gte` | `?uplinks__gt=2` | `n.uplinks > 2` |
| `lt` / `lte` | `?created_at__lt=2026-03-01` | `n.created_at < datetime('2026-03-01')` |
| `isnull` | `?decommissioned_at__isnull=true` | `n.decommissioned_at IS NULL` |
| `regex` | `?hostname__regex=^core-rtr-\d+` | `n.hostname =~ '^core-rtr-\\d+'` |

**Pagination:**

Cursor-based pagination is the default for large collections. Offset-based pagination is also supported for simpler use cases.

```
GET /api/v1/objects/device?page=1&page_size=25
```

- `page`: 1-indexed page number. Default: 1.
- `page_size`: Items per page. Default: 25. Maximum: 200.
- The response `meta` block includes `total_count`, `next`, and `previous` links.

**Sorting:**

```
GET /api/v1/objects/device?sort=hostname
GET /api/v1/objects/device?sort=-created_at
GET /api/v1/objects/device?sort=status,-hostname
```

- Prefix with `-` for descending order.
- Multiple sort fields are comma-separated and applied in order.
- Default sort is `-updated_at` (most recently modified first).

**Field selection:**

```
GET /api/v1/objects/device?fields=hostname,management_ip,status
```

- Reduces the response payload to only the requested attributes.
- `id` and `type` are always included regardless of field selection.
- Reduces Cypher `RETURN` clause to only the requested properties, improving query performance.

**Relationship inclusion:**

```
GET /api/v1/objects/device/d7f3a1b2?include=interfaces,location
```

- Embeds related nodes inline in the response under `relationships.{edge_type}.data`.
- Without `include`, relationships contain only the reference (`id`, `type`, and `links`).
- Supports one level of depth. Nested includes (e.g., `include=interfaces.ip_addresses`) are supported with dot notation but capped at 2 levels to prevent query explosion.

---

### 14.4 OpenAPI Generation

FastAPI auto-generates an OpenAPI 3.1 specification from the route definitions and Pydantic models. NetGraphy extends this with schema-driven dynamic route registration.

**Startup flow:**

1. The API application starts and loads the schema registry from Neo4j (or from YAML files on first boot).
2. For each node type in the registry, the dynamic route factory generates:
   - A Pydantic model for create requests (all required fields are required, optional fields are optional).
   - A Pydantic model for update requests (all fields are optional -- partial update semantics).
   - A Pydantic model for the response (all fields, plus `id`, `meta`, and `relationships`).
   - Five CRUD routes registered under `/objects/{node_type}`.
3. Each generated route is tagged in OpenAPI with the node type's category (e.g., `Infrastructure`, `Network`) for organized API documentation.
4. The OpenAPI spec is available at `/api/v1/openapi.json` and the interactive docs at `/api/v1/docs` (Swagger UI) and `/api/v1/redoc` (ReDoc).

**Dynamic model generation:**

```python
# Simplified illustration of the dynamic model factory
def create_pydantic_model(node_type_def: NodeTypeDefinition) -> type[BaseModel]:
    fields = {}
    for attr in node_type_def.attributes:
        python_type = SCHEMA_TYPE_MAP[attr.type]  # e.g., "string" -> str, "ipv4" -> IPv4Address
        if attr.required:
            fields[attr.name] = (python_type, ...)
        else:
            fields[attr.name] = (python_type | None, None)
    return create_model(f"{node_type_def.name}Create", **fields)
```

**Schema reload:**

When a `schema.changed` event is received (via NATS), the API triggers a graceful route re-registration. New routes are added, removed routes are deregistered, and modified routes have their Pydantic models regenerated. In-flight requests complete against the old routes. This enables schema hot-reload without API restart.

---

## 15. Eventing/Workflow Design

### 15.1 Event Architecture

NetGraphy uses NATS as its event backbone. NATS was chosen over Kafka or RabbitMQ for three reasons: operational simplicity (single binary, no ZooKeeper), built-in JetStream for durable streaming, and native subject-based routing that maps cleanly to NetGraphy's resource hierarchy.

Two messaging patterns coexist:

- **NATS JetStream** for durable event streams where delivery guarantees matter. Consumers can replay from any point. Used for audit, data changes, job lifecycle, and schema events.
- **Core NATS** (plain pub/sub) for ephemeral, best-effort notifications where loss is acceptable. Used for WebSocket push to connected UI clients and real-time log streaming.

**Stream definitions:**

| Stream | Subjects | Retention | Max Age | Storage | Purpose |
|--------|----------|-----------|---------|---------|---------|
| `AUDIT` | `audit.>` | Limits (size + age) | 90 days | File | Immutable audit trail. Every state-changing API call produces an audit event. |
| `SCHEMA` | `schema.>` | Limits (age) | 365 days | File | Schema change events. Low volume, long retention for compliance. |
| `DATA` | `data.>` | Limits (age) | 7 days | File | Node and edge CRUD events. High volume during ingestion runs. Consumers use this for cache invalidation, webhooks, and real-time UI updates. |
| `JOBS` | `jobs.>` | Limits (age) | 30 days | File | Job lifecycle events: queued, started, progress, completed, failed. |
| `SYNC` | `sync.>` | Limits (age) | 30 days | File | Git sync events: started, validated, applied, failed. |

**Subject hierarchy:**

```
audit.{action}.{resource_type}
  audit.create.device
  audit.update.interface
  audit.delete.edge.connected_to
  audit.login.user
  audit.query.cypher

schema.changed
schema.migrated
schema.validated

data.{action}.{node_or_edge_type}
  data.created.device
  data.updated.device
  data.deleted.device
  data.created.connected_to    (edge events use edge type name)
  data.bulk.ingestion          (batch event for ingestion runs)

jobs.{job_name}.{status}
  jobs.collect_device_facts.queued
  jobs.collect_device_facts.started
  jobs.collect_device_facts.progress
  jobs.collect_device_facts.completed
  jobs.collect_device_facts.failed

sync.{source_name}.{status}
  sync.network-schemas.started
  sync.network-schemas.validated
  sync.network-schemas.applied
  sync.network-schemas.failed
```

**Event payload format:**

All events share a common envelope:

```json
{
  "event_id": "evt-a1b2c3d4",
  "event_type": "data.created.device",
  "timestamp": "2026-03-28T10:15:30.123Z",
  "actor": {
    "user_id": "usr-001",
    "username": "jmercer",
    "source": "api"
  },
  "correlation_id": "req-xyz-789",
  "payload": {
    "resource_type": "device",
    "resource_id": "d7f3a1b2-4c5e-6f7a-8b9c-0d1e2f3a4b5c",
    "data": { "hostname": "core-rtr-01.sea", "status": "active" },
    "diff": null
  }
}
```

For update events, `payload.diff` contains the before/after values:

```json
{
  "diff": {
    "status": {"before": "planned", "after": "active"},
    "management_ip": {"before": null, "after": "10.0.1.1"}
  }
}
```

---

### 15.2 Event Consumers

Each consumer runs as a durable JetStream consumer with explicit acknowledgment. If a consumer crashes, unacknowledged messages are redelivered after the ack timeout. Consumers are deployed as independent processes (or goroutines in the Go worker) and scale horizontally.

**Audit Logger:**

- Subscribes to: `audit.>`
- Behavior: Writes every audit event to the audit storage table (PostgreSQL or Neo4j audit nodes, depending on configuration). Appends to an immutable append-only store. Never modifies or deletes records.
- Delivery: Must be exactly-once (deduplication by `event_id`). This is the compliance-critical consumer.

**Cache Invalidator:**

- Subscribes to: `data.>`, `schema.>`
- Behavior: On data change events, invalidates the Redis cache entries for the affected resource and its list views. On schema change events, invalidates the entire UI metadata cache and triggers Pydantic model regeneration in the API process.
- Delivery: At-least-once is acceptable. Duplicate invalidations are harmless (cache miss followed by re-population).
- Implementation: Publishes a `cache.invalidated.{resource_type}` message on Core NATS after invalidation, which the API process listens for to clear its in-process caches.

**WebSocket Bridge:**

- Subscribes to: `data.>`, `jobs.>`, `sync.>`
- Behavior: Maintains a registry of connected WebSocket clients and their subscriptions (each client subscribes to specific resource types or jobs). When a matching event arrives, pushes it to the relevant clients. Filters events by the client's RBAC permissions -- a user who cannot read devices does not receive device change events.
- Delivery: Best-effort via Core NATS relay. WebSocket clients handle reconnection and catch-up via the REST API if they miss events.

**Webhook Dispatcher:**

- Subscribes to: Configurable per webhook registration. Users register webhooks with a subject filter (e.g., `data.created.device`, `jobs.*.failed`).
- Behavior: For each matching event, sends an HTTP POST to the registered URL with the event payload. Implements retry with exponential backoff (3 attempts, 1s/5s/30s delays). Records delivery status per webhook per event.
- Delivery: At-least-once. Webhook receivers must be idempotent (they receive the `event_id` for deduplication).
- Configuration: Webhooks are registered via `POST /api/v1/webhooks` (Phase 4 feature). Each webhook specifies a URL, subject filter, optional secret for HMAC signing, and active/inactive status.

**Notification Service (Future):**

- Subscribes to: Configurable per notification rule.
- Behavior: Sends email or Slack notifications based on event rules. Example: notify the network team Slack channel when any device status changes to `failed`.
- Planned for Phase 4 or later.

---

### 15.3 Workflow Hooks (Future)

Workflow hooks extend the event system with pre/post triggers defined in the schema. They allow schema authors to declare automated reactions to data changes without writing custom consumers.

**Schema-defined hooks:**

```yaml
# In a node type definition
node_types:
  device:
    hooks:
      on_create:
        - action: emit_event
          subject: "workflows.device.onboarding"
        - action: execute_job
          job: "validate_device_reachability"
          params:
            target: "{{ node.management_ip }}"

      on_update:
        - condition: "old.status != new.status AND new.status == 'decommissioned'"
          action: execute_job
          job: "device_decommission_cleanup"
          params:
            device_id: "{{ node.id }}"

      on_delete:
        - action: emit_event
          subject: "workflows.device.deleted"
          payload:
            hostname: "{{ node.hostname }}"
            deleted_by: "{{ actor.username }}"
```

**Hook execution model:**

- **Pre-hooks** run before the database write. They can validate, enrich, or reject the operation. A pre-hook that raises an error aborts the entire operation. Pre-hooks run synchronously within the request transaction.
- **Post-hooks** run after the database write is committed. They are dispatched as events and executed asynchronously. A failing post-hook does not roll back the data change.
- Hooks are evaluated by the API layer at request time. The hook definitions are loaded from the schema registry and cached in memory.

**Guard rails:**

- Hooks cannot call other hooks (no cascading). If a hook triggers a job that modifies a node, that modification does not re-trigger hooks.
- Hook execution is logged as an audit event with the triggering event's correlation ID.
- Hooks have a 5-second timeout for pre-hooks (synchronous) and no timeout for post-hooks (asynchronous).
- Hook definitions are validated at schema load time. Invalid hook references (nonexistent jobs, malformed conditions) cause schema validation to fail.

---

## 16. Initial Product UX Design

### 16.1 Navigation Structure

The sidebar is the primary navigation element. It is organized by category, and categories are populated dynamically from the schema registry. When a user defines a new node type with `category: Infrastructure`, it automatically appears under the Infrastructure section without any frontend code changes.

```
[Logo] NetGraphy

INFRASTRUCTURE
  +-- Devices
  +-- Interfaces
  +-- Locations
  +-- Hardware Models

NETWORK
  +-- Connections
  +-- Services

SOFTWARE
  +-- Platforms
  +-- Software Versions
  +-- Images

REFERENCE
  +-- Vendors
  +-- Custom Types...

OPERATIONS
  +-- Query Workbench
  +-- Graph Explorer
  +-- Saved Queries
  +-- Dashboards

AUTOMATION
  +-- Jobs
  +-- Job History
  +-- Parsers
  +-- Command Bundles
  +-- Ingestion Runs

ADMINISTRATION
  +-- Schema Explorer
  +-- Git Sources
  +-- Users & Roles
  +-- Audit Log
```

**Navigation behavior:**

- The top sections (Infrastructure, Network, Software, Reference) are auto-populated from schema. Each section corresponds to a `category` value in the node type definitions. Node types within a category are ordered by the `nav_order` schema attribute, falling back to alphabetical.
- The Operations, Automation, and Administration sections are static (hardcoded in the frontend). They link to purpose-built pages, not schema-driven CRUD.
- The sidebar collapses to icons on narrow viewports. Each category has an icon defined in the schema or falls back to a default.
- A global search bar sits above the sidebar categories. It searches across all node types using a full-text index in Neo4j.
- The user avatar and settings menu are at the bottom of the sidebar.

---

### 16.2 Page Descriptions

#### 16.2.1 Dashboard

The dashboard is the landing page after login. Its purpose is to give a network engineer an immediate sense of the current state of their infrastructure and the platform's operational health.

**Layout:** A responsive grid of cards and panels.

**Components:**

- **Summary cards (top row):** Total devices, active devices, total interfaces, recent changes (last 24h), recent job runs (last 24h). Each card shows the count and a sparkline trend over the last 7 days. Cards are clickable and navigate to the corresponding list view.
- **Recent activity feed (left column):** A chronological list of the last 50 data changes across all types. Each entry shows: timestamp, actor, action ("jmercer created device core-rtr-03.sea"), and a link to the affected resource. Filterable by action type and resource type.
- **Quick search (top):** A prominent search bar that searches across all node types by display name, hostname, IP address, or any indexed attribute. Results appear in a dropdown as the user types. Powered by Neo4j full-text indexes.
- **System health indicators (right column):** Small status badges showing the health of dependent services: Neo4j (connected/degraded/down), NATS (connected/disconnected), worker pool (N workers active), Git sync (last sync time and status per source). Red/yellow/green color coding.
- **Pinned saved queries (bottom):** Users can pin saved queries to their dashboard. Each pinned query shows its name, description, and a live result count or mini table. Clicking opens the query in the Query Workbench. Results refresh on a configurable interval (default: 5 minutes) or on relevant data change events via WebSocket.

---

#### 16.2.2 Schema Explorer

The Schema Explorer provides visibility into the current schema and its history. It is the primary tool for understanding the data model and planning schema changes.

**Layout:** Full-page with a left panel and a main content area.

**Components:**

- **Visual ER diagram (main area):** An interactive graph visualization showing all node types as boxes and edge types as labeled arrows between them. Node type boxes show the type name, icon, and attribute count. Clicking a node type box selects it and shows its detail in the right panel. The diagram uses a force-directed layout by default, with options for hierarchical and circular layouts. Categories are color-coded.
- **Type detail panel (right, on selection):** Shows the full definition of the selected node or edge type: all attributes with types, constraints, default values, UI hints (field order, group, list visibility), and edge definitions. Read-only view of the YAML source.
- **Schema version history (tab):** A timeline of schema changes. Each entry shows the version, timestamp, source (Git sync or manual API call), and a summary of changes (types added, modified, removed). Clicking a version shows the full diff.
- **Pending migration viewer (tab):** If a schema change has been validated but not yet applied, this tab shows the pending migration plan: what Neo4j constraints will be added/removed, what indexes will be created, and what data migrations are needed.
- **Schema diff viewer (tab):** Compare any two schema versions side-by-side. Highlights added, removed, and modified types and attributes.

---

#### 16.2.3 Node Type List Page (e.g., Devices)

Every node type gets the same list page structure, dynamically configured by the schema. The Devices page and the Locations page share the same React component; only the schema configuration differs.

**Layout:** Full-page data table with a toolbar.

**Components:**

- **Data table:** Columns are defined by the schema's `list_column: true` attribute flag. For devices, this might be: hostname, management_ip, status, platform, role, location (as a linked reference). Each column header supports click-to-sort. Column widths are resizable and persisted in local storage.
- **Filtering bar:** Above the table. Shows active filters as removable chips. An "Add Filter" button opens a dropdown of all filterable attributes with operator selection (contains, equals, greater than, etc.). Attribute types determine available operators (e.g., IP fields get `subnet_of`, string fields get `contains`).
- **Search:** A free-text search box that searches across all text attributes of the node type.
- **Bulk actions:** Checkbox column on the left. When rows are selected, a bulk action bar appears at the top: Delete Selected, Export Selected (CSV/JSON). Future: Bulk Edit.
- **Create button:** Top right. Opens the create form (see 16.2.5).
- **Row click:** Navigates to the node detail page.
- **View toggle:** Table view (default) and card view. Card view shows each node as a card with icon, display name, key attributes, and status badge. Useful for visual scanning of smaller collections.
- **Pagination:** Bottom of table. Shows current page, total count, and page size selector (25, 50, 100).
- **Export:** "Export" button in the toolbar. Exports the current filtered/sorted view as CSV or JSON. For large exports, triggers an async job and provides a download link.

---

#### 16.2.4 Node Detail Page

The detail page shows everything about a single node: its attributes, relationships, graph context, and history.

**Layout:** Header section with key identity info, followed by a tabbed content area.

**Components:**

- **Header:** Node type icon, display name (e.g., hostname for devices), status badge (colored by status value), and action buttons (Edit, Delete, Clone). Breadcrumb trail: Home > Devices > core-rtr-01.sea.
- **Attribute sections:** Below the header, key attributes are displayed in a two-column layout. Attributes are grouped by the schema's `group` metadata (e.g., "Identity", "Management", "Physical"). Each group is a collapsible section.

**Tabs:**

- **Overview:** The default tab. Shows all attributes organized by group. Read-only display with an "Edit" button that switches to inline editing.
- **Relationships:** One panel per edge type that connects to this node. Each panel shows: edge type label, count, and a mini-table of related nodes with key attributes. Example: "Interfaces (24)" with a table showing interface name, type, status, IP. Each related node is clickable. "Add" button to create a new edge. "Remove" button on each row to delete the edge.
- **Graph:** A mini graph visualization centered on this node. Shows 1-hop neighbors by default with controls to expand to 2 or 3 hops. Uses the same graph rendering engine as the Graph Explorer but in a smaller viewport. Double-click a neighbor to navigate to its detail page.
- **History:** Audit trail for this node. Shows all create, update, and delete events in reverse chronological order. Each event shows: timestamp, actor, action, and the attribute diff (before/after values). Filterable by date range and action type.
- **Raw:** JSON view of all node properties as stored in Neo4j. Includes internal metadata (created_at, updated_at, provenance). Copyable. Useful for debugging and API integration development.

---

#### 16.2.5 Create/Edit Form

Forms are generated entirely from the schema. No hardcoded form exists for any node type.

**Layout:** Single-column form with grouped sections matching the schema's `group` metadata.

**Field type mapping:**

| Schema Type | Form Widget | Behavior |
|-------------|-------------|----------|
| `string` | Text input | Max length validation from schema. |
| `text` | Textarea | Multi-line free text. |
| `integer` / `float` | Number input | Min/max validation from schema. Step defined for floats. |
| `boolean` | Toggle switch | Default value from schema. |
| `enum` | Select dropdown | Options populated from schema enum values. |
| `date` / `datetime` | Date picker | Calendar widget with format validation. |
| `ipv4` / `ipv6` | Text input with validation | Validates IP address format on blur. Shows error for invalid addresses. |
| `cidr` | Text input with validation | Validates CIDR notation. Shows the subnet and host count on valid input. |
| `mac_address` | Text input with validation | Validates MAC address format. Normalizes to colon-separated on blur. |
| `reference` | Searchable select | Dropdown that searches the referenced node type by display name. Shows a mini-preview of the selected node. Supports "Create New" inline for quick reference creation. |
| `json` | Code editor (Monaco) | JSON editor with syntax highlighting and validation. |

**Reference selectors:** When a field references another node type (e.g., Device.location references Location), the form widget is a searchable dropdown. The user types to search, and the dropdown shows matching nodes with their display name and key attributes. Selection populates the field with the node's ID. A "Create New" button at the bottom of the dropdown opens a modal to create the referenced node inline, then auto-selects it.

**Relationship creation inline:** For edge types marked as `inline_create: true` in the schema, the create form includes an "Add {Edge Type}" section at the bottom. Example: when creating a Device, the form may include an "Add Interfaces" section where the user can add interface rows inline. Each row is a mini-form with the interface's required attributes.

**Validation:** All validation rules from the schema (required, regex, min/max, unique) are enforced client-side on blur and on submit. Server-side validation is the authoritative check; client-side validation is for immediate feedback. Validation errors appear inline below the relevant field. A summary of all errors appears at the top of the form on submit.

**Actions:**
- **Save:** Validates and submits. On success, navigates to the detail page.
- **Save & Add Another:** Validates and submits. On success, clears the form for another entry of the same type. Preserves "sticky" field values (e.g., location stays the same when adding multiple devices at the same site).

---

#### 16.2.6 Query Workbench

The Query Workbench is the power-user interface for interrogating the graph.

**Layout:** Three-panel layout.

**Left panel -- Query Library:**
- Saved queries, grouped by tag. Searchable.
- Recent queries (last 20, stored in local storage).
- Query templates: pre-built queries for common patterns (e.g., "Find all devices at site X", "Show BGP peering for device Y"). Templates are parameterized.
- Clicking a saved/recent/template query loads it into the editor.

**Center panel -- Query Editor:**
- **Mode toggle:** Cypher Editor / Structured Builder.
- **Cypher Editor:** Monaco editor instance configured with Cypher syntax highlighting, auto-completion for node types, edge types, and attribute names (populated from schema). Line numbers, bracket matching, error squiggles from Cypher parse errors. Multi-line support.
- **Structured Builder:** A form-based query builder for users who do not know Cypher. The user selects: starting node type, filter conditions (attribute filters), traversal steps (follow edge type X to node type Y), and return fields. The builder generates Cypher under the hood and shows it in a read-only panel.
- **Parameter inputs:** If the query contains parameters (e.g., `$hostname`), input fields appear above the editor for each parameter. Parameter types are inferred from the query or defined in saved query metadata.
- **Action bar:** Run (executes the query), Explain (shows the Cypher execution plan), Save (opens save dialog with name, tags, shared flag).

**Bottom panel -- Results:**
- **View toggle:** Table / Graph / JSON.
- **Table view:** Column headers from the query's return fields. Sortable, filterable. Cell values that are node references are clickable links to the detail page.
- **Graph view:** Nodes and edges from the query result rendered as an interactive graph. Uses the same rendering engine as Graph Explorer. Node styling (color, icon, size) from schema UI metadata.
- **JSON view:** Raw result payload in a collapsible tree viewer. Useful for complex nested results.
- **Result metadata:** Execution time, row count, nodes/edges returned. Shown in a status bar above the results.

---

#### 16.2.7 Graph Explorer

The Graph Explorer is a full-page interactive graph visualization for exploring the network topology.

**Layout:** Full viewport graph canvas with overlay controls.

**Entry points:**
- From a search result: the user searches for a node, and the Graph Explorer opens centered on that node with 1-hop neighbors expanded.
- From a query result: the graph view of a Query Workbench result can be "popped out" into the full Graph Explorer.
- From a node detail page: the Graph tab has an "Open in Explorer" button.
- Direct navigation: the user opens Graph Explorer empty and uses the search bar to start.

**Interaction model:**
- **Expand:** Double-click a node to expand its neighbors (load 1 hop of connected nodes). A context menu on right-click offers "Expand All", "Expand by Type" (choose which edge types to follow), and "Collapse".
- **Filter panel (left overlay):** Toggle visibility of node types and edge types. Uncheck "Interface" to hide all interface nodes and their edges. Useful for reducing visual clutter.
- **Layout selector (top toolbar):** Force-directed (default), hierarchical (top-down, good for site/device/interface trees), circular (good for peering meshes). Layout can be re-applied at any time.
- **Details sidebar (right, on node select):** Click a node to see its key attributes in a sidebar without leaving the graph. The sidebar includes a "View Detail" link to the full detail page.
- **Depth control:** A slider or numeric input that controls the default expansion depth (1, 2, or 3 hops). Higher depths load more data and may require the max nodes limit.
- **Max nodes limit:** A configurable limit (default: 500) on the total number of nodes in the viewport. When the limit is reached, a warning appears and the user must filter or remove nodes before expanding further. This prevents the browser from choking on massive graphs.

**Export:** PNG and SVG export of the current graph view. Includes a legend with node type colors and edge type labels.

**Node styling:** Each node type has a color and icon defined in the schema's UI metadata. Node size can be mapped to a numeric attribute (e.g., interface count). Edge thickness can be mapped to edge attributes (e.g., bandwidth).

---

#### 16.2.8 Parser Registry

**Layout:** Standard list/detail pages.

**List page:** Table of registered parsers with columns: platform, command, parser name, version, last tested date, test status (pass/fail). Filterable by platform and command. Searchable.

**Detail page:** Shows the parser's metadata (platform, command, version), the full TextFSM template content in a code viewer (Monaco, read-only), the associated command bundle, the associated mapping, and test history (last 10 test runs with input/output).

**Test page:** Accessible from the detail page via a "Test" button. Two-panel layout:
- **Left:** A large text area where the user pastes raw command output (e.g., the output of `show interfaces` from a Cisco router).
- **Right:** The parsed result as a structured JSON table. Each row is a parsed record. Columns are the template's value definitions.
- **Action:** "Run Parser" button. Sends the raw text to `POST /parsers/{id}/test` and displays the result. No data is persisted.

---

#### 16.2.9 Ingestion Run History

**Layout:** List page with drill-down.

**List page:** Table of ingestion runs with columns: run ID, timestamp, status (queued/running/completed/failed), device count, records parsed, mutations applied, duration. Sortable by any column. Filterable by status and date range.

**Run detail page:** Tabs:
- **Summary:** Overall statistics: devices targeted, devices reached, devices failed, total commands executed, total records parsed, total mutations (creates/updates/deletes), duration.
- **Per-device results:** A table with one row per device. Columns: hostname, status, commands executed, records parsed, mutations applied, errors. Clicking a device row expands to show per-command results.
- **Per-command detail (expanded row):** For each command on a device: raw output (link to MinIO download), parsed records (inline table), resulting mutations (list of graph operations with before/after diffs).
- **Errors:** Aggregated error list with device, command, error type, and message.

---

#### 16.2.10 Job Registry

**Layout:** List/detail pages.

**List page:** Table of registered jobs with columns: name, description, platform (Python/Go), schedule (cron expression or "manual"), last run status, last run time. Filterable by platform and status. "Run" button on each row (if the user has `job:execute` permission).

**Detail page:** Tabs:
- **Overview:** Job manifest rendered as a readable form: name, description, platform, parameter schema (shown as a table of parameter names, types, defaults, descriptions), target selector (the Cypher query), timeout, retry policy.
- **Execution history:** Table of past executions with status, duration, start/end times, triggered by (user or schedule). Clicking an execution navigates to the execution detail page.
- **Schedule:** If the job has a cron schedule, shows the schedule expression, next scheduled run, and a toggle to enable/disable the schedule.

**Run dialog:** Clicking "Run" opens a modal with:
- Parameter inputs generated from the manifest's parameter schema (same form generation logic as node create forms).
- Target override: optional Cypher query to override the manifest's default target selector.
- "Execute" button that triggers `POST /jobs/{name}/execute` and navigates to the execution detail page.

---

#### 16.2.11 Job Run Detail

**Layout:** Full-page detail view.

**Components:**

- **Status header:** Large status badge (queued/running/completed/failed), duration, start time, end time (or "running" with elapsed time).
- **Log viewer:** The main component. For running jobs, streams logs in real-time via SSE from `/jobs/{name}/executions/{id}/logs`. For completed jobs, shows the full log. Supports ANSI color rendering. Log lines are timestamped. Search within logs. Auto-scroll toggle (on by default for running jobs).
- **Artifacts:** List of artifacts produced by the job (config backups, reports, exports). Each artifact shows name, size, and a download link (served from MinIO).
- **Result summary:** If the job produces structured results (e.g., "collected facts from 47 devices, 3 unreachable"), they are shown in a summary card.
- **Affected nodes/edges:** If the job modified graph data, a list of affected resources with links to their detail pages. Shows the mutation type (created/updated/deleted) for each.

---

#### 16.2.12 Git Sources

**Layout:** List/detail pages.

**List page:** Table of registered Git sources with columns: name, repo URL, branch, content domains (badges: "schemas", "parsers", "jobs"), sync status (synced/pending/error), last sync time. "Sync Now" button on each row.

**Detail page:** Tabs:
- **Overview:** Repository info (URL, branch, auth method), content domain mapping (which directories map to schemas, parsers, jobs, etc.), sync configuration (schedule, auto-apply or require approval).
- **Sync history:** Table of sync events. Columns: timestamp, commit SHA, status, files changed, duration. Clicking a sync event shows the full diff: files added/modified/removed, schema migrations applied, parser updates, job manifest changes. Each change links to the affected resource.
- **Preview:** Shows pending changes that would be applied on the next sync. Fetches the remote, computes the diff, and shows it in a structured format: "3 schema changes, 2 new parsers, 1 job updated". Each change is expandable to show the full diff. A "Sync Now" button applies the previewed changes.

---

#### 16.2.13 Saved Query Library

**Layout:** Searchable card/list view.

**Components:**
- **Search and filter bar:** Free-text search across query names and descriptions. Tag filter (multi-select). Owner filter (my queries / shared / all).
- **Query cards:** Each saved query is a card showing: name, description (truncated), tags, owner, last run time, share status. Cards are clickable to open in the Query Workbench.
- **Actions per card:** Run (executes immediately with default params, shows results in a modal), Edit (opens in Query Workbench), Share/Unshare, Delete.
- **Import from Git:** If a Git source contains saved queries (in a `queries/` directory), they appear in the library with a "Git" badge and are read-only (edits must go through Git).

---

## 17. Phased Delivery Plan

### Phase 1: Graph-Native SoT MVP

**Duration:** 8--10 weeks

**Objective:** Deliver a working graph-native source-of-truth that proves the core thesis: define a node type in YAML, and it appears in the UI with full CRUD, query, and visualization. This phase establishes the foundation that everything else builds on.

**Scope:**

| Component | Deliverables |
|-----------|-------------|
| Schema Engine | YAML schema loading and validation. Schema registry backed by Neo4j. Schema versioning. Hot-reload on change. Support for core types: string, integer, float, boolean, enum, date, ipv4, ipv6, cidr, mac_address, reference. |
| Graph Repository | Neo4j driver integration. CypherBuilder for safe, parameterized query generation. Connection pooling. Transaction management. Constraint and index creation from schema definitions. |
| Query Engine | Cypher execution with RBAC-aware query rewriting. Structured query builder backend (JSON-to-Cypher translation). Query timeout enforcement. Result serialization (table and graph formats). |
| REST API | Full CRUD for dynamic node types and edges (Sections 14.1.1--14.1.3). Schema discovery endpoints (Section 14.1.1). Query endpoints (Section 14.1.4). OpenAPI auto-generation. Filtering, pagination, sorting (Section 14.3). |
| Web Application | Sidebar navigation (auto-populated from schema). Node type list page with data table. Node detail page with all tabs (Overview, Relationships, Graph, History, Raw). Create/edit form with dynamic field generation. |
| Graph Visualization | Force-directed graph rendering (D3.js or Cytoscape.js). Node/edge styling from schema metadata. Basic interaction: click to select, double-click to expand, drag to reposition. Mini graph on node detail page. |
| Query Workbench | Monaco-based Cypher editor with syntax highlighting. Table and graph result views. Save/load queries. |
| Git Sync (Basic) | Read-only sync of schema files from a Git repository. Manual trigger via API. Schema validation before apply. |
| Infrastructure | Docker Compose for local development: API, web, Neo4j, Redis, NATS. Seed data script with realistic network topology (50+ devices, interfaces, locations, connections). |
| Core Schema Files | YAML definitions for: Device, Interface, Location, Site, Rack, Vendor, Platform, HardwareModel, IPAddress, Prefix, VLAN, Circuit, Provider. Edge types: connected_to, installed_in, located_at, member_of, assigned_to, belongs_to, provides. |

**Week-by-week breakdown:**

| Week | Focus |
|------|-------|
| 1--2 | Schema engine: YAML parser, validator, registry. Neo4j driver setup and CypherBuilder. Core schema files authored. |
| 3--4 | Graph repository: CRUD operations, constraint management, transaction handling. REST API: dynamic route registration, CRUD endpoints, filtering, pagination. |
| 5--6 | Web app: project scaffolding (React + TypeScript + Vite), sidebar navigation, list page with data table, detail page with attribute display. |
| 7--8 | Create/edit forms, graph visualization (mini graph on detail page, basic explorer), Cypher editor with results. |
| 9--10 | Git sync (basic), Docker Compose, seed data, integration testing, bug fixes, polish. |

**Risks and mitigations:**

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schema engine complexity exceeds estimate. Handling all type permutations, validation rules, and migration planning in 2 weeks is aggressive. | Medium | High | Scope Phase 1 schema engine to core types only. Defer complex types (json, computed, polymorphic) to later phases. Build the engine with extension points but do not implement all extensions. |
| Dynamic UI quality is poor. Auto-generated forms and tables from schema may feel generic and lack the polish of purpose-built UI. | Medium | Medium | Invest in the UI metadata system (icons, groups, ordering, display hints). Allow schema authors to control the presentation. Build a small number of "showcase" types (Device, Interface) with rich UI metadata to demonstrate quality. |
| Graph visualization performance degrades with >100 nodes. Browser-based graph rendering is notoriously expensive. | Medium | Medium | Implement the max-nodes limit from day one (default 200 for Phase 1). Use WebGL-accelerated rendering (Cytoscape.js with canvas renderer). Defer clustering and level-of-detail to Phase 4. |
| Neo4j query performance is unpredictable without production-scale data. | Low | High | Define indexing strategy in schema (indexed attributes get Neo4j indexes). Load-test with 10K nodes in Week 9. Profile slow queries and add composite indexes. |

**Acceptance criteria:**

1. Define a new node type `custom_equipment` in a YAML file. Push it to the schema Git repo (or apply via API). Verify it appears in the sidebar under its defined category, with a working list page, detail page, and create/edit form.
2. Create a device via the API (`POST /api/v1/objects/device`). Verify it appears in the device list page. Click into the detail page. Edit the hostname. Verify the change persists.
3. Create an edge between a device and a location (`POST /api/v1/edges/located_at`). Verify the relationship appears on both the device detail page (Relationships tab) and the location detail page.
4. Execute a Cypher query in the Query Workbench: `MATCH (d:Device)-[:CONNECTED_TO]-(n) WHERE d.hostname = 'core-rtr-01.sea' RETURN d, n`. Verify results display in table view and graph view.
5. Apply a schema change from Git: add a new attribute `firmware_version` to the Device type. Sync the Git source. Verify the attribute appears in the Device create form and detail page without restarting any service.
6. Run the entire platform locally with `docker compose up`. Verify all services start, seed data loads, and the UI is accessible at `http://localhost:3000`.

---

### Phase 2: Parser and Ingestion

**Duration:** 6--8 weeks

**Objective:** Close the loop between network devices and the graph. Data should flow from device command output through parsers and mappings into the graph automatically, with full provenance tracking.

**Scope:**

| Component | Deliverables |
|-----------|-------------|
| Parser Registry | TextFSM template storage and CRUD API (Section 14.1.5). Template syntax validation on upload. Parser versioning. |
| Parser Test Page | UI for pasting raw command output and seeing parsed results (Section 16.2.8). Fixture management: save test inputs with expected outputs for regression testing. |
| Command Bundles | CRUD for command bundle definitions. A bundle maps a platform to a list of commands and their associated parsers. |
| Mapping Engine | Mapping definition CRUD. A mapping translates parsed records into graph mutations: field-to-attribute mapping, reference resolution (e.g., parsed interface name maps to an Interface node), upsert logic (match on key fields, create or update). |
| Ingestion Pipeline | Orchestration of collect-parse-map-upsert. The pipeline: (1) collects raw output from devices (via Nornir or mock for Phase 2), (2) stores raw output in MinIO, (3) parses with the associated TextFSM template, (4) applies mappings to generate graph mutations, (5) executes mutations against Neo4j with provenance metadata. |
| Raw Output Storage | MinIO integration for storing raw command output. Organized by device, command, timestamp. Referenced from ingestion run records. |
| Provenance Tracking | Every node attribute set by ingestion carries provenance metadata: source (ingestion run ID), timestamp, raw output reference, parser version. The UI shows provenance on hover for each attribute value. |
| Ingestion Run History UI | Run list and detail pages (Section 16.2.9). Per-device, per-command drill-down. |
| Git Sync for Content | Extend Git sync to handle parsers, command bundles, and mappings. Content files in Git are synced to the registry. |

**Week-by-week breakdown:**

| Week | Focus |
|------|-------|
| 1--2 | Parser registry API, TextFSM template validation, parser test endpoint. Command bundle and mapping data models. |
| 3--4 | Mapping engine: field mapping DSL, reference resolution, upsert logic. MinIO integration for raw output storage. |
| 5--6 | Ingestion pipeline orchestration. Provenance tracking on graph mutations. Ingestion run tracking. |
| 7--8 | Parser test UI, ingestion run history UI. Git sync for parsers/mappings. Integration testing with real device output fixtures. |

**Risks and mitigations:**

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Mapping engine flexibility is insufficient. Real-world device output is messy -- parsers produce records that do not map 1:1 to graph nodes. | High | High | Design the mapping DSL to support: one-to-many (one parsed record creates multiple nodes), many-to-one (multiple records merge into one node), conditional mapping (if field X is present, map to type A, else type B), and computed fields (concatenate, regex extract). Start with the simple cases and extend. |
| TextFSM parser compatibility with NTC-templates. Users expect to use the existing NTC-templates library. | Medium | Medium | Test against the top 20 most-used NTC-templates in Phase 2. File issues and contribute fixes upstream if needed. Document known incompatibilities. |
| Provenance tracking overhead slows ingestion. Storing provenance per attribute per mutation adds write volume. | Low | Medium | Store provenance as a JSON blob on the node rather than as separate properties per attribute. Benchmark ingestion with and without provenance. If overhead exceeds 20%, make provenance optional per mapping. |

**Acceptance criteria:**

1. Register a TextFSM template for `cisco_ios` / `show interfaces`. Paste fixture output on the test page. Verify parsed records match expected structure.
2. Define a mapping from `show interfaces` parsed records to Interface node upserts (match on device + interface name, update status, speed, description).
3. Run an ingestion pipeline against 5 mock devices. Verify: raw output stored in MinIO, records parsed correctly, Interface nodes created/updated in the graph with correct attributes, provenance metadata present on each ingested attribute.
4. View an ingestion run in the UI. Drill into a specific device and command. See the raw output, parsed records, and resulting mutations.
5. Hover over an interface's `status` attribute in the UI. See provenance tooltip: "Set by ingestion run #12 at 2026-03-28 10:15, parsed from show interfaces output."
6. Push a new parser template to the Git source. Sync. Verify the parser appears in the registry.

---

### Phase 3: Jobs and Automation

**Duration:** 6--8 weeks

**Objective:** Enable users to define, schedule, and execute automation jobs that interact with both the graph (as a source of truth) and network devices (via Nornir or custom logic). The graph becomes not just a record, but a driver of automation.

**Scope:**

| Component | Deliverables |
|-----------|-------------|
| Job Framework | Job manifest schema (YAML). Manifest loader and validator. Job registry. Parameter schema support (typed parameters with defaults and descriptions). Target selector (Cypher query that determines which devices/nodes a job runs against). |
| Python Job Worker | Celery-based worker for Python jobs. Jobs are Python modules that receive a context object with: graph client, target list, parameters, logger, artifact writer. Worker runs in a Docker container with network access. |
| Go Job Worker | Custom Go binary that pulls job manifests and executes Go-based jobs. Communicates with the API via gRPC or REST. Suitable for high-performance jobs (bulk polling, SNMP collection). |
| Nornir Integration | Nornir inventory plugin that reads device inventory from the NetGraphy graph API. Supports filtering by any graph attribute or relationship (e.g., "all devices at site SEA with role=access_switch"). Nornir tasks can write results back to the graph via the API. |
| Job Scheduling | Cron-based scheduling via Celery Beat (Python) or a dedicated scheduler service. Schedules defined in job manifests. Enable/disable via API and UI. |
| Job Logs and Artifacts | Real-time log streaming via SSE. Logs stored in MinIO. Artifact upload API (jobs can store config backups, reports, exports). Artifact download in UI. |
| Job UI | Job registry page, run dialog with parameter form, execution history, execution detail with log viewer (Section 16.2.10, 16.2.11). |
| Git Sync for Jobs | Job manifests and Python modules synced from Git. Worker auto-loads new/updated jobs. |
| Secret Injection | Jobs can reference secrets by name. Secrets are injected as environment variables at runtime. Backed by HashiCorp Vault (preferred) or environment variables (simple mode). Secret references in manifests are validated at load time. |

**Week-by-week breakdown:**

| Week | Focus |
|------|-------|
| 1--2 | Job manifest schema and registry. Celery worker scaffolding. Job context API (graph client, logger, artifact writer). |
| 3--4 | Nornir inventory plugin. First working job: collect device facts via Nornir and update graph. Log streaming via SSE. |
| 5--6 | Job scheduling (Celery Beat). Go worker prototype. Secret injection. Artifact storage. |
| 7--8 | Job UI (registry, run dialog, execution detail, log viewer). Git sync for jobs. Integration testing. |

**Risks and mitigations:**

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Worker security. Jobs execute arbitrary code with network access. A malicious or buggy job could compromise the platform or network devices. | High | Critical | Run workers in isolated containers with no access to the API's internal network. Jobs interact with the graph only through the public API (with their own service account token). Limit resource consumption per job (CPU, memory, time). Implement job approval workflow in Phase 4. |
| Go worker integration complexity. Maintaining a separate worker runtime adds operational overhead. | Medium | Medium | Phase 3 delivers the Go worker as a prototype. Full production support (scheduling, artifact management, log streaming) comes in Phase 4. The Python worker handles 90% of use cases. |
| Secret management varies wildly across deployments. Some users have Vault, some do not. | Medium | Low | Support three secret backends: environment variables (always available), file-based (Docker secrets / K8s secrets), and Vault (optional). Default to environment variables. Document Vault integration. |

**Acceptance criteria:**

1. Write a Python job (`collect_device_facts.py`) with a manifest (`collect_device_facts.yaml`) that: uses Nornir to SSH into target devices, runs `show version`, parses the output, and updates the Device node's `os_version` and `serial_number` attributes in the graph.
2. The job's target selector is a Cypher query: `MATCH (d:Device) WHERE d.status = 'active' AND d.platform = 'cisco_iosxe' RETURN d`. Verify the job only runs against matching devices.
3. Execute the job from the UI. Provide parameters (e.g., `dry_run: true`). Verify the execution starts and logs appear in real-time in the log viewer.
4. After job completion, verify artifacts (raw command output) are stored and downloadable. Verify affected Device nodes show updated attributes.
5. Schedule the job to run daily at 02:00. Verify the schedule appears in the UI. Disable the schedule via the UI toggle. Verify it does not run.
6. Push a new job manifest and Python module to the Git source. Sync. Verify the job appears in the job registry.

---

### Phase 4: Enterprise Hardening

**Duration:** 8--10 weeks

**Objective:** Make NetGraphy production-ready for enterprise deployment. This phase addresses the concerns that block adoption in regulated or large-scale environments: authentication, authorization, audit, performance, and operational maturity.

**Scope:**

| Component | Deliverables |
|-----------|-------------|
| OIDC/SAML Authentication | OIDC integration (Keycloak, Okta, Azure AD). SAML support for legacy IdPs. Local user management as fallback. Session management with configurable timeout. |
| Full RBAC | Role-based access control at three levels: per-type (user can read Devices but not Circuits), per-action (user can read but not write), per-field (user can see hostname but not management_ip for sensitive devices). Roles are assignable to users and groups (synced from IdP). Permission evaluation integrated into every API endpoint and Cypher query. |
| Audit Log | Full audit log with search and filter UI (Section 16.2.12 -- Audit is under Administration). Every state-changing operation is logged with actor, action, resource, before/after diff, and request metadata. Retention policy configurable. Export to SIEM via syslog or webhook. |
| Query Performance | Query result caching in Redis with automatic invalidation via data change events. Query plan analysis and index recommendations. Slow query log. Bulk query endpoint for batch operations. |
| Bulk Import/Export | CSV and JSON bulk import with validation preview. Bulk export of filtered views. Async processing for large datasets with progress tracking. |
| API Token Management | Long-lived API tokens with scopes, expiry, and rotation. Token management UI. Token usage tracking (last used, request count). |
| Webhook Dispatch | Webhook registration API and UI. Configurable event filters. HMAC signature verification. Delivery tracking with retry. |
| Graph Visualization (Advanced) | Clustering (group nodes by type or attribute). Level-of-detail (show clusters when zoomed out, individual nodes when zoomed in). Large-graph rendering with WebGL. Additional layouts: geographic (if nodes have coordinates), CLOS/spine-leaf. |
| Multi-Tenancy Groundwork | Workspace model: each workspace is an isolated subgraph with its own schema extensions, users, and roles. Neo4j label-based scoping (each node carries a workspace label). API and query engine filter by workspace. Full multi-tenancy is Phase 5, but the data model and access control foundations are laid here. |
| Kubernetes Deployment | Helm chart for production Kubernetes deployment. Configurable replicas, resource limits, and PVC sizes. Ingress configuration. TLS termination. Health checks and readiness probes. |
| Monitoring | Prometheus metrics from all services (API request rate/latency, Neo4j query time, NATS message throughput, worker pool utilization). Grafana dashboards for operational monitoring. Alerting rules for common failure modes. |
| Documentation | User guide (getting started, schema authoring, query writing, job development). API documentation (auto-generated from OpenAPI + narrative guides). Schema specification reference. Deployment guide (Docker Compose and Kubernetes). |

**Week-by-week breakdown:**

| Week | Focus |
|------|-------|
| 1--2 | OIDC integration and session management. RBAC data model (roles, permissions, assignments). Permission evaluation in API middleware. |
| 3--4 | RBAC enforcement in Cypher queries (type-level filtering injected into query rewriter). Audit log storage and API. API token management. |
| 5--6 | Webhook dispatch. Bulk import/export. Query caching with Redis. Slow query logging. |
| 7--8 | Kubernetes Helm chart. Prometheus metrics and Grafana dashboards. Health checks. Advanced graph visualization (clustering, WebGL). |
| 9--10 | Multi-tenancy data model and workspace scoping. Documentation. Performance testing (10K+ nodes, 50K+ edges). Bug fixes and hardening. |

**Risks and mitigations:**

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| RBAC complexity. Per-type, per-field, per-action permissions create a combinatorial explosion that is hard to reason about and test. | High | High | Start with per-type, per-action RBAC (the 80% case). Add per-field RBAC as an opt-in feature for specific types (e.g., mark `management_ip` as `restricted: true` in schema, only users with `device:read_restricted` can see it). Do not try to build a generic per-field RBAC engine. |
| Multi-tenancy data isolation. Label-based scoping in Neo4j must be watertight -- a query in Workspace A must never return nodes from Workspace B. | High | Critical | Implement workspace scoping as a Cypher query rewriter that injects `WHERE n.workspace = $workspace` into every query. Unit test with adversarial queries (UNION, subqueries, APOC calls). Run penetration testing in Week 10. Workspace scoping is enforced at the CypherBuilder level, not at the application level, so it cannot be bypassed by raw Cypher injection. |
| Performance at 10K+ nodes. The UI, API, and Neo4j all need to handle this scale with acceptable latency (<500ms for list pages, <2s for graph visualization). | Medium | High | Load-test in Week 9 with synthetic data (10K devices, 100K interfaces, 50K edges). Profile and optimize: add composite indexes, tune Neo4j memory settings, implement server-side pagination in graph visualization (return only visible nodes based on viewport). Establish performance budget: list page < 500ms, detail page < 300ms, graph expansion < 1s. |
| Kubernetes deployment complexity. Helm charts that work across different cluster configurations (EKS, GKE, on-prem) are hard to get right. | Medium | Medium | Test on at least two Kubernetes distributions (kind for CI, EKS for staging). Use standard patterns (StatefulSet for Neo4j, Deployment for stateless services). Document the minimum viable configuration. Do not try to support every possible configuration -- provide a reference architecture and let users customize. |

**Acceptance criteria:**

1. Configure OIDC with Keycloak (in Docker Compose). Log in via the UI. Verify the user's roles and permissions are synced from the IdP.
2. Create a role `network_readonly` with permissions: `device:read`, `interface:read`, `location:read`. Assign it to a user. Verify the user can view devices but cannot create, edit, or delete. Verify the user cannot see node types they lack permission for (no "Circuits" in sidebar if no `circuit:read` permission).
3. Execute a Cypher query as a restricted user: `MATCH (n) RETURN n`. Verify the results only include node types the user has permission to read. The RBAC filter is injected transparently -- the user does not need to add WHERE clauses.
4. View the audit log. Filter by `action=update&resource_type=device&since=2026-03-01`. Verify each event shows the actor, timestamp, and before/after diff.
5. Deploy to Kubernetes using the Helm chart. Verify all services start, health checks pass, and the UI is accessible via ingress. Scale the API to 3 replicas and verify load balancing works.
6. Load 10,000 device nodes and 50,000 edges into the graph. Verify: the device list page loads in under 500ms, the device detail page loads in under 300ms, the graph explorer can render 200 nodes without browser lag, a Cypher query returning 100 results completes in under 2 seconds.
7. Access Grafana dashboards. Verify metrics are present: API request rate, p50/p95/p99 latency, Neo4j query time, NATS message throughput, worker pool size.
