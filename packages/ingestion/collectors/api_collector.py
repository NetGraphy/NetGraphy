"""API collector — REST-based device/controller collection via httpx.

Supports basic auth, bearer tokens, and API-key authentication.
URL templates are rendered with Jinja2 against ``DeviceTarget`` fields
so a single ``CollectorCommand`` definition can target many devices.

Response extraction uses JMESPath (optional dependency) when a
``response_path`` is specified on the command.
"""

from __future__ import annotations

import base64
import time
from dataclasses import asdict
from typing import Any

import httpx
import structlog
from jinja2 import BaseLoader, Environment

from packages.ingestion.collectors.base import (
    CollectorCommand,
    CollectorResult,
    DeviceTarget,
)

logger = structlog.get_logger()

# Shared Jinja2 environment for URL template rendering.
_jinja_env = Environment(loader=BaseLoader(), autoescape=False)


class APICollector:
    """Collect JSON data from REST APIs (e.g. controller NBI, cloud APIs)."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    async def collect(
        self,
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> CollectorResult:
        """Call the REST endpoint described by *command* and return JSON.

        The URL is built from ``target.api_base_url`` + the rendered
        ``command.url_template``.  Authentication headers are added
        based on ``command.auth_type`` and ``target.credentials``.
        """
        start = time.monotonic()
        try:
            url = self._build_url(target, command)
            headers = self._build_headers(target, command)

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
            ) as client:
                response = await client.request(
                    method=command.method,
                    url=url,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            # Optionally extract a sub-path from the response.
            data = self._extract_response_path(data, command.response_path)

            elapsed = int((time.monotonic() - start) * 1000)
            logger.info(
                "api_collector.success",
                hostname=target.hostname,
                url=url,
                duration_ms=elapsed,
            )
            return CollectorResult(
                raw_output=data,
                success=True,
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "api_collector.failed",
                hostname=target.hostname,
                error=error_msg,
            )
            return CollectorResult(
                raw_output={},
                success=False,
                error=error_msg,
                duration_ms=elapsed,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_url(target: DeviceTarget, command: CollectorCommand) -> str:
        """Render the full URL from base + template."""
        base = (target.api_base_url or "").rstrip("/")
        if not command.url_template:
            return base

        template = _jinja_env.from_string(command.url_template)
        # Provide all DeviceTarget fields as template variables.
        rendered_path = template.render(**asdict(target))
        return f"{base}/{rendered_path.lstrip('/')}"

    @staticmethod
    def _build_headers(
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> dict[str, str]:
        """Merge explicit headers with auth-derived headers."""
        headers: dict[str, str] = {**command.headers}
        creds = target.credentials
        auth_type = (command.auth_type or "").lower()

        if auth_type == "basic":
            username = creds.get("username", "")
            password = creds.get("password", "")
            token = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        elif auth_type == "bearer":
            token = creds.get("token", creds.get("password", ""))
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key = creds.get("api_key", creds.get("token", ""))
            header_name = creds.get("api_key_header", "X-API-Key")
            headers[header_name] = key

        # Default to JSON accept if not explicitly set.
        headers.setdefault("Accept", "application/json")
        return headers

    @staticmethod
    def _extract_response_path(
        data: Any,
        response_path: str | None,
    ) -> Any:
        """Use JMESPath to extract a sub-path from the response data.

        Falls back to simple dot-notation traversal when jmespath is not
        installed.
        """
        if not response_path:
            return data

        # Try JMESPath first (optional dependency).
        try:
            import jmespath

            return jmespath.search(response_path, data)
        except ImportError:
            pass

        # Simple dot-path fallback: "results.devices" -> data["results"]["devices"]
        current = data
        for segment in response_path.split("."):
            if isinstance(current, dict):
                current = current.get(segment)
            else:
                return data
        return current
