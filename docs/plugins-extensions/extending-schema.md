---
title: "Extending the Schema"
slug: "plugins-extensions-extending-schema"
summary: "Add new node types and edge types to NetGraphy by placing YAML schema files in content/schemas/ or a plugin repository."
category: "Plugins and Extensions"
tags: [schema, yaml, node-types, edge-types, plugins]
status: published
---

# Extending the Schema

Every object type and relationship in NetGraphy is defined by a YAML schema file. Extending the platform means adding new YAML files that follow the same structure as core schema definitions. The schema engine discovers them automatically and the generation pipeline produces all downstream capabilities.

## Adding a Node Type

Create a YAML file in `content/schemas/` (for local development) or in your plugin repository's `schemas/` directory. A node type definition includes metadata, attributes, and optional blocks for permissions, MCP tools, agent behavior, health rules, and query configuration.

```yaml
kind: NodeTypeDefinition
metadata:
  name: WirelessAccessPoint
  display_name: Wireless Access Point
  description: A managed wireless access point
  icon: wifi
  color: "#4A90D9"
  category: Network
  tags: [wireless, infrastructure]

attributes:
  hostname:
    type: string
    required: true
    unique: true
    description: Device hostname
  model:
    type: string
    description: Hardware model
  band:
    type: enum
    choices: ["2.4GHz", "5GHz", "6GHz", "dual-band", "tri-band"]
    description: Supported frequency band
  status:
    type: enum
    choices: [active, planned, maintenance, decommissioned]
    default: planned
    description: Operational status

mixins:
  - Timestamped
  - Provenance
```

## Adding an Edge Type

Edge types define the relationships between node types. They specify source and target types, cardinality, and optional edge attributes.

```yaml
kind: EdgeTypeDefinition
metadata:
  name: MANAGED_BY
  display_name: Managed By
  description: Indicates which controller manages this access point

source: WirelessAccessPoint
target: WirelessController
cardinality: many_to_one

attributes:
  adopted_at:
    type: datetime
    description: When the AP was adopted by the controller
```

## Discovery and Loading

Schema files are discovered at startup. The schema engine scans `content/schemas/` and any configured plugin repository paths for files matching `*.yaml` or `*.yml`. Each file is validated against the schema meta-schema (the definition of what a valid `NodeTypeDefinition` or `EdgeTypeDefinition` looks like) before being registered.

If a file fails validation, the engine logs the error and skips it. Valid files are merged into the schema registry, which is the single runtime source of truth for all type definitions.

## Naming Conventions

- Node type names use PascalCase: `WirelessAccessPoint`, `VirtualMachine`, `BGPSession`.
- Edge type names use UPPER_SNAKE_CASE: `MANAGED_BY`, `CONNECTED_TO`, `HAS_INTERFACE`.
- File names match the type name in snake_case: `wireless_access_point.yaml`, `managed_by.yaml`.

## Avoiding Conflicts

Node type and edge type names must be globally unique across core schema and all plugins. If two plugins attempt to define the same type name, the schema engine raises a conflict error at load time. Use a plugin-specific prefix if there is a risk of collision (for example, `Wireless_AccessPoint` or a namespace prefix agreed upon by your team).
