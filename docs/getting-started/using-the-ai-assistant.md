---
title: "Using the AI Assistant"
slug: "using-the-ai-assistant"
summary: "Use the built-in AI assistant to query your network, explore topology, and manage objects in natural language."
category: "Getting Started"
tags: [ai, assistant, natural-language, mcp, tools]
status: published
---

# Using the AI Assistant

NetGraphy includes a built-in AI assistant that understands your schema and can interact with the graph database through structured tool calls. It is not a general-purpose chatbot. It has access to the same API and query engine that powers the rest of the platform, and it uses your schema definitions to understand what object types exist, what properties they have, and how they relate to each other.

![AI Assistant](../assets/screenshots/ai-assistant.png)

## Opening the Assistant

Click the **AI Assistant** button in the top navigation bar, or use the keyboard shortcut `Ctrl+K` (or `Cmd+K` on macOS). The assistant panel opens on the right side of the screen. You can resize it or pop it out into a separate window.

## What It Can Do

The assistant has access to MCP (Model Context Protocol) tools that are generated from your schema at runtime. This means it can:

- **Query objects** -- "Show me all active routers" or "List devices at the Dallas site."
- **Traverse relationships** -- "What interfaces does core-rtr-01 have?" or "What devices are connected to this switch?"
- **Explore topology** -- "What is the path between core-rtr-01 and core-rtr-02?" or "What devices are downstream of this distribution switch?"
- **Create and update objects** -- "Add a new location called dc-south-01 in Atlanta" or "Change the status of core-rtr-01 to maintenance."
- **Aggregate and summarize** -- "How many devices are at each site?" or "Which locations have no devices assigned?"
- **Investigate dependencies** -- "If I decommission this circuit, what devices lose connectivity?"

## How Tool Usage Works

When you ask a question, the assistant determines which tools to call based on the query. You can see the tool calls and their results in the conversation panel. Each tool call corresponds to an API operation or graph query.

For example, asking "What devices are at the Ashburn site?" triggers the assistant to:

1. Search for a Location node with a matching name.
2. Traverse `LOCATED_IN` edges inward to find connected Device nodes.
3. Format the results into a readable response.

The tool calls are transparent. You can expand each one to see the exact parameters sent and the raw data returned. This is useful for understanding what the assistant is doing and for learning the query patterns you can use directly in the query workbench or API.

## Example Questions to Try

Start with these to get a feel for what the assistant can do with your data:

- "How many devices are in the graph?"
- "Show me all locations of type site."
- "What interfaces does dist-sw-01 have?"
- "List all circuits provided by Zayo."
- "What devices have a status of maintenance?"
- "Show me the BGP sessions on core-rtr-01."
- "What prefixes are assigned to the 10.0.0.0/8 range?"
- "What is connected to interface GigabitEthernet0/1 on core-rtr-01?"
- "Create a new device called edge-fw-01 with role firewall and status planned."
- "Which sites have more than 10 devices?"

## Relationship-Aware Queries

The assistant's primary advantage over a simple search bar is its ability to reason about relationships. Because it knows the edge types defined in your schema, it can follow multi-hop paths through the graph.

Try questions that span multiple relationship types:

- "What provider supplies the circuits terminating at the Ashburn site?" -- This traverses Location to Circuit (via termination) to Provider.
- "What VLANs are in use on devices at dc-west-01?" -- This traverses Location to Device to Interface to VLAN.
- "Show me all devices that share a common upstream switch." -- This uses connectivity edges to find convergence points.

## Limitations

The assistant operates within the permissions of your user account. It cannot access objects or perform actions that your role does not permit. It also works within the schema boundaries -- it can only query and manipulate object types and relationships that are defined in the loaded schema files.

The assistant does not have access to device CLIs, live network state, or external systems. It operates exclusively on the data stored in the NetGraphy graph.

## Next Steps

- [Quick Start](quick-start.md) -- Set up the platform if you have not already.
- [Creating Graph Objects](first-graph-objects.md) -- Add data for the assistant to work with.
