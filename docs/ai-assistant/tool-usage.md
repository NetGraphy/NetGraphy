---
title: "Tool Usage"
slug: "ai-assistant-tool-usage"
summary: "How the AI assistant uses schema-generated MCP tools to query, mutate, and traverse graph data."
category: "AI Assistant"
tags: [ai, tools, mcp, filters, query, schema]
status: published
---

# Tool Usage

The AI assistant interacts with the NetGraphy graph exclusively through MCP tools generated from the schema. It does not execute raw queries or bypass the repository layer. Every operation -- reading, writing, connecting, disconnecting -- goes through a typed tool with validated parameters.

## Tool Categories

Each node type in the schema produces up to seven tool prefixes:

- **`query_`** -- Retrieve a filtered list of nodes. Supports pagination, sorting, and structured filters. Example: `query_device` returns devices matching the provided criteria.
- **`find_by_`** -- Look up a single node by its unique field (typically `hostname`, `name`, or `circuit_id`). Returns one result or nothing.
- **`count_`** -- Return the count of nodes matching a filter without fetching full records. Useful for aggregation questions like "how many active routers are there?"
- **`create_`** -- Create a new node with validated attributes. The tool schema enforces required fields and type constraints.
- **`update_`** -- Modify attributes on an existing node, identified by ID or unique field.
- **`delete_`** -- Remove a node and its associated edges. Subject to destructive action confirmation policy.
- **`connect_` / `disconnect_`** -- Create or remove edges between nodes. Parameter schemas include source and target identifiers plus any edge attributes defined in the schema.

## Filter Path Syntax

Tools that accept filters use a dot-separated path syntax to express relationship traversals. Instead of matching on flat attributes alone, the assistant can filter through edges.

For example, to find devices at a specific location, the filter path `located_in.Location.city` tells the query engine to traverse the `LOCATED_IN` edge to a `Location` node and match on its `city` attribute. This is how the assistant answers "show me devices in Dallas" without searching for the string "Dallas" on device nodes.

## Structured Filters vs. Flat Parameters

Simple queries use flat parameters: `query_device(status="active", role="router")`. When the question involves relationships, the assistant constructs structured filter objects:

```json
{
  "filters": {
    "located_in.Location.city": "Dallas",
    "status": "active"
  }
}
```

The tool execution layer translates these structured filters into graph traversal operations through the repository layer.

## Tool Selection and Scoring

A fully loaded schema can produce hundreds of tools. LLM context windows have finite capacity, so the assistant runtime scores and selects tools based on the current conversation context. The scoring considers the object types mentioned in the user's message, recent tool call history, and schema-defined relevance hints. Only the highest-scoring tools are included in the LLM context for a given turn. This keeps the tool set focused and avoids overwhelming the model with irrelevant options.

Tools that are filtered out by scoring are not permanently hidden. If the conversation shifts to a different domain, the tool set is re-scored on the next turn and the relevant tools surface automatically.
