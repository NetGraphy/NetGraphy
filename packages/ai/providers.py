"""Model Provider Abstraction Layer — supports multiple LLM providers through a common interface.

Providers: OpenAI-compatible, Anthropic, Azure, AWS Bedrock, GCP Vertex, local/vLLM.
Each provider normalizes its API to a common ChatCompletion interface with tool calling.

The provider is never accessed directly — the ModelRouter selects the appropriate
provider and model based on tenant, use case, and routing policy.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger()


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    """Normalized chat message across all providers."""
    role: str  # system, user, assistant, tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # For tool result messages
    name: str | None = None  # Tool name for tool results
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatChunk:
    """A streaming response chunk."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    done: bool = False


@dataclass
class ChatResponse:
    """Complete (non-streaming) response from a provider."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens
    model: str = ""
    provider: str = ""
    latency_ms: int = 0


@dataclass
class ProviderConfig:
    """Configuration for a model provider instance."""
    id: str
    name: str
    provider_type: str  # openai, anthropic, azure, bedrock, vertex, vllm, ollama
    api_key: str = ""
    api_base: str = ""
    api_version: str = ""
    organization: str = ""
    region: str = ""  # For cloud providers
    project_id: str = ""  # For GCP
    extra: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    max_retries: int = 2
    timeout_seconds: int = 120


class BaseProvider(ABC):
    """Abstract base for all model providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a chat completion request and return the full response."""

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[ChatChunk]:
        """Stream a chat completion response."""

    async def list_models(self) -> list[str]:
        """List available models from this provider."""
        return []

    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
        return self.config.enabled


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API provider."""

    async def chat(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed")

        client = anthropic.AsyncAnthropic(api_key=self.config.api_key)
        start = time.monotonic()

        # Convert messages to Anthropic format
        system = ""
        api_messages = []
        for msg in messages:
            if msg.role == "system":
                system = msg.content
            elif msg.role == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}],
                })
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        # Convert tools to Anthropic format
        api_tools = None
        if tools:
            api_tools = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("inputSchema", t.get("parameters", {}))}
                for t in tools
            ]

        response = await client.messages.create(
            model=model, messages=api_messages, system=system or anthropic.NOT_GIVEN,
            tools=api_tools or anthropic.NOT_GIVEN,
            temperature=temperature, max_tokens=max_tokens,
        )

        elapsed = int((time.monotonic() - start) * 1000)

        # Parse response
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return ChatResponse(
            content=content, tool_calls=tool_calls,
            finish_reason=response.stop_reason or "",
            usage={"prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens},
            model=model, provider="anthropic", latency_ms=elapsed,
        )

    async def chat_stream(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed")

        client = anthropic.AsyncAnthropic(api_key=self.config.api_key)

        system = ""
        api_messages = []
        for msg in messages:
            if msg.role == "system":
                system = msg.content
            elif msg.role == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}],
                })
            else:
                api_messages.append({"role": msg.role, "content": msg.content})

        api_tools = None
        if tools:
            api_tools = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("inputSchema", t.get("parameters", {}))}
                for t in tools
            ]

        async with client.messages.stream(
            model=model, messages=api_messages, system=system or anthropic.NOT_GIVEN,
            tools=api_tools or anthropic.NOT_GIVEN,
            temperature=temperature, max_tokens=max_tokens,
        ) as stream:
            async for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        yield ChatChunk(content=event.delta.text)
                    elif event.type == "message_stop":
                        yield ChatChunk(done=True, finish_reason="end_turn")

    async def list_models(self):
        return ["claude-sonnet-4-20250514", "claude-haiku-4-20250414", "claude-opus-4-20250514"]


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible API provider (OpenAI, Azure, vLLM, Ollama, etc.)."""

    async def chat(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package not installed")

        client_kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.api_base:
            client_kwargs["base_url"] = self.config.api_base
        if self.config.organization:
            client_kwargs["organization"] = self.config.organization

        client = openai.AsyncOpenAI(**client_kwargs)
        start = time.monotonic()

        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        api_tools = None
        if tools:
            api_tools = [
                {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("inputSchema", t.get("parameters", {}))}}
                for t in tools
            ]

        create_kwargs: dict[str, Any] = {
            "model": model, "messages": api_messages, "temperature": temperature, "max_tokens": max_tokens,
        }
        if api_tools:
            create_kwargs["tools"] = api_tools

        response = await client.chat.completions.create(**create_kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return ChatResponse(
            content=choice.message.content or "", tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            usage={"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens} if response.usage else {},
            model=model, provider=self.config.provider_type, latency_ms=elapsed,
        )

    async def chat_stream(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package not installed")

        client_kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.api_base:
            client_kwargs["base_url"] = self.config.api_base

        client = openai.AsyncOpenAI(**client_kwargs)
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        stream = await client.chat.completions.create(
            model=model, messages=api_messages, temperature=temperature,
            max_tokens=max_tokens, stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield ChatChunk(content=chunk.choices[0].delta.content)
            if chunk.choices and chunk.choices[0].finish_reason:
                yield ChatChunk(done=True, finish_reason=chunk.choices[0].finish_reason)


class VertexAIProvider(BaseProvider):
    """Google Cloud Vertex AI provider (Gemini models)."""

    async def chat(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel, Content, Part
        except ImportError:
            raise RuntimeError("google-cloud-aiplatform package not installed")

        start = time.monotonic()

        if self.config.project_id:
            vertexai.init(project=self.config.project_id, location=self.config.region or "us-central1")

        gen_model = GenerativeModel(model)

        # Convert messages to Vertex format
        contents = []
        for msg in messages:
            if msg.role == "system":
                continue  # Vertex handles system differently
            role = "user" if msg.role == "user" else "model"
            contents.append(Content(role=role, parts=[Part.from_text(msg.content)]))

        response = gen_model.generate_content(contents, generation_config={"temperature": temperature, "max_output_tokens": max_tokens})
        elapsed = int((time.monotonic() - start) * 1000)

        return ChatResponse(
            content=response.text or "", tool_calls=[],
            finish_reason="stop", usage={},
            model=model, provider="vertex", latency_ms=elapsed,
        )

    async def chat_stream(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel, Content, Part
        except ImportError:
            raise RuntimeError("google-cloud-aiplatform package not installed")

        if self.config.project_id:
            vertexai.init(project=self.config.project_id, location=self.config.region or "us-central1")

        gen_model = GenerativeModel(model)
        contents = []
        for msg in messages:
            if msg.role == "system":
                continue
            role = "user" if msg.role == "user" else "model"
            contents.append(Content(role=role, parts=[Part.from_text(msg.content)]))

        response = gen_model.generate_content(contents, generation_config={"temperature": temperature, "max_output_tokens": max_tokens}, stream=True)
        for chunk in response:
            if chunk.text:
                yield ChatChunk(content=chunk.text)
        yield ChatChunk(done=True, finish_reason="stop")

    async def list_models(self):
        return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]


class BedrockProvider(BaseProvider):
    """AWS Bedrock provider (Claude, Llama, Titan, etc.)."""

    async def chat(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        try:
            import boto3
            import json as _json
        except ImportError:
            raise RuntimeError("boto3 package not installed")

        start = time.monotonic()
        client = boto3.client(
            "bedrock-runtime",
            region_name=self.config.region or "us-east-1",
            aws_access_key_id=self.config.api_key or None,
            aws_secret_access_key=self.config.extra.get("aws_secret_key") or None,
        )

        # Build messages for Bedrock Converse API
        bedrock_messages = []
        system_text = ""
        for msg in messages:
            if msg.role == "system":
                system_text = msg.content
            else:
                bedrock_messages.append({
                    "role": msg.role,
                    "content": [{"text": msg.content}],
                })

        converse_kwargs: dict[str, Any] = {
            "modelId": model,
            "messages": bedrock_messages,
            "inferenceConfig": {"temperature": temperature, "maxTokens": max_tokens},
        }
        if system_text:
            converse_kwargs["system"] = [{"text": system_text}]

        import asyncio
        response = await asyncio.to_thread(client.converse, **converse_kwargs)
        elapsed = int((time.monotonic() - start) * 1000)

        content = ""
        for block in response.get("output", {}).get("message", {}).get("content", []):
            if "text" in block:
                content += block["text"]

        usage = response.get("usage", {})
        return ChatResponse(
            content=content, tool_calls=[],
            finish_reason=response.get("stopReason", ""),
            usage={"prompt_tokens": usage.get("inputTokens", 0), "completion_tokens": usage.get("outputTokens", 0)},
            model=model, provider="bedrock", latency_ms=elapsed,
        )

    async def chat_stream(self, messages, model, tools=None, temperature=0.7, max_tokens=4096, **kwargs):
        # Bedrock streaming uses ConverseStream — fall back to non-streaming for now
        response = await self.chat(messages, model, tools, temperature, max_tokens, **kwargs)
        yield ChatChunk(content=response.content)
        yield ChatChunk(done=True, finish_reason=response.finish_reason)

    async def list_models(self):
        return ["anthropic.claude-sonnet-4-20250514-v1:0", "anthropic.claude-haiku-4-20250414-v1:0",
                "meta.llama3-70b-instruct-v1:0", "amazon.titan-text-premier-v1:0"]


def create_provider(config: ProviderConfig) -> BaseProvider:
    """Factory function to create a provider from config."""
    if config.provider_type == "anthropic":
        return AnthropicProvider(config)
    elif config.provider_type in ("openai", "azure", "vllm", "ollama", "openai_compatible"):
        return OpenAICompatibleProvider(config)
    elif config.provider_type == "vertex":
        return VertexAIProvider(config)
    elif config.provider_type == "bedrock":
        return BedrockProvider(config)
    else:
        raise ValueError(f"Unknown provider type: {config.provider_type}")
