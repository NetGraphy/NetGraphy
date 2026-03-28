"""Example job: Collect device facts from network inventory.

This job demonstrates the NetGraphy job SDK pattern:
1. Query the graph for target devices
2. Use Nornir to collect commands from devices
3. Parse output with TextFSM
4. Map parsed data into graph mutations
5. Upsert results into the graph
"""

from __future__ import annotations

from packages.jobs.sdk.context import JobContext, JobResult, JobStatus


async def run(ctx: JobContext) -> JobResult:
    """Collect base facts from network devices.

    Parameters:
        target_query: Cypher query to select target devices
        command_bundle: Command bundle name to execute
        dry_run: If true, parse but don't write to graph
    """
    target_query = ctx.params.get("target_query", "MATCH (d:Device {status: 'active'}) RETURN d")
    command_bundle = ctx.params.get("command_bundle", "cisco_ios_base")
    dry_run = ctx.params.get("dry_run", False)

    ctx.logger.info("Starting device fact collection",
                    command_bundle=command_bundle, dry_run=dry_run)

    # Step 1: Query graph for target devices
    devices_result = await ctx.graph.execute_cypher(target_query, {})
    devices = devices_result.rows
    total = len(devices)

    ctx.logger.info("Target devices selected", count=total)
    await ctx.progress.report(0, total, "Starting collection")

    # Step 2: Build Nornir inventory from graph data
    # TODO: Implement NornirGraphInventory that builds Nornir inventory
    # from the graph query results. Each device needs:
    # - hostname/management_ip for connectivity
    # - platform for driver selection
    # - credentials from secrets

    # Example Nornir integration pattern:
    # from nornir import InitNornir
    # from nornir_netmiko.tasks import netmiko_send_command
    #
    # nr = InitNornir(
    #     inventory={
    #         "plugin": "packages.ingestion.collectors.nornir_graph_inventory.GraphInventory",
    #         "options": {"devices": devices, "secrets": ctx.secrets},
    #     },
    #     runner={"plugin": "threaded", "options": {"num_workers": ctx.params.get("concurrency", 10)}},
    # )

    # Step 3: Execute commands from bundle
    # TODO: Load command bundle, iterate commands, execute via Nornir

    # Step 4: Parse outputs
    # TODO: For each command output, run TextFSM parser

    # Step 5: Map and upsert
    # TODO: Apply mapping definitions, generate graph mutations, upsert

    collected = 0
    errors = []

    # Placeholder: iterate devices and simulate collection
    for i, device in enumerate(devices):
        device_name = device.get("d", {}).get("hostname", f"device-{i}")
        try:
            # TODO: Replace with actual Nornir execution
            ctx.logger.debug("Collecting from device", device=device_name)
            collected += 1
        except Exception as e:
            errors.append(f"{device_name}: {e}")
            ctx.logger.error("Collection failed", device=device_name, error=str(e))

        await ctx.progress.report(i + 1, total, f"Processed {device_name}")

    summary = {
        "total_devices": total,
        "collected": collected,
        "errors": len(errors),
        "dry_run": dry_run,
    }

    ctx.logger.info("Collection complete", **summary)

    return JobResult(
        status=JobStatus.SUCCESS if not errors else JobStatus.FAILURE,
        summary=summary,
        errors=errors,
    )
