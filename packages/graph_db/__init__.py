"""Graph DB — Neo4j abstraction layer with repository pattern.

This package provides a clean abstraction over Neo4j so that application
code never writes raw Cypher. The driver adapter layer is designed to
support Apache AGE in the future by isolating Cypher dialect differences.
"""
