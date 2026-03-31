#!/usr/bin/env python3
"""Seed WAN transport routers (T2B) and leased line circuits between all DCs.

Creates the WAN backbone that closes the loop between DCs:
  Spine → CONNECTED_TO → T2B → Circuit Termination → Circuit → Circuit Termination → T2B → CONNECTED_TO → Spine

This enables MAC-to-MAC path traversal across DCs:
  MAC → Interface → Server → Leaf → Spine → T2B → Circuit → T2B → Spine → Leaf → Server → Interface → MAC

Usage:
  export NETGRAPHY_URL=https://api-staging-a8ac.up.railway.app/api/v1
  export NETGRAPHY_USER=admin
  export NETGRAPHY_PASS=admin
  python scripts/seed_wan.py
"""

import os
import sys
import random
import itertools
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


def rand_mac(prefix: str = "00") -> str:
    return f"{prefix}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}:{random.randint(0,255):02X}"


def lookup_device(hostname: str) -> str | None:
    """Look up an existing device by hostname."""
    if f"Device:{hostname}" in IDS:
        return IDS[f"Device:{hostname}"]
    resp = SESSION.get(f"{BASE_URL}/objects/Device", params={"hostname": hostname})
    if resp.status_code == 200:
        items = resp.json().get("data", [])
        if items:
            did = items[0].get("id")
            IDS[f"Device:{hostname}"] = did
            return did
    return None


def lookup_location(name: str) -> str | None:
    if f"Location:{name}" in IDS:
        return IDS[f"Location:{name}"]
    resp = SESSION.get(f"{BASE_URL}/objects/Location", params={"name": name})
    if resp.status_code == 200:
        items = resp.json().get("data", [])
        if items:
            lid = items[0].get("id")
            IDS[f"Location:{name}"] = lid
            return lid
    return None


