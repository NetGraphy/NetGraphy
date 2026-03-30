"""Policy Generator — derives RBAC resource definitions, tool authorization rules,
field visibility policies, and agent safety boundaries from the schema.

Core invariant:
    An agent acting on behalf of a user inherits the user's permissions
    and may never exceed them.

Generates:
1. Protected resource definitions (node:Device, edge:CONNECTED_TO, tool:create_device)
2. Default role→operation mappings from schema permissions metadata
3. Field-level visibility rules from attribute health.sensitive metadata
4. Tool authorization requirements (required permission, destructive flag, approval)
5. Agent safety boundaries (agent-callable flag, confirmation requirements)
"""

from __future__ import annotations

import re
from typing import Any

from packages.schema_engine.models import (
    EdgeTypeDefinition,
    NodeTypeDefinition,
)
from packages.schema_engine.registry import SchemaRegistry


def _slugify(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def generate_resource_definitions(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate protected resource definitions from the schema.

    Every node type, edge type, attribute, and generated tool becomes a
    named resource that the policy engine can authorize against.
    """
    resources: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        name = nt.metadata.name

        # Node type resource
        resources.append({
            "resource": f"node_type:{name}",
            "display_name": nt.metadata.display_name or name,
            "category": nt.metadata.category or "uncategorized",
            "operations": ["view", "list", "search", "create", "update", "delete"],
            "default_permissions": {
                "view": nt.permissions.default_read,
                "list": nt.permissions.default_read,
                "search": nt.permissions.default_read,
                "create": nt.permissions.default_write,
                "update": nt.permissions.default_write,
                "delete": nt.permissions.default_delete,
            },
        })

        # Per-attribute resources (for field-level control)
        for attr_name, attr in nt.attributes.items():
            if attr.health.sensitive:
                resources.append({
                    "resource": f"attribute:{name}.{attr_name}",
                    "display_name": f"{name}.{attr.display_name or attr_name}",
                    "operations": ["view", "edit"],
                    "sensitive": True,
                    "default_permissions": {
                        "view": "admin",
                        "edit": "admin",
                    },
                })

    for et in registry._edge_types.values():
        resources.append({
            "resource": f"edge_type:{et.metadata.name}",
            "display_name": et.metadata.display_name or et.metadata.name,
            "operations": ["view", "create", "delete", "connect", "disconnect"],
            "default_permissions": {
                "view": et.permissions.default_read,
                "create": et.permissions.default_write,
                "delete": et.permissions.default_delete,
                "connect": et.permissions.default_write,
                "disconnect": et.permissions.default_delete,
            },
        })

    return resources


def generate_tool_auth_rules(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate authorization requirements for each MCP tool.

    Every tool gets:
    - required_permission: what the actor must have
    - destructive: whether this is a destructive operation
    - requires_confirmation: whether human confirmation is needed
    - agent_callable: whether an agent can invoke this
    """
    rules: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        slug = _slugify(nt.metadata.name)
        name = nt.metadata.name

        if not nt.mcp.exposed:
            continue

        # create tool
        if nt.mcp.allow_create:
            rules.append({
                "tool": f"create_{slug}",
                "required_permission": f"write:node:{name}",
                "required_role": nt.permissions.default_write,
                "destructive": False,
                "requires_confirmation": False,
                "agent_callable": nt.agent.exposed and not nt.agent.sensitive,
                "resource": f"node_type:{name}",
                "operation": "create",
            })

        # get/list/search tools
        for op in ["get", "list", "search"]:
            tool_name = f"{slug}s" if op in ("list", "search") else slug
            plural = nt.api.plural_name or f"{slug}s"
            rules.append({
                "tool": f"{op}_{tool_name}" if op == "get" else f"{op}_{plural.replace('-', '_')}",
                "required_permission": f"read:node:{name}",
                "required_role": nt.permissions.default_read,
                "destructive": False,
                "requires_confirmation": False,
                "agent_callable": nt.agent.exposed,
                "resource": f"node_type:{name}",
                "operation": op,
            })

        # update tool
        if nt.mcp.allow_update:
            rules.append({
                "tool": f"update_{slug}",
                "required_permission": f"write:node:{name}",
                "required_role": nt.permissions.default_write,
                "destructive": False,
                "requires_confirmation": False,
                "agent_callable": nt.agent.exposed and not nt.agent.sensitive,
                "resource": f"node_type:{name}",
                "operation": "update",
            })

        # delete tool
        if nt.mcp.allow_delete:
            rules.append({
                "tool": f"delete_{slug}",
                "required_permission": f"write:node:{name}",
                "required_role": nt.permissions.default_delete,
                "destructive": True,
                "requires_confirmation": True,
                "agent_callable": nt.agent.exposed and not nt.agent.sensitive,
                "resource": f"node_type:{name}",
                "operation": "delete",
            })

    # Edge tools
    for et in registry._edge_types.values():
        if not et.mcp.exposed:
            continue

        for src in et.source.node_types:
            for tgt in et.target.node_types:
                src_slug = _slugify(src)
                tgt_slug = _slugify(tgt)

                if et.mcp.allow_create:
                    rules.append({
                        "tool": f"connect_{src_slug}_to_{tgt_slug}",
                        "required_permission": f"write:edge:{et.metadata.name}",
                        "required_role": et.permissions.default_write,
                        "destructive": False,
                        "requires_confirmation": False,
                        "agent_callable": et.agent.exposed,
                        "resource": f"edge_type:{et.metadata.name}",
                        "operation": "connect",
                    })

                if et.mcp.allow_delete:
                    rules.append({
                        "tool": f"disconnect_{src_slug}_from_{tgt_slug}",
                        "required_permission": f"write:edge:{et.metadata.name}",
                        "required_role": et.permissions.default_delete,
                        "destructive": True,
                        "requires_confirmation": False,
                        "agent_callable": et.agent.exposed,
                        "resource": f"edge_type:{et.metadata.name}",
                        "operation": "disconnect",
                    })

    return rules


def generate_field_visibility_rules(registry: SchemaRegistry) -> list[dict[str, Any]]:
    """Generate field-level visibility rules.

    Sensitive fields are hidden from agents and non-admin users.
    Fields marked hidden_from_agents are excluded from agent responses.
    """
    rules: list[dict[str, Any]] = []

    for nt in registry._node_types.values():
        for attr_name, attr in nt.attributes.items():
            if attr.health.sensitive:
                rules.append({
                    "node_type": nt.metadata.name,
                    "field": attr_name,
                    "display_name": attr.display_name or attr_name,
                    "rule": "sensitive",
                    "visible_to_roles": ["admin", "superadmin"],
                    "hidden_from_agents": True,
                    "masked_in_logs": True,
                    "masked_in_search": True,
                })
            elif not attr.health.editable:
                rules.append({
                    "node_type": nt.metadata.name,
                    "field": attr_name,
                    "display_name": attr.display_name or attr_name,
                    "rule": "read_only",
                    "editable_by_roles": ["admin", "superadmin"],
                    "hidden_from_agents": False,
                    "agent_can_read": True,
                    "agent_can_write": False,
                })

    return rules


def generate_agent_boundaries(registry: SchemaRegistry) -> dict[str, Any]:
    """Generate the complete agent safety boundary specification.

    This is the master document that defines what an agent CAN and CANNOT do.
    It is derived entirely from the schema and never grants the agent
    permissions beyond what the acting user has.
    """
    allowed_types: list[str] = []
    denied_types: list[str] = []
    sensitive_types: list[str] = []
    destructive_tools: list[str] = []
    confirmation_required: list[str] = []

    for nt in registry._node_types.values():
        if nt.agent.exposed and not nt.agent.sensitive:
            allowed_types.append(nt.metadata.name)
        elif nt.agent.sensitive:
            sensitive_types.append(nt.metadata.name)
        else:
            denied_types.append(nt.metadata.name)

        if nt.mcp.allow_delete:
            destructive_tools.append(f"delete_{_slugify(nt.metadata.name)}")
            confirmation_required.append(f"delete_{_slugify(nt.metadata.name)}")

    return {
        "enforcement_rule": "user_equivalent",
        "description": (
            "An agent acting on behalf of a user inherits exactly the user's "
            "permissions. It may never exceed them. The agent is not a privileged "
            "superuser — it acts strictly as an extension of the authenticated user."
        ),
        "allowed_node_types": sorted(allowed_types),
        "denied_node_types": sorted(denied_types),
        "sensitive_node_types": sorted(sensitive_types),
        "destructive_tools": sorted(destructive_tools),
        "confirmation_required_tools": sorted(confirmation_required),
        "rules": [
            "Agent uses the acting user's AuthContext for all permission checks",
            "Agent cannot see fields the user cannot see",
            "Agent cannot modify fields the user cannot modify",
            "Agent cannot create/update/delete objects the user cannot",
            "Agent cannot execute tools the user's role/groups do not permit",
            "Agent cannot cross tenant boundaries the user cannot cross",
            "Destructive operations require explicit user confirmation",
            "Sensitive node types are excluded from agent tool generation",
            "All agent actions are audited with actor_type=agent",
        ],
        "sensitive_field_count": sum(
            1 for nt in registry._node_types.values()
            for attr in nt.attributes.values()
            if attr.health.sensitive
        ),
    }


def generate_all_policies(registry: SchemaRegistry) -> dict[str, Any]:
    """Generate complete policy manifest from the schema."""
    return {
        "resources": generate_resource_definitions(registry),
        "tool_auth_rules": generate_tool_auth_rules(registry),
        "field_visibility": generate_field_visibility_rules(registry),
        "agent_boundaries": generate_agent_boundaries(registry),
    }
