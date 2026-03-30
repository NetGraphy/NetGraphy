"""CLI collector — SSH-based device collection via Netmiko.

Wraps synchronous Netmiko calls in ``asyncio.to_thread`` so the
ingestion pipeline can drive collection concurrently without blocking
the event loop.

Netmiko is imported lazily so that the rest of the ingestion package
can be used (and tested) without installing it.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from packages.ingestion.collectors.base import (
    CollectorCommand,
    CollectorResult,
    DeviceTarget,
)

logger = structlog.get_logger()


class CLICollector:
    """Collect raw CLI output from network devices over SSH."""

    def __init__(
        self,
        timeout: int = 30,
        global_delay_factor: int = 1,
    ) -> None:
        self._timeout = timeout
        self._global_delay_factor = global_delay_factor

    async def collect(
        self,
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> CollectorResult:
        """SSH to *target*, execute *command*, and return raw text output.

        Connection and authentication errors are caught and returned as
        a ``CollectorResult`` with ``success=False`` so that the pipeline
        can continue processing remaining devices.
        """
        start = time.monotonic()
        try:
            output = await asyncio.to_thread(
                self._collect_sync, target, command
            )
            elapsed = int((time.monotonic() - start) * 1000)
            logger.info(
                "cli_collector.success",
                hostname=target.hostname,
                command=command.command,
                duration_ms=elapsed,
            )
            return CollectorResult(
                raw_output=output,
                success=True,
                duration_ms=elapsed,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "cli_collector.failed",
                hostname=target.hostname,
                command=command.command,
                error=error_msg,
            )
            return CollectorResult(
                raw_output="",
                success=False,
                error=error_msg,
                duration_ms=elapsed,
            )

    # ------------------------------------------------------------------
    # Synchronous Netmiko interaction (run in a thread)
    # ------------------------------------------------------------------

    def _collect_sync(
        self,
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> str:
        """Build Netmiko params and execute the command synchronously."""
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:
            raise RuntimeError(
                "netmiko is required for CLI collection. "
                "Install it with: pip install netmiko"
            ) from exc

        device_params = self._build_device_params(target)
        connection = ConnectHandler(**device_params)
        try:
            output: str = connection.send_command(
                command.command,
                read_timeout=self._timeout,
            )
            return output
        finally:
            connection.disconnect()

    def _build_device_params(self, target: DeviceTarget) -> dict[str, Any]:
        """Translate a ``DeviceTarget`` into Netmiko connection kwargs."""
        params: dict[str, Any] = {
            "device_type": target.netmiko_device_type or "autodetect",
            "host": target.management_ip or target.hostname,
            "timeout": self._timeout,
            "global_delay_factor": self._global_delay_factor,
        }

        creds = target.credentials
        if "username" in creds:
            params["username"] = creds["username"]
        if "password" in creds:
            params["password"] = creds["password"]
        if "enable_secret" in creds:
            params["secret"] = creds["enable_secret"]

        return params
