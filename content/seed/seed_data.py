"""Seed data script — populates a local dev environment with example data.

Run with: python -m content.seed.seed_data
Or via: make seed
"""

import asyncio

# Seed data for development and demonstration
VENDORS = [
    {"name": "Cisco", "slug": "cisco", "url": "https://www.cisco.com"},
    {"name": "Juniper Networks", "slug": "juniper", "url": "https://www.juniper.net"},
    {"name": "Arista Networks", "slug": "arista", "url": "https://www.arista.com"},
    {"name": "Palo Alto Networks", "slug": "palo-alto", "url": "https://www.paloaltonetworks.com"},
]

PLATFORMS = [
    {"name": "Cisco IOS", "slug": "cisco_ios", "netmiko_device_type": "cisco_ios", "nornir_platform": "ios"},
    {"name": "Cisco IOS-XE", "slug": "cisco_ios_xe", "netmiko_device_type": "cisco_xe", "nornir_platform": "iosxe"},
    {"name": "Cisco NX-OS", "slug": "cisco_nxos", "netmiko_device_type": "cisco_nxos", "nornir_platform": "nxos"},
    {"name": "Juniper JunOS", "slug": "juniper_junos", "netmiko_device_type": "juniper_junos", "nornir_platform": "junos"},
    {"name": "Arista EOS", "slug": "arista_eos", "netmiko_device_type": "arista_eos", "nornir_platform": "eos"},
]

LOCATIONS = [
    {"name": "US-East", "location_type": "region", "status": "active", "country": "US"},
    {"name": "US-West", "location_type": "region", "status": "active", "country": "US"},
    {"name": "NYC-DC1", "location_type": "site", "status": "active", "city": "New York", "country": "US"},
    {"name": "SFO-DC1", "location_type": "site", "status": "active", "city": "San Francisco", "country": "US"},
    {"name": "NYC-DC1-R01", "location_type": "rack", "status": "active"},
    {"name": "NYC-DC1-R02", "location_type": "rack", "status": "active"},
]

HARDWARE_MODELS = [
    {"model": "Catalyst 9300-48T", "slug": "c9300-48t", "u_height": 1},
    {"model": "Catalyst 9500-32C", "slug": "c9500-32c", "u_height": 1},
    {"model": "Nexus 9332C", "slug": "n9332c", "u_height": 1},
    {"model": "ASR 1001-X", "slug": "asr1001x", "u_height": 1},
    {"model": "PA-5220", "slug": "pa-5220", "u_height": 2},
]

DEVICES = [
    {"hostname": "nyc-core-rtr-01", "management_ip": "10.1.1.1", "status": "active", "role": "router"},
    {"hostname": "nyc-core-rtr-02", "management_ip": "10.1.1.2", "status": "active", "role": "router"},
    {"hostname": "nyc-dist-sw-01", "management_ip": "10.1.2.1", "status": "active", "role": "switch"},
    {"hostname": "nyc-dist-sw-02", "management_ip": "10.1.2.2", "status": "active", "role": "switch"},
    {"hostname": "nyc-access-sw-01", "management_ip": "10.1.3.1", "status": "active", "role": "switch"},
    {"hostname": "nyc-fw-01", "management_ip": "10.1.4.1", "status": "active", "role": "firewall"},
    {"hostname": "sfo-core-rtr-01", "management_ip": "10.2.1.1", "status": "active", "role": "router"},
    {"hostname": "sfo-dist-sw-01", "management_ip": "10.2.2.1", "status": "active", "role": "switch"},
    {"hostname": "nyc-new-sw-01", "management_ip": "10.1.5.1", "status": "planned", "role": "switch"},
]

SOFTWARE_VERSIONS = [
    {"version_string": "17.06.05", "status": "current"},
    {"version_string": "17.03.07", "status": "deprecated"},
    {"version_string": "15.2(7)E2", "status": "end_of_support"},
    {"version_string": "10.3(2)", "status": "current"},
]


async def seed(graph_driver) -> dict[str, int]:
    """Seed the database with example data.

    Returns a summary of created objects.
    """
    from packages.graph_db.repositories.node_repository import NodeRepository
    from packages.schema_engine.registry import SchemaRegistry

    registry = SchemaRegistry()
    await registry.load_from_directories(["schemas/core", "schemas/mixins"])

    repo = NodeRepository(driver=graph_driver, registry=registry)
    counts = {}

    for vendor in VENDORS:
        await repo.create_node("Vendor", vendor)
    counts["vendors"] = len(VENDORS)

    for platform in PLATFORMS:
        await repo.create_node("Platform", platform)
    counts["platforms"] = len(PLATFORMS)

    for location in LOCATIONS:
        await repo.create_node("Location", location)
    counts["locations"] = len(LOCATIONS)

    for model in HARDWARE_MODELS:
        await repo.create_node("HardwareModel", model)
    counts["hardware_models"] = len(HARDWARE_MODELS)

    for device in DEVICES:
        await repo.create_node("Device", device)
    counts["devices"] = len(DEVICES)

    for version in SOFTWARE_VERSIONS:
        await repo.create_node("SoftwareVersion", version)
    counts["software_versions"] = len(SOFTWARE_VERSIONS)

    # TODO: Create edges (LOCATED_IN, RUNS_PLATFORM, RUNS_VERSION, etc.)

    return counts


if __name__ == "__main__":
    print("Seed data script — run via 'make seed' with a running Neo4j instance")
    print(f"  Vendors: {len(VENDORS)}")
    print(f"  Platforms: {len(PLATFORMS)}")
    print(f"  Locations: {len(LOCATIONS)}")
    print(f"  Hardware Models: {len(HARDWARE_MODELS)}")
    print(f"  Devices: {len(DEVICES)}")
    print(f"  Software Versions: {len(SOFTWARE_VERSIONS)}")
