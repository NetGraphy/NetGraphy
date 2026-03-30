"""Config Compliance Engine — compares backup vs intended configs per feature.

Flow:
1. Load ComplianceRules for the device's platform
2. For each rule/feature, extract matching config sections from backup and intended
3. Compare sections using appropriate diff algorithm (CLI, JSON, XML)
4. Generate ComplianceResult records with missing/extra/remediation
5. A device is compliant only when ALL features are compliant

Improvements over Golden Config:
- Graph-native storage of compliance results with full relationship traversal
- Support for custom compliance functions per rule (not just per-plugin)
- Remediation templates are Jinja2-powered with full context access
- Feature-level severity drives priority-based compliance reporting
"""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


@dataclass
class FeatureCompliance:
    """Compliance result for a single feature on a device."""
    feature_name: str
    rule_name: str
    compliant: bool
    actual_config: str = ""
    intended_config: str = ""
    missing: str = ""
    extra: str = ""
    remediation: str = ""
    ordered: bool = True
    diff_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceCompliance:
    """Aggregate compliance for a device across all features."""
    device_id: str
    device_hostname: str
    platform_slug: str
    compliant: bool = True
    features: list[FeatureCompliance] = field(default_factory=list)
    features_compliant: int = 0
    features_non_compliant: int = 0
    features_total: int = 0
    error: str = ""


