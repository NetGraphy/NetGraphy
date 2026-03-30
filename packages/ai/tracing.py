"""AI Agent OTel Tracing — configurable observability for LLM interactions.

Sends traces to a configurable OTLP endpoint (Phoenix, Jaeger, etc.)
with spans for:
- Agent runs (full conversation turn)
- Model calls (individual LLM requests)
- Tool executions
- Token usage

The endpoint is configured via the _AgentConfig node in Neo4j,
controllable from the AI Configuration UI.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import structlog

logger = structlog.get_logger()

# Module-level state for the tracer
_tracer = None
_configured_endpoint: str | None = None


def _get_tracer():
    """Return the cached tracer instance."""
    return _tracer


def configure_tracing(endpoint: str, service_name: str = "netgraphy-agent") -> bool:
    """Configure OTel tracing with an OTLP HTTP endpoint.

    Call this when the endpoint changes (e.g., from UI configuration).
    Returns True if configuration succeeded.
    """
    global _tracer, _configured_endpoint

    if not endpoint:
        _tracer = None
        _configured_endpoint = None
        logger.info("otel.tracing_disabled")
        return True

    if endpoint == _configured_endpoint and _tracer is not None:
        return True  # Already configured

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
        })

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("netgraphy.agent")
        _configured_endpoint = endpoint

        logger.info("otel.tracing_configured", endpoint=endpoint, service=service_name)
        return True

    except ImportError:
        logger.warning("otel.packages_not_installed")
        return False
    except Exception as e:
        logger.error("otel.configuration_failed", error=str(e))
        return False


async def load_tracing_config(driver) -> None:
    """Load OTel configuration from Neo4j and configure tracing."""
    try:
        result = await driver.execute_read(
            "MATCH (c:_AgentConfig {key: 'otel_config'}) RETURN c", {}
        )
        if result.rows:
            cfg = result.rows[0]["c"]
            endpoint = cfg.get("endpoint", "")
            enabled = cfg.get("enabled", False)
            service_name = cfg.get("service_name", "netgraphy-agent")

            if enabled and endpoint:
                configure_tracing(endpoint, service_name)
            else:
                configure_tracing("")  # Disable
    except Exception as e:
        logger.warning("otel.config_load_failed", error=str(e))


@contextmanager
def trace_agent_run(
    user: str = "",
    message: str = "",
    model: str = "",
    provider: str = "",
) -> Generator[dict[str, Any], None, None]:
    """Context manager for tracing a full agent run."""
    tracer = _get_tracer()
    metadata: dict[str, Any] = {}

    if not tracer:
        yield metadata
        return

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.user", user)
        span.set_attribute("agent.message_preview", message[:200])
        span.set_attribute("agent.model", model)
        span.set_attribute("agent.provider", provider)
        span.set_attribute("gen_ai.system", "netgraphy")

        yield metadata

        # Set result attributes after the run
        if "content" in metadata:
            span.set_attribute("agent.response_length", len(metadata.get("content", "")))
        if "tool_calls" in metadata:
            span.set_attribute("agent.tool_calls_made", metadata.get("tool_calls", 0))
        if "usage" in metadata:
            usage = metadata["usage"]
            span.set_attribute("gen_ai.usage.prompt_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.completion_tokens", usage.get("completion_tokens", 0))
        if "latency_ms" in metadata:
            span.set_attribute("agent.latency_ms", metadata["latency_ms"])
        if "error" in metadata:
            span.set_attribute("error", True)
            span.set_attribute("error.message", metadata["error"])


@contextmanager
def trace_model_call(
    model: str = "",
    provider: str = "",
    tool_count: int = 0,
) -> Generator[dict[str, Any], None, None]:
    """Context manager for tracing a single model call."""
    tracer = _get_tracer()
    metadata: dict[str, Any] = {}

    if not tracer:
        yield metadata
        return

    with tracer.start_as_current_span("agent.model_call") as span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.system", provider)
        span.set_attribute("agent.tool_count", tool_count)

        yield metadata

        if "usage" in metadata:
            usage = metadata["usage"]
            span.set_attribute("gen_ai.usage.prompt_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.completion_tokens", usage.get("completion_tokens", 0))
        if "latency_ms" in metadata:
            span.set_attribute("gen_ai.response.latency_ms", metadata["latency_ms"])
        if "finish_reason" in metadata:
            span.set_attribute("gen_ai.response.finish_reason", metadata["finish_reason"])


@contextmanager
def trace_tool_call(
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Context manager for tracing a tool execution."""
    tracer = _get_tracer()
    metadata: dict[str, Any] = {}

    if not tracer:
        yield metadata
        return

    with tracer.start_as_current_span(f"agent.tool.{tool_name}") as span:
        span.set_attribute("tool.name", tool_name)
        if tool_args:
            # Log filter count but not full args for safety
            span.set_attribute("tool.arg_count", len(tool_args))
            if "filters" in tool_args:
                span.set_attribute("tool.filter_count", len(tool_args["filters"]))

        yield metadata

        if "result_count" in metadata:
            span.set_attribute("tool.result_count", metadata["result_count"])
        if "error" in metadata:
            span.set_attribute("error", True)
            span.set_attribute("error.message", str(metadata["error"]))
        if "latency_ms" in metadata:
            span.set_attribute("tool.latency_ms", metadata["latency_ms"])
