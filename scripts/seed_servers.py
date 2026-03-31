#!/usr/bin/env python3
"""Seed servers with NICs, MACs, and IPs connected to leaf switches.

Creates synthetic data for testing MAC-to-MAC path traversal:
  Server (Device) → Interface (NIC) → MACAddress → IPAddress
  Server NIC CONNECTED_TO Leaf Switch Interface

Usage:
  export NETGRAPHY_URL=https://api-staging-a8ac.up.railway.app/api/v1
  export NETGRAPHY_USER=admin
  export NETGRAPHY_PASS=admin
  python scripts/seed_servers.py
"""

import os
import sys
import random
import requests
from typing import Any

BASE_URL = os.environ.get("NETGRAPHY_URL", "http://localhost:8000/api/v1")
USERNAME = os.environ.get("NETGRAPHY_USER", "admin")
PASSWORD = os.environ.get("NETGRAPHY_PASS", "admin")

TOKEN: str | None = None
SESSION = requests.Session()
IDS: dict[str, str] = {}


def login():
    resp = SESSION.post(f"{BASE_URL}/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code != 200:
        print(f"Login failed: {resp.status_code}")
        sys.exit(1)
    global TOKEN
    TOKEN = resp.json()["data"]["access_token"]
    SESSION.headers["Authorization"] = f"Bearer {TOKEN}"
    print(f"Logged in as {USERNAME}")


def create_node(node_type: str, props: dict[str, Any], key_field: str = "name", dedup_key: str | None = None) -> str | None:
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
    return IDS.get(f"{node_type}:{key_value}")


def rand_mac(prefix: str = "02") -> str:
    return f"{prefix}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}"


def lookup_device(hostname: str) -> str | None:
    """Look up an existing device by hostname."""
    resp = SESSION.get(f"{BASE_URL}/objects/Device", params={"hostname": hostname})
    if resp.status_code == 200:
        items = resp.json().get("data", [])
        if items:
            did = items[0].get("id")
            IDS[f"Device:{hostname}"] = did
            return did
    return None


def main():
    login()

    # DC sites with their leaf switches
    dc_config = {
        "DAL-DC1": {
            "leaves": ["DAL-LEAF01", "DAL-LEAF02", "DAL-LEAF03", "DAL-LEAF04"],
            "subnet": "10.10",
            "servers_per_leaf": 3,
        },
        "NYC-DC1": {
            "leaves": ["NYC-LEAF01", "NYC-LEAF02", "NYC-LEAF03", "NYC-LEAF04"],
            "subnet": "10.20",
            "servers_per_leaf": 3,
        },
        "LON-DC1": {
            "leaves": ["LON-LEAF01", "LON-LEAF02"],
            "subnet": "10.30",
            "servers_per_leaf": 4,
        },
    }

    total_servers = 0
    total_macs = 0
    total_ips = 0
    total_connections = 0

    for site, cfg in dc_config.items():
        print(f"\n=== {site} ===")

        for leaf_idx, leaf_name in enumerate(cfg["leaves"]):
            # Look up the leaf switch
            leaf_id = lookup_device(leaf_name)
            if not leaf_id:
                print(f"  SKIP: Leaf {leaf_name} not found")
                continue

            print(f"  Leaf: {leaf_name}")

            for srv_idx in range(cfg["servers_per_leaf"]):
                srv_num = leaf_idx * cfg["servers_per_leaf"] + srv_idx + 1
                site_prefix = site.split("-")[0]
                srv_hostname = f"{site_prefix}-SRV{srv_num:02d}"

                # Create server device
                srv_id = create_node("Device", {
                    "hostname": srv_hostname,
                    "role": "server",
                    "status": "active",
                    "serial_number": f"SRV-{site_prefix}-{srv_num:04d}",
                }, key_field="hostname")

                if not srv_id:
                    continue

                total_servers += 1
                print(f"    Server: {srv_hostname}")

                # Wire server to location
                loc_id = lookup_device(site)  # Won't work — need location lookup
                # Just create the edge via the site name pattern
                loc_resp = SESSION.get(f"{BASE_URL}/objects/Location", params={"name": site})
                if loc_resp.status_code == 200:
                    locs = loc_resp.json().get("data", [])
                    if locs:
                        create_edge("LOCATED_IN", srv_id, locs[0]["id"])

                # Create 2 NICs per server (dual-homed)
                for nic_idx in range(2):
                    nic_name = f"eth{nic_idx}"
                    nic_mac = rand_mac(prefix=f"0{nic_idx + 2}")
                    ip_third = leaf_idx * 16 + srv_idx * 2 + nic_idx + 1
                    nic_ip = f"{cfg['subnet']}.{leaf_idx + 1}.{ip_third}"

                    # Create server interface (NIC)
                    iface_id = create_node("Interface", {
                        "name": f"{srv_hostname}/{nic_name}",
                        "interface_type": "physical",
                        "enabled": True,
                        "oper_status": "up",
                        "speed_mbps": 25000,
                        "mac_address": nic_mac,
                        "mtu": 9000,
                        "mode": "access",
                        "description": f"Server NIC {nic_name} to {leaf_name}",
                    }, key_field="name")

                    if not iface_id:
                        continue

                    # Wire interface to server
                    create_edge("HAS_INTERFACE", srv_id, iface_id)

                    # Create MAC address node
                    mac_id = create_node("MACAddress", {
                        "address": nic_mac,
                        "status": "active",
                        "mac_type": "unicast",
                        "vendor_oui": "Server NIC",
                    }, key_field="address")

                    if mac_id:
                        create_edge("MAC_ON_INTERFACE", mac_id, iface_id)
                        total_macs += 1

                    # Create IP address node
                    ip_id = create_node("IPAddress", {
                        "address": f"{nic_ip}/24",
                        "status": "active",
                        "ip_version": "4",
                        "role": "server",
                    }, key_field="address")

                    if ip_id:
                        create_edge("IP_ON_INTERFACE", ip_id, iface_id)
                        if mac_id:
                            create_edge("MAC_HAS_IP", mac_id, ip_id, {"source_table": "arp"})
                        total_ips += 1

                    # Create leaf switch port interface
                    leaf_port = f"Ethernet{srv_num * 2 + nic_idx - 1}"
                    leaf_port_name = f"{leaf_name}/{leaf_port}"
                    leaf_mac = rand_mac(prefix="44")

                    leaf_iface_id = create_node("Interface", {
                        "name": leaf_port_name,
                        "interface_type": "physical",
                        "enabled": True,
                        "oper_status": "up",
                        "speed_mbps": 25000,
                        "mac_address": leaf_mac,
                        "mtu": 9000,
                        "mode": "access",
                        "description": f"To {srv_hostname} {nic_name}",
                    }, key_field="name")

                    if leaf_iface_id:
                        # Wire leaf port to leaf switch
                        create_edge("HAS_INTERFACE", leaf_id, leaf_iface_id)

                        # Create leaf port MAC
                        leaf_mac_id = create_node("MACAddress", {
                            "address": leaf_mac,
                            "status": "active",
                            "mac_type": "unicast",
                            "vendor_oui": "Arista" if "DAL" in leaf_name or "NYC" in leaf_name else "Juniper",
                        }, key_field="address")

                        if leaf_mac_id:
                            create_edge("MAC_ON_INTERFACE", leaf_mac_id, leaf_iface_id)
                            total_macs += 1

                        # CONNECTED_TO between server NIC and leaf port
                        create_edge("CONNECTED_TO", iface_id, leaf_iface_id,
                                    {"cable_type": "cat6a", "cable_id": f"CAB-{site_prefix}-{srv_num:02d}-{nic_name}"})
                        total_connections += 1

    print(f"\n=== Summary ===")
    print(f"  Servers:     {total_servers}")
    print(f"  MACs:        {total_macs}")
    print(f"  IPs:         {total_ips}")
    print(f"  Connections: {total_connections}")


if __name__ == "__main__":
    main()
