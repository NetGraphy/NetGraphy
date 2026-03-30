"""Ingestion collectors — pluggable backends for device data collection."""

from packages.ingestion.collectors.api_collector import APICollector
from packages.ingestion.collectors.base import (
    Collector,
    CollectorCommand,
    CollectorResult,
    DeviceTarget,
)
from packages.ingestion.collectors.cli_collector import CLICollector
from packages.ingestion.collectors.mock_collector import MockCollector

__all__ = [
    "APICollector",
    "CLICollector",
    "Collector",
    "CollectorCommand",
    "CollectorResult",
    "DeviceTarget",
    "MockCollector",
]
