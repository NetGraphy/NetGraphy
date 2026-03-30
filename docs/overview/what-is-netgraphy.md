---
title: "What Is NetGraphy?"
slug: "what-is-netgraphy"
summary: "NetGraphy is a graph-native network source of truth that models infrastructure as nodes and edges instead of rows and tables."
category: "Overview"
tags: [overview, introduction, graph, source-of-truth]
status: published
---

# What Is NetGraphy?

NetGraphy is a network source of truth built on a graph database. It stores your infrastructure -- devices, interfaces, cables, circuits, IP addresses, locations, providers, and every relationship between them -- as nodes and edges in Neo4j rather than rows in a relational database.

This is not a cosmetic difference. In a table-first system like NetBox or Nautobot, answering "what is connected to this switch?" requires joining across multiple tables, traversing foreign key chains, and assembling the answer in application code. In NetGraphy, that question is a single graph traversal. The topology is the data model.

## Why It Exists

Network infrastructure is inherently a graph. Devices connect to devices through cables. Interfaces belong to devices. Circuits terminate at locations. Prefixes nest inside other prefixes. BGP sessions peer between routing instances. Every interesting question about a network is a question about relationships, paths, and connectivity.

Relational databases can model this, but they fight it. You end up with dozens of join tables, complex ORM queries, and a data model that obscures the very topology you are trying to represent. NetGraphy starts from the assumption that the graph is the natural structure and builds everything on top of it.

## Schema-Driven Everything

NetGraphy's schema is defined in YAML files. Each file declares a node type or edge type: its attributes, validation rules, UI hints, API behavior, search configuration, and permission model. The platform reads these schemas at startup and generates the full stack from them.

When you add a new YAML schema file for a node type, the system creates the corresponding REST API endpoints, list and detail views in the UI, search indexing, filter controls, form fields, graph visualization rules, and AI assistant tools. There is no code to write for a new object type. The schema is the single source of truth for platform behavior.

## AI-Native

NetGraphy includes a built-in AI assistant that understands your schema and can answer questions about your network using tool calls against the graph. Because the schema is machine-readable and the graph is naturally traversable, the AI runtime can reason about topology, find paths between objects, and surface relationships that would require manual investigation in a traditional system.

## Key Concepts

- **Nodes** represent objects: devices, interfaces, locations, prefixes, circuits, vendors, platforms.
- **Edges** represent relationships: LOCATED_IN, HAS_INTERFACE, CONNECTED_TO, PROVIDES_CIRCUIT, PEERS_WITH.
- **Schemas** are YAML files that define node types, edge types, their attributes, and all platform behavior.
- **Mixins** are reusable attribute sets (like lifecycle timestamps or provenance tracking) that can be applied to any node type.
- **Provenance** tracks the source, timestamp, and method of every piece of ingested data.

## How It Differs from Table-First Systems

| Concern | Table-First (NetBox, Nautobot) | Graph-First (NetGraphy) |
|---|---|---|
| Data model | Rows, columns, foreign keys | Nodes, edges, properties |
| Topology queries | Multi-table joins | Native traversal |
| Schema changes | Database migrations | YAML file update |
| Relationship modeling | Junction tables | First-class edges with attributes |
| New object types | Code + migration + UI work | Single YAML file |
| Connectivity questions | Application logic | Graph queries |

NetGraphy does not aim to replicate NetBox with a different database. It rethinks what a network source of truth looks like when the data model matches the domain.
