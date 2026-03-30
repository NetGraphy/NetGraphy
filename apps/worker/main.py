"""NetGraphy Worker — Celery-based job execution worker.

Processes job executions dispatched by the API server.
Supports Python jobs natively and Go jobs via subprocess.
"""

from celery import Celery

from netgraphy_api.config import settings

app = Celery(
    "netgraphy-worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # Fair task distribution
)


@app.task(bind=True, name="netgraphy.execute_job")
def execute_job(self, job_name: str, execution_id: str, params: dict):
    """Execute a registered job.

    This is the main Celery task that:
    1. Loads the job manifest
    2. Resolves the job entrypoint
    3. Builds the JobContext
    4. Executes the job function
    5. Records results
    """
    import asyncio
    import importlib

    from packages.jobs.sdk.context import JobContext, JobResult, JobStatus

    # TODO: Load manifest from job registry
    # TODO: Build proper JobContext with graph connection, secrets, etc.
    # TODO: Implement proper progress reporting and log streaming

    # For now, a basic execution skeleton:
    try:
        # Parse entrypoint: "jobs.python.collect_device_facts:run"
        module_path, func_name = "jobs.python.example_job", "run"

        module = importlib.import_module(module_path)
        job_func = getattr(module, func_name)

        # Execute
        # result = asyncio.run(job_func(ctx))
        return {"status": "success", "execution_id": execution_id}

    except Exception as e:
        return {"status": "failure", "execution_id": execution_id, "error": str(e)}


@app.task(bind=True, name="netgraphy.execute_ingestion")
def execute_ingestion(self, run_id: str, target_query: str, command_bundle: str):
    """Execute an ingestion pipeline run.

    Orchestrates the full collect -> parse -> map -> mutate flow:
    1. Update run status to ``running``
    2. Resolve target devices via the supplied Cypher query
    3. Load the command bundle definition
    4. Build and execute the IngestionPipeline
    5. Update the run node with final statistics
    """
    import asyncio
    import json
    from datetime import datetime, timezone

    from packages.events.bus import EventBus
    from packages.graph_db.driver import Neo4jDriver
    from packages.ingestion.collectors.base import CollectorCommand, DeviceTarget
    from packages.ingestion.collectors.nornir_collector import NornirCollector
    from packages.ingestion.pipeline import IngestionPipeline
    from packages.schema_engine.registry import SchemaRegistry

    async def _run() -> dict:
        driver = Neo4jDriver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        registry = SchemaRegistry()
        event_bus = EventBus()
        collector = NornirCollector()

        try:
            # Mark run as running
            now = datetime.now(timezone.utc).isoformat()
            await driver.execute_write(
                "MATCH (r:_IngestionRun {id: $id}) "
                "SET r.status = 'running', r.started_at = $now",
                {"id": run_id, "now": now},
            )

            # Resolve targets
            targets_result = await driver.execute_read(target_query)
            targets: list[DeviceTarget] = []
            for row in targets_result.rows:
                d = row.get("d") or row.get("n") or {}
                targets.append(DeviceTarget(
                    hostname=d.get("hostname", "unknown"),
                    management_ip=d.get("management_ip"),
                    platform_slug=d.get("platform_slug"),
                    netmiko_device_type=d.get("netmiko_device_type"),
                ))

            # Load command bundle
            bundle_result = await driver.execute_read(
                "MATCH (cb:_CommandBundle {name: $name}) RETURN cb",
                {"name": command_bundle},
            )
            commands: list[CollectorCommand] = []
            if bundle_result.rows:
                commands_json = bundle_result.rows[0]["cb"]["commands_json"]
                for cmd_def in json.loads(commands_json):
                    commands.append(CollectorCommand(
                        command=cmd_def["command"],
                        collector_type=cmd_def.get("collector_type", "cli"),
                        parser_name=cmd_def.get("parser_name"),
                        mapping_name=cmd_def.get("mapping_name"),
                    ))

            # Execute pipeline
            pipeline = IngestionPipeline(
                driver=driver,
                registry=registry,
                event_bus=event_bus,
                collector=collector,
            )
            result = await pipeline.execute(
                run_id=run_id,
                targets=targets,
                commands=commands,
                dry_run=False,
            )

            # Update run with results
            completed_at = datetime.now(timezone.utc).isoformat()
            await driver.execute_write(
                "MATCH (r:_IngestionRun {id: $id}) "
                "SET r.status = $status, r.completed_at = $now, "
                "    r.device_count = $devices, r.records_parsed = $records, "
                "    r.mutations_applied = $mutations, r.error_count = $error_count",
                {
                    "id": run_id,
                    "status": "failed" if result.errors else "completed",
                    "now": completed_at,
                    "devices": result.devices_processed,
                    "records": result.records_parsed,
                    "mutations": result.mutations_applied,
                    "error_count": len(result.errors),
                },
            )

            return {
                "status": "completed" if not result.errors else "completed_with_errors",
                "run_id": run_id,
                "devices_processed": result.devices_processed,
                "records_parsed": result.records_parsed,
                "mutations_applied": result.mutations_applied,
                "errors": result.errors,
            }

        except Exception as exc:
            # Mark run as failed
            failed_at = datetime.now(timezone.utc).isoformat()
            await driver.execute_write(
                "MATCH (r:_IngestionRun {id: $id}) "
                "SET r.status = 'failed', r.completed_at = $now, "
                "    r.error_message = $error",
                {"id": run_id, "now": failed_at, "error": str(exc)},
            )
            raise

        finally:
            await driver.close()

    return asyncio.run(_run())


@app.task(name="netgraphy.execute_sync")
def execute_sync(source_id: str):
    """Execute a Git source sync."""
    # TODO: Implement sync execution
    return {"status": "success", "source_id": source_id}
