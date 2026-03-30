"""Agent Chat Gateway — streaming chat API with tool execution, conversation management,
and provider configuration.

Supports:
- Streaming SSE responses for real-time chat
- Non-streaming endpoint for programmatic use
- Conversation CRUD with tenant isolation
- Provider/model configuration
- External agent access
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse

from netgraphy_api.dependencies import (
    get_auth_context,
    get_graph_driver,
    get_rbac,
    get_schema_registry,
)
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()
router = APIRouter()


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

async def _get_provider_and_model(driver: Neo4jDriver) -> tuple[Any, str]:
    """Load the configured provider and model from Neo4j, or fall back to defaults."""
    from packages.ai.providers import ProviderConfig, create_provider

    # Try to load from config
    result = await driver.execute_read(
        "MATCH (p:_AgentProvider {enabled: true}) RETURN p ORDER BY p.name LIMIT 1", {}
    )
    if result.rows:
        cfg = result.rows[0]["p"]
        provider_config = ProviderConfig(
            id=cfg.get("id", ""), name=cfg.get("name", ""),
            provider_type=cfg.get("provider_type", "anthropic"),
            api_key=cfg.get("api_key", ""),
            api_base=cfg.get("api_base", ""),
        )
        model = cfg.get("default_model", "claude-sonnet-4-20250514")
        return create_provider(provider_config), model

    # Fall back to environment variable
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="No AI provider configured. Add one in Admin > AI Configuration.")

    provider_type = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openai"
    default_model = "claude-sonnet-4-20250514" if provider_type == "anthropic" else "gpt-4o"

    provider_config = ProviderConfig(
        id="env-default", name="Environment Default",
        provider_type=provider_type, api_key=api_key,
    )
    return create_provider(provider_config), default_model


MAX_TOOLS = 80  # Stay well under provider limits (OpenAI=128, Anthropic=4096)


async def _get_tools_for_user(
    registry: SchemaRegistry,
    actor: AuthContext,
    message: str = "",
) -> list[dict[str, Any]]:
    """Get MCP tools filtered by user permissions and relevance to the message.

    With 52+ node types generating 600+ tools, we can't send them all to
    the model. Instead we:
    1. Score tools by relevance to the user's message
    2. Always include core CRUD tools for the most common types
    3. Cap at MAX_TOOLS to stay within provider limits
    """
    from packages.schema_engine.generators.engine import GenerationEngine
    engine = GenerationEngine(registry)
    manifest = engine.generate()
    all_tools = manifest.mcp_tools

    if len(all_tools) <= MAX_TOOLS:
        return all_tools

    # Score each tool by keyword relevance to the message
    msg_lower = message.lower()
    msg_words = set(msg_lower.split())

    scored: list[tuple[float, dict]] = []
    for tool in all_tools:
        score = 0.0
        name = tool.get("name", "").lower()
        desc = tool.get("description", "").lower()
        node_type = (tool.get("node_type") or "").lower()
        category = tool.get("category", "")

        # Boost if message mentions the node type or tool keywords
        for word in msg_words:
            if len(word) < 3:
                continue
            if word in name:
                score += 10
            if word in node_type:
                score += 8
            if word in desc:
                score += 3

        # Always include tools for core types
        core_types = {"device", "interface", "prefix", "ipaddress", "vlan", "site", "location", "circuit", "provider"}
        if node_type in core_types:
            score += 5

        # Strongly boost query/find/count tools (relationship-aware, production grade)
        if category == "query":
            score += 6
        if category == "aggregate":
            score += 5
        if category == "lookup":
            score += 4
        if category in ("crud", "search"):
            score += 2

        # Prefer query tools over list tools
        if name.startswith("query_"):
            score += 4
        elif name.startswith("find_"):
            score += 3
        elif name.startswith("count_"):
            score += 3
        elif name.startswith("get_") and "_by_" in name:
            score += 3

        scored.append((score, tool))

    # Sort by score descending, take top MAX_TOOLS
    scored.sort(key=lambda x: x[0], reverse=True)
    return [tool for _, tool in scored[:MAX_TOOLS]]


# --------------------------------------------------------------------------- #
#  Chat Endpoints                                                              #
# --------------------------------------------------------------------------- #


@router.post("/chat")
async def chat(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Send a chat message and get a complete (non-streaming) response.

    Body:
        message: str — user message
        conversation_id: str — (optional) existing conversation
        system_instruction: str — (optional) additional system prompt
    """
    from packages.ai.agent import AgentRuntime
    from packages.ai.conversations import ConversationService
    from packages.ai.providers import ChatMessage

    provider, model = await _get_provider_and_model(driver)
    conv_svc = ConversationService(driver)
    tools = await _get_tools_for_user(registry, actor, body.get("message", ""))

    message = body.get("message", "")
    conv_id = body.get("conversation_id")
    system_instruction = body.get("system_instruction", "")

    # Load configured system prompt from Neo4j if no override provided
    if not system_instruction:
        prompt_result = await driver.execute_read(
            "MATCH (s:_AgentConfig {key: 'system_prompt'}) RETURN s.value AS prompt", {}
        )
        if prompt_result.rows and prompt_result.rows[0].get("prompt"):
            system_instruction = prompt_result.rows[0]["prompt"]

    # Create or load conversation
    if not conv_id:
        conv = await conv_svc.create_conversation(actor.user_id, title=message[:80])
        conv_id = conv["id"]

    # Load conversation history — only user and assistant messages.
    # Tool messages are internal to a single agent turn and cannot be
    # replayed without the full tool_calls structure (OpenAI requires
    # tool messages to follow an assistant message with tool_calls).
    history_msgs = await conv_svc.get_messages(conv_id)
    chat_messages = [
        ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in history_msgs
        if m.get("role") in ("user", "assistant")
    ]
    chat_messages.append(ChatMessage(role="user", content=message))

    # Save user message
    await conv_svc.add_message(conv_id, "user", message)

    # Run agent
    runtime = AgentRuntime(driver, registry, provider, model)
    try:
        response = await runtime.run(
            messages=chat_messages, actor=actor, tools=tools,
            system_instruction=system_instruction,
        )
    except RuntimeError as e:
        # Provider SDK not installed or config error
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("agent.chat_error", error=str(e), user=actor.username)
        raise HTTPException(status_code=502, detail=f"AI provider error: {e}")

    # Save assistant response
    await conv_svc.add_message(
        conv_id, "assistant", response.content,
        metadata={
            "model": response.model_used,
            "provider": response.provider_used,
            "tool_calls": response.tool_calls_made,
            "latency_ms": response.total_latency_ms,
        },
    )

    return {
        "data": {
            "conversation_id": conv_id,
            "content": response.content,
            "model": response.model_used,
            "provider": response.provider_used,
            "tool_calls_made": response.tool_calls_made,
            "steps": [
                {"type": s.step_type, "tool": s.tool_name, "content": s.content[:200]}
                for s in response.steps
            ],
            "usage": response.usage,
            "confirmation_required": response.confirmation_required,
        }
    }


