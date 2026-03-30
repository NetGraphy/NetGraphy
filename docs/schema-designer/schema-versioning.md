---
title: "Schema Versioning"
slug: "schema-designer-schema-versioning"
summary: "How NetGraphy computes schema versions, detects changes, generates migration plans, and classifies risk levels."
category: "Schema Designer"
tags: [schema, versioning, migrations, diff, risk-levels]
status: published
---

# Schema Versioning

Every schema state has a deterministic version. The generation engine computes a SHA-256 hash from the sorted set of node type names, their attribute names, edge type names, and their source/target node types. The first 12 characters of that hash serve as the schema version identifier. If nothing in the schema changes, the version stays the same. If any type, attribute, or relationship endpoint changes, the version updates.

## Change Detection

When the schema engine loads a new set of YAML files, it can compare the resulting registry against a previous manifest to produce a diff. The diff reports:

- **Added types** -- New node or edge types that did not exist before.
- **Removed types** -- Types that existed previously but are no longer present.
- **Added/removed attributes** -- Fields added to or removed from existing types.
- **Modified constraints** -- Changes to cardinality, uniqueness, required flags, or enum values.

This diff is available through the generation engine's `diff()` method and is surfaced in the UI's schema explorer so operators can review what changed before applying.

## Migration Planning

For changes that affect the graph database, the schema engine generates a `MigrationPlan` containing:

- A list of `SchemaChange` objects, each with a change type, target, risk level, and description.
- A list of `MigrationOperation` objects with the database operations needed to apply the change, including rollback operations where possible.
- Aggregated warnings about potential data loss or constraint violations.

## Risk Levels

Every schema change is classified into one of three risk levels:

- **safe** -- Additive changes that cannot break existing data. Adding a new optional attribute, adding a new node or edge type, or adding a new enum value. These can be applied automatically.
- **cautious** -- Changes that are unlikely to cause data loss but require validation. Adding a required attribute with a default value, changing cardinality from restrictive to permissive, or adding an index. These should be reviewed before applying.
- **dangerous** -- Changes that may cause data loss or constraint violations. Removing a node type, removing an attribute, narrowing an enum, tightening cardinality, or adding a uniqueness constraint to an attribute with duplicate values. These require explicit approval and may need data migration scripts.

The overall migration plan's risk level is the highest risk level among its individual changes. A plan with nine safe changes and one dangerous change is classified as dangerous.

## Workflow

In practice, schema versioning fits into the GitOps workflow: propose a schema change in a branch, run the diff to review impacts, check the risk level, and merge only after the migration plan has been reviewed. The schema version hash appears in every generated manifest, making it easy to verify that a running system matches the expected schema state.
