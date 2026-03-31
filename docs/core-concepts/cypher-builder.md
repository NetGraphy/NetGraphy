---
title: "Cypher Builder"
slug: "cypher-builder"
summary: "Visual graph query builder with live Cypher generation, path traversal, and graph visualization"
category: "Core Concepts"
tags: [cypher, query, graph, path, visualization]
status: published
related_tools: [query_devices, count_devices]
screenshot_groups: [cypher-builder]
---

# Cypher Builder

The Cypher Builder is a visual graph query construction interface at `/query/builder`. It lets you compose Cypher queries by assembling node patterns, relationships, filters, and return fields through form controls rather than writing query text by hand. The generated Cypher updates in real time as you make changes, and you can execute queries directly against Neo4j with results rendered in table, graph, or JSON format.

This page covers every section of the interface, the query generation rules, and a complete walkthrough of the MAC-to-MAC path discovery workflow.

## Interface Layout

The page is split into two main regions:

- **Left panel (380px)** -- The pattern builder. Contains all controls for constructing the query: templates, query mode, path settings, parameters, node patterns, relationships, filters, return fields, sort, and pagination.
- **Right panel (remaining width)** -- The generated Cypher displayed in a read-only Monaco editor with syntax highlighting at the top, and a results area below with Table, Graph, and JSON tabs.

A toolbar at the top of the left panel provides the primary actions: **+ Node**, **+ Relationship**, **Reset**, and **Saved**.

## Templates

Six one-click starter patterns populate the builder with pre-configured nodes, relationships, filters, and return fields. Click any template to replace the current builder state entirely.

| Template | Description | Mode |
|---|---|---|
| **Devices by Site** | `MATCH (d:Device)-[:LOCATED_IN]->(s:Location)` returning hostname, status, role, site name, and city. Limit 50. | Pattern |
| **Sites w/o Devices** | `MATCH (s:Location) OPTIONAL MATCH (s)<-[:LOCATED_IN]-(d:Device) WHERE d.id IS NULL` returning site name and city. Identifies locations with no devices attached. | Pattern |
| **Count by City** | `MATCH (d:Device)-[:LOCATED_IN]->(s:Location)` returning `s.city` and `count(d)` ordered by count descending. | Pattern |
| **Circuits by Provider** | `MATCH (c:Circuit)-[:CIRCUIT_FROM_PROVIDER]->(p:Provider)` returning provider name and `count(c)` ordered by count descending. | Pattern |
| **MAC-to-MAC Path** | Shortest path between two MACAddress nodes. Traverses MAC_ON_INTERFACE, HAS_INTERFACE, CONNECTED_TO, CIRCUIT_HAS_TERMINATION, and TERMINATION_CONNECTED_TO with a 30-hop limit. Requires two parameters: source MAC and destination MAC. | Shortest Path |
| **Device Neighbors** | Shortest path from a named device to all other Device nodes within 4 hops across HAS_INTERFACE and CONNECTED_TO edges. Requires a hostname parameter. | Shortest Path |

Templates are the fastest way to learn the builder. Load one, study what it populates, then modify it.

## Query Mode

Three modes control the shape of the generated Cypher:

- **Pattern Match** -- Standard `MATCH`/`WHERE`/`RETURN` Cypher. You define node patterns and explicit relationships, add filters, and choose return expressions. This is the default mode for most queries.
- **Shortest Path** -- Generates a `shortestPath()` call. You define two endpoint nodes and configure which relationship types to traverse and the maximum hop depth. The builder produces the correct inline relationship type syntax that Neo4j requires for shortestPath.
- **All Paths** -- Identical to Shortest Path but uses `allShortestPaths()` to return every equally-short path between the endpoints.

Click the mode buttons to switch. The builder adapts its controls: in path modes, the Path Settings section appears; in pattern mode, the full relationship builder is available.

## Path Mode Settings

Visible only when Shortest Path or All Paths is selected. These controls configure the variable-length path traversal.

**Max hops** -- An integer input (default 15, configurable up to 50). This becomes the `*..N` depth limit in the generated Cypher. The MAC-to-MAC template sets this to 30; the Device Neighbors template uses 4.