@dataclass
class ComplianceRunResult:
    """Aggregate result of a compliance run."""
    run_id: str
    devices_attempted: int = 0
    devices_compliant: int = 0
    devices_non_compliant: int = 0
    devices_errored: int = 0
    results: list[DeviceCompliance] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class ComplianceEngine:
    """Calculates configuration compliance by diffing backup vs intended per feature."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    async def get_rules_for_platform(self, platform_slug: str) -> list[dict[str, Any]]:
        """Load all compliance rules for a given platform."""
        result = await self._driver.execute_read(
            "MATCH (r:ComplianceRule {platform_slug: $platform}) RETURN r ORDER BY r.feature_name",
            {"platform": platform_slug},
        )
        return [row["r"] for row in result.rows]

    async def get_backup_config(self, device_id: str) -> str | None:
        """Load the most recent backup config for a device."""
        result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id})-[:HAS_BACKUP]->(b:_ConfigBackup) RETURN b.config as config",
            {"id": device_id},
        )
        return result.rows[0]["config"] if result.rows else None

    async def get_intended_config(self, device_id: str) -> str | None:
        """Load the most recent intended config for a device."""
        result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id})-[:HAS_INTENDED_CONFIG]->(ic:_IntendedConfig) "
            "RETURN ic.config as config",
            {"id": device_id},
        )
        return result.rows[0]["config"] if result.rows else None

    def extract_feature_config(
        self,
        full_config: str,
        match_config: str,
        config_type: str = "cli",
    ) -> str:
        """Extract the config section matching a feature's match_config patterns.

        For CLI configs: extracts lines starting with any match pattern and their
        indented children (hierarchical extraction).

        For JSON configs: extracts matching top-level keys.
        """
        if config_type == "json":
            return self._extract_json_feature(full_config, match_config)

        return self._extract_cli_feature(full_config, match_config)

    def _extract_cli_feature(self, config: str, match_config: str) -> str:
        """Extract CLI config sections matching root patterns with their children.

        Each line in match_config is a root pattern. We extract lines that start
        with the pattern and all indented child lines that follow.
        """
        if not config or not match_config:
            return ""

        patterns = [line.strip() for line in match_config.strip().splitlines() if line.strip()]
        if not patterns:
            return ""

        lines = config.splitlines()
        extracted: list[str] = []
        in_section = False
        section_indent = 0

        for line in lines:
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)

            # Check if this line starts a matching section
            if any(stripped.startswith(p) or re.match(p, stripped) for p in patterns):
                in_section = True
                section_indent = current_indent
                extracted.append(line)
                continue

            # If we're in a section, check if we're still in the child block
            if in_section:
                if stripped == "" or stripped.startswith("!"):
                    # Blank line or section separator — include and continue
                    extracted.append(line)
                    continue
                if current_indent > section_indent:
                    # Indented child line — part of this section
                    extracted.append(line)
                    continue
                else:
                    # Back to root level — section ended
                    in_section = False

        return "\n".join(extracted)

    def _extract_json_feature(self, config: str, match_config: str) -> str:
        """Extract matching top-level JSON keys."""
        import json

        try:
            data = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            return config

        if not match_config or not match_config.strip():
            return config  # Compare full JSON

        keys = [k.strip() for k in match_config.strip().splitlines() if k.strip()]
        filtered = {k: v for k, v in data.items() if k in keys}
        return json.dumps(filtered, indent=2, sort_keys=True)

    def compute_compliance(
        self,
        actual: str,
        intended: str,
        config_type: str = "cli",
        ordered: bool = False,
    ) -> FeatureCompliance:
        """Compare actual vs intended config sections.

        Returns a FeatureCompliance with missing, extra, and compliance status.
        """
        result = FeatureCompliance(
            feature_name="",
            rule_name="",
            compliant=False,
            actual_config=actual,
            intended_config=intended,
        )

        if config_type == "json":
            return self._compare_json(result, actual, intended, ordered)

        return self._compare_cli(result, actual, intended, ordered)

    def _compare_cli(
        self,
        result: FeatureCompliance,
        actual: str,
        intended: str,
        ordered: bool,
    ) -> FeatureCompliance:
        """Compare CLI config sections line by line."""
        actual_lines = set(
            line.rstrip() for line in actual.splitlines() if line.strip() and not line.strip().startswith("!")
        )
        intended_lines = set(
            line.rstrip() for line in intended.splitlines() if line.strip() and not line.strip().startswith("!")
        )

        missing = intended_lines - actual_lines
        extra = actual_lines - intended_lines

        result.missing = "\n".join(sorted(missing)) if missing else ""
        result.extra = "\n".join(sorted(extra)) if extra else ""
        result.compliant = len(missing) == 0 and len(extra) == 0

        # Check ordering if required
        if ordered and result.compliant:
            actual_ordered = [l.rstrip() for l in actual.splitlines() if l.strip() and not l.strip().startswith("!")]
            intended_ordered = [l.rstrip() for l in intended.splitlines() if l.strip() and not l.strip().startswith("!")]
            result.ordered = actual_ordered == intended_ordered
            if not result.ordered:
                result.compliant = False

        result.diff_summary = {
            "missing_count": len(missing),
            "extra_count": len(extra),
            "actual_line_count": len(actual_lines),
            "intended_line_count": len(intended_lines),
        }

        # Generate unified diff for display
        if not result.compliant:
            diff = difflib.unified_diff(
                actual.splitlines(keepends=True),
                intended.splitlines(keepends=True),
                fromfile="actual",
                tofile="intended",
                lineterm="",
            )
            result.diff_summary["unified_diff"] = "\n".join(diff)

        return result

    def _compare_json(
        self,
        result: FeatureCompliance,
        actual: str,
        intended: str,
        ordered: bool,
    ) -> FeatureCompliance:
        """Compare JSON config structures."""
        import json

        try:
            actual_data = json.loads(actual) if actual else {}
            intended_data = json.loads(intended) if intended else {}
        except (json.JSONDecodeError, TypeError):
            result.compliant = False
            result.missing = "JSON parse error"
            return result

        # Simple recursive comparison
        missing, extra = self._json_diff(intended_data, actual_data)

        result.missing = json.dumps(missing, indent=2) if missing else ""
        result.extra = json.dumps(extra, indent=2) if extra else ""
        result.compliant = not missing and not extra

        result.diff_summary = {
            "missing_keys": len(missing) if isinstance(missing, dict) else 0,
            "extra_keys": len(extra) if isinstance(extra, dict) else 0,
        }

        return result

    def _json_diff(
        self, intended: Any, actual: Any,
    ) -> tuple[Any, Any]:
        """Recursively diff two JSON structures. Returns (missing, extra)."""
        if isinstance(intended, dict) and isinstance(actual, dict):
            missing = {}
            extra = {}
            all_keys = set(intended.keys()) | set(actual.keys())
            for key in all_keys:
                if key not in actual:
                    missing[key] = intended[key]
                elif key not in intended:
                    extra[key] = actual[key]
                else:
                    m, e = self._json_diff(intended[key], actual[key])
                    if m:
                        missing[key] = m
                    if e:
                        extra[key] = e
            return missing, extra
        elif isinstance(intended, list) and isinstance(actual, list):
            missing_items = [i for i in intended if i not in actual]
            extra_items = [i for i in actual if i not in intended]
            return missing_items or None, extra_items or None
        elif intended != actual:
            return intended, actual
        return None, None

    def generate_remediation(
        self,
        compliance: FeatureCompliance,
        rule: dict[str, Any],
        device_context: dict[str, Any] | None = None,
    ) -> str:
        """Generate remediation config for a non-compliant feature.

        Strategies:
        - intended_deploy: Return the intended config section (push it as-is)
        - custom_template: Render a Jinja2 template with compliance context
        - hierconfig: Use hierarchical config diff (future)
        - manual: Return empty (flag for human review)
        """
        if compliance.compliant:
            return ""

        remediation_type = rule.get("remediation_type", "intended_deploy")

        if remediation_type == "intended_deploy":
            return compliance.intended_config

        elif remediation_type == "custom_template":
            template = rule.get("remediation_template", "")
            if template:
                from packages.ingestion.mappers.jinja2_engine import Jinja2MappingEngine
                engine = Jinja2MappingEngine()
                context = {
                    "device": device_context or {},
                    "feature": compliance.feature_name,
                    "intended": compliance.intended_config,
                    "actual": compliance.actual_config,
                    "missing": compliance.missing,
                    "extra": compliance.extra,
                }
                try:
                    return engine.resolve_template(template, context)
                except Exception as e:
                    logger.error("Remediation template failed", error=str(e))
                    return f"! Remediation template error: {e}"
            return compliance.intended_config

        elif remediation_type == "manual":
            return ""

        # Default fallback
        return compliance.intended_config

    async def run_compliance(
        self,
        device_ids: list[str],
        run_id: str | None = None,
    ) -> ComplianceRunResult:
        """Execute compliance check for a set of devices.

        For each device:
        1. Load backup and intended configs
        2. Get platform-specific compliance rules
        3. For each rule, extract and compare feature configs
        4. Generate remediation for non-compliant features
        5. Store ComplianceResult records in graph
        """
        run_id = run_id or str(uuid.uuid4())
        run_result = ComplianceRunResult(run_id=run_id, devices_attempted=len(device_ids))

        for device_id in device_ids:
            device_result = DeviceCompliance(device_id=device_id, device_hostname="", platform_slug="")
            try:
                # Load device metadata
                dev = await self._driver.execute_read(
                    "MATCH (d:Device {id: $id}) "
                    "OPTIONAL MATCH (d)-[:RUNS_PLATFORM]->(p:Platform) "
                    "RETURN d, p.slug as platform_slug",
                    {"id": device_id},
                )
                if not dev.rows:
                    device_result.error = "Device not found"
                    run_result.devices_errored += 1
                    run_result.results.append(device_result)
                    continue

                device = dev.rows[0]["d"]
                device_result.device_hostname = device.get("hostname", "")
                device_result.platform_slug = dev.rows[0].get("platform_slug", "")

                # Load configs
                backup_config = await self.get_backup_config(device_id)
                intended_config = await self.get_intended_config(device_id)

                if not backup_config:
                    device_result.error = "No backup config available — run backup first"
                    run_result.devices_errored += 1
                    run_result.results.append(device_result)
                    continue

                if not intended_config:
                    device_result.error = "No intended config available — run intended generation first"
                    run_result.devices_errored += 1
                    run_result.results.append(device_result)
                    continue

                # Load rules for this platform
                rules = await self.get_rules_for_platform(device_result.platform_slug)
                if not rules:
                    device_result.error = f"No compliance rules for platform {device_result.platform_slug}"
                    run_result.devices_errored += 1
                    run_result.results.append(device_result)
                    continue

                # Check compliance per feature
                device_result.features_total = len(rules)
                all_compliant = True

                for rule in rules:
                    feature_name = rule.get("feature_name", "")
                    match_config = rule.get("match_config", "")
                    config_type = rule.get("config_type", "cli")
                    config_ordered = rule.get("config_ordered", False)

                    # Extract feature sections
                    actual_section = self.extract_feature_config(
                        backup_config, match_config, config_type
                    )
                    intended_section = self.extract_feature_config(
                        intended_config, match_config, config_type
                    )

                    # Compare
                    fc = self.compute_compliance(
                        actual_section, intended_section, config_type, config_ordered
                    )
                    fc.feature_name = feature_name
                    fc.rule_name = rule.get("name", "")

                    # Generate remediation if enabled
                    if rule.get("enable_remediation", True) and not fc.compliant:
                        fc.remediation = self.generate_remediation(fc, rule, device)

                    if fc.compliant:
                        device_result.features_compliant += 1
                    else:
                        device_result.features_non_compliant += 1
                        all_compliant = False

                    device_result.features.append(fc)

                    # Persist compliance result
                    now = datetime.now(timezone.utc).isoformat()
                    await self._driver.execute_write(
                        "MERGE (cr:ComplianceResult {device_id: $device_id, feature_name: $feature}) "
                        "SET cr.device_hostname = $hostname, cr.rule_name = $rule_name, "
                        "    cr.compliant = $compliant, cr.actual_config = $actual, "
                        "    cr.intended_config = $intended, cr.missing = $missing, "
                        "    cr.extra = $extra, cr.remediation = $remediation, "
                        "    cr.ordered = $ordered, cr.diff_summary = $diff, "
                        "    cr.run_id = $run_id, cr.checked_at = $now",
                        {
                            "device_id": device_id,
                            "feature": feature_name,
                            "hostname": device_result.device_hostname,
                            "rule_name": rule.get("name", ""),
                            "compliant": fc.compliant,
                            "actual": fc.actual_config,
                            "intended": fc.intended_config,
                            "missing": fc.missing,
                            "extra": fc.extra,
                            "remediation": fc.remediation,
                            "ordered": fc.ordered,
                            "diff": str(fc.diff_summary),
                            "run_id": run_id,
                            "now": now,
                        },
                    )

                device_result.compliant = all_compliant
                if all_compliant:
                    run_result.devices_compliant += 1
                else:
                    run_result.devices_non_compliant += 1

            except Exception as e:
                device_result.error = str(e)
                run_result.devices_errored += 1
                logger.error("Compliance check failed", device_id=device_id, error=str(e))

            run_result.results.append(device_result)

        run_result.completed_at = datetime.now(timezone.utc)
        return run_result
