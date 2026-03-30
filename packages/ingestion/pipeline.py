"""Ingestion pipeline orchestrator.

Drives the full collect -> parse -> map -> mutate flow for a batch of
devices and commands.  Errors are isolated per-device and per-command so
that one failure does not abort the entire run.

Provenance metadata is stamped on every mutated node:
- ``_ingestion_run_id``
- ``_ingestion_source``
- ``_ingestion_timestamp``
- ``_ingestion_parser``
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
import yaml

from packages.events.bus import Event, EventBus
from packages.graph_db.driver import Neo4jDriver
from packages.ingestion.collectors.base import (
    Collector,
    CollectorCommand,
    CollectorResult,
    DeviceTarget,
)
from packages.ingestion.mappers.mapping_engine import (
    GraphMutation,
    MappingResult,
    apply_mapping,
)
from packages.ingestion.parsers.json_parser import parse_json_output
from packages.ingestion.parsers.textfsm_parser import parse_output_from_string
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


# ------------------------------------------------------------------
# Result dataclass
# ------------------------------------------------------------------


@dataclass
class IngestionResult:
    """Accumulator for pipeline execution statistics and errors."""

    devices_processed: int = 0
    commands_executed: int = 0
    records_parsed: int = 0
    mutations_generated: int = 0
    mutations_applied: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run_mutations: list[dict[str, Any]] | None = None


# ------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------


class IngestionPipeline:
    """Orchestrate ingestion: collect, parse, map, mutate.

    Parameters
    ----------
    driver:
        Neo4j async driver (used for mutation execution and loading
        parser/mapping definitions stored as graph nodes).
    registry:
        Schema registry for validation of generated mutations.
    event_bus:
        EventBus for emitting ``ingestion.completed`` events.
    collector:
        A ``Collector`` implementation (CLI, API, or mock).
    """

    def __init__(
        self,
        driver: Neo4jDriver,
        registry: SchemaRegistry,
        event_bus: EventBus,
        collector: Collector,
    ) -> None:
        self._driver = driver
        self._registry = registry
        self._event_bus = event_bus
        self._collector = collector

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        run_id: str | None = None,
        targets: list[DeviceTarget] | None = None,
        commands: list[CollectorCommand] | None = None,
        dry_run: bool = False,
    ) -> IngestionResult:
        """Execute the full pipeline for *targets* x *commands*.

        For each target/command pair:
          1. Collect raw output via the configured collector.
          2. Parse via TextFSM (CLI) or JSON parser (API).
          3. Load mapping definition from the graph.
          4. Render through the mapping engine.
          5. If not *dry_run*: execute mutations via ``bulk_upsert``.
          6. Stamp provenance on mutated nodes.

        Returns an ``IngestionResult`` summarising the run.
        """
        run_id = run_id or str(uuid.uuid4())
        targets = targets or []
        commands = commands or []
        result = IngestionResult()

        if dry_run:
            result.dry_run_mutations = []

        for target in targets:
            result.devices_processed += 1
            for command in commands:
                await self._execute_one(
                    run_id=run_id,
                    target=target,
                    command=command,
                    result=result,
                    dry_run=dry_run,
                )

        # Emit completion event.
        await self._emit_completion(run_id, result)

        logger.info(
            "ingestion.pipeline.completed",
            run_id=run_id,
            devices=result.devices_processed,
            commands=result.commands_executed,
            records=result.records_parsed,
            mutations_generated=result.mutations_generated,
            mutations_applied=result.mutations_applied,
            errors=len(result.errors),
            dry_run=dry_run,
        )
        return result

    # ------------------------------------------------------------------
    # Per-target / per-command execution
    # ------------------------------------------------------------------

    async def _execute_one(
        self,
        run_id: str,
        target: DeviceTarget,
        command: CollectorCommand,
        result: IngestionResult,
        dry_run: bool,
    ) -> None:
        """Run the pipeline for a single target + command pair."""
        log = logger.bind(
            run_id=run_id,
            hostname=target.hostname,
            command=command.command,
        )

        # -- 1. Collect ---------------------------------------------------
        collect_result: CollectorResult = await self._collector.collect(
            target, command,
        )
        result.commands_executed += 1

        if not collect_result.success:
            msg = (
                f"Collection failed for {target.hostname} "
                f"command='{command.command}': {collect_result.error}"
            )
            result.errors.append(msg)
            log.warning("ingestion.collect_failed", error=collect_result.error)
            return

        # -- 2. Parse -----------------------------------------------------
        try:
            parsed_records = await self._parse(command, collect_result)
        except Exception as exc:
            msg = (
                f"Parse failed for {target.hostname} "
                f"command='{command.command}': {exc}"
            )
            result.errors.append(msg)
            log.warning("ingestion.parse_failed", error=str(exc))
            return

        result.records_parsed += len(parsed_records)
        if not parsed_records:
            log.info("ingestion.no_records_parsed")
            return

        # -- 3. Load mapping definition -----------------------------------
        if not command.mapping_name:
            log.info("ingestion.no_mapping_name")
            return

        try:
            mapping_def = await self._load_mapping_def(command.mapping_name)
        except Exception as exc:
            msg = (
                f"Mapping load failed for {target.hostname} "
                f"mapping='{command.mapping_name}': {exc}"
            )
            result.errors.append(msg)
            log.warning("ingestion.mapping_load_failed", error=str(exc))
            return

        # -- 4. Apply mapping ---------------------------------------------
        context = {
            "hostname": target.hostname,
            "management_ip": target.management_ip or "",
            "platform_slug": target.platform_slug or "",
            "run_id": run_id,
        }

        mapping_result: MappingResult = apply_mapping(
            mapping_def, parsed_records, context=context,
        )

        result.mutations_generated += len(mapping_result.mutations)
        result.errors.extend(mapping_result.errors)

        if not mapping_result.mutations:
            log.info("ingestion.no_mutations_generated")
            return

        # -- 5. Execute or collect mutations ------------------------------
        if dry_run:
            for mut in mapping_result.mutations:
                result.dry_run_mutations.append(self._mutation_to_dict(mut))  # type: ignore[union-attr]
        else:
            try:
                applied = await self._execute_mutations(
                    mapping_result.mutations, run_id, target.hostname,
                )
                result.mutations_applied += applied
            except Exception as exc:
                msg = (
                    f"Mutation execution failed for {target.hostname}: {exc}"
                )
                result.errors.append(msg)
                log.warning("ingestion.mutation_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    async def _parse(
        self,
        command: CollectorCommand,
        collect_result: CollectorResult,
    ) -> list[dict[str, Any]]:
        """Route to the correct parser based on collector_type."""
        if command.collector_type == "api":
            data = collect_result.raw_output
            if not isinstance(data, (dict, list)):
                raise ValueError(
                    f"API collector returned non-JSON output: {type(data).__name__}"
                )
            return parse_json_output(data)

        # CLI: requires a TextFSM template.
        if not command.parser_name:
            raise ValueError(
                "CLI command requires a parser_name for TextFSM parsing"
            )

        template_content = await self._load_parser_template(command.parser_name)
        raw_text = collect_result.raw_output
        if not isinstance(raw_text, str):
            raise ValueError(
                f"CLI collector returned non-string output: {type(raw_text).__name__}"
            )

        return parse_output_from_string(template_content, raw_text)

    async def _load_parser_template(self, parser_name: str) -> str:
        """Load a TextFSM template from a ``_Parser`` node in Neo4j.

        The ``_Parser`` node is matched by its ``name`` property and the
        template content is stored in the ``template_content`` field.
        """
        query = (
            "MATCH (p:_Parser {name: $name}) "
            "RETURN p.template_content AS template_content"
        )
        result = await self._driver.execute_read(query, {"name": parser_name})

        if not result.rows:
            raise ValueError(f"Parser template not found: {parser_name}")

        content = result.rows[0].get("template_content")
        if not content:
            raise ValueError(
                f"Parser '{parser_name}' has no template_content"
            )
        return content

    # ------------------------------------------------------------------
    # Mapping definition loading
    # ------------------------------------------------------------------

    async def _load_mapping_def(self, mapping_name: str) -> dict[str, Any]:
        """Load a mapping definition from a ``_MappingDef`` node in Neo4j.

        The definition body is stored as a YAML string in the
        ``definition_yaml`` property.
        """
        query = (
            "MATCH (m:_MappingDef {name: $name}) "
            "RETURN m.definition_yaml AS definition_yaml"
        )
        result = await self._driver.execute_read(query, {"name": mapping_name})

        if not result.rows:
            raise ValueError(f"Mapping definition not found: {mapping_name}")

        definition_yaml = result.rows[0].get("definition_yaml")
        if not definition_yaml:
            raise ValueError(
                f"Mapping '{mapping_name}' has no definition_yaml"
            )
        return yaml.safe_load(definition_yaml)

    # ------------------------------------------------------------------
    # Mutation execution
    # ------------------------------------------------------------------

    async def _execute_mutations(
        self,
        mutations: list[GraphMutation],
        run_id: str,
        source_hostname: str,
    ) -> int:
        """Execute a list of ``GraphMutation`` objects against Neo4j.

        Node upserts are batched by ``node_type`` and sent through
        ``bulk_upsert`` for performance.  Edge upserts are executed
        individually via MERGE queries.

        Provenance metadata is injected into every mutation.
        """
        from packages.graph_db.repositories.node_repository import NodeRepository

        node_repo = NodeRepository(self._driver, self._registry)
        timestamp = datetime.now(timezone.utc).isoformat()
        applied = 0

        # Group node mutations by type for batched upsert.
        node_batches: dict[str, list[dict[str, Any]]] = {}
        match_keys: dict[str, list[str]] = {}

        for mutation in mutations:
            if mutation.operation == "upsert_node" and mutation.node_type:
                # Inject provenance into attributes.
                attrs = {
                    **mutation.attributes,
                    "_ingestion_run_id": run_id,
                    "_ingestion_source": source_hostname,
                    "_ingestion_timestamp": timestamp,
                    "_ingestion_parser": "textfsm",
                }
                node_batches.setdefault(mutation.node_type, []).append(attrs)
                # Capture match_on keys (assumed consistent within a batch).
                if mutation.node_type not in match_keys:
                    match_keys[mutation.node_type] = list(mutation.match_on.keys())

            elif mutation.operation == "upsert_edge" and mutation.edge_type:
                try:
                    await self._upsert_edge(mutation, run_id, timestamp)
                    applied += 1
                except Exception as exc:
                    logger.warning(
                        "ingestion.edge_upsert_failed",
                        edge_type=mutation.edge_type,
                        error=str(exc),
                    )

        # Execute batched node upserts.
        for node_type, items in node_batches.items():
            try:
                counts = await node_repo.bulk_upsert(
                    node_type=node_type,
                    items=items,
                    match_on=match_keys.get(node_type, ["name"]),
                )
                applied += counts.get("created", 0) + counts.get("updated", 0)
            except Exception as exc:
                logger.warning(
                    "ingestion.bulk_upsert_failed",
                    node_type=node_type,
                    error=str(exc),
                )

        return applied

    async def _upsert_edge(
        self,
        mutation: GraphMutation,
        run_id: str,
        timestamp: str,
    ) -> None:
        """MERGE a single edge in Neo4j with provenance attributes."""
        source_match = mutation.source_match or {}
        target_match = mutation.target_match or {}

        # Build parameterised MATCH conditions for source and target.
        src_conditions = ", ".join(
            f"{k}: $src_{k}" for k in source_match
        )
        tgt_conditions = ", ".join(
            f"{k}: $tgt_{k}" for k in target_match
        )

        query = (
            f"MATCH (a {{{src_conditions}}}), (b {{{tgt_conditions}}}) "
            f"MERGE (a)-[r:{mutation.edge_type}]->(b) "
            f"SET r._ingestion_run_id = $run_id, "
            f"r._ingestion_timestamp = $timestamp "
            f"RETURN r"
        )

        params: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": timestamp,
        }
        for k, v in source_match.items():
            params[f"src_{k}"] = v
        for k, v in target_match.items():
            params[f"tgt_{k}"] = v

        await self._driver.execute_write(query, params)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def _emit_completion(
        self,
        run_id: str,
        result: IngestionResult,
    ) -> None:
        """Emit an ``ingestion.completed`` event on the bus."""
        await self._event_bus.publish(Event(
            event_type="ingestion.completed",
            payload={
                "run_id": run_id,
                "devices_processed": result.devices_processed,
                "commands_executed": result.commands_executed,
                "records_parsed": result.records_parsed,
                "mutations_generated": result.mutations_generated,
                "mutations_applied": result.mutations_applied,
                "error_count": len(result.errors),
            },
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mutation_to_dict(mutation: GraphMutation) -> dict[str, Any]:
        """Serialise a ``GraphMutation`` for dry-run output."""
        return {
            "operation": mutation.operation,
            "node_type": mutation.node_type,
            "edge_type": mutation.edge_type,
            "match_on": mutation.match_on,
            "attributes": mutation.attributes,
            "source_match": mutation.source_match,
            "target_match": mutation.target_match,
        }
