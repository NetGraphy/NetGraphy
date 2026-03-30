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
        from packages.ai.tracing import trace_agent_run, trace_model_call, trace_tool_call

        response = AgentResponse(model_used=self._model, provider_used=self._provider.config.provider_type)

        # Filter tools to only those the user is allowed to use
        allowed_tools = self._filter_tools_by_permissions(tools or [], actor)

        # Build system prompt
        system = self._build_system_prompt(system_instruction, actor)
        full_messages = [ChatMessage(role="system", content=system)] + messages

        user_msg = messages[-1].content if messages else ""
        _run_ctx = trace_agent_run(
            user=actor.username, message=user_msg,
            model=self._model, provider=self._provider.config.provider_type,
        )
        run_meta = _run_ctx.__enter__()

        try:
            for round_num in range(max_rounds):
                # Call model with tracing
                with trace_model_call(
                    model=self._model, provider=self._provider.config.provider_type,
                    tool_count=len(allowed_tools),
                ) as model_meta:
                    model_response = await self._provider.chat(
                        messages=full_messages,
                        model=self._model,
                        tools=allowed_tools if allowed_tools else None,
                    )
                    model_meta["usage"] = model_response.usage
                    model_meta["latency_ms"] = model_response.latency_ms
                    model_meta["finish_reason"] = model_response.finish_reason

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

                    # Execute the tool with tracing
                    with trace_tool_call(tool_name=tc.name, tool_args=tc.arguments) as tool_meta:
                        result = await self._execute_tool(tc, actor)
                        if result.tool_result and isinstance(result.tool_result, dict):
                            tool_meta["result_count"] = len(result.tool_result.get("items", []))
                            if result.tool_result.get("error"):
                                tool_meta["error"] = result.tool_result.get("message", "")

                    response.steps.append(result)

                    # Add tool result to conversation
                    full_messages.append(ChatMessage(
                        role="tool",
                        content=json.dumps(result.tool_result) if result.tool_result else result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    ))

            # Set run metadata for tracing
            run_meta["content"] = response.content
            run_meta["tool_calls"] = response.tool_calls_made
            run_meta["usage"] = response.usage
            run_meta["latency_ms"] = response.total_latency_ms

        finally:
            _run_ctx.__exit__(None, None, None)

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
        """Route a tool call to the platform's query engine or CRUD operations.

        New query/find/count/lookup tools are routed through the MCPToolExecutor
        which provides relationship-aware filtering and safe pagination.
        Legacy CRUD tools are also handled by the executor.
        """
        from packages.query_engine.tool_executor import MCPToolExecutor

        name = tc.name
        args = tc.arguments

        # Permission pre-check based on tool name pattern
        self._check_tool_permission(name, actor)

        # Route all tools through the MCPToolExecutor
        executor = MCPToolExecutor(self._driver, self._registry)
        return await executor.execute_tool(name, args)

    def _check_tool_permission(self, tool_name: str, actor: AuthContext) -> None:
        """Pre-check permissions before tool execution (defense in depth)."""
        # Write operations
        if any(tool_name.startswith(p) for p in ("create_", "update_", "delete_", "connect_", "disconnect_")):
            node_type = self._resolve_node_type_from_tool(tool_name)
            if node_type:
                self._rbac.require_permission(actor, "write", f"node:{node_type}")
            return

        # Read operations (query, find, count, get, list, search, lookup)
        node_type = self._resolve_node_type_from_tool(tool_name)
        if node_type:
            self._rbac.require_permission(actor, "read", f"node:{node_type}")

    def _resolve_node_type_from_tool(self, tool_name: str) -> str | None:
        """Resolve the node type a tool operates on."""
        # Strip known prefixes
        for prefix in ("query_", "find_", "count_", "create_", "get_",
                        "list_", "update_", "delete_", "search_"):
            if tool_name.startswith(prefix):
                slug = tool_name[len(prefix):]
                # For find_ tools, extract the entity part (find_devices_by_location → devices)
                if prefix == "find_" and "_by_" in slug:
                    slug = slug.split("_by_")[0]
                nt = self._resolve_node_type_plural(slug) or self._resolve_node_type(slug)
                if nt:
                    return nt
        return None

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
        """Build the system prompt with schema context, query behavior rules, and safety rules."""
        node_types = sorted(self._registry._node_types.keys())
        edge_types = sorted(self._registry._edge_types.keys())

        # Build relationship summary for key types
        rel_summary: list[str] = []
        for et in list(self._registry._edge_types.values())[:25]:
            src = ", ".join(et.source.node_types[:2])
            tgt = ", ".join(et.target.node_types[:2])
            rel_summary.append(f"  {et.metadata.name}: {src} → {tgt}")

        parts = [
            "You are the NetGraphy AI assistant — an intelligent agent for a graph-native "
            "network source-of-truth platform. You help users manage network infrastructure "
            "data using the platform's schema-driven tools.",
            "",
            f"Current user: {actor.username} (role: {actor.role})",
            "",
            "SAFETY RULES:",
            "- You act strictly as an extension of the authenticated user",
            "- You may NEVER exceed the user's permissions",
            "- You may NEVER fabricate tool results",
            "- For destructive actions (delete), ask for confirmation first",
            "",
            "AUTONOMOUS EXECUTION RULES (CRITICAL):",
            "- NEVER ask the user for permission to try alternative approaches",
            "- If a tool call fails, IMMEDIATELY try a different approach without asking",
            "- Try at least 3 different strategies before reporting failure",
            "- Fallback strategies in order:",
            "  1. Try the query tool with relationship filters",
            "  2. If that fails, find the related object first, then query by its ID",
            "  3. If that fails, use a simpler direct attribute search",
            "  4. If that fails, try listing with basic filters",
            "- NEVER say 'say try fallback' or ask user to confirm retries",
            "- Report RESULTS, not your process. The user wants answers, not status updates.",
            "",
            "QUERY BEHAVIOR RULES (CRITICAL):",
            "- ALWAYS prefer explicit relationship filters over naming conventions",
            "- NEVER infer location from hostname prefixes when a relationship exists",
            "- ALWAYS use query_* tools with structured filters for filtered searches",
            "- ALWAYS use find_*_by_* tools for relationship-based lookups",
            "- NEVER pull broad data and post-filter — use backend filters",
            "- ALWAYS ground answers in explicit query results",
            "- For relationship-based questions (e.g., 'devices in Dallas'), use relationship",
            "  filter paths like located_in.Location.city, NOT hostname matching",
            "- For aggregation questions (e.g., 'how many devices'), use count_* tools",
            "- For exact lookups (e.g., 'find device DAL-RTR01'), use get_*_by_* tools",
            "",
            "FILTER PATH SYNTAX:",
            "- Direct attribute: {\"path\": \"status\", \"operator\": \"eq\", \"value\": \"active\"}",
            "- Relationship traversal: {\"path\": \"located_in.Location.city\", \"operator\": \"contains\", \"value\": \"Dallas\"}",
            "- Relationship existence: {\"path\": \"has_interface\", \"operator\": \"exists\"}",
            "- Relationship count: {\"path\": \"has_interface\", \"operator\": \"count_gt\", \"value\": 10}",
            "",
            f"Available node types ({len(node_types)}): {', '.join(node_types[:30])}{'...' if len(node_types) > 30 else ''}",
            f"Available edge types ({len(edge_types)}): {', '.join(edge_types[:20])}{'...' if len(edge_types) > 20 else ''}",
            "",
            "Key relationships:",
            *rel_summary[:20],
        ]

        if custom_instruction:
            parts.extend(["", "Additional instructions:", custom_instruction])

        return "\n".join(parts)
