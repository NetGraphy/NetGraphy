# NetGraphy Architecture: Ingestion, Jobs, Git Sync, Security, and Operations

This document covers Sections 9 through 15 of the NetGraphy architecture specification:
parser/mapping architecture, jobs framework, Git synchronization, security/RBAC/audit,
performance and operations, testing strategy, and local development.

---

## 9. Parser/Mapping Architecture

### 9.1 Ingestion Pipeline Overview

The ingestion pipeline transforms raw network device output into graph facts through a
deterministic, auditable sequence of stages:

```
Command Collection
       |
       v
Raw Output Storage (MinIO/S3)
       |
       v
Parser Execution (TextFSM)
       |
       v
Parsed Records (list[dict])
       |
       v
Mapping Engine (YAML-defined transforms)
       |
       v
Graph Mutations (Cypher UNWIND batches)
       |
       v
Provenance Recording (per-fact lineage)
```

Each stage is independent and replayable. Raw output is stored before parsing, so parsers
can be updated and re-run against historical data without re-collecting from devices. Parsed
records are ephemeral intermediate state -- they exist only for the duration of a job run
and are not persisted independently. Graph mutations are the durable output.

**Implementation entry point:** `apps/api/netgraphy/ingestion/pipeline.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4
from typing import Any

@dataclass
class IngestionContext:
    job_run_id: UUID
    device_id: UUID
    device_hostname: str
    collected_at: datetime
    command_bundle: str

@dataclass
class RawOutput:
    command: str
    output: str
    storage_key: str  # MinIO object key after storage
    collected_at: datetime
    exit_code: int

@dataclass
class ParsedRecord:
    parser_name: str
    command: str
    data: list[dict[str, Any]]

@dataclass
class GraphMutation:
    """A single node or edge upsert with full provenance."""
    mutation_type: str  # "upsert_node" | "upsert_edge"
    cypher: str
    parameters: dict[str, Any]
    provenance: dict[str, Any]


class IngestionPipeline:
    """Orchestrates the full ingestion flow for a single device."""

    def __init__(
        self,
        raw_store: "RawOutputStore",
        parser_registry: "ParserRegistry",
        mapping_engine: "MappingEngine",
        graph_repo: "GraphRepository",
        event_bus: "EventBus",
    ):
        self._raw_store = raw_store
        self._parser_registry = parser_registry
        self._mapping_engine = mapping_engine
        self._graph_repo = graph_repo
        self._event_bus = event_bus

    async def ingest(
        self,
        ctx: IngestionContext,
        raw_outputs: list[RawOutput],
        bundle: "CommandBundle",
    ) -> "IngestionResult":
        results = []

        for raw in raw_outputs:
            # 1. Store raw output
            storage_key = await self._raw_store.store(
                job_run_id=ctx.job_run_id,
                device_hostname=ctx.device_hostname,
                command=raw.command,
                output=raw.output,
                collected_at=raw.collected_at,
            )
            raw.storage_key = storage_key

            # 2. Resolve parser and mapping from bundle
            cmd_entry = bundle.get_command_entry(raw.command)
            if cmd_entry is None:
                results.append(CommandResult(
                    command=raw.command, status="skipped", reason="no bundle entry"
                ))
                continue

            # 3. Parse raw output
            parser = self._parser_registry.get(cmd_entry.parser)
            parsed_records = parser.parse(raw.output)

            # 4. Map parsed records to graph mutations
            mapping = self._mapping_engine.load(cmd_entry.mapping)
            mutations = mapping.apply(
                parsed_records=parsed_records,
                provenance=Provenance(
                    source_type="collected",
                    source_command=raw.command,
                    source_parser=cmd_entry.parser,
                    source_mapping=cmd_entry.mapping,
                    source_job_run_id=ctx.job_run_id,
                    collected_at=ctx.collected_at,
                    device_id=ctx.device_id,
                    raw_output_ref=storage_key,
                    confidence_score=1.0,
                ),
            )

            # 5. Execute graph mutations in batch
            await self._graph_repo.execute_mutations(mutations)

            results.append(CommandResult(
                command=raw.command,
                status="success",
                records_parsed=len(parsed_records),
                mutations_applied=len(mutations),
            ))

        # 6. Emit completion event
        await self._event_bus.publish("ingestion.device.completed", {
            "job_run_id": str(ctx.job_run_id),
            "device_id": str(ctx.device_id),
            "device_hostname": ctx.device_hostname,
            "commands_processed": len(results),
        })

        return IngestionResult(device_hostname=ctx.device_hostname, commands=results)
```

### 9.2 Command Bundle Format

Command bundles define what to collect from a device and how to process it. They are
YAML files stored in `commands/` and synced via Git or managed through the API.

```yaml
kind: CommandBundle
version: v1
metadata:
  name: cisco_ios_base
  description: "Base collection for Cisco IOS devices"
  platform: cisco_ios
  tags: [cisco, ios, base]

commands:
  - command: "show version"
    parser: cisco_ios_show_version
    mapping: cisco_ios_version_to_graph
    timeout_seconds: 30

  - command: "show interfaces"
    parser: cisco_ios_show_interfaces
    mapping: cisco_ios_interfaces_to_graph
    timeout_seconds: 60

  - command: "show ip interface brief"
    parser: cisco_ios_show_ip_int_brief
    mapping: cisco_ios_ip_int_brief_to_graph
    timeout_seconds: 30

  - command: "show cdp neighbors detail"
    parser: cisco_ios_show_cdp_neighbors_detail
    mapping: cisco_ios_cdp_to_graph
    timeout_seconds: 30

  - command: "show ip route"
    parser: cisco_ios_show_ip_route
    mapping: cisco_ios_routes_to_graph
    timeout_seconds: 60

  - command: "show vlan brief"
    parser: cisco_ios_show_vlan_brief
    mapping: cisco_ios_vlans_to_graph
    timeout_seconds: 30
```

**Bundle loader implementation:** `apps/api/netgraphy/ingestion/bundles.py`

```python
from pathlib import Path
from dataclasses import dataclass
import yaml

@dataclass
class CommandEntry:
    command: str
    parser: str
    mapping: str
    timeout_seconds: int = 30

@dataclass
class CommandBundle:
    name: str
    description: str
    platform: str
    tags: list[str]
    commands: list[CommandEntry]

    def get_command_entry(self, command: str) -> CommandEntry | None:
        for entry in self.commands:
            if entry.command == command:
                return entry
        return None

    @classmethod
    def from_yaml(cls, data: dict) -> "CommandBundle":
        meta = data["metadata"]
        return cls(
            name=meta["name"],
            description=meta.get("description", ""),
            platform=meta["platform"],
            tags=meta.get("tags", []),
            commands=[
                CommandEntry(
                    command=c["command"],
                    parser=c["parser"],
                    mapping=c["mapping"],
                    timeout_seconds=c.get("timeout_seconds", 30),
                )
                for c in data["commands"]
            ],
        )

class BundleRegistry:
    """Loads command bundles from the database and filesystem."""

    def __init__(self, db_session, content_dir: Path | None = None):
        self._db = db_session
        self._content_dir = content_dir
        self._cache: dict[str, CommandBundle] = {}

    async def get(self, name: str) -> CommandBundle:
        if name in self._cache:
            return self._cache[name]

        # Try database first (managed bundles and git-synced bundles)
        row = await self._db.fetch_one(
            "SELECT definition FROM command_bundles WHERE name = :name AND active = true",
            {"name": name},
        )
        if row:
            bundle = CommandBundle.from_yaml(yaml.safe_load(row["definition"]))
            self._cache[name] = bundle
            return bundle

        # Fall back to filesystem (development)
        if self._content_dir:
            path = self._content_dir / f"{name}.yaml"
            if path.exists():
                with open(path) as f:
                    bundle = CommandBundle.from_yaml(yaml.safe_load(f))
                    self._cache[name] = bundle
                    return bundle

        raise ValueError(f"Command bundle not found: {name}")

    def invalidate(self, name: str | None = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
```

### 9.3 TextFSM Parser Registry

