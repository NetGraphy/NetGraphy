---
title: "User-Equivalent Permissions"
slug: "ai-assistant-user-equivalent-permissions"
summary: "The AI assistant inherits the authenticated user's permissions and cannot exceed them. Enforcement happens at tool filtering and execution time."
category: "AI Assistant"
tags: [ai, permissions, rbac, security, auth]
status: published
---

# User-Equivalent Permissions

The AI assistant operates with exactly the permissions of the user who initiated the session. It cannot see, query, or modify any object type that the user's role does not grant access to. This is a hard boundary, enforced at multiple layers.

## AuthContext Inheritance

When a user opens the assistant, the runtime binds the session to the user's `AuthContext` -- the same identity and permission set that governs their API and UI access. The assistant does not have its own service account or elevated privileges. If a user cannot delete devices through the UI, the assistant cannot delete devices either.

## Tool Filtering

The first enforcement layer operates at context assembly time. Before the LLM receives its tool definitions for a conversation turn, the tool generation engine filters out every tool the user lacks permission to invoke. If the user's role grants read-only access to the `Circuit` type, the `create_circuit`, `update_circuit`, and `delete_circuit` tools are excluded from the context entirely. The model never sees them, so it cannot attempt to call them.

This is not just a UX convenience. It reduces the attack surface by ensuring the model cannot be prompt-injected into calling tools that should not exist in its context.

## Execution-Time Re-Check

The second enforcement layer operates at tool execution time. Even if a tool is present in the context (for example, due to a race condition during permission updates), the execution handler re-validates the user's permissions before running the operation. This defense-in-depth approach ensures that no tool call reaches the graph without passing a current permission check.

## Destructive Action Confirmation

Tools that perform destructive operations -- `delete_` and `disconnect_` -- require explicit user confirmation before execution. When the assistant determines it needs to call a destructive tool, it presents the intended action and waits for the user to approve or reject it. This confirmation step cannot be bypassed by the model.

## Policy-Generated Safety Boundaries

The policy generator reads each node type's `permissions` block and produces the tool filtering rules and confirmation requirements automatically. Administrators do not manually configure per-tool permission mappings. When you update a role's access to a node type, the assistant's tool set updates on the next session without additional configuration.
