---
title: "Nodes"
slug: "nodes"
summary: "Graph objects representing network entities — devices, interfaces, locations, and anything defined in YAML schema."
category: "Core Concepts"
tags: [graph, schema, data-model, neo4j]
status: published
---

# Nodes

In NetGraphy, a **node** is a vertex in the graph database representing a distinct network entity. Every device, interface, location, circuit, prefix, VLAN, and provider is a node. Unlike rows in a relational table, nodes exist in a graph where their relationships to other nodes are as important as their own properties.

## What Makes a Node

Every node has three fundamental characteristics:

- **Label** — The node type, derived from the schema. A node labeled `Device` is an instance of the `Device` type. Labels determine which attributes are valid, which edges can connect, and how the node appears in the UI.
- **Properties** — Key-value attributes defined by the schema. A `Device` node might carry `hostname`, `platform`, `status`, `management_ip`, and `serial_number`. Properties are typed and validated.
- **Identity** — A system-generated unique ID (`id`) plus any user-defined unique fields (like `hostname` for devices). The ID is how edges reference the node internally.

## Defining Node Types in YAML

Every node type is defined as a `NodeTypeDefinition` in YAML. The schema specifies the type's attributes, metadata, permissions, MCP tool exposure, agent capabilities, health rules, and query configuration. There is no hand-written code per model — the generation engine reads the schema and produces everything.

A node type definition includes:

- `metadata` — Name, display name, description, icon, color, category, and tags. These drive navigation, search grouping, and graph visualization.
- `attributes` — A dictionary of `AttributeDefinition` entries, each with a type, constraints, and UI/query/health metadata.
- `mixins` — References to reusable attribute groups (like a `Timestamped` mixin that adds `created_at` and `updated_at`).
- `permissions` — Default read, write, and delete roles.
- `mcp`, `agent`, `health`, `query` — Metadata blocks that control what the generation engine produces for this type.

## Common Node Types

Typical NetGraphy deployments define node types for:

- **Device** — Routers, switches, firewalls. Carries hostname, platform, role, status, management IP.
- **Interface** — Physical and logical ports. Carries name, type, speed, MTU, MAC address, operational state.
- **Location** — Sites, buildings, floors, racks. Hierarchical via `PARENT_OF` edges.
- **Circuit** — WAN links, point-to-point connections. Carries circuit ID, bandwidth, provider reference.
- **Prefix** — IP prefixes (CIDR notation). Carries network address, VLAN assignment, role.
- **Provider** — ISPs and service providers. Carries name, ASN, account number.

These are not hardcoded — they exist because YAML files define them. You can add, remove, or modify node types by editing schema files and reloading the registry.

## How Nodes Map to the Graph

In Neo4j, each node becomes a labeled node with properties stored directly on it. The schema registry validates properties on create and update, ensuring every node conforms to its type definition before it reaches the database.
