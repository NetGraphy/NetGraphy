---
title: "External Agent Access"
slug: "ai-assistant-external-agent-access"
summary: "External AI agents and MCP clients can connect to NetGraphy's agent API to use schema-generated tools programmatically."
category: "AI Assistant"
tags: [ai, api, mcp, external, integration, tokens]
status: published
---

# External Agent Access

NetGraphy's AI capabilities are not limited to the built-in chat panel. External agents -- including Claude Code, custom MCP clients, and automation scripts -- can connect to the platform's agent API to use the same schema-generated tools available to the built-in assistant.

## The Agent Chat Endpoint

External agents interact with NetGraphy through the `POST /agent/chat` endpoint. This endpoint accepts a conversation payload (messages, tool call history, and optional configuration) and returns the assistant's response, including any tool calls it makes against the graph. The endpoint handles the full tool execution loop: the external client sends a user message, the API runs the LLM inference, executes any tool calls, and returns the final response.

```
POST /api/v1/agent/chat
Content-Type: application/json
Authorization: Bearer <api-token>

{
  "messages": [
    {"role": "user", "content": "How many active devices are in the graph?"}
  ]
}
```

## Tool Definitions

External clients that implement their own LLM orchestration can retrieve the full set of MCP tool definitions from the `/generated/mcp-tools` endpoint. This returns the JSON schema for every tool the authenticated user has access to, allowing external agents to include these definitions in their own LLM context and handle tool calls directly.

```
GET /api/v1/generated/mcp-tools
Authorization: Bearer <api-token>
```

The response is filtered by the token's associated user permissions, so different tokens may receive different tool sets.

## Authentication

External agents authenticate using API tokens. Tokens are created in the administration panel or via the API and are bound to a specific user account. The token inherits that user's full permission set, so the same [user-equivalent permissions](user-equivalent-permissions.md) model applies. An external agent using a read-only token will only receive query and count tools -- no create, update, delete, connect, or disconnect tools appear in its tool set.

## Use Cases

- **Claude Code** -- Use the MCP tool definitions to give Claude Code direct access to your network graph during development and troubleshooting sessions.
- **Custom automation** -- Build scripts that ask natural language questions about your network and act on the structured responses.
- **Multi-platform agents** -- Connect agents running on different LLM providers to the same NetGraphy instance, each with their own token and permission scope.
