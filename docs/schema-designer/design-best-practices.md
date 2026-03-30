---
title: "Schema Design Best Practices"
slug: "schema-designer-design-best-practices"
summary: "Guidelines for designing effective graph schemas: modeling relationships as edges, using enums, indexing strategy, mixins, and keeping node types focused."
category: "Schema Designer"
tags: [schema, best-practices, modeling, design, graph]
status: published
---

# Schema Design Best Practices

A well-designed schema makes the platform faster, the data more reliable, and the graph more queryable. These guidelines reflect the patterns that work best in a graph-native system.

## Use Edges for Relationships, Not String References

Never store a related object's name or ID as a string attribute. If a device is in a location, model that as a `LOCATED_IN` edge, not a `location_name` string field. Edges give you cardinality enforcement, traversal in queries, visibility in the graph explorer, and automatic API endpoints. A string field gives you none of that.

The one exception is `reference` type attributes, which are specifically designed for lightweight cross-references that do not need full edge semantics.

## Use Enums for Controlled Vocabularies

Any field with a known set of valid values should be an `enum` type with `enum_values` declared in the schema. This gives you validation on write, filter dropdowns in the UI, badge colors on detail pages, and type safety in MCP tools. Avoid free-text fields for things like status, role, or type -- the data quality cost is not worth the flexibility.

## Index Frequently Filtered Fields

Set `indexed: true` on any attribute that appears in `api.filterable_fields` or `search.search_fields`. Indexes are cheap to maintain and expensive to lack. At minimum, always index the primary identifier field (hostname, name), any status or type enum, and any field used for programmatic lookups (serial number, management IP, asset tag).

## Use Mixins for Common Fields

If multiple node types share the same set of fields, define those fields in a mixin rather than duplicating them. The two built-in mixins cover the most common cases:

- **lifecycle_mixin** -- `created_at`, `updated_at`, `created_by`, `updated_by` with automatic timestamping.
- **provenance_mixin** -- `source_type`, `source_id`, `last_verified_at`, `confidence_score` for tracking how data entered the system.

Apply both mixins to any node type that represents discovered or managed infrastructure. Create custom mixins for domain-specific field groups that recur across types (e.g., a `geo_mixin` with latitude, longitude, and timezone).

## Keep Node Types Focused

Each node type should represent a single concept. If you find a node type accumulating attributes that belong to different concerns, split it. A device should not store its circuit details -- those belong on a `Circuit` node connected by an edge. A location should not store device counts -- those are derived from traversing edges.

## Model Hierarchy with Edges, Not Attributes

Location hierarchies (region, site, building, floor, room, rack) should be modeled with `PARENT_OF` / `CHILD_OF` edges between Location nodes, not with a `parent_name` attribute. Edge-based hierarchy gives you recursive traversal ("find all devices in this region and everything below it"), tree visualization in the graph explorer, and cardinality enforcement (each location has at most one parent).

The same principle applies to any tree or DAG structure: organizational hierarchy, VLAN groups, route policy chains. If there is a parent-child or contains relationship, it belongs on an edge.

## Set Permissions Explicitly

Every node type should declare `permissions` with appropriate `default_read`, `default_write`, and `default_delete` levels. The defaults (`authenticated` / `editor` / `admin`) work for most infrastructure types, but sensitive types (credentials, tokens, compliance results) should restrict read access as well.

## Configure Health Checks for Critical Types

For node types that represent operational infrastructure, enable the `health` section. Set `freshness_hours` to alert when discovery data goes stale, `alert_on_orphan` to catch nodes that have lost all relationships, and `min_count` to detect when expected infrastructure disappears. These checks feed directly into the platform's observability dashboard.
