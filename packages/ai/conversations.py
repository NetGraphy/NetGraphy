"""Conversation Service — persists chat history, manages context, enforces tenant isolation.

Conversations and messages are stored as _Conversation and _ConversationMessage
nodes in Neo4j with tenant and actor scoping.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


class ConversationService:
    """Manages conversation lifecycle and message persistence."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    async def create_conversation(
        self, user_id: str, title: str = "", agent_profile: str = "default",
    ) -> dict[str, Any]:
        """Create a new conversation."""
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._driver.execute_write(
            "CREATE (c:_Conversation {id: $id, user_id: $user_id, title: $title, "
            "  agent_profile: $profile, status: 'active', "
            "  created_at: $now, updated_at: $now}) RETURN c",
            {"id": conv_id, "user_id": user_id, "title": title, "profile": agent_profile, "now": now},
        )
        return {"id": conv_id, "title": title, "status": "active", "created_at": now}

    async def list_conversations(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List conversations for a user, most recent first."""
        result = await self._driver.execute_read(
            "MATCH (c:_Conversation {user_id: $user_id}) "
            "RETURN c ORDER BY c.updated_at DESC LIMIT $limit",
            {"user_id": user_id, "limit": limit},
        )
        return [row["c"] for row in result.rows]

    async def get_conversation(self, conv_id: str, user_id: str) -> dict[str, Any] | None:
        """Get a conversation with its messages."""
        result = await self._driver.execute_read(
            "MATCH (c:_Conversation {id: $id, user_id: $user_id}) RETURN c",
            {"id": conv_id, "user_id": user_id},
        )
        if not result.rows:
            return None
        conv = result.rows[0]["c"]

        msgs = await self.get_messages(conv_id)
        conv["messages"] = msgs
        return conv

    async def add_message(
        self, conv_id: str, role: str, content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a message to a conversation."""
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        props: dict[str, Any] = {
            "id": msg_id, "conversation_id": conv_id, "role": role,
            "content": content, "created_at": now,
        }
        if tool_calls:
            props["tool_calls"] = json.dumps(tool_calls)
        if tool_call_id:
            props["tool_call_id"] = tool_call_id
        if metadata:
            props["metadata"] = json.dumps(metadata)

        await self._driver.execute_write(
            "MATCH (c:_Conversation {id: $conv_id}) "
            "SET c.updated_at = $now "
            "CREATE (m:_ConversationMessage $props) "
            "CREATE (c)-[:HAS_MESSAGE]->(m)",
            {"conv_id": conv_id, "props": props, "now": now},
        )
        return props

    async def get_messages(self, conv_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get messages for a conversation in chronological order."""
        result = await self._driver.execute_read(
            "MATCH (c:_Conversation {id: $id})-[:HAS_MESSAGE]->(m:_ConversationMessage) "
            "RETURN m ORDER BY m.created_at LIMIT $limit",
            {"id": conv_id, "limit": limit},
        )
        messages = []
        for row in result.rows:
            msg = row["m"]
            for field in ["tool_calls", "metadata"]:
                val = msg.get(field)
                if isinstance(val, str):
                    try:
                        msg[field] = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
            messages.append(msg)
        return messages

    async def update_title(self, conv_id: str, title: str) -> None:
        """Update conversation title."""
        await self._driver.execute_write(
            "MATCH (c:_Conversation {id: $id}) SET c.title = $title, c.updated_at = $now",
            {"id": conv_id, "title": title, "now": datetime.now(timezone.utc).isoformat()},
        )

    async def delete_conversation(self, conv_id: str, user_id: str) -> bool:
        """Delete a conversation and all its messages."""
        result = await self._driver.execute_write(
            "MATCH (c:_Conversation {id: $id, user_id: $user_id}) "
            "OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:_ConversationMessage) "
            "DETACH DELETE c, m RETURN count(c) as deleted",
            {"id": conv_id, "user_id": user_id},
        )
        return result.rows[0]["deleted"] > 0 if result.rows else False
