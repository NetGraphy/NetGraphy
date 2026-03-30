---
title: "Documentation-Aware Chat"
slug: "ai-assistant-documentation-aware-chat"
summary: "The AI assistant can answer questions about the NetGraphy platform itself using a documentation knowledge graph."
category: "AI Assistant"
tags: [ai, documentation, knowledge-graph, docs]
status: published
---

# Documentation-Aware Chat

The AI assistant can answer questions about the NetGraphy platform itself -- not just the network data stored in the graph. It does this by querying a documentation knowledge graph that represents the platform's own docs as structured nodes and relationships.

## How It Works

NetGraphy's documentation files are ingested into the graph as `DocPage` nodes. Each documentation page becomes a node with properties for title, slug, category, summary, and content. The relationships between pages are modeled as edges: `RELATES_TO` for topical connections, `PREREQ_OF` for dependency ordering, and `PARENT_OF` for hierarchical structure.

## Section Chunking

Long documentation pages are split into section-level chunks. Each section becomes a child node linked to its parent `DocPage` via a `HAS_SECTION` edge. This allows the assistant to retrieve specific sections rather than entire pages, keeping the context focused and the responses precise. Section nodes carry their own heading, content, and position metadata.

## Semantic Relationships

The knowledge graph captures semantic relationships that go beyond the table of contents. A page about schema definition relates to pages about tool generation, validation, and the AI assistant because they all depend on schema concepts. These cross-cutting relationships let the assistant follow conceptual paths -- answering "how does adding a schema file affect the assistant?" by traversing from schema documentation to tool generation documentation to assistant documentation.

## Query Behavior

When you ask a platform question like "how do I add a new node type?" or "what is provenance?", the assistant queries the `DocPage` and section nodes to find relevant content. It synthesizes answers from the retrieved sections and includes references to the source documentation pages so you can read the full detail.
