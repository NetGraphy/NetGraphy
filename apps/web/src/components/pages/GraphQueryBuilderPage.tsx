/**
 * GraphQueryBuilderPage — Visual graph query builder with live Cypher generation,
 * execution, results viewer, and saved query library.
 *
 * Layout:
 * - Left: Pattern builder + Filter builder
 * - Center: Generated Cypher (Monaco) + Results (table/graph)
 * - Right: Return fields / Sort / Query config
 */

import { useState, useCallback, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryApi } from "@/api/client";
import Editor from "@monaco-editor/react";
import { useQueryBuilderStore } from "@/stores/queryBuilderStore";
import { GraphCanvas } from "@/components/graph/GraphCanvas";

const OPERATORS = [
  { value: "eq", label: "=" },
  { value: "neq", label: "!=" },
  { value: "contains", label: "CONTAINS" },
  { value: "starts_with", label: "STARTS WITH" },
  { value: "ends_with", label: "ENDS WITH" },
  { value: "gt", label: ">" },
  { value: "gte", label: ">=" },
  { value: "lt", label: "<" },
  { value: "lte", label: "<=" },
  { value: "in", label: "IN" },
  { value: "is_null", label: "IS NULL" },
  { value: "is_not_null", label: "IS NOT NULL" },
  { value: "regex", label: "=~ (regex)" },
];

