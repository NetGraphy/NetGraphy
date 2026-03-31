/**
 * QueryWorkbench — Cypher editor + structured query builder + results viewer.
 *
 * Three-panel layout:
 * - Left: Saved queries sidebar
 * - Center: Cypher editor (Monaco) with syntax highlighting
 * - Bottom: Results as table, graph, or JSON
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { queryApi } from "@/api/client";
import { CypherEditor } from "@/components/query/CypherEditor";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import type { QueryResult } from "@/types/schema";

interface SavedQuery {
  id: string;
  name: string;
  query?: string;
  cypher?: string;
  description?: string;
}

export function QueryWorkbench() {
  const [query, setQuery] = useState(
    "MATCH (d:Device) RETURN d.hostname AS hostname, d.status AS status, d.role AS role LIMIT 25",
  );
  const [resultView, setResultView] = useState<"table" | "graph" | "json">(
    "table",
  );
  const [showSavedPanel, setShowSavedPanel] = useState(true);
  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  const queryClient = useQueryClient();

  const executeMutation = useMutation({
    mutationFn: (cypher: string) =>
      queryApi.executeCypher(cypher).then((r) => r.data.data as QueryResult),
  });

  const { data: savedData } = useQuery({
    queryKey: ["saved-queries"],
    queryFn: () =>
      queryApi.listSaved().then((r) => {
        const d = r.data?.data || r.data;
        return (d?.items || d || []) as SavedQuery[];
      }),
  });

  const savedQueries = savedData || [];

  const saveMutation = useMutation({
    mutationFn: (data: { name: string; query: string }) =>
      queryApi.saveQuery(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      setSaveName("");
      setShowSaveInput(false);
    },
  });

  const result = executeMutation.data;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Query Workbench
        </h1>
        <button
          onClick={() => setShowSavedPanel(!showSavedPanel)}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
        >
          {showSavedPanel ? "Hide" : "Show"} Saved Queries
        </button>
      </div>

      <div className="flex min-h-0 flex-1 gap-3">
        {/* Saved Queries Sidebar */}
        {showSavedPanel && (
          <div className="w-56 flex-shrink-0 overflow-y-auto rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <div className="border-b border-gray-200 px-3 py-2 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase text-gray-500 dark:text-gray-400">
                  Saved Queries
                </h3>
                <button
                  onClick={() => setShowSaveInput(!showSaveInput)}
                  className="text-xs text-brand-600 hover:text-brand-700"
                >
                  + Save
                </button>
              </div>
              {showSaveInput && (
                <div className="mt-2 flex gap-1">
                  <input
                    type="text"
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && saveName.trim()) {
                        saveMutation.mutate({
                          name: saveName.trim(),
                          query,
                        });
                      }
                    }}
                    className="min-w-0 flex-1 rounded border border-gray-300 px-1.5 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    placeholder="Query name..."
                  />
                  <button
                    onClick={() => {
                      if (saveName.trim()) {
                        saveMutation.mutate({
                          name: saveName.trim(),
                          query,
                        });
                      }
                    }}
                    disabled={saveMutation.isPending || !saveName.trim()}
                    className="rounded bg-brand-600 px-2 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50"
                  >
                    Save
                  </button>
                </div>
              )}
            </div>
            <div className="divide-y divide-gray-100 dark:divide-gray-700">
              {savedQueries.map((sq: SavedQuery) => (
                <div
                  key={sq.id}
                  className="flex items-center justify-between px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <button
                    onClick={() => setQuery(sq.cypher || sq.query || "")}
                    className="flex-1 text-left"
                  >
                    <div className="text-sm font-medium text-gray-900 dark:text-white">
                      {sq.name}
                    </div>
                    {(sq.cypher || sq.query) && (
                      <div className="mt-0.5 truncate text-[10px] text-gray-400 max-w-[200px] font-mono">
                        {(sq.cypher || sq.query || "").slice(0, 50)}...
                      </div>
                    )}
                  </button>
                  <button
                    onClick={async () => {
                      if (confirm(`Delete "${sq.name}"?`)) {
                        try {
                          await queryApi.deleteSaved(sq.id);
                          queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
                        } catch { /* ignore */ }
                      }
                    }}
                    className="ml-2 flex-shrink-0 text-[10px] text-red-400 hover:text-red-600"
                    title="Delete query"
                  >
                    x
                  </button>
                </div>
              ))}
              {savedQueries.length === 0 && (
                <div className="px-3 py-4 text-center text-xs text-gray-400">
                  No saved queries yet
                </div>
              )}
            </div>
          </div>
        )}

        {/* Main Content */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Editor */}
          <div className="mb-4 flex-shrink-0">
            <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              <CypherEditor
                value={query}
                onChange={setQuery}
                onExecute={() => executeMutation.mutate(query)}
              />
              <div className="flex items-center justify-between border-t border-gray-700 px-4 py-2">
                <div className="text-xs text-gray-500">
                  {executeMutation.data?.metadata?.row_count !== undefined
                    ? `${executeMutation.data.metadata.row_count} rows`
                    : "Ctrl+Enter to execute"}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => executeMutation.mutate(query)}
                    disabled={executeMutation.isPending}
                    className="rounded bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                  >
                    {executeMutation.isPending ? "Running..." : "Run Query"}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Result view toggle */}
          <div className="mb-2 flex gap-2">
            {(["table", "graph", "json"] as const).map((view) => (
              <button
                key={view}
                onClick={() => setResultView(view)}
                className={`rounded px-3 py-1 text-sm ${
                  resultView === view
                    ? "bg-brand-100 text-brand-700"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                {view.charAt(0).toUpperCase() + view.slice(1)}
              </button>
            ))}
          </div>

          {/* Results */}
          <div className="flex-1 overflow-auto rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            {executeMutation.error ? (
              <div className="p-4 text-red-500">
                Error: {String(executeMutation.error)}
              </div>
            ) : !result ? (
              <div className="p-8 text-center text-gray-500">
                Run a query to see results
              </div>
            ) : resultView === "table" ? (
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-900">
                  <tr>
                    {result.columns.map((col) => (
                      <th
                        key={col}
                        className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {result.columns.map((col) => (
                        <td key={col} className="px-4 py-2 text-sm">
                          {typeof row[col] === "object"
                            ? JSON.stringify(row[col])
                            : String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : resultView === "json" ? (
              <pre className="p-4 text-sm">
                {JSON.stringify(result, null, 2)}
              </pre>
            ) : (
              <div className="h-full">
                <GraphCanvas
                  nodes={result.nodes || []}
                  edges={result.edges || []}
                  className="h-full"
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
