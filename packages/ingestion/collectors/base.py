"""Collector base types — data classes and protocol for device collection.

Defines the shared vocabulary for all collectors (CLI, API, mock).
The ``Collector`` protocol allows the pipeline to work with any
collection backend without coupling to a specific transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class DeviceTarget:
    """A device to collect data from.

    Carries enough context for both SSH/CLI and REST API collection
    so the pipeline can select the right collector and build connection
    parameters without additional lookups.
    """

    hostname: str
    management_ip: str | None = None
    platform_slug: str | None = None
    netmiko_device_type: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)  # username, password, enable_secret
    api_base_url: str | None = None  # for API-based collection


@dataclass
class CollectorCommand:
    """A command (or API call) to execute against a device.

    Attributes:
        command: CLI command string (e.g. ``show interfaces``) or a
            short label for API calls.
        collector_type: ``"cli"`` for SSH, ``"api"`` for REST.
        parser_name: Name of the parser template to apply to the output.
        mapping_name: Name of the mapping definition to apply.
        method: HTTP method for API collection.
        url_template: Jinja2 template for the API URL path, rendered
            against the ``DeviceTarget`` fields.
        response_path: JMESPath expression to extract records from the
            API JSON response.
        headers: Extra HTTP headers for API collection.
        auth_type: ``"basic"``, ``"bearer"``, or ``"api_key"``.
    """

    command: str
    collector_type: str = "cli"  # cli | api
    parser_name: str | None = None
    mapping_name: str | None = None
    # API-specific fields
    method: str = "GET"
    url_template: str | None = None
    response_path: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    auth_type: str | None = None  # basic, bearer, api_key


@dataclass
class CollectorResult:
    """Result of a single collection attempt.

    ``raw_output`` is a ``str`` for CLI collectors and a ``dict`` (or
    ``list``) for API collectors.  The pipeline inspects
    ``CollectorCommand.collector_type`` to choose the right parser.
    """

    raw_output: str | dict[str, Any] | list[Any]
    success: bool = True
    error: str | None = None
    duration_ms: int = 0


class Collector(Protocol):
    """Protocol that all collectors must satisfy."""

    async def collect(
        self,
        target: DeviceTarget,
        command: CollectorCommand,
    ) -> CollectorResult: ...
