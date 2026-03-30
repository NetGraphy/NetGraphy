"""Schema generation engine — derives platform artifacts from the canonical schema.

Generators:
- MCP tools: create/get/list/update/delete/search per node/edge type
- Agent capabilities: semantic actions (onboard, move, detect) from schema relationships
- Validation rules: required, enum, uniqueness, cardinality from constraints
- Observability rules: health checks, alerts, metrics from health metadata
"""
