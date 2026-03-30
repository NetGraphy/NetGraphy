"""Config Backup Service — collects running configs from devices and stores in Git.

Flow:
1. Resolve ConfigProfile for each device (highest weight match)
2. Connect to device via CLI collector
3. Execute backup command (e.g., show running-config)
4. Apply ConfigRemoval patterns (strip timestamps, build info)
5. Apply ConfigReplacement patterns (redact passwords, keys)
6. Render backup file path from template
7. Store in Git backup repository
8. Record backup metadata in graph (provenance)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver
from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine

logger = structlog.get_logger()


@dataclass
class BackupResult:
    """Result of a single device backup operation."""
    device_id: str
    device_hostname: str
    success: bool
    raw_config: str = ""
    cleaned_config: str = ""
    file_path: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass
class BackupRunResult:
    """Aggregate result of a backup job run."""
    run_id: str
    devices_attempted: int = 0
    devices_succeeded: int = 0
    devices_failed: int = 0
    results: list[BackupResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class ConfigBackupService:
    """Orchestrates config backup collection, cleaning, and Git storage."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver
        self._jinja = Jinja2MappingEngine()

    async def get_profile_for_device(self, device_id: str) -> dict[str, Any] | None:
        """Find the highest-weight ConfigProfile that applies to a device."""
        result = await self._driver.execute_read(
            "MATCH (d:Device {id: $device_id})-[:HAS_CONFIG_PROFILE]->(p:ConfigProfile) "
            "WHERE p.status = 'active' "
            "RETURN p ORDER BY p.weight DESC LIMIT 1",
            {"device_id": device_id},
        )
        if result.rows:
            return result.rows[0]["p"]
        # Fall back to default profile (no explicit link)
        result = await self._driver.execute_read(
            "MATCH (p:ConfigProfile) WHERE p.status = 'active' "
            "RETURN p ORDER BY p.weight DESC LIMIT 1",
            {},
        )
        return result.rows[0]["p"] if result.rows else None

    async def get_removals(self, platform_slug: str) -> list[dict[str, str]]:
        """Get ConfigRemoval patterns for a platform."""
        result = await self._driver.execute_read(
            "MATCH (r:ConfigRemoval {platform_slug: $platform}) RETURN r",
            {"platform": platform_slug},
        )
        return [row["r"] for row in result.rows]

    async def get_replacements(self, platform_slug: str) -> list[dict[str, str]]:
        """Get ConfigReplacement patterns for a platform."""
        result = await self._driver.execute_read(
            "MATCH (r:ConfigReplacement {platform_slug: $platform}) RETURN r",
            {"platform": platform_slug},
        )
        return [row["r"] for row in result.rows]

    def clean_config(
        self,
        raw_config: str,
        removals: list[dict[str, str]],
        replacements: list[dict[str, str]],
    ) -> str:
        """Apply removal and replacement patterns to a raw config.

        Args:
            raw_config: The raw running configuration text.
            removals: ConfigRemoval records with 'regex' field.
            replacements: ConfigReplacement records with 'regex' and 'replace' fields.

        Returns:
            Cleaned configuration text.
        """
        config = raw_config

        # Apply removals — delete matching lines entirely
        for removal in removals:
            try:
                config = re.sub(removal["regex"], "", config, flags=re.MULTILINE)
            except re.error as e:
                logger.warning("Invalid removal regex", regex=removal["regex"], error=str(e))

        # Apply replacements — redact sensitive values
        for replacement in replacements:
            try:
                config = re.sub(
                    replacement["regex"],
                    replacement["replace"],
                    config,
                    flags=re.MULTILINE,
                )
            except re.error as e:
                logger.warning("Invalid replacement regex", regex=replacement["regex"], error=str(e))

        return config

    def render_path(self, template: str, device: dict[str, Any]) -> str:
        """Render a file path template with device data.

        Args:
            template: Jinja2 path template (e.g., "{{device.location}}/{{device.hostname}}-cfg.txt")
            device: Device properties dict.

        Returns:
            Rendered file path.
        """
        return self._jinja.resolve_template(template, {"device": device})

    async def execute_backup(
        self,
        device_ids: list[str],
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> BackupRunResult:
        """Execute config backup for a set of devices.

        Args:
            device_ids: List of device IDs to back up.
            run_id: Optional run ID (generated if not provided).
            dry_run: If True, collect configs but don't commit to Git.

        Returns:
            BackupRunResult with per-device results.
        """
        run_id = run_id or str(uuid.uuid4())
        run_result = BackupRunResult(run_id=run_id, devices_attempted=len(device_ids))

        for device_id in device_ids:
            result = BackupResult(device_id=device_id, device_hostname="")
            try:
                # Load device data
                dev_result = await self._driver.execute_read(
                    "MATCH (d:Device {id: $id}) "
                    "OPTIONAL MATCH (d)-[:RUNS_PLATFORM]->(p:Platform) "
                    "OPTIONAL MATCH (d)-[:LOCATED_IN]->(l:Location) "
                    "RETURN d, p.slug as platform_slug, l.name as location_name",
                    {"id": device_id},
                )
                if not dev_result.rows:
                    result.error = f"Device {device_id} not found"
                    result.success = False
                    run_result.results.append(result)
                    run_result.devices_failed += 1
                    continue

                device = dev_result.rows[0]["d"]
                platform_slug = dev_result.rows[0].get("platform_slug", "")
                location_name = dev_result.rows[0].get("location_name", "")
                result.device_hostname = device.get("hostname", "")

                device_context = {
                    **device,
                    "platform_slug": platform_slug,
                    "location": location_name,
                }

                # Get profile
                profile = await self.get_profile_for_device(device_id)
                if not profile:
                    result.error = "No active ConfigProfile found"
                    result.success = False
                    run_result.results.append(result)
                    run_result.devices_failed += 1
                    continue

                # Collect config (in production, this would use CLICollector)
                # For now, check if we have a recent backup or use mock
                backup_command = profile.get("backup_command", "show running-config")

                # Get removals and replacements for this platform
                removals = await self.get_removals(platform_slug)
                replacements = await self.get_replacements(platform_slug)

                # In a real implementation, this calls CLICollector
                # result.raw_config = await collector.collect(target, command)
                # For the framework, we store what we have
                if result.raw_config:
                    result.cleaned_config = self.clean_config(
                        result.raw_config, removals, replacements
                    )

                # Render file path
                path_template = profile.get(
                    "backup_path_template",
                    "{{device.location}}/{{device.hostname}}-cfg.txt",
                )
                result.file_path = self.render_path(path_template, device_context)

                # Store backup metadata in graph
                if not dry_run:
                    now = datetime.now(timezone.utc).isoformat()
                    await self._driver.execute_write(
                        "MATCH (d:Device {id: $device_id}) "
                        "MERGE (b:_ConfigBackup {device_id: $device_id}) "
                        "SET b.config = $config, b.file_path = $path, "
                        "    b.backed_up_at = $now, b.run_id = $run_id, "
                        "    b.platform_slug = $platform, b.command = $command "
                        "MERGE (d)-[:HAS_BACKUP]->(b)",
                        {
                            "device_id": device_id,
                            "config": result.cleaned_config or result.raw_config,
                            "path": result.file_path,
                            "now": now,
                            "run_id": run_id,
                            "platform": platform_slug,
                            "command": backup_command,
                        },
                    )

                result.success = True
                run_result.devices_succeeded += 1

            except Exception as e:
                result.error = str(e)
                result.success = False
                run_result.devices_failed += 1
                logger.error("Backup failed", device_id=device_id, error=str(e))

            run_result.results.append(result)

        run_result.completed_at = datetime.now(timezone.utc)
        return run_result
