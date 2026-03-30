/**
 * FilterEditorPage — IDE for writing custom Jinja2 filter functions in Python.
 *
 * Provides a Monaco editor for code, test panel for trying filters,
 * and CRUD for managing saved filters.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

const SAMPLE_FILTER = `def classify_inventory_type(name: str) -> str:
    """Classify a 'show inventory' NAME into an item_type enum."""
    name_lower = name.lower()
    if "power supply" in name_lower or "psu" in name_lower:
        return "power_supply"
    if "fan" in name_lower:
        return "fan"
    if "supervisor" in name_lower:
        return "supervisor"
    if "module" in name_lower or "nim" in name_lower:
        return "module"
    if "sfp" in name_lower or "transceiver" in name_lower:
        return "optic"
    return "other"`;

interface JinjaFilter {
  id: string;
  name: string;
  description: string;
  python_source: string;
  is_active: boolean;
  created_at: string;
}

export function FilterEditorPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState("");
  const [testInput, setTestInput] = useState("");
  const [testOutput, setTestOutput] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const { data: filtersData } = useQuery({
    queryKey: ["jinja-filters"],
    queryFn: () => api.get("/parsers/filters"),
  });
  const filters: JinjaFilter[] = filtersData?.data?.data || [];

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post("/parsers/filters", { name, description, python_source: source }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jinja-filters"] });
      setSaveError(null);
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jinja-filters"] }),
  });

  const handleTest = async () => {
    if (!name) return;
    setTestOutput(null);
    setTestError(null);
    try {
      const resp = await api.post(`/parsers/filters/${name}/test`, { input: testInput });
      const d = resp.data.data;
      if (d.error) {
        setTestError(d.error);
      } else {
        setTestOutput(typeof d.output === "string" ? d.output : JSON.stringify(d.output));
      }
    } catch {
      setTestError("Filter not found — save it first");
    }
  };

  const loadFilter = (f: JinjaFilter) => {
    setName(f.name);
    setDescription(f.description);
    setSource(f.python_source);
    setEditingId(f.id);
    setSaveError(null);
    setTestOutput(null);
    setTestError(null);
  };

  const newFilter = () => {
    setName("");
    setDescription("");
    setSource("");
    setEditingId(null);
    setSaveError(null);
    setTestOutput(null);
    setTestError(null);
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Jinja2 Filter Editor</h1>
          <p className="mt-1 text-sm text-gray-500">
            Write Python functions that can be used as Jinja2 filters in ingestion mapping templates.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={newFilter}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            New Filter
          </button>
          <button
            onClick={() => { setName("classify_inventory_type"); setSource(SAMPLE_FILTER); setDescription("Classify inventory items by name"); }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Load Sample
          </button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-6">
        {/* Filter list */}
        <div className="col-span-1">
          <h3 className="mb-2 text-sm font-semibold text-gray-500">Saved Filters</h3>
          <div className="space-y-1">
            {filters.map((f) => (
              <div
                key={f.id || f.name}
                className={`flex items-center justify-between rounded-md px-3 py-2 text-sm cursor-pointer ${
                  editingId === f.id ? "bg-brand-50 text-brand-700" : "hover:bg-gray-50"
                }`}
                onClick={() => loadFilter(f)}
              >
                <div>
                  <div className="font-medium">{f.name}</div>
                  {f.description && (
                    <div className="text-xs text-gray-400">{f.description}</div>
                  )}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(f.name); }}
                  className="text-xs text-red-400 hover:text-red-600"
                >
                  &times;
                </button>
              </div>
            ))}
            {filters.length === 0 && (
              <p className="text-xs text-gray-400 px-3 py-2">No custom filters yet</p>
            )}
          </div>
        </div>

        {/* Editor */}
        <div className="col-span-2">
          <div className="mb-3 flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-gray-500">Filter Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. classify_inventory_type"
                className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-gray-500">Description</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this filter does"
                className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
              />
            </div>
          </div>

          <label className="mb-1 block text-xs font-medium text-gray-500">
            Python Source (must define exactly one function)
          </label>
          <textarea
            value={source}
            onChange={(e) => setSource(e.target.value)}
            rows={16}
            spellCheck={false}
            className="w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-mono text-sm leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="def my_filter(value: str) -> str:&#10;    return value.upper()"
          />

          {saveError && (
            <div className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">{saveError}</div>
          )}

          <div className="mt-3 flex gap-2">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!name || !source || saveMutation.isPending}
              className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Filter"}
            </button>
          </div>
        </div>

        {/* Test panel */}
        <div className="col-span-1">
          <h3 className="mb-2 text-sm font-semibold text-gray-500">Test Filter</h3>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <label className="mb-1 block text-xs font-medium text-gray-500">Input Value</label>
            <input
              type="text"
              value={testInput}
              onChange={(e) => setTestInput(e.target.value)}
              placeholder='e.g. "Power Supply Module 0"'
              className="mb-3 w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
            />
            <button
              onClick={handleTest}
              disabled={!name || !testInput}
              className="w-full rounded-md bg-gray-100 px-3 py-1.5 text-sm font-medium hover:bg-gray-200 disabled:opacity-50"
            >
              Run Test
            </button>

            {testOutput !== null && (
              <div className="mt-3 rounded-md bg-green-50 px-3 py-2">
                <div className="text-xs font-medium text-green-600">Output:</div>
                <div className="mt-1 font-mono text-sm text-green-800">{testOutput}</div>
              </div>
            )}
            {testError && (
              <div className="mt-3 rounded-md bg-red-50 px-3 py-2">
                <div className="text-xs font-medium text-red-600">Error:</div>
                <div className="mt-1 font-mono text-xs text-red-700">{testError}</div>
              </div>
            )}

            <div className="mt-4 border-t border-gray-100 pt-3">
              <h4 className="mb-1 text-xs font-medium text-gray-500">Usage in Mapping</h4>
              <code className="block rounded bg-gray-50 px-2 py-1 text-xs text-gray-600">
                {"{{ parsed.NAME | " + (name || "my_filter") + " }}"}
              </code>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
