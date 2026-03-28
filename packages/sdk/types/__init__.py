"""Shared type definitions used across packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Pagination:
    page: int = 1
    page_size: int = 25


@dataclass
class Page:
    items: list[Any]
    total_count: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return (self.total_count + self.page_size - 1) // self.page_size

    def to_dict(self) -> dict:
        return {
            "data": self.items,
            "meta": {
                "total_count": self.total_count,
                "page": self.page,
                "page_size": self.page_size,
                "total_pages": self.total_pages,
            },
        }


@dataclass
class AuditEvent:
    """Audit event record."""
    id: str
    timestamp: datetime
    actor_id: str
    actor_type: str  # "user", "system", "job", "sync"
    action: str  # "create", "update", "delete", "execute", "sync", "login"
    resource_type: str
    resource_id: str
    changes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    correlation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
