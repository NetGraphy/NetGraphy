---
title: "Edges"
slug: "edges"
summary: "Typed, directional relationships between nodes — first-class graph citizens with properties, cardinality, and constraints."
category: "Core Concepts"
tags: [graph, schema, relationships, data-model]
status: published
---

# Edges

In NetGraphy, an **edge** is a typed, directional relationship between two nodes. Edges are not foreign keys or join tables — they are first-class objects in the graph with their own properties, constraints, health rules, and permissions. The way a device connects to a location, an interface belongs to a device, or a circuit originates from a provider is modeled explicitly as an edge.

## Why Edges Are First-Class

In relational systems, relationships are implicit — a `device_id` column on an interface table implies ownership, but the relationship itself has no identity, no attributes, and no constraints beyond a foreign key. In NetGraphy, the `HAS_INTERFACE` edge between a `Device` and an `Interface` is a named, schema-defined object. It can carry properties (like `position` or `installed_date`), enforce cardinality rules, participate in health checks, and be independently secured with permissions.

This matters because network infrastructure is fundamentally about connections. A cable between two interfaces, a circuit from a provider, a device in a rack at a site — these relationships carry meaning that flat tables cannot express.

## Edge Type Definitions

Every edge type is defined as an `EdgeTypeDefinition` in YAML schema. The definition specifies:

- **Source and target** — Which node types can appear on each end. An `EdgeSourceTarget` lists allowed `node_types` for each direction. A single edge type can connect multiple source/target type combinations.
- **Cardinality** — One of `one_to_one`, `one_to_many`, `many_to_one`, or `many_to_many`. NetGraphy enforces cardinality at the application layer during create and connect operations.
- **Attributes** — Edges can carry their own properties. A `CONNECTED_TO` edge between interfaces might store `cable_type`, `cable_id`, and `speed`. These attributes are validated against the schema like node attributes.
- **Constraints** — `unique_source`, `unique_target`, `min_count`, and `max_count` provide fine-grained control beyond cardinality. For example, a `PRIMARY_ADDRESS` edge might enforce `unique_source` so a device can have only one.
- **Inverse name** — An optional human-readable name for the reverse direction (e.g., `LOCATED_IN` has inverse `CONTAINS`).

## Common Edge Types

- **LOCATED_IN** — Device to Location. Cardinality: `many_to_one` (many devices at one location).
- **HAS_INTERFACE** — Device to Interface. Cardinality: `one_to_many` (one device, many interfaces).
- **CONNECTED_TO** — Interface to Interface. Cardinality: `one_to_one` (point-to-point link). Attributes: cable type, cable ID.
- **CIRCUIT_FROM_PROVIDER** — Circuit to Provider. Cardinality: `many_to_one`.
- **PARENT_OF** — Location to Location. Enables hierarchical site modeling (region > site > building > floor > rack).
- **ASSIGNED_TO** — Prefix to VLAN or Interface. Tracks IP address assignment.

## Cardinality Enforcement

Cardinality is enforced at the repository layer before edges reach the database. When creating a `one_to_one` edge, the system checks that neither the source nor the target already has an edge of that type. Violations produce clear validation errors rather than silent data corruption.
