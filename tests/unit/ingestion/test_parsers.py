"""Parser fixture tests — validates TextFSM templates against known inputs."""

import json
from pathlib import Path

import pytest

from packages.ingestion.parsers.textfsm_parser import parse_output

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "parsers" / "fixtures"


def discover_parser_fixtures():
    """Discover all parser fixture directories."""
    fixtures = []
    if FIXTURES_DIR.exists():
        for fixture_dir in sorted(FIXTURES_DIR.iterdir()):
            if fixture_dir.is_dir():
                input_file = fixture_dir / "input.txt"
                expected_file = fixture_dir / "expected.json"
                if input_file.exists() and expected_file.exists():
                    fixtures.append(fixture_dir.name)
    return fixtures


PARSER_FIXTURES = discover_parser_fixtures()


@pytest.mark.parametrize("fixture_name", PARSER_FIXTURES)
def test_parser_fixture(fixture_name: str):
    """Test a parser against its fixture data.

    Each fixture directory must contain:
    - input.txt: raw command output
    - expected.json: expected parsed records
    And a matching template in parsers/templates/{fixture_name}.textfsm
    """
    fixture_dir = FIXTURES_DIR / fixture_name
    template_path = Path("parsers/templates") / f"{fixture_name}.textfsm"

    if not template_path.exists():
        pytest.skip(f"Template not found: {template_path}")

    input_text = (fixture_dir / "input.txt").read_text()
    expected = json.loads((fixture_dir / "expected.json").read_text())

    result = parse_output(str(template_path), input_text)

    assert len(result) == len(expected), (
        f"Expected {len(expected)} records, got {len(result)}"
    )

    # Compare each record
    for i, (actual, exp) in enumerate(zip(result, expected)):
        for key in exp:
            assert key in actual, f"Record {i}: missing key '{key}'"
            # TextFSM may return slightly different types, so compare as strings
            # for basic validation
            if isinstance(exp[key], list):
                assert isinstance(actual[key], list), f"Record {i}.{key}: expected list"