def main():
    login()

    # DC sites with their spine switches and WAN IP subnets
    dcs = {
        "DAL": {
            "site": "DAL-DC1",
            "spines": ["DAL-SPN01", "DAL-SPN02"],
            "loopback": "172.16.1",
            "model": "ASR 9001",
            "platform": "IOS-XR",
        },
        "NYC": {
            "site": "NYC-DC1",
            "spines": ["NYC-SPN01", "NYC-SPN02"],
            "loopback": "172.16.2",
            "model": "ASR 9001",
            "platform": "IOS-XR",
        },
        "LON": {
            "site": "LON-DC1",
            "spines": ["LON-SPN01", "LON-SPN02"],
            "loopback": "172.16.3",
            "model": "MX204",
            "platform": "Junos",
        },
    }

    # =========================================================================
    # 1. Create T2B routers at each DC
    # =========================================================================
    print("\n=== Creating T2B Transport/Border Routers ===")

    for prefix, cfg in dcs.items():
        site = cfg["site"]
        loc_id = lookup_location(site)

        for t2b_num in [1, 2]:
            hostname = f"{prefix}-T2B0{t2b_num}"
            print(f"  Creating {hostname}")

            t2b_id = create_node("Device", {
                "hostname": hostname,
                "role": "router",
                "status": "active",
                "serial_number": f"T2B-{prefix}-{t2b_num:04d}",
                "description": f"Transport/Border router {t2b_num} at {site}",
            }, key_field="hostname")

            if not t2b_id:
                continue

            # Wire to location
            if loc_id:
                create_edge("LOCATED_IN", t2b_id, loc_id)

            # Create uplink interfaces to spines (2 per spine for redundancy)
            for spn_idx, spn_name in enumerate(cfg["spines"]):
                spn_id = lookup_device(spn_name)
                if not spn_id:
                    print(f"    SKIP: Spine {spn_name} not found")
                    continue

                # T2B uplink interface
                t2b_iface_name = f"{hostname}/Ethernet{spn_idx + 1}"
                t2b_mac = rand_mac(prefix="08")
                t2b_iface_id = create_node("Interface", {
                    "name": t2b_iface_name,
                    "interface_type": "physical",
                    "enabled": True,
                    "oper_status": "up",
                    "speed_mbps": 100000,
                    "mac_address": t2b_mac,
                    "mtu": 9216,
                    "mode": "routed",
                    "description": f"Uplink to {spn_name}",
                }, key_field="name")

                if not t2b_iface_id:
                    continue

                create_edge("HAS_INTERFACE", t2b_id, t2b_iface_id)

                # Create MAC for T2B interface
                t2b_mac_id = create_node("MACAddress", {
                    "address": t2b_mac, "status": "active",
                    "mac_type": "unicast", "vendor_oui": "Cisco" if prefix != "LON" else "Juniper",
                }, key_field="address")
                if t2b_mac_id:
                    create_edge("MAC_ON_INTERFACE", t2b_mac_id, t2b_iface_id)

                # Spine downlink interface to T2B
                spn_iface_name = f"{spn_name}/Ethernet{48 + t2b_num}"
                spn_mac = rand_mac(prefix="44")
                spn_iface_id = create_node("Interface", {
                    "name": spn_iface_name,
                    "interface_type": "physical",
                    "enabled": True,
                    "oper_status": "up",
                    "speed_mbps": 100000,
                    "mac_address": spn_mac,
                    "mtu": 9216,
                    "mode": "routed",
                    "description": f"Downlink to {hostname}",
                }, key_field="name")

                if not spn_iface_id:
                    continue

                create_edge("HAS_INTERFACE", spn_id, spn_iface_id)

                # MAC for spine interface
                spn_mac_id = create_node("MACAddress", {
                    "address": spn_mac, "status": "active",
                    "mac_type": "unicast", "vendor_oui": "Arista" if prefix != "LON" else "Juniper",
                }, key_field="address")
                if spn_mac_id:
                    create_edge("MAC_ON_INTERFACE", spn_mac_id, spn_iface_id)

                # CONNECTED_TO between T2B and Spine
                create_edge("CONNECTED_TO", t2b_iface_id, spn_iface_id,
                            {"cable_type": "fiber_smf", "cable_id": f"CAB-{prefix}-T2B{t2b_num}-SPN{spn_idx+1}"})

                print(f"    {hostname} <-> {spn_name} connected")

    # =========================================================================
    # 2. Create leased line circuits between all DC pairs
    # =========================================================================
    print("\n=== Creating Leased Line Circuits Between DCs ===")

    # Ensure circuit type exists
    ct_id = create_node("CircuitType", {"name": "Leased Line", "slug": "leased-line"})

    # Ensure provider exists
    prov_id = create_node("Provider", {"name": "Lumen Technologies", "slug": "lumen"})
    if not prov_id:
        # Try lookup
        resp = SESSION.get(f"{BASE_URL}/objects/Provider", params={"name": "Lumen Technologies"})
        if resp.status_code == 200:
            items = resp.json().get("data", [])
            if items:
                prov_id = items[0]["id"]
                IDS["Provider:Lumen Technologies"] = prov_id

    dc_pairs = list(itertools.combinations(dcs.keys(), 2))
    wan_link_num = 0

    for dc_a, dc_b in dc_pairs:
        cfg_a = dcs[dc_a]
        cfg_b = dcs[dc_b]

        # Create 2 circuits per DC pair (primary + backup via different T2B routers)
        for ckt_idx in range(2):
            wan_link_num += 1
            cid = f"CKT-LL-{dc_a}-{dc_b}-{ckt_idx + 1:02d}"
            t2b_a = f"{dc_a}-T2B0{ckt_idx + 1}"
            t2b_b = f"{dc_b}-T2B0{ckt_idx + 1}"

            print(f"  Circuit {cid}: {t2b_a} <-> {t2b_b}")

            # Create circuit
            ckt_id = create_node("Circuit", {
                "cid": cid,
                "status": "active",
                "bandwidth_kbps": 100_000_000,  # 100G
                "commit_rate_kbps": 100_000_000,
                "description": f"Leased line {dc_a} to {dc_b} via T2B0{ckt_idx + 1}",
            }, key_field="cid")

            if not ckt_id:
                continue

            # Wire to type and provider
            if ct_id:
                create_edge("CIRCUIT_HAS_TYPE", ckt_id, ct_id)
            if prov_id:
                create_edge("CIRCUIT_FROM_PROVIDER", ckt_id, prov_id)

            # A-side termination
            term_a_id = create_node("CircuitTermination", {
                "term_side": "A",
                "port_speed_kbps": 100_000_000,
                "xconnect_id": f"XC-{dc_a}-{wan_link_num:03d}",
            }, dedup_key=f"CircuitTermination:{cid}:A")

            if term_a_id:
                create_edge("CIRCUIT_HAS_TERMINATION", ckt_id, term_a_id)
                loc_a = lookup_location(cfg_a["site"])
                if loc_a:
                    create_edge("TERMINATION_AT_LOCATION", term_a_id, loc_a)

                # Create WAN interface on T2B A-side
                t2b_a_id = lookup_device(t2b_a)
                if t2b_a_id:
                    wan_iface_name = f"{t2b_a}/WAN{ckt_idx + 1}"
                    wan_mac_a = rand_mac(prefix="0A")
                    wan_iface_a = create_node("Interface", {
                        "name": wan_iface_name,
                        "interface_type": "physical",
                        "enabled": True,
                        "oper_status": "up",
                        "speed_mbps": 100000,
                        "mac_address": wan_mac_a,
                        "mtu": 9216,
                        "mode": "routed",
                        "description": f"WAN to {dc_b} via {cid}",
                    }, key_field="name")

                    if wan_iface_a:
                        create_edge("HAS_INTERFACE", t2b_a_id, wan_iface_a)
                        create_edge("TERMINATION_CONNECTED_TO", term_a_id, wan_iface_a)

                        # MAC on WAN interface
                        mac_a_id = create_node("MACAddress", {
                            "address": wan_mac_a, "status": "active",
                            "mac_type": "unicast", "vendor_oui": "Cisco",
                        }, key_field="address")
                        if mac_a_id:
                            create_edge("MAC_ON_INTERFACE", mac_a_id, wan_iface_a)

            # Z-side termination
            term_z_id = create_node("CircuitTermination", {
                "term_side": "Z",
                "port_speed_kbps": 100_000_000,
                "xconnect_id": f"XC-{dc_b}-{wan_link_num:03d}",
            }, dedup_key=f"CircuitTermination:{cid}:Z")

            if term_z_id:
                create_edge("CIRCUIT_HAS_TERMINATION", ckt_id, term_z_id)
                loc_b = lookup_location(cfg_b["site"])
                if loc_b:
                    create_edge("TERMINATION_AT_LOCATION", term_z_id, loc_b)

                # Create WAN interface on T2B Z-side
                t2b_b_id = lookup_device(t2b_b)
                if t2b_b_id:
                    wan_iface_name = f"{t2b_b}/WAN{ckt_idx + 1}"
                    wan_mac_z = rand_mac(prefix="0A")
                    wan_iface_z = create_node("Interface", {
                        "name": wan_iface_name,
                        "interface_type": "physical",
                        "enabled": True,
                        "oper_status": "up",
                        "speed_mbps": 100000,
                        "mac_address": wan_mac_z,
                        "mtu": 9216,
                        "mode": "routed",
                        "description": f"WAN to {dc_a} via {cid}",
                    }, key_field="name")

                    if wan_iface_z:
                        create_edge("HAS_INTERFACE", t2b_b_id, wan_iface_z)
                        create_edge("TERMINATION_CONNECTED_TO", term_z_id, wan_iface_z)

                        # MAC on WAN interface
                        mac_z_id = create_node("MACAddress", {
                            "address": wan_mac_z, "status": "active",
                            "mac_type": "unicast", "vendor_oui": "Cisco",
                        }, key_field="address")
                        if mac_z_id:
                            create_edge("MAC_ON_INTERFACE", mac_z_id, wan_iface_z)

    print(f"\n=== Summary ===")
    print(f"  T2B routers: 6 (2 per DC)")
    print(f"  DC pairs: {len(dc_pairs)} ({', '.join(f'{a}-{b}' for a,b in dc_pairs)})")
    print(f"  Circuits: {wan_link_num} (2 per pair)")
    print(f"  Full path chain available:")
    print(f"    MAC → Interface → Server → Leaf → Spine → T2B → Circuit → T2B → Spine → Leaf → Server → Interface → MAC")


if __name__ == "__main__":
    main()
