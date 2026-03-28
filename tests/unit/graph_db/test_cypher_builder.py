"""Tests for the CypherBuilder."""

from packages.graph_db.builders.cypher_builder import (
    Condition,
    CypherBuilder,
    Direction,
    MatchPattern,
    OrderField,
    RelationshipPattern,
    ReturnField,
)


class TestCypherBuilder:
    def test_simple_match_return(self):
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .return_clause([ReturnField("d")])
            .build()
        )
        assert "MATCH (d:Device)" in query
        assert "RETURN d" in query

    def test_match_with_properties(self):
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"], {"id": "$id"}))
            .return_clause([ReturnField("d")])
            .set_param("id", "abc-123")
            .build()
        )
        assert "MATCH (d:Device {id: $id})" in query
        assert params["id"] == "abc-123"

    def test_where_conditions(self):
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .where([Condition("d.status = $status"), Condition("d.role = $role")])
            .return_clause([ReturnField("d")])
            .set_param("status", "active")
            .set_param("role", "router")
            .build()
        )
        assert "WHERE d.status = $status AND d.role = $role" in query
        assert params["status"] == "active"
        assert params["role"] == "router"

    def test_pagination(self):
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .return_clause([ReturnField("d")])
            .order_by([OrderField("d.hostname")])
            .skip(20)
            .limit(10)
            .build()
        )
        assert "ORDER BY d.hostname" in query
        assert "SKIP $__skip" in query
        assert "LIMIT $__limit" in query
        assert params["__skip"] == 20
        assert params["__limit"] == 10

    def test_descending_order(self):
        query, _ = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .return_clause([ReturnField("d")])
            .order_by([OrderField("d.created_at", descending=True)])
            .build()
        )
        assert "ORDER BY d.created_at DESC" in query

    def test_relationship_pattern(self):
        builder = CypherBuilder()
        builder.match_path(
            MatchPattern("d", ["Device"]),
            RelationshipPattern("r", "HAS_INTERFACE", Direction.OUTGOING),
            MatchPattern("i", ["Interface"]),
        )
        builder.return_clause([ReturnField("d"), ReturnField("i")])
        query, _ = builder.build()
        assert "MATCH (d:Device)-[r:HAS_INTERFACE]->(i:Interface)" in query

    def test_variable_length_path(self):
        builder = CypherBuilder()
        builder.match_path(
            MatchPattern("a", ["Device"]),
            RelationshipPattern("r", "CONNECTED_TO", Direction.BOTH, min_hops=1, max_hops=3),
            MatchPattern("b", ["Device"]),
        )
        builder.return_clause([ReturnField("a"), ReturnField("b")])
        query, _ = builder.build()
        assert "*1..3" in query

    def test_optional_match(self):
        query, _ = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .optional_match(MatchPattern("i", ["Interface"]))
            .return_clause([ReturnField("d"), ReturnField("i")])
            .build()
        )
        assert "OPTIONAL MATCH (i:Interface)" in query

    def test_parameterization_no_interpolation(self):
        """Verify that values are never interpolated into the query string."""
        query, params = (
            CypherBuilder()
            .match(MatchPattern("d", ["Device"]))
            .where([Condition("d.hostname = $hostname")])
            .return_clause([ReturnField("d")])
            .set_param("hostname", "'; DROP DATABASE neo4j; --")
            .build()
        )
        # The malicious string should be in params, not in the query
        assert "DROP DATABASE" not in query
        assert params["hostname"] == "'; DROP DATABASE neo4j; --"
