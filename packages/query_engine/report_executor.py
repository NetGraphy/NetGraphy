"""Report executor — runs compiled reports and produces structured/CSV results.

Handles:
- Report execution against Neo4j
- Row flattening for CSV export
- Streaming CSV generation
- Result metadata
"""

from __future__ import annotations

import csv
import io
from typing import Any, AsyncIterator

import structlog

from packages.graph_db.driver import Neo4jDriver
from packages.query_engine.report_compiler import ReportCompiler
from packages.query_engine.report_models import (
    ReportDefinition,
    ReportResult,
    RowMode,
)
from packages.schema_engine.registry import SchemaRegistry

logger = structlog.get_logger()


class ReportExecutor:
    """Executes report definitions and produces structured or CSV results."""

    def __init__(self, driver: Neo4jDriver, registry: SchemaRegistry):
        self._driver = driver
        self._registry = registry
        self._compiler = ReportCompiler(registry)

    async def execute(self, report: ReportDefinition) -> ReportResult:
        """Execute a report and return structured results."""
        compiled = self._compiler.compile(report)

        logger.debug(
            "report_executing",
            entity=report.root_entity,
            columns=len(report.columns),
            row_mode=report.row_mode,
            cypher=compiled.data_query[:200],
        )

        # Execute data query
        data_result = await self._driver.execute_read(
            compiled.data_query, compiled.data_params,
        )

        # Execute count query
        total_count = None
        if compiled.count_query and compiled.count_params is not None:
            count_result = await self._driver.execute_read(
                compiled.count_query, compiled.count_params,
            )
            if count_result.rows:
                total_count = count_result.rows[0].get("total", len(data_result.rows))

        # Use the compiler's csv_headers — these match the Cypher AS aliases
        csv_headers = compiled.csv_headers
        column_meta = compiled.column_meta

        # The rows from Neo4j use the csv_header aliases from the compiler
        rows = data_result.rows

        return ReportResult(
            columns=column_meta,
            rows=rows,
            total_count=total_count,
            row_mode=report.row_mode,
            csv_headers=csv_headers,
            query_metadata={
                "cypher": compiled.data_query,
                "param_count": len(compiled.data_params),
                "entity": report.root_entity,
            },
        )

    async def export_csv(self, report: ReportDefinition) -> str:
        """Execute a report and return CSV string.

        Uses the full export limit instead of pagination limit.
        """
        # Override pagination for export
        export_report = report.model_copy(deep=True)
        export_report.pagination.limit = report.max_export_rows
        export_report.pagination.offset = 0

        result = await self.execute(export_report)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=result.csv_headers,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in result.rows:
            # Ensure all values are CSV-safe strings
            safe_row = {}
            for header in result.csv_headers:
                val = row.get(header)
                if val is None:
                    safe_row[header] = ""
                elif isinstance(val, (list, dict)):
                    import json
                    safe_row[header] = json.dumps(val)
                else:
                    safe_row[header] = str(val)
            writer.writerow(safe_row)

        return output.getvalue()

    async def stream_csv(self, report: ReportDefinition) -> AsyncIterator[str]:
        """Stream CSV rows for large exports.

        Yields the header row first, then data rows in batches.
        """
        export_report = report.model_copy(deep=True)
        export_report.pagination.limit = report.max_export_rows
        export_report.pagination.offset = 0

        result = await self.execute(export_report)

        # Yield header
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(result.csv_headers)
        yield output.getvalue()

        # Yield data rows
        for row in result.rows:
            output = io.StringIO()
            writer = csv.writer(output)
            values = []
            for header in result.csv_headers:
                val = row.get(header)
                if val is None:
                    values.append("")
                elif isinstance(val, (list, dict)):
                    import json
                    values.append(json.dumps(val))
                else:
                    values.append(str(val))
            writer.writerow(values)
            yield output.getvalue()

    def get_available_columns(self, entity: str) -> list[dict[str, Any]]:
        """Return available columns for report builder UI."""
        return self._compiler.get_available_columns(entity)

    def get_available_entities(self) -> list[dict[str, Any]]:
        """Return all entity types available as report roots."""
        entities = []
        for nt in self._registry._node_types.values():
            if nt.api.exposed:
                entities.append({
                    "name": nt.metadata.name,
                    "display_name": nt.metadata.display_name or nt.metadata.name,
                    "description": nt.metadata.description or "",
                    "category": nt.metadata.category or "",
                    "icon": nt.metadata.icon or "",
                })
        return sorted(entities, key=lambda x: x["display_name"])