Parsers use [TextFSM](https://github.com/google/textfsm) templates to transform raw
command output into structured records. NetGraphy ships with
[NTC Templates](https://github.com/networktocode/ntc-templates) as a baseline and
supports custom overrides.

**Directory structure:**

```
parsers/
  templates/
    cisco_ios_show_version.textfsm
    cisco_ios_show_interfaces.textfsm
    cisco_ios_show_cdp_neighbors_detail.textfsm
    ...
  fixtures/
    cisco_ios_show_version/
      input_01.txt
      expected_01.json
      input_02.txt      # multiple fixtures per parser
      expected_02.json
    cisco_ios_show_interfaces/
      input_01.txt
      expected_01.json
```

**Parser registry database schema** (PostgreSQL sidecar -- parsers are registered metadata;
the actual template content lives in the filesystem or object storage):

```sql
CREATE TABLE parser_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,          -- "cisco_ios_show_version"
    platform VARCHAR(100) NOT NULL,             -- "cisco_ios"
    command VARCHAR(500) NOT NULL,              -- "show version"
    version INTEGER NOT NULL DEFAULT 1,
    author VARCHAR(255),
    description TEXT,
    template_content TEXT NOT NULL,             -- TextFSM template body
    is_custom BOOLEAN DEFAULT false,            -- true = overrides NTC template
    managed_by VARCHAR(255) DEFAULT 'local',    -- "local" or "git:{source_name}"
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_parser_templates_platform ON parser_templates(platform);
CREATE INDEX idx_parser_templates_command ON parser_templates(command);
```

**Parser execution engine:** `apps/api/netgraphy/ingestion/parsers.py`

```python
import io
from typing import Any
import textfsm

class TextFSMParser:
    """Wraps a TextFSM template for parsing raw command output."""

    def __init__(self, name: str, template_content: str):
        self.name = name
        self._template_content = template_content

    def parse(self, raw_output: str) -> list[dict[str, Any]]:
        template = textfsm.TextFSM(io.StringIO(self._template_content))
        parsed = template.ParseText(raw_output)
        headers = template.header
        return [dict(zip(headers, row)) for row in parsed]


class ParserRegistry:
    """Resolves parser names to TextFSMParser instances.

    Resolution order:
    1. Custom templates in DB (is_custom=True)
    2. Standard templates in DB
    3. NTC Templates on filesystem (fallback)
    """

    def __init__(self, db_session, ntc_templates_dir: str | None = None):
        self._db = db_session
        self._ntc_dir = ntc_templates_dir
        self._cache: dict[str, TextFSMParser] = {}

    async def get(self, name: str) -> TextFSMParser:
        if name in self._cache:
            return self._cache[name]

        # Check DB -- custom templates take precedence
        row = await self._db.fetch_one(
            """SELECT name, template_content FROM parser_templates
               WHERE name = :name
               ORDER BY is_custom DESC, version DESC
               LIMIT 1""",
            {"name": name},
        )
        if row:
            parser = TextFSMParser(row["name"], row["template_content"])
            self._cache[name] = parser
            return parser

        # Fallback: NTC Templates filesystem
        if self._ntc_dir:
            # NTC convention: platform_command.textfsm
            # e.g., cisco_ios_show_version.textfsm
            template_path = f"{self._ntc_dir}/{name}.textfsm"
            try:
                with open(template_path) as f:
                    content = f.read()
                parser = TextFSMParser(name, content)
                self._cache[name] = parser
                return parser
            except FileNotFoundError:
                pass

        raise ValueError(f"Parser template not found: {name}")

    async def register(
        self,
        name: str,
        platform: str,
        command: str,
        template_content: str,
        author: str | None = None,
        is_custom: bool = False,
    ) -> None:
        """Register or update a parser template."""
        await self._db.execute(
            """INSERT INTO parser_templates (name, platform, command, template_content, author, is_custom)
               VALUES (:name, :platform, :command, :template_content, :author, :is_custom)
               ON CONFLICT (name) DO UPDATE SET
                 template_content = EXCLUDED.template_content,
                 version = parser_templates.version + 1,
                 is_custom = EXCLUDED.is_custom,
                 updated_at = now()""",
            {
                "name": name,
                "platform": platform,
                "command": command,
                "template_content": template_content,
                "author": author,
                "is_custom": is_custom,
            },
        )
        self._cache.pop(name, None)

    def invalidate(self, name: str | None = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()
```

### 9.4 Mapping Definition Format

Mappings define how parsed records translate into graph nodes, edges, and their attributes.
They use Jinja2 templating for attribute values, allowing parsed fields to be referenced
directly.

**Full mapping definition example:**

```yaml
kind: MappingDefinition
version: v1
metadata:
  name: cisco_ios_version_to_graph
  description: "Maps show version output to Device and SoftwareVersion nodes"
  parser: cisco_ios_show_version

mappings:
  # Upsert a Device node, matched by hostname
  - target_node_type: Device
    match_on: [hostname]
    attributes:
      hostname: "{{ parsed.hostname }}"
      serial_number: "{{ parsed.serial[0] }}"
      hardware_model: "{{ parsed.hardware[0] }}"
      uptime: "{{ parsed.uptime }}"
      reload_reason: "{{ parsed.reload_reason }}"
      config_register: "{{ parsed.config_register }}"

  # Upsert a SoftwareVersion node
  - target_node_type: SoftwareVersion
    match_on: [version_string, platform]
    attributes:
      version_string: "{{ parsed.version }}"
      platform: "{{ parsed.platform }}"
      image_file: "{{ parsed.running_image }}"
      rommon_version: "{{ parsed.rommon }}"

  # Create the RUNS_VERSION edge between Device and SoftwareVersion
  - target_edge_type: RUNS_VERSION
    source:
      node_type: Device
      match_on:
        hostname: "{{ parsed.hostname }}"
    target:
      node_type: SoftwareVersion
      match_on:
        version_string: "{{ parsed.version }}"
        platform: "{{ parsed.platform }}"
    attributes:
      first_seen: "{{ now() }}"
```

**Interface mapping example** (one-to-many -- one command produces multiple interfaces):

```yaml
kind: MappingDefinition
version: v1
metadata:
  name: cisco_ios_interfaces_to_graph
  description: "Maps show interfaces output to Interface nodes"
  parser: cisco_ios_show_interfaces

# iterate: true means each parsed record produces its own set of mutations
iterate: true

mappings:
  - target_node_type: Interface
    match_on: [device_hostname, name]
    attributes:
      name: "{{ parsed.interface }}"
      device_hostname: "{{ context.device_hostname }}"
      ip_address: "{{ parsed.ip_address }}"
      status: "{{ parsed.link_status }}"
      protocol_status: "{{ parsed.protocol_status }}"
      mtu: "{{ parsed.mtu | int }}"
      bandwidth_kbps: "{{ parsed.bandwidth | int }}"
      description: "{{ parsed.description }}"
      mac_address: "{{ parsed.address }}"
      media_type: "{{ parsed.media_type }}"

  - target_edge_type: HAS_INTERFACE
    source:
      node_type: Device
      match_on:
        hostname: "{{ context.device_hostname }}"
    target:
      node_type: Interface
      match_on:
        device_hostname: "{{ context.device_hostname }}"
        name: "{{ parsed.interface }}"
```

**CDP neighbor mapping** (creates edges between devices):

```yaml
kind: MappingDefinition
version: v1
metadata:
  name: cisco_ios_cdp_to_graph
  description: "Maps CDP neighbors to topology edges"
  parser: cisco_ios_show_cdp_neighbors_detail

iterate: true

mappings:
  # Ensure the remote device exists as a stub
  - target_node_type: Device
    match_on: [hostname]
    attributes:
      hostname: "{{ parsed.destination_host | strip_domain }}"
      platform: "{{ parsed.platform }}"
      management_ip: "{{ parsed.management_ip }}"
      _stub: true  # Marked as stub -- will be enriched when collected directly

  # Create the topology edge
  - target_edge_type: CONNECTED_TO
    source:
      node_type: Interface
      match_on:
        device_hostname: "{{ context.device_hostname }}"
        name: "{{ parsed.local_port }}"
    target:
      node_type: Interface
      match_on:
        device_hostname: "{{ parsed.destination_host | strip_domain }}"
        name: "{{ parsed.remote_port }}"
    attributes:
      discovery_protocol: "cdp"
      remote_platform: "{{ parsed.platform }}"
```

**Mapping engine implementation:** `apps/api/netgraphy/ingestion/mapping.py`

```python
from dataclasses import dataclass
from typing import Any
import jinja2

@dataclass
class Provenance:
    source_type: str
    source_command: str
    source_parser: str
    source_mapping: str
    source_job_run_id: str
    collected_at: str
    device_id: str
    raw_output_ref: str
    confidence_score: float

class MappingEngine:
    """Applies a mapping definition to parsed records, producing graph mutations."""

    def __init__(self, schema_registry: "SchemaRegistry"):
        self._schema_registry = schema_registry
        self._jinja_env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        # Register custom filters
        self._jinja_env.filters["strip_domain"] = lambda s: s.split(".")[0] if s else s
        self._jinja_env.filters["normalize_interface"] = self._normalize_interface

    def load(self, mapping_name: str) -> "MappingExecutor":
        # Load mapping definition from registry (DB or filesystem)
        definition = self._load_definition(mapping_name)
        return MappingExecutor(definition, self._jinja_env, self._schema_registry)

    @staticmethod
    def _normalize_interface(value: str) -> str:
        """Normalize interface names: Gi0/1 -> GigabitEthernet0/1, etc."""
        abbreviations = {
            "Gi": "GigabitEthernet",
            "Te": "TenGigabitEthernet",
            "Fa": "FastEthernet",
            "Eth": "Ethernet",
            "Lo": "Loopback",
            "Vl": "Vlan",
            "Po": "Port-channel",
        }
        for abbrev, full in abbreviations.items():
            if value.startswith(abbrev) and not value.startswith(full):
                return full + value[len(abbrev):]
        return value

    def _load_definition(self, name: str) -> dict:
        # Implementation loads from DB or filesystem
        ...


class MappingExecutor:
    """Executes a loaded mapping definition against parsed records."""

    def __init__(self, definition: dict, jinja_env: jinja2.Environment, schema_registry):
        self._definition = definition
        self._jinja = jinja_env
        self._schema = schema_registry
        self._iterate = definition.get("iterate", False)

    def apply(
        self,
        parsed_records: list[dict[str, Any]],
        provenance: Provenance,
        context: dict[str, Any] | None = None,
    ) -> list["GraphMutation"]:
        mutations: list[GraphMutation] = []
        context = context or {}

        if self._iterate:
            # Each parsed record generates its own set of mutations
            for record in parsed_records:
                template_ctx = {"parsed": record, "context": context}
                for mapping in self._definition["mappings"]:
                    mutation = self._apply_single_mapping(mapping, template_ctx, provenance)
                    if mutation:
                        mutations.append(mutation)
        else:
            # All records treated as one (e.g., show version returns one record)
            record = parsed_records[0] if parsed_records else {}
            template_ctx = {"parsed": record, "context": context}
            for mapping in self._definition["mappings"]:
                mutation = self._apply_single_mapping(mapping, template_ctx, provenance)
                if mutation:
                    mutations.append(mutation)

        return mutations

    def _apply_single_mapping(
        self,
        mapping: dict,
        template_ctx: dict,
        provenance: Provenance,
    ) -> "GraphMutation | None":
        if "target_node_type" in mapping:
            return self._build_node_upsert(mapping, template_ctx, provenance)
        elif "target_edge_type" in mapping:
            return self._build_edge_upsert(mapping, template_ctx, provenance)
        return None

    def _build_node_upsert(
        self, mapping: dict, ctx: dict, provenance: Provenance
    ) -> "GraphMutation":
        node_type = mapping["target_node_type"]
        match_keys = mapping["match_on"]
        attrs = self._render_attributes(mapping["attributes"], ctx)

        # Build match properties from rendered attributes
        match_props = {k: attrs[k] for k in match_keys if k in attrs}
        set_props = {k: v for k, v in attrs.items() if k not in match_keys}

        # Inject provenance into properties
        provenance_dict = {
            "_source_type": provenance.source_type,
            "_source_job_run_id": str(provenance.source_job_run_id),
            "_collected_at": str(provenance.collected_at),
            "_confidence_score": provenance.confidence_score,
        }
        set_props.update(provenance_dict)

        # Generate MERGE Cypher
        match_clause = ", ".join(f"{k}: ${k}" for k in match_props)
        set_clause = ", ".join(f"n.{k} = ${k}" for k in set_props)

        cypher = f"""
            MERGE (n:{node_type} {{{match_clause}}})
            ON CREATE SET {set_clause}, n._created_at = datetime()
            ON MATCH SET {set_clause}, n._updated_at = datetime()
        """

        params = {**match_props, **set_props}
        return GraphMutation(
            mutation_type="upsert_node",
            cypher=cypher,
            parameters=params,
            provenance=provenance.__dict__,
        )

    def _build_edge_upsert(
        self, mapping: dict, ctx: dict, provenance: Provenance
    ) -> "GraphMutation":
        edge_type = mapping["target_edge_type"]
        source = mapping["source"]
        target = mapping["target"]

        source_match = self._render_attributes(source["match_on"], ctx)
        target_match = self._render_attributes(target["match_on"], ctx)
        edge_attrs = self._render_attributes(mapping.get("attributes", {}), ctx)

        # Build Cypher for edge upsert
        src_match = ", ".join(f"{k}: $src_{k}" for k in source_match)
        tgt_match = ", ".join(f"{k}: $tgt_{k}" for k in target_match)
        edge_set = ", ".join(f"r.{k} = $edge_{k}" for k in edge_attrs)

        cypher = f"""
            MATCH (src:{source['node_type']} {{{src_match}}})
            MATCH (tgt:{target['node_type']} {{{tgt_match}}})
            MERGE (src)-[r:{edge_type}]->(tgt)
            {"SET " + edge_set if edge_set else ""}
        """

        params = {}
        params.update({f"src_{k}": v for k, v in source_match.items()})
        params.update({f"tgt_{k}": v for k, v in target_match.items()})
        params.update({f"edge_{k}": v for k, v in edge_attrs.items()})

        return GraphMutation(
            mutation_type="upsert_edge",
            cypher=cypher,
            parameters=params,
            provenance=provenance.__dict__,
        )

    def _render_attributes(self, attrs: dict, ctx: dict) -> dict[str, Any]:
        """Render Jinja2 templates in attribute values."""
        rendered = {}
        for key, template_str in attrs.items():
            if isinstance(template_str, str) and "{{" in template_str:
                template = self._jinja.from_string(template_str)
                value = template.render(**ctx)
                # Skip empty strings from templates that resolved to nothing
                if value.strip():
                    rendered[key] = value
            else:
                rendered[key] = template_str
        return rendered
```

### 9.5 Provenance Model

Every fact written by the ingestion pipeline carries full lineage metadata. This enables
audit ("where did this value come from?"), debugging ("which parser produced this?"),
and replay ("re-run this parser against the stored raw output").

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass
class Provenance:
    source_type: str          # "collected", "manual", "imported", "inferred"
    source_command: str        # "show version"
    source_parser: str         # "cisco_ios_show_version"
    source_mapping: str        # "cisco_ios_version_to_graph"
    source_job_run_id: UUID    # Links to the specific job execution
    collected_at: datetime     # When the command was run on the device
    device_id: UUID            # Which device the data came from
    raw_output_ref: str        # MinIO object key for the raw output
    confidence_score: float    # 1.0 for direct parse, <1.0 for inferred
```

**Provenance is stored on graph nodes as underscore-prefixed properties:**

```
(:Device {
  hostname: "core-rtr-01",
  serial_number: "FTX1234ABCD",
  _source_type: "collected",
  _source_job_run_id: "a1b2c3d4-...",
  _collected_at: "2026-03-28T14:30:00Z",
  _confidence_score: 1.0,
  _created_at: "2026-03-28T14:30:05Z",
  _updated_at: "2026-03-28T14:30:05Z"
})
```

**Field-level provenance** is stored in a separate PostgreSQL table for full audit detail,
since storing per-field provenance on Neo4j properties would be impractical:

```sql
CREATE TABLE fact_provenance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_type VARCHAR(100) NOT NULL,
    node_match_key JSONB NOT NULL,        -- {"hostname": "core-rtr-01"}
    field_name VARCHAR(255) NOT NULL,
    field_value TEXT,
    source_type VARCHAR(50) NOT NULL,
    source_command VARCHAR(500),
    source_parser VARCHAR(255),
    source_mapping VARCHAR(255),
    source_job_run_id UUID NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    device_id UUID,
    raw_output_ref VARCHAR(500),
    confidence_score FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Composite index for lookups by node + field
    CONSTRAINT uq_fact_provenance UNIQUE (node_type, node_match_key, field_name, source_job_run_id)
);

CREATE INDEX idx_fact_prov_node ON fact_provenance(node_type, node_match_key);
CREATE INDEX idx_fact_prov_job ON fact_provenance(source_job_run_id);
CREATE INDEX idx_fact_prov_device ON fact_provenance(device_id);
CREATE INDEX idx_fact_prov_collected ON fact_provenance(collected_at);
```

**Querying provenance:**

```sql
-- "Where did the serial_number for core-rtr-01 come from?"
SELECT * FROM fact_provenance
WHERE node_type = 'Device'
  AND node_match_key = '{"hostname": "core-rtr-01"}'
  AND field_name = 'serial_number'
ORDER BY collected_at DESC
LIMIT 10;

-- "What facts were written by job run X?"
SELECT * FROM fact_provenance
WHERE source_job_run_id = 'a1b2c3d4-...'
ORDER BY node_type, field_name;
```

### 9.6 Raw Output Storage

Raw command output is stored in MinIO (S3-compatible) before parsing. This ensures
outputs are never lost and parsers can be improved retroactively.

**Storage key format:**

```
raw-outputs/{job_run_id}/{device_hostname}/{command_slug}/{timestamp}.txt
```

Where `command_slug` normalizes the command: `show ip interface brief` becomes
`show_ip_interface_brief`.

**Implementation:** `apps/api/netgraphy/ingestion/raw_store.py`

```python
from datetime import datetime
from uuid import UUID
import re
from miniopy_async import Minio

BUCKET_NAME = "netgraphy-raw-outputs"

class RawOutputStore:
    def __init__(self, minio_client: Minio):
        self._client = minio_client

    async def ensure_bucket(self):
        exists = await self._client.bucket_exists(BUCKET_NAME)
        if not exists:
            await self._client.make_bucket(BUCKET_NAME)

    async def store(
        self,
        job_run_id: UUID,
        device_hostname: str,
        command: str,
        output: str,
        collected_at: datetime,
    ) -> str:
        slug = self._slugify_command(command)
        ts = collected_at.strftime("%Y%m%dT%H%M%S")
        key = f"raw-outputs/{job_run_id}/{device_hostname}/{slug}/{ts}.txt"

        data = output.encode("utf-8")
        from io import BytesIO
        await self._client.put_object(
            BUCKET_NAME,
            key,
            BytesIO(data),
            length=len(data),
            content_type="text/plain",
            metadata={
                "device_hostname": device_hostname,
                "command": command,
                "job_run_id": str(job_run_id),
                "collected_at": collected_at.isoformat(),
            },
        )
        return key

    async def retrieve(self, key: str) -> str:
        response = await self._client.get_object(BUCKET_NAME, key)
        data = await response.read()
        return data.decode("utf-8")

    async def list_for_device(
        self,
        device_hostname: str,
        command: str | None = None,
        since: datetime | None = None,
    ) -> list[dict]:
        """List raw outputs for a device, optionally filtered by command and time."""
        prefix = f"raw-outputs/"
        results = []

        # MinIO list_objects is synchronous in the async wrapper; iterate
        objects = await self._client.list_objects(
            BUCKET_NAME, prefix=prefix, recursive=True
        )
        for obj in objects:
            # Parse key components
            parts = obj.object_name.split("/")
            if len(parts) >= 5 and parts[2] == device_hostname:
                if command and parts[3] != self._slugify_command(command):
                    continue
                if since and obj.last_modified < since:
                    continue
                results.append({
                    "key": obj.object_name,
                    "job_run_id": parts[1],
                    "device_hostname": parts[2],
                    "command_slug": parts[3],
                    "timestamp": parts[4].replace(".txt", ""),
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                })

        return sorted(results, key=lambda r: r["timestamp"], reverse=True)

    @staticmethod
    def _slugify_command(command: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", command.lower()).strip("_")
```

**Retention policy** is enforced by a scheduled job that runs daily:

```python
# jobs/python/cleanup_raw_outputs.py
async def run(ctx: JobContext) -> JobResult:
    retention_days = ctx.params.get("retention_days", 90)
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    deleted_count = 0
    objects = await ctx.raw_store.list_objects(
        BUCKET_NAME, prefix="raw-outputs/", recursive=True
    )
    for obj in objects:
        if obj.last_modified < cutoff:
            await ctx.raw_store.remove_object(BUCKET_NAME, obj.object_name)
            deleted_count += 1

    return JobResult(status="success", summary={"deleted": deleted_count})
```

### 9.7 Parser Testing

Every parser must have at least one fixture. Tests are fixture-driven and run in CI.

**Fixture structure:**

```
parsers/fixtures/
  cisco_ios_show_version/
    input_01.txt              # Raw "show version" output from a device
    expected_01.json          # Expected parsed records
    input_02.txt              # Different device model / version
    expected_02.json
  cisco_ios_show_interfaces/
    input_01.txt
    expected_01.json
```

**Example fixture -- `parsers/fixtures/cisco_ios_show_version/input_01.txt`:**

```
Cisco IOS Software, C3750E Software (C3750E-UNIVERSALK9-M), Version 15.2(4)E10, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2018 by Cisco Systems, Inc.
Compiled Fri 16-Nov-18 07:07 by prod_rel_team

ROM: Bootstrap program is C3750E boot loader
BOOTLDR: C3750E Boot Loader (C3750E-HBOOT-M) Version 12.2(58r)SE, RELEASE SOFTWARE (fc1)

core-sw-01 uptime is 1 year, 2 weeks, 3 days, 4 hours, 5 minutes
System returned to ROM by power-on
System image file is "flash:/c3750e-universalk9-mz.152-4.E10.bin"

...
```

**Example fixture -- `parsers/fixtures/cisco_ios_show_version/expected_01.json`:**

```json
[
  {
    "version": "15.2(4)E10",
    "rommon": "12.2(58r)SE",
    "hostname": "core-sw-01",
    "uptime": "1 year, 2 weeks, 3 days, 4 hours, 5 minutes",
    "reload_reason": "power-on",
    "running_image": "flash:/c3750e-universalk9-mz.152-4.E10.bin",
    "hardware": ["WS-C3750E-48PD"],
    "serial": ["FDO1234A5BC"],
    "config_register": "0xF"
  }
]
```

**Test runner:** `tests/parsers/test_parsers.py`

```python
import json
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent.parent.parent / "parsers" / "fixtures"
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "parsers" / "templates"

def discover_parser_fixtures() -> list[tuple[str, Path, Path]]:
    """Discover all (parser_name, input_file, expected_file) triples."""
    fixtures = []
    for parser_dir in sorted(FIXTURES_DIR.iterdir()):
        if not parser_dir.is_dir():
            continue
        parser_name = parser_dir.name
        # Find all input/expected pairs
        for input_file in sorted(parser_dir.glob("input_*.txt")):
            suffix = input_file.stem.replace("input", "expected")
            expected_file = parser_dir / f"{suffix}.json"
            if expected_file.exists():
                fixtures.append((parser_name, input_file, expected_file))
    return fixtures

@pytest.mark.parametrize(
    "parser_name,input_file,expected_file",
    discover_parser_fixtures(),
    ids=lambda x: str(x) if isinstance(x, Path) else x,
)
def test_parser_fixture(parser_name: str, input_file: Path, expected_file: Path):
    """Validate that a parser produces the expected output for a given input."""
    template_path = TEMPLATES_DIR / f"{parser_name}.textfsm"
    assert template_path.exists(), f"Template not found: {template_path}"

    from netgraphy.ingestion.parsers import TextFSMParser

    with open(template_path) as f:
        parser = TextFSMParser(parser_name, f.read())

    raw_input = input_file.read_text()
    expected = json.loads(expected_file.read_text())

    result = parser.parse(raw_input)

    assert result == expected, (
        f"Parser {parser_name} output mismatch for {input_file.name}.\n"
        f"Got: {json.dumps(result, indent=2)}\n"
        f"Expected: {json.dumps(expected, indent=2)}"
    )
```

**CI enforcement** (in `.github/workflows/ci.yml` or equivalent):

```yaml
- name: Run parser tests
  run: |
    pytest tests/parsers/ -v --tb=short
```

---

## 10. Jobs Architecture

### 10.1 Job Framework Overview

Jobs are the primary unit of automation work in NetGraphy. They cover collection, parsing,
compliance checks, remediation, report generation, and any custom logic that operates
on or mutates the graph.

Key design principles:

- **Manifest-driven:** Every job is declared in YAML with typed parameters, scheduling,
  permissions, and resource requirements. The manifest is the contract.
- **Worker-isolated:** Jobs execute on worker processes, never on the API server. This
  prevents runaway jobs from affecting API availability.
- **Language-flexible:** Python (via Celery) and Go (via a custom worker binary) are
  both first-class runtimes.
- **Observable:** Every job execution produces structured logs, progress updates, and
  artifacts. All are queryable.
- **Replayable:** Job runs are recorded with full parameters, so any run can be re-triggered
  with identical or modified inputs.

### 10.2 Job Manifest Format

```yaml
kind: Job
version: v1
metadata:
  name: collect_device_facts
  display_name: "Collect Device Facts"
  description: "Collect base facts from network devices via SSH/NETCONF"
  author: "netgraphy"
  tags: [collection, discovery]

runtime: python
entrypoint: jobs.python.collect_device_facts:run

parameters:
  target_query:
    type: cypher
    description: "Cypher query to select target devices"
    default: "MATCH (d:Device {status: 'active'}) RETURN d"
    required: true
  command_bundle:
    type: string
    description: "Command bundle to execute"
    default: "cisco_ios_base"
    required: true
  dry_run:
    type: boolean
    description: "If true, show what would be collected without executing"
    default: false
  max_devices:
    type: integer
    description: "Maximum number of devices to collect from (0 = unlimited)"
    default: 0
    min: 0

schedule:
  enabled: false
  cron: "0 */6 * * *"  # Every 6 hours when enabled
  timezone: "UTC"

execution:
  timeout_seconds: 3600
  max_retries: 2
  retry_delay_seconds: 60
  concurrency_limit: 50       # Max concurrent device connections
  priority: 5                 # 1 (highest) to 10 (lowest)

secrets:
  - NETWORK_USERNAME
  - NETWORK_PASSWORD
  - NETWORK_ENABLE_SECRET

permissions:
  required_role: operator
  required_permissions:
    - "execute:job:collect_device_facts"
    - "read:node:Device"
    - "write:node:Device"
    - "write:node:Interface"
    - "write:edge:HAS_INTERFACE"

artifacts:
  - name: collection_report
    type: json
    description: "Per-device collection results"
  - name: error_log
    type: text
    description: "Detailed error log for failed devices"
```

**Job manifest database schema:**

```sql
CREATE TABLE job_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(500),
    description TEXT,
    runtime VARCHAR(20) NOT NULL CHECK (runtime IN ('python', 'go')),
    entrypoint VARCHAR(500) NOT NULL,
    manifest JSONB NOT NULL,            -- Full YAML manifest as JSON
    active BOOLEAN DEFAULT true,
    managed_by VARCHAR(255) DEFAULT 'local',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE job_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name VARCHAR(255) NOT NULL REFERENCES job_definitions(name),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- pending, queued, running, success, failure, timeout, cancelled
    triggered_by VARCHAR(255) NOT NULL,  -- user ID, "schedule", "webhook", "api"
    parameters JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    timeout_at TIMESTAMPTZ,
    worker_id VARCHAR(255),
    progress_pct FLOAT DEFAULT 0,
    progress_message TEXT,
    summary JSONB,                       -- Job-defined summary data
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    parent_execution_id UUID,            -- For retries
    correlation_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_job_exec_status ON job_executions(status);
CREATE INDEX idx_job_exec_name ON job_executions(job_name);
CREATE INDEX idx_job_exec_created ON job_executions(created_at DESC);

CREATE TABLE job_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES job_executions(id),
    name VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    storage_key VARCHAR(500) NOT NULL,   -- MinIO object key
    size_bytes BIGINT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE job_logs (
    id BIGSERIAL PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES job_executions(id),
    timestamp TIMESTAMPTZ DEFAULT now(),
    level VARCHAR(20) NOT NULL,          -- debug, info, warning, error
    message TEXT NOT NULL,
    metadata JSONB,
    CONSTRAINT fk_execution FOREIGN KEY (execution_id) REFERENCES job_executions(id)
);

CREATE INDEX idx_job_logs_exec ON job_logs(execution_id, timestamp);
```

### 10.3 Python Job Interface

```python
# packages/netgraphy-jobs-sdk/netgraphy/jobs/sdk.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID
import structlog

@dataclass
class JobContext:
    """Injected context available to every Python job."""

    # Validated parameters from the job manifest
    params: dict[str, Any]

    # Graph repository for Cypher execution
    graph: "GraphRepository"

    # Structured logger bound to this execution
    logger: structlog.BoundLogger

    # Secrets injected from the vault (only those declared in manifest)
    secrets: dict[str, str]

    # Artifact storage helper
    artifacts: "ArtifactHelper"

    # Progress reporting
    progress: "ProgressReporter"

    # Job execution metadata
    execution_id: UUID
    job_name: str
    triggered_by: str
    started_at: datetime

    # Raw output storage (for collection jobs)
    raw_store: "RawOutputStore"

    # Event bus for emitting events
    events: "EventBus"


@dataclass
class JobResult:
    status: str  # "success" or "failure"
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ProgressReporter:
    """Reports job progress to the API/database."""

    def __init__(self, execution_id: UUID, db_session):
        self._execution_id = execution_id
        self._db = db_session

    async def update(self, pct: float, message: str = ""):
        await self._db.execute(
            """UPDATE job_executions
               SET progress_pct = :pct, progress_message = :msg
               WHERE id = :id""",
            {"pct": pct, "msg": message, "id": self._execution_id},
        )

    async def increment(self, completed: int, total: int, message: str = ""):
        pct = (completed / total * 100) if total > 0 else 0
        await self.update(pct, message)


class ArtifactHelper:
    """Stores job artifacts in MinIO."""

    BUCKET = "netgraphy-job-artifacts"

    def __init__(self, execution_id: UUID, minio_client, db_session):
        self._execution_id = execution_id
        self._minio = minio_client
        self._db = db_session

    async def store(self, name: str, data: bytes | str, content_type: str = "application/json"):
        if isinstance(data, str):
            data = data.encode("utf-8")
        key = f"artifacts/{self._execution_id}/{name}"

        from io import BytesIO
        await self._minio.put_object(
            self.BUCKET, key, BytesIO(data), length=len(data), content_type=content_type
        )

        await self._db.execute(
            """INSERT INTO job_artifacts (execution_id, name, content_type, storage_key, size_bytes)
               VALUES (:exec_id, :name, :ct, :key, :size)""",
            {
                "exec_id": self._execution_id,
                "name": name,
                "ct": content_type,
                "key": key,
                "size": len(data),
            },
        )
```

**Example collection job:** `jobs/python/collect_device_facts.py`

```python
import json
from nornir import InitNornir
from nornir.core.task import Task, Result
from nornir_netmiko.tasks import netmiko_send_command
from netgraphy.jobs.sdk import JobContext, JobResult

async def run(ctx: JobContext) -> JobResult:
    # 1. Query graph for target devices
    devices = await ctx.graph.execute_cypher(ctx.params["target_query"], {})

    if not devices:
        return JobResult(status="success", summary={"message": "No devices matched query"})

    max_devices = ctx.params.get("max_devices", 0)
    if max_devices > 0:
        devices = devices[:max_devices]

    ctx.logger.info("collection.starting", device_count=len(devices))

    # 2. Load command bundle
    bundle_name = ctx.params["command_bundle"]
    bundle = await ctx.bundle_registry.get(bundle_name)

    # 3. Build Nornir inventory from graph results
    nr = _build_nornir(devices, ctx.secrets)

    if ctx.params.get("dry_run", False):
        return JobResult(
            status="success",
            summary={
                "dry_run": True,
                "devices": [d["hostname"] for d in devices],
                "commands": [c.command for c in bundle.commands],
            },
        )

    # 4. Collect from all devices
    results = {"success": [], "failed": []}

    for i, device in enumerate(devices):
        hostname = device["hostname"]
        try:
            device_results = nr.filter(name=hostname).run(
                task=_collect_commands,
                bundle=bundle,
            )

            if device_results[hostname].failed:
                results["failed"].append({
                    "hostname": hostname,
                    "error": str(device_results[hostname].exception),
                })
                continue

            # 5. Feed raw outputs into ingestion pipeline
            raw_outputs = device_results[hostname].result
            from netgraphy.ingestion.pipeline import IngestionContext
            ing_ctx = IngestionContext(
                job_run_id=ctx.execution_id,
                device_id=device["id"],
                device_hostname=hostname,
                collected_at=device_results[hostname].changed_at,
                command_bundle=bundle_name,
            )
            await ctx.ingestion_pipeline.ingest(ing_ctx, raw_outputs, bundle)

            results["success"].append(hostname)

        except Exception as e:
            ctx.logger.error("collection.device_failed", hostname=hostname, error=str(e))
            results["failed"].append({"hostname": hostname, "error": str(e)})

        await ctx.progress.increment(i + 1, len(devices), f"Collected {hostname}")

    # 6. Store summary artifact
    await ctx.artifacts.store(
        "collection_report",
        json.dumps(results, indent=2),
        content_type="application/json",
    )

    status = "success" if not results["failed"] else "failure"
    return JobResult(status=status, summary={
        "total": len(devices),
        "success": len(results["success"]),
        "failed": len(results["failed"]),
    })


def _collect_commands(task: Task, bundle) -> Result:
    """Nornir task: run all commands in a bundle against a device."""
    outputs = []
    for cmd in bundle.commands:
        result = task.run(
            task=netmiko_send_command,
            command_string=cmd.command,
            read_timeout=cmd.timeout_seconds,
        )
        from netgraphy.ingestion.pipeline import RawOutput
        from datetime import datetime
        outputs.append(RawOutput(
            command=cmd.command,
            output=result.result,
            storage_key="",  # Assigned during ingestion
            collected_at=datetime.utcnow(),
            exit_code=0,
        ))
    return Result(host=task.host, result=outputs)


def _build_nornir(devices: list[dict], secrets: dict):
    """Build a Nornir instance from graph device data."""
    inventory_data = {
        "hosts": {},
        "defaults": {
            "username": secrets["NETWORK_USERNAME"],
            "password": secrets["NETWORK_PASSWORD"],
            "connection_options": {
                "netmiko": {
                    "extras": {
                        "secret": secrets.get("NETWORK_ENABLE_SECRET", ""),
                    }
                }
            },
        },
    }

    for device in devices:
        inventory_data["hosts"][device["hostname"]] = {
            "hostname": device.get("management_ip", device["hostname"]),
            "platform": device.get("platform", "cisco_ios"),
            "data": {
                "id": device["id"],
                "site": device.get("site"),
                "role": device.get("role"),
            },
        }

    return InitNornir(
        inventory={
            "plugin": "DictInventory",
            "options": {"hosts": inventory_data["hosts"], "defaults": inventory_data["defaults"]},
        },
        runner={"plugin": "threaded", "options": {"num_workers": 50}},
    )
```

### 10.4 Go Job Interface

Go jobs are compiled into the worker binary and registered at startup.

```go
// packages/netgraphy-jobs-sdk-go/sdk.go
package sdk

import (
    "context"
    "log/slog"
    "time"

    "github.com/google/uuid"
)

// JobContext provides all dependencies a job needs.
type JobContext struct {
    Ctx          context.Context
    Params       map[string]interface{}
    Graph        GraphClient
    Logger       *slog.Logger
    Secrets      map[string]string
    Artifacts    ArtifactHelper
    Progress     ProgressReporter
    ExecutionID  uuid.UUID
    JobName      string
    TriggeredBy  string
    StartedAt    time.Time
}

// JobResult is the return value from a job execution.
type JobResult struct {
    Status  string                 `json:"status"` // "success" or "failure"
    Summary map[string]interface{} `json:"summary"`
    Error   string                 `json:"error,omitempty"`
}

// JobFunc is the signature every Go job must implement.
type JobFunc func(ctx *JobContext) (*JobResult, error)

// GraphClient provides access to the Neo4j graph.
type GraphClient interface {
    ExecuteCypher(ctx context.Context, query string, params map[string]interface{}) ([]map[string]interface{}, error)
    ExecuteMutations(ctx context.Context, mutations []GraphMutation) error
}

// ProgressReporter reports execution progress.
type ProgressReporter interface {
    Update(ctx context.Context, pct float64, message string) error
}

// ArtifactHelper stores job artifacts.
type ArtifactHelper interface {
    Store(ctx context.Context, name string, data []byte, contentType string) error
}
```

**Go job registration:**

```go
// apps/worker-go/main.go
package main

import (
    "github.com/org/netgraphy/apps/worker-go/jobs"
    sdk "github.com/org/netgraphy/packages/netgraphy-jobs-sdk-go"
)

var registry = map[string]sdk.JobFunc{
    "compliance_check":     jobs.ComplianceCheck,
    "topology_calculation": jobs.TopologyCalculation,
    "config_backup":        jobs.ConfigBackup,
}

func main() {
    worker := NewWorker(registry)
    worker.Start()
}
```

**Example Go job:**

```go
// apps/worker-go/jobs/compliance_check.go
package jobs

import (
    "fmt"

    sdk "github.com/org/netgraphy/packages/netgraphy-jobs-sdk-go"
)

func ComplianceCheck(ctx *sdk.JobContext) (*sdk.JobResult, error) {
    policyName := ctx.Params["policy"].(string)

    ctx.Logger.Info("compliance check starting", "policy", policyName)

    // Query devices that should comply with this policy
    devices, err := ctx.Graph.ExecuteCypher(ctx.Ctx,
        "MATCH (d:Device)-[:IN_SITE]->(s:Site) WHERE d.status = 'active' RETURN d, s", nil)
    if err != nil {
        return nil, fmt.Errorf("failed to query devices: %w", err)
    }

    violations := 0
    for i, device := range devices {
        // Run compliance checks...
        // ...

        ctx.Progress.Update(ctx.Ctx, float64(i+1)/float64(len(devices))*100,
            fmt.Sprintf("Checked %d/%d devices", i+1, len(devices)))
    }

    return &sdk.JobResult{
        Status: "success",
        Summary: map[string]interface{}{
            "devices_checked": len(devices),
            "violations":      violations,
        },
    }, nil
}
```

### 10.5 Worker Architecture

Workers are separate processes that consume tasks from a queue and execute jobs. They
are horizontally scalable and packaged as OCI container images.

**Python workers** use Celery with Redis as the broker:

```python
# apps/worker/celery_app.py
from celery import Celery

app = Celery(
    "netgraphy-worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/1",
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Concurrency: one process per worker, async within
    worker_concurrency=4,
    worker_prefetch_multiplier=1,

    # Task routing
    task_routes={
        "netgraphy.worker.tasks.execute_python_job": {"queue": "python-jobs"},
        "netgraphy.worker.tasks.execute_ingestion": {"queue": "ingestion"},
    },

    # Timeouts
    task_soft_time_limit=3600,  # 1 hour soft limit
    task_time_limit=3900,       # 1 hour 5 min hard limit (allows graceful shutdown)

    # Retry policy
    task_acks_late=True,         # Acknowledge after completion, not receipt
    worker_reject_on_worker_lost=True,  # Requeue if worker crashes
)


@app.task(bind=True, max_retries=2, default_retry_delay=60)
def execute_python_job(self, execution_id: str, job_name: str, params: dict):
    """Celery task that wraps Python job execution."""
    import asyncio
    asyncio.run(_run_job(self, execution_id, job_name, params))


async def _run_job(task, execution_id: str, job_name: str, params: dict):
    from uuid import UUID
    from netgraphy.worker.executor import JobExecutor

    executor = JobExecutor()
    try:
        await executor.execute(
            execution_id=UUID(execution_id),
            job_name=job_name,
            params=params,
        )
    except Exception as exc:
        # Update execution status to failure
        await executor.mark_failed(UUID(execution_id), str(exc))
        raise task.retry(exc=exc)
```

**Job executor** (shared by both dispatch paths):

```python
# apps/worker/netgraphy/worker/executor.py
import importlib
from uuid import UUID
from datetime import datetime
import structlog

class JobExecutor:
    """Loads and runs a job, managing lifecycle and context injection."""

    def __init__(self):
        self._db = ...       # Database session factory
        self._graph = ...    # GraphRepository
        self._minio = ...    # MinIO client
        self._event_bus = ...  # NATS event bus

    async def execute(self, execution_id: UUID, job_name: str, params: dict):
        # 1. Load job definition
        job_def = await self._load_job_definition(job_name)

        # 2. Update execution status to running
        await self._update_status(execution_id, "running", started_at=datetime.utcnow())

        # 3. Resolve secrets
        secrets = await self._resolve_secrets(job_def.get("secrets", []))

        # 4. Build context
        logger = structlog.get_logger().bind(
            job_name=job_name,
            execution_id=str(execution_id),
        )
        ctx = JobContext(
            params=params,
            graph=self._graph,
            logger=logger,
            secrets=secrets,
            artifacts=ArtifactHelper(execution_id, self._minio, self._db),
            progress=ProgressReporter(execution_id, self._db),
            execution_id=execution_id,
            job_name=job_name,
            triggered_by="worker",
            started_at=datetime.utcnow(),
            raw_store=RawOutputStore(self._minio),
            events=self._event_bus,
        )

        # 5. Import and execute the entrypoint
        module_path, func_name = job_def["entrypoint"].rsplit(":", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)

        result = await func(ctx)

        # 6. Update execution with result
        await self._update_status(
            execution_id,
            result.status,
            completed_at=datetime.utcnow(),
            summary=result.summary,
            error_message=result.error,
        )

        # 7. Emit event
        await self._event_bus.publish("job.completed", {
            "execution_id": str(execution_id),
            "job_name": job_name,
            "status": result.status,
            "summary": result.summary,
        })
```

**Go workers** run a custom binary that polls Redis (or NATS JetStream) for tasks:

```go
// apps/worker-go/worker.go
package main

import (
    "context"
    "encoding/json"
    "log/slog"
    "os"
    "os/signal"
    "syscall"
    "time"

    "github.com/redis/go-redis/v9"
    sdk "github.com/org/netgraphy/packages/netgraphy-jobs-sdk-go"
)

type Worker struct {
    registry map[string]sdk.JobFunc
    redis    *redis.Client
    graph    sdk.GraphClient
    logger   *slog.Logger
}

func NewWorker(registry map[string]sdk.JobFunc) *Worker {
    rdb := redis.NewClient(&redis.Options{
        Addr: os.Getenv("REDIS_URL"),
    })
    return &Worker{
        registry: registry,
        redis:    rdb,
        logger:   slog.Default(),
    }
}

type TaskMessage struct {
    ExecutionID string                 `json:"execution_id"`
    JobName     string                 `json:"job_name"`
    Params      map[string]interface{} `json:"params"`
}

func (w *Worker) Start() {
    ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
    defer cancel()

    w.logger.Info("go worker starting", "registered_jobs", len(w.registry))

    for {
        select {
        case <-ctx.Done():
            w.logger.Info("worker shutting down")
            return
        default:
            // BRPOP blocks until a task is available (5s timeout for graceful shutdown check)
            result, err := w.redis.BRPop(ctx, 5*time.Second, "go-jobs").Result()
            if err != nil {
                continue // Timeout or context cancelled
            }

            var msg TaskMessage
            if err := json.Unmarshal([]byte(result[1]), &msg); err != nil {
                w.logger.Error("failed to unmarshal task", "error", err)
                continue
            }

            w.execute(ctx, msg)
        }
    }
}

func (w *Worker) execute(ctx context.Context, msg TaskMessage) {
    jobFunc, ok := w.registry[msg.JobName]
    if !ok {
        w.logger.Error("unknown job", "job_name", msg.JobName)
        return
    }

    jobCtx := &sdk.JobContext{
        Ctx:         ctx,
        Params:      msg.Params,
        Graph:       w.graph,
        Logger:      w.logger.With("job_name", msg.JobName, "execution_id", msg.ExecutionID),
        ExecutionID: uuid.MustParse(msg.ExecutionID),
        JobName:     msg.JobName,
        StartedAt:   time.Now(),
    }

    result, err := jobFunc(jobCtx)
    if err != nil {
        w.logger.Error("job failed", "error", err, "job_name", msg.JobName)
        // Update execution status to failure via API call
        return
    }

    w.logger.Info("job completed", "status", result.Status, "job_name", msg.JobName)
}
```

### 10.6 Job Execution Lifecycle

```
1. Trigger (manual / schedule / webhook / API)
        |
        v
2. Validate parameters against manifest schema
        |
        v
3. Create JobExecution record (status: "pending")
        |
        v
4. Dispatch task to queue
   - Python jobs -> Celery/Redis queue "python-jobs"
   - Go jobs -> Redis list "go-jobs"
   status -> "queued"
        |
        v
5. Worker picks up task
   status -> "running"
   started_at = now()
   timeout_at = now() + execution.timeout_seconds
        |
        v
6. Worker streams logs to job_logs table
   (via structured logger that writes to DB)
        |
        v
7. Worker reports progress updates
   (progress_pct, progress_message)
        |
        v
8. Job completes
   status -> "success" | "failure" | "timeout"
   completed_at = now()
   summary = {job-defined JSON}
        |
        v
9. Artifacts stored in MinIO
   (collection_report, error_log, etc.)
        |
        v
10. Event emitted to NATS
    "job.completed" with execution summary
    - Consumed by: UI WebSocket bridge, webhook dispatcher, dependent jobs
```

**Job dispatch API endpoint:**

```python
# apps/api/netgraphy/api/routes/jobs.py

@router.post("/jobs/{job_name}/execute", response_model=JobExecutionResponse)
async def execute_job(
    job_name: str,
    request: JobExecuteRequest,
    current_user: User = Depends(get_current_user),
    job_service: JobService = Depends(get_job_service),
):
    # 1. Load and validate job definition
    job_def = await job_service.get_definition(job_name)
    if not job_def:
        raise HTTPException(404, f"Job not found: {job_name}")

    # 2. Check permissions
    if not current_user.has_role(job_def.manifest["permissions"]["required_role"]):
        raise HTTPException(403, "Insufficient permissions")

    # 3. Validate parameters
    validated_params = job_service.validate_params(job_def, request.parameters)

    # 4. Create execution record
    execution = await job_service.create_execution(
        job_name=job_name,
        params=validated_params,
        triggered_by=current_user.id,
    )

    # 5. Dispatch to worker
    await job_service.dispatch(execution)

    return JobExecutionResponse(
        execution_id=execution.id,
        status="queued",
        job_name=job_name,
    )
```

**Timeout enforcement:**

```python
# apps/worker/netgraphy/worker/timeout.py
import asyncio
from datetime import datetime, timedelta

async def enforce_timeout(execution_id: UUID, timeout_seconds: int, db_session):
    """Background task that marks executions as timed out."""
    timeout_at = datetime.utcnow() + timedelta(seconds=timeout_seconds)
    await asyncio.sleep(timeout_seconds)

    # Check if still running
    row = await db_session.fetch_one(
        "SELECT status FROM job_executions WHERE id = :id",
        {"id": execution_id},
    )
    if row and row["status"] == "running":
        await db_session.execute(
            """UPDATE job_executions
               SET status = 'timeout', completed_at = now(), error_message = 'Execution timed out'
               WHERE id = :id AND status = 'running'""",
            {"id": execution_id},
        )
```

### 10.7 Nornir Integration (Python)

NetGraphy uses [Nornir](https://nornir.readthedocs.io/) as the primary network automation
framework for Python collection jobs. A custom inventory plugin builds the Nornir inventory
dynamically from graph queries.

**Custom Nornir inventory plugin:** `packages/netgraphy-nornir/netgraphy_nornir/inventory.py`

```python
from nornir.core.inventory import (
    Inventory, Host, Hosts, Group, Groups, Defaults, ConnectionOptions,
    ParentGroups,
)

class NornirGraphInventory:
    """Nornir inventory plugin that queries the NetGraphy graph for devices."""

    def __init__(
        self,
        graph_client,
        cypher_query: str = "MATCH (d:Device {status: 'active'}) RETURN d",
        username: str = "",
        password: str = "",
        enable_secret: str = "",
        platform_map: dict | None = None,
    ):
        self._graph = graph_client
        self._query = cypher_query
        self._username = username
        self._password = password
        self._enable_secret = enable_secret
        # Map NetGraphy platform names to Nornir/Netmiko platform strings
        self._platform_map = platform_map or {
            "cisco_ios": "cisco_ios",
            "cisco_nxos": "cisco_nxos",
            "cisco_iosxr": "cisco_xr",
            "arista_eos": "arista_eos",
            "juniper_junos": "juniper_junos",
            "paloalto_panos": "paloalto_panos",
        }

    def load(self) -> Inventory:
        import asyncio
        devices = asyncio.get_event_loop().run_until_complete(
            self._graph.execute_cypher(self._query, {})
        )

        hosts = Hosts()
        groups = Groups()
        defaults = Defaults(
            username=self._username,
            password=self._password,
            connection_options={
                "netmiko": ConnectionOptions(
                    extras={"secret": self._enable_secret},
                ),
            },
        )

        # Build groups from sites and roles
        seen_groups = set()
        for device in devices:
            d = device["d"]  # Node properties
            site = d.get("site", "unknown")
            role = d.get("role", "unknown")

            for group_name in [f"site_{site}", f"role_{role}"]:
                if group_name not in seen_groups:
                    groups[group_name] = Group(name=group_name)
                    seen_groups.add(group_name)

            platform = self._platform_map.get(d.get("platform", ""), d.get("platform", ""))

            hosts[d["hostname"]] = Host(
                name=d["hostname"],
                hostname=d.get("management_ip", d["hostname"]),
                platform=platform,
                groups=ParentGroups([groups[f"site_{site}"], groups[f"role_{role}"]]),
                data={
                    "id": d.get("id"),
                    "serial_number": d.get("serial_number"),
                    "site": site,
                    "role": role,
                    "model": d.get("hardware_model"),
                },
            )

        return Inventory(hosts=hosts, groups=groups, defaults=defaults)
```

**Usage in a job:**

```python
from nornir import InitNornir
from netgraphy_nornir.inventory import NornirGraphInventory

nr = InitNornir(
    inventory={
        "plugin": "NornirGraphInventory",
        "options": {
            "graph_client": ctx.graph,
            "cypher_query": ctx.params["target_query"],
            "username": ctx.secrets["NETWORK_USERNAME"],
            "password": ctx.secrets["NETWORK_PASSWORD"],
            "enable_secret": ctx.secrets.get("NETWORK_ENABLE_SECRET", ""),
        },
    },
    runner={"plugin": "threaded", "options": {"num_workers": ctx.params.get("concurrency", 50)}},
)
```

---

## 11. Git Sync Architecture

### 11.1 Content Domains

Git repositories can supply content for any of these domains:

| Domain     | Directory     | File Format             | Description                              |
|------------|---------------|-------------------------|------------------------------------------|
| `schemas`  | `schemas/`    | YAML                    | Node type and edge type definitions      |
| `helpers`  | `helpers/`    | YAML                    | Reference data (VLANs, sites, roles)     |
| `queries`  | `queries/`    | `.cypher` + YAML meta   | Saved Cypher queries                     |
| `parsers`  | `parsers/`    | `.textfsm` + YAML meta  | TextFSM templates and mappings           |
| `commands` | `commands/`   | YAML                    | Command bundle definitions               |
| `jobs`     | `jobs/`       | YAML + Python/Go        | Job manifests and implementation code    |

Each domain has its own validation schema, conflict resolution rules, and apply logic.

### 11.2 Repo Registration

Git sources are registered via the API and stored in the database.

**Registration payload:**

```yaml
kind: GitSource
metadata:
  name: core-schemas
  description: "Core NetGraphy schema definitions"

source:
  url: "https://github.com/org/netgraphy-content.git"
  branch: main
  auth:
    type: github_app    # or: token, ssh_key, deploy_key
    secret_ref: github-app-credentials

sync:
  mode: webhook         # or: polling
  poll_interval: 300    # seconds, if mode is polling
  auto_apply: false     # if false, creates SyncProposal for review

content:
  - domain: schemas
    path: schemas/
  - domain: helpers
    path: content/helpers/
  - domain: queries
    path: queries/
  - domain: parsers
    path: parsers/
```

**Database schema:**

```sql
CREATE TABLE git_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    url VARCHAR(1000) NOT NULL,
    branch VARCHAR(255) NOT NULL DEFAULT 'main',
    auth_type VARCHAR(50) NOT NULL,       -- "github_app", "token", "ssh_key", "deploy_key"
    auth_secret_ref VARCHAR(255),
    sync_mode VARCHAR(20) NOT NULL DEFAULT 'polling',  -- "webhook", "polling"
    poll_interval_seconds INTEGER DEFAULT 300,
    auto_apply BOOLEAN DEFAULT false,
    last_commit_sha VARCHAR(64),
    last_sync_at TIMESTAMPTZ,
    last_sync_status VARCHAR(50),         -- "success", "failure", "pending"
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE git_source_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_source_id UUID NOT NULL REFERENCES git_sources(id) ON DELETE CASCADE,
    domain VARCHAR(50) NOT NULL,
    path VARCHAR(500) NOT NULL,
    UNIQUE (git_source_id, domain, path)
);

CREATE TABLE sync_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_source_id UUID NOT NULL REFERENCES git_sources(id),
    commit_sha VARCHAR(64) NOT NULL,
    commit_message TEXT,
    commit_author VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- "pending", "approved", "rejected", "applied"
    changes JSONB NOT NULL,               -- Detailed diff of what will change
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMPTZ,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE sync_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_source_id UUID NOT NULL REFERENCES git_sources(id),
    commit_sha VARCHAR(64) NOT NULL,
    status VARCHAR(50) NOT NULL,
    changes_applied JSONB,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 11.3 Sync Process

**Sync engine implementation:** `apps/api/netgraphy/sync/engine.py`

```python
import tempfile
import subprocess
from pathlib import Path
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any
import yaml
import structlog

logger = structlog.get_logger()

@dataclass
class SyncChange:
    domain: str
    action: str       # "create", "update", "delete"
    file_path: str
    object_name: str
    diff: dict | None = None

@dataclass
class SyncResult:
    status: str
    commit_sha: str
    changes: list[SyncChange]
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


class GitSyncEngine:
    """Manages the full Git sync lifecycle."""

    def __init__(self, db_session, domain_handlers: dict[str, "DomainHandler"], event_bus):
        self._db = db_session
        self._handlers = domain_handlers
        self._event_bus = event_bus

    async def sync(self, source_id: UUID) -> SyncResult:
        start = datetime.utcnow()

        # 1. Load source configuration
        source = await self._load_source(source_id)
        log = logger.bind(source_name=source["name"])

        # 2. Clone or fetch repository
        repo_dir = await self._fetch_repo(source)
        new_sha = self._get_head_sha(repo_dir)

        if new_sha == source.get("last_commit_sha"):
            log.info("sync.no_changes", commit=new_sha)
            return SyncResult(status="no_changes", commit_sha=new_sha, changes=[])

        log.info("sync.starting", old_sha=source.get("last_commit_sha"), new_sha=new_sha)

        # 3. Identify changed files per domain
        all_changes: list[SyncChange] = []
        content_mappings = await self._load_content_mappings(source_id)

        for mapping in content_mappings:
            domain = mapping["domain"]
            path_prefix = mapping["path"]
            handler = self._handlers.get(domain)
            if not handler:
                log.warning("sync.unknown_domain", domain=domain)
                continue

            # Get files in this domain path
            domain_dir = Path(repo_dir) / path_prefix
            if not domain_dir.exists():
                continue

            changed_files = self._get_changed_files(
                repo_dir, source.get("last_commit_sha"), new_sha, path_prefix
            )

            # 4. Validate each changed file
            for file_info in changed_files:
                try:
                    file_path = Path(repo_dir) / file_info["path"]
                    if file_info["status"] == "deleted":
                        change = SyncChange(
                            domain=domain,
                            action="delete",
                            file_path=file_info["path"],
                            object_name=handler.path_to_name(file_info["path"]),
                        )
                    else:
                        content = file_path.read_text()
                        parsed = handler.parse(content)
                        handler.validate(parsed)

                        # Determine create vs update
                        exists = await handler.exists(parsed)
                        change = SyncChange(
                            domain=domain,
                            action="update" if exists else "create",
                            file_path=file_info["path"],
                            object_name=handler.get_name(parsed),
                            diff=handler.compute_diff(parsed) if exists else None,
                        )

                    all_changes.append(change)
                except Exception as e:
                    log.error("sync.validation_failed", file=file_info["path"], error=str(e))
                    all_changes.append(SyncChange(
                        domain=domain, action="error", file_path=file_info["path"],
                        object_name="", diff={"error": str(e)},
                    ))

        # 5. Check auto_apply setting
        if not source.get("auto_apply", False):
            # Create sync proposal for review
            proposal_id = await self._create_proposal(source_id, new_sha, all_changes)
            log.info("sync.proposal_created", proposal_id=str(proposal_id))
            return SyncResult(
                status="proposal_created",
                commit_sha=new_sha,
                changes=all_changes,
            )

        # 6. Apply changes transactionally per domain
        errors = []
        for domain, domain_changes in self._group_by_domain(all_changes).items():
            handler = self._handlers[domain]
            try:
                await handler.apply_batch(domain_changes, managed_by=f"git:{source['name']}")
            except Exception as e:
                errors.append(f"{domain}: {str(e)}")
                log.error("sync.apply_failed", domain=domain, error=str(e))

        # 7. Update source record
        status = "success" if not errors else "partial_failure"
        await self._db.execute(
            """UPDATE git_sources
               SET last_commit_sha = :sha, last_sync_at = now(), last_sync_status = :status
               WHERE id = :id""",
            {"sha": new_sha, "status": status, "id": source_id},
        )

        # 8. Record sync event
        duration_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        await self._record_sync_event(source_id, new_sha, status, all_changes, duration_ms)

        # 9. Emit event
        await self._event_bus.publish("sync.completed", {
            "source_name": source["name"],
            "commit_sha": new_sha,
            "status": status,
            "changes_count": len(all_changes),
        })

        return SyncResult(
            status=status, commit_sha=new_sha, changes=all_changes,
            errors=errors, duration_ms=duration_ms,
        )

    async def _fetch_repo(self, source: dict) -> str:
        """Clone or fetch the repository into a temporary directory."""
        repo_dir = tempfile.mkdtemp(prefix="netgraphy-sync-")
        auth_env = await self._build_auth_env(source)

        subprocess.run(
            ["git", "clone", "--depth=50", "--branch", source["branch"],
             source["url"], repo_dir],
            env=auth_env,
            check=True,
            capture_output=True,
            timeout=120,
        )
        return repo_dir

    def _get_changed_files(
        self, repo_dir: str, old_sha: str | None, new_sha: str, path_prefix: str
    ) -> list[dict]:
        """Get list of changed files between two commits, filtered by path prefix."""
        if old_sha is None:
            # First sync: all files are new
            cmd = ["git", "-C", repo_dir, "ls-tree", "-r", "--name-only", new_sha, path_prefix]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return [{"path": p, "status": "added"} for p in result.stdout.strip().split("\n") if p]

        cmd = [
            "git", "-C", repo_dir, "diff", "--name-status", old_sha, new_sha, "--", path_prefix
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        changes = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t", 1)
            status_map = {"A": "added", "M": "modified", "D": "deleted"}
            changes.append({
                "path": parts[1],
                "status": status_map.get(parts[0], "modified"),
            })
        return changes

    @staticmethod
    def _get_head_sha(repo_dir: str) -> str:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def _group_by_domain(self, changes: list[SyncChange]) -> dict[str, list[SyncChange]]:
        groups: dict[str, list[SyncChange]] = {}
        for change in changes:
            if change.action != "error":
                groups.setdefault(change.domain, []).append(change)
        return groups
```

**Domain handler interface:**

```python
# apps/api/netgraphy/sync/handlers.py
from abc import ABC, abstractmethod

class DomainHandler(ABC):
    """Base class for domain-specific sync handlers."""

    @abstractmethod
    def parse(self, content: str) -> dict:
        """Parse file content into a structured object."""
        ...

    @abstractmethod
    def validate(self, parsed: dict) -> None:
        """Validate parsed content. Raises ValueError on failure."""
        ...

    @abstractmethod
    async def exists(self, parsed: dict) -> bool:
        """Check if this object already exists in the system."""
        ...

    @abstractmethod
    def get_name(self, parsed: dict) -> str:
        """Extract the object name from parsed content."""
        ...

    @abstractmethod
    def path_to_name(self, path: str) -> str:
        """Convert a file path to an object name (for deletions)."""
        ...

    @abstractmethod
    def compute_diff(self, parsed: dict) -> dict | None:
        """Compute diff between parsed content and existing object."""
        ...

    @abstractmethod
    async def apply_batch(self, changes: list, managed_by: str) -> None:
        """Apply a batch of changes atomically."""
        ...


class SchemasDomainHandler(DomainHandler):
    """Handles sync of schema definitions (node types, edge types)."""

    def __init__(self, schema_registry):
        self._registry = schema_registry

    def parse(self, content: str) -> dict:
        import yaml
        return yaml.safe_load(content)

    def validate(self, parsed: dict) -> None:
        kind = parsed.get("kind")
        if kind not in ("NodeType", "EdgeType", "EnumType", "Mixin"):
            raise ValueError(f"Unknown schema kind: {kind}")
        if "metadata" not in parsed or "name" not in parsed["metadata"]:
            raise ValueError("Schema must have metadata.name")

    async def exists(self, parsed: dict) -> bool:
        name = parsed["metadata"]["name"]
        return await self._registry.type_exists(name)

    def get_name(self, parsed: dict) -> str:
        return parsed["metadata"]["name"]

    def path_to_name(self, path: str) -> str:
        # schemas/device.yaml -> "Device" (capitalize)
        from pathlib import Path
        return Path(path).stem

    def compute_diff(self, parsed: dict) -> dict | None:
        # Compare parsed schema with existing schema
        # Returns field-level diff
        ...

    async def apply_batch(self, changes: list, managed_by: str) -> None:
        for change in changes:
            if change.action == "delete":
                await self._registry.delete_type(change.object_name)
            else:
                # Re-parse the file content (stored in change metadata)
                await self._registry.upsert_type(
                    change.object_name,
                    change.diff,  # Full parsed content
                    managed_by=managed_by,
                )
```

### 11.4 Conflict Resolution

Git-synced content can conflict with locally managed content. The conflict resolution
strategy is configurable per Git source.

**Conflict resolution modes:**

| Mode               | Behavior                                                             |
|--------------------|----------------------------------------------------------------------|
| `overwrite_local`  | Git content always wins. Local modifications are overwritten.        |
| `skip_conflicts`   | If local content has been modified since last sync, skip that file.  |
| `create_conflicts` | Create conflict records in the database for manual resolution.       |

**Conflict detection:**

Every managed object has a `managed_by` field:

```sql
-- On any content table (schemas, parsers, queries, etc.)
managed_by VARCHAR(255) DEFAULT 'local'
-- Values: "local", "git:core-schemas", "git:custom-parsers"

-- Track local modifications to git-managed content
locally_modified BOOLEAN DEFAULT false
locally_modified_at TIMESTAMPTZ
locally_modified_by VARCHAR(255)
```

**Conflict resolution implementation:**

```python
async def resolve_conflict(
    self,
    change: SyncChange,
    existing: dict,
    mode: str,
    source_name: str,
) -> str:
    """Returns: 'apply', 'skip', or 'conflict'."""
    managed_by = existing.get("managed_by", "local")
    locally_modified = existing.get("locally_modified", False)

    # Content managed by this same git source: always apply
    if managed_by == f"git:{source_name}":
        if not locally_modified:
            return "apply"

    # Content managed locally or by another source
    if mode == "overwrite_local":
        return "apply"
    elif mode == "skip_conflicts":
        if locally_modified or managed_by == "local":
            return "skip"
        return "apply"
    elif mode == "create_conflicts":
        if locally_modified or managed_by == "local":
            # Create conflict record
            await self._create_conflict_record(change, existing, source_name)
            return "conflict"
        return "apply"

    return "skip"  # Default safe behavior
```

**Conflict records:**

```sql
CREATE TABLE sync_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_source_id UUID NOT NULL REFERENCES git_sources(id),
    domain VARCHAR(50) NOT NULL,
    object_name VARCHAR(255) NOT NULL,
    local_content JSONB NOT NULL,
    remote_content JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'unresolved',  -- "unresolved", "resolved_local", "resolved_remote"
    resolved_by VARCHAR(255),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 11.5 Export to Git

Content can be exported from NetGraphy back to a Git repository, enabling a bidirectional
workflow where operators create queries or helper data in the UI and then persist them
to version control.

**Export API:**

```python
# apps/api/netgraphy/api/routes/sync.py

@router.post("/sync/export")
async def export_to_git(
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    sync_service: SyncService = Depends(get_sync_service),
):
    """Export content to a Git repository, optionally opening a PR."""
    # request.content_ids: list of content objects to export
    # request.target_repo: Git source name to export to
    # request.branch: branch name for the export (default: auto-generated)
    # request.open_pr: whether to open a PR

    result = await sync_service.export(
        content_ids=request.content_ids,
        target_source=request.target_repo,
        branch=request.branch or f"netgraphy-export/{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        open_pr=request.open_pr,
        author=current_user.display_name,
    )

    return {"status": "success", "branch": result.branch, "pr_url": result.pr_url}
```

**Export engine:**

```python
class GitExportEngine:
    """Exports content from NetGraphy to a Git repository."""

    async def export(
        self,
        content_ids: list[str],
        target_source: dict,
        branch: str,
        open_pr: bool,
        author: str,
    ) -> "ExportResult":
        # 1. Clone the target repo
        repo_dir = await self._clone_repo(target_source)

        # 2. Create a new branch
        subprocess.run(
            ["git", "-C", repo_dir, "checkout", "-b", branch],
            check=True, capture_output=True,
        )

        # 3. Write content files
        for content_id in content_ids:
            content = await self._load_content(content_id)
            file_path = self._content_to_path(content, target_source)
            full_path = Path(repo_dir) / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(self._serialize(content))

        # 4. Commit
        subprocess.run(["git", "-C", repo_dir, "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", repo_dir, "commit", "-m",
             f"Export from NetGraphy by {author}"],
            check=True, capture_output=True,
        )

        # 5. Push
        auth_env = await self._build_auth_env(target_source)
        subprocess.run(
            ["git", "-C", repo_dir, "push", "origin", branch],
            env=auth_env, check=True, capture_output=True,
        )

        # 6. Optionally open PR
        pr_url = None
        if open_pr:
            pr_url = await self._create_pull_request(target_source, branch, content_ids)

        return ExportResult(branch=branch, pr_url=pr_url)
```

---

## 12. Security/RBAC/Audit Architecture

### 12.1 Authentication

NetGraphy supports multiple authentication mechanisms, layered to support everything
from local development to enterprise SSO.

**Authentication flow:**

```
Client Request
      |
      v
  API Gateway / FastAPI middleware
      |
      +-- Authorization: Bearer <JWT>  --> JWT validation
      |
      +-- Authorization: Token <api_token> --> API token lookup
      |
      +-- No auth header --> 401 Unauthorized
      |
      v
  User context injected into request
```

**Supported authentication methods:**

| Method           | Use Case                        | Token Type      | Lifetime        |
|------------------|---------------------------------|-----------------|-----------------|
| Local password   | Dev, small deployments          | JWT             | Configurable    |
| OIDC/OAuth2      | Okta, Azure AD, Keycloak        | JWT (from IdP)  | Per IdP config  |
| SAML 2.0         | Future -- enterprise SSO        | JWT (post-SAML) | Per IdP config  |
| API tokens       | Automation, CI/CD, service-to-service | Opaque token | Long-lived      |

**Authentication implementation:** `apps/api/netgraphy/auth/authentication.py`

```python
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import bcrypt
from pydantic import BaseModel

# Configuration
JWT_SECRET = "..."  # Loaded from env/vault
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7

security = HTTPBearer(auto_error=False)

class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AuthService:
    def __init__(self, db_session, oidc_client=None):
        self._db = db_session
        self._oidc = oidc_client

    # --- Local Authentication ---

    async def authenticate_local(self, username: str, password: str) -> TokenPair:
        user = await self._db.fetch_one(
            "SELECT id, username, password_hash, active FROM users WHERE username = :u",
            {"u": username},
        )
        if not user or not user["active"]:
            raise HTTPException(401, "Invalid credentials")

        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            raise HTTPException(401, "Invalid credentials")

        return self._create_token_pair(user["id"], user["username"])

    # --- OIDC Authentication ---

    async def authenticate_oidc(self, code: str, redirect_uri: str) -> TokenPair:
        """Exchange OIDC authorization code for tokens."""
        oidc_tokens = await self._oidc.exchange_code(code, redirect_uri)
        id_token = self._oidc.decode_id_token(oidc_tokens["id_token"])

        # Find or create user from OIDC claims
        email = id_token["email"]
        user = await self._db.fetch_one(
            "SELECT id, username, active FROM users WHERE email = :email",
            {"email": email},
        )

        if not user:
            # Auto-provision user from OIDC
            user_id = uuid4()
            await self._db.execute(
                """INSERT INTO users (id, username, email, display_name, auth_provider, active)
                   VALUES (:id, :username, :email, :display_name, 'oidc', true)""",
                {
                    "id": user_id,
                    "username": email.split("@")[0],
                    "email": email,
                    "display_name": id_token.get("name", email),
                },
            )
            # Assign default role
            await self._assign_default_role(user_id)
            username = email.split("@")[0]
        else:
            if not user["active"]:
                raise HTTPException(403, "Account disabled")
            user_id = user["id"]
            username = user["username"]

        return self._create_token_pair(user_id, username)

    # --- API Token Authentication ---

    async def validate_api_token(self, token: str) -> dict:
        """Validate a long-lived API token."""
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        row = await self._db.fetch_one(
            """SELECT t.id, t.user_id, t.scopes, t.expires_at, u.username, u.active
               FROM api_tokens t JOIN users u ON t.user_id = u.id
               WHERE t.token_hash = :hash AND t.revoked = false""",
            {"hash": token_hash},
        )
        if not row:
            raise HTTPException(401, "Invalid API token")
        if not row["active"]:
            raise HTTPException(403, "Account disabled")
        if row["expires_at"] and row["expires_at"] < datetime.utcnow():
            raise HTTPException(401, "API token expired")

        # Update last_used
        await self._db.execute(
            "UPDATE api_tokens SET last_used_at = now() WHERE id = :id",
            {"id": row["id"]},
        )

        return {
            "user_id": row["user_id"],
            "username": row["username"],
            "scopes": row["scopes"],
        }

    # --- JWT Helpers ---

    def _create_token_pair(self, user_id: UUID, username: str) -> TokenPair:
        now = datetime.utcnow()
        access_exp = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        refresh_exp = now + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        access_payload = {
            "sub": str(user_id),
            "username": username,
            "type": "access",
            "iat": now,
            "exp": access_exp,
        }
        refresh_payload = {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": refresh_exp,
            "jti": str(uuid4()),  # Unique ID for refresh token revocation
        }

        return TokenPair(
            access_token=jwt.encode(access_payload, JWT_SECRET, JWT_ALGORITHM),
            refresh_token=jwt.encode(refresh_payload, JWT_SECRET, JWT_ALGORITHM),
            expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Issue new token pair from a valid refresh token."""
        try:
            payload = jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Refresh token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid refresh token")

        if payload.get("type") != "refresh":
            raise HTTPException(401, "Not a refresh token")

        # Check if refresh token has been revoked
        jti = payload["jti"]
        revoked = await self._db.fetch_one(
            "SELECT 1 FROM revoked_tokens WHERE jti = :jti", {"jti": jti}
        )
        if revoked:
            raise HTTPException(401, "Refresh token has been revoked")

        # Revoke the old refresh token (rotation)
        await self._db.execute(
            "INSERT INTO revoked_tokens (jti, revoked_at) VALUES (:jti, now())",
            {"jti": jti},
        )

        user = await self._db.fetch_one(
            "SELECT id, username, active FROM users WHERE id = :id",
            {"id": payload["sub"]},
        )
        if not user or not user["active"]:
            raise HTTPException(403, "Account disabled")

        return self._create_token_pair(user["id"], user["username"])


# --- FastAPI Dependency ---

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> "User":
    """Extract and validate the current user from the request."""
    auth_service: AuthService = request.app.state.auth_service

    if credentials is None:
        raise HTTPException(401, "Authentication required")

    scheme = credentials.scheme.lower()
    token = credentials.credentials

    if scheme == "bearer":
        # JWT access token
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            if payload.get("type") != "access":
                raise HTTPException(401, "Not an access token")
            return await _load_user(request.app.state.db, payload["sub"])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")

    elif scheme == "token":
        # API token
        token_data = await auth_service.validate_api_token(token)
        return await _load_user(request.app.state.db, token_data["user_id"])

    raise HTTPException(401, "Unsupported authentication scheme")
```

**Users and tokens database schema:**

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(500) UNIQUE,
    display_name VARCHAR(500),
    password_hash VARCHAR(255),            -- NULL for OIDC-only users
    auth_provider VARCHAR(50) DEFAULT 'local',  -- "local", "oidc", "saml"
    active BOOLEAN DEFAULT true,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    token_hash VARCHAR(255) UNIQUE NOT NULL,  -- SHA256 of token
    scopes JSONB DEFAULT '[]',
    expires_at TIMESTAMPTZ,
    revoked BOOLEAN DEFAULT false,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE revoked_tokens (
    jti VARCHAR(255) PRIMARY KEY,
    revoked_at TIMESTAMPTZ DEFAULT now()
);

-- Clean up expired revoked tokens periodically
CREATE INDEX idx_revoked_tokens_at ON revoked_tokens(revoked_at);
```

### 12.2 RBAC Model

NetGraphy uses a role-based access control model with granular, resource-scoped permissions.

**Roles:**

| Role         | Description                                              | Typical User           |
|--------------|----------------------------------------------------------|------------------------|
| `viewer`     | Read-only access to all graph data and queries           | NOC staff, auditors    |
| `editor`     | Create/update nodes, edges, run saved queries            | Network engineers      |
| `operator`   | Run jobs, trigger syncs, manage parsers                  | Automation engineers   |
| `admin`      | Manage users, roles, schema, system configuration        | Platform admins        |
| `superadmin` | Full access, multi-tenant admin                          | Platform owners        |

**Permission model:**

Permissions follow the pattern `{action}:{resource_type}:{resource_id}`, where resource_id
is optional (omitted means "all of this type").

```
read:node:Device              # Read any Device node
write:node:Device             # Create/update any Device node
delete:node:Device            # Delete any Device node
read:node:*                   # Read any node type
execute:query:*               # Execute any saved query
execute:query:find_orphans    # Execute a specific query
execute:cypher                # Execute arbitrary Cypher (dangerous, admin only)
execute:job:*                 # Execute any job
execute:job:collect_device_facts
manage:sync:*                 # Manage any Git source
manage:sync:core-schemas
manage:users                  # User management
manage:schema                 # Schema management
manage:system                 # System configuration
```

**Database schema:**

```sql
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    description TEXT,
    built_in BOOLEAN DEFAULT false,       -- true for system roles
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission VARCHAR(500) NOT NULL,     -- "read:node:Device"
    UNIQUE (role_id, permission)
);

CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

-- Seed built-in roles
INSERT INTO roles (name, display_name, built_in) VALUES
    ('viewer', 'Viewer', true),
    ('editor', 'Editor', true),
    ('operator', 'Operator', true),
    ('admin', 'Administrator', true),
    ('superadmin', 'Super Administrator', true);

-- Viewer permissions
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r, (VALUES
    ('read:node:*'),
    ('read:edge:*'),
    ('execute:query:*')
) AS p(perm)
WHERE r.name = 'viewer';

-- Editor inherits viewer + write
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r, (VALUES
    ('read:node:*'),
    ('read:edge:*'),
    ('write:node:*'),
    ('write:edge:*'),
    ('execute:query:*'),
    ('execute:cypher')
) AS p(perm)
WHERE r.name = 'editor';

-- Operator inherits editor + jobs + sync + parsers
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r, (VALUES
    ('read:node:*'),
    ('read:edge:*'),
    ('write:node:*'),
    ('write:edge:*'),
    ('execute:query:*'),
    ('execute:cypher'),
    ('execute:job:*'),
    ('manage:sync:*'),
    ('manage:parsers'),
    ('manage:commands')
) AS p(perm)
WHERE r.name = 'operator';

-- Admin inherits operator + management
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, p.perm
FROM roles r, (VALUES
    ('read:node:*'),
    ('read:edge:*'),
    ('write:node:*'),
    ('write:edge:*'),
    ('delete:node:*'),
    ('delete:edge:*'),
    ('execute:query:*'),
    ('execute:cypher'),
    ('execute:job:*'),
    ('manage:sync:*'),
    ('manage:parsers'),
    ('manage:commands'),
    ('manage:users'),
    ('manage:schema'),
    ('manage:system')
) AS p(perm)
WHERE r.name = 'admin';

-- Superadmin: wildcard
INSERT INTO role_permissions (role_id, permission)
SELECT r.id, '*'
FROM roles r
WHERE r.name = 'superadmin';
```

**Permission checking implementation:** `apps/api/netgraphy/auth/rbac.py`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class PermissionCheck:
    actor: "User"
    action: str             # read, write, delete, execute, manage
    resource_type: str      # node, edge, job, query, sync, users, schema, system
    resource_id: str | None = None
    field: str | None = None  # For field-level checks

class RBACService:
    def __init__(self, db_session):
        self._db = db_session
        self._cache: dict[str, set[str]] = {}  # user_id -> permissions

    async def check(self, perm: PermissionCheck) -> bool:
        """Check if an actor has a specific permission. Returns True/False."""
        permissions = await self._load_permissions(perm.actor.id)

        # Check wildcard (superadmin)
        if "*" in permissions:
            return True

        # Build permission strings to check, from most specific to least
        candidates = []

        if perm.resource_id:
            candidates.append(f"{perm.action}:{perm.resource_type}:{perm.resource_id}")
        candidates.append(f"{perm.action}:{perm.resource_type}:*")
        candidates.append(f"{perm.action}:{perm.resource_type}")

        # Field-level check
        if perm.field:
            if perm.resource_id:
                candidates.insert(0,
                    f"{perm.action}:{perm.resource_type}:{perm.resource_id}:{perm.field}")

        return any(c in permissions for c in candidates)

    async def enforce(self, perm: PermissionCheck) -> None:
        """Enforce a permission check. Raises HTTPException(403) on failure."""
        if not await self.check(perm):
            from fastapi import HTTPException
            raise HTTPException(
                403,
                f"Permission denied: {perm.action} on {perm.resource_type}"
                + (f"/{perm.resource_id}" if perm.resource_id else ""),
            )

    async def _load_permissions(self, user_id: str) -> set[str]:
        cache_key = str(user_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        rows = await self._db.fetch_all(
            """SELECT DISTINCT rp.permission
               FROM user_roles ur
               JOIN role_permissions rp ON ur.role_id = rp.role_id
               WHERE ur.user_id = :user_id""",
            {"user_id": user_id},
        )
        permissions = {row["permission"] for row in rows}
        self._cache[cache_key] = permissions
        return permissions

    def invalidate_cache(self, user_id: str | None = None):
        if user_id:
            self._cache.pop(str(user_id), None)
        else:
            self._cache.clear()
```

**RBAC enforcement in API routes:**

```python
@router.get("/nodes/{node_type}")
async def list_nodes(
    node_type: str,
    current_user: User = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac),
    graph: GraphRepository = Depends(get_graph),
):
    await rbac.enforce(PermissionCheck(
        actor=current_user,
        action="read",
        resource_type="node",
        resource_id=node_type,
    ))

    # Proceed with query...
    nodes = await graph.list_nodes(node_type)
    return nodes


@router.post("/nodes/{node_type}")
async def create_node(
    node_type: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    rbac: RBACService = Depends(get_rbac),
):
    await rbac.enforce(PermissionCheck(
        actor=current_user,
        action="write",
        resource_type="node",
        resource_id=node_type,
    ))

    # Field-level check for sensitive fields
    schema = await schema_registry.get_type(node_type)
    for field_name in body:
        field_def = schema.get_field(field_name)
        if field_def and field_def.get("sensitive"):
            await rbac.enforce(PermissionCheck(
                actor=current_user,
                action="write",
                resource_type="node",
                resource_id=node_type,
                field=field_name,
            ))

    # Proceed with creation...
```

### 12.3 Audit Model

Every state-changing operation produces an audit event. The audit log is the single
source of truth for "who did what, when."

**Audit event structure:**

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

@dataclass
class AuditEvent:
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    actor_id: str = ""              # User ID, "system", job execution ID
    actor_type: str = ""            # "user", "system", "job", "sync"
    action: str = ""                # "create", "update", "delete", "execute", "login", etc.
    resource_type: str = ""         # "node:Device", "edge:CONNECTED_TO", "job", "user"
    resource_id: str = ""           # Specific resource identifier
    changes: dict = field(default_factory=dict)  # {field: {old: x, new: y}} for updates
    metadata: dict = field(default_factory=dict)  # Additional context
    correlation_id: str = ""        # Trace through related operations
    ip_address: str = ""
    user_agent: str = ""
```

**Why PostgreSQL for audit storage, not Neo4j:**

The audit log is stored in a dedicated PostgreSQL table (the PostgreSQL sidecar) rather
than as Neo4j nodes. This is a deliberate architectural choice for several reasons:

1. **Query patterns are relational.** Audit queries are time-range scans, filtered by
   actor, action, or resource. These are `WHERE`/`ORDER BY`/`LIMIT` queries -- exactly
   what PostgreSQL is optimized for. Neo4j would require index scans on node properties
   with no benefit from graph traversal.

2. **Volume and retention.** Audit events accumulate rapidly (every API call, every
   graph mutation, every login). Millions of audit nodes would bloat the Neo4j database,
   increasing memory pressure and slowing unrelated graph queries. PostgreSQL handles
   append-heavy workloads with partitioning and efficient vacuuming.

3. **Separation of concerns.** The graph database contains the network model -- the
   "what is." Audit data is operational telemetry -- the "what happened." Mixing them
   pollutes the graph with non-domain data and makes both harder to reason about.

4. **Compliance tooling.** Audit data often needs to be exported to SIEM systems,
   compliance tools, or long-term archival. PostgreSQL's ecosystem for ETL, CDC
   (logical replication, Debezium), and export is mature. Neo4j's is not.

5. **Partitioning.** PostgreSQL supports native table partitioning by time range,
   enabling efficient retention policies (drop old partitions) without the overhead
   of bulk deletes.

**Audit storage schema:**

```sql
-- Partitioned by month for efficient retention management
CREATE TABLE audit_events (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id VARCHAR(255) NOT NULL,
    actor_type VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(255) NOT NULL,
    resource_id VARCHAR(500),
    changes JSONB,
    metadata JSONB,
    correlation_id VARCHAR(255),
    ip_address INET,
    user_agent TEXT,
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- Create partitions for current and next 3 months
CREATE TABLE audit_events_2026_03 PARTITION OF audit_events
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE audit_events_2026_04 PARTITION OF audit_events
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE audit_events_2026_05 PARTITION OF audit_events
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE audit_events_2026_06 PARTITION OF audit_events
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- Indexes on the parent table (automatically applied to partitions)
CREATE INDEX idx_audit_actor ON audit_events(actor_id, timestamp DESC);
CREATE INDEX idx_audit_resource ON audit_events(resource_type, resource_id, timestamp DESC);
CREATE INDEX idx_audit_action ON audit_events(action, timestamp DESC);
CREATE INDEX idx_audit_correlation ON audit_events(correlation_id) WHERE correlation_id IS NOT NULL;
```

**Audit middleware:** `apps/api/netgraphy/auth/audit.py`

```python
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from uuid import uuid4

logger = structlog.get_logger()

class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware that records audit events for state-changing requests."""

    AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):
        # Generate correlation ID for this request
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Only audit state-changing operations
        if request.method in self.AUDITED_METHODS and response.status_code < 500:
            try:
                await self._record_audit_event(request, response, correlation_id)
            except Exception as e:
                logger.error("audit.record_failed", error=str(e))

        return response

    async def _record_audit_event(self, request: Request, response, correlation_id: str):
        audit_data = getattr(request.state, "audit_data", None)
        if not audit_data:
            return  # Route did not set audit data

        user = getattr(request.state, "user", None)

        event = AuditEvent(
            actor_id=str(user.id) if user else "anonymous",
            actor_type="user" if user else "anonymous",
            action=audit_data.get("action", request.method.lower()),
            resource_type=audit_data.get("resource_type", ""),
            resource_id=audit_data.get("resource_id", ""),
            changes=audit_data.get("changes", {}),
            metadata=audit_data.get("metadata", {}),
            correlation_id=correlation_id,
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
        )

        db = request.app.state.audit_db
        await db.execute(
            """INSERT INTO audit_events
               (id, timestamp, actor_id, actor_type, action, resource_type,
                resource_id, changes, metadata, correlation_id, ip_address, user_agent)
               VALUES (:id, :ts, :actor_id, :actor_type, :action, :resource_type,
                       :resource_id, :changes, :metadata, :correlation_id,
                       :ip_address::inet, :user_agent)""",
            {
                "id": event.id,
                "ts": event.timestamp,
                "actor_id": event.actor_id,
                "actor_type": event.actor_type,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "changes": event.changes,
                "metadata": event.metadata,
                "correlation_id": event.correlation_id,
                "ip_address": event.ip_address or None,
                "user_agent": event.user_agent,
            },
        )
```

**Setting audit data from route handlers:**

```python
@router.put("/nodes/{node_type}/{node_id}")
async def update_node(
    node_type: str,
    node_id: str,
    body: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    # Compute changes
    existing = await graph.get_node(node_type, node_id)
    changes = {
        k: {"old": existing.get(k), "new": v}
        for k, v in body.items()
        if existing.get(k) != v
    }

    # Set audit data for middleware
    request.state.audit_data = {
        "action": "update",
        "resource_type": f"node:{node_type}",
        "resource_id": node_id,
        "changes": changes,
    }

    # Perform update
    await graph.update_node(node_type, node_id, body)
    return {"status": "updated"}
```

**Audit retention management** (runs as a scheduled job):

```python
async def run(ctx: JobContext) -> JobResult:
    """Drop audit partitions older than retention period."""
    retention_months = ctx.params.get("retention_months", 12)
    cutoff = datetime.utcnow() - timedelta(days=retention_months * 30)
    cutoff_partition = f"audit_events_{cutoff.strftime('%Y_%m')}"

    # List all partitions
    partitions = await ctx.audit_db.fetch_all(
        """SELECT tablename FROM pg_tables
           WHERE tablename LIKE 'audit_events_%'
           ORDER BY tablename"""
    )

    dropped = []
    for row in partitions:
        if row["tablename"] < cutoff_partition:
            await ctx.audit_db.execute(f"DROP TABLE IF EXISTS {row['tablename']}")
            dropped.append(row["tablename"])

    # Create future partitions (next 3 months)
    for i in range(1, 4):
        future = datetime.utcnow() + timedelta(days=30 * i)
        partition_name = f"audit_events_{future.strftime('%Y_%m')}"
        start = future.replace(day=1).strftime('%Y-%m-%d')
        end = (future.replace(day=1) + timedelta(days=32)).replace(day=1).strftime('%Y-%m-%d')
        await ctx.audit_db.execute(
            f"""CREATE TABLE IF NOT EXISTS {partition_name}
                PARTITION OF audit_events
                FOR VALUES FROM ('{start}') TO ('{end}')"""
        )

    return JobResult(status="success", summary={"dropped": dropped})
```

### 12.4 Multi-tenancy Strategy

**Phase 1 (current): single tenant.** One Neo4j database, one logical workspace.

**Phase 2 (future): label-prefix isolation.**

Each workspace gets a label prefix applied to all node types:

```
Workspace "acme":  (:acme_Device), (:acme_Interface), (:acme_Site)
Workspace "contoso": (:contoso_Device), (:contoso_Interface), (:contoso_Site)
```

This approach is recommended initially because:

- No infrastructure changes needed (single Neo4j instance)
- All Cypher queries automatically scoped by prefixing labels in the query builder
- RBAC extends naturally: permissions include workspace scope
- Cross-workspace queries are possible for superadmins
- Lower operational cost than multiple databases

**Query builder workspace scoping:**

```python
class WorkspaceScopedCypherBuilder:
    def __init__(self, workspace: str, inner_builder: "CypherBuilder"):
        self._ws = workspace
        self._inner = inner_builder

    def match_node(self, node_type: str, alias: str = "n") -> "CypherBuilder":
        prefixed = f"{self._ws}_{node_type}"
        return self._inner.match_node(prefixed, alias)
```

**Phase 3 (enterprise): database-per-tenant.**

Neo4j 4+ Enterprise supports multiple databases. Each tenant gets its own database:

```
neo4j> CREATE DATABASE acme;
neo4j> CREATE DATABASE contoso;
```

This provides:
- Complete data isolation (no prefix leaks)
- Independent backup and restore per tenant
- Per-tenant resource limits
- Required for regulatory compliance in some environments

The tradeoff is operational complexity: each database needs its own indexes, constraints,
and schema management. The API must route connections to the correct database based on
the authenticated user's workspace membership.

```python
# Connection routing for database-per-tenant
class TenantAwareGraphDriver:
    def __init__(self, neo4j_uri: str, auth):
        self._driver = neo4j.AsyncGraphDatabase.driver(neo4j_uri, auth=auth)

    def session(self, workspace: str):
        return self._driver.session(database=workspace)
```

**RBAC workspace integration:**

```sql
CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role_id UUID NOT NULL REFERENCES roles(id),
    PRIMARY KEY (workspace_id, user_id)
);
```

---

## 13. Performance/Scale/Operations

### 13.1 Indexing Strategy

Neo4j indexes are derived from the schema registry and managed automatically.

**Index generation from schema:**

```python
class IndexManager:
    """Manages Neo4j indexes and constraints based on schema definitions."""

    def __init__(self, driver: "neo4j.AsyncDriver"):
        self._driver = driver

    async def sync_indexes(self, schema_registry: "SchemaRegistry"):
        """Ensure Neo4j indexes match the current schema."""
        desired_indexes = self._compute_desired_indexes(schema_registry)
        current_indexes = await self._get_current_indexes()

        # Create missing indexes
        to_create = desired_indexes - current_indexes
        for idx in to_create:
            await self._create_index(idx)

        # Drop orphaned indexes (managed by NetGraphy only)
        to_drop = current_indexes - desired_indexes
        for idx in to_drop:
            if idx.startswith("ng_"):  # Only drop NetGraphy-managed indexes
                await self._drop_index(idx)

    def _compute_desired_indexes(self, registry) -> set:
        indexes = set()
        for type_name, type_def in registry.all_types().items():
            if type_def["kind"] != "NodeType":
                continue
            for field_name, field_def in type_def.get("attributes", {}).items():
                if field_def.get("unique"):
                    indexes.add(
                        f"CONSTRAINT ng_unique_{type_name}_{field_name} "
                        f"FOR (n:{type_name}) REQUIRE n.{field_name} IS UNIQUE"
                    )
                elif field_def.get("indexed"):
                    indexes.add(
                        f"INDEX ng_idx_{type_name}_{field_name} "
                        f"FOR (n:{type_name}) ON (n.{field_name})"
                    )

            # Composite indexes
            for comp_idx in type_def.get("composite_indexes", []):
                fields = ", ".join(f"n.{f}" for f in comp_idx["fields"])
                name = f"ng_comp_{type_name}_{'_'.join(comp_idx['fields'])}"
                indexes.add(f"INDEX {name} FOR (n:{type_name}) ON ({fields})")

            # Full-text indexes for search fields
            search_fields = [
                f for f, d in type_def.get("attributes", {}).items()
                if d.get("full_text_search")
            ]
            if search_fields:
                fields_str = ", ".join(f"n.{f}" for f in search_fields)
                indexes.add(
                    f"FULLTEXT INDEX ng_fts_{type_name} "
                    f"FOR (n:{type_name}) ON EACH [{fields_str}]"
                )

        return indexes

    async def _create_index(self, index_statement: str):
        async with self._driver.session() as session:
            if index_statement.startswith("CONSTRAINT"):
                await session.run(f"CREATE {index_statement} IF NOT EXISTS")
            else:
                await session.run(f"CREATE {index_statement} IF NOT EXISTS")

    async def _get_current_indexes(self) -> set:
        async with self._driver.session() as session:
            result = await session.run("SHOW INDEXES YIELD name RETURN name")
            return {record["name"] async for record in result if record["name"].startswith("ng_")}
```

**Example indexes generated from schema:**

```cypher
-- From Device node type
CREATE CONSTRAINT ng_unique_Device_hostname FOR (n:Device) REQUIRE n.hostname IS UNIQUE;
CREATE INDEX ng_idx_Device_status FOR (n:Device) ON (n.status);
CREATE INDEX ng_idx_Device_site FOR (n:Device) ON (n.site);
CREATE INDEX ng_comp_Device_platform_role FOR (n:Device) ON (n.platform, n.role);
CREATE FULLTEXT INDEX ng_fts_Device FOR (n:Device) ON EACH [n.hostname, n.description];

-- From Interface node type
CREATE CONSTRAINT ng_unique_Interface_device_hostname_name
    FOR (n:Interface) REQUIRE (n.device_hostname, n.name) IS UNIQUE;
CREATE INDEX ng_idx_Interface_status FOR (n:Interface) ON (n.status);
CREATE INDEX ng_idx_Interface_ip_address FOR (n:Interface) ON (n.ip_address);

-- From Site node type
CREATE CONSTRAINT ng_unique_Site_name FOR (n:Site) REQUIRE n.name IS UNIQUE;
CREATE INDEX ng_idx_Site_region FOR (n:Site) ON (n.region);
```

### 13.2 Caching

```python
# apps/api/netgraphy/cache/manager.py
import json
import hashlib
from datetime import timedelta
from redis.asyncio import Redis

class CacheManager:
    """Centralized cache manager using Redis."""

    def __init__(self, redis: Redis):
        self._redis = redis

    # --- Schema Cache ---
    # Schema definitions change infrequently and are read on every request.
    # Cache indefinitely; invalidate on schema.changed events.

    async def get_schema(self, type_name: str) -> dict | None:
        data = await self._redis.get(f"schema:{type_name}")
        return json.loads(data) if data else None

    async def set_schema(self, type_name: str, schema: dict):
        await self._redis.set(f"schema:{type_name}", json.dumps(schema))

    async def invalidate_schema(self, type_name: str | None = None):
        if type_name:
            await self._redis.delete(f"schema:{type_name}")
        else:
            # Invalidate all schemas
            keys = []
            async for key in self._redis.scan_iter("schema:*"):
                keys.append(key)
            if keys:
                await self._redis.delete(*keys)

    # --- Query Result Cache ---
    # Short TTL (30s). Invalidated on relevant mutations via NATS events.

    async def get_query_result(self, query_hash: str) -> list | None:
        data = await self._redis.get(f"query:{query_hash}")
        return json.loads(data) if data else None

    async def set_query_result(self, query_hash: str, result: list, ttl_seconds: int = 30):
        await self._redis.setex(
            f"query:{query_hash}", timedelta(seconds=ttl_seconds), json.dumps(result)
        )

    async def invalidate_queries_for_type(self, node_type: str):
        """Invalidate all cached queries that involve a given node type."""
        # Queries are tagged with the node types they reference
        keys = []
        async for key in self._redis.scan_iter(f"query:*"):
            tags = await self._redis.smembers(f"querytags:{key}")
            if node_type.encode() in tags:
                keys.append(key)
        if keys:
            await self._redis.delete(*keys)

    @staticmethod
    def hash_query(cypher: str, params: dict) -> str:
        content = f"{cypher}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # --- Session Cache ---

    async def get_session(self, session_id: str) -> dict | None:
        data = await self._redis.get(f"session:{session_id}")
        return json.loads(data) if data else None

    async def set_session(self, session_id: str, data: dict, ttl_seconds: int = 1800):
        await self._redis.setex(
            f"session:{session_id}", timedelta(seconds=ttl_seconds), json.dumps(data)
        )

    async def delete_session(self, session_id: str):
        await self._redis.delete(f"session:{session_id}")
```

**Cache invalidation via NATS events:**

```python
# apps/api/netgraphy/cache/invalidation.py
import nats

class CacheInvalidationSubscriber:
    """Subscribes to NATS events and invalidates relevant caches."""

    def __init__(self, cache: CacheManager, nats_client: nats.Client):
        self._cache = cache
        self._nc = nats_client

    async def start(self):
        await self._nc.subscribe("schema.changed", cb=self._on_schema_changed)
        await self._nc.subscribe("graph.node.mutated", cb=self._on_node_mutated)
        await self._nc.subscribe("graph.edge.mutated", cb=self._on_edge_mutated)

    async def _on_schema_changed(self, msg):
        data = json.loads(msg.data)
        type_name = data.get("type_name")
        await self._cache.invalidate_schema(type_name)

    async def _on_node_mutated(self, msg):
        data = json.loads(msg.data)
        await self._cache.invalidate_queries_for_type(data["node_type"])

    async def _on_edge_mutated(self, msg):
        data = json.loads(msg.data)
        await self._cache.invalidate_queries_for_type(data.get("source_type", ""))
        await self._cache.invalidate_queries_for_type(data.get("target_type", ""))
```

### 13.3 Bulk Operations

Large ingestion runs may upsert thousands of nodes and edges. Bulk operations use Neo4j
`UNWIND` for batched writes.

```python
class BulkGraphWriter:
    """Executes graph mutations in configurable batches."""

    DEFAULT_BATCH_SIZE = 1000

    def __init__(self, driver: "neo4j.AsyncDriver", batch_size: int = DEFAULT_BATCH_SIZE):
        self._driver = driver
        self._batch_size = batch_size

    async def bulk_upsert_nodes(
        self,
        node_type: str,
        match_keys: list[str],
        records: list[dict],
        on_progress: callable = None,
    ) -> int:
        """Upsert nodes in batches using UNWIND."""
        total = len(records)
        upserted = 0

        match_clause = ", ".join(f"{k}: row.{k}" for k in match_keys)
        set_clause = "SET n += row"

        cypher = f"""
            UNWIND $rows AS row
            MERGE (n:{node_type} {{{match_clause}}})
            {set_clause}
            SET n._updated_at = datetime()
            RETURN count(n) AS cnt
        """

        for batch_start in range(0, total, self._batch_size):
            batch = records[batch_start:batch_start + self._batch_size]
            async with self._driver.session() as session:
                result = await session.run(cypher, {"rows": batch})
                record = await result.single()
                upserted += record["cnt"]

            if on_progress:
                await on_progress(upserted, total)

        return upserted

    async def bulk_upsert_edges(
        self,
        edge_type: str,
        source_type: str,
        source_key: str,
        target_type: str,
        target_key: str,
        records: list[dict],
        on_progress: callable = None,
    ) -> int:
        """Upsert edges in batches using UNWIND."""
        total = len(records)
        upserted = 0

        cypher = f"""
            UNWIND $rows AS row
            MATCH (src:{source_type} {{{source_key}: row.source_id}})
            MATCH (tgt:{target_type} {{{target_key}: row.target_id}})
            MERGE (src)-[r:{edge_type}]->(tgt)
            SET r += row.attributes
            SET r._updated_at = datetime()
            RETURN count(r) AS cnt
        """

        for batch_start in range(0, total, self._batch_size):
            batch = records[batch_start:batch_start + self._batch_size]
            async with self._driver.session() as session:
                result = await session.run(cypher, {"rows": batch})
                record = await result.single()
                upserted += record["cnt"]

            if on_progress:
                await on_progress(upserted, total)

        return upserted
```

### 13.4 Observability

**Structured logging with structlog:**

```python
# apps/api/netgraphy/observability/logging.py
import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # In production: JSON output
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

**Correlation ID middleware:**

```python
from uuid import uuid4
import structlog

class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        structlog.contextvars.unbind_contextvars("correlation_id")
        return response
```

**Prometheus metrics:**

```python
# apps/api/netgraphy/observability/metrics.py
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest

REGISTRY = CollectorRegistry()

# Request metrics
REQUEST_COUNT = Counter(
    "netgraphy_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "netgraphy_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

# Neo4j metrics
CYPHER_QUERY_DURATION = Histogram(
    "netgraphy_cypher_query_duration_seconds",
    "Cypher query execution time",
    ["query_type"],  # "read", "write"
    buckets=[0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
    registry=REGISTRY,
)
CYPHER_QUERY_COUNT = Counter(
    "netgraphy_cypher_queries_total",
    "Total Cypher queries executed",
    ["query_type", "status"],
    registry=REGISTRY,
)

# Job metrics
JOB_DURATION = Histogram(
    "netgraphy_job_duration_seconds",
    "Job execution duration",
    ["job_name", "status"],
    buckets=[1, 5, 30, 60, 300, 600, 1800, 3600],
    registry=REGISTRY,
)
JOB_QUEUE_DEPTH = Gauge(
    "netgraphy_job_queue_depth",
    "Number of pending jobs in queue",
    ["queue_name"],
    registry=REGISTRY,
)

# Ingestion metrics
INGESTION_RECORDS = Counter(
    "netgraphy_ingestion_records_total",
    "Total records ingested",
    ["parser_name", "status"],
    registry=REGISTRY,
)
INGESTION_MUTATIONS = Counter(
    "netgraphy_ingestion_mutations_total",
    "Total graph mutations from ingestion",
    ["mutation_type"],
    registry=REGISTRY,
)

# Metrics endpoint
@router.get("/metrics")
async def metrics():
    from starlette.responses import Response
    return Response(
        generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
```

**OpenTelemetry tracing:**

```python
# apps/api/netgraphy/observability/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

def configure_tracing(app, service_name: str = "netgraphy-api"):
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Auto-instrument frameworks
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    # Custom Neo4j instrumentation (no auto-instrumentation available)
    return trace.get_tracer(service_name)
```

**Neo4j query tracing wrapper:**

```python
class TracedGraphRepository:
    """Wraps GraphRepository with OpenTelemetry spans."""

    def __init__(self, inner: "GraphRepository", tracer):
        self._inner = inner
        self._tracer = tracer

    async def execute_cypher(self, query: str, params: dict):
        with self._tracer.start_as_current_span("neo4j.query") as span:
            span.set_attribute("db.system", "neo4j")
            span.set_attribute("db.statement", query[:500])  # Truncate long queries
            span.set_attribute("db.operation", "read" if query.strip().upper().startswith("MATCH") else "write")

            start = time.monotonic()
            try:
                result = await self._inner.execute_cypher(query, params)
                duration = time.monotonic() - start
                CYPHER_QUERY_DURATION.labels(
                    query_type="read" if query.strip().upper().startswith("MATCH") else "write"
                ).observe(duration)
                span.set_attribute("db.result_count", len(result))
                return result
            except Exception as e:
                span.set_status(StatusCode.ERROR, str(e))
                CYPHER_QUERY_COUNT.labels(query_type="read", status="error").inc()
                raise
```

**Health endpoints:**

```python
# apps/api/netgraphy/api/routes/health.py

@router.get("/health/live")
async def liveness():
    """Liveness probe: is the process running?"""
    return {"status": "ok"}

@router.get("/health/ready")
async def readiness(
    neo4j: "neo4j.AsyncDriver" = Depends(get_neo4j_driver),
    redis: "Redis" = Depends(get_redis),
):
    """Readiness probe: can the service handle requests?"""
    checks = {}

    # Neo4j
    try:
        async with neo4j.session() as session:
            await session.run("RETURN 1")
        checks["neo4j"] = "ok"
    except Exception as e:
        checks["neo4j"] = f"error: {str(e)}"

    # Redis
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ready" if all_ok else "not_ready", "checks": checks}, status_code=status_code)

@router.get("/health/startup")
async def startup(request: Request):
    """Startup probe: has the application finished initializing?"""
    ready = getattr(request.app.state, "startup_complete", False)
    status_code = 200 if ready else 503
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "started" if ready else "starting"}, status_code=status_code)
```

### 13.5 Messaging: NATS Justification

NetGraphy uses NATS as its primary event bus and inter-service messaging layer, with
Redis reserved for job queuing (Celery), caching, and session storage. This is a
deliberate split based on the strengths of each system.

**Why NATS over RabbitMQ or Redis Streams:**

| Criterion              | NATS                           | RabbitMQ                        | Redis Streams                  |
|------------------------|--------------------------------|---------------------------------|--------------------------------|
| Operational overhead   | Single binary, zero config     | Erlang runtime, clustering      | Already deployed (shared)      |
| Pub/sub model          | Native, core feature           | Exchanges + bindings (complex)  | Consumer groups (basic)        |
| Durable streams        | JetStream (built-in)           | Queues (native)                 | Streams (basic)                |
| Ephemeral messaging    | Core NATS (fire-and-forget)    | Possible but wasteful           | Not natural                    |
| Python client          | nats-py (async-native)         | aio-pika (mature)               | redis-py (built-in)           |
| Go client              | nats.go (official, excellent)  | amqp091-go (good)               | go-redis (good)                |
| Cloud-native           | Designed for it                | Requires tuning                 | Single-process concern         |
| WebSocket bridge       | Built-in (nats-ws)             | Requires plugin                 | Custom implementation          |
| Message routing        | Subject-based wildcards        | Exchange routing keys           | No routing                     |

**Specific usage patterns:**

```
NATS Core (ephemeral pub/sub):
  - schema.changed             -> Cache invalidation across API instances
  - graph.node.mutated         -> Cache invalidation, UI real-time updates
  - graph.edge.mutated         -> Cache invalidation, UI real-time updates
  - ui.notification            -> WebSocket push to connected clients

NATS JetStream (durable streams):
  - audit.events               -> Guaranteed delivery to audit writer
  - sync.completed             -> Guaranteed delivery to webhook dispatcher
  - job.completed              -> Guaranteed delivery to notification service
  - ingestion.device.completed -> Tracking ingestion progress

Redis (not for messaging):
  - Celery broker              -> Python job queue
  - Cache                      -> Schema, query results, sessions
  - Go job queue               -> Simple BRPOP-based queue for Go workers
```

**NATS configuration:**

```python
# apps/api/netgraphy/events/bus.py
import json
import nats
from nats.js.api import StreamConfig, RetentionPolicy

class EventBus:
    """NATS-based event bus for inter-service messaging."""

    def __init__(self, nats_url: str = "nats://nats:4222"):
        self._url = nats_url
        self._nc: nats.Client | None = None
        self._js = None  # JetStream context

    async def connect(self):
        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()

        # Create durable streams
        await self._js.add_stream(StreamConfig(
            name="AUDIT",
            subjects=["audit.>"],
            retention=RetentionPolicy.LIMITS,
            max_msgs=1_000_000,
            max_age=86400 * 30,  # 30 days
        ))
        await self._js.add_stream(StreamConfig(
            name="EVENTS",
            subjects=["job.>", "sync.>", "ingestion.>"],
            retention=RetentionPolicy.LIMITS,
            max_msgs=100_000,
            max_age=86400 * 7,  # 7 days
        ))

    async def publish(self, subject: str, data: dict):
        """Publish to core NATS (ephemeral) or JetStream (durable)."""
        payload = json.dumps(data).encode()

        # Durable subjects go through JetStream
        if subject.startswith(("audit.", "job.", "sync.", "ingestion.")):
            await self._js.publish(subject, payload)
        else:
            await self._nc.publish(subject, payload)

    async def subscribe(self, subject: str, callback, durable: str | None = None):
        """Subscribe to a subject. Use durable for JetStream subscriptions."""
        if durable:
            await self._js.subscribe(subject, cb=callback, durable=durable)
        else:
            await self._nc.subscribe(subject, cb=callback)

    async def close(self):
        if self._nc:
            await self._nc.close()
```

---

## 14. Testing Strategy

### 14.1 Schema Validation Tests

```python
# tests/schemas/test_schema_loading.py
import pytest
from pathlib import Path
import yaml

SCHEMA_DIR = Path(__file__).parent.parent.parent / "schemas"

def discover_schema_files():
    return sorted(SCHEMA_DIR.glob("**/*.yaml"))

@pytest.mark.parametrize("schema_file", discover_schema_files(), ids=lambda p: p.name)
def test_schema_file_loads(schema_file: Path):
    """Every YAML schema file must parse without error."""
    content = yaml.safe_load(schema_file.read_text())
    assert "kind" in content, f"Schema file missing 'kind': {schema_file}"
    assert "metadata" in content, f"Schema file missing 'metadata': {schema_file}"
    assert "name" in content["metadata"], f"Schema missing 'metadata.name': {schema_file}"


def test_schema_cross_references(schema_registry_fixture):
    """All edge type source/target references must point to existing node types."""
    registry = schema_registry_fixture
    node_types = {t["metadata"]["name"] for t in registry.all_types().values() if t["kind"] == "NodeType"}
    edge_types = [t for t in registry.all_types().values() if t["kind"] == "EdgeType"]

    for edge in edge_types:
        name = edge["metadata"]["name"]
        for constraint in edge.get("constraints", []):
            assert constraint["source"] in node_types, (
                f"Edge {name}: source type '{constraint['source']}' not found"
            )
            assert constraint["target"] in node_types, (
                f"Edge {name}: target type '{constraint['target']}' not found"
            )


def test_mixin_resolution(schema_registry_fixture):
    """All referenced mixins must exist and resolve correctly."""
    registry = schema_registry_fixture
    mixins = {t["metadata"]["name"] for t in registry.all_types().values() if t["kind"] == "Mixin"}

    for type_def in registry.all_types().values():
        for mixin_ref in type_def.get("mixins", []):
            assert mixin_ref in mixins, (
                f"Type {type_def['metadata']['name']} references unknown mixin: {mixin_ref}"
            )


def test_enum_references(schema_registry_fixture):
    """All enum type references in attributes must point to existing enum types."""
    registry = schema_registry_fixture
    enum_types = {t["metadata"]["name"] for t in registry.all_types().values() if t["kind"] == "EnumType"}

    for type_def in registry.all_types().values():
        for field_name, field_def in type_def.get("attributes", {}).items():
            if field_def.get("type") == "enum":
                enum_ref = field_def.get("enum_type")
                assert enum_ref in enum_types, (
                    f"Type {type_def['metadata']['name']}.{field_name} "
                    f"references unknown enum: {enum_ref}"
                )


def test_schema_migration_detection(schema_registry_fixture):
    """Detect breaking changes between current and loaded schemas."""
    # This test loads the current deployed schema from a fixtures directory
    # and compares it to the schema files to detect breaking changes
    registry = schema_registry_fixture
    migrations = registry.detect_migrations()

    for migration in migrations:
        if migration.is_breaking:
            pytest.fail(
                f"Breaking schema change detected: {migration.description}. "
                f"Add an explicit migration to proceed."
            )
```

### 14.2 Backend Unit Tests

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

@pytest_asyncio.fixture
async def mock_neo4j():
    """Mock Neo4j driver for unit tests."""
    driver = AsyncMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver, session

@pytest_asyncio.fixture
async def graph_repo(mock_neo4j):
    """GraphRepository with mocked Neo4j."""
    driver, session = mock_neo4j
    from netgraphy.graph.repository import GraphRepository
    repo = GraphRepository(driver)
    return repo, session

@pytest_asyncio.fixture
async def schema_registry_fixture():
    """Load schema registry from test fixtures."""
    from netgraphy.schema.registry import SchemaRegistry
    registry = SchemaRegistry()
    await registry.load_from_directory("tests/fixtures/schemas/")
    return registry


# tests/schema/test_schema_engine.py
class TestSchemaEngine:
    async def test_load_node_type(self, schema_registry_fixture):
        registry = schema_registry_fixture
        device = await registry.get_type("Device")
        assert device["kind"] == "NodeType"
        assert "hostname" in device["attributes"]

    async def test_validate_node_data(self, schema_registry_fixture):
        registry = schema_registry_fixture
        # Valid data
        errors = registry.validate("Device", {"hostname": "rtr-01", "status": "active"})
        assert errors == []

        # Missing required field
        errors = registry.validate("Device", {"status": "active"})
        assert any("hostname" in e for e in errors)

    async def test_mixin_attribute_inheritance(self, schema_registry_fixture):
        registry = schema_registry_fixture
        device = await registry.get_type("Device")
        # Should have attributes from applied mixins
        assert "_created_at" in device["resolved_attributes"]


# tests/graph/test_cypher_builder.py
class TestCypherBuilder:
    def test_simple_match(self):
        from netgraphy.graph.cypher import CypherBuilder
        builder = CypherBuilder()
        cypher, params = builder.match("Device", "d").where("d.status", "=", "active").return_("d").build()
        assert "MATCH (d:Device)" in cypher
        assert "WHERE d.status = $p0" in cypher
        assert params["p0"] == "active"

    def test_relationship_match(self):
        from netgraphy.graph.cypher import CypherBuilder
        builder = CypherBuilder()
        cypher, params = (
            builder
            .match("Device", "d")
            .related_to("HAS_INTERFACE", "Interface", "i", direction="out")
            .where("d.hostname", "=", "rtr-01")
            .return_("d", "i")
            .build()
        )
        assert "(d)-[:HAS_INTERFACE]->(i:Interface)" in cypher

    def test_pagination(self):
        from netgraphy.graph.cypher import CypherBuilder
        builder = CypherBuilder()
        cypher, _ = (
            builder
            .match("Device", "d")
            .return_("d")
            .order_by("d.hostname")
            .skip(20)
            .limit(10)
            .build()
        )
        assert "ORDER BY d.hostname" in cypher
        assert "SKIP 20" in cypher
        assert "LIMIT 10" in cypher


# tests/api/test_routes.py
class TestDeviceRoutes:
    async def test_list_devices(self, async_client, mock_graph):
        mock_graph.list_nodes.return_value = [
            {"hostname": "rtr-01", "status": "active"},
            {"hostname": "rtr-02", "status": "active"},
        ]
        response = await async_client.get("/api/v1/nodes/Device")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 2

    async def test_create_device_requires_auth(self, async_client):
        response = await async_client.post("/api/v1/nodes/Device", json={"hostname": "rtr-01"})
        assert response.status_code == 401

    async def test_create_device_validates_schema(self, async_client, auth_headers):
        response = await async_client.post(
            "/api/v1/nodes/Device",
            json={"invalid_field": "value"},
            headers=auth_headers,
        )
        assert response.status_code == 422
```

### 14.3 Integration Tests

```python
# tests/integration/conftest.py
import pytest
import pytest_asyncio
from testcontainers.neo4j import Neo4jContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def neo4j_container():
    """Start a real Neo4j container for integration tests."""
    with Neo4jContainer("neo4j:5-community") as neo4j:
        neo4j.with_env("NEO4J_AUTH", "neo4j/testpassword")
        yield neo4j

@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis

@pytest_asyncio.fixture
async def integration_graph(neo4j_container):
    """GraphRepository connected to real Neo4j."""
    import neo4j as neo4j_lib
    driver = neo4j_lib.AsyncGraphDatabase.driver(
        neo4j_container.get_connection_url(),
        auth=("neo4j", "testpassword"),
    )
    from netgraphy.graph.repository import GraphRepository
    repo = GraphRepository(driver)

    yield repo

    # Cleanup: delete all nodes after each test
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    await driver.close()


# tests/integration/test_graph_operations.py
class TestGraphIntegration:
    async def test_create_and_read_device(self, integration_graph):
        repo = integration_graph

        # Create
        await repo.upsert_node("Device", {"hostname": "test-rtr-01", "status": "active"}, match_keys=["hostname"])

        # Read back
        result = await repo.execute_cypher(
            "MATCH (d:Device {hostname: $hostname}) RETURN d",
            {"hostname": "test-rtr-01"},
        )
        assert len(result) == 1
        assert result[0]["d"]["hostname"] == "test-rtr-01"

    async def test_create_edge(self, integration_graph):
        repo = integration_graph

        await repo.upsert_node("Device", {"hostname": "rtr-01"}, match_keys=["hostname"])
        await repo.upsert_node("Interface", {"device_hostname": "rtr-01", "name": "Gi0/1"}, match_keys=["device_hostname", "name"])

        await repo.upsert_edge(
            "HAS_INTERFACE",
            source=("Device", {"hostname": "rtr-01"}),
            target=("Interface", {"device_hostname": "rtr-01", "name": "Gi0/1"}),
        )

        result = await repo.execute_cypher(
            "MATCH (d:Device)-[:HAS_INTERFACE]->(i:Interface) RETURN d.hostname, i.name",
            {},
        )
        assert len(result) == 1

    async def test_rbac_enforcement(self, integration_graph, integration_app):
        """Test that RBAC is enforced end-to-end."""
        # Create a viewer user
        viewer_token = await create_test_user(integration_app, role="viewer")

        # Viewer can read
        response = await integration_app.get(
            "/api/v1/nodes/Device", headers={"Authorization": f"Bearer {viewer_token}"}
        )
        assert response.status_code == 200

        # Viewer cannot write
        response = await integration_app.post(
            "/api/v1/nodes/Device",
            json={"hostname": "blocked"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 403

    async def test_git_sync_with_local_repo(self, integration_app, tmp_path):
        """Test Git sync against a local Git repository."""
        import subprocess

        # Create a local Git repo with a schema file
        repo_dir = tmp_path / "test-content"
        repo_dir.mkdir()
        subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)

        schemas_dir = repo_dir / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "test_type.yaml").write_text("""
kind: NodeType
metadata:
  name: TestType
attributes:
  name:
    type: string
    required: true
""")
        subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo_dir), "commit", "-m", "initial"],
            check=True, capture_output=True,
        )

        # Register as git source and sync
        # ... (test the full sync flow)
