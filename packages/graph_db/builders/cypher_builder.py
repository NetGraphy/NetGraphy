"""CypherBuilder — programmatic construction of parameterized Cypher queries.

This is the ONLY place where Cypher strings are assembled. All parameters
are passed via Neo4j's parameter binding ($param syntax), never interpolated.

The builder is the single point where future Neo4j vs Apache AGE dialect
differences would be handled (via a dialect flag or subclass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass
class MatchPattern:
    """A MATCH pattern component."""
    variable: str
    labels: list[str] | None = None
    properties: dict[str, str] | None = None  # param references, e.g., {"id": "$node_id"}

    def to_cypher(self) -> str:
        label_str = ":" + ":".join(self.labels) if self.labels else ""
        if self.properties:
            props = ", ".join(f"{k}: {v}" for k, v in self.properties.items())
            return f"({self.variable}{label_str} {{{props}}})"
        return f"({self.variable}{label_str})"


@dataclass
class RelationshipPattern:
    """A relationship pattern in a MATCH clause."""
    variable: str | None = None
    rel_type: str | None = None
    direction: Direction = Direction.OUTGOING
    min_hops: int | None = None
    max_hops: int | None = None

    def to_cypher(self) -> str:
        var = self.variable or ""
        type_str = f":{self.rel_type}" if self.rel_type else ""
        hop_str = ""
        if self.min_hops is not None or self.max_hops is not None:
            min_h = self.min_hops if self.min_hops is not None else ""
            max_h = self.max_hops if self.max_hops is not None else ""
            hop_str = f"*{min_h}..{max_h}"

        inner = f"[{var}{type_str}{hop_str}]" if (var or type_str or hop_str) else "[]"

        if self.direction == Direction.OUTGOING:
            return f"-{inner}->"
        elif self.direction == Direction.INCOMING:
            return f"<-{inner}-"
        else:
            return f"-{inner}-"


@dataclass
class Condition:
    """A WHERE condition."""
    expression: str  # e.g., "n.status = $status"


@dataclass
class ReturnField:
    """A RETURN clause field."""
    expression: str  # e.g., "n", "n.hostname", "count(n) as total"


@dataclass
class OrderField:
    """An ORDER BY field."""
    expression: str
    descending: bool = False

    def to_cypher(self) -> str:
        return f"{self.expression} DESC" if self.descending else self.expression


class CypherBuilder:
    """Fluent builder for parameterized Cypher queries.

    Example:
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .where([Condition("d.status = $status")])
            .return_clause([ReturnField("d")])
            .order_by([OrderField("d.hostname")])
            .limit(25)
            .build()
        )
        # query = "MATCH (d:Device) WHERE d.status = $status RETURN d ORDER BY d.hostname LIMIT $__limit"
        # params = {"__limit": 25}
    """

    def __init__(self):
        self._match_clauses: list[str] = []
        self._optional_match_clauses: list[str] = []
        self._where_conditions: list[str] = []
        self._with_clauses: list[str] = []
        self._return_fields: list[str] = []
        self._order_fields: list[str] = []
        self._skip_value: int | None = None
        self._limit_value: int | None = None
        self._params: dict[str, Any] = {}
        self._create_clauses: list[str] = []
        self._set_clauses: list[str] = []
        self._delete_clauses: list[str] = []

    def match(self, *patterns: MatchPattern | str) -> CypherBuilder:
        """Add a MATCH clause."""
        parts = []
        for p in patterns:
            parts.append(p.to_cypher() if isinstance(p, MatchPattern) else str(p))
        self._match_clauses.append("MATCH " + "".join(parts))
        return self

    def match_path(
        self,
        start: MatchPattern,
        rel: RelationshipPattern,
        end: MatchPattern,
    ) -> CypherBuilder:
        """Add a MATCH with a relationship pattern."""
        clause = f"MATCH {start.to_cypher()}{rel.to_cypher()}{end.to_cypher()}"
        self._match_clauses.append(clause)
        return self

    def optional_match(self, *patterns: MatchPattern | str) -> CypherBuilder:
        """Add an OPTIONAL MATCH clause."""
        parts = []
        for p in patterns:
            parts.append(p.to_cypher() if isinstance(p, MatchPattern) else str(p))
        self._optional_match_clauses.append("OPTIONAL MATCH " + "".join(parts))
        return self

    def where(self, conditions: list[Condition | str]) -> CypherBuilder:
        """Add WHERE conditions (AND-joined)."""
        for c in conditions:
            expr = c.expression if isinstance(c, Condition) else str(c)
            self._where_conditions.append(expr)
        return self

    def with_clause(self, expressions: list[str]) -> CypherBuilder:
        """Add a WITH clause."""
        self._with_clauses.append("WITH " + ", ".join(expressions))
        return self

    def return_clause(self, fields: list[ReturnField | str]) -> CypherBuilder:
        """Set the RETURN clause."""
        for f in fields:
            expr = f.expression if isinstance(f, ReturnField) else str(f)
            self._return_fields.append(expr)
        return self

    def order_by(self, fields: list[OrderField | str]) -> CypherBuilder:
        """Set ORDER BY."""
        for f in fields:
            if isinstance(f, OrderField):
                self._order_fields.append(f.to_cypher())
            else:
                self._order_fields.append(str(f))
        return self

    def skip(self, n: int) -> CypherBuilder:
        self._skip_value = n
        self._params["__skip"] = n
        return self

    def limit(self, n: int) -> CypherBuilder:
        self._limit_value = n
        self._params["__limit"] = n
        return self

    def set_param(self, key: str, value: Any) -> CypherBuilder:
        """Set a query parameter."""
        self._params[key] = value
        return self

    def build(self) -> tuple[str, dict[str, Any]]:
        """Build the final Cypher query string and parameter dict."""
        parts = []

        parts.extend(self._match_clauses)
        parts.extend(self._optional_match_clauses)

        if self._where_conditions:
            parts.append("WHERE " + " AND ".join(self._where_conditions))

        parts.extend(self._with_clauses)

        if self._create_clauses:
            parts.extend(self._create_clauses)

        if self._set_clauses:
            parts.append("SET " + ", ".join(self._set_clauses))

        if self._delete_clauses:
            parts.extend(self._delete_clauses)

        if self._return_fields:
            parts.append("RETURN " + ", ".join(self._return_fields))

        if self._order_fields:
            parts.append("ORDER BY " + ", ".join(self._order_fields))

        if self._skip_value is not None:
            parts.append("SKIP $__skip")

        if self._limit_value is not None:
            parts.append("LIMIT $__limit")

        query = "\n".join(parts)
        return query, dict(self._params)