@router.post("/chat/stream")
async def chat_stream(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    registry: SchemaRegistry = Depends(get_schema_registry),
):
    """Stream a chat response via Server-Sent Events (SSE).

    Body:
        message: str — user message
        conversation_id: str — (optional) existing conversation
    """
    from packages.ai.agent import AgentRuntime
    from packages.ai.conversations import ConversationService
    from packages.ai.providers import ChatMessage

    provider, model = await _get_provider_and_model(driver)
    conv_svc = ConversationService(driver)
    tools = await _get_tools_for_user(registry, actor, body.get("message", ""))

    message = body.get("message", "")
    conv_id = body.get("conversation_id")

    if not conv_id:
        conv = await conv_svc.create_conversation(actor.user_id, title=message[:80])
        conv_id = conv["id"]

    history_msgs = await conv_svc.get_messages(conv_id)
    chat_messages = [
        ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in history_msgs
        if m.get("role") in ("user", "assistant")
    ]
    chat_messages.append(ChatMessage(role="user", content=message))

    await conv_svc.add_message(conv_id, "user", message)

    runtime = AgentRuntime(driver, registry, provider, model)

    async def event_generator():
        collected = ""
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': conv_id})}\n\n"

        async for event in runtime.run_stream(
            messages=chat_messages, actor=actor, tools=tools,
        ):
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") == "text":
                collected += event.get("content", "")

        # Save assistant response
        if collected:
            await conv_svc.add_message(conv_id, "assistant", collected)

        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
