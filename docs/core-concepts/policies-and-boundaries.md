---
title: "Policies and Boundaries"
slug: "policies-and-boundaries"
summary: "RBAC model with role-based permissions, field-level visibility, tool authorization, and agent safety boundaries — all schema-derived."
category: "Core Concepts"
tags: [rbac, security, permissions, agent, policy]
status: published
---

# Policies and Boundaries

NetGraphy's authorization system is generated from the schema. The policy generator reads each type's `permissions` metadata, each attribute's `health.sensitive` and `health.editable` flags, and each type's `agent` metadata to produce a complete policy manifest covering RBAC resources, tool authorization, field visibility, and agent safety boundaries.

## RBAC Model

### Roles

NetGraphy defines three default roles, referenced in the schema's `PermissionsMetadata`:

- **`authenticated`** — Any logged-in user. Default for read operations.
- **`editor`** — Can create and update data. Default for write operations.
- **`admin`** — Full access including deletion and sensitive field visibility. Default for delete operations and sensitive data.

Roles are hierarchical: an admin inherits editor permissions, and an editor inherits authenticated permissions.

### Protected Resources

Every schema object becomes a named resource in the policy system:

- **`node_type:<Name>`** — Operations: view, list, search, create, update, delete.
- **`edge_type:<Name>`** — Operations: view, create, delete, connect, disconnect.
- **`attribute:<NodeType>.<field>`** — Generated only for sensitive attributes. Operations: view, edit.

Each resource carries default permission mappings from the schema. These can be overridden by group-based permission assignments at runtime.

### Group-Based Permissions

Users belong to groups, and groups are granted permissions on specific resources. A "Network Engineering" group might have editor access to Device and Interface types but only viewer access to Circuit types. Permissions are evaluated per-request: the system checks the user's groups against the required permission for the requested operation on the target resource.

## Field-Level Visibility

Attributes marked `health.sensitive: true` are protected at multiple levels:

- Excluded from MCP tool input schemas (agents cannot read or write them).
- Hidden from search indexes and query results for non-admin users.
- Masked in logs and audit trails.
- Visible only to users with admin or superadmin roles.

Attributes marked `health.editable: false` are read-only for agents and non-admin users. The agent can read the field but cannot modify it.

## Tool Authorization

Every generated MCP tool carries authorization metadata:

- **`required_permission`** — The permission string needed (e.g., `write:node:Device`).
- **`required_role`** — Minimum role from the schema's permission defaults.
- **`destructive`** — Whether the operation destroys data (delete, disconnect).
- **`requires_confirmation`** — Whether the user must confirm before execution. All delete operations require confirmation.
- **`agent_callable`** — Whether an agent can invoke this tool. Sensitive types and their tools are excluded.

## Agent Safety Boundaries

The policy generator produces an `agent_boundaries` specification that governs what any AI agent can do. The core invariant:

> An agent acting on behalf of a user inherits exactly the user's permissions and may never exceed them.

The boundary specification includes:

- **Allowed node types** — Types where `agent.exposed: true` and `agent.sensitive: false`.
- **Denied node types** — Types where `agent.exposed: false`.
- **Sensitive node types** — Types where `agent.sensitive: true`. Completely invisible to agents.
- **Destructive tools** — All delete tools, listed explicitly so agent frameworks can gate them.
- **Confirmation-required tools** — Tools that need human approval before execution.

Nine enforcement rules ensure the agent cannot escalate privileges, cross tenant boundaries, see hidden fields, or modify read-only data. All agent actions are audited with `actor_type=agent` for traceability.
