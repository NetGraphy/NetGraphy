"""Intended Config Generation — renders device configs from Jinja2 templates + SoT data.

Flow:
1. Resolve ConfigProfile for device
2. Execute SoT query (Cypher) to aggregate device data
3. Resolve config contexts and merge by weight
4. Load entry-point Jinja2 template from template repo
5. Render intended config with full context (device data + config contexts + custom filters)
6. Store in intended config Git repository
7. Record intended config metadata in graph
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver
from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine
from packages.ingestion.mappers.custom_filters import CustomFilterLoader

logger = structlog.get_logger()


@dataclass
class IntendedResult:
    """Result of intended config generation for a single device."""
    device_id: str
    device_hostname: str
    success: bool
    intended_config: str = ""
    file_path: str = ""
    template_used: str = ""
    context_keys: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class IntendedRunResult:
    """Aggregate result of an intended config generation run."""
    run_id: str
    devices_attempted: int = 0
    devices_succeeded: int = 0
    devices_failed: int = 0
    results: list[IntendedResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class IntendedConfigService:
    """Generates intended configurations by rendering Jinja2 templates with SoT data."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    async def aggregate_sot_data(
        self, device_id: str, sot_query: str | None = None,
    ) -> dict[str, Any]:
        """Execute SoT aggregation query for a device.

        If no custom query is provided, uses a default that collects
        common device properties, interfaces, platform, and location.
        """
        if sot_query:
            result = await self._driver.execute_read(sot_query, {"device_id": device_id})
            if result.rows:
                return result.rows[0]
            return {}

        # Default SoT query — gather common device data
        result = await self._driver.execute_read(
            "MATCH (d:Device {id: $device_id}) "
            "OPTIONAL MATCH (d)-[:RUNS_PLATFORM]->(platform:Platform) "
            "OPTIONAL MATCH (d)-[:LOCATED_IN]->(location:Location) "
            "OPTIONAL MATCH (d)-[:HAS_INTERFACE]->(iface:Interface) "
            "OPTIONAL MATCH (d)-[:RUNS_VERSION]->(sw:SoftwareVersion) "
            "RETURN d AS device, "
            "  platform, location, sw, "
            "  collect(DISTINCT iface) AS interfaces",
            {"device_id": device_id},
        )
        if not result.rows:
            return {}

        row = result.rows[0]
        data: dict[str, Any] = {}

        # Flatten device properties to top level
        device = row.get("device", {})
        if isinstance(device, dict):
            data.update(device)

        # Add related objects
        if row.get("platform"):
            data["platform"] = row["platform"]
            data["platform_slug"] = row["platform"].get("slug", "")
        if row.get("location"):
            data["location"] = row["location"]
        if row.get("sw"):
            data["software_version"] = row["sw"]
        if row.get("interfaces"):
            data["interfaces"] = row["interfaces"]

        return data

    async def resolve_config_contexts(
        self, device: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve and merge all applicable ConfigContexts for a device.

        Contexts are matched by scope (location, role, platform, tags, hostname regex)
        and merged by weight (higher weight wins on conflicts).
        """
        hostname = device.get("hostname", "")
        role = device.get("role", "")
        platform_slug = device.get("platform_slug", "")
        location = device.get("location", {}).get("name", "") if isinstance(device.get("location"), dict) else ""
        tags = device.get("tags", [])

        result = await self._driver.execute_read(
            "MATCH (cc:ConfigContext) WHERE cc.is_active = true "
            "RETURN cc ORDER BY cc.weight ASC",
            {},
        )

        merged: dict[str, Any] = {}

        for row in result.rows:
            cc = row["cc"]

            # Check scope matches
            if not self._context_matches(cc, hostname, role, platform_slug, location, tags):
                continue

            # Deep merge — higher weight overwrites conflicts
            data = cc.get("data", {})
            if isinstance(data, str):
                import json
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue

            if isinstance(data, dict):
                self._deep_merge(merged, data)

        return merged

    def _context_matches(
        self,
        cc: dict[str, Any],
        hostname: str,
        role: str,
        platform_slug: str,
        location: str,
        tags: list[str],
    ) -> bool:
        """Check if a ConfigContext matches the given device attributes."""
        import re as _re

        has_scope = False

        # Location scope
        scope_locations = cc.get("scope_locations", [])
        if scope_locations:
            has_scope = True
            if isinstance(scope_locations, str):
                import json
                scope_locations = json.loads(scope_locations) if scope_locations else []
            if location not in scope_locations:
                return False

        # Role scope
        scope_roles = cc.get("scope_roles", [])
        if scope_roles:
            has_scope = True
            if isinstance(scope_roles, str):
                import json
                scope_roles = json.loads(scope_roles) if scope_roles else []
            if role not in scope_roles:
                return False

        # Platform scope
        scope_platforms = cc.get("scope_platforms", [])
        if scope_platforms:
            has_scope = True
            if isinstance(scope_platforms, str):
                import json
                scope_platforms = json.loads(scope_platforms) if scope_platforms else []
            if platform_slug not in scope_platforms:
                return False

        # Tag scope
        scope_tags = cc.get("scope_tags", [])
        if scope_tags:
            has_scope = True
            if isinstance(scope_tags, str):
                import json
                scope_tags = json.loads(scope_tags) if scope_tags else []
            if not any(t in scope_tags for t in tags):
                return False

        # Hostname regex scope
        hostname_regex = cc.get("scope_hostname_regex", "")
        if hostname_regex:
            has_scope = True
            try:
                if not _re.match(hostname_regex, hostname):
                    return False
            except _re.error:
                return False

        # If no scope defined, context is global
        return True

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base. Override wins on conflicts."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    async def _load_custom_filters(self) -> dict[str, Any]:
        """Load all active custom Jinja2 filters from the graph."""
        result = await self._driver.execute_read(
            "MATCH (f:_JinjaFilter) WHERE f.is_active = true RETURN f", {}
        )
        filters = {}
        for row in result.rows:
            fname = row["f"]["name"]
            source = row["f"]["python_source"]
            try:
                fn = CustomFilterLoader.load_from_source(fname, source)
                filters[fname] = fn
            except Exception as e:
                logger.warning("Failed to load custom filter", filter=fname, error=str(e))
        return filters

    async def generate_intended(
        self,
        device_ids: list[str],
        run_id: str | None = None,
        dry_run: bool = False,
        template_repo_path: str | None = None,
    ) -> IntendedRunResult:
        """Generate intended configs for a set of devices.

        Args:
            device_ids: Devices to generate configs for.
            run_id: Optional run ID.
            dry_run: If True, generate but don't persist.
            template_repo_path: Local filesystem path to cloned template repo.
        """
        run_id = run_id or str(uuid.uuid4())
        run_result = IntendedRunResult(run_id=run_id, devices_attempted=len(device_ids))

        # Load custom filters once for the entire run
        custom_filters = await self._load_custom_filters()

        for device_id in device_ids:
            result = IntendedResult(device_id=device_id, device_hostname="")
            try:
                # Aggregate SoT data
                sot_data = await self.aggregate_sot_data(device_id)
                if not sot_data:
                    result.error = f"No SoT data for device {device_id}"
                    result.success = False
                    run_result.results.append(result)
                    run_result.devices_failed += 1
                    continue

                result.device_hostname = sot_data.get("hostname", "")

                # Resolve config contexts
                config_context = await self.resolve_config_contexts(sot_data)
                result.context_keys = list(config_context.keys())

                # Build full template context
                template_context: dict[str, Any] = {
                    **sot_data,
                    "config_context": config_context,
                }

                # Create Jinja2 engine with custom filters
                engine = Jinja2MappingEngine()
                engine.register_filters(custom_filters)

                # Get profile for template path
                from packages.iac.backup import ConfigBackupService
                backup_svc = ConfigBackupService(self._driver)
                profile = await backup_svc.get_profile_for_device(device_id)

                if not profile:
                    result.error = "No active ConfigProfile"
                    result.success = False
                    run_result.results.append(result)
                    run_result.devices_failed += 1
                    continue

                # Resolve template entry point
                entry_template = profile.get("template_entry_template", "{{device.platform_slug}}.j2")
                device_ctx = {**sot_data, "platform_slug": sot_data.get("platform_slug", "")}
                template_filename = engine.resolve_template(
                    entry_template, {"device": device_ctx}
                )
                result.template_used = template_filename

                # Load and render template
                if template_repo_path:
                    template_path = Path(template_repo_path) / template_filename
                    if template_path.exists():
                        template_content = template_path.read_text()
                        result.intended_config = engine.resolve_template(
                            template_content, template_context
                        )
                    else:
                        result.error = f"Template not found: {template_filename}"
                        result.success = False
                        run_result.results.append(result)
                        run_result.devices_failed += 1
                        continue
                else:
                    # No local repo — try loading template from graph
                    tmpl_result = await self._driver.execute_read(
                        "MATCH (t:_JinjaTemplate {name: $name}) RETURN t.content as content",
                        {"name": template_filename},
                    )
                    if tmpl_result.rows:
                        result.intended_config = engine.resolve_template(
                            tmpl_result.rows[0]["content"], template_context
                        )
                    else:
                        result.error = f"Template '{template_filename}' not found in repo or graph"
                        result.success = False
                        run_result.results.append(result)
                        run_result.devices_failed += 1
                        continue

                # Render intended file path
                intended_path_template = profile.get(
                    "intended_path_template",
                    "{{device.location}}/{{device.hostname}}-intended.txt",
                )
                result.file_path = engine.resolve_template(
                    intended_path_template, {"device": device_ctx}
                )

                # Persist intended config
                if not dry_run and result.intended_config:
                    now = datetime.now(timezone.utc).isoformat()
                    await self._driver.execute_write(
                        "MATCH (d:Device {id: $device_id}) "
                        "MERGE (ic:_IntendedConfig {device_id: $device_id}) "
                        "SET ic.config = $config, ic.file_path = $path, "
                        "    ic.generated_at = $now, ic.run_id = $run_id, "
                        "    ic.template_used = $template "
                        "MERGE (d)-[:HAS_INTENDED_CONFIG]->(ic)",
                        {
                            "device_id": device_id,
                            "config": result.intended_config,
                            "path": result.file_path,
                            "now": now,
                            "run_id": run_id,
                            "template": template_filename,
                        },
                    )

                result.success = True
                run_result.devices_succeeded += 1

            except Exception as e:
                result.error = str(e)
                result.success = False
                run_result.devices_failed += 1
                logger.error("Intended gen failed", device_id=device_id, error=str(e))

            run_result.results.append(result)

        run_result.completed_at = datetime.now(timezone.utc)
        return run_result
