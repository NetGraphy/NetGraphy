---
title: "Generated Agent Capabilities"
slug: "generated-capabilities"
summary: "Higher-level semantic actions for AI agents — onboard, decommission, find, modify — built on MCP tools and governed by safety levels."
category: "Core Concepts"
tags: [ai, agent, capabilities, mcp, schema]
status: published
---

# Generated Agent Capabilities

Agent capabilities are higher-level semantic actions that sit on top of MCP tools. Where an MCP tool is a single operation like `create_device`, a capability describes what an agent **can do** in domain terms — "onboard a device," "find orphaned interfaces," or "audit devices by status."

The agent capability generator reads the schema registry and produces a manifest of capabilities organized by category, each referencing the MCP tools it uses.

## Capability Categories

- **CRUD** — `create_<entity>`, `modify_<entity>`, `remove_<entity>`. Wraps the corresponding MCP tools with required input descriptions and example prompts.
- **Search** — `find_<entity>`. Covers listing, searching, and counting. Example prompts: "Show me all devices," "How many locations are there?"
- **Relationship** — `connect_<entity>_to_<target>`, `find_<entity>_<target>_via_<edge>`. Traversal and linking actions. Example: "What interfaces are connected to this device?"
- **Health** — `detect_orphaned_<entity>`, `detect_<entity>_without_<target>`. Generated when the schema defines orphan alerts or required edges. Example: "Find devices without a location."
- **Audit** — `audit_<entity>_by_<field>`. Generated for filterable enum attributes. Example: "How many devices are in each status?"
- **Custom** — Named capabilities declared in the schema's `agent.capabilities` list. Example: declaring `["onboard", "decommission"]` on the Device type generates `device_onboard` and `device_decommission` capabilities.

## Safety Levels

Every capability carries a safety classification:

- **`read`** — No data modification. Search, traversal, health detection, and audit capabilities.
- **`write`** — Creates or modifies data. Create, modify, and connect capabilities.
- **`destructive`** — Deletes data or removes relationships. Remove and disconnect capabilities. These require explicit user confirmation when executed by an agent.

## Example Prompts

Each capability includes pre-generated example prompts that illustrate what natural language requests it handles. These serve as documentation for agent systems and can be used for prompt routing. For a `Device` type with `status` as a filterable enum:

- "Create a new device"
- "Find devices where status is active"
- "Change the status of device router-01"
- "Delete device old-switch-03"
- "Which devices are missing a location?"
- "Show device breakdown by status"

## Schema Control

The `agent` metadata block on each type controls capability generation. Setting `agent.exposed: false` suppresses all capabilities for that type. Setting `agent.sensitive: true` excludes the type from agent tool generation entirely — the agent cannot see or interact with sensitive types unless explicitly allowed. Custom capabilities are declared in `agent.capabilities` as a list of action names.
