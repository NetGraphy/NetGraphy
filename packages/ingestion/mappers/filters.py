"""Built-in Jinja2 filters for network engineering data transformations.

These filters are automatically registered with the Jinja2MappingEngine
and can be used in any mapping template expression.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Callable

# Canonical interface name expansions, ordered longest-prefix-first per family
# to avoid false matches (e.g., "Lo" before "Lo" is fine, but "Gi" must not
# match before "GigabitEthernet" when we're *expanding* abbreviations).
_INTERFACE_EXPANSIONS: list[tuple[str, str]] = [
    # Ethernet family
    ("TenGigabitEthernet", "TenGigabitEthernet"),
    ("TenGigE", "TenGigabitEthernet"),
    ("TenGig", "TenGigabitEthernet"),
    ("Te", "TenGigabitEthernet"),
    ("GigabitEthernet", "GigabitEthernet"),
    ("GigE", "GigabitEthernet"),
    ("Gig", "GigabitEthernet"),
    ("Gi", "GigabitEthernet"),
    ("FastEthernet", "FastEthernet"),
    ("Fas", "FastEthernet"),
    ("Fa", "FastEthernet"),
    ("Ethernet", "Ethernet"),
    ("Eth", "Ethernet"),
    ("Et", "Ethernet"),
    # Port-channel / bundle
    ("Port-channel", "Port-channel"),
    ("Port-Channel", "Port-Channel"),
    ("Po", "Port-channel"),
    # Loopback
    ("Loopback", "Loopback"),
    ("Loop", "Loopback"),
    ("Lo", "Loopback"),
    # VLAN
    ("Vlan", "Vlan"),
    ("Vl", "Vlan"),
    # Management
    ("Management", "Management"),
    ("Mgmt", "Management"),
    ("Ma", "Management"),
    # Tunnel
    ("Tunnel", "Tunnel"),
    ("Tu", "Tunnel"),
    # Serial
    ("Serial", "Serial"),
    ("Ser", "Serial"),
    ("Se", "Serial"),
    # Hundred-Gig
    ("HundredGigE", "HundredGigabitEthernet"),
    ("HundredGigabitEthernet", "HundredGigabitEthernet"),
    ("Hu", "HundredGigabitEthernet"),
    # Twenty-Five-Gig
    ("TwentyFiveGigE", "TwentyFiveGigabitEthernet"),
    ("TwentyFiveGigabitEthernet", "TwentyFiveGigabitEthernet"),
    # Forty-Gig
    ("FortyGigabitEthernet", "FortyGigabitEthernet"),
    ("FortyGigE", "FortyGigabitEthernet"),
    ("Fo", "FortyGigabitEthernet"),
    # NVE (VXLAN)
    ("nve", "nve"),
    ("Nve", "Nve"),
]

# Pre-compile a regex for each abbreviation so lookup is fast.
# We match the abbreviation at the start, followed by a digit (the slot/port part).
_INTERFACE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"^{re.escape(abbrev)}(\d.*)$", re.IGNORECASE), expansion)
    for abbrev, expansion in _INTERFACE_EXPANSIONS
]


def normalize_interface_name(name: str) -> str:
    """Expand abbreviated interface names to their canonical long form.

    Examples:
        Gi0/0/1       -> GigabitEthernet0/0/1
        Eth1/1        -> Ethernet1/1
        Fa0/1         -> FastEthernet0/1
        Lo0           -> Loopback0
        Te1/0/1       -> TenGigabitEthernet1/0/1
        Po10          -> Port-channel10
        Vl100         -> Vlan100
    """
    name = name.strip()
    if not name:
        return name

    for pattern, expansion in _INTERFACE_PATTERNS:
        m = pattern.match(name)
        if m:
            return f"{expansion}{m.group(1)}"

    # No match — return as-is (already full name or unknown format)
    return name


def to_slug(name: str) -> str:
    """Convert a human-readable name to a URL-safe slug.

    Examples:
        'Cisco IOS-XE'   -> 'cisco_ios_xe'
        'My Device (v2)' -> 'my_device_v2'
        '  hello world  ' -> 'hello_world'
    """
    slug = name.strip().lower()
    # Replace any non-alphanumeric character (except underscore) with underscore
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    # Collapse multiple underscores
    slug = re.sub(r"_+", "_", slug)
    # Strip leading/trailing underscores
    slug = slug.strip("_")
    return slug


# Speed multipliers — keys are lowercase unit suffixes.
_SPEED_MULTIPLIERS: dict[str, int] = {
    "kbps": 1,           # keep as kbps? No — normalise to Mbps integer
    "mbps": 1,
    "gbps": 1_000,
    "tbps": 1_000_000,
    "k": 1,              # bare K/M/G assumed bps-class shorthand
    "m": 1,
    "g": 1_000,
    "t": 1_000_000,
}


def parse_speed(raw: str) -> int:
    """Parse a speed string into an integer value in Mbps.

    Examples:
        '1000 Mbps'  -> 1000
        '10Gbps'     -> 10000
        '100G'       -> 100000
        '1000'       -> 1000   (bare number assumed Mbps)
        '10 Gbps'    -> 10000
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty speed string")

    # Try to split into numeric part + unit
    m = re.match(r"^([\d.]+)\s*([a-zA-Z]*)$", raw)
    if not m:
        raise ValueError(f"Cannot parse speed: {raw!r}")

    numeric_str, unit = m.group(1), m.group(2).lower()
    numeric = float(numeric_str)

    if not unit or unit == "mbps" or unit == "m":
        return int(numeric)

    multiplier = _SPEED_MULTIPLIERS.get(unit)
    if multiplier is None:
        raise ValueError(f"Unknown speed unit: {unit!r} in {raw!r}")

    return int(numeric * multiplier)


