---
title: "Extending Generated Capabilities"
slug: "plugins-extensions-extending-generated-capabilities"
summary: "Schema extensions automatically produce new MCP tools, agent capabilities, API endpoints, validation rules, and observability checks."
category: "Plugins and Extensions"
tags: [schema, generation, mcp, tools, api, validation]
status: published
---

# Extending Generated Capabilities

When you add a new schema file, the generation engine does not just register a type. It produces the full set of platform capabilities for that type, identical in scope to what core types receive. There is no distinction between a built-in type and a plugin-contributed type once it is loaded into the registry.

## MCP Tools

Each new node type generates the standard tool set: `query_`, `find_by_`, `count_`, `create_`, `update_`, `delete_`, and `connect_`/`disconnect_` for each edge type referencing it. The tool parameters are derived from the type's attribute definitions, including types, constraints, required fields, and enum choices. These tools appear in the AI assistant's context immediately.

## Agent Capabilities

The `agent` metadata block in the schema controls how the assistant reasons about the type. It can include description hints, example questions, and relationship guidance that help the LLM understand when and how to use the type's tools. Plugin authors can tune this metadata to improve the assistant's accuracy for domain-specific types.

## API Endpoints

The REST API generation engine produces CRUD endpoints, list endpoints with filtering and pagination, and relationship traversal endpoints for each new type. These endpoints follow the same URL conventions and response formats as core types.

## Validation Rules

Attribute constraints defined in the schema -- `required`, `unique`, `min_length`, `max_length`, `pattern`, `choices` -- become validation rules enforced on create and update operations. The validation layer does not differentiate between core and plugin types.

## Observability

If the schema includes a `health` metadata block, the observability engine generates health checks, freshness monitors, and attribute constraint monitors for the new type. These appear in the system health dashboard alongside core type checks. See [Extending Validation and Observability](extending-validation-and-observability.md) for details.
