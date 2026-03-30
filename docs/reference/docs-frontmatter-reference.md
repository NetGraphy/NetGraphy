---
title: "Documentation Frontmatter Reference"
slug: "docs-frontmatter-reference"
summary: "Supported frontmatter fields for NetGraphy documentation pages"
category: "Reference"
tags: [docs, frontmatter, reference]
status: published
---

# Documentation Frontmatter Reference

Every documentation page in NetGraphy uses YAML frontmatter to declare metadata. This metadata drives navigation, search, knowledge graph relationships, and plugin attribution.

## Required Fields

| Field | Type | Description |
|---|---|---|
| `title` | string | Page title displayed in navigation and headings |
| `slug` | string | URL-safe identifier, unique within the docs tree |
| `summary` | string | One-line description shown in search results and tooltips |
| `category` | string | Top-level section (e.g., "Core Concepts", "AI Assistant") |
| `status` | string | `published`, `draft`, or `deprecated` |

## Optional Fields

| Field | Type | Description |
|---|---|---|
| `tags` | list[string] | Searchable tags for filtering and discovery |
| `version` | string | Platform version this page applies to |
| `plugin` | string | Plugin name if this page belongs to a plugin |
| `generated` | boolean | Whether this page was auto-generated from schema |
| `source_repo` | string | GitHub repo this page originates from |
| `source_path` | string | File path within the source repo |
| `related_schema_items` | list[string] | Schema node/edge types this page documents |
| `related_tools` | list[string] | MCP tool names this page references |
| `related_capabilities` | list[string] | Agent capability names this page references |
| `screenshot_groups` | list[string] | Screenshot directory groups used in this page |

## Example

```yaml
---
title: "Device Node Type"
slug: "device-node-type"
summary: "Reference documentation for the Device node type"
category: "Reference"
tags: [device, infrastructure, node-type]
status: published
version: "1.0"
generated: true
related_schema_items: [Device, HAS_INTERFACE, LOCATED_IN]
related_tools: [query_devices, create_device, count_devices]
screenshot_groups: [schema-designer, graph-operations]
---
```

## Knowledge Graph Integration

Frontmatter fields are parsed into the documentation knowledge graph:

- `related_schema_items` → creates `DOCUMENTS` edges between the doc page and schema nodes
- `related_tools` → creates `REFERENCES_TOOL` edges
- `related_capabilities` → creates `REFERENCES_CAPABILITY` edges
- `plugin` → creates `BELONGS_TO_PLUGIN` edge
- `tags` → indexed for keyword search and filtering