```

### 14.4 Parser Tests

Covered in detail in Section 9.7. Summary of CI requirements:

```yaml
# .github/workflows/ci.yml (parser test section)
parser-tests:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install -e "packages/netgraphy-parsers[test]"
    - run: pytest tests/parsers/ -v --tb=short --junitxml=reports/parser-tests.xml
    - uses: actions/upload-artifact@v4
      with:
        name: parser-test-results
        path: reports/parser-tests.xml
```

### 14.5 Frontend Tests

```typescript
// apps/web/src/components/__tests__/DynamicList.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DynamicList } from "../DynamicList";

const mockSchema = {
  kind: "NodeType",
  metadata: { name: "Device", display_name: "Devices" },
  attributes: {
    hostname: { type: "string", display_name: "Hostname" },
    status: { type: "enum", enum_type: "DeviceStatus", display_name: "Status" },
    site: { type: "string", display_name: "Site" },
  },
  list_view: {
    default_columns: ["hostname", "status", "site"],
    default_sort: { field: "hostname", direction: "asc" },
  },
};

const mockData = [
  { hostname: "rtr-01", status: "active", site: "NYC" },
  { hostname: "rtr-02", status: "active", site: "LAX" },
];

describe("DynamicList", () => {
  it("renders columns from schema", async () => {
    render(<DynamicList schema={mockSchema} data={mockData} />);

    await waitFor(() => {
      expect(screen.getByText("Hostname")).toBeInTheDocument();
      expect(screen.getByText("Status")).toBeInTheDocument();
      expect(screen.getByText("Site")).toBeInTheDocument();
    });
  });

  it("renders data rows", async () => {
    render(<DynamicList schema={mockSchema} data={mockData} />);

    await waitFor(() => {
      expect(screen.getByText("rtr-01")).toBeInTheDocument();
      expect(screen.getByText("rtr-02")).toBeInTheDocument();
    });
  });

  it("handles empty data", async () => {
    render(<DynamicList schema={mockSchema} data={[]} />);

    await waitFor(() => {
      expect(screen.getByText(/no .* found/i)).toBeInTheDocument();
    });
  });
});
```

**Playwright E2E tests:**

```typescript
// apps/web/e2e/critical-flows.spec.ts
import { test, expect } from "@playwright/test";

