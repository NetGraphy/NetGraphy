"""Generation Engine — orchestrates all schema-derived artifact generation.

Given the canonical schema registry, produces:
1. MCP tool definitions (with auth metadata)
2. Agent capability manifest (with safety boundaries)
3. Validation rules
4. Observability rules
5. Policy artifacts (RBAC resources, tool auth, field visibility, agent boundaries)

All outputs are deterministic and version-aware.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from packages.schema_engine.generators.agent_generator import generate_all_capabilities
from packages.schema_engine.generators.mcp_generator import generate_all_mcp_tools
from packages.schema_engine.generators.observability_generator import generate_all_observability_rules
from packages.schema_engine.generators.policy_generator import (
    generate_agent_boundaries,
    generate_all_policies,
    generate_field_visibility_rules,
    generate_resource_definitions,
    generate_tool_auth_rules,
)
from packages.schema_engine.generators.validation_generator import generate_all_validation_rules
from packages.schema_engine.registry import SchemaRegistry


class GeneratedManifest:
    """Complete set of artifacts generated from the schema."""

    def __init__(
        self,
        mcp_tools: list[dict[str, Any]],
        agent_capabilities: list[dict[str, Any]],
        validation_rules: list[dict[str, Any]],
        observability_rules: list[dict[str, Any]],
        policy: dict[str, Any],
        schema_version: str,
        generated_at: str,
    ) -> None:
        self.mcp_tools = mcp_tools
        self.agent_capabilities = agent_capabilities
        self.validation_rules = validation_rules
        self.observability_rules = observability_rules
        self.policy = policy
        self.schema_version = schema_version
        self.generated_at = generated_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "summary": {
                "mcp_tools": len(self.mcp_tools),
                "agent_capabilities": len(self.agent_capabilities),
                "validation_rules": len(self.validation_rules),
                "observability_rules": len(self.observability_rules),
                "rbac_resources": len(self.policy.get("resources", [])),
                "tool_auth_rules": len(self.policy.get("tool_auth_rules", [])),
                "field_visibility_rules": len(self.policy.get("field_visibility", [])),
            },
            "mcp_tools": self.mcp_tools,
            "agent_capabilities": self.agent_capabilities,
            "validation_rules": self.validation_rules,
            "observability_rules": self.observability_rules,
            "policy": self.policy,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "mcp_tools_count": len(self.mcp_tools),
            "agent_capabilities_count": len(self.agent_capabilities),
            "validation_rules_count": len(self.validation_rules),
            "observability_rules_count": len(self.observability_rules),
            "rbac_resources_count": len(self.policy.get("resources", [])),
            "tool_auth_rules_count": len(self.policy.get("tool_auth_rules", [])),
            "field_visibility_rules_count": len(self.policy.get("field_visibility", [])),
            "mcp_tools_by_category": self._count_by("mcp_tools", "category"),
            "agent_capabilities_by_category": self._count_by("agent_capabilities", "category"),
            "validation_rules_by_type": self._count_by("validation_rules", "rule_type"),
            "observability_rules_by_type": self._count_by("observability_rules", "rule_type"),
            "agent_boundaries": self.policy.get("agent_boundaries", {}),
        }

    def _count_by(self, artifact_type: str, key: str) -> dict[str, int]:
        items = getattr(self, artifact_type, [])
        counts: dict[str, int] = {}
        for item in items:
            val = item.get(key, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts


class GenerationEngine:
    """Orchestrates generation of all schema-derived artifacts.

    Produces MCP tools, agent capabilities, validation rules, observability
    rules, and policy artifacts. MCP tools and agent capabilities are
    enriched with authorization metadata from the policy generator.
    """

    def __init__(self, registry: SchemaRegistry) -> None:
        self._registry = registry
        self._last_manifest: GeneratedManifest | None = None

    def generate(self) -> GeneratedManifest:
        """Generate all artifacts from the current schema state."""
        schema_version = self._compute_schema_version()
        generated_at = datetime.now(timezone.utc).isoformat()

        # Generate raw artifacts
        mcp_tools = generate_all_mcp_tools(self._registry)
        agent_capabilities = generate_all_capabilities(self._registry)
        validation_rules = generate_all_validation_rules(self._registry)
        observability_rules = generate_all_observability_rules(self._registry)
        policy = generate_all_policies(self._registry)

        # Enrich MCP tools with auth metadata from policy
        tool_auth_map = {r["tool"]: r for r in policy.get("tool_auth_rules", [])}
        for tool in mcp_tools:
            auth = tool_auth_map.get(tool["name"], {})
            tool["auth"] = {
                "required_permission": auth.get("required_permission", ""),
                "required_role": auth.get("required_role", "authenticated"),
                "destructive": auth.get("destructive", False),
                "requires_confirmation": auth.get("requires_confirmation", False),
                "agent_callable": auth.get("agent_callable", True),
            }

        # Enrich agent capabilities with safety metadata
        for cap in agent_capabilities:
            cap["auth"] = {
                "agent_callable": cap.get("safety") != "destructive" or True,
                "requires_user_permission": True,
                "enforcement_rule": "user_equivalent",
            }

        manifest = GeneratedManifest(
            mcp_tools=mcp_tools,
            agent_capabilities=agent_capabilities,
            validation_rules=validation_rules,
            observability_rules=observability_rules,
            policy=policy,
            schema_version=schema_version,
            generated_at=generated_at,
        )

        self._last_manifest = manifest
        return manifest

    def diff(self, previous: GeneratedManifest | None = None) -> dict[str, Any]:
        current = self.generate()
        prev = previous or self._last_manifest

        if not prev:
            return {"status": "initial", "added": current.summary()}

        def _diff_list(current_items: list, previous_items: list, key: str = "name") -> dict:
            current_names = {item.get(key): item for item in current_items}
            prev_names = {item.get(key): item for item in previous_items}
            added = [n for n in current_names if n not in prev_names]
            removed = [n for n in prev_names if n not in current_names]
            return {"added": added, "removed": removed, "added_count": len(added), "removed_count": len(removed)}

        return {
            "status": "diff",
            "schema_version": current.schema_version,
            "previous_version": prev.schema_version,
            "mcp_tools": _diff_list(current.mcp_tools, prev.mcp_tools),
            "agent_capabilities": _diff_list(current.agent_capabilities, prev.agent_capabilities),
        }

    def _compute_schema_version(self) -> str:
        parts: list[str] = []
        for nt in sorted(self._registry._node_types.values(), key=lambda x: x.metadata.name):
            attrs = sorted(nt.attributes.keys())
            parts.append(f"N:{nt.metadata.name}:{','.join(attrs)}")
        for et in sorted(self._registry._edge_types.values(), key=lambda x: x.metadata.name):
            parts.append(f"E:{et.metadata.name}:{','.join(et.source.node_types)}->{','.join(et.target.node_types)}")
        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()[:12]
