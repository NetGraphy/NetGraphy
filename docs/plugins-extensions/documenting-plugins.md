---
title: "Documenting Plugins"
slug: "documenting-plugins"
summary: "Conventions for writing documentation in plugin repositories"
category: "Plugins and Extensions"
tags: [plugins, documentation, conventions]
status: published
---

# Documenting Plugins

Plugin repositories can contribute documentation that integrates into the NetGraphy docs platform. When a plugin repo is registered, its `/docs` directory is discovered and rendered alongside core documentation.

## Plugin Docs Structure

Place documentation in your plugin repository:

```
my-plugin/
  schemas/           # YAML schema definitions
  docs/
    index.md         # Plugin overview (required)
    models/          # Documentation for contributed node/edge types
    capabilities/    # What the plugin enables
    examples/        # Usage examples and walkthroughs
    troubleshooting/ # Common issues and solutions
    assets/          # Screenshots and diagrams
```

## Frontmatter Convention

Every plugin doc page must declare plugin ownership:

```yaml
---
title: "My Plugin Overview"
slug: "my-plugin-overview"
summary: "What this plugin adds to NetGraphy"
category: "Plugins"
plugin: "my-plugin"
related_schema_items: [CustomType, CUSTOM_EDGE]
status: published
---
```

The `plugin` field links the page to the plugin's namespace in navigation and search.

## Linking to Schema Items

When your plugin contributes node or edge types, use `related_schema_items` to create bidirectional links:

- The plugin doc page links to the schema item's reference page
- The schema item's generated reference page links back to the plugin doc

This ensures users can navigate between "what this type is" and "which plugin provides it."

## Screenshots

Store plugin screenshots in `docs/assets/` within your repo. Use relative paths in markdown:

```markdown
![Custom dashboard](assets/custom-dashboard.png)
```

These are resolved at render time based on the plugin's registered source path.

## Integration

Plugin docs appear in the main documentation navigation under a "Plugins" section. Each registered plugin gets its own subsection with its contributed pages, maintaining the feel of integrated documentation while keeping source control separate.