export function GraphQueryBuilderPage() {
  const store = useQueryBuilderStore();
  const {
    model, cypher, savedMeta, selectedPatternId,
    addNode, updateNode, removeNode,
    addRelationship, updateRelationship, removeRelationship,
    addFilter, updateFilter, removeFilter,
    addReturnField, removeReturnField, updateReturnField, clearReturnFields,
    setSortFields, setDistinct, setLimit, setSkip,
    setModel, resetModel, setSavedMeta, selectPattern, loadTemplate,
  } = store;

  const queryClient = useQueryClient();

  // Schema data for dropdowns
  const { data: nodeTypesData } = useQuery({
    queryKey: ["schema-node-types"],
    queryFn: () => api.get("/schema/node-types"),
  });
  const { data: edgeTypesData } = useQuery({
    queryKey: ["schema-edge-types"],
    queryFn: () => api.get("/schema/edge-types"),
  });
  const nodeTypes: string[] = (nodeTypesData?.data?.data || []).map((nt: any) => nt.metadata?.name || nt.name);
  const edgeTypes: string[] = (edgeTypesData?.data?.data || []).map((et: any) => et.metadata?.name || et.name);

  // Results
  const [results, setResults] = useState<any>(null);
  const [resultView, setResultView] = useState<"table" | "graph" | "json">("table");
  const [executing, setExecuting] = useState(false);
  const [execError, setExecError] = useState("");
  const [execTime, setExecTime] = useState(0);

  // Saved queries
  const [showSaved, setShowSaved] = useState(false);
  const [saveFeedback, setSaveFeedback] = useState("");
  const { data: savedData } = useQuery({
    queryKey: ["saved-queries-builder"],
    queryFn: () => api.get("/query/saved"),
    enabled: showSaved,
  });
  const savedQueries: any[] = savedData?.data?.data?.items || savedData?.data?.data || [];

  // Add node dialog
  const [showAddNode, setShowAddNode] = useState(false);
  const [newNodeLabel, setNewNodeLabel] = useState("");
  const [newNodeAlias, setNewNodeAlias] = useState("");

  // Add relationship dialog
  const [showAddRel, setShowAddRel] = useState(false);
  const [newRelFrom, setNewRelFrom] = useState("");
  const [newRelTo, setNewRelTo] = useState("");
  const [newRelType, setNewRelType] = useState("");
  const [newRelDir, setNewRelDir] = useState<"outgoing" | "incoming" | "undirected">("outgoing");

  // Parameter values for execution
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  // Search filter for relationship type picker
  const [relTypeSearch, setRelTypeSearch] = useState("");

  // Copy feedback
  const [copied, setCopied] = useState(false);

  // Execute query
  const executeQuery = useCallback(async () => {
    // Check required parameters
    for (const p of model.parameters) {
      if (p.required && !paramValues[p.name]) {
        setExecError(`Required parameter "${p.label || p.name}" is missing`);
        return;
      }
    }
    setExecuting(true);
    setExecError("");
    const start = Date.now();
    try {
      const params = model.parameters.length > 0 ? paramValues : undefined;
      const resp = await queryApi.executeCypher(cypher, params);
      const data = resp.data.data;
      setResults(data);
      setExecTime(Date.now() - start);
      // Auto-switch to graph view if results contain graph nodes
      if (data?.nodes?.length > 0) {
        setResultView("graph");
      }
    } catch (err: any) {
      setExecError(err?.response?.data?.detail || err.message || "Query execution failed");
      setResults(null);
      setExecTime(Date.now() - start);
    } finally {
      setExecuting(false);
    }
  }, [cypher, model.parameters, paramValues]);

  // Copy Cypher
  const copyCypher = useCallback(() => {
    navigator.clipboard.writeText(cypher);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [cypher]);

  // Save query
  const saveQuery = useCallback(async () => {
    try {
      await api.post("/query/saved", {
        name: savedMeta.name || "Untitled Query",
        description: savedMeta.description,
        query: cypher,
        query_model: JSON.stringify(model),
        tags: savedMeta.tags,
        visibility: savedMeta.visibility,
      });
      setSaveFeedback("Saved");
      setTimeout(() => setSaveFeedback(""), 2000);
      queryClient.invalidateQueries({ queryKey: ["saved-queries-builder"] });
    } catch { setSaveFeedback("Failed"); }
  }, [savedMeta, cypher, model, queryClient]);

  // Load saved query
  const loadSavedQuery = useCallback((q: any) => {
    if (q.query_model) {
      try {
        const parsed = typeof q.query_model === "string" ? JSON.parse(q.query_model) : q.query_model;
        setModel(parsed);
      } catch { /* fall through */ }
    }
    setSavedMeta({ name: q.name || "", description: q.description || "" });
    setShowSaved(false);
  }, [setModel, setSavedMeta]);

  // All aliases for dropdowns
  const aliases = model.nodes.map((n) => n.alias);

  return (
    <div className="flex h-[calc(100vh-64px)]">
      {/* LEFT — Pattern Builder */}
      <div className="w-[380px] flex-shrink-0 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-y-auto">
        <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <h2 className="text-sm font-bold text-gray-900 dark:text-white">Cypher Builder</h2>
          <p className="text-[10px] text-gray-500">Build graph patterns visually, generate Cypher</p>
        </div>
        {/* Toolbar */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700 flex flex-wrap gap-1.5">
          <button onClick={() => setShowAddNode(true)}
            className="rounded bg-brand-600 px-2 py-1 text-[11px] text-white hover:bg-brand-700">+ Node</button>
          <button onClick={() => setShowAddRel(true)} disabled={model.nodes.length < 1}
            className="rounded bg-green-600 px-2 py-1 text-[11px] text-white hover:bg-green-700 disabled:opacity-50">+ Relationship</button>
          <button onClick={resetModel} className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-500">Reset</button>
          <button onClick={() => { setShowSaved(true); }} className="rounded border border-gray-300 px-2 py-1 text-[11px] text-gray-500">Saved</button>
        </div>

        {/* Templates */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Templates</div>
          <div className="flex flex-wrap gap-1">
            {[
              { key: "devices-by-site", label: "Devices by Site" },
              { key: "sites-no-devices", label: "Sites w/o Devices" },
              { key: "count-devices-by-city", label: "Count by City" },
              { key: "circuits-by-provider", label: "Circuits by Provider" },
              { key: "mac-to-mac-path", label: "MAC-to-MAC Path" },
              { key: "device-neighbors", label: "Device Neighbors" },
            ].map((t) => (
              <button key={t.key} onClick={() => loadTemplate(t.key)}
                className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] text-gray-600 hover:bg-brand-50 hover:border-brand-300 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700">
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Query Mode */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Query Mode</div>
          <div className="flex gap-1">
            {([
              { value: "pattern", label: "Pattern Match" },
              { value: "shortestPath", label: "Shortest Path" },
              { value: "allPaths", label: "All Paths" },
            ] as const).map((m) => (
              <button key={m.value} onClick={() => setModel({ ...model, queryMode: m.value })}
                className={`flex-1 rounded border px-2 py-1 text-[10px] ${model.queryMode === m.value ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/20" : "border-gray-200 text-gray-500 dark:border-gray-600"}`}>
                {m.label}
              </button>
            ))}
          </div>
          {(model.queryMode === "shortestPath" || model.queryMode === "allPaths") && (
            <div className="mt-2 space-y-2">
              <div>
                <label className="text-[9px] text-gray-500">Max hops</label>
                <input type="number" value={model.pathDepthLimit} min={1} max={50}
                  onChange={(e) => setModel({ ...model, pathDepthLimit: Number(e.target.value) })}
                  className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              </div>
              <div>
                <label className="text-[9px] text-gray-500">Allowed relationship types</label>
                <input value={relTypeSearch} onChange={(e) => setRelTypeSearch(e.target.value)}
                  placeholder="Type to filter..."
                  className="w-full mt-1 rounded border border-gray-300 px-2 py-1 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                <div className="mt-1 max-h-28 overflow-y-auto rounded border border-gray-300 p-1 dark:border-gray-600">
                  {edgeTypes
                    .filter((et) => !relTypeSearch || et.toLowerCase().includes(relTypeSearch.toLowerCase()))
                    .map((et) => {
                      const checked = model.pathRelTypes.includes(et);
                      return (
                        <label key={et} className="flex items-center gap-1.5 px-1 py-0.5 text-[10px] hover:bg-gray-50 dark:hover:bg-gray-700 rounded cursor-pointer">
                          <input type="checkbox" checked={checked}
                            onChange={() => {
                              const next = checked
                                ? model.pathRelTypes.filter((t) => t !== et)
                                : [...model.pathRelTypes, et];
                              setModel({ ...model, pathRelTypes: next });
                            }} />
                          <span className={checked ? "text-brand-600 font-medium" : "text-gray-500"}>{et}</span>
                        </label>
                      );
                    })}
                </div>
                <div className="text-[9px] text-gray-400 mt-0.5">{model.pathRelTypes.length} selected</div>
              </div>
            </div>
          )}
        </div>

        {/* Parameters */}
        {model.parameters.length > 0 && (
          <div className="p-3 border-b border-gray-200 dark:border-gray-700 bg-amber-50 dark:bg-amber-900/10">
            <div className="text-[10px] font-semibold text-amber-600 uppercase mb-1.5">Parameters</div>
            {model.parameters.map((p) => (
              <div key={p.name} className="mb-2">
                <label className="text-[10px] font-medium text-gray-600 dark:text-gray-300">
                  {p.label || p.name} {p.required && <span className="text-red-400">*</span>}
                </label>
                <input value={paramValues[p.name] || ""}
                  onChange={(e) => setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))}
                  placeholder={p.description || p.name}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              </div>
            ))}
          </div>
        )}

        {/* Node Patterns */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Node Patterns ({model.nodes.length})</div>
          {model.nodes.map((node) => (
            <div key={node.id}
              className={`mb-2 rounded border p-2 cursor-pointer text-xs ${selectedPatternId === node.id ? "border-brand-500 bg-brand-50 dark:bg-brand-900/20" : "border-gray-200 dark:border-gray-600"}`}
              onClick={() => selectPattern(node.id)}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-brand-500" />
                  <input value={node.alias} onChange={(e) => updateNode(node.id, { alias: e.target.value })}
                    onClick={(e) => e.stopPropagation()}
                    className="font-bold bg-transparent border-none p-0 focus:outline-none w-12 text-xs dark:text-white" />
                  <span className="text-gray-400">:{node.labels.join(":")}</span>
                </div>
                <div className="flex items-center gap-1">
                  <select value={node.matchType} onChange={(e) => updateNode(node.id, { matchType: e.target.value as any })}
                    onClick={(e) => e.stopPropagation()}
                    className="text-[9px] rounded border border-gray-300 px-1 py-0 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="match">MATCH</option>
                    <option value="optional_match">OPTIONAL</option>
                  </select>
                  <button onClick={(e) => { e.stopPropagation(); removeNode(node.id); }}
                    className="text-red-400 hover:text-red-600">x</button>
                </div>
              </div>
              {node.properties.length > 0 && (
                <div className="mt-1 text-[9px] text-amber-600">
                  {node.properties.map((p) => `{${p.field}: $${p.paramName}}`).join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Relationship Patterns */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Relationships ({model.relationships.length})</div>
          {model.relationships.map((rel) => {
            const from = model.nodes.find((n) => n.id === rel.fromNodeId);
            const to = model.nodes.find((n) => n.id === rel.toNodeId);
            const dirIcon = rel.direction === "outgoing" ? "->" : rel.direction === "incoming" ? "<-" : "--";
            return (
              <div key={rel.id}
                className={`mb-2 rounded border p-2 cursor-pointer text-xs ${selectedPatternId === rel.id ? "border-green-500 bg-green-50 dark:bg-green-900/20" : "border-gray-200 dark:border-gray-600"}`}
                onClick={() => selectPattern(rel.id)}>
                <div className="flex items-center justify-between">
                  <span className="text-gray-600 dark:text-gray-300">
                    ({from?.alias}){dirIcon}[:{rel.types.join("|")}]{dirIcon}({to?.alias})
                  </span>
                  <button onClick={(e) => { e.stopPropagation(); removeRelationship(rel.id); }}
                    className="text-red-400 hover:text-red-600">x</button>
                </div>
                {selectedPatternId === rel.id && (
                  <div className="mt-2 space-y-1 border-t border-gray-200 pt-2 dark:border-gray-600">
                    <div className="flex gap-2">
                      <select value={rel.direction} onChange={(e) => updateRelationship(rel.id, { direction: e.target.value as any })}
                        className="text-[10px] rounded border border-gray-300 px-1 py-0.5 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                        <option value="outgoing">Outgoing (-&gt;)</option>
                        <option value="incoming">Incoming (&lt;-)</option>
                        <option value="undirected">Undirected (--)</option>
                      </select>
                      <select value={rel.matchType} onChange={(e) => updateRelationship(rel.id, { matchType: e.target.value as any })}
                        className="text-[10px] rounded border border-gray-300 px-1 py-0.5 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                        <option value="match">MATCH</option>
                        <option value="optional_match">OPTIONAL</option>
                      </select>
                    </div>
                    <div className="flex gap-1 items-center">
                      <label className="text-[9px] text-gray-500">Hops:</label>
                      <input type="number" min={0} placeholder="min"
                        value={rel.minHops ?? ""} onChange={(e) => updateRelationship(rel.id, { minHops: e.target.value ? Number(e.target.value) : null })}
                        className="w-10 rounded border border-gray-300 px-1 py-0 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                      <span className="text-[9px] text-gray-400">..</span>
                      <input type="number" min={0} placeholder="max"
                        value={rel.maxHops ?? ""} onChange={(e) => updateRelationship(rel.id, { maxHops: e.target.value ? Number(e.target.value) : null })}
                        className="w-10 rounded border border-gray-300 px-1 py-0 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Filters */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold text-gray-400 uppercase">Filters ({model.filters.length})</span>
            <button onClick={() => { if (aliases.length) addFilter(aliases[0]); }}
              disabled={aliases.length === 0}
              className="text-[10px] text-brand-600 hover:underline disabled:opacity-50">+ Add</button>
          </div>
          {model.filters.map((f) => (
            <div key={f.id} className="mb-2 rounded border border-gray-200 bg-gray-50 p-2 dark:border-gray-600 dark:bg-gray-700/50">
              <div className="flex gap-1 mb-1">
                <select value={f.targetAlias} onChange={(e) => updateFilter(f.id, { targetAlias: e.target.value, field: "" })}
                  className="w-14 rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  {aliases.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
                {(() => {
                  const aliasNode = model.nodes.find((n) => n.alias === f.targetAlias);
                  const label = aliasNode?.labels[0];
                  const nt = label ? (nodeTypesData?.data?.data || []).find((t: any) => (t.metadata?.name || t.name) === label) : null;
                  const attrs = nt ? [...Object.keys(nt.attributes || {}), "id"] : ["id"];
                  const filtered = attrs.filter((a) => !f.field || a.toLowerCase().includes(f.field.toLowerCase()));
                  return (
                    <div className="flex-1 relative">
                      <input value={f.field} onChange={(e) => updateFilter(f.id, { field: e.target.value })}
                        placeholder="Type field name..."
                        className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                      {f.field && !attrs.includes(f.field) && filtered.length > 0 && (
                        <div className="absolute z-10 left-0 right-0 top-full mt-0.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded shadow-lg max-h-32 overflow-y-auto">
                          {filtered.slice(0, 10).map((a) => (
                            <button key={a} onClick={() => updateFilter(f.id, { field: a })}
                              className="block w-full text-left px-2 py-1 text-[10px] hover:bg-brand-50 dark:hover:bg-gray-700">
                              {a}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}
                <button onClick={() => removeFilter(f.id)} className="text-red-400 text-[10px]">x</button>
              </div>
              <div className="flex gap-1">
                <select value={f.operator} onChange={(e) => updateFilter(f.id, { operator: e.target.value })}
                  className="w-24 rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  {OPERATORS.map((op) => <option key={op.value} value={op.value}>{op.label}</option>)}
                </select>
                {f.operator !== "is_null" && f.operator !== "is_not_null" && (
                  <input value={f.value} onChange={(e) => updateFilter(f.id, { value: e.target.value })}
                    placeholder="value"
                    className="flex-1 rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Return Fields */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold text-gray-400 uppercase">Return ({model.returnFields.length})</span>
            <button onClick={() => addReturnField("", "")}
              className="text-[10px] text-brand-600 hover:underline">+ Add</button>
          </div>
          {model.returnFields.map((rf) => (
            <div key={rf.id} className="mb-1 flex gap-1 items-center relative">
              {(() => {
                // Build suggestions: alias.field for all nodes
                const suggestions: string[] = [];
                for (const node of model.nodes) {
                  suggestions.push(node.alias); // Return whole node
                  const label = node.labels[0];
                  const nt = label ? (nodeTypesData?.data?.data || []).find((t: any) => (t.metadata?.name || t.name) === label) : null;
                  if (nt) {
                    for (const attr of Object.keys(nt.attributes || {})) {
                      suggestions.push(`${node.alias}.${attr}`);
                    }
                  }
                  suggestions.push(`${node.alias}.id`);
                  suggestions.push(`count(${node.alias})`);
                }
                suggestions.push("path");
                const filtered = rf.expression
                  ? suggestions.filter((s) => s.toLowerCase().includes(rf.expression.toLowerCase()) && s !== rf.expression)
                  : [];
                return (
                  <div className="flex-1 relative">
                    <input value={rf.expression} onChange={(e) => updateReturnField(rf.id, { expression: e.target.value })}
                      placeholder="Type: d.hostname, count(d), path..."
                      className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                    {rf.expression && filtered.length > 0 && filtered.length < 15 && (
                      <div className="absolute z-10 left-0 right-0 top-full mt-0.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded shadow-lg max-h-32 overflow-y-auto">
                        {filtered.slice(0, 10).map((s) => (
                          <button key={s} onClick={() => updateReturnField(rf.id, { expression: s, alias: s.includes(".") ? s.split(".").pop() || s : s })}
                            className="block w-full text-left px-2 py-1 text-[10px] font-mono hover:bg-brand-50 dark:hover:bg-gray-700">
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })()}
              <input value={rf.alias} onChange={(e) => updateReturnField(rf.id, { alias: e.target.value })}
                placeholder="alias"
                className="w-20 rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              <button onClick={() => removeReturnField(rf.id)} className="text-red-400 text-[10px]">x</button>
            </div>
          ))}
        </div>

        {/* Sort / Limit */}
        <div className="p-3">
          <div className="flex gap-2 mb-2">
            <label className="flex items-center gap-1 text-[10px] text-gray-500">
              <input type="checkbox" checked={model.distinct} onChange={(e) => setDistinct(e.target.checked)} /> DISTINCT
            </label>
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[9px] text-gray-500">Limit</label>
              <input type="number" value={model.limit} onChange={(e) => setLimit(Number(e.target.value))} min={0}
                className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            <div className="flex-1">
              <label className="text-[9px] text-gray-500">Skip</label>
              <input type="number" value={model.skip} onChange={(e) => setSkip(Number(e.target.value))} min={0}
                className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
          </div>
        </div>
      </div>

      {/* CENTER — Cypher + Results */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Cypher view + actions */}
        <div className="flex-shrink-0">
          <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-gray-500">Generated Cypher</span>
              <button onClick={copyCypher}
                className="rounded border border-gray-300 px-2 py-0.5 text-[10px] text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400">
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="flex items-center gap-2">
              <input value={savedMeta.name} onChange={(e) => setSavedMeta({ name: e.target.value })}
                placeholder="Query name..."
                className="w-40 rounded border border-gray-300 px-2 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              <button onClick={saveQuery}
                className="rounded border border-brand-300 px-2 py-0.5 text-[10px] text-brand-600 hover:bg-brand-50">
                {saveFeedback || "Save"}
              </button>
              <button onClick={executeQuery} disabled={!cypher || executing}
                className="rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50">
                {executing ? "Running..." : "Execute"}
              </button>
            </div>
          </div>
          <div style={{ height: "150px" }}>
            <Editor
              language="cypher"
              value={cypher || "// Build a query pattern on the left to generate Cypher"}
              theme="vs-light"
              options={{ minimap: { enabled: false }, fontSize: 12, lineNumbers: "on", scrollBeyondLastLine: false, readOnly: true, wordWrap: "on" }}
            />
          </div>
        </div>
        <div className="border-t border-gray-200 dark:border-gray-700" />

        {/* Results */}
        <div className="flex-1 overflow-auto">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
            {["table", "graph", "json"].map((v) => (
              <button key={v} onClick={() => setResultView(v as any)}
                className={`rounded px-2 py-0.5 text-[10px] ${resultView === v ? "bg-brand-100 text-brand-700" : "text-gray-500 hover:bg-gray-100"}`}>
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </button>
            ))}
            {results && (
              <span className="text-[10px] text-gray-400 ml-auto">
                {results.rows?.length || 0} rows, {execTime}ms
              </span>
            )}
            {execError && <span className="text-[10px] text-red-500 ml-auto">{execError}</span>}
          </div>

          <div className="p-3">
            {!results && !execError && !executing && (
              <div className="flex h-48 items-center justify-center text-gray-400 text-sm">
                Build a query pattern and click Execute
              </div>
            )}
            {executing && <div className="flex h-48 items-center justify-center text-gray-400">Running query...</div>}

            {results && resultView === "table" && (
              <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      {(results.columns || []).map((col: string) => (
                        <th key={col} className="px-3 py-2 text-left text-[10px] font-medium uppercase text-gray-500">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {(results.rows || []).map((row: any, i: number) => (
                      <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                        {(results.columns || []).map((col: string) => {
                          const val = row[col];
                          const display = val !== null && typeof val === "object" ? JSON.stringify(val) : String(val ?? "");
                          return <td key={col} className="px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">{display}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {results && resultView === "json" && (
              <pre className="text-xs font-mono bg-gray-50 dark:bg-gray-900 p-3 rounded overflow-auto max-h-96">
                {JSON.stringify(results, null, 2)}
              </pre>
            )}

            {results && resultView === "graph" && (
              <div style={{ width: "100%", height: "500px" }} className="rounded border border-gray-200 dark:border-gray-700">
                {(results.nodes?.length || 0) > 0 ? (
                  <GraphCanvas
                    key={`graph-${results.nodes.length}-${results.edges?.length || 0}`}
                    nodes={results.nodes || []}
                    edges={results.edges || []}
                    maxNodes={500}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-gray-400 text-sm">
                    No graph data. Return full nodes (e.g., RETURN path) instead of scalar fields for graph visualization.
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* DIALOGS */}

      {/* Add Node dialog */}
      {showAddNode && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/30 z-50" onClick={() => setShowAddNode(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-80" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-bold mb-3">Add Node Pattern</h3>
            <div className="space-y-2">
              <div>
                <label className="text-[10px] font-medium text-gray-500">Node Type (Label)</label>
                <select value={newNodeLabel} onChange={(e) => setNewNodeLabel(e.target.value)}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="">Any node type</option>
                  {nodeTypes.map((nt) => <option key={nt} value={nt}>{nt}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-medium text-gray-500">Alias</label>
                <input value={newNodeAlias} onChange={(e) => setNewNodeAlias(e.target.value)}
                  placeholder={`e.g., d, s, p (auto: n${model.nodes.length})`}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setShowAddNode(false)} className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600">Cancel</button>
              <button onClick={() => {
                addNode(newNodeLabel ? [newNodeLabel] : [], newNodeAlias || undefined);
                setShowAddNode(false);
                setNewNodeLabel("");
                setNewNodeAlias("");
              }} className="rounded bg-brand-600 px-3 py-1 text-xs text-white">Add</button>
            </div>
          </div>
        </div>
      )}

      {/* Add Relationship dialog */}
      {showAddRel && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/30 z-50" onClick={() => setShowAddRel(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-96" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-bold mb-3">Add Relationship</h3>
            <div className="space-y-2">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-[10px] font-medium text-gray-500">From</label>
                  <select value={newRelFrom} onChange={(e) => setNewRelFrom(e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="">Select...</option>
                    {model.nodes.map((n) => <option key={n.id} value={n.id}>{n.alias} (:{n.labels.join(":")})</option>)}
                  </select>
                </div>
                <div className="flex-1">
                  <label className="text-[10px] font-medium text-gray-500">To</label>
                  <select value={newRelTo} onChange={(e) => setNewRelTo(e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="">Select...</option>
                    {model.nodes.map((n) => <option key={n.id} value={n.id}>{n.alias} (:{n.labels.join(":")})</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[10px] font-medium text-gray-500">Relationship Type</label>
                <select value={newRelType} onChange={(e) => setNewRelType(e.target.value)}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="">Any type</option>
                  {edgeTypes.map((et) => <option key={et} value={et}>{et}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] font-medium text-gray-500">Direction</label>
                <select value={newRelDir} onChange={(e) => setNewRelDir(e.target.value as any)}
                  className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="outgoing">Outgoing (-&gt;)</option>
                  <option value="incoming">Incoming (&lt;-)</option>
                  <option value="undirected">Undirected (--)</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setShowAddRel(false)} className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600">Cancel</button>
              <button onClick={() => {
                if (newRelFrom && newRelTo) {
                  addRelationship(newRelFrom, newRelTo, newRelType ? [newRelType] : [], newRelDir);
                  setShowAddRel(false);
                  setNewRelType("");
                }
              }} disabled={!newRelFrom || !newRelTo}
                className="rounded bg-brand-600 px-3 py-1 text-xs text-white disabled:opacity-50">Add</button>
            </div>
          </div>
        </div>
      )}

      {/* Saved Queries dialog */}
      {showSaved && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/30 z-50" onClick={() => setShowSaved(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-96 max-h-[400px] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-bold mb-3">Saved Queries</h3>
            <div className="flex-1 overflow-y-auto space-y-1">
              {savedQueries.map((q: any) => (
                <button key={q.id} onClick={() => loadSavedQuery(q)}
                  className="w-full flex items-center justify-between rounded px-3 py-2 text-left text-xs hover:bg-brand-50 dark:hover:bg-gray-700">
                  <div>
                    <div className="font-medium text-gray-700 dark:text-gray-200">{q.name || "Untitled"}</div>
                    <div className="text-[10px] text-gray-400 truncate max-w-[250px]">{q.query?.slice(0, 60) || ""}</div>
                  </div>
                </button>
              ))}
              {savedQueries.length === 0 && <div className="text-xs text-gray-400 text-center py-4">No saved queries</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
