"""Infrastructure as Code API endpoints.

Provides REST API for config backup, intended config generation,
compliance checking, remediation, config contexts, and JSON transformation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from netgraphy_api.dependencies import get_graph_driver, get_auth_context, get_rbac
from packages.auth.models import AuthContext
from packages.auth.rbac import PermissionChecker
from packages.graph_db.driver import Neo4jDriver

router = APIRouter()


# ---------------------------------------------------------------------------
#  Config Profiles
# ---------------------------------------------------------------------------


@router.get("/profiles")
async def list_config_profiles(
    status: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List IaC configuration profiles."""
    where = " WHERE p.status = $status" if status else ""
    params: dict[str, Any] = {"status": status} if status else {}
    result = await driver.execute_read(
        f"MATCH (p:ConfigProfile){where} RETURN p ORDER BY p.weight DESC", params
    )
    return {"data": [row["p"] for row in result.rows]}


@router.post("/profiles", status_code=201)
async def create_config_profile(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a new IaC configuration profile."""
    rbac.require_permission(actor, "manage", "iac")
    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    body["id"] = profile_id
    body["created_at"] = now
    body["updated_at"] = now

    await driver.execute_write(
        "CREATE (p:ConfigProfile $props) RETURN p",
        {"props": body},
    )
    return {"data": {"id": profile_id, "name": body.get("name")}}


# ---------------------------------------------------------------------------
#  Compliance Features & Rules
# ---------------------------------------------------------------------------


@router.get("/compliance/features")
async def list_compliance_features(
    category: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List compliance features."""
    where = " WHERE f.category = $category" if category else ""
    params: dict[str, Any] = {"category": category} if category else {}
    result = await driver.execute_read(
        f"MATCH (f:ComplianceFeature){where} RETURN f ORDER BY f.name", params
    )
    return {"data": [row["f"] for row in result.rows]}


@router.post("/compliance/features", status_code=201)
async def create_compliance_feature(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a compliance feature."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())
    await driver.execute_write("CREATE (f:ComplianceFeature $props)", {"props": body})
    return {"data": body}


@router.get("/compliance/rules")
async def list_compliance_rules(
    platform: str | None = None,
    feature: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List compliance rules, optionally filtered by platform or feature."""
    wheres: list[str] = []
    params: dict[str, Any] = {}
    if platform:
        wheres.append("r.platform_slug = $platform")
        params["platform"] = platform
    if feature:
        wheres.append("r.feature_name = $feature")
        params["feature"] = feature
    where = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    result = await driver.execute_read(
        f"MATCH (r:ComplianceRule){where} RETURN r ORDER BY r.platform_slug, r.feature_name",
        params,
    )
    return {"data": [row["r"] for row in result.rows]}


@router.post("/compliance/rules", status_code=201)
async def create_compliance_rule(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a per-platform compliance rule."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())
    await driver.execute_write("CREATE (r:ComplianceRule $props)", {"props": body})

    # Link to feature if it exists
    if body.get("feature_name"):
        await driver.execute_write(
            "MATCH (f:ComplianceFeature {name: $feature}), (r:ComplianceRule {id: $rule_id}) "
            "MERGE (f)-[:HAS_COMPLIANCE_RULE]->(r)",
            {"feature": body["feature_name"], "rule_id": body["id"]},
        )
    return {"data": body}


# ---------------------------------------------------------------------------
#  Config Backup
# ---------------------------------------------------------------------------


@router.post("/backup/run", status_code=202)
async def run_backup(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Trigger a config backup run for specified devices.

    Body:
        device_ids: list[str] — devices to back up (or empty for all in scope)
        dry_run: bool — preview without committing to Git
    """
    rbac.require_permission(actor, "execute", "iac")
    from packages.iac.backup import ConfigBackupService

    svc = ConfigBackupService(driver)
    device_ids = body.get("device_ids", [])
    dry_run = body.get("dry_run", False)

    if not device_ids:
        # Get all devices in scope
        result = await driver.execute_read(
            "MATCH (d:Device) WHERE d.status = 'active' RETURN d.id as id", {}
        )
        device_ids = [row["id"] for row in result.rows]

    run_result = await svc.execute_backup(device_ids, dry_run=dry_run)

    return {
        "data": {
            "run_id": run_result.run_id,
            "devices_attempted": run_result.devices_attempted,
            "devices_succeeded": run_result.devices_succeeded,
            "devices_failed": run_result.devices_failed,
            "results": [
                {
                    "device_hostname": r.device_hostname,
                    "success": r.success,
                    "file_path": r.file_path,
                    "error": r.error,
                }
                for r in run_result.results
            ],
        }
    }


# ---------------------------------------------------------------------------
#  Intended Config Generation
# ---------------------------------------------------------------------------


@router.post("/intended/run", status_code=202)
async def run_intended(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Trigger intended config generation for specified devices.

    Body:
        device_ids: list[str] — devices to generate (or empty for all in scope)
        dry_run: bool — preview without persisting
    """
    rbac.require_permission(actor, "execute", "iac")
    from packages.iac.intended import IntendedConfigService

    svc = IntendedConfigService(driver)
    device_ids = body.get("device_ids", [])
    dry_run = body.get("dry_run", False)

    if not device_ids:
        result = await driver.execute_read(
            "MATCH (d:Device) WHERE d.status = 'active' RETURN d.id as id", {}
        )
        device_ids = [row["id"] for row in result.rows]

    run_result = await svc.generate_intended(device_ids, dry_run=dry_run)

    return {
        "data": {
            "run_id": run_result.run_id,
            "devices_attempted": run_result.devices_attempted,
            "devices_succeeded": run_result.devices_succeeded,
            "devices_failed": run_result.devices_failed,
            "results": [
                {
                    "device_hostname": r.device_hostname,
                    "success": r.success,
                    "template_used": r.template_used,
                    "file_path": r.file_path,
                    "context_keys": r.context_keys,
                    "intended_config": r.intended_config[:500] if r.intended_config else "",
                    "error": r.error,
                }
                for r in run_result.results
            ],
        }
    }


# ---------------------------------------------------------------------------
#  Config Compliance
# ---------------------------------------------------------------------------


@router.post("/compliance/run", status_code=202)
async def run_compliance(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Run compliance check for specified devices.

    Body:
        device_ids: list[str] — devices to check (or empty for all with backups)
    """
    rbac.require_permission(actor, "execute", "iac")
    from packages.iac.compliance import ComplianceEngine

    engine = ComplianceEngine(driver)
    device_ids = body.get("device_ids", [])

    if not device_ids:
        result = await driver.execute_read(
            "MATCH (d:Device)-[:HAS_BACKUP]->(:_ConfigBackup) "
            "RETURN DISTINCT d.id as id",
            {},
        )
        device_ids = [row["id"] for row in result.rows]

    run_result = await engine.run_compliance(device_ids)

    return {
        "data": {
            "run_id": run_result.run_id,
            "devices_attempted": run_result.devices_attempted,
            "devices_compliant": run_result.devices_compliant,
            "devices_non_compliant": run_result.devices_non_compliant,
            "devices_errored": run_result.devices_errored,
            "results": [
                {
                    "device_hostname": r.device_hostname,
                    "platform_slug": r.platform_slug,
                    "compliant": r.compliant,
                    "features_total": r.features_total,
                    "features_compliant": r.features_compliant,
                    "features_non_compliant": r.features_non_compliant,
                    "error": r.error,
                    "features": [
                        {
                            "feature_name": f.feature_name,
                            "compliant": f.compliant,
                            "missing_lines": len(f.missing.splitlines()) if f.missing else 0,
                            "extra_lines": len(f.extra.splitlines()) if f.extra else 0,
                            "has_remediation": bool(f.remediation),
                        }
                        for f in r.features
                    ],
                }
                for r in run_result.results
            ],
        }
    }


@router.get("/compliance/results")
async def list_compliance_results(
    device_hostname: str | None = None,
    feature_name: str | None = None,
    compliant: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List compliance results with filtering."""
    wheres: list[str] = []
    params: dict[str, Any] = {}
    if device_hostname:
        wheres.append("cr.device_hostname CONTAINS $hostname")
        params["hostname"] = device_hostname
    if feature_name:
        wheres.append("cr.feature_name = $feature")
        params["feature"] = feature_name
    if compliant is not None:
        wheres.append("cr.compliant = $compliant")
        params["compliant"] = compliant
    where = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    skip = (page - 1) * page_size
    params.update({"skip": skip, "limit": page_size})

    count_r = await driver.execute_read(
        f"MATCH (cr:ComplianceResult){where} RETURN count(cr) as total", params
    )
    total = count_r.rows[0]["total"] if count_r.rows else 0

    result = await driver.execute_read(
        f"MATCH (cr:ComplianceResult){where} "
        "RETURN cr ORDER BY cr.compliant, cr.device_hostname, cr.feature_name "
        "SKIP $skip LIMIT $limit",
        params,
    )
    return {
        "data": [row["cr"] for row in result.rows],
        "meta": {"total_count": total, "page": page, "page_size": page_size},
    }


@router.get("/compliance/results/{device_id}")
async def get_device_compliance(
    device_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get all compliance results for a specific device."""
    result = await driver.execute_read(
        "MATCH (cr:ComplianceResult {device_id: $device_id}) "
        "RETURN cr ORDER BY cr.feature_name",
        {"device_id": device_id},
    )
    results = [row["cr"] for row in result.rows]
    compliant = all(r.get("compliant", False) for r in results) if results else False

    return {
        "data": {
            "device_id": device_id,
            "overall_compliant": compliant,
            "features": results,
            "total_features": len(results),
            "compliant_count": sum(1 for r in results if r.get("compliant")),
            "non_compliant_count": sum(1 for r in results if not r.get("compliant")),
        }
    }


@router.get("/compliance/summary")
async def compliance_summary(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Get aggregate compliance summary across all devices."""
    result = await driver.execute_read(
        "MATCH (cr:ComplianceResult) "
        "RETURN cr.feature_name as feature, "
        "  count(cr) as total, "
        "  sum(CASE WHEN cr.compliant THEN 1 ELSE 0 END) as compliant, "
        "  sum(CASE WHEN NOT cr.compliant THEN 1 ELSE 0 END) as non_compliant "
        "ORDER BY feature",
        {},
    )
    features = [
        {
            "feature": row["feature"],
            "total": row["total"],
            "compliant": row["compliant"],
            "non_compliant": row["non_compliant"],
            "compliance_pct": round(row["compliant"] / row["total"] * 100, 1) if row["total"] else 0,
        }
        for row in result.rows
    ]

    total = sum(f["total"] for f in features)
    compliant = sum(f["compliant"] for f in features)

    return {
        "data": {
            "overall_compliance_pct": round(compliant / total * 100, 1) if total else 0,
            "total_checks": total,
            "total_compliant": compliant,
            "total_non_compliant": total - compliant,
            "by_feature": features,
        }
    }


# ---------------------------------------------------------------------------
#  Config Contexts
# ---------------------------------------------------------------------------


@router.get("/contexts")
async def list_config_contexts(
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List all config contexts."""
    result = await driver.execute_read(
        "MATCH (cc:ConfigContext) RETURN cc ORDER BY cc.weight DESC, cc.name", {}
    )
    return {"data": [row["cc"] for row in result.rows]}


@router.post("/contexts", status_code=201)
async def create_config_context(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a config context."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    body["created_at"] = now

    # Serialize list/dict fields to JSON strings for Neo4j
    import json
    for field in ["data", "scope_locations", "scope_roles", "scope_platforms", "scope_tags"]:
        if field in body and isinstance(body[field], (list, dict)):
            body[field] = json.dumps(body[field])

    await driver.execute_write("CREATE (cc:ConfigContext $props)", {"props": body})
    return {"data": body}


@router.get("/contexts/resolve/{device_id}")
async def resolve_device_contexts(
    device_id: str,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """Preview the merged config context for a specific device."""
    from packages.iac.intended import IntendedConfigService

    svc = IntendedConfigService(driver)
    sot_data = await svc.aggregate_sot_data(device_id)
    if not sot_data:
        raise HTTPException(status_code=404, detail="Device not found")

    merged = await svc.resolve_config_contexts(sot_data)
    return {
        "data": {
            "device_id": device_id,
            "device_hostname": sot_data.get("hostname", ""),
            "merged_context": merged,
            "context_keys": list(merged.keys()),
        }
    }


# ---------------------------------------------------------------------------
#  JSON Transformation
# ---------------------------------------------------------------------------


@router.get("/transformations")
async def list_transformation_mappings(
    source_platform: str | None = None,
    destination_platform: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List transformation mappings."""
    wheres: list[str] = []
    params: dict[str, Any] = {}
    if source_platform:
        wheres.append("m.source_platform = $sp")
        params["sp"] = source_platform
    if destination_platform:
        wheres.append("m.destination_platform = $dp")
        params["dp"] = destination_platform
    where = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    result = await driver.execute_read(
        f"MATCH (m:TransformationMapping){where} RETURN m ORDER BY m.name", params
    )
    return {"data": [row["m"] for row in result.rows]}


@router.post("/transformations", status_code=201)
async def create_transformation_mapping(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a transformation mapping for hardware replacement."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())

    # Serialize complex fields
    import json
    for field in ["interface_map", "feature_translations", "property_map", "relationship_rules"]:
        if field in body and isinstance(body[field], (list, dict)):
            body[field] = json.dumps(body[field])

    await driver.execute_write("CREATE (m:TransformationMapping $props)", {"props": body})
    return {"data": body}


@router.post("/transformations/preview")
async def preview_transformation(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Preview a device state transformation (dry run).

    Body:
        source_device_id: str — device being replaced
        destination_device_id: str — replacement device
        mapping_name: str — (optional) explicit mapping to use
    """
    rbac.require_permission(actor, "execute", "iac")
    from packages.iac.transformation import TransformationEngine

    engine = TransformationEngine(driver)
    result = await engine.transform_device(
        source_device_id=body.get("source_device_id", ""),
        destination_device_id=body.get("destination_device_id", ""),
        mapping_name=body.get("mapping_name"),
        dry_run=True,
    )

    return {
        "data": {
            "source_hostname": result.source_hostname,
            "destination_hostname": result.destination_hostname,
            "mapping_name": result.mapping_name,
            "success": result.success,
            "interfaces_transformed": [
                {
                    "source_name": it.source_name,
                    "destination_name": it.destination_name,
                    "properties": it.properties_transferred,
                    "warnings": it.warnings,
                }
                for it in result.interfaces_transformed
            ],
            "relationships_transferred": result.relationships_transferred,
            "properties_transferred": result.properties_transferred,
            "errors": result.errors,
            "warnings": result.warnings,
        }
    }


@router.post("/transformations/execute", status_code=202)
async def execute_transformation(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Execute a device state transformation (applies changes to graph).

    Body:
        source_device_id: str — device being replaced
        destination_device_id: str — replacement device
        mapping_name: str — (optional) explicit mapping to use
    """
    rbac.require_permission(actor, "manage", "iac")
    from packages.iac.transformation import TransformationEngine

    engine = TransformationEngine(driver)
    result = await engine.transform_device(
        source_device_id=body.get("source_device_id", ""),
        destination_device_id=body.get("destination_device_id", ""),
        mapping_name=body.get("mapping_name"),
        dry_run=False,
    )

    return {
        "data": {
            "source_hostname": result.source_hostname,
            "destination_hostname": result.destination_hostname,
            "mapping_name": result.mapping_name,
            "success": result.success,
            "interfaces_count": len(result.interfaces_transformed),
            "relationships_count": len(result.relationships_transferred),
            "errors": result.errors,
        }
    }


# ---------------------------------------------------------------------------
#  Config Removals & Replacements
# ---------------------------------------------------------------------------


@router.get("/config-cleaning/removals")
async def list_config_removals(
    platform: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List config removal rules."""
    where = " WHERE r.platform_slug = $platform" if platform else ""
    params: dict[str, Any] = {"platform": platform} if platform else {}
    result = await driver.execute_read(
        f"MATCH (r:ConfigRemoval){where} RETURN r ORDER BY r.platform_slug, r.name", params
    )
    return {"data": [row["r"] for row in result.rows]}


@router.post("/config-cleaning/removals", status_code=201)
async def create_config_removal(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a config removal rule."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())
    await driver.execute_write("CREATE (r:ConfigRemoval $props)", {"props": body})
    return {"data": body}


@router.get("/config-cleaning/replacements")
async def list_config_replacements(
    platform: str | None = None,
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
):
    """List config replacement rules."""
    where = " WHERE r.platform_slug = $platform" if platform else ""
    params: dict[str, Any] = {"platform": platform} if platform else {}
    result = await driver.execute_read(
        f"MATCH (r:ConfigReplacement){where} RETURN r ORDER BY r.platform_slug, r.name", params
    )
    return {"data": [row["r"] for row in result.rows]}


@router.post("/config-cleaning/replacements", status_code=201)
async def create_config_replacement(
    body: dict[str, Any],
    driver: Neo4jDriver = Depends(get_graph_driver),
    actor: AuthContext = Depends(get_auth_context),
    rbac: PermissionChecker = Depends(get_rbac),
):
    """Create a config replacement rule."""
    rbac.require_permission(actor, "manage", "iac")
    body["id"] = str(uuid.uuid4())
    await driver.execute_write("CREATE (r:ConfigReplacement $props)", {"props": body})
    return {"data": body}
