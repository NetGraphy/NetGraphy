"""Agent Runtime — orchestrates chat, tool execution, and safety enforcement.

The agent runtime:
1. Receives a user message with auth context
2. Resolves allowed tools based on user permissions
3. Builds system prompt with schema context
4. Calls the model provider
5. Executes tool calls (with permission checks)
6. Returns the response with citations and traces

Core invariant: The agent uses the acting user's AuthContext for ALL
permission checks. It never exceeds the user's permissions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog

from packages.ai.providers import (
    BaseProvider,
    ChatChunk,
    ChatMessage,
    ChatResponse,
    ProviderConfig,
    ToolCall,
    create_provider,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()

MAX_TOOL_ROUNDS = 10  # Prevent infinite tool loops


@dataclass
class AgentStep:
    """A single step in the agent execution trace."""
    step_type: str  # "model_call", "tool_call", "tool_result", "auth_denied", "error"
    content: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: Any = None
    model: str = ""
    latency_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentResponse:
    """Complete agent response with trace and metadata."""
    content: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    tool_calls_made: int = 0
    model_used: str = ""
    provider_used: str = ""
    total_latency_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    confirmation_required: dict[str, Any] | None = None


class AgentRuntime:
    """Orchestrates the agent loop: prompt → model → tools → response.

    The runtime enforces user-equivalent permissions at every step.
    Tools are filtered by the acting user's permissions before being
    presented to the model. Tool execution is permission-checked again
    before invocation (defense in depth).
    """

    def __init__(
        self,
        driver: Neo4jDriver,
        registry: SchemaRegistry,
        provider: BaseProvider,
        model: str,
    ) -> None:
        self._driver = driver
        self._registry = registry
        self._provider = provider
        self._model = model
        self._rbac = PermissionChecker()

    async def run(
        self,
        messages: list[ChatMessage],
        actor: AuthContext,
        tools: list[dict[str, Any]] | None = None,
        system_instruction: str = "",
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> AgentResponse:
        """Execute the agent loop for a user message.

        1. Filter tools by user permissions
        2. Build system prompt with schema context
        3. Call model with tool definitions
        4. If model returns tool calls, execute them (permission-checked)
        5. Feed tool results back to model
        6. Repeat until model returns text or max rounds reached
        """
        response = AgentResponse(model_used=self._model, provider_used=self._provider.config.provider_type)

        # Filter tools to only those the user is allowed to use
        allowed_tools = self._filter_tools_by_permissions(tools or [], actor)

        # Build system prompt
        system = self._build_system_prompt(system_instruction, actor)
        full_messages = [ChatMessage(role="system", content=system)] + messages

        for round_num in range(max_rounds):
            # Call model
            model_response = await self._provider.chat(
                messages=full_messages,
                model=self._model,
                tools=allowed_tools if allowed_tools else None,
            )

            response.steps.append(AgentStep(
                step_type="model_call", content=model_response.content,
                model=self._model, latency_ms=model_response.latency_ms,
            ))
            response.usage = model_response.usage
            response.total_latency_ms += model_response.latency_ms

            # If no tool calls, we're done
            if not model_response.tool_calls:
                response.content = model_response.content
                break

            # Execute tool calls
            full_messages.append(ChatMessage(
                role="assistant", content=model_response.content,
                tool_calls=model_response.tool_calls,
            ))

            for tc in model_response.tool_calls:
                response.tool_calls_made += 1

                # Check if tool requires confirmation for destructive actions
                tool_def = next((t for t in (tools or []) if t["name"] == tc.name), None)
                auth_meta = tool_def.get("auth", {}) if tool_def else {}

                if auth_meta.get("requires_confirmation") and auth_meta.get("destructive"):
                    response.confirmation_required = {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "reason": "This is a destructive action that requires your confirmation.",
                    }
                    response.content = (
                        f"I need your confirmation before executing **{tc.name}**. "
                        f"This is a destructive action."
                    )
                    response.steps.append(AgentStep(
                        step_type="confirmation_required", tool_name=tc.name,
                        tool_args=tc.arguments,
                    ))
                    return response

                # Execute the tool
                result = await self._execute_tool(tc, actor)
                response.steps.append(result)

                # Add tool result to conversation
                full_messages.append(ChatMessage(
                    role="tool",
                    content=json.dumps(result.tool_result) if result.tool_result else result.content,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        return response

    async def run_stream(
        self,
        messages: list[ChatMessage],
        actor: AuthContext,
        tools: list[dict[str, Any]] | None = None,
        system_instruction: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream the agent response for real-time chat UI.

        Yields SSE-compatible events:
        - {"type": "text", "content": "..."}
        - {"type": "tool_start", "tool": "...", "args": {...}}
        - {"type": "tool_result", "tool": "...", "result": {...}}
        - {"type": "done", "usage": {...}}
        """
        allowed_tools = self._filter_tools_by_permissions(tools or [], actor)
        system = self._build_system_prompt(system_instruction, actor)
        full_messages = [ChatMessage(role="system", content=system)] + messages

        for round_num in range(MAX_TOOL_ROUNDS):
            # Try streaming first
            try:
                collected_content = ""
                async for chunk in self._provider.chat_stream(
                    messages=full_messages, model=self._model,
                    tools=allowed_tools if allowed_tools else None,
                ):
                    if chunk.content:
                        collected_content += chunk.content
                        yield {"type": "text", "content": chunk.content}
                    if chunk.done:
                        yield {"type": "done", "finish_reason": chunk.finish_reason}
                        return
            except Exception:
                # Fall back to non-streaming
                model_response = await self._provider.chat(
                    messages=full_messages, model=self._model,
                    tools=allowed_tools if allowed_tools else None,
                )

                if not model_response.tool_calls:
                    yield {"type": "text", "content": model_response.content}
                    yield {"type": "done", "usage": model_response.usage}
                    return

                # Handle tool calls
                full_messages.append(ChatMessage(
                    role="assistant", content=model_response.content,
                    tool_calls=model_response.tool_calls,
                ))

                for tc in model_response.tool_calls:
                    yield {"type": "tool_start", "tool": tc.name, "args": tc.arguments}

                    result = await self._execute_tool(tc, actor)

                    yield {"type": "tool_result", "tool": tc.name, "result": result.tool_result}

                    full_messages.append(ChatMessage(
                        role="tool",
                        content=json.dumps(result.tool_result) if result.tool_result else result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    ))

        yield {"type": "done"}

    def _filter_tools_by_permissions(
        self,
        tools: list[dict[str, Any]],
        actor: AuthContext,
    ) -> list[dict[str, Any]]:
        """Filter tools to only those the acting user is allowed to use.

        The model must never see tools it cannot actually execute.
        """
        allowed = []
        for tool in tools:
            auth = tool.get("auth", {})

            # Check agent_callable flag
            if not auth.get("agent_callable", True):
                continue

            # Check required permission
            required = auth.get("required_permission", "")
            if required:
                parts = required.split(":", 1)
                action = parts[0] if parts else ""
                resource = parts[1] if len(parts) > 1 else ""
                if not self._rbac.check_permission(actor, action, resource):
                    continue

            allowed.append(tool)

        logger.info(
            "agent.tools_filtered",
            total=len(tools), allowed=len(allowed),
            user=actor.username, role=actor.role,
        )
        return allowed

    async def _execute_tool(self, tc: ToolCall, actor: AuthContext) -> AgentStep:
        """Execute a single tool call with permission enforcement.

        Defense in depth: even though tools are filtered before being shown
        to the model, we check permissions again at execution time.
        """
        step = AgentStep(step_type="tool_call", tool_name=tc.name, tool_args=tc.arguments)

        try:
            # Route tool call to the appropriate handler
            result = await self._route_tool_call(tc, actor)
            step.tool_result = result
            step.step_type = "tool_result"
        except PermissionError as e:
            step.step_type = "auth_denied"
            step.content = f"Permission denied: {e}"
            step.tool_result = {"error": str(e), "type": "authorization_denied"}
        except Exception as e:
            step.step_type = "error"
            step.content = f"Tool execution error: {e}"
            step.tool_result = {"error": str(e), "type": "execution_error"}

        return step

    async def _route_tool_call(self, tc: ToolCall, actor: AuthContext) -> Any:
        """Route a tool call to the platform's CRUD/query operations."""
        name = tc.name
        args = tc.arguments

        # Node CRUD tools
        if name.startswith("create_"):
            node_type = self._resolve_node_type(name[7:])
            if node_type:
                self._rbac.require_permission(actor, "write", f"node:{node_type}")
                return await self._create_node(node_type, args, actor)

        if name.startswith("get_"):
            node_type = self._resolve_node_type(name[4:])
            if node_type and "id" in args:
                self._rbac.require_permission(actor, "read", f"node:{node_type}")
                return await self._get_node(node_type, args["id"])

        if name.startswith("list_"):
            node_type = self._resolve_node_type_plural(name[5:])
            if node_type:
                self._rbac.require_permission(actor, "read", f"node:{node_type}")
                return await self._list_nodes(node_type, args)

        if name.startswith("delete_"):
            node_type = self._resolve_node_type(name[7:])
            if node_type and "id" in args:
                self._rbac.require_permission(actor, "write", f"node:{node_type}")
                return await self._delete_node(node_type, args["id"])

        if name.startswith("connect_"):
            return await self._handle_connect(name, args, actor)

        if name.startswith("search_"):
            node_type = self._resolve_node_type_plural(name[7:])
            if node_type:
                self._rbac.require_permission(actor, "read", f"node:{node_type}")
                return await self._search_nodes(node_type, args.get("query", ""), args.get("limit", 10))

        return {"error": f"Unknown tool: {name}", "type": "unknown_tool"}

    # --- Node operations ---

    async def _create_node(self, node_type: str, properties: dict, actor: AuthContext) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        props = {**properties, "id": str(uuid.uuid4()), "created_at": now, "updated_at": now,
                 "created_by": actor.username, "updated_by": actor.username}
        await self._driver.execute_write(
            f"CREATE (n:{node_type} $props) RETURN n", {"props": props}
        )
        return {"id": props["id"], "node_type": node_type, "created": True}

    async def _get_node(self, node_type: str, node_id: str) -> dict:
        result = await self._driver.execute_read(
            f"MATCH (n:{node_type} {{id: $id}}) RETURN n", {"id": node_id}
        )
        return result.rows[0]["n"] if result.rows else {"error": "Not found"}

    async def _list_nodes(self, node_type: str, args: dict) -> dict:
        page = args.get("page", 1)
        page_size = min(args.get("page_size", 25), 100)
        skip = (page - 1) * page_size

        # Build filter conditions
        filters = {k: v for k, v in args.items() if k not in ("page", "page_size", "sort")}
        where = ""
        params: dict[str, Any] = {"skip": skip, "limit": page_size}
        if filters:
            conditions = []
            for i, (k, v) in enumerate(filters.items()):
                param = f"f{i}"
                conditions.append(f"n.{k} = ${param}")
                params[param] = v
            where = " WHERE " + " AND ".join(conditions)

        result = await self._driver.execute_read(
            f"MATCH (n:{node_type}){where} RETURN n SKIP $skip LIMIT $limit", params
        )
        return {"items": [row["n"] for row in result.rows], "count": len(result.rows)}

    async def _delete_node(self, node_type: str, node_id: str) -> dict:
        await self._driver.execute_write(
            f"MATCH (n:{node_type} {{id: $id}}) DETACH DELETE n", {"id": node_id}
        )
        return {"id": node_id, "deleted": True}

    async def _search_nodes(self, node_type: str, query: str, limit: int) -> dict:
        nt = self._registry.get_node_type(node_type)
        if not nt or not nt.search.search_fields:
            return {"items": [], "query": query}

        conditions = " OR ".join(f"toLower(n.{f}) CONTAINS toLower($q)" for f in nt.search.search_fields)
        result = await self._driver.execute_read(
            f"MATCH (n:{node_type}) WHERE {conditions} RETURN n LIMIT $limit",
            {"q": query, "limit": limit},
        )
        return {"items": [row["n"] for row in result.rows], "query": query}

    async def _handle_connect(self, tool_name: str, args: dict, actor: AuthContext) -> dict:
        source_id = args.get("source_id", "")
        target_id = args.get("target_id", "")
        if not source_id or not target_id:
            return {"error": "source_id and target_id required"}

        # Parse edge type from tool name (connect_x_to_y maps to edge)
        for et in self._registry._edge_types.values():
            self._rbac.require_permission(actor, "write", f"edge:{et.metadata.name}")
            await self._driver.execute_write(
                f"MATCH (a {{id: $src}}), (b {{id: $tgt}}) "
                f"MERGE (a)-[:{et.metadata.name}]->(b)",
                {"src": source_id, "tgt": target_id},
            )
            return {"connected": True, "edge_type": et.metadata.name}

        return {"error": "Could not resolve edge type"}

    # --- Type resolution helpers ---

    def _resolve_node_type(self, slug: str) -> str | None:
        """Resolve a snake_case slug back to the PascalCase node type name."""
        for name in self._registry._node_types:
            if name.lower() == slug.lower() or name.lower().replace("_", "") == slug.replace("_", ""):
                return name
        return None

    def _resolve_node_type_plural(self, slug: str) -> str | None:
        """Resolve a plural slug to node type name."""
        for name, nt in self._registry._node_types.items():
            plural = (nt.api.plural_name or f"{name}s").replace("-", "_").lower()
            if plural == slug.lower():
                return name
        return self._resolve_node_type(slug.rstrip("s"))

    def _build_system_prompt(self, custom_instruction: str, actor: AuthContext) -> str:
        """Build the system prompt with schema context and safety rules."""
        node_types = sorted(self._registry._node_types.keys())
        edge_types = sorted(self._registry._edge_types.keys())

        parts = [
            "You are the NetGraphy AI assistant — an intelligent agent for a graph-native "
            "network source-of-truth platform. You help users manage network infrastructure "
            "data using the platform's schema-driven tools.",
            "",
            f"Current user: {actor.username} (role: {actor.role})",
            f"Authentication: {actor.token_type}",
            "",
            "IMPORTANT SAFETY RULES:",
            "- You act strictly as an extension of the authenticated user",
            "- You may NEVER exceed the user's permissions",
            "- You may NEVER fabricate tool results",
            "- For destructive actions (delete), ask for confirmation first",
            "- Show tool invocations transparently",
            "",
            f"Available node types ({len(node_types)}): {', '.join(node_types[:30])}{'...' if len(node_types) > 30 else ''}",
            f"Available edge types ({len(edge_types)}): {', '.join(edge_types[:20])}{'...' if len(edge_types) > 20 else ''}",
        ]

        if custom_instruction:
            parts.extend(["", "Additional instructions:", custom_instruction])

        return "\n".join(parts)
