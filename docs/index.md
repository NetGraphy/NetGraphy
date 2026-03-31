---
title: "NetGraphy Documentation"
slug: "index"
summary: "Official documentation for the NetGraphy graph-native network source of truth."
category: "Home"
tags: [documentation, home, index]
status: published
---

# NetGraphy Documentation

NetGraphy is a graph-native network source of truth and automation platform. It replaces traditional table-first inventory systems with a topology-aware graph model where every device, interface, cable, circuit, prefix, and policy is a node or edge in a real graph database. The schema is defined in YAML, and everything else -- the API, the UI, the AI tools, validation, observability -- is generated from it.

![Schema Explorer](assets/screenshots/schema-explorer.png)

## Getting Started

New to NetGraphy? Start here.

- [Quick Start](getting-started/quick-start.md) -- Clone the repo, bring up the stack, seed data, and log in.
- [Your First Schema](getting-started/first-schema.md) -- Create a new node type in YAML and watch the platform generate everything for it.
- [Creating Graph Objects](getting-started/first-graph-objects.md) -- Add devices, locations, and relationships through the UI and API.
- [Using the AI Assistant](getting-started/using-the-ai-assistant.md) -- Ask questions about your network in natural language.

## Platform Overview

- [What Is NetGraphy?](overview/what-is-netgraphy.md) -- The problem it solves, how it differs from NetBox and Nautobot, and why graph-native matters.
- [Platform Architecture](overview/platform-architecture.md) -- Backend, frontend, graph database, event bus, worker pool, and how the packages fit together.
- [Graph-First Mental Model](overview/graph-first-mental-model.md) -- How to think in graphs if you come from a relational or spreadsheet-driven world.

## Core Concepts

- [Nodes](core-concepts/nodes.md), [Edges](core-concepts/edges.md), [Attributes](core-concepts/attributes.md) -- The building blocks of the graph data model.
- [Schema Model](core-concepts/canonical-schema-model.md) -- How YAML schema definitions drive the entire platform.
- [Generated Tools](core-concepts/generated-tools.md) -- MCP tools auto-generated from schema for AI agent use.
- [Validation](core-concepts/validation.md) and [Observability](core-concepts/observability.md) -- Schema-derived health checks and constraint enforcement.

## Development Tools

- [Cypher Builder](core-concepts/cypher-builder.md) -- Visual graph query builder with live Cypher generation, path traversal, and graph visualization. Build MAC-to-MAC paths, topology queries, and aggregations visually.
- [Visual Schema Designer](schema-designer/visual-designer.md) -- ERD-style visual editor for creating node types, edge types, and generating YAML schema definitions.
- [Report Builder](reports/) -- Advanced filtering and reporting with relationship-native CSV export.

## API and Agent Interfaces

- [REST API](api/) -- Full CRUD, filtering, pagination, and relationship traversal via HTTP.
- [API and Agent Interfaces](api-agent-interfaces/) -- MCP tools, AI agent runtime, and programmatic access.
- [AI Assistant](ai-assistant/) -- Natural language queries, topology-aware reasoning, and tool usage.

## Operations

- [Administration](administration/) -- User management, RBAC, tokens, and system configuration.
- [Validation and Observability](validation-observability/) -- Schema validation, constraint enforcement, and audit logging.
- [Policies and Permissions](policies-permissions/) -- Role-based access control and type-level permissions.

## Extending NetGraphy

- [Plugins and Extensions](plugins-extensions/) -- Adding custom node types, ingestion pipelines, and integrations.
- [Deployment](deployment/) -- Production deployment, scaling, and infrastructure configuration.

## Reference

- [Reference](reference/) -- Configuration options, environment variables, and CLI commands.
- [Release Notes](release-notes/) -- Changelog and migration guides.