test.describe("Critical Flows", () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto("/login");
    await page.fill('[data-testid="username"]', "admin");
    await page.fill('[data-testid="password"]', "admin");
    await page.click('[data-testid="login-button"]');
    await page.waitForURL("/");
  });

  test("view device list", async ({ page }) => {
    await page.goto("/nodes/Device");
    await expect(page.getByRole("heading", { name: /devices/i })).toBeVisible();
    // Table should have rows from seed data
    await expect(page.locator("table tbody tr")).toHaveCount(5); // seed data count
  });

  test("view device detail", async ({ page }) => {
    await page.goto("/nodes/Device");
    await page.click("text=core-rtr-01");
    await expect(page.getByText("core-rtr-01")).toBeVisible();
    // Should show interfaces
    await expect(page.getByText("Interfaces")).toBeVisible();
  });

  test("create a new device", async ({ page }) => {
    await page.goto("/nodes/Device/new");
    await page.fill('[data-testid="field-hostname"]', "test-device-e2e");
    await page.selectOption('[data-testid="field-status"]', "active");
    await page.fill('[data-testid="field-site"]', "TEST");
    await page.click('[data-testid="save-button"]');

    // Should redirect to detail page
    await page.waitForURL(/\/nodes\/Device\/.*/);
    await expect(page.getByText("test-device-e2e")).toBeVisible();
  });

  test("run a saved query", async ({ page }) => {
    await page.goto("/queries");
    await page.click("text=Find Orphaned Devices");
    await page.click('[data-testid="run-query"]');
    await expect(page.locator('[data-testid="query-results"]')).toBeVisible();
  });

  test("graph visualization", async ({ page }) => {
    await page.goto("/nodes/Device");
    await page.click("text=core-rtr-01");
    await page.click('[data-testid="graph-view-tab"]');
    // Canvas should render
    await expect(page.locator("canvas")).toBeVisible();
  });
});
```

### 14.6 E2E Tests

Full-stack E2E tests run against the containerized environment.

```yaml
# .github/workflows/e2e.yml
name: E2E Tests