# Regex to strip all non-hex characters from a MAC address string
_MAC_HEX_RE = re.compile(r"[^0-9a-fA-F]")


def mac_format(mac: str, style: str = "colon") -> str:
    """Convert a MAC address to a specified format.

    Args:
        mac: Any common MAC format (colon, dash, dot/Cisco, bare hex).
        style: Target format — 'colon', 'cisco', or 'dash'.

    Examples:
        mac_format('aabb.ccdd.eeff', 'colon') -> 'AA:BB:CC:DD:EE:FF'
        mac_format('AA:BB:CC:DD:EE:FF', 'cisco') -> 'aabb.ccdd.eeff'
        mac_format('AABBCCDDEEFF', 'dash') -> 'AA-BB-CC-DD-EE-FF'
    """
    # Normalise to 12 hex chars
    cleaned = _MAC_HEX_RE.sub("", mac)
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r} (got {len(cleaned)} hex chars)")

    if style == "colon":
        upper = cleaned.upper()
        return ":".join(upper[i : i + 2] for i in range(0, 12, 2))
    elif style == "cisco":
        lower = cleaned.lower()
        return ".".join(lower[i : i + 4] for i in range(0, 12, 4))
    elif style == "dash":
        upper = cleaned.upper()
        return "-".join(upper[i : i + 2] for i in range(0, 12, 2))
    else:
        raise ValueError(f"Unknown MAC style: {style!r} (use 'colon', 'cisco', or 'dash')")


def to_cidr(addr: str, mask: str) -> str:
    """Combine an IP address and a dotted-decimal subnet mask into CIDR notation.

    Args:
        addr: IPv4 address string, e.g. '10.0.0.1'.
        mask: Dotted-decimal subnet mask, e.g. '255.255.255.0'.

    Returns:
        CIDR string, e.g. '10.0.0.1/24'.

    Examples:
        to_cidr('10.0.0.1', '255.255.255.0')   -> '10.0.0.1/24'
        to_cidr('192.168.1.1', '255.255.0.0')   -> '192.168.1.1/16'
        to_cidr('172.16.0.1', '255.255.255.252') -> '172.16.0.1/30'
    """
    network = ipaddress.IPv4Network(f"{addr}/{mask}", strict=False)
    return f"{addr}/{network.prefixlen}"


def extract_hostname(fqdn: str) -> str:
    """Extract the hostname (first label) from an FQDN.

    Examples:
        'router1.example.com'    -> 'router1'
        'switch1'                -> 'switch1'
        'core.dc1.company.net'   -> 'core'
    """
    fqdn = fqdn.strip()
    if not fqdn:
        return fqdn
    return fqdn.split(".")[0]


# ---------------------------------------------------------------------------
# Registry of all built-in filters
# ---------------------------------------------------------------------------

BUILTIN_FILTERS: dict[str, Callable] = {
    "normalize_interface_name": normalize_interface_name,
    "to_slug": to_slug,
    "parse_speed": parse_speed,
    "mac_format": mac_format,
    "to_cidr": to_cidr,
    "extract_hostname": extract_hostname,
}