**Allowed relationship types** -- A searchable checkbox list populated from every edge type in the loaded schema. Type into the filter input to narrow the list (for example, typing "inter" shows HAS_INTERFACE, MAC_ON_INTERFACE, and any other type containing that substring). Check the types you want the path to traverse. Selected types appear in the generated Cypher as `[:TYPE1|TYPE2*..N]` inside the path pattern. If no types are selected, the path traverses all relationship types.

Relationship types go inline in the shortestPath pattern rather than in a WHERE clause because Neo4j requires this syntax for shortestPath queries.

## Parameters

When the current query model defines parameters (the MAC-to-MAC and Device Neighbors templates do), an amber-highlighted section appears below the path settings. Each parameter shows:

- **Name** -- The internal `$param_name` used in the Cypher.
- **Label** -- A human-readable name displayed next to the input.
- **Type** -- string, integer, boolean, or enum.
- **Required** -- Marked with an asterisk (*). The Execute button validates that all required parameters have values before sending the query.
- **Default value** -- Pre-filled if the parameter definition provides one.

Values entered here are passed to Neo4j as query parameters using the `$param_name` syntax. This means values are never string-interpolated into the Cypher text -- they use Neo4j's native parameterized query mechanism, which is both safer and faster.

## Node Patterns

Click **+ Node** to open the add-node dialog. Each node pattern has:

- **Alias** -- A short variable name (e.g., `d`, `s`, `src`). The builder auto-generates sequential aliases (`n0`, `n1`, ...) but you can type any alias. This alias is used throughout the rest of the builder to reference the node in relationships, filters, and return fields.
- **Label** -- Selected from a dropdown of all node types loaded from the schema (Device, Interface, Location, Circuit, Provider, MACAddress, etc.). The label becomes the `:Label` in the Cypher pattern.
- **MATCH type** -- Either MATCH or OPTIONAL MATCH. OPTIONAL MATCH nodes produce patterns that return null when no match exists, which is how the "Sites w/o Devices" template finds empty locations.
- **MATCH-level properties** -- Displayed as `{field: $param}` below the alias. These are properties embedded directly in the MATCH pattern (as opposed to WHERE filters). They are used with parameterized queries -- for example, `(src:MACAddress {address: $src_mac})`.

Click the **x** button on any node pattern to remove it. Removing a node also removes all relationships that reference it.

## Relationships

Click **+ Relationship** to add an edge pattern connecting two nodes. Each relationship has:

- **From node** -- Dropdown of existing node aliases.
- **To node** -- Dropdown of existing node aliases.
- **Edge type** -- Dropdown of all edge types from the schema (LOCATED_IN, HAS_INTERFACE, CONNECTED_TO, CIRCUIT_FROM_PROVIDER, etc.).
- **Direction** -- Outgoing (`-[]->`), Incoming (`<-[]-`), or Undirected (`-[]-`).
- **Variable-length hops** -- Optional min and max hop values. When set, the relationship becomes `*min..max` in the Cypher, enabling multi-hop traversals.
- **MATCH type** -- MATCH or OPTIONAL MATCH, matching the same semantics as node patterns.

Relationships are rendered in the generated Cypher as part of the MATCH clause, connecting the from and to node expressions with the appropriate arrow syntax.

## Filters

Click **+ Add** in the Filters section. Each filter targets a specific node alias and applies a condition in the WHERE clause.

- **Target alias** -- Which node the filter applies to. Select from the dropdown of existing aliases.
- **Field** -- A typeahead input that searches the attributes of the selected node type. Type to filter (e.g., type "host" to see `hostname`, `host_id`, etc.).
- **Operator** -- A dropdown with 13 operators:

| Operator | Cypher Output |
|---|---|
| = | `alias.field = value` |
| != | `alias.field <> value` |
| CONTAINS | `alias.field CONTAINS value` |
| STARTS WITH | `alias.field STARTS WITH value` |
| ENDS WITH | `alias.field ENDS WITH value` |
| > | `alias.field > value` |
| >= | `alias.field >= value` |
| < | `alias.field < value` |
| <= | `alias.field <= value` |
| IN | `alias.field IN value` |
| IS NULL | `alias.field IS NULL` |
| IS NOT NULL | `alias.field IS NOT NULL` |
| =~ (regex) | `alias.field =~ value` |

