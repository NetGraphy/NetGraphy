/**
 * FilterPane — Custom Jinja2 filter development IDE.
 *
 * Layout modeled after SNEP's custom filters page:
 * - Left: Filter explorer (built-in + custom + git-synced)
 * - Center: Monaco editor with metadata fields
 * - Right: Reference panel (available filters, data models, usage)
 * - Bottom: Test runner with input/expected/output
 */

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { api } from "@/api/client";

interface JinjaFilter {
  id: string;
  name: string;
  description: string;
  python_source: string;
  is_active: boolean;
  created_at: string;
}

interface BuiltinFilter {
  name: string;
  signature: string;
  description: string;
  full_doc: string;
  category: string;
}

const CATEGORIES = [
  { value: "network", label: "Network" },
  { value: "formatting", label: "Formatting" },
  { value: "calculation", label: "Calculation" },
  { value: "parsing", label: "Parsing" },
  { value: "validation", label: "Validation" },
  { value: "other", label: "Other" },
];

const CATEGORY_COLORS: Record<string, string> = {
  network: "bg-emerald-500/20 text-emerald-300",
  formatting: "bg-blue-500/20 text-blue-300",
  calculation: "bg-amber-500/20 text-amber-300",
  parsing: "bg-purple-500/20 text-purple-300",
  validation: "bg-rose-500/20 text-rose-300",
  "built-in": "bg-gray-500/20 text-gray-300",
  other: "bg-gray-500/20 text-gray-300",
};

const SAMPLE_FILTER = `def counter_delta(new_val, old_val):
    """Calculate the delta between two counter values, handling 32-bit wrap."""
    old = int(old_val)
    new = int(new_val)
    if new >= old:
        return str(new - old)
    return str(2**32 - old + new)`;

