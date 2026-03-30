/**
 * MappingPane — YAML mapping template development IDE.
 *
 * Left: Mapping definitions list
 * Center: YAML mapping editor (Monaco) with Jinja2 template preview
 * Right: Data model reference (fields, relationships, available filters)
 * Bottom: Template rendering preview
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { api } from "@/api/client";
import { useSchemaStore } from "@/stores/schemaStore";

interface MappingDef {
  id: string;
  name: string;
  parser: string;
  platform: string;
  definition_json: string;
  description?: string;
}

const SAMPLE_MAPPING = `kind: MappingDefinition
version: v1
metadata:
  name: cisco_ios_version_to_graph
  description: "Maps 'show version' parsed output to Device and SoftwareVersion nodes"
  parser: cisco_ios_show_version
  platform: cisco_ios

mappings:
  # Upsert the Device node with hostname and serial
  - target_node_type: Device
    match_on: [hostname]
    attributes:
      hostname: "{{ parsed.HOSTNAME }}"
      serial_number: "{{ parsed.SERIAL }}"

  # Upsert the SoftwareVersion node
  - target_node_type: SoftwareVersion
    match_on: [version_string]
    attributes:
      version_string: "{{ parsed.VERSION }}"

  # Create RUNS_VERSION edge: Device -> SoftwareVersion
  - target_edge_type: RUNS_VERSION
    source:
      node_type: Device
      match_on:
        hostname: "{{ parsed.HOSTNAME }}"
    target:
      node_type: SoftwareVersion
      match_on:
        version_string: "{{ parsed.VERSION }}"
`;

const SAMPLE_CONTEXT = `{
  "parsed": {
    "HOSTNAME": "router1",
    "VERSION": "16.09.01",
    "SERIAL": "FDO2145A0BC",
    "HARDWARE": "ISR4431/K9"
  }
}`;

export function MappingPane() {
  const { nodeTypes, edgeTypes } = useSchemaStore();

  // Editor state
  const [mappingYaml, setMappingYaml] = useState("");
  const [contextJson, setContextJson] = useState(SAMPLE_CONTEXT);
  const [selectedTemplate, setSelectedTemplate] = useState("");

  // Preview state
  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // UI state
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [explorerFilter, setExplorerFilter] = useState("");

  // Queries
  const { data: mappingsData } = useQuery({
    queryKey: ["mappings"],
    queryFn: () => api.get("/parsers/mappings"),
  });
  const mappings: MappingDef[] = mappingsData?.data?.data || [];

  const { data: builtinData } = useQuery({
    queryKey: ["builtin-filters"],
    queryFn: () => api.get("/dev/builtin-filters"),
  });
  const builtinFilters = builtinData?.data?.data || [];

  const { data: customFiltersData } = useQuery({
    queryKey: ["jinja-filters"],
    queryFn: () => api.get("/parsers/filters"),
  });
  const customFilters = customFiltersData?.data?.data || [];

  // Template rendering test
  const renderMutation = useMutation({
    mutationFn: () => {
      let context: Record<string, unknown> = {};
      try {
        context = JSON.parse(contextJson);
      } catch {
        throw new Error("Invalid JSON in context");
      }
      return api.post("/dev/render-template", {
        template: selectedTemplate,
        context,
        filters: customFilters.map((f: { name: string }) => f.name),
      });
    },
    onSuccess: (resp) => {
      const d = resp.data.data;
      if (d.error) {
        setPreviewError(d.error);
        setPreviewResult(null);
      } else {
        setPreviewResult(d.rendered);
        setPreviewError(null);
      }
    },
    onError: (err) => {
      setPreviewError(String(err));
      setPreviewResult(null);
    },
  });

  const loadMapping = (m: MappingDef) => {
    try {
      const def = JSON.parse(m.definition_json);
      // Convert back to a readable YAML-ish representation
      setMappingYaml(JSON.stringify(def, null, 2));
    } catch {
      setMappingYaml(m.definition_json);
    }
  };

  const loadSample = () => {
    setMappingYaml(SAMPLE_MAPPING);
    setContextJson(SAMPLE_CONTEXT);
  };

  const filteredMappings = mappings.filter(
    (m) =>
      !explorerFilter ||
      m.name?.toLowerCase().includes(explorerFilter.toLowerCase()),
  );

  const ntNames = Object.keys(nodeTypes).sort();
  const etNames = Object.keys(edgeTypes).sort();

  const selectedNT = selectedModel ? nodeTypes[selectedModel] : null;
  const relatedEdges = selectedModel
    ? Object.values(edgeTypes).filter(
        (et) =>
          et.source.node_types.includes(selectedModel) ||
          et.target.node_types.includes(selectedModel),
      )
    : [];

  return (
    <div className="flex h-full">
      {/* ---- Left: Mapping Explorer ---- */}
      <div className="flex w-60 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800">
        <div className="flex items-center justify-between border-b border-gray-700 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Mappings
          </span>
          <button
            onClick={loadSample}
            className="rounded bg-brand-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-brand-500"
          >
            Sample
          </button>
        </div>

        <div className="border-b border-gray-700 px-3 py-2">
          <input
            type="text"
            value={explorerFilter}
            onChange={(e) => setExplorerFilter(e.target.value)}
            placeholder="Search mappings..."
            className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Registered mappings */}
          <div className="px-3 py-1.5 text-xs font-semibold uppercase text-gray-500">
            Registered ({filteredMappings.length})
          </div>
          {filteredMappings.map((m) => (
            <button
              key={m.id || m.name}
              onClick={() => loadMapping(m)}
              className="flex w-full flex-col rounded px-3 py-1.5 text-left text-gray-300 hover:bg-gray-700"
            >
              <div className="truncate text-sm font-medium">{m.name}</div>
              <div className="flex items-center gap-1 text-xs text-gray-500">
                <span>{m.platform}</span>
                <span className="text-gray-600">|</span>
                <span>{m.parser}</span>
              </div>
            </button>
          ))}
          {filteredMappings.length === 0 && (
            <div className="px-3 py-2 text-xs text-gray-500">No mappings found</div>
          )}

          {/* Available filters reference */}
          <div className="mt-4 border-t border-gray-700 pt-2">
            <div className="px-3 py-1.5 text-xs font-semibold uppercase text-gray-500">
              Available Filters
            </div>
            <div className="space-y-0.5 px-2">
              {[...builtinFilters, ...customFilters].map((f: { name: string; description?: string }) => (
                <div key={f.name} className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-700">
                  <code className="text-brand-300">{f.name}</code>
                  {f.description && (
                    <div className="truncate text-[10px] text-gray-500">{f.description}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ---- Center: Mapping Editor ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          <Editor
            height="100%"
            language="yaml"
            theme="vs-dark"
            value={mappingYaml}
            onChange={(v) => setMappingYaml(v || "")}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 2,
              automaticLayout: true,
              padding: { top: 8, bottom: 8 },
            }}
          />
        </div>

        {/* Bottom: Template Render Test */}
        <div className="border-t border-gray-700" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <div className="flex items-center justify-between border-b border-gray-700/50 px-4 py-1.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Template Render Test
            </span>
            <button
              onClick={() => renderMutation.mutate()}
              disabled={!selectedTemplate || renderMutation.isPending}
              className="rounded bg-emerald-600 px-4 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
            >
              {renderMutation.isPending ? "Rendering..." : "Render"}
            </button>
          </div>

          <div className="flex gap-4 px-4 py-2">
            <div className="flex-1">
              <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Jinja2 Template Expression
              </label>
              <input
                type="text"
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                placeholder='{{ parsed.HOSTNAME | to_slug }}'
                className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              />
            </div>
            <div className="flex-1">
              <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Context (JSON)
              </label>
              <textarea
                value={contextJson}
                onChange={(e) => setContextJson(e.target.value)}
                rows={3}
                className="w-full rounded border border-gray-600 bg-gray-900 p-2 font-mono text-xs text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              />
            </div>
          </div>

          {(previewResult !== null || previewError) && (
            <div className="border-t border-gray-700/50 px-4 py-2">
              {previewResult !== null && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">Result:</span>
                  <code className="font-mono text-sm text-green-300">{previewResult}</code>
                </div>
              )}
              {previewError && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">Error:</span>
                  <code className="font-mono text-xs text-red-300">{previewError}</code>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ---- Right: Model Reference ---- */}
      <div className="flex w-64 flex-shrink-0 flex-col border-l border-gray-700 bg-gray-800">
        <div className="border-b border-gray-700 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Data Model Reference
          </span>
        </div>

        <div className="border-b border-gray-700 px-3 py-2">
          <select
            value={selectedModel || ""}
            onChange={(e) => setSelectedModel(e.target.value || null)}
            className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200 focus:border-brand-500 focus:outline-none"
          >
            <option value="">Select a model...</option>
            <optgroup label="Node Types">
              {ntNames.map((name) => (
                <option key={name} value={name}>
                  {nodeTypes[name]?.metadata.display_name || name}
                </option>
              ))}
            </optgroup>
          </select>
        </div>

        <div className="flex-1 overflow-y-auto">
          {selectedNT && (
            <>
              {/* Fields */}
              <div className="px-3 py-1.5 text-xs font-semibold uppercase text-gray-500">
                Fields ({Object.keys(selectedNT.attributes).length})
              </div>
              <div className="space-y-0.5 px-2">
                {Object.entries(selectedNT.attributes).map(([attrName, attr]) => (
                  <div key={attrName} className="rounded px-2 py-1 hover:bg-gray-700">
                    <div className="flex items-center justify-between">
                      <code className="text-xs font-medium text-gray-200">{attrName}</code>
                      <span className="text-[10px] text-gray-500">{attr.type}</span>
                    </div>
                    <div className="flex items-center gap-1 text-[10px]">
                      {attr.required && <span className="text-amber-400">required</span>}
                      {attr.unique && <span className="text-purple-400">unique</span>}
                      {attr.indexed && <span className="text-blue-400">indexed</span>}
                    </div>
                    {attr.enum_values && (
                      <div className="mt-0.5 flex flex-wrap gap-0.5">
                        {attr.enum_values.map((v) => (
                          <span key={v} className="rounded bg-gray-700 px-1 py-0.5 text-[9px] text-gray-400">
                            {v}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* Template usage hint */}
                    <code className="mt-0.5 block text-[10px] text-brand-400/60">
                      {"{{ parsed." + attrName.toUpperCase() + " }}"}
                    </code>
                  </div>
                ))}
              </div>

              {/* Relationships */}
              {relatedEdges.length > 0 && (
                <>
                  <div className="mt-3 border-t border-gray-700 px-3 py-1.5 text-xs font-semibold uppercase text-gray-500">
                    Relationships ({relatedEdges.length})
                  </div>
                  <div className="space-y-1 px-2 pb-4">
                    {relatedEdges.map((et) => {
                      const isSource = et.source.node_types.includes(selectedModel!);
                      return (
                        <div key={et.metadata.name} className="rounded border border-gray-700 px-2 py-1.5">
                          <div className="flex items-center gap-1 text-xs">
                            <span className="text-gray-400">{isSource ? "OUT" : "IN"}</span>
                            <code className="font-medium text-emerald-300">{et.metadata.name}</code>
                          </div>
                          <div className="mt-0.5 text-[10px] text-gray-500">
                            {et.source.node_types.join("|")} {"->"} {et.target.node_types.join("|")}
                          </div>
                          <div className="text-[10px] text-gray-600">
                            {et.cardinality}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </>
          )}

          {!selectedModel && (
            <div className="px-3 py-4 text-center text-xs text-gray-500">
              Select a model to see its fields and relationships
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