on:
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Start test environment
        run: docker compose -f docker-compose.test.yml up -d --build --wait
        timeout-minutes: 5

      - name: Wait for services
        run: |
          for i in $(seq 1 30); do
            curl -sf http://localhost:8000/health/ready && break
            sleep 2
          done

      - name: Seed test data
        run: docker compose -f docker-compose.test.yml exec api python scripts/seed.py

      - name: Run Playwright tests
        run: |
          cd apps/web
          npx playwright install --with-deps chromium
          npx playwright test --project=chromium

      - name: Upload test artifacts
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-results
          path: apps/web/test-results/

      - name: Teardown
        if: always()
        run: docker compose -f docker-compose.test.yml down -v
```

### 14.7 Containerized Test Strategy

```yaml
# docker-compose.test.yml
services:
  neo4j-test:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/testpassword
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"
      - "7687:7687"
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis-test:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 5

  nats-test:
    image: nats:latest
    command: ["-js", "-m", "8222"]
    ports:
      - "4222:4222"
      - "8222:8222"
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8222/healthz"]
      interval: 2s
      timeout: 2s
      retries: 5

  minio-test:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 2s
      timeout: 2s
      retries: 5

  postgres-test:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: netgraphy_audit
      POSTGRES_USER: netgraphy
      POSTGRES_PASSWORD: testpassword
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U netgraphy"]
      interval: 2s
      timeout: 2s
      retries: 5

  api-test:
    build:
      context: .
      dockerfile: infra/docker/api.Dockerfile
    ports:
      - "8000:8000"
    environment:
      NEO4J_URI: bolt://neo4j-test:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: testpassword
      REDIS_URL: redis://redis-test:6379
      NATS_URL: nats://nats-test:4222
      MINIO_ENDPOINT: minio-test:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      POSTGRES_URL: postgresql://netgraphy:testpassword@postgres-test:5432/netgraphy_audit
      JWT_SECRET: test-secret-do-not-use-in-production
      ENVIRONMENT: test
    depends_on:
      neo4j-test:
        condition: service_healthy
      redis-test:
        condition: service_healthy
      nats-test:
        condition: service_healthy
      minio-test:
        condition: service_healthy
      postgres-test:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
      interval: 5s
      timeout: 5s
      retries: 15

  # Run backend tests inside the API container
  backend-tests:
    build:
      context: .
      dockerfile: infra/docker/api.Dockerfile
    command: ["pytest", "tests/", "-v", "--tb=short", "--junitxml=/reports/backend.xml"]
    environment:
      NEO4J_URI: bolt://neo4j-test:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: testpassword
      REDIS_URL: redis://redis-test:6379
      NATS_URL: nats://nats-test:4222
      MINIO_ENDPOINT: minio-test:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      POSTGRES_URL: postgresql://netgraphy:testpassword@postgres-test:5432/netgraphy_audit
    volumes:
      - ./reports:/reports
    depends_on:
      neo4j-test:
        condition: service_healthy
      redis-test:
        condition: service_healthy
      nats-test:
        condition: service_healthy
      postgres-test:
        condition: service_healthy

