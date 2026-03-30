"""Tests for built-in Jinja2 filters (packages/ingestion/mappers/filters.py)."""

import pytest

from packages.ingestion.mappers.filters import (
    BUILTIN_FILTERS,
    extract_hostname,
    mac_format,
    normalize_interface_name,
    parse_speed,
    to_cidr,
    to_slug,
)


# ---------------------------------------------------------------------------
# normalize_interface_name
# ---------------------------------------------------------------------------

class TestNormalizeInterfaceName:
    @pytest.mark.parametrize(
        "abbrev, expected",
        [
            ("Gi0/0/1", "GigabitEthernet0/0/1"),
            ("GigE0/0/1", "GigabitEthernet0/0/1"),
            ("Gig0/0/1", "GigabitEthernet0/0/1"),
            ("Fa0/1", "FastEthernet0/1"),
            ("Fas0/1", "FastEthernet0/1"),
            ("Eth1/1", "Ethernet1/1"),
            ("Et1/1", "Ethernet1/1"),
            ("Te1/0/1", "TenGigabitEthernet1/0/1"),
            ("Lo0", "Loopback0"),
            ("Loop0", "Loopback0"),
            ("Po10", "Port-channel10"),
            ("Vl100", "Vlan100"),
            ("Tu0", "Tunnel0"),
            ("Se0/0/0", "Serial0/0/0"),
            ("Mgmt0", "Management0"),
            ("Hu0/0/0/0", "HundredGigabitEthernet0/0/0/0"),
            ("Fo1/0/1", "FortyGigabitEthernet1/0/1"),
        ],
    )
    def test_abbreviation_expansion(self, abbrev, expected):
        assert normalize_interface_name(abbrev) == expected

    def test_already_full_name(self):
        assert normalize_interface_name("GigabitEthernet0/0/1") == "GigabitEthernet0/0/1"

    def test_unknown_format_passthrough(self):
        assert normalize_interface_name("SomeWeirdPort99") == "SomeWeirdPort99"

    def test_empty_string(self):
        assert normalize_interface_name("") == ""

    def test_whitespace_stripped(self):
        assert normalize_interface_name("  Gi0/0/1  ") == "GigabitEthernet0/0/1"


# ---------------------------------------------------------------------------
# to_slug
# ---------------------------------------------------------------------------

class TestToSlug:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("Cisco IOS-XE", "cisco_ios_xe"),
            ("My Device (v2)", "my_device_v2"),
            ("  hello world  ", "hello_world"),
            ("simple", "simple"),
            ("UPPER CASE", "upper_case"),
            ("dots.and-dashes", "dots_and_dashes"),
            ("multiple___underscores", "multiple_underscores"),
        ],
    )
    def test_slug_conversion(self, name, expected):
        assert to_slug(name) == expected


# ---------------------------------------------------------------------------
# parse_speed
# ---------------------------------------------------------------------------

class TestParseSpeed:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1000 Mbps", 1000),
            ("10Gbps", 10000),
            ("100G", 100000),
            ("1000", 1000),
            ("10 Gbps", 10000),
            ("1Tbps", 1000000),
            ("25G", 25000),
            ("40Gbps", 40000),
        ],
    )
    def test_parse_speed(self, raw, expected):
        assert parse_speed(raw) == expected

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty speed string"):
            parse_speed("")

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown speed unit"):
            parse_speed("10 Xbps")

    def test_unparseable_raises(self):
        with pytest.raises(ValueError, match="Cannot parse speed"):
            parse_speed("fast")


# ---------------------------------------------------------------------------
# mac_format
# ---------------------------------------------------------------------------

class TestMacFormat:
    def test_to_colon(self):
        assert mac_format("aabb.ccdd.eeff", "colon") == "AA:BB:CC:DD:EE:FF"

    def test_to_cisco(self):
        assert mac_format("AA:BB:CC:DD:EE:FF", "cisco") == "aabb.ccdd.eeff"

    def test_to_dash(self):
        assert mac_format("AABBCCDDEEFF", "dash") == "AA-BB-CC-DD-EE-FF"

    def test_default_is_colon(self):
        assert mac_format("aabb.ccdd.eeff") == "AA:BB:CC:DD:EE:FF"

    def test_from_dash_to_cisco(self):
        assert mac_format("AA-BB-CC-DD-EE-FF", "cisco") == "aabb.ccdd.eeff"

    def test_invalid_mac_raises(self):
        with pytest.raises(ValueError, match="Invalid MAC"):
            mac_format("not-a-mac", "colon")

    def test_unknown_style_raises(self):
        with pytest.raises(ValueError, match="Unknown MAC style"):
            mac_format("AABBCCDDEEFF", "unknown")


# ---------------------------------------------------------------------------
# to_cidr
# ---------------------------------------------------------------------------

class TestToCidr:
    @pytest.mark.parametrize(
        "addr, mask, expected",
        [
            ("10.0.0.1", "255.255.255.0", "10.0.0.1/24"),
            ("192.168.1.1", "255.255.0.0", "192.168.1.1/16"),
            ("172.16.0.1", "255.255.255.252", "172.16.0.1/30"),
            ("10.0.0.0", "255.0.0.0", "10.0.0.0/8"),
            ("0.0.0.0", "0.0.0.0", "0.0.0.0/0"),
        ],
    )
    def test_cidr_conversion(self, addr, mask, expected):
        assert to_cidr(addr, mask) == expected


# ---------------------------------------------------------------------------
# extract_hostname
# ---------------------------------------------------------------------------

class TestExtractHostname:
    @pytest.mark.parametrize(
        "fqdn, expected",
        [
            ("router1.example.com", "router1"),
            ("switch1", "switch1"),
            ("core.dc1.company.net", "core"),
        ],
    )
    def test_extraction(self, fqdn, expected):
        assert extract_hostname(fqdn) == expected

    def test_empty_string(self):
        assert extract_hostname("") == ""

    def test_whitespace_stripped(self):
        assert extract_hostname("  host1.example.com  ") == "host1"


# ---------------------------------------------------------------------------
# BUILTIN_FILTERS registry
# ---------------------------------------------------------------------------

class TestBuiltinFiltersRegistry:
    def test_all_filters_present(self):
        expected_names = {
            "normalize_interface_name",
            "to_slug",
            "parse_speed",
            "mac_format",
            "to_cidr",
            "extract_hostname",
        }
        assert expected_names == set(BUILTIN_FILTERS.keys())

    def test_all_filters_callable(self):
        for name, func in BUILTIN_FILTERS.items():
            assert callable(func), f"Filter '{name}' is not callable"
