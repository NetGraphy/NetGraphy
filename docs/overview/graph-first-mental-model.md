---
title: "Graph-First Mental Model"
slug: "graph-first-mental-model"
summary: "How to think about network infrastructure as a graph instead of a collection of tables."
category: "Overview"
tags: [graph, mental-model, neo4j, topology, relationships]
status: published
---

# Graph-First Mental Model

If you have used NetBox, Nautobot, or a CMDB backed by a relational database, you are accustomed to thinking in tables. Devices live in one table. Interfaces live in another. A foreign key on the interface row points back to the device. To find out what a switch is connected to, you join interfaces to cables to interfaces to devices, assembling the topology in application code.

NetGraphy works differently. There are no tables. There are nodes and edges.

## Nodes Are Objects

A node is any discrete object in your network: a device, an interface, a location, a prefix, a circuit, a vendor, a VLAN. Each node has a type (its label) and a set of properties. A Device node might have properties like `hostname`, `management_ip`, `status`, and `role`. A Location node might have `name`, `location_type`, `city`, and `country`.

This is broadly similar to a row in a table, with one critical difference: a node exists independently. It is not defined by its table membership. It is an entity in a graph, and its meaning comes from what it is connected to.

## Edges Are Relationships

An edge connects two nodes and has a type and direction. A Device node connects to a Location node via a `LOCATED_IN` edge. A Device connects to an Interface via `HAS_INTERFACE`. Two Interfaces connect via `CONNECTED_TO`. A Circuit connects to a Provider via `PROVIDED_BY`.

Edges are not second-class join records. They are first-class objects with their own properties. A `LOCATED_IN` edge can carry `rack_position` and `rack_face`. A `CONNECTED_TO` edge can carry `cable_type` and `cable_length`. This is important: in a relational model, putting attributes on a many-to-many relationship requires a junction table with extra columns. In a graph, properties on edges are native.

## Traversal Replaces Joins

In a relational system, answering "show me every device at the Dallas site and all their interfaces" requires joining the device table to the location table (filtering on name), then joining to the interface table. Each hop is another join clause.

In a graph, the same question is a traversal: start at the Location node where `name = 'Dallas'`, follow `LOCATED_IN` edges inward to find all Device nodes, then follow `HAS_INTERFACE` edges outward to find all Interface nodes. The query follows the same path your mind follows when you think about the question. There is no impedance mismatch between the question and the data model.

## Topology Is Native

The most important consequence of graph-first modeling is that topology is not something you reconstruct from data. It is the data. The physical connectivity of your network -- which port on which device is cabled to which port on which other device -- is stored as actual edges between actual nodes. You do not need to query a cable table and then look up both endpoints. The graph already encodes the path.

This means questions like "what is the Layer 1 path between these two devices?" or "if this switch fails, what downstream devices lose connectivity?" are graph traversal problems with well-known algorithms. You are not writing application logic to simulate graph operations on top of a relational database. You are running graph operations on a graph.

## Why This Matters for Network Engineers

Network engineers already think in graphs. A network diagram is a graph. A routing topology is a graph. A cabling plan is a graph. The gap between how you think about your network and how a traditional source of truth stores it has always been a source of friction. NetGraphy closes that gap. The data model in the database matches the mental model in your head.

When you ask "what is connected to this device?" in NetGraphy, the answer is a single traversal hop. When you ask "what is the full path between these two endpoints?" the answer is a shortest-path query. When you ask "what depends on this circuit?" the answer is a subgraph. These are not features bolted on to a relational core. They are the natural operations of the system you are using.
