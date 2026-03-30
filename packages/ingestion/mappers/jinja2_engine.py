"""Jinja2 Mapping Engine — renders mapping definitions through Jinja2.

This module provides a higher-level mapping engine that wraps the core
``apply_mapping`` logic with full Jinja2 template resolution, sandboxed
execution, and custom filter support.

Usage::

    engine = Jinja2MappingEngine()
    engine.register_filters(custom_filters)

    result = engine.render_mapping(mapping_def, parsed_records, context)
"""

from __future__ import annotations

from typing import Any, Callable

import jinja2
import structlog
from jinja2.sandbox import SandboxedEnvironment

from packages.ingestion.mappers.filters import BUILTIN_FILTERS
from packages.ingestion.mappers.mapping_engine import GraphMutation, MappingResult

logger = structlog.get_logger()


class Jinja2MappingEngine:
    """Renders mapping definitions through Jinja2 with custom filters.

    The engine uses a ``SandboxedEnvironment`` with ``StrictUndefined`` so
    that references to missing variables raise immediately rather than
    silently producing empty strings.

    All built-in network-engineering filters from ``filters.py`` are
    registered on construction.  Additional filters (built-in or
    user-defined) can be added via :meth:`register_filter` /
    :meth:`register_filters`.
    """

    def __init__(self) -> None:
        self._env = SandboxedEnvironment(undefined=jinja2.StrictUndefined)
        # Register all built-in filters
        self._env.filters.update(BUILTIN_FILTERS)

    # ------------------------------------------------------------------
    # Filter management
    # ------------------------------------------------------------------

    def register_filter(self, name: str, func: Callable) -> None:
        """Register a single Jinja2 filter by name."""
        self._env.filters[name] = func

    def register_filters(self, filters: dict[str, Callable]) -> None:
        """Register multiple Jinja2 filters at once."""
        self._env.filters.update(filters)

    # ------------------------------------------------------------------
    # Template resolution
    # ------------------------------------------------------------------

    def resolve_template(self, template_str: str, context: dict[str, Any]) -> str:
        """Render a single Jinja2 template string against a context dict.

        Args:
            template_str: A Jinja2 template string, e.g.
                ``"{{ parsed.HOSTNAME | to_slug }}"``.
            context: Variables available inside the template.

        Returns:
            The rendered string.
        """
        tmpl = self._env.from_string(template_str)
        return tmpl.render(**context)

    # ------------------------------------------------------------------
    # Full mapping rendering
    # ------------------------------------------------------------------

    def render_mapping(
        self,
        mapping_def: dict[str, Any],
        parsed_records: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> MappingResult:
        """Apply a mapping definition to parsed records, producing GraphMutations.

        This mirrors the logic in ``mapping_engine.apply_mapping`` but uses
        the Jinja2 sandboxed environment for all template resolution, giving
        access to filters, conditionals, and other Jinja2 features.

        Args:
            mapping_def: A loaded YAML mapping definition with a ``mappings``
                key containing a list of node/edge mapping entries.
            parsed_records: List of parsed records (e.g. from TextFSM).
            context: Additional context variables (device hostname, job run
                ID, etc.) available as top-level template variables.

        Returns:
            A ``MappingResult`` with the generated mutations and any errors.
        """
        mutations: list[GraphMutation] = []
        errors: list[str] = []
        context = context or {}

        for record in parsed_records:
            # Build the full template context: top-level context vars plus
            # ``parsed`` namespace containing the record fields.
            template_context: dict[str, Any] = {
                **context,
                "parsed": record,
            }

            for mapping in mapping_def.get("mappings", []):
                try:
                    mutation = self._process_mapping_entry(mapping, template_context)
                    if mutation is not None:
                        mutations.append(mutation)
                except Exception as exc:
                    errors.append(f"Mapping error for record {record}: {exc}")

        return MappingResult(
            mutations=mutations,
            errors=errors,
            record_count=len(parsed_records),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, template: str, ctx: dict[str, Any]) -> str:
        """Shorthand for resolving a template string."""
        return self.resolve_template(template, ctx)

    def _process_mapping_entry(
        self,
        mapping: dict[str, Any],
        ctx: dict[str, Any],
    ) -> GraphMutation | None:
        """Process a single mapping entry against a template context."""

        if "target_node_type" in mapping:
            # --- Node upsert ---
            match_on: dict[str, Any] = {}
            for field_name in mapping.get("match_on", []):
                # Use the explicit attribute template if present; otherwise
                # fall back to ``{{ parsed.<field_name> }}``.
                template = mapping.get("attributes", {}).get(
                    field_name, f"{{{{ parsed.{field_name} }}}}"
                )
                match_on[field_name] = self._resolve(template, ctx)

            attributes: dict[str, Any] = {}
            for attr_name, template in mapping.get("attributes", {}).items():
                attributes[attr_name] = self._resolve(template, ctx)

            return GraphMutation(
                operation="upsert_node",
                node_type=mapping["target_node_type"],
                match_on=match_on,
                attributes=attributes,
            )

        elif "target_edge_type" in mapping:
            # --- Edge upsert ---
            source = mapping.get("source", {})
            target = mapping.get("target", {})

            source_match: dict[str, Any] = {}
            for field_name, template in source.get("match_on", {}).items():
                source_match[field_name] = self._resolve(template, ctx)

            target_match: dict[str, Any] = {}
            for field_name, template in target.get("match_on", {}).items():
                target_match[field_name] = self._resolve(template, ctx)

            attributes = {}
            for attr_name, template in mapping.get("attributes", {}).items():
                attributes[attr_name] = self._resolve(template, ctx)

            return GraphMutation(
                operation="upsert_edge",
                edge_type=mapping["target_edge_type"],
                source_match=source_match,
                target_match=target_match,
                attributes=attributes,
            )

        return None
