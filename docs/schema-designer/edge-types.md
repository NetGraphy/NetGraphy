---
title: "Defining Edge Types"
slug: "schema-designer-edge-types"
summary: "How to define relationships between node types, including cardinality, constraints, attributes, and traversal configuration."
category: "Schema Designer"
tags: [schema, edge-types, relationships, cardinality, yaml]
status: published
---

# Defining Edge Types

Edges are first-class citizens in NetGraphy. They are not foreign keys or join tables -- they are typed, constrained, and can carry their own attributes. Every relationship in the graph is defined by an edge type in YAML with `kind: EdgeType`.

## Structure

An edge type declares which node types it connects, the cardinality of the relationship, optional constraints, optional attributes on the edge itself, and configuration for the API, graph visualization, and query engine.

## Examples

### LOCATED_IN -- Many Devices to One Location

```yaml
kind: EdgeType
version: v1
metadata:
  name: LOCATED_IN
  display_name: "Located In"
  description: "Device is located at a physical location"
  category: Organization

source:
  node_types: [Device]

target:
  node_types: [Location]

cardinality: many_to_one
inverse_name: HOSTS_DEVICE

attributes:
  rack_position:
    type: integer
    required: false
    description: "Rack unit position (if target is a rack)"
  rack_face:
    type: enum
    enum_values: [front, rear]
    required: false

constraints:
  unique_source: true

graph:
  style: dashed
  color: "#F59E0B"
  show_label: false

api:
  exposed: true

query:
  traversable: true
  query_alias: located_in
  supports_existence_filter: true
  supports_count_filter: true
```

### HAS_INTERFACE -- One Device to Many Interfaces

```yaml
kind: EdgeType
version: v1
metadata:
  name: HAS_INTERFACE
  display_name: "Has Interface"
  description: "A device has a physical or logical interface"
  category: Infrastructure

source:
  node_types: [Device]

target:
  node_types: [Interface]

cardinality: one_to_many
inverse_name: INTERFACE_OF

attributes:
  slot_position:
    type: integer
    required: false
    description: "Physical slot/bay position"

constraints:
  unique_target: true

graph:
  style: solid
  color: "#94A3B8"
  show_label: false

api:
  exposed: true

query:
  traversable: true
  query_alias: has_interface
  supports_existence_filter: true
  supports_count_filter: true
```

## Section Reference

### source and target

Each section contains a `node_types` list specifying which node types are allowed on that side of the relationship. An edge can support multiple source or target types (e.g., `source.node_types: [Device, VirtualMachine]`), allowing a single edge type to represent a polymorphic relationship.

### cardinality

Controls how many edges of this type a node can have. The four supported values are:

- **one_to_one** -- Each source node connects to at most one target, and each target connects to at most one source.
- **one_to_many** -- Each source node can connect to many targets, but each target connects to at most one source.
- **many_to_one** -- Each source node connects to at most one target, but each target can connect to many sources.
- **many_to_many** -- No restrictions on either side.

Cardinality is enforced in the application layer when edges are created or modified.

### inverse_name

Defines the name used when traversing the relationship in reverse. For `LOCATED_IN` with `inverse_name: HOSTS_DEVICE`, querying from a Location back to its devices uses `HOSTS_DEVICE` as the alias.

### attributes

Edges can carry their own attributes, just like nodes. In the `LOCATED_IN` example, `rack_position` and `rack_face` store placement details that belong to the relationship itself, not to either the device or the location.

### constraints

- **unique_source** -- Each source node can have at most one edge of this type. In `LOCATED_IN`, this means a device can be in exactly one location.
- **unique_target** -- Each target node can have at most one edge of this type. In `HAS_INTERFACE`, this means an interface belongs to exactly one device.
- **min_count / max_count** -- Optional bounds on the total number of edges of this type per source node.

### graph, api, query

These sections mirror their node type counterparts. `graph` controls edge rendering style, color, and label visibility. `api.exposed` determines whether the edge is accessible through the REST API. `query` configures traversal, filtering by existence or count, and the alias used in query builder paths.
