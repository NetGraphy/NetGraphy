---
title: "Plugins and Extensions Overview"
slug: "plugins-extensions-overview"
summary: "NetGraphy's extension model lets you add new node types, edge types, parsers, and documentation by contributing YAML schema files -- no Python required."
category: "Plugins and Extensions"
tags: [plugins, extensions, schema, yaml, customization]
status: published
---

# Plugins and Extensions Overview

NetGraphy is designed to be extended through schema, not code. The same YAML-driven architecture that powers the core platform is the extension mechanism. Adding a new object type, relationship, validation rule, or AI tool does not require writing Python, modifying application code, or deploying custom packages. You add YAML files, and the platform generates everything from them.

## What a Plugin Is

A NetGraphy plugin is a collection of YAML schema files, documentation, parsers, and mappings organized in a Git repository. At its simplest, a plugin is a single YAML file that defines a new node type. At its most complete, it includes:

- **Schema files** -- Node type and edge type definitions placed in the repository's `schemas/` directory.
- **Parsers** -- TextFSM or other parser templates for ingestion pipelines.
- **Mappings** -- Declarative YAML files that map parsed data to graph operations.
- **Documentation** -- Markdown files with frontmatter describing the plugin's contributed types and usage.

## No Code Required

For basic extensions, you never leave YAML. Define a node type with its attributes, validation rules, and metadata. Place the file in `content/schemas/` (for local extensions) or in a plugin repository's `schemas/` directory. The platform discovers it on startup and generates the REST API endpoints, UI views, search indexing, filter controls, form fields, MCP tools, and agent capabilities automatically.

## Plugin Repositories

Plugins can live in separate Git repositories and be synced into the platform via the GitSync engine. This keeps custom extensions version-controlled, reviewable, and independent of the core platform release cycle. Multiple plugin repositories can contribute to the same NetGraphy instance, each adding their own types without conflicting with each other or with core schema files.

## What Gets Generated

When a plugin contributes a new schema file, the generation engine produces:

- API endpoints (CRUD, filtering, pagination)
- UI list and detail views
- MCP tools for the AI assistant
- Validation rules and constraints
- Search index configuration
- Graph visualization rules

The specifics of each generated capability are covered in the following pages.
