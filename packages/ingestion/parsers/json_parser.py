"""JSON parser — extract structured records from API responses.

Complements the TextFSM parser for CLI output.  API collectors return
JSON data; this module normalises it into the same
``list[dict[str, Any]]`` record format that the mapping engine expects.
"""

from __future__ import annotations

from typing import Any


def parse_json_output(
    data: dict[str, Any] | list[Any],
    field_mappings: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Extract records from a JSON API response.

    Args:
        data: Raw JSON data -- either a list of records or a single
            dict treated as one record.
        field_mappings: Optional rename map ``{source_key: target_key}``
            applied to every record so that downstream mappings can
            use consistent field names regardless of the API's schema.

    Returns:
        List of dicts ready for the mapping engine.
    """
    # Normalise to a list of dicts.
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = [item if isinstance(item, dict) else {"value": item} for item in data]
    else:
        return []

    if not field_mappings:
        return records

    # Rename keys according to field_mappings.
    remapped: list[dict[str, Any]] = []
    for record in records:
        new_record: dict[str, Any] = {}
        for key, value in record.items():
            mapped_key = field_mappings.get(key, key)
            new_record[mapped_key] = value
        remapped.append(new_record)

    return remapped
