---
title: "Platform Architecture"
slug: "platform-architecture"
summary: "Overview of NetGraphy's backend, frontend, graph database, event bus, and package structure."
category: "Overview"
tags: [architecture, backend, frontend, neo4j, fastapi, react]
status: published
---

# Platform Architecture

NetGraphy is a modular platform composed of a Python backend, a React frontend, a Neo4j graph database, and supporting infrastructure services. Each component is independently deployable, and all graph database access is abstracted behind a backend interface to avoid coupling application logic to any specific database engine.

## Core Services

**API Server** -- A FastAPI application (`apps/api`) that serves the REST API. All endpoints are generated dynamically from the loaded YAML schema at startup. The API handles CRUD operations, relationship management, filtering, pagination, search, and bulk operations. It runs on port 8000 by default.

**Web Frontend** -- A React and TypeScript application (`apps/web`) that provides the browser-based UI. Views are schema-driven: list pages, detail pages, forms, graph visualizations, and the query workbench are all rendered from schema metadata. It runs on port 3000 and communicates with the API server.

**Worker** -- A Celery worker process (`apps/worker`) that handles asynchronous tasks including ingestion jobs, report generation, Git sync operations, and scheduled maintenance. Workers share the same codebase as the API server and connect to Neo4j and Redis independently.

## Infrastructure Services

**Neo4j** -- The graph database. All network objects are stored as labeled nodes with properties, and all relationships are stored as typed edges. NetGraphy uses Neo4j 5 Community Edition with the APOC plugin enabled. The graph backend interface in `packages/graph_db` wraps all database interactions so that no raw Cypher appears in business logic.

**Redis** -- Used for caching, session storage, and as the Celery task broker and result backend.

**NATS** -- A lightweight message bus used for real-time event distribution. Schema changes, object mutations, job completions, and other platform events are published to NATS subjects so that connected clients and services can react immediately.

**MinIO** -- S3-compatible object storage for job artifacts, report outputs, backup snapshots, and file attachments.

## Package Structure

The `packages/` directory contains the internal libraries that implement the platform's core logic:

- `schema_engine` -- Loads and validates YAML schema files, maintains the runtime type registry, and generates API and UI metadata.
- `graph_db` -- Defines the `GraphBackend` interface and provides the Neo4j implementation. This is the only package that contains database-specific code.
- `query_engine` -- Translates structured query objects and filter expressions into graph queries, normalizes results, and enforces query limits.
- `ingestion` -- Manages the ingestion pipeline: command execution, TextFSM parsing, mapping, graph updates, and provenance recording.
- `jobs` -- Job registration, scheduling, execution, logging, and artifact management.
- `ai` -- The AI agent runtime, MCP tool definitions, and prompt construction from schema metadata.
- `auth` -- Authentication, authorization, RBAC enforcement, and API token management.
- `events` -- NATS integration for publishing and subscribing to platform events.
- `sync_engine` -- Git-backed synchronization of schemas, content, parsers, and configuration.
- `sdk` -- A Python client SDK for programmatic access to the NetGraphy API.
- `docs` -- Auto-generated API documentation from schema definitions.
- `iac` -- Infrastructure-as-code integrations: config contexts, compliance rules, and transformation mappings.

## Content Directory

The `content/` directory holds declarative data that ships with the platform or is managed via GitOps: seed data for bootstrapping, helper/reference data sets, and saved queries.

## Schema Directory

The `schemas/` directory at the repository root contains all YAML schema definitions organized by domain: `core/` for built-in network types, `mixins/` for reusable attribute sets, and `iac/` for infrastructure-as-code types. This directory is mounted into both the API server and the worker at runtime.
