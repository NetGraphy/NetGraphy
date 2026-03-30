---
title: "Object-Aware Chat"
slug: "ai-assistant-object-aware-chat"
summary: "The AI assistant queries real graph data using relationship traversals, not keyword matching, to answer questions about your network."
category: "AI Assistant"
tags: [ai, graph, query, relationships, traversal]
status: published
---

# Object-Aware Chat

The AI assistant answers questions by querying the graph, not by searching text. When you ask "what devices are in Dallas?", the assistant does not look for the string "Dallas" in device names or descriptions. It traverses the graph: find Location nodes where `city` equals "Dallas", then follow inbound `LOCATED_IN` edges to reach the connected Device nodes.

## Relationship-First Resolution

Every query the assistant builds uses the schema's edge definitions to determine how to reach the requested data. The schema tells the assistant that devices connect to locations via `LOCATED_IN`, that interfaces belong to devices via `HAS_INTERFACE`, and that circuits connect to providers via `PROVIDED_BY`. The assistant uses these typed relationships as its primary navigation mechanism.

This means questions that span multiple hops work naturally:

- "What provider serves the circuits at the Ashburn site?" -- traverses Location to Circuit to Provider.
- "Which interfaces on core-rtr-01 are connected to other devices?" -- traverses Device to Interface, then follows `CONNECTED_TO` edges.
- "What VLANs are in use at dc-west-01?" -- traverses Location to Device to Interface to VLAN.

The assistant constructs these multi-hop queries from the schema's edge type definitions without hardcoded knowledge of any specific topology.

## Autonomous Fallback Strategies

When the initial query returns no results, the assistant does not immediately report failure. It applies fallback strategies autonomously:

- **Broadening filters** -- If an exact match on `city` returns nothing, the assistant may retry with a case-insensitive match or search the `name` field instead.
- **Alternate traversal paths** -- If the direct edge path yields no results, the assistant checks whether an alternate relationship chain reaches the same data. For example, if a location hierarchy uses `PARENT_OF` edges, the assistant may traverse up or down the hierarchy to find the relevant scope.
- **Clarification** -- If fallback strategies still produce no results, the assistant explains what it tried and asks the user to refine the question.

These strategies are guided by the schema metadata and do not rely on hardcoded logic for specific object types.
