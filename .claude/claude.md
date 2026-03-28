# CLAUDE.md

## Project: NetGraph

NetGraph is a **graph-native network source-of-truth and automation platform**.

This project is:
- fully open source
- GitOps-driven
- schema-as-code (YAML)
- graph-first (not relational-first)
- automation-native (jobs, parsing, ingestion)

The system is designed to compete with NetBox and Nautobot, but with:
- graph-native modeling
- dynamic schema extension
- built-in query + visualization
- native ingestion pipelines
- Git-backed control plane

---

# 🔴 CRITICAL RULES (DO NOT VIOLATE)

## 1. Graph Abstraction Rule (NON-NEGOTIABLE)

ALL graph interactions MUST go through the graph adapter layer.

❌ NEVER:
- write raw Cypher in application logic
- couple business logic to Neo4j
- embed query strings directly in services

✅ ALWAYS:
- use GraphBackend interface
- use repository/service layer
- keep DB interchangeable

---

## 2. Schema-Driven System

The schema is the source of truth.

❌ NEVER:
- hardcode models in code
- define UI manually for specific models
- define API endpoints per model manually

✅ ALWAYS:
- derive behavior from schema
- generate UI/API from schema metadata
- validate against schema engine

---

## 3. GitOps First

All platform behavior must be Git-driven where applicable.

Content that MUST support Git sync:
- schema definitions
- helper/reference data
- parsers
- mappings
- queries
- jobs

---

## 4. Relationships Are First-Class

Edges are NOT secondary.

❌ NEVER:
- treat relationships as simple foreign keys
- flatten relationships into attributes

✅ ALWAYS:
- model relationships as edges
- support attributes on edges
- enforce cardinality rules

---

## 5. No Relational Thinking

This is NOT a relational system.

❌ NEVER:
- design tables first
- assume joins
- model everything as flat objects

✅ ALWAYS:
- think in graph traversal
- think in relationships first
- model dependencies explicitly

---

## 6. Provenance is Required

All ingested or discovered data must include:
- source
- timestamp
- parser
- job/run reference

---

# 🧱 ARCHITECTURE OVERVIEW

## Core Components

### Backend
- Python
- FastAPI
- modular architecture

### Frontend
- React + TypeScript
- schema-driven UI

### Graph DB
- Neo4j (initial)
- MUST be abstracted

### Workers
- Python (Nornir)
- Go (Gornir)

### Messaging
- NATS or RabbitMQ

---

# 🧩 CORE MODULES

## 1. schema_engine
Responsible for:
- loading YAML schema
- validation
- runtime registry
- migration planning

## 2. graph_core
Contains:
- GraphBackend interface
- Neo4j implementation
- (future) AGE implementation

## 3. repository layer
Provides:
- domain-level graph operations
- no raw queries exposed

## 4. query_engine
Handles:
- structured queries
- Cypher execution (wrapped)
- result normalization

## 5. ingestion_engine
Handles:
- command execution
- parser execution
- mapping
- graph updates
- provenance tracking

## 6. jobs_engine
Handles:
- job registration
- execution
- scheduling
- logs + artifacts

## 7. git_sync_engine
Handles:
- repo integration
- sync
- validation
- diff preview

---

# 🧠 DESIGN PRINCIPLES

## Schema → Everything

Schema drives:
- UI
- API
- validation
- graph constraints
- search
- relationships

---

## Separation of Concerns

- schema_engine: definitions
- graph_core: persistence
- repository: business logic
- ingestion: data flow
- jobs: execution
- UI: rendering

---

## Extensibility First

Every system must be:
- pluggable
- modular
- replaceable

---

# 🧬 DATA MODEL RULES

## Nodes
- must have a defined type
- must follow schema
- must validate attributes

## Edges
- must define:
  - source type
  - target type
  - cardinality
- can have attributes

---

## Cardinality Enforcement

Must support:
- one_to_one
- one_to_many
- many_to_one
- many_to_many

Enforcement happens in:
- application layer
- optionally DB constraints

---

# 🔍 QUERY SYSTEM

## Modes

1. Query Builder (no-code)
2. Cypher Editor (advanced)
3. API queries

---

## Query Rules

- always validate against schema
- restrict unsafe operations
- normalize output for UI

---

# 📊 UI RULES

## UI is GENERATED

❌ NEVER:
- hardcode pages for models

✅ ALWAYS:
- build from schema metadata

---

## Required Views

- list view
- detail view
- graph view
- table view
- query workbench

---

# 🔄 INGESTION SYSTEM

## Flow

1. select devices via query  
2. run commands  
3. parse via TextFSM  
4. map to graph  
5. store provenance  

---

## Mapping Rules

- declarative YAML
- no hardcoded transformations
- must support templating

---

# ⚙️ JOB SYSTEM

## Requirements

- Python + Go support
- GitHub integration
- scalable workers
- logs + artifacts
- retry + scheduling

---

# 🔐 SECURITY

Must support:
- RBAC
- permissions by type
- audit logs
- job execution controls

---

# 🧪 TESTING REQUIREMENTS

ALL new features must include:

- unit tests
- integration tests
- schema validation tests
- parser tests (if applicable)

---

# 🐳 LOCAL DEVELOPMENT

Must support:
- Docker Compose
- hot reload
- seeded data
- example schema

---

# 📦 REPO STRUCTURE
apps/
api/
web/

packages/
schema_engine/
graph_core/
ingestion/
jobs/

content/
schemas/
parsers/
mappings/
queries/

infra/
docker/

tests/

---

# 🚫 COMMON MISTAKES TO AVOID

- embedding Cypher in services
- bypassing schema validation
- treating graph like relational DB
- hardcoding UI behavior
- skipping provenance
- tightly coupling to Neo4j
- building ingestion logic ad hoc

---

# 🧭 WHEN UNSURE

Always default to:

1. Schema-driven approach  
2. Graph-first modeling  
3. Abstraction over direct DB usage  
4. Git-backed configuration  
5. Modular design  

---

# 🏁 FINAL RULE

NetGraph is not:

- a CRUD app
- a relational inventory system
- a plugin-based platform

NetGraph is:

> A graph-native, schema-driven, GitOps-powered network intelligence platform.

Every decision must reinforce that.