- **Value** -- A text input for the comparison value. Numeric and boolean values are emitted without quotes; strings are quoted. If the filter's `isParameter` flag is set, the value is treated as a parameter name and emitted as `$value`.

Multiple filters are joined with AND. Each filter can belong to a logical group for AND/OR composition.

## Return Fields

Click **+ Add** to add a return expression. Each entry has:

- **Expression** -- A typeahead input. Type `d.` to see all Device attributes (d.hostname, d.status, d.role, etc.). Type `count` to see aggregate suggestions like `count(d)`. Type `path` for path return. Selecting a suggestion auto-fills the alias.
- **Alias** -- The output column name. Populated automatically from the suggestion but editable. In the generated Cypher this becomes `expression AS alias`.
- **Aggregate flag** -- Marks the field as an aggregate expression. When present, non-aggregate return fields become implicit GROUP BY targets.

If no return fields are specified, the builder defaults to returning all node aliases used in the pattern.

## Sort and Pagination

- **DISTINCT** -- A checkbox that adds the `DISTINCT` keyword to the RETURN clause.
- **Limit** -- An integer input (default 25). Adds `LIMIT N` to the generated Cypher.
- **Skip** -- An integer input (default 0). Adds `SKIP N` when greater than zero.
- **Sort fields** -- Configurable field/direction pairs that produce the `ORDER BY` clause.

## Generated Cypher Panel

The right side of the page displays the generated Cypher in a Monaco editor instance configured as read-only with Cypher syntax highlighting. The query text updates in real time as you modify any setting in the builder.

A **Copy** button in the top-right corner of the editor copies the current Cypher to the clipboard with visual feedback ("Copied!" for two seconds).

The Cypher generation follows these rules:

- **Pattern mode**: `MATCH (alias:Label {prop: $param})-[rel:TYPE]->(alias2:Label) WHERE conditions RETURN fields ORDER BY sort SKIP n LIMIT n`
- **Path mode**: First `MATCH` both endpoint nodes with their labels and MATCH-level properties, then `MATCH path = shortestPath((a)-[:TYPE1|TYPE2*..N]-(b))`, followed by optional WHERE, RETURN, and LIMIT clauses.
- Relationship types in path mode always go inline in the pattern, never in a WHERE ALL predicate. This is because Neo4j's shortestPath implementation requires relationship type constraints to be specified in the pattern itself.
- MATCH-level properties use `$param` syntax for parameterized queries.
- OPTIONAL MATCH patterns are emitted as separate clauses from regular MATCH patterns.

## Execution and Results

Click **Execute** to run the generated Cypher against Neo4j. The button validates that all required parameters have values before sending the query. During execution, the button shows a loading state.

After execution, the results area displays:

- **Row count** and **execution time** in the header.
- **Three result tabs**:

**Table** -- Column headers derived from the return field aliases, with rows of data. This is the default view for pattern queries that return scalar fields.

**Graph** -- A full GraphCanvas visualization. When query results contain graph nodes (returned from `path`, full node objects, or relationship traversals), the Graph tab renders an interactive topology diagram. Features include:
- Color-coded node types (MACAddress, Interface, Device, Circuit Termination, Circuit, etc.)
- Labeled edge types (On Interface, Connected To, Has Interface, Has Termination, etc.)
- Hierarchical layout and Force-directed layout toggle
- Node type filter checkboxes to show/hide specific types
- Edge type filter checkboxes to show/hide specific relationships
- Zoom, pan, and click-to-select interactions

The builder auto-switches to the Graph tab when results contain graph nodes.

**JSON** -- The raw result data as returned by the API, formatted for inspection.

## Save and Load

Enter a query name in the toolbar input and click **Save**. The query model (not just the Cypher text, but the full visual builder state) is persisted to the server. Saved queries appear in the Query Workbench sidebar and can be loaded back into the builder by clicking them. Click **x** on a saved query to delete it.

