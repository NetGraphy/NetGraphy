---
title: "AI Assistant Overview"
slug: "ai-assistant-overview"
summary: "NetGraphy's built-in AI assistant uses schema-generated tools, multi-provider LLM support, and graph-aware reasoning to answer questions about your network."
category: "AI Assistant"
tags: [ai, assistant, mcp, schema, llm, observability]
status: published
---

# AI Assistant Overview

NetGraphy's AI assistant is a core platform component, not an add-on. It is generated from the same YAML schema that drives the API, UI, validation, and graph constraints. When the schema defines a node type, the assistant automatically gains the ability to query, create, update, and delete instances of that type through structured MCP (Model Context Protocol) tool calls. There is no separate configuration step to teach the assistant about new object types.

## Schema-Generated Tools

At startup, the tool generation engine reads every `NodeTypeDefinition` and `EdgeTypeDefinition` in the schema registry and produces a set of MCP tools for each. These tools follow deterministic naming conventions -- `query_device`, `create_location`, `connect_interface_to_device` -- and carry full parameter schemas derived from the attribute definitions. The assistant receives these tool definitions as part of its context, giving it a precise understanding of what operations are available, what parameters each accepts, and what types those parameters expect.

## Multi-Provider LLM Support

The assistant runtime is not locked to a single LLM provider. It supports Anthropic (Claude), OpenAI, Google Vertex AI, Amazon Bedrock, vLLM, and Ollama out of the box. Provider configuration is set via environment variables or the admin settings panel. You can switch providers without changing any schema, tool definition, or application code. The tool interface is provider-agnostic -- the same MCP tool definitions work regardless of which model is executing.

## Auth-Aware Execution

Every assistant session inherits the authenticated user's permissions. The assistant cannot see or invoke tools for object types the user lacks access to. This is enforced at two layers: tool filtering at context assembly time and permission re-checking at execution time. The details are covered in [User-Equivalent Permissions](user-equivalent-permissions.md).

## Configurable System Prompt

Administrators can customize the assistant's system prompt to include organization-specific context, naming conventions, standard operating procedures, or behavioral guidelines. The system prompt is stored as platform configuration and can be versioned alongside schema files.

## Observability

Every assistant interaction is traced via OpenTelemetry. Spans cover tool selection, tool execution, LLM inference latency, token usage, and permission checks. These traces export to any OTel-compatible backend. The default development stack ships with Phoenix as the trace viewer, giving full visibility into how the assistant reasons about each query, which tools it considers, and where time is spent.
