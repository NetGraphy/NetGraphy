#!/usr/bin/env python3
"""Seed NetGraphy with synthetic network data.

Creates a realistic multi-site enterprise network with:
  - Organization: Tenants, Locations (regions → sites → buildings)
  - Infrastructure: Devices, Interfaces, HW models, Vendors, Platforms
  - IPAM: Prefixes, IP Addresses, BGP ASNs, MAC Addresses
  - Clouds: Cloud providers, VPCs, Subnets, Gateways
  - Network: Services
  - Cabling: Physical cables with endpoint connections for spine-leaf fabrics
  - Circuits: Providers, circuit types, circuits with A/Z terminations
  - Full relationship wiring between all objects

Usage:
  export NETGRAPHY_URL=https://api-staging-a8ac.up.railway.app/api/v1
  export NETGRAPHY_USER=admin
  export NETGRAPHY_PASS=admin
  python scripts/seed.py
"""

import os
import sys
import time
import random
import requests
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("NETGRAPHY_URL", "http://localhost:8000/api/v1")
USERNAME = os.environ.get("NETGRAPHY_USER", "admin")
PASSWORD = os.environ.get("NETGRAPHY_PASS", "admin")

TOKEN: str | None = None
SESSION = requests.Session()


def login():
    """Authenticate and store the JWT token."""
    global TOKEN
    resp = SESSION.post(f"{BASE_URL}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    resp.raise_for_status()
    TOKEN = resp.json()["data"]["access_token"]
    SESSION.headers.update({"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    print(f"Authenticated as {USERNAME}")


def wait_for_api(retries: int = 15, delay: int = 3):
    """Wait for the API to become available."""
    # Health endpoints are mounted at root, not under /api/v1
    health_url = BASE_URL.rsplit("/api/", 1)[0] + "/health/live"
    for i in range(retries):
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                print("API is ready")
                return
        except requests.exceptions.ConnectionError:
            pass
        print(f"Waiting for API... ({i + 1}/{retries})")
        time.sleep(delay)
    print("ERROR: API did not become ready", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
IDS: dict[str, str] = {}  # "NodeType:unique_value" → id


def create_node(node_type: str, props: dict[str, Any], key_field: str = "name", dedup_key: str | None = None) -> str | None:
    """Create a node, return its id. Idempotent via dedup_key or key_field."""
    tag = dedup_key or f"{node_type}:{props.get(key_field, '?')}"
    if tag in IDS:
        return IDS[tag]

    resp = SESSION.post(f"{BASE_URL}/objects/{node_type}", json=props)
    if resp.status_code == 201:
        nid = resp.json()["data"]["id"]
        IDS[tag] = nid
        return nid
    else:
        print(f"  WARN create {tag}: {resp.status_code} {resp.text[:200]}")
        return None


def create_edge(edge_type: str, source_id: str, target_id: str, props: dict[str, Any] | None = None) -> str | None:
    """Create an edge between two nodes."""
    if not source_id or not target_id:
        return None
    body: dict[str, Any] = {"source_id": source_id, "target_id": target_id}
    if props:
        body.update(props)
    resp = SESSION.post(f"{BASE_URL}/edges/{edge_type}", json=body)
    if resp.status_code == 201:
        return resp.json()["data"]["id"]
    else:
        print(f"  WARN edge {edge_type}: {resp.status_code} {resp.text[:200]}")
        return None


def n(node_type: str, key_value: str) -> str | None:
    """Lookup a previously-created node id by type:key."""
    return IDS.get(f"{node_type}:{key_value}")


def rand_mac() -> str:
    """Generate a random MAC address."""
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def rand_serial() -> str:
    """Generate a random serial number."""
    return f"{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=11))}"


# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

def seed_vendors_and_models():
    """Create vendors and hardware models."""
    print("\n=== Vendors & Hardware Models ===")
    vendors = [
        ("Cisco Systems", "cisco", "https://www.cisco.com"),
        ("Juniper Networks", "juniper", "https://www.juniper.net"),
        ("Arista Networks", "arista", "https://www.arista.com"),
        ("Palo Alto Networks", "palo-alto", "https://www.paloaltonetworks.com"),
    ]
    for name, slug, url in vendors:
        create_node("Vendor", {"name": name, "slug": slug, "url": url})

    models = [
        ("ISR 4321", "isr-4321", "ISR4321/K9", 1, 4, "Cisco Systems"),
        ("Catalyst 9300-48P", "cat9300-48p", "C9300-48P-A", 1, 48, "Cisco Systems"),
        ("Catalyst 9500-32C", "cat9500-32c", "C9500-32C-A", 1, 32, "Cisco Systems"),
        ("MX204", "mx204", "MX204-IR", 1, 4, "Juniper Networks"),
        ("QFX5120-48T", "qfx5120-48t", "QFX5120-48T-AFI", 1, 48, "Juniper Networks"),
        ("DCS-7050SX3-48YC12", "dcs-7050sx3", "DCS-7050SX3-48YC12", 1, 60, "Arista Networks"),
        ("DCS-7280CR3-32P4", "dcs-7280cr3", "DCS-7280CR3-32P4", 2, 36, "Arista Networks"),
        ("PA-5220", "pa-5220", "PA-5220", 2, 16, "Palo Alto Networks"),
    ]
    for model_name, slug, pn, u, ifc, vendor_name in models:
        mid = create_node("HardwareModel", {
            "model": model_name, "slug": slug, "part_number": pn,
            "u_height": u, "interface_count": ifc,
        }, key_field="model")
        vid = n("Vendor", vendor_name)
        if mid and vid:
            create_edge("MANUFACTURED_BY", mid, vid)


def seed_hardware_templates():
    """Create interface templates and inventory templates for hardware models."""
    print("\n=== Hardware Templates ===")

    # Interface templates per model: (model, name, type, speed, form_factor, position, mgmt, poe)
    iface_templates = {
        "Catalyst 9300-48P": [
            *[(f"GigabitEthernet1/0/{i}", "physical", 1000, "rj45", i, False, True) for i in range(1, 49)],
            ("TenGigabitEthernet1/1/1", "physical", 10000, "sfp_plus", 49, False, False),
            ("TenGigabitEthernet1/1/2", "physical", 10000, "sfp_plus", 50, False, False),
            ("GigabitEthernet0/0", "management", 1000, "rj45", 0, True, False),
        ],
        "DCS-7050SX3-48YC12": [
            *[(f"Ethernet{i}/1", "physical", 25000, "sfp28", i, False, False) for i in range(1, 49)],
            *[(f"Ethernet{i}/1", "physical", 100000, "qsfp28", i, False, False) for i in range(49, 61)],
            ("Management1", "management", 1000, "rj45", 0, True, False),
        ],
        "ISR 4321": [
            ("GigabitEthernet0/0/0", "physical", 1000, "rj45", 1, False, False),
            ("GigabitEthernet0/0/1", "physical", 1000, "rj45", 2, False, False),
            ("GigabitEthernet0/0/2", "physical", 1000, "rj45", 3, False, False),
            ("GigabitEthernet0/0/3", "physical", 1000, "rj45", 4, False, False),
            ("GigabitEthernet0", "management", 1000, "rj45", 0, True, False),
        ],
        "PA-5220": [
            *[(f"ethernet1/{i}", "physical", 10000, "sfp_plus", i, False, False) for i in range(1, 17)],
            ("management", "management", 1000, "rj45", 0, True, False),
        ],
    }

    for model_name, templates in iface_templates.items():
        model_id = n("HardwareModel", model_name)
        if not model_id:
            continue
        for t in templates:
            ifname, iftype, speed, ff, pos, mgmt, poe = t
            tid = create_node("InterfaceTemplate", {
                "name": ifname, "interface_type": iftype, "speed_mbps": speed,
                "form_factor": ff, "slot_position": pos, "mgmt_only": mgmt, "poe_capable": poe,
            }, dedup_key=f"InterfaceTemplate:{model_name}:{ifname}")
            if tid:
                create_edge("HAS_INTERFACE_TEMPLATE", model_id, tid)

    # Inventory item templates per model: (model, name, item_type, position, required)
    inv_templates = {
        "Catalyst 9300-48P": [
            ("PSU-1", "power_supply_bay", 1, True),
            ("PSU-2", "power_supply_bay", 2, False),
            ("FAN-1", "fan_bay", 1, True),
            ("FAN-2", "fan_bay", 2, True),
            ("FAN-3", "fan_bay", 3, True),
            ("Module Bay 1", "module_bay", 1, False),
        ],
        "DCS-7050SX3-48YC12": [
            ("PSU-1", "power_supply_bay", 1, True),
            ("PSU-2", "power_supply_bay", 2, True),
            ("FAN-1", "fan_bay", 1, True),
            ("FAN-2", "fan_bay", 2, True),
            ("FAN-3", "fan_bay", 3, True),
            ("FAN-4", "fan_bay", 4, True),
        ],
        "ISR 4321": [
            ("PSU-1", "power_supply_bay", 1, True),
            ("NIM Bay 0", "module_bay", 0, False),
            ("NIM Bay 1", "module_bay", 1, False),
            ("FAN-1", "fan_bay", 1, True),
        ],
        "PA-5220": [
            ("PSU-1", "power_supply_bay", 1, True),
            ("PSU-2", "power_supply_bay", 2, True),
            ("FAN-1", "fan_bay", 1, True),
            ("FAN-2", "fan_bay", 2, True),
        ],
        "DCS-7280CR3-32P4": [
            ("PSU-1", "power_supply_bay", 1, True),
            ("PSU-2", "power_supply_bay", 2, True),
            ("FAN-1", "fan_bay", 1, True),
            ("FAN-2", "fan_bay", 2, True),
            ("FAN-3", "fan_bay", 3, True),
            ("FAN-4", "fan_bay", 4, True),
            ("FAN-5", "fan_bay", 5, True),
        ],
    }

    for model_name, templates in inv_templates.items():
        model_id = n("HardwareModel", model_name)
        if not model_id:
            continue
        for tname, ttype, pos, req in templates:
            tid = create_node("InventoryItemTemplate", {
                "name": tname, "item_type": ttype, "slot_position": pos, "required": req,
            }, dedup_key=f"InventoryItemTemplate:{model_name}:{tname}")
            if tid:
                create_edge("HAS_INVENTORY_TEMPLATE", model_id, tid)


def seed_inventory():
    """Create inventory items installed in devices."""
    print("\n=== Inventory Items ===")

    # Sample inventory for a few devices
    device_inventory = {
        "DAL-SPN01": [
            ("PSU-1", "power_supply", "installed", "PWR-2900-AC", "FOC2234N0P1", "1"),
            ("PSU-2", "power_supply", "installed", "PWR-2900-AC", "FOC2234N0P2", "2"),
            ("FAN-1", "fan", "installed", "FAN-7050SX3", "FOC2234F001", "1"),
            ("FAN-2", "fan", "installed", "FAN-7050SX3", "FOC2234F002", "2"),
            ("FAN-3", "fan", "installed", "FAN-7050SX3", "FOC2234F003", "3"),
            ("FAN-4", "fan", "installed", "FAN-7050SX3", "FOC2234F004", "4"),
        ],
        "DAL-LEAF01": [
            ("PSU-1", "power_supply", "installed", "PWR-1100-AC", "FOC2245P001", "1"),
            ("PSU-2", "power_supply", "installed", "PWR-1100-AC", "FOC2245P002", "2"),
            ("SFP Eth49/1", "qsfp28", "installed", "QSFP-100G-SR4", "AVR2245Q001", "49"),
            ("SFP Eth50/1", "qsfp28", "installed", "QSFP-100G-SR4", "AVR2245Q002", "50"),
            ("SFP Eth51/1", "qsfp28", "installed", "QSFP-100G-SR4", "AVR2245Q003", "51"),
            ("SFP Eth52/1", "qsfp28", "installed", "QSFP-100G-SR4", "AVR2245Q004", "52"),
        ],
        "DAL-COR-RTR01": [
            ("PSU-1", "power_supply", "installed", "PWR-4320-AC", "FDO2234P001", "1"),
            ("NIM-2GE-CU-SFP", "module", "installed", "NIM-2GE-CU-SFP", "FOC2134M001", "0"),
            ("FAN-1", "fan", "installed", "ACS-4320-FAN", "FOC2234F001", "1"),
        ],
        "DAL-FW01": [
            ("PSU-1", "power_supply", "installed", "PAN-PSU-740W-AC", "PAL2234P001", "1"),
            ("PSU-2", "power_supply", "installed", "PAN-PSU-740W-AC", "PAL2234P002", "2"),
            ("SFP eth1/1", "sfp_plus", "installed", "SFP-10G-SR", "PAL2234S001", "1"),
            ("SFP eth1/2", "sfp_plus", "installed", "SFP-10G-SR", "PAL2234S002", "2"),
        ],
    }

    for hostname, items in device_inventory.items():
        dev_id = n("Device", hostname)
        if not dev_id:
            continue
        for iname, itype, status, pn, sn, slot in items:
            iid = create_node("InventoryItem", {
                "name": iname, "item_type": itype, "status": status,
                "part_number": pn, "serial_number": sn, "slot_position": slot,
            }, dedup_key=f"InventoryItem:{hostname}:{iname}")
            if iid:
                create_edge("HAS_INVENTORY_ITEM", dev_id, iid)


def seed_platforms():
    """Create platforms."""
    print("\n=== Platforms ===")
    platforms = [
        ("IOS-XE", "cisco_ios_xe", "ios", "cisco_ios", "cisco.ios.ios", "cisco_ios_xe"),
        ("NX-OS", "cisco_nxos", "nxos_ssh", "cisco_nxos", "cisco.nxos.nxos", "cisco_nxos"),
        ("Junos", "juniper_junos", "junos", "juniper_junos", "junipernetworks.junos.junos", "juniper_junos"),
        ("EOS", "arista_eos", "eos", "arista_eos", "arista.eos.eos", "arista_eos"),
        ("PAN-OS", "paloalto_panos", None, "paloalto_panos", None, "paloalto_panos"),
    ]
    for name, slug, napalm, netmiko, ansible, nornir in platforms:
        create_node("Platform", {
            "name": name, "slug": slug,
            "napalm_driver": napalm, "netmiko_device_type": netmiko,
            "ansible_network_os": ansible, "nornir_platform": nornir,
        })


def seed_software_versions():
    """Create software versions and link to platforms."""
    print("\n=== Software Versions ===")
    versions = [
        ("17.09.04a", 17, 9, "IOS-XE", "current"),
        ("17.06.05", 17, 6, "IOS-XE", "deprecated"),
        ("10.3(4a)", 10, 3, "NX-OS", "current"),
        ("23.2R1.14", 23, 2, "Junos", "current"),
        ("22.4R2.3", 22, 4, "Junos", "deprecated"),
        ("4.31.2F", 4, 31, "EOS", "current"),
        ("4.29.3M", 4, 29, "EOS", "deprecated"),
        ("11.1.2", 11, 1, "PAN-OS", "current"),
    ]
    for ver, major, minor, platform, status in versions:
        vid = create_node("SoftwareVersion", {
            "version_string": ver, "major": major, "minor": minor, "status": status,
        }, key_field="version_string")
        pid = n("Platform", platform)
        # SoftwareVersion doesn't directly link to Platform via edge in this seed;
        # the Device → Platform and Device → SoftwareVersion edges handle the chain.


def seed_tenants():
    """Create tenants."""
    print("\n=== Tenants ===")
    tenants = [
        ("Acme Corp", "acme-corp", "customer", "active", "noc@acme.example.com"),
        ("GlobalBank", "globalbank", "customer", "active", "netops@globalbank.example.com"),
        ("Internal IT", "internal-it", "internal", "active", "it@netgraphy.example.com"),
        ("Shared Services", "shared-services", "shared_services", "active", "shared@netgraphy.example.com"),
    ]
    for name, slug, ttype, status, email in tenants:
        create_node("Tenant", {
            "name": name, "slug": slug, "tenant_type": ttype,
            "status": status, "contact_email": email,
        })


def seed_locations():
    """Create location hierarchy: regions → countries → sites → buildings."""
    print("\n=== Locations ===")
    # Regions
    regions = [
        ("NAM", "region", "active"),
        ("EMEA", "region", "active"),
        ("APAC", "region", "active"),
        ("LATAM", "region", "active"),
    ]
    for name, lt, st in regions:
        create_node("Location", {"name": name, "location_type": lt, "status": st})

    # Sites
    sites = [
        # (name, type, status, city, country, lat, lon, parent_region)
        ("DAL-DC1", "site", "active", "Dallas", "US", 32.78, -96.80, "NAM"),
        ("NYC-DC1", "site", "active", "New York", "US", 40.71, -74.01, "NAM"),
        ("LON-DC1", "site", "active", "London", "GB", 51.51, -0.13, "EMEA"),
        ("FRA-DC1", "site", "active", "Frankfurt", "DE", 50.11, 8.68, "EMEA"),
        ("SIN-DC1", "site", "active", "Singapore", "SG", 1.35, 103.82, "APAC"),
        ("TKY-DC1", "site", "active", "Tokyo", "JP", 35.68, 139.69, "APAC"),
        ("SAO-DC1", "site", "active", "São Paulo", "BR", -23.55, -46.63, "LATAM"),
        ("MEX-BR1", "site", "active", "Mexico City", "MX", 19.43, -99.13, "LATAM"),
        ("CHI-BR1", "site", "active", "Chicago", "US", 41.88, -87.63, "NAM"),
        ("SEA-BR1", "site", "active", "Seattle", "US", 47.61, -122.33, "NAM"),
    ]
    for name, lt, st, city, country, lat, lon, parent in sites:
        sid = create_node("Location", {
            "name": name, "location_type": lt, "status": st,
            "city": city, "country": country, "latitude": lat, "longitude": lon,
        })
        pid = n("Location", parent)
        if sid and pid:
            create_edge("PARENT_OF", pid, sid)

    # Assign tenants to locations
    for loc in ["DAL-DC1", "NYC-DC1", "LON-DC1"]:
        lid = n("Location", loc)
        for tenant in ["Acme Corp", "GlobalBank"]:
            tid = n("Tenant", tenant)
            if lid and tid:
                create_edge("TENANT_USES_LOCATION", tid, lid)


def seed_devices():
    """Create devices at each site with interfaces, IPs, and relationships."""
    print("\n=== Devices & Interfaces ===")

    # (hostname, role, model, platform, sw_version, site)
    devices = [
        # Dallas DC — Core + Spine/Leaf
        ("DAL-COR-RTR01", "router", "ISR 4321", "IOS-XE", "17.09.04a", "DAL-DC1"),
        ("DAL-COR-RTR02", "router", "ISR 4321", "IOS-XE", "17.09.04a", "DAL-DC1"),
        ("DAL-FW01", "firewall", "PA-5220", "PAN-OS", "11.1.2", "DAL-DC1"),
        ("DAL-SPN01", "switch", "DCS-7280CR3-32P4", "EOS", "4.31.2F", "DAL-DC1"),
        ("DAL-SPN02", "switch", "DCS-7280CR3-32P4", "EOS", "4.31.2F", "DAL-DC1"),
        ("DAL-LEAF01", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "DAL-DC1"),
        ("DAL-LEAF02", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "DAL-DC1"),
        ("DAL-LEAF03", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "DAL-DC1"),
        ("DAL-LEAF04", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "DAL-DC1"),

        # NYC DC
        ("NYC-COR-RTR01", "router", "MX204", "Junos", "23.2R1.14", "NYC-DC1"),
        ("NYC-COR-RTR02", "router", "MX204", "Junos", "23.2R1.14", "NYC-DC1"),
        ("NYC-FW01", "firewall", "PA-5220", "PAN-OS", "11.1.2", "NYC-DC1"),
        ("NYC-SPN01", "switch", "DCS-7280CR3-32P4", "EOS", "4.31.2F", "NYC-DC1"),
        ("NYC-SPN02", "switch", "DCS-7280CR3-32P4", "EOS", "4.31.2F", "NYC-DC1"),
        ("NYC-LEAF01", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "NYC-DC1"),
        ("NYC-LEAF02", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "NYC-DC1"),
        ("NYC-LEAF03", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "NYC-DC1"),
        ("NYC-LEAF04", "switch", "DCS-7050SX3-48YC12", "EOS", "4.31.2F", "NYC-DC1"),

        # London DC
        ("LON-COR-RTR01", "router", "MX204", "Junos", "23.2R1.14", "LON-DC1"),
        ("LON-COR-RTR02", "router", "MX204", "Junos", "23.2R1.14", "LON-DC1"),
        ("LON-SPN01", "switch", "QFX5120-48T", "Junos", "23.2R1.14", "LON-DC1"),
        ("LON-SPN02", "switch", "QFX5120-48T", "Junos", "23.2R1.14", "LON-DC1"),
        ("LON-LEAF01", "switch", "QFX5120-48T", "Junos", "23.2R1.14", "LON-DC1"),
        ("LON-LEAF02", "switch", "QFX5120-48T", "Junos", "23.2R1.14", "LON-DC1"),

        # Frankfurt DC
        ("FRA-COR-RTR01", "router", "ISR 4321", "IOS-XE", "17.09.04a", "FRA-DC1"),
        ("FRA-ACC-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "FRA-DC1"),
        ("FRA-ACC-SW02", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "FRA-DC1"),

        # Singapore DC
        ("SIN-COR-RTR01", "router", "MX204", "Junos", "22.4R2.3", "SIN-DC1"),
        ("SIN-ACC-SW01", "switch", "Catalyst 9500-32C", "IOS-XE", "17.09.04a", "SIN-DC1"),

        # Tokyo DC
        ("TKY-COR-RTR01", "router", "ISR 4321", "IOS-XE", "17.09.04a", "TKY-DC1"),
        ("TKY-ACC-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "TKY-DC1"),

        # São Paulo DC
        ("SAO-COR-RTR01", "router", "ISR 4321", "IOS-XE", "17.09.04a", "SAO-DC1"),
        ("SAO-ACC-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "SAO-DC1"),

        # Branch offices
        ("MEX-BR-RTR01", "router", "ISR 4321", "IOS-XE", "17.06.05", "MEX-BR1"),
        ("MEX-BR-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "MEX-BR1"),
        ("CHI-BR-RTR01", "router", "ISR 4321", "IOS-XE", "17.06.05", "CHI-BR1"),
        ("CHI-BR-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "CHI-BR1"),
        ("SEA-BR-RTR01", "router", "ISR 4321", "IOS-XE", "17.06.05", "SEA-BR1"),
        ("SEA-BR-SW01", "switch", "Catalyst 9300-48P", "IOS-XE", "17.06.05", "SEA-BR1"),
    ]

    for hostname, role, model, platform, version, site in devices:
        serial = rand_serial()
        mgmt_ip = None  # will assign later via IPAM

        did = create_node("Device", {
            "hostname": hostname, "role": role, "status": "active",
            "serial_number": serial,
        }, key_field="hostname")

        if not did:
            continue

        # Wire relationships
        loc_id = n("Location", site)
        if loc_id:
            create_edge("LOCATED_IN", did, loc_id)

        model_id = n("HardwareModel", model)
        if model_id:
            create_edge("HAS_MODEL", did, model_id)

        plat_id = n("Platform", platform)
        if plat_id:
            create_edge("RUNS_PLATFORM", did, plat_id)

        ver_id = n("SoftwareVersion", version)
        if ver_id:
            create_edge("RUNS_VERSION", did, ver_id)

        # Assign to tenant
        if "DAL" in hostname or "NYC" in hostname:
            tid = n("Tenant", "Acme Corp")
        elif "LON" in hostname or "FRA" in hostname:
            tid = n("Tenant", "GlobalBank")
        else:
            tid = n("Tenant", "Internal IT")
        if tid:
            create_edge("ASSIGNED_TO_TENANT", did, tid)

        # Create interfaces (scoped to device — interface names repeat across devices)
        ifaces = _interfaces_for(hostname, role)
        for ifname, iftype, speed, enabled in ifaces:
            iid = create_node("Interface", {
                "name": ifname, "interface_type": iftype,
                "speed_mbps": speed, "enabled": enabled,
                "oper_status": "up" if enabled else "down",
            }, dedup_key=f"Interface:{hostname}:{ifname}")
            if iid:
                create_edge("HAS_INTERFACE", did, iid)


def _interfaces_for(hostname: str, role: str) -> list[tuple[str, str, int, bool]]:
    """Return (name, type, speed_mbps, enabled) for a device."""
    ifaces = [("Loopback0", "loopback", 0, True), ("Management0", "management", 1000, True)]
    if role == "router":
        ifaces += [
            ("GigabitEthernet0/0/0", "physical", 1000, True),
            ("GigabitEthernet0/0/1", "physical", 1000, True),
            ("GigabitEthernet0/0/2", "physical", 1000, True),
            ("GigabitEthernet0/0/3", "physical", 1000, False),
        ]
    elif role == "switch" and "SPN" in hostname:
        for i in range(8):
            ifaces.append((f"Ethernet{i + 1}/1", "physical", 100000, True))
    elif role == "switch" and "LEAF" in hostname:
        for i in range(4):
            ifaces.append((f"Ethernet{i + 1}/1", "physical", 100000, True))
        for i in range(24):
            ifaces.append((f"Ethernet{i + 49}/1", "physical", 25000, i < 16))
    elif role == "firewall":
        ifaces += [
            ("ethernet1/1", "physical", 10000, True),
            ("ethernet1/2", "physical", 10000, True),
            ("ethernet1/3", "physical", 10000, True),
            ("ethernet1/4", "physical", 10000, False),
        ]
    else:  # access switch
        for i in range(48):
            ifaces.append((f"GigabitEthernet1/0/{i + 1}", "physical", 1000, i < 32))
        ifaces += [
            ("TenGigabitEthernet1/1/1", "physical", 10000, True),
            ("TenGigabitEthernet1/1/2", "physical", 10000, True),
        ]
    return ifaces


def seed_ipam():
    """Create prefixes, IP addresses, MACs, and BGP ASNs."""
    print("\n=== IPAM: Prefixes ===")

    # Aggregates
    agg_rfc1918 = create_node("Prefix", {
        "prefix": "10.0.0.0/8", "description": "RFC 1918 — Class A private range",
        "status": "container", "ip_version": "4",
    }, key_field="prefix")

    agg_172 = create_node("Prefix", {
        "prefix": "172.16.0.0/12", "description": "RFC 1918 — Class B private range",
        "status": "container", "ip_version": "4",
    }, key_field="prefix")

    # Site prefixes (parent → child hierarchy)
    site_prefixes = [
        # (cidr, name, status, ip_ver, site, tenant, parent_prefix)
        ("10.1.0.0/16", "Dallas DC", "active", "4", "DAL-DC1", "Acme Corp", "10.0.0.0/8"),
        ("10.1.0.0/24", "DAL Mgmt", "active", "4", "DAL-DC1", "Acme Corp", "10.1.0.0/16"),
        ("10.1.1.0/24", "DAL Loopbacks", "active", "4", "DAL-DC1", "Acme Corp", "10.1.0.0/16"),
        ("10.1.10.0/24", "DAL Spine-Leaf Fabric", "active", "4", "DAL-DC1", "Acme Corp", "10.1.0.0/16"),
        ("10.1.100.0/24", "DAL Server VLAN 100", "active", "4", "DAL-DC1", "Acme Corp", "10.1.0.0/16"),
        ("10.1.101.0/24", "DAL Server VLAN 101", "active", "4", "DAL-DC1", "Acme Corp", "10.1.0.0/16"),

        ("10.2.0.0/16", "NYC DC", "active", "4", "NYC-DC1", "Acme Corp", "10.0.0.0/8"),
        ("10.2.0.0/24", "NYC Mgmt", "active", "4", "NYC-DC1", "Acme Corp", "10.2.0.0/16"),
        ("10.2.1.0/24", "NYC Loopbacks", "active", "4", "NYC-DC1", "Acme Corp", "10.2.0.0/16"),
        ("10.2.10.0/24", "NYC Spine-Leaf Fabric", "active", "4", "NYC-DC1", "Acme Corp", "10.2.0.0/16"),

        ("10.3.0.0/16", "London DC", "active", "4", "LON-DC1", "GlobalBank", "10.0.0.0/8"),
        ("10.3.0.0/24", "LON Mgmt", "active", "4", "LON-DC1", "GlobalBank", "10.3.0.0/16"),
        ("10.3.1.0/24", "LON Loopbacks", "active", "4", "LON-DC1", "GlobalBank", "10.3.0.0/16"),

        ("10.4.0.0/16", "Frankfurt DC", "active", "4", "FRA-DC1", "GlobalBank", "10.0.0.0/8"),
        ("10.5.0.0/16", "Singapore DC", "active", "4", "SIN-DC1", "Internal IT", "10.0.0.0/8"),
        ("10.6.0.0/16", "Tokyo DC", "active", "4", "TKY-DC1", "Internal IT", "10.0.0.0/8"),
        ("10.7.0.0/16", "São Paulo DC", "active", "4", "SAO-DC1", "Internal IT", "10.0.0.0/8"),

        ("10.100.1.0/24", "MEX Branch", "active", "4", "MEX-BR1", "Internal IT", "10.0.0.0/8"),
        ("10.100.2.0/24", "CHI Branch", "active", "4", "CHI-BR1", "Internal IT", "10.0.0.0/8"),
        ("10.100.3.0/24", "SEA Branch", "active", "4", "SEA-BR1", "Internal IT", "10.0.0.0/8"),

        # WAN / Transit
        ("172.16.0.0/24", "WAN P2P Links", "active", "4", None, "Shared Services", "172.16.0.0/12"),
    ]

    for cidr, pfx_desc, status, ipv, site, tenant, parent_cidr in site_prefixes:
        pid = create_node("Prefix", {
            "prefix": cidr, "description": pfx_desc, "status": status, "ip_version": ipv,
        }, key_field="prefix")
        if pid and parent_cidr:
            parent_id = n("Prefix", parent_cidr)
            if parent_id:
                create_edge("PREFIX_PARENT_OF", parent_id, pid)
        if pid and site:
            loc_id = n("Location", site)
            # tenant
            tenant_id = n("Tenant", tenant) if tenant else None
            if tenant_id:
                create_edge("PREFIX_ASSIGNED_TO_TENANT", pid, tenant_id)

    # IP Addresses — management + loopbacks for every device
    print("\n=== IPAM: IP Addresses ===")
    ip_counter: dict[str, int] = {}  # prefix_base → next host

    def next_ip(prefix_cidr: str) -> str:
        base = prefix_cidr.split("/")[0]
        parts = base.split(".")
        count = ip_counter.get(prefix_cidr, 1)
        ip_counter[prefix_cidr] = count + 1
        parts[3] = str(count)
        mask = prefix_cidr.split("/")[1]
        return ".".join(parts) + "/" + mask

    # Assign management IPs
    mgmt_map = {
        "DAL": "10.1.0.0/24", "NYC": "10.2.0.0/24", "LON": "10.3.0.0/24",
        "FRA": "10.4.0.0/16", "SIN": "10.5.0.0/16", "TKY": "10.6.0.0/16",
        "SAO": "10.7.0.0/16", "MEX": "10.100.1.0/24", "CHI": "10.100.2.0/24",
        "SEA": "10.100.3.0/24",
    }
    loopback_map = {
        "DAL": "10.1.1.0/24", "NYC": "10.2.1.0/24", "LON": "10.3.1.0/24",
    }

    for key, dev_id in list(IDS.items()):
        if not key.startswith("Device:"):
            continue
        hostname = key.split(":", 1)[1]
        site_prefix_key = hostname.split("-")[0]

        # Management IP
        mgmt_prefix = mgmt_map.get(site_prefix_key)
        if mgmt_prefix:
            addr = next_ip(mgmt_prefix)
            ip_id = create_node("IPAddress", {
                "address": addr, "status": "active", "ip_version": "4",
                "dns_name": f"{hostname.lower()}.mgmt.netgraphy.local",
            }, key_field="address")
            if ip_id:
                prefix_id = n("Prefix", mgmt_prefix)
                if prefix_id:
                    create_edge("IP_IN_PREFIX", ip_id, prefix_id)
                create_edge("DEVICE_MANAGEMENT_IP", dev_id, ip_id)

        # Loopback IP
        lo_prefix = loopback_map.get(site_prefix_key)
        if lo_prefix:
            lo_addr = next_ip(lo_prefix)
            lo_ip_id = create_node("IPAddress", {
                "address": lo_addr, "status": "active", "ip_version": "4",
                "role": "loopback",
            }, key_field="address")
            if lo_ip_id:
                prefix_id = n("Prefix", lo_prefix)
                if prefix_id:
                    create_edge("IP_IN_PREFIX", lo_ip_id, prefix_id)

    # MAC Addresses — one per physical interface on spine/leaf devices
    print("\n=== IPAM: MAC Addresses ===")
    mac_count = 0
    for key, iid in list(IDS.items()):
        if not key.startswith("Interface:"):
            continue
        ifname = key.split(":", 1)[1]
        if ifname.startswith("Ethernet") or ifname.startswith("ethernet"):
            mac = rand_mac()
            mac_id = create_node("MACAddress", {
                "address": mac, "status": "active", "mac_type": "unicast",
                "vendor_oui": "Arista" if "Ethernet" in ifname else "Palo Alto",
            }, key_field="address")
            if mac_id:
                create_edge("MAC_ON_INTERFACE", mac_id, iid)
                mac_count += 1
            if mac_count >= 40:
                break  # enough for demo

    # BGP ASNs
    print("\n=== IPAM: BGP ASNs ===")
    asns = [
        (65001, "Acme Corp — DAL", "private", "ARIN"),
        (65002, "Acme Corp — NYC", "private", "ARIN"),
        (65003, "GlobalBank — LON", "private", "RIPE"),
        (65010, "NetGraphy Internal", "private", "ARIN"),
        (13335, "Cloudflare (Transit)", "public", "ARIN"),
        (15169, "Google (Transit)", "public", "ARIN"),
    ]
    for asn_num, name, asn_type, rir in asns:
        asn_id = create_node("BGPASN", {
            "asn": asn_num, "name": name, "status": "active",
            "asn_type": asn_type, "rir": rir,
        }, key_field="asn")

    # ASN → Device assignments
    asn_device_map = {
        65001: ["DAL-COR-RTR01", "DAL-COR-RTR02"],
        65002: ["NYC-COR-RTR01", "NYC-COR-RTR02"],
        65003: ["LON-COR-RTR01", "LON-COR-RTR02"],
        65010: ["FRA-COR-RTR01", "SIN-COR-RTR01", "TKY-COR-RTR01", "SAO-COR-RTR01"],
    }
    for asn_num, hostnames in asn_device_map.items():
        asn_id = n("BGPASN", asn_num)
        for h in hostnames:
            did = n("Device", h)
            if asn_id and did:
                create_edge("ASN_ASSIGNED_TO_DEVICE", asn_id, did)

    # ASN → Tenant
    create_edge("ASN_OWNED_BY_TENANT", n("BGPASN", 65001), n("Tenant", "Acme Corp"))
    create_edge("ASN_OWNED_BY_TENANT", n("BGPASN", 65002), n("Tenant", "Acme Corp"))
    create_edge("ASN_OWNED_BY_TENANT", n("BGPASN", 65003), n("Tenant", "GlobalBank"))
    create_edge("ASN_OWNED_BY_TENANT", n("BGPASN", 65010), n("Tenant", "Internal IT"))

    # ASN peering
    for priv in [65001, 65002, 65003, 65010]:
        for transit in [13335, 15169]:
            create_edge("ASN_PEERS_WITH", n("BGPASN", priv), n("BGPASN", transit),
                        {"peering_type": "transit"})
    create_edge("ASN_PEERS_WITH", n("BGPASN", 65001), n("BGPASN", 65002),
                {"peering_type": "peer"})

    # ASN → Prefix origination
    asn_prefix_map = {
        65001: ["10.1.0.0/16"],
        65002: ["10.2.0.0/16"],
        65003: ["10.3.0.0/16"],
        65010: ["10.4.0.0/16", "10.5.0.0/16", "10.6.0.0/16", "10.7.0.0/16"],
    }
    for asn_num, prefixes in asn_prefix_map.items():
        for p in prefixes:
            create_edge("ASN_ORIGINATES_PREFIX", n("BGPASN", asn_num), n("Prefix", p))


def seed_cloud():
    """Create cloud providers, VPCs, subnets, and gateways."""
    print("\n=== Clouds ===")

    # Providers
    for name, slug, url in [
        ("Amazon Web Services", "aws", "https://console.aws.amazon.com"),
        ("Microsoft Azure", "azure", "https://portal.azure.com"),
        ("Google Cloud Platform", "gcp", "https://console.cloud.google.com"),
    ]:
        create_node("CloudProvider", {"name": name, "slug": slug, "status": "active", "console_url": url})

    # VPCs
    vpcs = [
        ("acme-prod-east", "vpc-0a1b2c3d4e5f", "us-east-1", ["10.50.0.0/16"], "Amazon Web Services", "Acme Corp"),
        ("acme-prod-west", "vpc-1a2b3c4d5e6f", "us-west-2", ["10.51.0.0/16"], "Amazon Web Services", "Acme Corp"),
        ("gbank-prod-eu", "gbank-vnet-eu-001", "westeurope", ["10.60.0.0/16"], "Microsoft Azure", "GlobalBank"),
        ("shared-svc", "vpc-shared-001", "us-east-1", ["10.70.0.0/16"], "Amazon Web Services", "Shared Services"),
        ("gcp-analytics", "projects/netgraphy/global/networks/analytics", "us-central1", ["10.80.0.0/16"], "Google Cloud Platform", "Internal IT"),
    ]
    for name, cid, region, cidrs, provider, tenant in vpcs:
        vid = create_node("VPC", {
            "name": name, "cloud_id": cid, "region": region,
            "cidr_blocks": cidrs, "status": "active",
        })
        prov_id = n("CloudProvider", provider)
        ten_id = n("Tenant", tenant)
        if vid and prov_id:
            create_edge("VPC_IN_PROVIDER", vid, prov_id)
        if vid and ten_id:
            create_edge("VPC_OWNED_BY_TENANT", vid, ten_id)

    # VPC Peering
    create_edge("VPC_PEERED_WITH", n("VPC", "acme-prod-east"), n("VPC", "shared-svc"),
                {"peering_id": "pcx-abc123", "status": "active"})
    create_edge("VPC_PEERED_WITH", n("VPC", "acme-prod-west"), n("VPC", "shared-svc"),
                {"peering_id": "pcx-def456", "status": "active"})

    # Cloud Subnets
    subnets = [
        ("acme-east-pub-1a", "subnet-pub1a", "10.50.1.0/24", "us-east-1a", "public", "acme-prod-east"),
        ("acme-east-priv-1a", "subnet-priv1a", "10.50.10.0/24", "us-east-1a", "private", "acme-prod-east"),
        ("acme-east-priv-1b", "subnet-priv1b", "10.50.11.0/24", "us-east-1b", "private", "acme-prod-east"),
        ("acme-west-pub-2a", "subnet-pub2a", "10.51.1.0/24", "us-west-2a", "public", "acme-prod-west"),
        ("acme-west-priv-2a", "subnet-priv2a", "10.51.10.0/24", "us-west-2a", "private", "acme-prod-west"),
        ("gbank-eu-pub-1", "gbank-sub-pub1", "10.60.1.0/24", "westeurope-1", "public", "gbank-prod-eu"),
        ("gbank-eu-priv-1", "gbank-sub-priv1", "10.60.10.0/24", "westeurope-1", "private", "gbank-prod-eu"),
    ]
    for name, cid, cidr, az, stype, vpc_name in subnets:
        sid = create_node("CloudSubnet", {
            "name": name, "cloud_id": cid, "cidr": cidr,
            "availability_zone": az, "subnet_type": stype, "status": "active",
        })
        vpc_id = n("VPC", vpc_name)
        if sid and vpc_id:
            create_edge("SUBNET_IN_VPC", sid, vpc_id)

    # Cloud Gateways
    gateways = [
        ("acme-east-tgw", "tgw-abc123", "transit_gateway", "us-east-1", "Amazon Web Services", ["acme-prod-east", "shared-svc"]),
        ("acme-east-nat", "nat-abc123", "nat_gateway", "us-east-1", "Amazon Web Services", ["acme-prod-east"]),
        ("acme-east-igw", "igw-abc123", "internet_gateway", "us-east-1", "Amazon Web Services", ["acme-prod-east"]),
        ("acme-west-vpn", "vgw-def456", "vpn_gateway", "us-west-2", "Amazon Web Services", ["acme-prod-west"]),
        ("gbank-eu-er", "er-gbank-001", "expressroute", "westeurope", "Microsoft Azure", ["gbank-prod-eu"]),
    ]
    for name, cid, gtype, region, provider, vpc_names in gateways:
        gid = create_node("CloudGateway", {
            "name": name, "cloud_id": cid, "gateway_type": gtype,
            "region": region, "status": "active",
        })
        prov_id = n("CloudProvider", provider)
        if gid and prov_id:
            create_edge("GATEWAY_IN_PROVIDER", gid, prov_id)
        for vn in vpc_names:
            vpc_id = n("VPC", vn)
            if gid and vpc_id:
                create_edge("GATEWAY_IN_VPC", gid, vpc_id)


def seed_services():
    """Create network services."""
    print("\n=== Services ===")
    services = [
        ("MPLS WAN Backbone", "overlay", "MPLS", "active", "critical"),
        ("VXLAN-EVPN DC Fabric — DAL", "overlay", "VXLAN", "active", "critical"),
        ("VXLAN-EVPN DC Fabric — NYC", "overlay", "VXLAN", "active", "critical"),
        ("OSPF Underlay — DAL", "underlay", "OSPF", "active", "high"),
        ("OSPF Underlay — NYC", "underlay", "OSPF", "active", "high"),
        ("Corporate DNS", "infrastructure", "DNS", "active", "critical"),
        ("NTP Service", "infrastructure", "NTP", "active", "high"),
        ("DHCP — DAL", "infrastructure", "DHCP", "active", "medium"),
        ("Network Monitoring (SNMP)", "monitoring", "SNMP", "active", "high"),
    ]
    for name, stype, proto, status, crit in services:
        create_node("Service", {
            "name": name, "service_type": stype, "protocol": proto,
            "status": status, "criticality": crit,
        })

    # Service → Device
    svc_device_map = {
        "VXLAN-EVPN DC Fabric — DAL": ["DAL-SPN01", "DAL-SPN02", "DAL-LEAF01", "DAL-LEAF02", "DAL-LEAF03", "DAL-LEAF04"],
        "VXLAN-EVPN DC Fabric — NYC": ["NYC-SPN01", "NYC-SPN02", "NYC-LEAF01", "NYC-LEAF02", "NYC-LEAF03", "NYC-LEAF04"],
        "OSPF Underlay — DAL": ["DAL-COR-RTR01", "DAL-COR-RTR02", "DAL-SPN01", "DAL-SPN02"],
        "OSPF Underlay — NYC": ["NYC-COR-RTR01", "NYC-COR-RTR02", "NYC-SPN01", "NYC-SPN02"],
        "MPLS WAN Backbone": ["DAL-COR-RTR01", "DAL-COR-RTR02", "NYC-COR-RTR01", "NYC-COR-RTR02", "LON-COR-RTR01", "LON-COR-RTR02"],
    }
    for svc_name, hostnames in svc_device_map.items():
        svc_id = n("Service", svc_name)
        for h in hostnames:
            did = n("Device", h)
            if svc_id and did:
                create_edge("HOSTED_ON", svc_id, did)

    # Service dependencies
    create_edge("DEPENDS_ON", n("Service", "VXLAN-EVPN DC Fabric — DAL"), n("Service", "OSPF Underlay — DAL"),
                {"dependency_type": "hard"})
    create_edge("DEPENDS_ON", n("Service", "VXLAN-EVPN DC Fabric — NYC"), n("Service", "OSPF Underlay — NYC"),
                {"dependency_type": "hard"})


def seed_architectures():
    """Create architecture zones and wire them to devices, services, and locations."""
    print("\n=== Architectures ===")

    archs = [
        # (name, type, status, standard_name, standard_url, compliance, security, description)
        ("WAN Backbone", "backbone", "active", "SD-WAN / MPLS Reference", None, "compliant", None,
         "Global MPLS/SD-WAN backbone interconnecting all sites"),
        ("DC IP Fabric — DAL", "fabric", "active", "EVPN-VXLAN RFC 7348", "https://datatracker.ietf.org/doc/html/rfc7348", "compliant", None,
         "Spine-leaf EVPN-VXLAN fabric in Dallas data center"),
        ("DC IP Fabric — NYC", "fabric", "active", "EVPN-VXLAN RFC 7348", "https://datatracker.ietf.org/doc/html/rfc7348", "compliant", None,
         "Spine-leaf EVPN-VXLAN fabric in NYC data center"),
        ("DMZ", "zone", "active", "NIST SP 800-41", "https://csrc.nist.gov/pubs/sp/800/41/r1/final", "compliant", "low",
         "Demilitarized zone for public-facing services"),
        ("B2B Gateway", "zone", "active", "PCI DSS 4.0", None, "partial", "high",
         "Business-to-business interconnect zone for partner connectivity"),
        ("Campus Core — LON", "campus", "active", "Cisco SAFE Architecture", "https://www.cisco.com/c/en/us/solutions/enterprise/design-zone-security/index.html", "compliant", "medium",
         "London campus core switching and routing layer"),
        ("Branch WAN Edge", "edge", "active", "SD-WAN Reference Architecture", None, "compliant", None,
         "Branch office WAN edge routers and local switching"),
        ("Internet Edge", "edge", "active", "NIST SP 800-41", "https://csrc.nist.gov/pubs/sp/800/41/r1/final", "compliant", "untrusted",
         "Internet peering and transit edge — firewalled ingress/egress"),
        ("Cloud Transit", "cloud", "active", "AWS Transit Gateway Best Practices", None, "compliant", "medium",
         "Hub-and-spoke transit architecture connecting VPCs"),
        ("Server Zone — DAL", "zone", "active", None, None, "not_assessed", "high",
         "Trusted server zone behind DC firewall in Dallas"),
        ("Server Zone — NYC", "zone", "active", None, None, "not_assessed", "high",
         "Trusted server zone behind DC firewall in NYC"),
        ("Management Plane", "zone", "active", "CIS Benchmarks", None, "partial", "restricted",
         "Out-of-band management network for device access"),
    ]

    for name, atype, status, std_name, std_url, compliance, security, desc in archs:
        props: dict[str, Any] = {
            "name": name, "architecture_type": atype, "status": status,
            "compliance_level": compliance, "description": desc,
        }
        if std_name:
            props["standard_name"] = std_name
        if std_url:
            props["standard_url"] = std_url
        if security:
            props["security_level"] = security
        create_node("Architecture", props)

    # --- Architecture hierarchy (ARCHITECTURE_CONTAINS) ---
    hierarchy = [
        # parent → child
        ("DC IP Fabric — DAL", "Server Zone — DAL"),
        ("DC IP Fabric — NYC", "Server Zone — NYC"),
        ("Internet Edge", "DMZ"),
    ]
    for parent, child in hierarchy:
        create_edge("ARCHITECTURE_CONTAINS", n("Architecture", parent), n("Architecture", child))

    # --- Architecture ↔ Architecture connections ---
    connections = [
        ("DMZ", "Internet Edge", "filtered", "NGFW inbound policy"),
        ("DMZ", "Server Zone — DAL", "filtered", "App-tier firewall rules"),
        ("B2B Gateway", "WAN Backbone", "routed", "BGP partner peering policy"),
        ("WAN Backbone", "DC IP Fabric — DAL", "routed", None),
        ("WAN Backbone", "DC IP Fabric — NYC", "routed", None),
        ("WAN Backbone", "Campus Core — LON", "routed", None),
        ("WAN Backbone", "Branch WAN Edge", "tunneled", "SD-WAN overlay"),
        ("Cloud Transit", "DC IP Fabric — DAL", "tunneled", "Site-to-site VPN"),
        ("Management Plane", "DC IP Fabric — DAL", "filtered", "OOB access ACLs"),
        ("Management Plane", "DC IP Fabric — NYC", "filtered", "OOB access ACLs"),
    ]
    for src, tgt, ctype, policy in connections:
        props: dict[str, Any] = {"connection_type": ctype}
        if policy:
            props["policy"] = policy
        create_edge("ARCHITECTURE_CONNECTS_TO", n("Architecture", src), n("Architecture", tgt), props)

    # --- Device → Architecture ---
    device_arch = {
        "DC IP Fabric — DAL": [
            ("DAL-SPN01", "spine"), ("DAL-SPN02", "spine"),
            ("DAL-LEAF01", "leaf"), ("DAL-LEAF02", "leaf"),
            ("DAL-LEAF03", "leaf"), ("DAL-LEAF04", "leaf"),
        ],
        "DC IP Fabric — NYC": [
            ("NYC-SPN01", "spine"), ("NYC-SPN02", "spine"),
            ("NYC-LEAF01", "leaf"), ("NYC-LEAF02", "leaf"),
            ("NYC-LEAF03", "leaf"), ("NYC-LEAF04", "leaf"),
        ],
        "WAN Backbone": [
            ("DAL-COR-RTR01", "core"), ("DAL-COR-RTR02", "core"),
            ("NYC-COR-RTR01", "core"), ("NYC-COR-RTR02", "core"),
            ("LON-COR-RTR01", "core"), ("LON-COR-RTR02", "core"),
            ("FRA-COR-RTR01", "core"),
        ],
        "DMZ": [
            ("DAL-FW01", "firewall"), ("NYC-FW01", "firewall"),
        ],
        "Internet Edge": [
            ("DAL-COR-RTR01", "border"), ("NYC-COR-RTR01", "border"),
        ],
        "Campus Core — LON": [
            ("LON-COR-RTR01", "core"), ("LON-COR-RTR02", "core"),
            ("LON-SPN01", "distribution"), ("LON-SPN02", "distribution"),
            ("LON-LEAF01", "access"), ("LON-LEAF02", "access"),
        ],
        "Branch WAN Edge": [
            ("MEX-BR-RTR01", "edge"), ("CHI-BR-RTR01", "edge"), ("SEA-BR-RTR01", "edge"),
        ],
        "Management Plane": [
            ("DAL-COR-RTR01", "gateway"), ("NYC-COR-RTR01", "gateway"),
        ],
    }
    for arch_name, devices in device_arch.items():
        arch_id = n("Architecture", arch_name)
        for hostname, role in devices:
            did = n("Device", hostname)
            if arch_id and did:
                create_edge("DEVICE_IN_ARCHITECTURE", did, arch_id, {"device_role": role})

    # --- Service → Architecture ---
    svc_arch = {
        "VXLAN-EVPN DC Fabric — DAL": "DC IP Fabric — DAL",
        "VXLAN-EVPN DC Fabric — NYC": "DC IP Fabric — NYC",
        "OSPF Underlay — DAL": "DC IP Fabric — DAL",
        "OSPF Underlay — NYC": "DC IP Fabric — NYC",
        "MPLS WAN Backbone": "WAN Backbone",
        "Corporate DNS": "Management Plane",
        "NTP Service": "Management Plane",
    }
    for svc_name, arch_name in svc_arch.items():
        create_edge("SERVICE_IN_ARCHITECTURE", n("Service", svc_name), n("Architecture", arch_name))

    # --- Architecture → Location ---
    arch_loc = {
        "DC IP Fabric — DAL": ["DAL-DC1"],
        "DC IP Fabric — NYC": ["NYC-DC1"],
        "Server Zone — DAL": ["DAL-DC1"],
        "Server Zone — NYC": ["NYC-DC1"],
        "Campus Core — LON": ["LON-DC1"],
        "WAN Backbone": ["DAL-DC1", "NYC-DC1", "LON-DC1", "FRA-DC1"],
        "DMZ": ["DAL-DC1", "NYC-DC1"],
        "Branch WAN Edge": ["MEX-BR1", "CHI-BR1", "SEA-BR1"],
        "Management Plane": ["DAL-DC1", "NYC-DC1"],
    }
    for arch_name, locs in arch_loc.items():
        arch_id = n("Architecture", arch_name)
        for loc_name in locs:
            lid = n("Location", loc_name)
            if arch_id and lid:
                create_edge("ARCHITECTURE_AT_LOCATION", arch_id, lid)

    # --- VPC → Architecture ---
    create_edge("VPC_IN_ARCHITECTURE", n("VPC", "acme-prod-east"), n("Architecture", "Cloud Transit"))
    create_edge("VPC_IN_ARCHITECTURE", n("VPC", "acme-prod-west"), n("Architecture", "Cloud Transit"))
    create_edge("VPC_IN_ARCHITECTURE", n("VPC", "shared-svc"), n("Architecture", "Cloud Transit"))

    # --- Architecture → Tenant ---
    for arch in ["DC IP Fabric — DAL", "DC IP Fabric — NYC", "WAN Backbone", "DMZ", "Internet Edge"]:
        create_edge("ARCHITECTURE_OWNED_BY_TENANT", n("Architecture", arch), n("Tenant", "Acme Corp"))
    create_edge("ARCHITECTURE_OWNED_BY_TENANT", n("Architecture", "Campus Core — LON"), n("Tenant", "GlobalBank"))
    create_edge("ARCHITECTURE_OWNED_BY_TENANT", n("Architecture", "Management Plane"), n("Tenant", "Internal IT"))


def seed_cables_and_connections():
    """Create cables between interfaces and CONNECTED_TO edges for spine-leaf fabrics."""
    print("\n=== Cables & Connections ===")

    def _cable(label: str, cable_type: str, color: str, length_m: float,
               host_a: str, if_a: str, host_b: str, if_b: str):
        """Create a cable node, CABLE_ENDPOINT edges, and CONNECTED_TO edge."""
        cable_id = create_node("Cable", {
            "label": label, "cable_type": cable_type, "color": color,
            "status": "connected", "length_m": length_m,
        }, key_field="label")

        iface_a = n("Interface", f"{host_a}:{if_a}")
        iface_b = n("Interface", f"{host_b}:{if_b}")

        if cable_id and iface_a:
            create_edge("CABLE_ENDPOINT_A", cable_id, iface_a)
        if cable_id and iface_b:
            create_edge("CABLE_ENDPOINT_B", cable_id, iface_b)
        if iface_a and iface_b:
            create_edge("CONNECTED_TO", iface_a, iface_b,
                        {"cable_type": cable_type, "cable_id": label})

    # ----- Dallas spine-leaf full mesh (2 spines x 4 leaves = 8 cables) -----
    dal_leaves = ["DAL-LEAF01", "DAL-LEAF02", "DAL-LEAF03", "DAL-LEAF04"]
    for spine_idx, spine in enumerate(["DAL-SPN01", "DAL-SPN02"], start=0):
        for leaf_idx, leaf in enumerate(dal_leaves, start=1):
            cab_num = spine_idx * len(dal_leaves) + leaf_idx
            _cable(
                label=f"DAL-CAB-{cab_num:03d}",
                cable_type="fiber_smf", color="aqua",
                length_m=round(random.uniform(1, 15), 1),
                host_a=spine, if_a=f"Ethernet{leaf_idx}/1",
                host_b=leaf, if_b=f"Ethernet{spine_idx + 1}/1",
            )

    # ----- NYC spine-leaf full mesh (2 spines x 4 leaves = 8 cables) -----
    nyc_leaves = ["NYC-LEAF01", "NYC-LEAF02", "NYC-LEAF03", "NYC-LEAF04"]
    for spine_idx, spine in enumerate(["NYC-SPN01", "NYC-SPN02"], start=0):
        for leaf_idx, leaf in enumerate(nyc_leaves, start=1):
            cab_num = spine_idx * len(nyc_leaves) + leaf_idx
            _cable(
                label=f"NYC-CAB-{cab_num:03d}",
                cable_type="fiber_smf", color="aqua",
                length_m=round(random.uniform(1, 15), 1),
                host_a=spine, if_a=f"Ethernet{leaf_idx}/1",
                host_b=leaf, if_b=f"Ethernet{spine_idx + 1}/1",
            )

    # ----- London spine-leaf full mesh (2 spines x 2 leaves = 4 cables) -----
    lon_leaves = ["LON-LEAF01", "LON-LEAF02"]
    for spine_idx, spine in enumerate(["LON-SPN01", "LON-SPN02"], start=0):
        for leaf_idx, leaf in enumerate(lon_leaves, start=1):
            cab_num = spine_idx * len(lon_leaves) + leaf_idx
            _cable(
                label=f"LON-CAB-{cab_num:03d}",
                cable_type="fiber_smf", color="aqua",
                length_m=round(random.uniform(1, 15), 1),
                host_a=spine, if_a=f"Ethernet{leaf_idx}/1",
                host_b=leaf, if_b=f"Ethernet{spine_idx + 1}/1",
            )

    # ----- Core router to firewall uplinks -----
    # Dallas: COR-RTR → FW
    _cable("DAL-CAB-RTR-FW01", "cat6a", "blue", round(random.uniform(1, 15), 1),
           "DAL-COR-RTR01", "GigabitEthernet0/0/0", "DAL-FW01", "ethernet1/1")
    _cable("DAL-CAB-RTR-FW02", "cat6a", "blue", round(random.uniform(1, 15), 1),
           "DAL-COR-RTR02", "GigabitEthernet0/0/0", "DAL-FW01", "ethernet1/2")

    # NYC: COR-RTR → FW
    _cable("NYC-CAB-RTR-FW01", "cat6a", "blue", round(random.uniform(1, 15), 1),
           "NYC-COR-RTR01", "GigabitEthernet0/0/0", "NYC-FW01", "ethernet1/1")
    _cable("NYC-CAB-RTR-FW02", "cat6a", "blue", round(random.uniform(1, 15), 1),
           "NYC-COR-RTR02", "GigabitEthernet0/0/0", "NYC-FW01", "ethernet1/2")

    # ----- Branch router to switch links -----
    branch_links = [
        ("MEX-BR-RTR01", "MEX-BR-SW01", "MEX-CAB-BR01"),
        ("CHI-BR-RTR01", "CHI-BR-SW01", "CHI-CAB-BR01"),
        ("SEA-BR-RTR01", "SEA-BR-SW01", "SEA-CAB-BR01"),
    ]
    for rtr, sw, label in branch_links:
        _cable(label, "cat6a", "green", round(random.uniform(2, 50), 1),
               rtr, "GigabitEthernet0/0/1", sw, "GigabitEthernet1/0/1")


def seed_circuits():
    """Create providers, circuit types, circuits with A/Z terminations."""
    print("\n=== Circuits ===")

    # ----- Providers -----
    providers = [
        ("Lumen Technologies", "lumen", 3356),
        ("Zayo Group", "zayo", 6461),
        ("Equinix", "equinix", None),
        ("Megaport", "megaport", None),
    ]
    for pname, slug, asn in providers:
        props: dict[str, Any] = {"name": pname, "slug": slug}
        if asn is not None:
            props["asn"] = asn
        create_node("Provider", props)

    # ----- Circuit Types -----
    circuit_types = [
        ("Internet Transit", "internet-transit"),
        ("MPLS VPN", "mpls-vpn"),
        ("Dark Fiber", "dark-fiber"),
        ("Cross Connect", "cross-connect"),
        ("Cloud On-Ramp", "cloud-on-ramp"),
    ]
    for ct_name, ct_slug in circuit_types:
        create_node("CircuitType", {"name": ct_name, "slug": ct_slug})

    # ----- Provider presence at locations -----
    provider_locations = {
        "Lumen Technologies": ["DAL-DC1", "NYC-DC1", "LON-DC1", "FRA-DC1", "SIN-DC1", "MEX-BR1", "CHI-BR1"],
        "Zayo Group": ["NYC-DC1", "LON-DC1", "SEA-BR1"],
        "Equinix": ["DAL-DC1", "NYC-DC1"],
        "Megaport": ["DAL-DC1", "NYC-DC1"],
    }
    for pname, locs in provider_locations.items():
        prov_id = n("Provider", pname)
        for loc_name in locs:
            loc_id = n("Location", loc_name)
            if prov_id and loc_id:
                create_edge("PROVIDER_IN_LOCATION", prov_id, loc_id)

    # ----- Helper to create a circuit with terminations -----
    def _circuit(cid: str, provider: str, ctype: str, status: str,
                 bandwidth_kbps: int | None, commit_rate_kbps: int | None,
                 a_location: str, z_location: str | None = None,
                 xconnect_id: str | None = None, patch_panel: str | None = None):
        """Create a circuit, its type/provider edges, and A/Z terminations."""
        props: dict[str, Any] = {"cid": cid, "status": status}
        if bandwidth_kbps is not None:
            props["bandwidth_kbps"] = bandwidth_kbps
        if commit_rate_kbps is not None:
            props["commit_rate_kbps"] = commit_rate_kbps

        ckt_id = create_node("Circuit", props, key_field="cid")
        if not ckt_id:
            return

        # Wire to type and provider
        ct_id = n("CircuitType", ctype)
        if ct_id:
            create_edge("CIRCUIT_HAS_TYPE", ckt_id, ct_id)
        prov_id = n("Provider", provider)
        if prov_id:
            create_edge("CIRCUIT_FROM_PROVIDER", ckt_id, prov_id)

        # A-side termination
        a_props: dict[str, Any] = {"term_side": "A"}
        if bandwidth_kbps:
            a_props["port_speed_kbps"] = bandwidth_kbps
        if xconnect_id:
            a_props["xconnect_id"] = xconnect_id
        if patch_panel:
            a_props["patch_panel"] = patch_panel
        term_a = create_node("CircuitTermination", a_props,
                             dedup_key=f"CircuitTermination:{cid}:A")
        if term_a:
            create_edge("CIRCUIT_HAS_TERMINATION", ckt_id, term_a)
            a_loc = n("Location", a_location)
            if a_loc:
                create_edge("TERMINATION_AT_LOCATION", term_a, a_loc)

        # Z-side termination (if applicable)
        if z_location:
            z_props: dict[str, Any] = {"term_side": "Z"}
            if bandwidth_kbps:
                z_props["port_speed_kbps"] = bandwidth_kbps
            term_z = create_node("CircuitTermination", z_props,
                                 dedup_key=f"CircuitTermination:{cid}:Z")
            if term_z:
                create_edge("CIRCUIT_HAS_TERMINATION", ckt_id, term_z)
                z_loc = n("Location", z_location)
                if z_loc:
                    create_edge("TERMINATION_AT_LOCATION", term_z, z_loc)

    # ----- Internet Transit circuits -----
    _circuit("CKT-LUMEN-DAL-INT01", "Lumen Technologies", "Internet Transit",
             "active", 1_000_000, 1_000_000, "DAL-DC1")
    _circuit("CKT-ZAYO-NYC-INT01", "Zayo Group", "Internet Transit",
             "active", 1_000_000, 1_000_000, "NYC-DC1")
    _circuit("CKT-LUMEN-LON-INT01", "Lumen Technologies", "Internet Transit",
             "active", 500_000, 500_000, "LON-DC1")

    # ----- MPLS VPN circuits (site-to-site) -----
    _circuit("CKT-LUMEN-MPLS-DAL-NYC", "Lumen Technologies", "MPLS VPN",
             "active", 10_000_000, 10_000_000, "DAL-DC1", "NYC-DC1")
    _circuit("CKT-LUMEN-MPLS-DAL-LON", "Lumen Technologies", "MPLS VPN",
             "active", 1_000_000, 1_000_000, "DAL-DC1", "LON-DC1")
    _circuit("CKT-ZAYO-MPLS-NYC-LON", "Zayo Group", "MPLS VPN",
             "active", 1_000_000, 1_000_000, "NYC-DC1", "LON-DC1")
    _circuit("CKT-LUMEN-MPLS-DAL-FRA", "Lumen Technologies", "MPLS VPN",
             "active", 500_000, 500_000, "DAL-DC1", "FRA-DC1")
    _circuit("CKT-LUMEN-MPLS-DAL-SIN", "Lumen Technologies", "MPLS VPN",
             "planned", 500_000, 500_000, "DAL-DC1", "SIN-DC1")

    # ----- Cross Connects -----
    _circuit("CKT-EQX-DAL-XCON01", "Equinix", "Cross Connect",
             "active", None, None, "DAL-DC1",
             xconnect_id="EQX-DAL-XCON-4412", patch_panel="PP-A-12")
    _circuit("CKT-EQX-NYC-XCON01", "Equinix", "Cross Connect",
             "active", None, None, "NYC-DC1",
             xconnect_id="EQX-NYC-XCON-7801", patch_panel="PP-B-03")

    # ----- Cloud On-Ramp -----
    _circuit("CKT-MEGA-DAL-AWS01", "Megaport", "Cloud On-Ramp",
             "active", 1_000_000, 1_000_000, "DAL-DC1")
    _circuit("CKT-MEGA-NYC-AZR01", "Megaport", "Cloud On-Ramp",
             "active", 1_000_000, 1_000_000, "NYC-DC1")

    # ----- Branch Internet -----
    _circuit("CKT-LUMEN-MEX-INT01", "Lumen Technologies", "Internet Transit",
             "active", 100_000, 100_000, "MEX-BR1")
    _circuit("CKT-LUMEN-CHI-INT01", "Lumen Technologies", "Internet Transit",
             "active", 100_000, 100_000, "CHI-BR1")
    _circuit("CKT-ZAYO-SEA-INT01", "Zayo Group", "Internet Transit",
             "active", 100_000, 100_000, "SEA-BR1")


def seed_parsers_and_ingestion():
    """Register TextFSM parsers, command bundles, mappings, and custom filters.

    Creates _Parser, _CommandBundle, _MappingDef, and _JinjaFilter nodes via
    the API so the ingestion pipeline has working seed data for testing.
    """
    import json as _json
    import pathlib
    import yaml

    print("\n=== Parsers & Ingestion Pipeline ===")

    parsers_root = pathlib.Path(__file__).resolve().parent.parent / "parsers"

    # ---- 1. Register TextFSM parsers via POST /parsers ----
    parser_defs = [
        {
            "name": "cisco_ios_show_version",
            "platform": "cisco_ios",
            "command": "show version",
            "description": "Parse Cisco IOS 'show version' output",
            "template_file": "templates/cisco_ios_show_version.textfsm",
        },
        {
            "name": "cisco_ios_show_ip_int_brief",
            "platform": "cisco_ios",
            "command": "show ip interface brief",
            "description": "Parse Cisco IOS 'show ip interface brief' output",
            "template_file": "templates/cisco_ios_show_ip_int_brief.textfsm",
        },
        {
            "name": "cisco_ios_show_inventory",
            "platform": "cisco_ios",
            "command": "show inventory",
            "description": "Parse Cisco IOS 'show inventory' output",
            "template_file": "templates/cisco_ios_show_inventory.textfsm",
        },
        {
            "name": "cisco_ios_show_cdp_neighbors_detail",
            "platform": "cisco_ios",
            "command": "show cdp neighbors detail",
            "description": "Parse Cisco IOS 'show cdp neighbors detail' output",
            "template_file": "templates/cisco_ios_show_cdp_neighbors_detail.textfsm",
        },
    ]

    for pdef in parser_defs:
        tpl_path = parsers_root / pdef["template_file"]
        if not tpl_path.exists():
            print(f"  WARN template not found: {tpl_path}")
            continue
        template_content = tpl_path.read_text()
        body = {
            "name": pdef["name"],
            "platform": pdef["platform"],
            "command": pdef["command"],
            "description": pdef["description"],
            "template": template_content,
        }
        resp = SESSION.post(f"{BASE_URL}/parsers", json=body)
        if resp.status_code == 201:
            print(f"  Parser registered: {pdef['name']}")
        else:
            print(f"  WARN parser {pdef['name']}: {resp.status_code} {resp.text[:200]}")

    # ---- 2. Register command bundles via Cypher ----
    bundle_files = [
        "commands/cisco_ios_base.yaml",
        "commands/f5_ltm_base.yaml",
    ]

    for bf in bundle_files:
        bf_path = parsers_root / bf
        if not bf_path.exists():
            print(f"  WARN bundle not found: {bf_path}")
            continue
        bundle = yaml.safe_load(bf_path.read_text())
        meta = bundle.get("metadata", {})
        bundle_name = meta.get("name", bf)
        cypher = (
            "MERGE (cb:_CommandBundle {name: $name}) "
            "SET cb.description = $description, cb.platform = $platform, "
            "    cb.tags = $tags, cb.version = $version, "
            "    cb.commands_json = $commands_json, cb.managed_by = 'seed'"
        )
        params = {
            "name": bundle_name,
            "description": meta.get("description", ""),
            "platform": meta.get("platform", ""),
            "tags": meta.get("tags", []),
            "version": bundle.get("version", "v2"),
            "commands_json": _json.dumps(bundle.get("commands", [])),
        }
        resp = SESSION.post(f"{BASE_URL}/query/cypher", json={"query": cypher, "parameters": params})
        if resp.status_code == 200:
            print(f"  CommandBundle registered: {bundle_name}")
        else:
            print(f"  WARN bundle {bundle_name}: {resp.status_code} {resp.text[:200]}")

    # ---- 3. Register mapping definitions via Cypher ----
    mapping_files = [
        "mappings/cisco_ios_version_to_graph.yaml",
        "mappings/cisco_ios_inventory_to_graph.yaml",
        "mappings/cisco_ios_cdp_to_graph.yaml",
    ]

    for mf in mapping_files:
        mf_path = parsers_root / mf
        if not mf_path.exists():
            print(f"  WARN mapping not found: {mf_path}")
            continue
        mapping = yaml.safe_load(mf_path.read_text())
        meta = mapping.get("metadata", {})
        mapping_name = meta.get("name", mf)
        cypher = (
            "MERGE (m:_MappingDef {name: $name}) "
            "SET m.description = $description, m.parser = $parser, "
            "    m.platform = $platform, m.version = $version, "
            "    m.definition_json = $definition_json, m.managed_by = 'seed'"
        )
        params = {
            "name": mapping_name,
            "description": meta.get("description", ""),
            "parser": meta.get("parser", ""),
            "platform": meta.get("platform", ""),
            "version": mapping.get("version", "v2"),
            "definition_json": _json.dumps(mapping.get("mappings", [])),
        }
        resp = SESSION.post(f"{BASE_URL}/query/cypher", json={"query": cypher, "parameters": params})
        if resp.status_code == 200:
            print(f"  MappingDef registered: {mapping_name}")
        else:
            print(f"  WARN mapping {mapping_name}: {resp.status_code} {resp.text[:200]}")

    # ---- 4. Register custom Jinja2 filter via Cypher ----
    filter_path = parsers_root / "filters" / "network_filters.py"
    if filter_path.exists():
        source = filter_path.read_text()
        cypher = (
            "MERGE (f:_JinjaFilter {name: $name}) "
            "SET f.python_source = $source, f.description = $description, "
            "    f.is_active = true, f.managed_by = 'seed'"
        )
        params = {
            "name": "classify_inventory_type",
            "source": source,
            "description": "Classify inventory item NAME into item_type enum value",
        }
        resp = SESSION.post(f"{BASE_URL}/query/cypher", json={"query": cypher, "parameters": params})
        if resp.status_code == 200:
            print("  JinjaFilter registered: classify_inventory_type")
        else:
            print(f"  WARN filter classify_inventory_type: {resp.status_code} {resp.text[:200]}")
    else:
        print(f"  WARN filter file not found: {filter_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  NetGraphy Seed Data")
    print("=" * 60)
    print(f"Target: {BASE_URL}")

    wait_for_api()
    login()

    seed_vendors_and_models()
    seed_hardware_templates()
    seed_platforms()
    seed_software_versions()
    seed_tenants()
    seed_locations()
    seed_devices()
    seed_inventory()
    seed_ipam()
    seed_cloud()
    seed_services()
    seed_architectures()
    seed_parsers_and_ingestion()
    seed_cables_and_connections()
    seed_circuits()

    print("\n" + "=" * 60)
    print(f"  Done! Created {len(IDS)} objects.")
    print("=" * 60)


if __name__ == "__main__":
    main()