volumes:
  reports:
```

---

## 15. Local Dev Architecture

### 15.1 Docker Compose Stack

```yaml
# docker-compose.yml
services:
  api:
    build:
      context: .
      dockerfile: infra/docker/api.Dockerfile
      target: dev  # Multi-stage: dev target includes dev dependencies
    ports:
      - "8000:8000"
    volumes:
      - ./apps/api:/app/apps/api
      - ./packages:/app/packages
      - ./schemas:/app/schemas
      - ./parsers:/app/parsers
      - ./commands:/app/commands
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: netgraphy
      REDIS_URL: redis://redis:6379
      NATS_URL: nats://nats:4222
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      POSTGRES_URL: postgresql://netgraphy:netgraphy@postgres:5432/netgraphy_audit
      JWT_SECRET: dev-secret-not-for-production
      ENVIRONMENT: development
      LOG_LEVEL: debug
    command: >
      uvicorn netgraphy.api.main:app
      --host 0.0.0.0
      --port 8000
      --reload
      --reload-dir /app/apps/api
      --reload-dir /app/packages
    depends_on:
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
      nats:
        condition: service_started
      minio:
        condition: service_started
      postgres:
        condition: service_healthy

  web:
    build:
      context: .
      dockerfile: infra/docker/web.Dockerfile
      target: dev
    ports:
      - "3000:3000"
    volumes:
      - ./apps/web:/app/apps/web
      - /app/apps/web/node_modules  # Exclude node_modules from mount
    environment:
      VITE_API_URL: http://localhost:8000
      VITE_WS_URL: ws://localhost:8000/ws
    command: npm run dev -- --host 0.0.0.0

  worker:
    build:
      context: .
      dockerfile: infra/docker/worker.Dockerfile
      target: dev
    volumes:
      - ./apps/worker:/app/apps/worker
      - ./packages:/app/packages
      - ./jobs:/app/jobs
      - ./parsers:/app/parsers
      - ./commands:/app/commands
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: netgraphy
      REDIS_URL: redis://redis:6379
      NATS_URL: nats://nats:4222
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      POSTGRES_URL: postgresql://netgraphy:netgraphy@postgres:5432/netgraphy_audit
      LOG_LEVEL: debug
    command: >
      celery -A netgraphy.worker.celery_app worker
      --loglevel=info
      --concurrency=2
      -Q python-jobs,ingestion
    depends_on:
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy

  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"   # Browser UI
      - "7687:7687"   # Bolt protocol
    environment:
      NEO4J_AUTH: neo4j/netgraphy
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_server_memory_heap_initial__size: 512m
      NEO4J_server_memory_heap_max__size: 1G
      NEO4J_server_memory_pagecache_size: 512m
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 5s
      timeout: 10s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 5

  nats:
    image: nats:latest
    command: ["-js", "-m", "8222", "--store_dir", "/data"]
    ports:
      - "4222:4222"   # Client connections
      - "8222:8222"   # Monitoring
    volumes:
      - nats_data:/data

  minio:
    image: minio/minio
    ports:
      - "9000:9000"   # API
      - "9001:9001"   # Console
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: netgraphy_audit
      POSTGRES_USER: netgraphy
      POSTGRES_PASSWORD: netgraphy
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infra/db/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U netgraphy"]
      interval: 2s
      timeout: 2s
      retries: 5