export function FilterPane() {
  const queryClient = useQueryClient();

  // Editor state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("other");
  const [parameters, setParameters] = useState("");
  const [source, setSource] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  // Test state
  const [testArgs, setTestArgs] = useState("");
  const [testExpected, setTestExpected] = useState("");
  const [testOutput, setTestOutput] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [testPassed, setTestPassed] = useState<boolean | null>(null);

  // UI state
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [explorerFilter, setExplorerFilter] = useState("");
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    "built-in": true,
    custom: true,
    git: true,
  });

  // Queries
  const { data: filtersData } = useQuery({
    queryKey: ["jinja-filters"],
    queryFn: () => api.get("/parsers/filters"),
  });
  const filters: JinjaFilter[] = filtersData?.data?.data || [];

  const { data: builtinData } = useQuery({
    queryKey: ["builtin-filters"],
    queryFn: () => api.get("/dev/builtin-filters"),
  });
  const builtinFilters: BuiltinFilter[] = builtinData?.data?.data || [];

  // Mutations
  const saveMutation = useMutation({
    mutationFn: () =>
      api.post("/parsers/filters", { name, description, python_source: source }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jinja-filters"] });
      setSaveError(null);
      setSaveSuccess(true);
      setDirty(false);
      setTimeout(() => setSaveSuccess(false), 2000);
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (typeof detail === "object" && detail !== null) {
        const d = detail as Record<string, unknown>;
        setSaveError(
          (d.validation_errors as string[])?.join("; ") ||
          (d.compilation_error as string) ||
          "Save failed",
        );
      } else {
        setSaveError(String(detail || "Save failed"));
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (filterName: string) => api.delete(`/parsers/filters/${filterName}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jinja-filters"] });
      newFilter();
    },
  });

  const handleTest = useCallback(async () => {
    if (!name) return;
    setTestOutput(null);
    setTestError(null);
    setTestPassed(null);
    try {
      let input = testArgs;
      // Parse JSON array for multi-arg
      let parsedArgs: unknown;
      try {
        parsedArgs = JSON.parse(testArgs);
      } catch {
        parsedArgs = testArgs;
      }

      const resp = await api.post(`/parsers/filters/${name}/test`, {
        input: Array.isArray(parsedArgs) ? parsedArgs[0] : parsedArgs,
        args: Array.isArray(parsedArgs) && parsedArgs.length > 1
          ? { old_val: parsedArgs[1] }
          : {},
      });
      const d = resp.data.data;
      if (d.error) {
        setTestError(d.error);
        setTestPassed(false);
      } else {
        const output = typeof d.output === "string" ? d.output : JSON.stringify(d.output);
        setTestOutput(output);
        if (testExpected) {
          setTestPassed(output === testExpected);
        }
      }
    } catch {
      setTestError("Filter not found — save it first");
      setTestPassed(false);
    }
  }, [name, testArgs, testExpected]);

  const loadFilter = (f: JinjaFilter) => {
    setName(f.name);
    setDescription(f.description);
    setSource(f.python_source);
    setEditingId(f.id);
    setDirty(false);
    setSaveError(null);
    setSaveSuccess(false);
    setTestOutput(null);
    setTestError(null);
    setTestPassed(null);
    // Extract parameters from function signature
    const match = f.python_source.match(/^def\s+\w+\(([^)]*)\)/m);
    if (match) setParameters(match[1]);
  };

  const loadBuiltin = (f: BuiltinFilter) => {
    setName(f.name);
    setDescription(f.description);
    setParameters(f.signature.replace(/^\(/, "").replace(/\)$/, ""));
    setSource(`# Built-in filter: ${f.name}\n# ${f.description}\n#\n# Signature: ${f.name}${f.signature}\n#\n${f.full_doc ? "# " + f.full_doc.split("\n").join("\n# ") : ""}`);
    setEditingId(null);
    setCategory("built-in");
    setDirty(false);
  };

  const newFilter = () => {
    setName("");
    setDescription("");
    setParameters("");
    setSource("");
    setCategory("other");
    setEditingId(null);
    setDirty(false);
    setSaveError(null);
    setSaveSuccess(false);
    setTestOutput(null);
    setTestError(null);
    setTestPassed(null);
  };

  const loadSample = () => {
    setName("counter_delta");
    setDescription("Calculate the delta between two counter values, handling 32-bit wrap");
    setParameters("new_val, old_val");
    setSource(SAMPLE_FILTER);
    setCategory("calculation");
    setEditingId(null);
    setDirty(true);
    setTestArgs("[100, 4294967290]");
    setTestExpected("106");
  };

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const filteredBuiltin = builtinFilters.filter(
    (f) => !explorerFilter || f.name.toLowerCase().includes(explorerFilter.toLowerCase()),
  );

  const filteredCustom = filters.filter(
    (f) => !explorerFilter || f.name.toLowerCase().includes(explorerFilter.toLowerCase()),
  );

  return (
    <div className="flex h-full">
      {/* ---- Left: Filter Explorer ---- */}
      <div className="flex w-64 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800">
        {/* Explorer header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Filters
          </span>
          <div className="flex gap-1">
            <button
              onClick={loadSample}
              className="rounded px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700 hover:text-gray-200"
              title="Load sample filter"
            >
              Sample
            </button>
            <button
              onClick={newFilter}
              className="rounded bg-brand-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-brand-500"
            >
              + New
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="border-b border-gray-700 px-3 py-2">
          <input
            type="text"
            value={explorerFilter}
            onChange={(e) => setExplorerFilter(e.target.value)}
            placeholder="Search filters..."
            className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          />
        </div>

        {/* Filter list */}
        <div className="flex-1 overflow-y-auto">
          {/* Built-in section */}
          <div>
            <button
              onClick={() => toggleSection("built-in")}
              className="flex w-full items-center gap-1 px-3 py-1.5 text-xs font-semibold uppercase text-gray-500 hover:text-gray-300"
            >
              <svg
                className={`h-3 w-3 transition-transform ${expandedSections["built-in"] ? "rotate-90" : ""}`}
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
              </svg>
              Built-in ({filteredBuiltin.length})
            </button>
            {expandedSections["built-in"] && (
              <div className="space-y-0.5 px-1">
                {filteredBuiltin.map((f) => (
                  <button
                    key={f.name}
                    onClick={() => loadBuiltin(f)}
                    className={`group flex w-full items-center justify-between rounded px-2 py-1.5 text-left ${
                      name === f.name && category === "built-in"
                        ? "bg-brand-600/20 text-brand-300"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{f.name}</div>
                      <div className="truncate text-xs text-gray-500">{f.description}</div>
                    </div>
                    <span className="ml-1 flex-shrink-0 rounded px-1 py-0.5 text-[10px] font-medium bg-gray-500/20 text-gray-400">
                      built-in
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Custom section */}
          <div className="mt-1">
            <button
              onClick={() => toggleSection("custom")}
              className="flex w-full items-center gap-1 px-3 py-1.5 text-xs font-semibold uppercase text-gray-500 hover:text-gray-300"
            >
              <svg
                className={`h-3 w-3 transition-transform ${expandedSections.custom ? "rotate-90" : ""}`}
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
              </svg>
              Custom ({filteredCustom.length})
            </button>
            {expandedSections.custom && (
              <div className="space-y-0.5 px-1">
                {filteredCustom.map((f) => (
                  <button
                    key={f.id || f.name}
                    onClick={() => loadFilter(f)}
                    className={`group flex w-full items-center justify-between rounded px-2 py-1.5 text-left ${
                      editingId === f.id
                        ? "bg-brand-600/20 text-brand-300"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{f.name}</div>
                      {f.description && (
                        <div className="truncate text-xs text-gray-500">{f.description}</div>
                      )}
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete filter "${f.name}"?`)) {
                          deleteMutation.mutate(f.name);
                        }
                      }}
                      className="ml-1 hidden flex-shrink-0 rounded px-1 py-0.5 text-xs text-red-400 hover:bg-red-900/30 hover:text-red-300 group-hover:block"
                    >
                      &times;
                    </button>
                  </button>
                ))}
                {filteredCustom.length === 0 && (
                  <div className="px-3 py-2 text-xs text-gray-500">No custom filters yet</div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ---- Center: Editor Area ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Metadata fields */}
        <div className="flex items-center gap-3 border-b border-gray-700 bg-gray-850 px-4 py-3" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <div className="flex-1">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Filter Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => { setName(e.target.value); setDirty(true); }}
              placeholder="e.g. counter_delta"
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div className="flex-1">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Parameters
            </label>
            <input
              type="text"
              value={parameters}
              onChange={(e) => setParameters(e.target.value)}
              placeholder="new_val, old_val"
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              readOnly
            />
          </div>
          <div className="w-40">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => { setCategory(e.target.value); setDirty(true); }}
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 focus:border-brand-500 focus:outline-none"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Description */}
        <div className="border-b border-gray-700 px-4 py-2" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
            Description
          </label>
          <input
            type="text"
            value={description}
            onChange={(e) => { setDescription(e.target.value); setDirty(true); }}
            placeholder="Calculate the delta between two counter values, handling 32-bit wrap"
            className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
          />
        </div>

        {/* Code Editor */}
        <div className="relative min-h-0 flex-1">
          {/* Action buttons */}
          <div className="absolute right-3 top-2 z-10 flex gap-2">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!name || !source || saveMutation.isPending || category === "built-in"}
              className="rounded bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-500 disabled:opacity-40"
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
            {editingId && (
              <button
                onClick={() => {
                  if (confirm(`Delete filter "${name}"?`)) {
                    deleteMutation.mutate(name);
                  }
                }}
                className="rounded bg-red-600/80 px-3 py-1 text-xs font-medium text-white hover:bg-red-500"
              >
                Delete
              </button>
            )}
          </div>

          {/* Status indicators */}
          {saveError && (
            <div className="absolute left-3 top-2 z-10 rounded bg-red-900/80 px-2 py-1 text-xs text-red-200">
              {saveError}
            </div>
          )}
          {saveSuccess && (
            <div className="absolute left-3 top-2 z-10 rounded bg-green-900/80 px-2 py-1 text-xs text-green-200">
              Filter saved successfully
            </div>
          )}

          <Editor
            height="100%"
            language="python"
            theme="vs-dark"
            value={source}
            onChange={(v) => { setSource(v || ""); setDirty(true); }}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 4,
              automaticLayout: true,
              padding: { top: 8, bottom: 8 },
              renderLineHighlight: "line",
              cursorBlinking: "smooth",
            }}
          />
        </div>

        {/* ---- Bottom: Test Runner ---- */}
        <div className="border-t border-gray-700" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <div className="flex items-center justify-between border-b border-gray-700/50 px-4 py-1.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Test Runner
            </span>
            <div className="flex items-center gap-2">
              {testPassed === true && (
                <span className="flex items-center gap-1 text-xs font-medium text-green-400">
                  <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  PASS
                </span>
              )}
              {testPassed === false && (
                <span className="flex items-center gap-1 text-xs font-medium text-red-400">
                  <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                  FAIL
                </span>
              )}
            </div>
          </div>
          <div className="flex items-start gap-4 px-4 py-3">
            <div className="flex-1">
              <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Test Args (JSON array)
              </label>
              <input
                type="text"
                value={testArgs}
                onChange={(e) => setTestArgs(e.target.value)}
                placeholder='[100, 4294967290]'
                className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              />
            </div>
            <div className="w-40">
              <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Expected
              </label>
              <input
                type="text"
                value={testExpected}
                onChange={(e) => setTestExpected(e.target.value)}
                placeholder="106"
                className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              />
            </div>
            <div className="flex-shrink-0 pt-4">
              <button
                onClick={handleTest}
                disabled={!name || !testArgs}
                className="rounded bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
              >
                Run Test
              </button>
            </div>
          </div>

          {/* Test output */}
          {(testOutput !== null || testError) && (
            <div className="border-t border-gray-700/50 px-4 py-2">
              {testOutput !== null && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">Output:</span>
                  <code className="font-mono text-sm text-green-300">{testOutput}</code>
                </div>
              )}
              {testError && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">Error:</span>
                  <code className="font-mono text-xs text-red-300">{testError}</code>
                </div>
              )}
            </div>
          )}

          {/* Usage hint */}
          <div className="border-t border-gray-700/50 px-4 py-2">
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="font-medium">Usage in templates:</span>
              <code className="rounded bg-gray-900 px-2 py-0.5 font-mono text-brand-300">
                {"{{ value | " + (name || "my_filter") + " }}"}
              </code>
              {parameters && parameters.includes(",") && (
                <code className="rounded bg-gray-900 px-2 py-0.5 font-mono text-brand-300">
                  {"{{ value | " + (name || "my_filter") + "(" + parameters.split(",").slice(1).map(s => s.trim()).join(", ") + ") }}"}
                </code>
              )}
            </div>
          </div>

          {/* Filter development guide */}
          <div className="border-t border-gray-700/50 px-4 py-2">
            <details className="group">
              <summary className="cursor-pointer text-xs font-semibold text-gray-400 hover:text-gray-200">
                Filter Development Guide
              </summary>
              <div className="mt-2 grid grid-cols-2 gap-4 text-xs text-gray-400">
                <div>
                  <div className="mb-1 font-medium text-gray-300">How it works</div>
                  <p className="text-gray-500">
                    Your code is the body of a Python function. The first parameter receives the
                    piped value in Jinja2 templates.
                  </p>
                  <div className="mt-1.5 space-y-1">
                    <div>
                      <span className="text-gray-400">Template:</span>{" "}
                      <code className="text-brand-300">{"{{ 45000000 | bits_to_human }}"}</code>
                    </div>
                    <div>
                      <span className="text-gray-400">Calls:</span>{" "}
                      <code className="text-brand-300">bits_to_human(45000000)</code>
                    </div>
                    <div>
                      <span className="text-gray-400">With args:</span>{" "}
                      <code className="text-brand-300">{"{{ 45.6 | pct(2) }}"}</code>
                    </div>
                    <div>
                      <span className="text-gray-400">Calls:</span>{" "}
                      <code className="text-brand-300">pct(45.6, 2)</code>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="mb-1 font-medium text-gray-300">Allowed Python Modules</div>
                  <div className="flex flex-wrap gap-1">
                    {["math", "ipaddress", "re", "json", "datetime", "hashlib", "base64",
                      "textwrap", "collections", "decimal", "statistics", "string", "functools",
                      "itertools", "operator"].map((mod) => (
                      <span key={mod} className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] font-medium text-gray-300">
                        {mod}
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 font-medium text-gray-300">Security</div>
                  <p className="text-gray-500">
                    Filters run in a sandboxed environment. Access to os, sys, subprocess, and
                    network modules is blocked.
                  </p>
                </div>
              </div>
            </details>
          </div>
        </div>
      </div>
    </div>
  );
}
