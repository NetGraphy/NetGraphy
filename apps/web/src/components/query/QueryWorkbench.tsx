/**
 * QueryWorkbench — Cypher editor + structured query builder + results viewer.
 *
 * Three-panel layout:
 * - Left: Saved queries (TODO)
 * - Center: Cypher editor (Monaco) or structured builder
 * - Bottom: Results as table or graph
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { queryApi } from "@/api/client";
import type { QueryResult } from "@/types/schema";

export function QueryWorkbench() {
  const [query, setQuery] = useState(
    "MATCH (d:Device) RETURN d.hostname AS hostname, d.status AS status, d.role AS role LIMIT 25",
  );
  const [resultView, setResultView] = useState<"table" | "graph" | "json">(
    "table",
  );

  const executeMutation = useMutation({
    mutationFn: (cypher: string) =>
      queryApi.executeCypher(cypher).then((r) => r.data.data as QueryResult),
  });

  const result = executeMutation.data;

  return (
    <div className="flex h-full flex-col">
      <h1 className="mb-4 text-2xl font-bold text-gray-900 dark:text-white">
        Query Workbench
      </h1>

      {/* Editor */}
      <div className="mb-4 flex-shrink-0">
        <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          {/* TODO: Replace with Monaco editor for Cypher syntax highlighting */}
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={6}
            className="w-full rounded-t-lg border-none bg-gray-900 p-4 font-mono text-sm text-green-400 focus:outline-none"
            placeholder="Enter Cypher query..."
          />
          <div className="flex items-center justify-between border-t border-gray-700 px-4 py-2">
            <div className="text-xs text-gray-500">
              {executeMutation.data?.metadata?.row_count !== undefined
                ? `${executeMutation.data.metadata.row_count} rows`
                : ""}
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
          <div className="flex h-full items-center justify-center text-gray-500">
            {/* TODO: Graph visualization with @xyflow/react */}
            Graph view coming in Phase 1
          </div>
        )}
      </div>
    </div>
  );
}
