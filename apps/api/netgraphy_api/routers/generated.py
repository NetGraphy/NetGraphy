"""Generated Artifacts API — exposes schema-derived MCP tools, agent capabilities,
validation rules, observability rules, and health reports.

All artifacts are generated on-demand from the canonical schema registry.
They update automatically when the schema changes — no manual definitions required.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_schema_registry
from packages.auth.models import AuthContext
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

router = APIRouter()


def _get_engine(registry: SchemaRegistry = Depends(get_schema_registry)):
    from packages.schema_engine.generators.engine import GenerationEngine
    return GenerationEngine(registry)


# --------------------------------------------------------------------------- #
#  Full Manifest                                                               #
# --------------------------------------------------------------------------- #


@router.get("/manifest")
async def get_full_manifest(
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Generate and return the complete artifact manifest.

    Includes all MCP tools, agent capabilities, validation rules, and
    observability rules derived from the current schema state.
    """
    manifest = engine.generate()
    return {"data": manifest.to_dict()}


@router.get("/summary")
async def get_manifest_summary(
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Summary counts of all generated artifacts."""
    manifest = engine.generate()
    return {"data": manifest.summary()}


# --------------------------------------------------------------------------- #
#  MCP Tools                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/mcp-tools")
async def list_mcp_tools(
    category: str | None = None,
    node_type: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all generated MCP tool definitions.

    These tools can be registered with any MCP-compatible client (Claude,
    GPT, etc.) to enable AI interaction with the graph.

    Filters:
        category: crud | query | aggregate | lookup | search | relationship | traversal
        node_type: Filter tools for a specific node type
    """
    manifest = engine.generate()
    tools = manifest.mcp_tools

    if category:
        tools = [t for t in tools if t.get("category") == category]
    if node_type:
        tools = [t for t in tools if t.get("node_type") == node_type or t.get("edge_type") == node_type]

    return {
        "data": tools,
        "meta": {"total": len(tools), "schema_version": manifest.schema_version},
    }


@router.get("/mcp-tools/{tool_name}")
async def get_mcp_tool(
    tool_name: str,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get a single MCP tool definition by name."""
    manifest = engine.generate()
    for tool in manifest.mcp_tools:
        if tool["name"] == tool_name:
            return {"data": tool}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"MCP tool '{tool_name}' not found")


# --------------------------------------------------------------------------- #
#  Agent Capabilities                                                          #
# --------------------------------------------------------------------------- #


@router.get("/agent-capabilities")
async def list_agent_capabilities(
    category: str | None = None,
    safety: str | None = None,
    node_type: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all generated agent capabilities.

    Capabilities are semantic actions an AI agent can perform — higher-level
    than raw CRUD tools. They include example prompts and safety ratings.

    Filters:
        category: crud | search | relationship | traversal | health | audit | custom
        safety: read | write | destructive
        node_type: Filter capabilities for a specific node type
    """
    manifest = engine.generate()
    caps = manifest.agent_capabilities

    if category:
        caps = [c for c in caps if c.get("category") == category]
    if safety:
        caps = [c for c in caps if c.get("safety") == safety]
    if node_type:
        caps = [c for c in caps if c.get("node_type") == node_type]

    return {
        "data": caps,
        "meta": {"total": len(caps), "schema_version": manifest.schema_version},
    }


# --------------------------------------------------------------------------- #
#  Validation Rules                                                            #
# --------------------------------------------------------------------------- #


@router.get("/validation-rules")
async def list_validation_rules(
    node_type: str | None = None,
    edge_type: str | None = None,
    rule_type: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all generated validation rules.

    These rules are enforced at API boundaries, by MCP tools, and by
    agent actions — all derived from the schema, no manual definitions.

    Filters:
        node_type: Rules for a specific node type
        edge_type: Rules for a specific edge type
        rule_type: required_field | unique_field | type_check | enum_check | cardinality | etc.
    """
    manifest = engine.generate()
    rules = manifest.validation_rules

    if node_type:
        rules = [r for r in rules if r.get("node_type") == node_type]
    if edge_type:
        rules = [r for r in rules if r.get("edge_type") == edge_type]
    if rule_type:
        rules = [r for r in rules if r.get("rule_type") == rule_type]

    return {
        "data": rules,
        "meta": {"total": len(rules), "schema_version": manifest.schema_version},
    }


# --------------------------------------------------------------------------- #
#  Observability Rules                                                         #
# --------------------------------------------------------------------------- #


@router.get("/observability-rules")
async def list_observability_rules(
    rule_type: str | None = None,
    category: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all generated observability rules.

    Includes metrics definitions, health checks, and alerts — all derived
    from schema health metadata.

    Filters:
        rule_type: metric | health_check | alert
        category: validation | integrity | capacity | freshness | data_quality
    """
    manifest = engine.generate()
    rules = manifest.observability_rules

    if rule_type:
        rules = [r for r in rules if r.get("rule_type") == rule_type]
    if category:
        rules = [r for r in rules if r.get("category") == category]

    return {
        "data": rules,
        "meta": {"total": len(rules), "schema_version": manifest.schema_version},
    }


# --------------------------------------------------------------------------- #
#  Health Report                                                               #
# --------------------------------------------------------------------------- #


@router.get("/health-report")
async def get_health_report(
    driver: Neo4jDriver = Depends(get_graph_driver),
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Execute all health checks and return a live health report.

    Runs every generated health check and metric query against the graph
    database and returns the results.
    """
    manifest = engine.generate()
    report: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "status": "healthy",
        "metrics": [],
        "checks": [],
        "alerts": [],
        "issues_count": 0,
    }

    # Execute metric queries
    for rule in manifest.observability_rules:
        if rule["rule_type"] == "metric":
            try:
                result = await driver.execute_read(rule["query"], {})
                values = []
                for row in result.rows:
                    values.append(row)
                report["metrics"].append({
                    "name": rule["metric_name"],
                    "labels": rule.get("labels", {}),
                    "description": rule.get("description", ""),
                    "values": values,
                })
            except Exception as e:
                report["metrics"].append({
                    "name": rule["metric_name"],
                    "error": str(e),
                })

    # Execute health checks
    for rule in manifest.observability_rules:
        if rule["rule_type"] == "health_check":
            try:
                result = await driver.execute_read(rule["query"], {})
                issues = result.rows
                check = {
                    "name": rule["check_name"],
                    "description": rule.get("description", ""),
                    "severity": rule.get("severity", "warning"),
                    "category": rule.get("category", ""),
                    "passed": len(issues) == 0,
                    "issue_count": len(issues),
                    "issues": issues[:10],  # Limit to first 10 for response size
                }
                report["checks"].append(check)
                if not check["passed"]:
                    report["issues_count"] += len(issues)
                    if rule.get("severity") == "critical":
                        report["status"] = "critical"
                    elif rule.get("severity") == "error" and report["status"] != "critical":
                        report["status"] = "unhealthy"
                    elif report["status"] == "healthy":
                        report["status"] = "degraded"
            except Exception as e:
                report["checks"].append({
                    "name": rule["check_name"],
                    "error": str(e),
                    "passed": False,
                })

    return {"data": report}


# --------------------------------------------------------------------------- #
#  Prometheus Metrics Endpoint                                                 #
# --------------------------------------------------------------------------- #


@router.get("/metrics", response_class=None)
async def prometheus_metrics(
    driver: Neo4jDriver = Depends(get_graph_driver),
    engine=Depends(_get_engine),
):
    """Prometheus-compatible metrics endpoint.

    Returns metrics in Prometheus text exposition format.
    """
    from fastapi.responses import PlainTextResponse

    manifest = engine.generate()
    lines: list[str] = []

    for rule in manifest.observability_rules:
        if rule["rule_type"] != "metric":
            continue

        metric_name = rule["metric_name"]
        labels = rule.get("labels", {})
        description = rule.get("description", "")

        try:
            result = await driver.execute_read(rule["query"], {})
            if result.rows:
                lines.append(f"# HELP {metric_name} {description}")
                lines.append(f"# TYPE {metric_name} gauge")
                for row in result.rows:
                    value = row.get("value", 0)
                    # Build label string
                    all_labels = {**labels}
                    for k, v in row.items():
                        if k != "value":
                            all_labels[k] = str(v)
                    label_str = ",".join(f'{k}="{v}"' for k, v in all_labels.items() if v)
                    if label_str:
                        lines.append(f"{metric_name}{{{label_str}}} {value}")
                    else:
                        lines.append(f"{metric_name} {value}")
        except Exception:
            pass

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


# --------------------------------------------------------------------------- #
#  Policy & RBAC Resources                                                     #
# --------------------------------------------------------------------------- #


@router.get("/policy")
async def get_policy_manifest(
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Full policy manifest: RBAC resources, tool auth rules, field visibility, agent boundaries."""
    manifest = engine.generate()
    return {"data": manifest.policy}


@router.get("/policy/resources")
async def list_rbac_resources(
    category: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all schema-derived RBAC resource definitions with default permissions."""
    manifest = engine.generate()
    resources = manifest.policy.get("resources", [])
    if category:
        resources = [r for r in resources if r.get("category") == category]
    return {"data": resources, "meta": {"total": len(resources)}}


@router.get("/policy/tool-auth")
async def list_tool_auth_rules(
    destructive: bool | None = None,
    agent_callable: bool | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List authorization requirements for every generated MCP tool."""
    manifest = engine.generate()
    rules = manifest.policy.get("tool_auth_rules", [])
    if destructive is not None:
        rules = [r for r in rules if r.get("destructive") == destructive]
    if agent_callable is not None:
        rules = [r for r in rules if r.get("agent_callable") == agent_callable]
    return {"data": rules, "meta": {"total": len(rules)}}


@router.get("/policy/field-visibility")
async def list_field_visibility_rules(
    node_type: str | None = None,
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """List field-level visibility and sensitivity rules."""
    manifest = engine.generate()
    rules = manifest.policy.get("field_visibility", [])
    if node_type:
        rules = [r for r in rules if r.get("node_type") == node_type]
    return {"data": rules, "meta": {"total": len(rules)}}


@router.get("/policy/agent-boundaries")
async def get_agent_boundaries(
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get the complete agent safety boundary specification.

    Defines exactly what an agent can and cannot do, derived from schema.
    The core rule: an agent inherits the acting user's permissions and
    may never exceed them.
    """
    manifest = engine.generate()
    return {"data": manifest.policy.get("agent_boundaries", {})}


# --------------------------------------------------------------------------- #
#  Permission Introspection                                                    #
# --------------------------------------------------------------------------- #


@router.get("/permissions/effective")
async def get_effective_permissions(
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get the effective permissions for the current user.

    Shows exactly what the user (and an agent acting on their behalf) can do.
    Combines role-based permissions with group-based object permissions and
    evaluates them against all generated tools and resources.
    """
    from packages.auth.rbac import PermissionChecker

    manifest = engine.generate()
    checker = PermissionChecker()

    # Evaluate every tool
    tool_results: list[dict[str, Any]] = []
    for tool in manifest.mcp_tools:
        auth = tool.get("auth", {})
        required_perm = auth.get("required_permission", "")
        if required_perm:
            parts = required_perm.split(":", 1)
            action = parts[0] if parts else ""
            resource = parts[1] if len(parts) > 1 else ""
            allowed = checker.check_permission(actor, action, resource)
        else:
            allowed = True

        tool_results.append({
            "tool": tool["name"],
            "allowed": allowed,
            "required_permission": required_perm,
            "destructive": auth.get("destructive", False),
            "agent_callable": auth.get("agent_callable", True) and allowed,
        })

    allowed_count = sum(1 for t in tool_results if t["allowed"])
    denied_count = len(tool_results) - allowed_count

    # Evaluate node type permissions
    node_perms: list[dict[str, Any]] = []
    for resource in manifest.policy.get("resources", []):
        if not resource["resource"].startswith("node_type:"):
            continue
        node_type = resource["resource"].split(":", 1)[1]
        ops = {}
        for op in ["view", "create", "update", "delete"]:
            action = "read" if op in ("view", "list") else "write"
            ops[op] = checker.check_permission(actor, action, f"node:{node_type}")
        node_perms.append({
            "node_type": node_type,
            "display_name": resource.get("display_name", node_type),
            "category": resource.get("category", ""),
            **ops,
        })

    return {
        "data": {
            "user": {
                "user_id": actor.user_id,
                "username": actor.username,
                "role": actor.role,
                "groups": actor.groups,
                "auth_backend": actor.auth_backend,
            },
            "summary": {
                "tools_allowed": allowed_count,
                "tools_denied": denied_count,
                "total_tools": len(tool_results),
            },
            "node_permissions": node_perms,
            "tool_permissions": tool_results,
            "agent_note": (
                "An agent acting on your behalf has exactly these permissions. "
                "It cannot see, create, update, or delete anything you cannot."
            ),
        }
    }


@router.get("/permissions/check")
async def check_permission(
    action: str = Query(..., description="Action: read, write, execute, manage"),
    resource: str = Query(..., description="Resource: node:Device, edge:CONNECTED_TO, job:backup"),
    engine=Depends(_get_engine),
    actor: AuthContext = Depends(get_auth_context),
):
    """Check whether the current user has a specific permission.

    Returns the decision with an explanation of why it was allowed or denied.
    Useful for debugging agent refusals.
    """
    from packages.auth.rbac import PermissionChecker, get_role_permissions

    checker = PermissionChecker()
    allowed = checker.check_permission(actor, action, resource)

    explanation: list[str] = []
    if actor.role == "superadmin":
        explanation.append("Allowed: superadmin has global wildcard permission")
    else:
        role_perms = get_role_permissions(actor.role)
        matching = [p for p in role_perms if p == "*" or f"{action}:{resource}".startswith(p.replace("*", ""))]
        if matching:
            explanation.append(f"Allowed by role '{actor.role}' via: {', '.join(matching)}")
        else:
            explanation.append(f"Not granted by role '{actor.role}'")

        # Check object permissions
        for perm in actor.object_permissions:
            if perm.get("enabled"):
                explanation.append(f"Group permission '{perm.get('name', '?')}' evaluated")

    return {
        "data": {
            "allowed": allowed,
            "action": action,
            "resource": resource,
            "actor": actor.username,
            "role": actor.role,
            "groups": actor.groups,
            "explanation": explanation,
        }
    }
