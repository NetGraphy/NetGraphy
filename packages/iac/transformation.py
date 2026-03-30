"""JSON Transformation Engine — transfers device state for hardware replacement.

Enables automated EoL hardware replacement by:
1. Extracting full device state from the graph (interfaces, IPs, relationships)
2. Applying transformation mappings (interface names, feature syntax, properties)
3. Generating a new device state that can render correct intended config on replacement hardware

Example: Replacing Arista 7050 with Cisco 9300
- Arista Ethernet1 -> Cisco Ethernet1/1
- Arista Management0 -> Cisco mgmt0
- All IP addresses, VLANs, descriptions, and connectivity transferred

The transformation is graph-aware — it transfers not just node properties but
full relationship topology (CONNECTED_TO, MEMBER_OF, etc.)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from packages.graph_db.driver import Neo4jDriver

logger = structlog.get_logger()


@dataclass
class InterfaceTransformation:
    """Result of transforming a single interface."""
    source_name: str
    destination_name: str
    properties_transferred: dict[str, Any] = field(default_factory=dict)
    relationships_transferred: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TransformationResult:
    """Result of a full device state transformation."""
    source_device_id: str
    source_hostname: str
    destination_device_id: str
    destination_hostname: str
    mapping_name: str
    success: bool = False
    interfaces_transformed: list[InterfaceTransformation] = field(default_factory=list)
    properties_transferred: dict[str, Any] = field(default_factory=dict)
    relationships_transferred: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False


class TransformationEngine:
    """Transforms device state between hardware platforms for replacement automation."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    async def get_mapping(
        self,
        source_platform: str,
        destination_platform: str,
        source_model: str | None = None,
        destination_model: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the best transformation mapping for a platform pair.

        Prefers model-specific mappings over platform-level ones.
        """
        # Try model-specific first
        if source_model and destination_model:
            result = await self._driver.execute_read(
                "MATCH (m:TransformationMapping) "
                "WHERE m.source_platform = $sp AND m.destination_platform = $dp "
                "AND m.source_model = $sm AND m.destination_model = $dm "
                "AND m.status = 'active' "
                "RETURN m LIMIT 1",
                {"sp": source_platform, "dp": destination_platform,
                 "sm": source_model, "dm": destination_model},
            )
            if result.rows:
                return result.rows[0]["m"]

        # Fall back to platform-level
        result = await self._driver.execute_read(
            "MATCH (m:TransformationMapping) "
            "WHERE m.source_platform = $sp AND m.destination_platform = $dp "
            "AND m.status = 'active' "
            "RETURN m ORDER BY m.source_model IS NOT NULL DESC LIMIT 1",
            {"sp": source_platform, "dp": destination_platform},
        )
        return result.rows[0]["m"] if result.rows else None

    def transform_interface_name(
        self,
        source_name: str,
        interface_map: dict[str, str],
    ) -> str:
        """Apply interface name transformation using regex patterns.

        Args:
            source_name: Original interface name (e.g., "Ethernet1")
            interface_map: Pattern->replacement dict (e.g., {"Ethernet(\\d+)": "Ethernet1/\\1"})

        Returns:
            Transformed interface name.
        """
        for pattern, replacement in interface_map.items():
            try:
                match = re.match(pattern, source_name)
                if match:
                    return re.sub(pattern, replacement, source_name)
            except re.error as e:
                logger.warning("Invalid interface map regex", pattern=pattern, error=str(e))
        return source_name  # No match — return as-is

    def transform_properties(
        self,
        properties: dict[str, Any],
        property_map: dict[str, Any],
    ) -> dict[str, Any]:
        """Transform node properties according to the property map.

        Property map values can be:
        - "preserve": Keep the value as-is
        - dict: Value translation map
        - "drop": Remove the property
        - "rename:new_name": Rename the property key
        """
        result: dict[str, Any] = {}

        for key, value in properties.items():
            if key.startswith("_"):
                continue  # Skip internal properties

            rule = property_map.get(key, "preserve")

            if rule == "preserve":
                result[key] = value
            elif rule == "drop":
                continue
            elif isinstance(rule, str) and rule.startswith("rename:"):
                new_key = rule.split(":", 1)[1]
                result[new_key] = value
            elif isinstance(rule, dict):
                # Value translation
                str_value = str(value)
                result[key] = rule.get(str_value, value)
            else:
                result[key] = value

        return result

    async def extract_device_state(self, device_id: str) -> dict[str, Any]:
        """Extract complete device state from the graph.

        Returns a structured dict with:
        - device: Core device properties
        - platform: Platform info
        - location: Location info
        - interfaces: List of interfaces with their properties
        - relationships: All non-interface edges
        - connectivity: Interface-to-interface connections (CONNECTED_TO)
        """
        # Device + platform + location
        dev_result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id}) "
            "OPTIONAL MATCH (d)-[:RUNS_PLATFORM]->(p:Platform) "
            "OPTIONAL MATCH (d)-[:LOCATED_IN]->(l:Location) "
            "OPTIONAL MATCH (d)-[:RUNS_VERSION]->(sw:SoftwareVersion) "
            "RETURN d, p, l, sw",
            {"id": device_id},
        )
        if not dev_result.rows:
            return {}

        row = dev_result.rows[0]
        state: dict[str, Any] = {
            "device": row["d"],
            "platform": row.get("p"),
            "location": row.get("l"),
            "software_version": row.get("sw"),
        }

        # Interfaces with all properties
        iface_result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id})-[:HAS_INTERFACE]->(i:Interface) "
            "RETURN i ORDER BY i.name",
            {"id": device_id},
        )
        state["interfaces"] = [row["i"] for row in iface_result.rows]

        # Interface connectivity (CONNECTED_TO)
        conn_result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id})-[:HAS_INTERFACE]->(i:Interface) "
            "-[c:CONNECTED_TO]->(ri:Interface)<-[:HAS_INTERFACE]-(rd:Device) "
            "RETURN i.name as local_interface, ri.name as remote_interface, "
            "  rd.hostname as remote_device, rd.id as remote_device_id, "
            "  properties(c) as connection_props",
            {"id": device_id},
        )
        state["connectivity"] = [
            {
                "local_interface": row["local_interface"],
                "remote_interface": row["remote_interface"],
                "remote_device": row["remote_device"],
                "remote_device_id": row["remote_device_id"],
                "connection_props": row.get("connection_props", {}),
            }
            for row in conn_result.rows
        ]

        # Other relationships (MEMBER_OF, ASSIGNED_VLAN, etc.)
        rel_result = await self._driver.execute_read(
            "MATCH (d:Device {id: $id})-[r]->(t) "
            "WHERE NOT type(r) IN ['HAS_INTERFACE', 'RUNS_PLATFORM', 'LOCATED_IN', "
            "  'RUNS_VERSION', 'HAS_BACKUP', 'HAS_INTENDED_CONFIG', 'HAS_COMPLIANCE_RESULT', "
            "  'HAS_CONFIG_PROFILE'] "
            "RETURN type(r) as edge_type, properties(r) as edge_props, "
            "  labels(t) as target_labels, properties(t) as target_props, t.id as target_id",
            {"id": device_id},
        )
        state["relationships"] = [
            {
                "edge_type": row["edge_type"],
                "edge_props": row.get("edge_props", {}),
                "target_labels": row.get("target_labels", []),
                "target_props": row.get("target_props", {}),
                "target_id": row.get("target_id"),
            }
            for row in rel_result.rows
        ]

        return state

    async def transform_device(
        self,
        source_device_id: str,
        destination_device_id: str,
        mapping_name: str | None = None,
        dry_run: bool = True,
    ) -> TransformationResult:
        """Transform state from source device to destination device.

        Args:
            source_device_id: Device being replaced.
            destination_device_id: Replacement device.
            mapping_name: Explicit mapping name. If None, auto-detected from platforms.
            dry_run: If True, compute transformation without applying.
        """
        result = TransformationResult(
            source_device_id=source_device_id,
            destination_device_id=destination_device_id,
            mapping_name=mapping_name or "",
            dry_run=dry_run,
        )

        try:
            # Extract source state
            source_state = await self.extract_device_state(source_device_id)
            if not source_state:
                result.errors.append("Source device not found")
                return result

            result.source_hostname = source_state["device"].get("hostname", "")

            # Load destination device
            dest_result = await self._driver.execute_read(
                "MATCH (d:Device {id: $id}) "
                "OPTIONAL MATCH (d)-[:RUNS_PLATFORM]->(p:Platform) "
                "RETURN d, p.slug as platform_slug",
                {"id": destination_device_id},
            )
            if not dest_result.rows:
                result.errors.append("Destination device not found")
                return result

            result.destination_hostname = dest_result.rows[0]["d"].get("hostname", "")
            dest_platform = dest_result.rows[0].get("platform_slug", "")

            # Find transformation mapping
            source_platform = source_state.get("platform", {}).get("slug", "") if source_state.get("platform") else ""

            if mapping_name:
                map_result = await self._driver.execute_read(
                    "MATCH (m:TransformationMapping {name: $name}) RETURN m",
                    {"name": mapping_name},
                )
                mapping = map_result.rows[0]["m"] if map_result.rows else None
            else:
                mapping = await self.get_mapping(source_platform, dest_platform)

            if not mapping:
                result.errors.append(
                    f"No transformation mapping found for {source_platform} -> {dest_platform}"
                )
                return result

            result.mapping_name = mapping.get("name", "")

            # Parse mapping configs
            import json

            interface_map = mapping.get("interface_map", {})
            if isinstance(interface_map, str):
                interface_map = json.loads(interface_map)

            property_map = mapping.get("property_map", {})
            if isinstance(property_map, str):
                property_map = json.loads(property_map)

            relationship_rules = mapping.get("relationship_rules", {})
            if isinstance(relationship_rules, str):
                relationship_rules = json.loads(relationship_rules)

            # Transform interfaces
            transfer_edges = relationship_rules.get("transfer", [])
            skip_edges = relationship_rules.get("skip", [])

            for iface in source_state.get("interfaces", []):
                source_name = iface.get("name", "")
                dest_name = self.transform_interface_name(source_name, interface_map)

                # Transform interface properties
                iface_props = self.transform_properties(iface, property_map)
                iface_props["name"] = dest_name

                it = InterfaceTransformation(
                    source_name=source_name,
                    destination_name=dest_name,
                    properties_transferred=iface_props,
                )

                if source_name == dest_name and source_platform != dest_platform:
                    it.warnings.append("Interface name unchanged despite platform change")

                result.interfaces_transformed.append(it)

                # Apply interface to destination device
                if not dry_run:
                    await self._driver.execute_write(
                        "MATCH (d:Device {id: $device_id}) "
                        "MERGE (i:Interface {name: $name})-[:HAS_INTERFACE]-(d) "
                        "SET i += $props",
                        {
                            "device_id": destination_device_id,
                            "name": dest_name,
                            "props": iface_props,
                        },
                    )

            # Transfer connectivity
            for conn in source_state.get("connectivity", []):
                if "CONNECTED_TO" not in transfer_edges and "CONNECTED_TO" not in skip_edges:
                    continue
                if "CONNECTED_TO" in skip_edges:
                    continue

                local_name = conn["local_interface"]
                dest_local = self.transform_interface_name(local_name, interface_map)

                result.relationships_transferred.append({
                    "type": "CONNECTED_TO",
                    "from_interface": dest_local,
                    "to_device": conn["remote_device"],
                    "to_interface": conn["remote_interface"],
                })

                if not dry_run:
                    await self._driver.execute_write(
                        "MATCH (d:Device {id: $dest_id})-[:HAS_INTERFACE]->(li:Interface {name: $local_name}), "
                        "      (ri:Interface {name: $remote_name})<-[:HAS_INTERFACE]-(rd:Device {id: $remote_id}) "
                        "MERGE (li)-[:CONNECTED_TO]->(ri)",
                        {
                            "dest_id": destination_device_id,
                            "local_name": dest_local,
                            "remote_name": conn["remote_interface"],
                            "remote_id": conn["remote_device_id"],
                        },
                    )

            # Transfer other relationships
            for rel in source_state.get("relationships", []):
                edge_type = rel["edge_type"]
                if edge_type in skip_edges:
                    continue
                if transfer_edges and edge_type not in transfer_edges:
                    continue

                result.relationships_transferred.append({
                    "type": edge_type,
                    "target_id": rel["target_id"],
                    "edge_props": rel.get("edge_props", {}),
                })

                if not dry_run:
                    await self._driver.execute_write(
                        f"MATCH (d:Device {{id: $dest_id}}), (t {{id: $target_id}}) "
                        f"MERGE (d)-[:{edge_type}]->(t)",
                        {
                            "dest_id": destination_device_id,
                            "target_id": rel["target_id"],
                        },
                    )

            # Transfer device-level properties
            device_props = self.transform_properties(
                source_state["device"], property_map
            )
            # Remove identity fields that shouldn't transfer
            for key in ["id", "hostname", "serial_number", "asset_tag", "created_at"]:
                device_props.pop(key, None)

            result.properties_transferred = device_props

            if not dry_run and device_props:
                await self._driver.execute_write(
                    "MATCH (d:Device {id: $id}) SET d += $props",
                    {"id": destination_device_id, "props": device_props},
                )

            # Record the replacement relationship
            if not dry_run:
                now = datetime.now(timezone.utc).isoformat()
                await self._driver.execute_write(
                    "MATCH (src:Device {id: $src_id}), (dst:Device {id: $dst_id}) "
                    "MERGE (dst)-[r:REPLACES_DEVICE]->(src) "
                    "SET r.transformation_mapping = $mapping, "
                    "    r.status = 'completed', r.transferred_at = $now",
                    {
                        "src_id": source_device_id,
                        "dst_id": destination_device_id,
                        "mapping": result.mapping_name,
                        "now": now,
                    },
                )

            result.success = True

        except Exception as e:
            result.errors.append(str(e))
            logger.error("Transformation failed", error=str(e))

        return result