#  Conversations                                                               #
# --------------------------------------------------------------------------- #


@router.get("/conversations")
async def list_conversations(
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """List the current user's conversations."""
    from packages.ai.conversations import ConversationService
    svc = ConversationService(driver)
    convs = await svc.list_conversations(actor.user_id)
    return {"data": convs}


@router.get("/conversations/{conv_id}")
async def get_conversation(
    conv_id: str,
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Get a conversation with its messages."""
    from packages.ai.conversations import ConversationService
    svc = ConversationService(driver)
    conv = await svc.get_conversation(conv_id, actor.user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"data": conv}


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: str,
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Delete a conversation and all its messages."""
    from packages.ai.conversations import ConversationService
    svc = ConversationService(driver)
    if not await svc.delete_conversation(conv_id, actor.user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


# --------------------------------------------------------------------------- #
#  Provider Configuration                                                      #
# --------------------------------------------------------------------------- #


@router.get("/providers")
async def list_providers(
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """List configured AI providers."""
    rbac.require_permission(actor, "manage", "user:*")
    result = await driver.execute_read(
        "MATCH (p:_AgentProvider) RETURN p ORDER BY p.name", {}
    )
    providers = []
    for row in result.rows:
        p = row["p"]
        p.pop("api_key", None)  # Never expose API keys
        providers.append(p)
    return {"data": providers}


@router.post("/providers", status_code=201)
async def create_provider(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Configure a new AI provider."""
    rbac.require_permission(actor, "manage", "user:*")

    provider_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    props = {
        "id": provider_id,
        "name": body.get("name", ""),
        "provider_type": body.get("provider_type", "anthropic"),
        "api_key": body.get("api_key", ""),
        "api_base": body.get("api_base", ""),
        "default_model": body.get("default_model", ""),
        "enabled": body.get("enabled", True),
        "created_at": now,
    }

    await driver.execute_write("CREATE (p:_AgentProvider $props)", {"props": props})
    props.pop("api_key")  # Don't return the key
    return {"data": props}


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Update a provider's configuration."""
    rbac.require_permission(actor, "manage", "user:*")

    updates = {k: v for k, v in body.items() if k != "id"}
    if not updates:
        return {"data": "No changes"}

    set_clauses = ", ".join(f"p.{k} = ${k}" for k in updates)
    result = await driver.execute_write(
        f"MATCH (p:_AgentProvider {{id: $id}}) SET {set_clauses} RETURN p",
        {"id": provider_id, **updates},
    )
    if not result.rows:
        raise HTTPException(status_code=404, detail="Provider not found")

    p = result.rows[0]["p"]
    p.pop("api_key", None)
    return {"data": p}


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Delete a provider."""
    rbac.require_permission(actor, "manage", "user:*")
    await driver.execute_write(
        "MATCH (p:_AgentProvider {id: $id}) DELETE p", {"id": provider_id}
    )


# --------------------------------------------------------------------------- #
#  System Prompt Configuration                                                 #
# --------------------------------------------------------------------------- #


@router.get("/system-prompt")
async def get_system_prompt(
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
):
    """Get the configured system prompt for the AI assistant."""
    result = await driver.execute_read(
        "MATCH (s:_AgentConfig {key: 'system_prompt'}) RETURN s", {}
    )
    if result.rows:
        cfg = result.rows[0]["s"]
        return {"data": {"system_prompt": cfg.get("value", ""), "updated_at": cfg.get("updated_at", "")}}
    return {"data": {"system_prompt": "", "updated_at": ""}}


@router.put("/system-prompt")
async def set_system_prompt(
    body: dict[str, Any],
    actor: AuthContext = Depends(get_auth_context),
    driver: Neo4jDriver = Depends(get_graph_driver),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Set the system prompt for the AI assistant.

    Body:
        system_prompt: str — the custom system prompt text
    """
    rbac.require_permission(actor, "manage", "user:*")

    prompt_text = body.get("system_prompt", "")
    now = datetime.now(timezone.utc).isoformat()

    await driver.execute_write(
        "MERGE (s:_AgentConfig {key: 'system_prompt'}) "
        "SET s.value = $value, s.updated_at = $now, s.updated_by = $user",
        {"value": prompt_text, "now": now, "user": actor.username},
    )
    return {"data": {"system_prompt": prompt_text, "updated_at": now}}
