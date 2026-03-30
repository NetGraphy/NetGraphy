---
title: "Generated Capability Reference"
slug: "generated-capability-reference"
summary: "Reference for agent capabilities auto-generated from schema"
category: "Reference"
tags: [agent, capabilities, reference]
status: published
---

# Generated Capability Reference

Agent capabilities are higher-level semantic actions generated from the schema. While MCP tools are low-level operations (create, query, connect), capabilities represent meaningful workflows that an agent can perform.

## Capability Types

| Type | Description | Example |
|---|---|---|
| `crud` | Basic object management | "Create a new device", "Find a location" |
| `relationship` | Connect or traverse objects | "Connect device to location", "Find related interfaces" |
| `traversal` | Multi-hop graph exploration | "Trace circuit path", "Find devices via location hierarchy" |
| `health` | Detect problems | "Find orphaned devices", "Check for stale data" |
| `audit` | Track changes | "Show recent changes to device" |

## Capability Structure

Each generated capability includes:

- **display_name** — Human-readable name (e.g., "Find Devices")
- **description** — What the capability does
- **backing_tools** — The MCP tools that implement this capability
- **required_inputs** — What the agent needs to invoke it
- **example_prompts** — Example user messages that trigger this capability
- **safety_level** — `read`, `write`, or `destructive`

## Safety Levels

| Level | Behavior |
|---|---|
| `read` | No data modification. Agent can execute freely. |
| `write` | Creates or modifies data. Agent proceeds with user's write permission. |
| `destructive` | Deletes data or removes relationships. Agent asks for confirmation. |

## Viewing Capabilities

Browse at **Admin > Generated Artifacts > Agent Capabilities** or via API:

```
GET /api/v1/generated/agent-capabilities
GET /api/v1/generated/agent-capabilities?category=crud
```
