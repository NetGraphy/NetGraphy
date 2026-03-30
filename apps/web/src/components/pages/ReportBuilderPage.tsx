/**
 * ReportBuilderPage — Schema-driven report builder with advanced filtering,
 * column selection, row expansion, preview, CSV export, and saved reports.
 */

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface ColumnDef {
  path: string;
  source: string;
  display_label: string;
  data_type?: string;
  relationship?: string;
  target_type?: string;
  causes_expansion?: boolean;
  sortable?: boolean;
  export_default?: boolean;
  formatter_hint?: string;
}

interface FilterPath {
  path: string;
  type: string;
  operators: string[];
  description?: string;
  enum_values?: string[];
}

interface FilterCondition {
  path: string;
  operator: string;
  value: string;
}

interface SelectedColumn {
  path: string;
  source: string;
  display_label: string;
  alias?: string;
}

type RowMode = "root" | "expanded" | "aggregate";

export function ReportBuilderPage() {
  const queryClient = useQueryClient();

  // --- State ---
  const [rootEntity, setRootEntity] = useState("");
  const [selectedColumns, setSelectedColumns] = useState<SelectedColumn[]>([]);
  const [filters, setFilters] = useState<FilterCondition[]>([]);
  const [rowMode, setRowMode] = useState<RowMode>("root");
  const [sortField, setSortField] = useState("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [limit, setLimit] = useState(50);
  const [groupBy, setGroupBy] = useState<string[]>([]);

  // Preview
  const [previewData, setPreviewData] = useState<{ columns: any[]; rows: any[]; total_count: number | null; csv_headers: string[] } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Saved reports
  const [showSaved, setShowSaved] = useState(false);
  const [reportName, setReportName] = useState("");
  const [saveFeedback, setSaveFeedback] = useState("");

  // --- Queries ---
  const { data: entitiesData } = useQuery({
    queryKey: ["report-entities"],
    queryFn: () => api.get("/reports/entities"),
  });
  const entities: { name: string; display_name: string; category: string }[] = entitiesData?.data?.data || [];

  const { data: columnsData } = useQuery({
    queryKey: ["report-columns", rootEntity],
    queryFn: () => api.get(`/reports/columns/${rootEntity}`),
    enabled: !!rootEntity,
  });
  const availableColumns: ColumnDef[] = columnsData?.data?.data || [];

  const { data: filtersData } = useQuery({
    queryKey: ["report-filters", rootEntity],
    queryFn: () => api.get(`/reports/filters/${rootEntity}`),
    enabled: !!rootEntity,
  });
  const filterPaths: FilterPath[] = filtersData?.data?.data?.filter_paths || [];

  const { data: savedData } = useQuery({
    queryKey: ["saved-reports"],
    queryFn: () => api.get("/reports/saved"),
    enabled: showSaved,
  });
  const savedReports: any[] = savedData?.data?.data || [];

  // Auto-detect row mode
  useEffect(() => {
    const hasExpansion = selectedColumns.some((sc) => {
      const col = availableColumns.find((c) => c.path === sc.path);
      return col?.causes_expansion;
    });
    if (hasExpansion && rowMode === "root") {
      setRowMode("expanded");
    }
  }, [selectedColumns, availableColumns]);

  // --- Actions ---
  const addColumn = useCallback((col: ColumnDef) => {
    if (selectedColumns.find((c) => c.path === col.path)) return;
    setSelectedColumns((prev) => [...prev, {
      path: col.path,
      source: col.source,
      display_label: col.display_label,
    }]);
  }, [selectedColumns]);

  const removeColumn = useCallback((path: string) => {
    setSelectedColumns((prev) => prev.filter((c) => c.path !== path));
  }, []);

  const moveColumn = useCallback((idx: number, dir: -1 | 1) => {
    setSelectedColumns((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }, []);

  const addFilter = useCallback(() => {
    setFilters((prev) => [...prev, { path: "", operator: "eq", value: "" }]);
  }, []);

  const updateFilter = useCallback((idx: number, field: keyof FilterCondition, value: string) => {
    setFilters((prev) => prev.map((f, i) => i === idx ? { ...f, [field]: value } : f));
  }, []);

  const removeFilter = useCallback((idx: number) => {
    setFilters((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const buildReportBody = useCallback(() => ({
    root_entity: rootEntity,
    columns: selectedColumns.map((c) => ({ path: c.path, source: c.source, display_label: c.display_label, alias: c.alias })),
    filters: filters.filter((f) => f.path && f.operator),
    row_mode: rowMode,
    sort: sortField || undefined,
    sort_direction: sortDir,
    limit,
    group_by: rowMode === "aggregate" ? groupBy : [],
  }), [rootEntity, selectedColumns, filters, rowMode, sortField, sortDir, limit, groupBy]);

  const runPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const resp = await api.post("/reports/execute", buildReportBody());
      setPreviewData(resp.data.data);
    } catch (err: any) {
      setPreviewData(null);
      alert(err?.response?.data?.detail || "Report execution failed");
    } finally {
      setPreviewLoading(false);
    }
  }, [buildReportBody]);

  const exportCsv = useCallback(async () => {
    try {
      const resp = await api.post("/reports/export/csv", { ...buildReportBody(), max_export_rows: 10000 }, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([resp.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${rootEntity.toLowerCase()}_report.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "CSV export failed");
    }
  }, [buildReportBody, rootEntity]);

  const saveReport = useCallback(async () => {
    try {
      await api.post("/reports/saved", {
        name: reportName || `${rootEntity} Report`,
        root_entity: rootEntity,
        definition: buildReportBody(),
        visibility: "personal",
      });
      setSaveFeedback("Saved");
      setTimeout(() => setSaveFeedback(""), 2000);
      queryClient.invalidateQueries({ queryKey: ["saved-reports"] });
    } catch { setSaveFeedback("Failed"); }
  }, [reportName, rootEntity, buildReportBody, queryClient]);

  const loadReport = useCallback((report: any) => {
    let def = report.definition;
    if (typeof def === "string") def = JSON.parse(def);
    setRootEntity(def.root_entity || report.root_entity || "");
    setSelectedColumns(def.columns || []);
    setFilters(def.filters || []);
    setRowMode(def.row_mode || "root");
    setSortField(def.sort || "");
    setLimit(def.limit || 50);
    setReportName(report.name || "");
    setShowSaved(false);
  }, []);

  // Group columns by source for the picker
  const rootColumns = availableColumns.filter((c) => c.source === "root");
  const relatedColumns = availableColumns.filter((c) => c.source === "related");
  const edgeColumns = availableColumns.filter((c) => c.source === "edge");
  const aggColumns = availableColumns.filter((c) => c.source === "aggregate");

  // Group related by relationship
  const relByRel: Record<string, ColumnDef[]> = {};
  relatedColumns.forEach((c) => {
    const key = c.relationship || "other";
    if (!relByRel[key]) relByRel[key] = [];
    relByRel[key].push(c);
  });

  return (
    <div className="flex h-[calc(100vh-64px)] gap-0">
      {/* Left: Builder */}
      <div className="flex w-[420px] flex-shrink-0 flex-col border-r border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 overflow-y-auto">
        {/* Entity selector */}
        <div className="border-b border-gray-200 p-3 dark:border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-semibold text-gray-500 uppercase">Root Entity</label>
            <div className="flex gap-1">
              <button onClick={() => setShowSaved(!showSaved)} className="text-[10px] text-brand-600 hover:underline">
                {showSaved ? "Hide" : "Saved Reports"}
              </button>
            </div>
          </div>
          <select value={rootEntity} onChange={(e) => { setRootEntity(e.target.value); setSelectedColumns([]); setFilters([]); setPreviewData(null); }}
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            <option value="">Select entity type...</option>
            {entities.map((e) => <option key={e.name} value={e.name}>{e.display_name} ({e.category})</option>)}
          </select>
        </div>

        {/* Saved reports dropdown */}
        {showSaved && (
          <div className="border-b border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900 max-h-48 overflow-y-auto">
            <div className="text-xs font-semibold text-gray-500 mb-1">Saved Reports</div>
            {savedReports.map((r) => (
              <button key={r.id} onClick={() => loadReport(r)}
                className="block w-full text-left rounded px-2 py-1 text-xs hover:bg-gray-100 dark:hover:bg-gray-700 truncate">
                {r.name} <span className="text-gray-400">({r.root_entity})</span>
              </button>
            ))}
            {savedReports.length === 0 && <div className="text-xs text-gray-400">No saved reports</div>}
          </div>
        )}

        {rootEntity && (
          <>
            {/* Filters */}
            <div className="border-b border-gray-200 p-3 dark:border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-semibold text-gray-500 uppercase">Filters</label>
                <button onClick={addFilter} className="text-[10px] text-brand-600 hover:underline">+ Add Filter</button>
              </div>
              {filters.map((f, i) => (
                <div key={i} className="mb-2 flex gap-1 items-start">
                  <select value={f.path} onChange={(e) => updateFilter(i, "path", e.target.value)}
                    className="flex-1 rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="">Field...</option>
                    {filterPaths.map((fp) => <option key={fp.path} value={fp.path}>{fp.path} ({fp.type})</option>)}
                  </select>
                  <select value={f.operator} onChange={(e) => updateFilter(i, "operator", e.target.value)}
                    className="w-20 rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    {(filterPaths.find((fp) => fp.path === f.path)?.operators || ["eq", "neq", "contains"]).map((op) => (
                      <option key={op} value={op}>{op}</option>
                    ))}
                  </select>
                  <input value={f.value} onChange={(e) => updateFilter(i, "value", e.target.value)}
                    placeholder="Value" className="w-24 rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                  <button onClick={() => removeFilter(i)} className="text-red-500 text-[11px] px-1">x</button>
                </div>
              ))}
              {filters.length === 0 && <div className="text-[11px] text-gray-400">No filters — all records will be included</div>}
            </div>

            {/* Column Picker */}
            <div className="border-b border-gray-200 p-3 dark:border-gray-700 flex-1 overflow-y-auto">
              <label className="text-xs font-semibold text-gray-500 uppercase mb-2 block">Available Columns</label>

              {/* Root fields */}
              <div className="mb-2">
                <div className="text-[10px] font-semibold text-gray-400 mb-1">Direct Fields</div>
                <div className="flex flex-wrap gap-1">
                  {rootColumns.map((c) => (
                    <button key={c.path} onClick={() => addColumn(c)}
                      disabled={!!selectedColumns.find((s) => s.path === c.path)}
                      className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] hover:bg-brand-50 hover:border-brand-300 disabled:opacity-30 dark:border-gray-600 dark:hover:bg-gray-700">
                      {c.display_label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Related fields grouped by relationship */}
              {Object.entries(relByRel).map(([rel, cols]) => (
                <div key={rel} className="mb-2">
                  <div className="text-[10px] font-semibold text-gray-400 mb-1">
                    {rel} {cols[0]?.causes_expansion && <span className="text-amber-500">(expands rows)</span>}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {cols.map((c) => (
                      <button key={c.path} onClick={() => addColumn(c)}
                        disabled={!!selectedColumns.find((s) => s.path === c.path)}
                        className="rounded-full border border-blue-200 px-2 py-0.5 text-[10px] text-blue-700 hover:bg-blue-50 hover:border-blue-400 disabled:opacity-30 dark:border-blue-800 dark:text-blue-300 dark:hover:bg-blue-900/20">
                        {c.display_label.split(" > ").pop()}
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              {/* Edge fields */}
              {edgeColumns.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] font-semibold text-gray-400 mb-1">Edge Attributes</div>
                  <div className="flex flex-wrap gap-1">
                    {edgeColumns.map((c) => (
                      <button key={c.path} onClick={() => addColumn(c)}
                        disabled={!!selectedColumns.find((s) => s.path === c.path)}
                        className="rounded-full border border-purple-200 px-2 py-0.5 text-[10px] text-purple-700 hover:bg-purple-50 disabled:opacity-30 dark:border-purple-800 dark:text-purple-300">
                        {c.display_label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Aggregates */}
              {aggColumns.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] font-semibold text-gray-400 mb-1">Aggregates</div>
                  <div className="flex flex-wrap gap-1">
                    {aggColumns.map((c) => (
                      <button key={c.path} onClick={() => addColumn(c)}
                        disabled={!!selectedColumns.find((s) => s.path === c.path)}
                        className="rounded-full border border-green-200 px-2 py-0.5 text-[10px] text-green-700 hover:bg-green-50 disabled:opacity-30 dark:border-green-800 dark:text-green-300">
                        {c.display_label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Row Mode */}
            <div className="border-b border-gray-200 p-3 dark:border-gray-700">
              <label className="text-xs font-semibold text-gray-500 uppercase mb-1 block">Row Mode</label>
              <div className="flex gap-2">
                {([
                  { value: "root", label: "One per entity", desc: "Collapse related" },
                  { value: "expanded", label: "Expanded", desc: "One per match" },
                  { value: "aggregate", label: "Aggregate", desc: "Group & count" },
                ] as const).map((m) => (
                  <button key={m.value} onClick={() => setRowMode(m.value)}
                    className={`flex-1 rounded border px-2 py-1.5 text-center text-[10px] ${rowMode === m.value ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/20 dark:text-brand-300" : "border-gray-200 text-gray-500 dark:border-gray-600"}`}>
                    <div className="font-semibold">{m.label}</div>
                    <div className="text-gray-400">{m.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Sort & Limit */}
            <div className="border-b border-gray-200 p-3 dark:border-gray-700">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-[10px] font-medium text-gray-500">Sort by</label>
                  <select value={sortField} onChange={(e) => setSortField(e.target.value)}
                    className="w-full rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="">Default</option>
                    {selectedColumns.map((c) => <option key={c.path} value={c.path}>{c.display_label}</option>)}
                  </select>
                </div>
                <div className="w-16">
                  <label className="text-[10px] font-medium text-gray-500">Dir</label>
                  <select value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")}
                    className="w-full rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </div>
                <div className="w-16">
                  <label className="text-[10px] font-medium text-gray-500">Limit</label>
                  <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} min={1} max={10000}
                    className="w-full rounded border border-gray-300 px-1 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="p-3 flex gap-2 flex-wrap">
              <button onClick={runPreview} disabled={selectedColumns.length === 0 || previewLoading}
                className="rounded bg-brand-600 px-3 py-1.5 text-xs text-white hover:bg-brand-700 disabled:opacity-50">
                {previewLoading ? "Running..." : "Preview"}
              </button>
              <button onClick={exportCsv} disabled={selectedColumns.length === 0}
                className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300">
                Export CSV
              </button>
              <div className="flex-1" />
              <input value={reportName} onChange={(e) => setReportName(e.target.value)} placeholder="Report name"
                className="w-32 rounded border border-gray-300 px-2 py-1 text-[11px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              <button onClick={saveReport} disabled={!rootEntity}
                className="rounded border border-brand-300 px-3 py-1.5 text-xs text-brand-600 hover:bg-brand-50 disabled:opacity-50">
                {saveFeedback || "Save"}
              </button>
            </div>
          </>
        )}
      </div>

      {/* Right: Selected columns + Preview */}
      <div className="flex-1 flex flex-col overflow-hidden bg-gray-50 dark:bg-gray-900">
        {/* Selected columns bar */}
        <div className="border-b border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-semibold text-gray-500 uppercase">Selected Columns ({selectedColumns.length})</label>
            {selectedColumns.length > 0 && (
              <button onClick={() => setSelectedColumns([])} className="text-[10px] text-red-500 hover:underline">Clear all</button>
            )}
          </div>
          <div className="flex flex-wrap gap-1">
            {selectedColumns.map((col, i) => {
              const meta = availableColumns.find((c) => c.path === col.path);
              const borderColor = col.source === "root" ? "border-gray-300"
                : col.source === "related" ? "border-blue-300"
                : col.source === "edge" ? "border-purple-300" : "border-green-300";
              return (
                <div key={col.path} className={`flex items-center gap-1 rounded border ${borderColor} bg-white px-2 py-0.5 text-[10px] dark:bg-gray-700`}>
                  <button onClick={() => moveColumn(i, -1)} className="text-gray-400 hover:text-gray-600" disabled={i === 0}>&lt;</button>
                  <span className="text-gray-700 dark:text-gray-200">{col.display_label}</span>
                  {meta?.causes_expansion && <span className="text-amber-500" title="Causes row expansion">*</span>}
                  <button onClick={() => removeColumn(col.path)} className="text-red-400 hover:text-red-600 ml-1">x</button>
                  <button onClick={() => moveColumn(i, 1)} className="text-gray-400 hover:text-gray-600" disabled={i === selectedColumns.length - 1}>&gt;</button>
                </div>
              );
            })}
            {selectedColumns.length === 0 && <div className="text-[11px] text-gray-400">Click columns on the left to add them to the report</div>}
          </div>
        </div>

        {/* Preview grid */}
        <div className="flex-1 overflow-auto p-3">
          {!previewData && !previewLoading && (
            <div className="flex h-full items-center justify-center">
              <div className="text-center text-gray-400">
                <svg className="mx-auto h-12 w-12 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <div className="text-sm">Select an entity, add columns, and click Preview</div>
              </div>
            </div>
          )}

          {previewLoading && <div className="flex h-full items-center justify-center text-gray-400">Running report...</div>}

          {previewData && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs text-gray-500">
                  {previewData.total_count !== null ? `${previewData.total_count} total results` : `${previewData.rows.length} rows`}
                  {rowMode === "expanded" && " (expanded)"}
                </span>
                <span className="text-[10px] text-gray-400">
                  CSV headers: {previewData.csv_headers.join(", ")}
                </span>
              </div>
              <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      {previewData.csv_headers.map((h) => (
                        <th key={h} className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-gray-500">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {previewData.rows.map((row, i) => (
                      <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                        {previewData.csv_headers.map((h) => (
                          <td key={h} className="px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap">
                            {row[h] != null ? String(row[h]) : <span className="text-gray-300">null</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {previewData.rows.length === 0 && (
                      <tr>
                        <td colSpan={previewData.csv_headers.length} className="px-3 py-6 text-center text-xs text-gray-400">
                          No results match the current filters
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
