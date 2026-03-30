"""Mock collector — fixture-based collection for testing.

Reads canned output from the filesystem so that parser and pipeline
tests can run without real network devices or external APIs.

Fixture layout::

    {fixtures_dir}/{parser_name}/input.txt   -- CLI text fixtures
    {fixtures_dir}/{parser_name}/input.json  -- API JSON fixtures
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from packages.ingestion.collectors.base import (
    CollectorCommand,
    CollectorResult,
    DeviceTarget,
)

logger = structlog.get_logger()


class MockCollector:
    """Return fixture data instead of connecting to a real device."""

    def __init__(self, fixtures_dir: str = "parsers/fixtures") -> None:
        self._fixtures_dir = Path(fixtures_dir)

    async def collect(
        self,
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> CollectorResult:
        """Look up a fixture file matching *command.parser_name* and return its content.

        For CLI commands the fixture is ``{parser_name}/input.txt``.
        For API commands the fixture is ``{parser_name}/input.json``.
        """
        start = time.monotonic()
        parser_name = command.parser_name or command.command.replace(" ", "_")

        if command.collector_type == "api":
            fixture_path = self._fixtures_dir / parser_name / "input.json"
        else:
            fixture_path = self._fixtures_dir / parser_name / "input.txt"

        if not fixture_path.exists():
            elapsed = int((time.monotonic() - start) * 1000)
            error_msg = f"Fixture not found: {fixture_path}"
            logger.warning(
                "mock_collector.fixture_missing",
                hostname=target.hostname,
                parser_name=parser_name,
                path=str(fixture_path),
            )
            return CollectorResult(
                raw_output="" if command.collector_type == "cli" else {},
                success=False,
                error=error_msg,
                duration_ms=elapsed,
            )

        try:
            raw = fixture_path.read_text(encoding="utf-8")
            elapsed = int((time.monotonic() - start) * 1000)

            if command.collector_type == "api":
                output = json.loads(raw)
            else:
                output = raw

            logger.info(
                "mock_collector.success",
                hostname=target.hostname,
                parser_name=parser_name,
                path=str(fixture_path),
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
                "mock_collector.failed",
                hostname=target.hostname,
                error=error_msg,
            )
            return CollectorResult(
                raw_output="" if command.collector_type == "cli" else {},
                success=False,
                error=error_msg,
                duration_ms=elapsed,
            )
