#!/usr/bin/env python3
"""Seed missing spine-to-leaf physical connections in all DC fabrics.

The original seed created spine and leaf devices but never connected them
with CONNECTED_TO edges. This script closes the gap so paths can traverse:
  Leaf → Spine → T2B → Circuit → T2B → Spine → Leaf

Usage:
  export NETGRAPHY_URL=https://api-staging-a8ac.up.railway.app/api/v1
  export NETGRAPHY_USER=admin
  export NETGRAPHY_PASS=admin
  python scripts/seed_fabric_links.py
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


def create_node(node_type, props, key_field="name", dedup_key=None):
    tag = dedup_key or f"{node_type}:{props.get(key_field, '?')}"
    if tag in IDS:
        return IDS[tag]
    resp = SESSION.post(f"{BASE_URL}/objects/{node_type}", json=props)
    if resp.status_code == 201:
        nid = resp.json()["data"]["id"]
        IDS[tag] = nid
        return nid
    print(f"  WARN create {tag}: {resp.status_code} {resp.text[:200]}")
    return None


def create_edge(edge_type, source_id, target_id, props=None):
    if not source_id or not target_id:
        return None
    body = {"source_id": source_id, "target_id": target_id}
    if props:
        body.update(props)
    resp = SESSION.post(f"{BASE_URL}/edges/{edge_type}", json=body)
    if resp.status_code == 201:
        return resp.json()["data"]["id"]
    print(f"  WARN edge {edge_type}: {resp.status_code} {resp.text[:150]}")
    return None


def lookup_device(hostname):
    if f"Device:{hostname}" in IDS:
        return IDS[f"Device:{hostname}"]
    resp = SESSION.get(f"{BASE_URL}/objects/Device", params={"hostname": hostname})
    if resp.status_code == 200:
        items = resp.json().get("data", [])
        if items:
            did = items[0]["id"]
            IDS[f"Device:{hostname}"] = did
            return did
    return None


def rand_mac(prefix="44"):
    return f"{prefix}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}"


def connect_devices(dev_a_name, port_a_num, dev_b_name, port_b_num, speed=100000):
    """Create interfaces on both devices and a CONNECTED_TO edge between them."""
    dev_a = lookup_device(dev_a_name)
    dev_b = lookup_device(dev_b_name)
    if not dev_a or not dev_b:
        print(f"  SKIP: {dev_a_name} or {dev_b_name} not found")
        return

    # Interface on device A
    iface_a_name = f"{dev_a_name}/Ethernet{port_a_num}"
    mac_a = rand_mac()
    iface_a = create_node("Interface", {
        "name": iface_a_name,
        "interface_type": "physical",
        "enabled": True,
        "oper_status": "up",
        "speed_mbps": speed,
        "mac_address": mac_a,
        "mtu": 9216,
        "mode": "routed",
        "description": f"Fabric link to {dev_b_name}",
    }, key_field="name")

    if not iface_a:
        return

    create_edge("HAS_INTERFACE", dev_a, iface_a)

    mac_a_id = create_node("MACAddress", {
        "address": mac_a, "status": "active",
        "mac_type": "unicast", "vendor_oui": "Switch",
    }, key_field="address")
    if mac_a_id:
        create_edge("MAC_ON_INTERFACE", mac_a_id, iface_a)

    # Interface on device B
    iface_b_name = f"{dev_b_name}/Ethernet{port_b_num}"
    mac_b = rand_mac()
    iface_b = create_node("Interface", {
        "name": iface_b_name,
        "interface_type": "physical",
        "enabled": True,
        "oper_status": "up",
        "speed_mbps": speed,
        "mac_address": mac_b,
        "mtu": 9216,
        "mode": "routed",
        "description": f"Fabric link to {dev_a_name}",
    }, key_field="name")

    if not iface_b:
        return

    create_edge("HAS_INTERFACE", dev_b, iface_b)

    mac_b_id = create_node("MACAddress", {
        "address": mac_b, "status": "active",
        "mac_type": "unicast", "vendor_oui": "Switch",
    }, key_field="address")
    if mac_b_id:
        create_edge("MAC_ON_INTERFACE", mac_b_id, iface_b)

    # CONNECTED_TO
    create_edge("CONNECTED_TO", iface_a, iface_b,
                {"cable_type": "fiber_smf", "cable_id": f"FAB-{dev_a_name}-{dev_b_name}"})

    print(f"  {dev_a_name}/Eth{port_a_num} <-> {dev_b_name}/Eth{port_b_num}")


def main():
    login()

    # =====================================================================
    # Spine-to-Leaf full mesh per DC (each leaf connects to each spine)
    # =====================================================================

    fabrics = {
        "DAL": {
            "spines": ["DAL-SPN01", "DAL-SPN02"],
            "leaves": ["DAL-LEAF01", "DAL-LEAF02", "DAL-LEAF03", "DAL-LEAF04"],
        },
        "NYC": {
            "spines": ["NYC-SPN01", "NYC-SPN02"],
            "leaves": ["NYC-LEAF01", "NYC-LEAF02", "NYC-LEAF03", "NYC-LEAF04"],
        },
        "LON": {
            "spines": ["LON-SPN01", "LON-SPN02"],
            "leaves": ["LON-LEAF01", "LON-LEAF02"],
        },
    }

    total_links = 0

    for dc, cfg in fabrics.items():
        print(f"\n=== {dc} Spine-Leaf Fabric ===")

        for leaf_idx, leaf in enumerate(cfg["leaves"]):
            for spn_idx, spine in enumerate(cfg["spines"]):
                # Spine port: Ethernet1-8 for leaf downlinks
                spn_port = leaf_idx * 2 + spn_idx + 1
                # Leaf port: Ethernet49-50 for spine uplinks
                leaf_port = 49 + spn_idx

                connect_devices(spine, spn_port, leaf, leaf_port, speed=100000)
                total_links += 1

    print(f"\n=== Summary ===")
    print(f"  Fabric links created: {total_links}")
    print(f"  DAL: {len(fabrics['DAL']['leaves'])} leaves x {len(fabrics['DAL']['spines'])} spines = {len(fabrics['DAL']['leaves']) * len(fabrics['DAL']['spines'])} links")
    print(f"  NYC: {len(fabrics['NYC']['leaves'])} leaves x {len(fabrics['NYC']['spines'])} spines = {len(fabrics['NYC']['leaves']) * len(fabrics['NYC']['spines'])} links")
    print(f"  LON: {len(fabrics['LON']['leaves'])} leaves x {len(fabrics['LON']['spines'])} spines = {len(fabrics['LON']['leaves']) * len(fabrics['LON']['spines'])} links")
    print(f"\n  Full chain now available:")
    print(f"  MAC → Server NIC → Server → Leaf → Spine → T2B → Circuit → T2B → Spine → Leaf → Server → Server NIC → MAC")


if __name__ == "__main__":
    main()