volumes:
  neo4j_data:
  neo4j_logs:
  redis_data:
  nats_data:
  minio_data:
  postgres_data:
```

**API Dockerfile** (`infra/docker/api.Dockerfile`):

```dockerfile
# Base stage: shared across dev and prod
FROM python:3.12-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/api/ apps/api/
RUN uv pip install --system -e "apps/api[all]" -e "packages/netgraphy-core" -e "packages/netgraphy-parsers"

# Dev stage: includes dev tools, no code copy (volumes instead)
FROM base AS dev
RUN uv pip install --system pytest pytest-asyncio pytest-cov httpx testcontainers structlog
# Source mounted via volume

# Prod stage: optimized
FROM base AS prod
COPY schemas/ schemas/
COPY parsers/ parsers/
COPY commands/ commands/
EXPOSE 8000
CMD ["uvicorn", "netgraphy.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 15.2 Developer Ergonomics

**Makefile:**

```makefile
.PHONY: dev test lint seed migrate clean logs

# ============================================================
# Development
# ============================================================

dev:  ## Start full development stack
	docker compose up -d --build
	@echo "Services starting..."
	@echo "  API:       http://localhost:8000"
	@echo "  Web:       http://localhost:3000"
	@echo "  Neo4j:     http://localhost:7474"
	@echo "  MinIO:     http://localhost:9001"
	@echo "  NATS Mon:  http://localhost:8222"

dev-api:  ## Start only backend services (no web)
	docker compose up -d neo4j redis nats minio postgres api worker

stop:  ## Stop all services
	docker compose down

clean:  ## Stop all services and remove volumes
	docker compose down -v
	@echo "All data volumes removed."

logs:  ## Tail logs from all services
	docker compose logs -f

logs-api:  ## Tail API logs only
	docker compose logs -f api

# ============================================================
# Database
# ============================================================

migrate:  ## Run schema migrations against Neo4j and PostgreSQL
	docker compose exec api python -m netgraphy.cli migrate

seed:  ## Populate development seed data
	docker compose exec api python -m netgraphy.cli seed

reset-db:  ## Reset all databases (destructive!)
	docker compose exec neo4j cypher-shell -u neo4j -p netgraphy "MATCH (n) DETACH DELETE n"
	docker compose exec postgres psql -U netgraphy -d netgraphy_audit -c "TRUNCATE audit_events CASCADE"
	@echo "Databases reset. Run 'make seed' to repopulate."

# ============================================================
# Testing
# ============================================================

test:  ## Run all backend tests
	docker compose exec api pytest tests/ -v --tb=short

test-unit:  ## Run unit tests only
	docker compose exec api pytest tests/unit/ -v --tb=short

test-integration:  ## Run integration tests only
	docker compose exec api pytest tests/integration/ -v --tb=short

test-parsers:  ## Run parser fixture tests
	docker compose exec api pytest tests/parsers/ -v --tb=short

test-web:  ## Run frontend tests
	cd apps/web && npm test

test-e2e:  ## Run Playwright E2E tests
	docker compose -f docker-compose.test.yml up -d --build --wait
	cd apps/web && npx playwright test
	docker compose -f docker-compose.test.yml down -v

test-all:  ## Run full test suite (unit + integration + parser + frontend + e2e)
	$(MAKE) test
	$(MAKE) test-web
	$(MAKE) test-e2e

# ============================================================
# Code Quality
# ============================================================

lint:  ## Run all linters
	docker compose exec api ruff check apps/ packages/
	docker compose exec api ruff format --check apps/ packages/
	cd apps/web && npm run lint

lint-fix:  ## Auto-fix linting issues
	docker compose exec api ruff check --fix apps/ packages/
	docker compose exec api ruff format apps/ packages/
	cd apps/web && npm run lint -- --fix

typecheck:  ## Run type checking
	docker compose exec api mypy apps/api/ packages/
	cd apps/web && npm run typecheck

# ============================================================
# Schema Management
# ============================================================

schema-validate:  ## Validate all schema files
	docker compose exec api python -m netgraphy.cli schema validate

schema-diff:  ## Show pending schema changes
	docker compose exec api python -m netgraphy.cli schema diff

schema-apply:  ## Apply schema changes to Neo4j (indexes, constraints)
	docker compose exec api python -m netgraphy.cli schema apply

# ============================================================
# Jobs
# ============================================================

job-list:  ## List available jobs
	docker compose exec api python -m netgraphy.cli jobs list

job-run:  ## Run a job. Usage: make job-run JOB=collect_device_facts
	docker compose exec api python -m netgraphy.cli jobs run $(JOB)

# ============================================================
# Utilities
# ============================================================

shell-api:  ## Open a shell in the API container
	docker compose exec api bash

shell-neo4j:  ## Open Neo4j cypher-shell
	docker compose exec neo4j cypher-shell -u neo4j -p netgraphy

shell-redis:  ## Open Redis CLI
	docker compose exec redis redis-cli

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
```

**Seed data script:** `scripts/seed.py`

```python
"""
Seed script: populates a development environment with realistic example data.

Usage:
    python -m netgraphy.cli seed
    # or
    make seed
"""
import asyncio
from datetime import datetime, timedelta
import random

async def seed():
    from netgraphy.api.dependencies import get_graph_repo, get_schema_registry

    graph = await get_graph_repo()
    registry = await get_schema_registry()

    # 1. Load schemas from filesystem
    await registry.load_from_directory("schemas/")
    await registry.apply_indexes(graph)
    print("Schemas loaded and indexes applied.")

    # 2. Seed Sites
    sites = [
        {"name": "NYC-DC1", "region": "us-east", "address": "New York, NY", "status": "active"},
        {"name": "LAX-DC1", "region": "us-west", "address": "Los Angeles, CA", "status": "active"},
        {"name": "LHR-DC1", "region": "eu-west", "address": "London, UK", "status": "active"},
        {"name": "NRT-DC1", "region": "ap-northeast", "address": "Tokyo, Japan", "status": "active"},
        {"name": "LAB-01", "region": "us-east", "address": "Lab Environment", "status": "staging"},
    ]
    for site in sites:
        await graph.upsert_node("Site", site, match_keys=["name"])
    print(f"Seeded {len(sites)} sites.")

    # 3. Seed Devices
    platforms = ["cisco_ios", "cisco_nxos", "arista_eos", "juniper_junos"]
    roles = ["core_router", "distribution_switch", "access_switch", "firewall", "load_balancer"]

    devices = []
    for site in sites[:4]:  # Skip lab for auto-generation
        site_prefix = site["name"].split("-")[0].lower()
        for i, role in enumerate(roles[:3]):
            hostname = f"{site_prefix}-{role.replace('_', '-')}-{i+1:02d}"
            device = {
                "hostname": hostname,
                "platform": random.choice(platforms),
                "role": role,
                "site": site["name"],
                "status": "active",
                "management_ip": f"10.{sites.index(site)}.{i}.1",
                "serial_number": f"FTX{random.randint(1000, 9999)}A{random.randint(100, 999)}",
                "hardware_model": random.choice(["C9300-48P", "N9K-C9336C-FX2", "DCS-7280SR", "MX204"]),
            }
            devices.append(device)
            await graph.upsert_node("Device", device, match_keys=["hostname"])
            await graph.upsert_edge(
                "IN_SITE",
                source=("Device", {"hostname": hostname}),
                target=("Site", {"name": site["name"]}),
            )

    print(f"Seeded {len(devices)} devices with site assignments.")

    # 4. Seed Interfaces
    interface_count = 0
    for device in devices:
        for port_num in range(1, random.randint(5, 25)):
            iface = {
                "device_hostname": device["hostname"],
                "name": f"GigabitEthernet0/{port_num}",
                "status": random.choice(["up", "up", "up", "down", "admin_down"]),
                "ip_address": f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
                    if port_num <= 3 else None,
                "mtu": 1500,
                "description": f"Link to {random.choice(['server', 'uplink', 'user', 'management'])}",
            }
            await graph.upsert_node("Interface", iface, match_keys=["device_hostname", "name"])
            await graph.upsert_edge(
                "HAS_INTERFACE",
                source=("Device", {"hostname": device["hostname"]}),
                target=("Interface", {"device_hostname": device["hostname"], "name": iface["name"]}),
            )
            interface_count += 1

    print(f"Seeded {interface_count} interfaces.")

    # 5. Seed some topology connections (CONNECTED_TO edges between interfaces)
    connection_count = 0
    for i in range(0, len(devices) - 1, 2):
        d1, d2 = devices[i], devices[i + 1]
        await graph.upsert_edge(
            "CONNECTED_TO",
            source=("Interface", {"device_hostname": d1["hostname"], "name": "GigabitEthernet0/1"}),
            target=("Interface", {"device_hostname": d2["hostname"], "name": "GigabitEthernet0/1"}),
            attributes={"discovery_protocol": "cdp"},
        )
        connection_count += 1

    print(f"Seeded {connection_count} topology connections.")

    # 6. Create default admin user
    from netgraphy.auth.authentication import AuthService
    auth = AuthService(graph._db)
    import bcrypt
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
    await graph._db.execute(
        """INSERT INTO users (username, email, display_name, password_hash, auth_provider)
           VALUES ('admin', 'admin@netgraphy.local', 'Admin User', :hash, 'local')
           ON CONFLICT (username) DO NOTHING""",
        {"hash": password_hash},
    )
    # Assign admin role
    await graph._db.execute(
        """INSERT INTO user_roles (user_id, role_id)
           SELECT u.id, r.id FROM users u, roles r
           WHERE u.username = 'admin' AND r.name = 'admin'
           ON CONFLICT DO NOTHING""",
    )
    print("Default admin user created (admin/admin).")
    print("Seed complete.")

if __name__ == "__main__":
    asyncio.run(seed())
```

**Startup initialization:** `apps/api/netgraphy/api/main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("startup.begin")

    # 1. Connect to Neo4j
    import neo4j
    app.state.neo4j_driver = neo4j.AsyncGraphDatabase.driver(
        settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    logger.info("startup.neo4j_connected")

    # 2. Connect to Redis
    from redis.asyncio import Redis
    app.state.redis = Redis.from_url(settings.REDIS_URL)
    logger.info("startup.redis_connected")

    # 3. Connect to NATS
    from netgraphy.events.bus import EventBus
    app.state.event_bus = EventBus(settings.NATS_URL)
    await app.state.event_bus.connect()
    logger.info("startup.nats_connected")

    # 4. Connect to PostgreSQL (audit)
    import databases
    app.state.audit_db = databases.Database(settings.POSTGRES_URL)
    await app.state.audit_db.connect()
    logger.info("startup.postgres_connected")

    # 5. Connect to MinIO
    from miniopy_async import Minio
    app.state.minio = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )

    # 6. Load schema registry
    from netgraphy.schema.registry import SchemaRegistry
    app.state.schema_registry = SchemaRegistry(app.state.redis)
    await app.state.schema_registry.load_from_directory("schemas/")
    logger.info("startup.schemas_loaded")

    # 7. Apply Neo4j indexes from schema
    from netgraphy.graph.indexes import IndexManager
    index_mgr = IndexManager(app.state.neo4j_driver)
    await index_mgr.sync_indexes(app.state.schema_registry)
    logger.info("startup.indexes_synced")

    # 8. Start cache invalidation subscriber
    from netgraphy.cache.invalidation import CacheInvalidationSubscriber
    from netgraphy.cache.manager import CacheManager
    cache = CacheManager(app.state.redis)
    invalidation = CacheInvalidationSubscriber(cache, app.state.event_bus._nc)
    await invalidation.start()

    # 9. Mark startup complete
    app.state.startup_complete = True
    logger.info("startup.complete")

    yield

    # Shutdown
    logger.info("shutdown.begin")
    await app.state.event_bus.close()
    await app.state.neo4j_driver.close()
    await app.state.redis.close()
    await app.state.audit_db.disconnect()
    logger.info("shutdown.complete")


app = FastAPI(
    title="NetGraphy API",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
from netgraphy.auth.audit import AuditMiddleware
from netgraphy.observability.logging import CorrelationMiddleware
app.add_middleware(AuditMiddleware)
app.add_middleware(CorrelationMiddleware)

# Routes
from netgraphy.api.routes import nodes, edges, queries, jobs, sync, health, auth
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(nodes.router, prefix="/api/v1/nodes", tags=["nodes"])
app.include_router(edges.router, prefix="/api/v1/edges", tags=["edges"])
app.include_router(queries.router, prefix="/api/v1/queries", tags=["queries"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(sync.router, prefix="/api/v1/sync", tags=["sync"])
```
