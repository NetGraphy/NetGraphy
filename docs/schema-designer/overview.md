---
title: "Schema Designer Overview"
slug: "schema-designer-overview"
summary: "How YAML schema definitions drive the entire NetGraphy platform, from API generation to AI agent capabilities."
category: "Schema Designer"
tags: [schema, yaml, generation, architecture, schema-engine]
status: published
---

# Schema Designer Overview

The Schema Designer is the control plane for NetGraphy's data model. Every node type, edge type, mixin, and enum in the platform is defined in a YAML file under the `schemas/` directory. These definitions are not just documentation -- they are the executable source of truth. The entire platform derives its behavior from them.

## How It Works

At startup (and on every Git sync), the schema engine loads all YAML files from the configured schema directories, parses them into typed Pydantic models (`NodeTypeDefinition`, `EdgeTypeDefinition`, `MixinDefinition`, `EnumTypeDefinition`), and registers them in the `SchemaRegistry`. The registry is the single in-memory authority that every other component consults.

## The Generation Pipeline

Once the registry is populated, the `GenerationEngine` reads it and produces a complete set of derived artifacts:

1. **MCP tool definitions** -- CRUD and search tools for every exposed node and edge type, with authorization metadata attached. These tools allow LLMs and external agents to interact with the graph programmatically.
2. **Agent capabilities** -- Higher-level semantic actions (e.g., "onboard a device", "decommission a location") built on top of the MCP tools, with safety boundaries.
3. **Validation rules** -- Attribute type checks, required field enforcement, enum validation, regex patterns, range constraints, and network type validation (IP, CIDR, MAC).
4. **Observability rules** -- Health checks, freshness alerts, orphan detection, and count thresholds derived from the `health` section of each type.
5. **Policy artifacts** -- RBAC resource definitions, tool authorization rules, field visibility rules, and agent boundary enforcement.

Every generated artifact is deterministic. The engine computes a schema version hash from the set of node types, edge types, and their attributes. If the schema has not changed, the output is identical. If it has changed, the engine can diff the previous manifest against the current one to show exactly what was added or removed.

## What This Means in Practice

You never write API endpoints, validation logic, permission checks, or AI tool definitions by hand. You write a YAML file that describes a node type or edge type, and the platform generates everything else. Add a new `status` enum value to `Device`, and the API filter, the UI dropdown, the MCP tool parameter schema, and the validation rule all update automatically.

The schema is code. Commit it to Git, review it in a pull request, and deploy it like any other configuration change.