Because the full `VisualQueryModel` is saved (nodes, relationships, filters, return fields, parameters, mode, path settings), loading a saved query restores the builder to the exact state it was in when saved -- not just the Cypher output.

## Walkthrough: MAC-to-MAC Path Discovery

This walkthrough demonstrates the most complex builder scenario: finding the full network path between two MAC addresses.

![Cypher Builder](../assets/screenshots/cypher-builder/mac-to-mac-path.png)

**Step 1: Load the template.** Click the **MAC-to-MAC Path** template button. The builder populates with:
- Two node patterns: `src:MACAddress` with `{address: $src_mac}` and `dst:MACAddress` with `{address: $dst_mac}`.
- Query mode set to Shortest Path.
- Path depth limit of 30 hops.
- Five allowed relationship types: MAC_ON_INTERFACE, HAS_INTERFACE, CONNECTED_TO, CIRCUIT_HAS_TERMINATION, TERMINATION_CONNECTED_TO.
- Two required parameters: Source MAC and Destination MAC.
- Return field: `path`.
- Limit: 5.

**Step 2: Enter parameters.** In the amber Parameters section, fill in:
- Source MAC: `03:7B:D9:D9:CE:A4`
- Destination MAC: `03:AD:A3:1F:E5:FA`

**Step 3: Review the generated Cypher.** The Monaco editor shows:

```cypher
MATCH (src:MACAddress {address: $src_mac}), (dst:MACAddress {address: $dst_mac})
MATCH path = shortestPath((src)-[:MAC_ON_INTERFACE|HAS_INTERFACE|CONNECTED_TO|CIRCUIT_HAS_TERMINATION|TERMINATION_CONNECTED_TO*..30]-(dst))
RETURN path
LIMIT 5
```

Notice that the relationship types are inline in the pattern (`[:TYPE1|TYPE2*..30]`) rather than in a WHERE clause. This is required by Neo4j for shortestPath queries.

**Step 4: Execute.** Click Execute. The query runs against Neo4j with `$src_mac` and `$dst_mac` passed as parameters.

**Step 5: View the graph result.** The builder auto-switches to the Graph tab. The visualization shows the complete network path:

MAC (source) --> Server NIC (Interface) --> Server (Device) --> Leaf Switch Port (Interface) --> Leaf Switch (Device) --> Spine Switch Port (Interface) --> Spine Switch (Device) --> T2B Port (Interface) --> Circuit Termination --> Circuit --> Circuit Termination --> T2B Port (Interface) --> Spine Switch (Device) --> Spine Switch Port (Interface) --> Leaf Switch (Device) --> Leaf Switch Port (Interface) --> Server (Device) --> Server NIC (Interface) --> MAC (destination)

Each node type is color-coded. Edge types are labeled. You can toggle the layout between hierarchical and force-directed, filter node or edge types to simplify the view, and zoom or pan to explore the topology.

This single query traverses the full Layer 2 path: from MAC address through the interface it is learned on, up through the device hierarchy (server to leaf to spine), across a circuit connecting two sites, and back down the hierarchy on the other side to the destination MAC. It demonstrates the power of graph-native path traversal -- a query that would require multiple recursive joins in a relational system is a single shortestPath call in Cypher.

## Cypher Generation Reference

The store function `generateCypher()` in `queryBuilderStore.ts` is the single source of truth for all Cypher generation. It reads the `VisualQueryModel` and deterministically produces a Cypher string. Key behaviors:

- Nodes with relationships are merged into a single MATCH line: `MATCH (a:Label)-[r:TYPE]->(b:Label)`.
- Standalone nodes (not part of any relationship) get their own MATCH line.
- OPTIONAL MATCH nodes and relationships are emitted in a separate clause.
- Filters produce a WHERE clause with conditions joined by AND.
- Return fields support aliasing (`expression AS alias`) and aggregate detection.
- Sort fields produce ORDER BY with ASC/DESC direction.
- In path mode, the endpoint MATCH and the shortestPath MATCH are separate lines.
- An empty model generates no output. A model with fewer than two nodes in path mode generates a helpful comment: `// Add at least two node patterns for path query`.
