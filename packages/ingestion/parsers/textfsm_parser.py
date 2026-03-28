"""TextFSM parser execution engine.

Wraps the textfsm library to parse raw command output using registered
templates and return structured records.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import textfsm


def parse_output(template_path: str | Path, raw_output: str) -> list[dict[str, Any]]:
    """Parse raw command output using a TextFSM template.

    Args:
        template_path: Path to the TextFSM template file.
        raw_output: Raw text output from the network device command.

    Returns:
        List of parsed records as dicts with header names as keys.
    """
    with open(template_path) as f:
        template = textfsm.TextFSM(f)

    parsed = template.ParseText(raw_output)
    headers = template.header

    return [dict(zip(headers, record)) for record in parsed]


def parse_output_from_string(template_content: str, raw_output: str) -> list[dict[str, Any]]:
    """Parse raw output using a TextFSM template provided as a string.

    Useful for testing parsers in the UI without writing to disk.
    """
    template = textfsm.TextFSM(io.StringIO(template_content))
    parsed = template.ParseText(raw_output)
    headers = template.header

    return [dict(zip(headers, record)) for record in parsed]


def validate_template(template_content: str) -> list[str]:
    """Validate a TextFSM template for syntax errors.

    Returns list of error messages (empty if valid).
    """
    errors = []
    try:
        textfsm.TextFSM(io.StringIO(template_content))
    except textfsm.TextFSMTemplateError as e:
        errors.append(f"Template syntax error: {e}")
    except Exception as e:
        errors.append(f"Template error: {e}")
    return errors
