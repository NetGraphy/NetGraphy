/**
 * GraphExplorerPage — full-page interactive graph exploration.
 * Search for a starting node, expand neighbors, click to inspect properties.
 */

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { queryApi } from "@/api/client";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import type { GraphNode, GraphEdge, QueryResult } from "@/types/schema";

export function GraphExplorerPage() {
  const [search, setSearch] = useState("");
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const searchMutation = useMutation({
    mutationFn: (term: string) =>
      queryApi
        .executeCypher(
          "MATCH (n) WHERE n.hostname = $search OR n.name = $search RETURN n LIMIT 1",
          { search: term },
        )
        .then((r) => r.data.data as QueryResult),
    onSuccess: (result) => {
      setHasSearched(true);
      if (result.nodes.length > 0) {
        // Found a starting node; now expand its neighbors
        expandMutation.mutate(result.nodes[0].id);
      } else {
        setGraphNodes([]);
        setGraphEdges([]);
      }
    },
  });

  const expandMutation = useMutation({
    mutationFn: (nodeId: string) =>
      queryApi
        .executeCypher(
          "MATCH (n {id: $id})-[r]-(m) RETURN n, r, m",
          { id: nodeId },
        )
        .then((r) => r.data.data as QueryResult),
    onSuccess: (result) => {
      setGraphNodes((prev) => {
        const existingIds = new Set(prev.map((n) => n.id));
        const newNodes = result.nodes.filter((n) => !existingIds.has(n.id));
        return [...prev, ...newNodes];
      });
      setGraphEdges((prev) => {
        const existingIds = new Set(prev.map((e) => e.id));
        const newEdges = result.edges.filter((e) => !existingIds.has(e.id));
        return [...prev, ...newEdges];
      });
    },
  });

  const handleSearch = () => {
    if (!search.trim()) return;
    setGraphNodes([]);
    setGraphEdges([]);
    setSelectedNode(null);
    searchMutation.mutate(search.trim());
  };

  const handleNodeSelect = useCallback((node: GraphNode) => {
    setSelectedNode(node);
  }, []);

  const handleNodeExpand = useCallback(
    (node: GraphNode) => {
      expandMutation.mutate(node.id);
    },
    [expandMutation],
  );

  const handleClearGraph = () => {
    setGraphNodes([]);
    setGraphEdges([]);
    setSelectedNode(null);
    setHasSearched(false);
    setSearch("");
  };

  const isLoading = searchMutation.isPending || expandMutation.isPending;

  return (
    <div className="flex h-full flex-col">
      {/* Search Bar */}
      <div className="mb-4 flex flex-shrink-0 items-center gap-3">
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
            />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSearch();
            }}
            className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-gray-600 dark:bg-gray-800 dark:text-white"
            placeholder="Search by hostname or name..."
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={isLoading || !search.trim()}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {searchMutation.isPending ? "Searching..." : "Search"}
        </button>
        {graphNodes.length > 0 && (
          <button
            onClick={handleClearGraph}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Error */}
      {searchMutation.isError && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          Search error: {String(searchMutation.error)}
        </div>
      )}

      {/* Loading indicator for expansion */}
      {expandMutation.isPending && (
        <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
          Expanding node neighbors...
        </div>
      )}

      {/* Graph + Detail Sidebar */}
      <div className="flex min-h-0 flex-1 gap-0">
        {/* Graph Canvas */}
        <div className="flex-1 overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          {graphNodes.length > 0 ? (
            <GraphCanvas
              nodes={graphNodes}
              edges={graphEdges}
              onNodeSelect={handleNodeSelect}
              onNodeExpand={handleNodeExpand}
              className="h-full"
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <svg
                  className="mx-auto mb-3 h-12 w-12 text-gray-300"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7.5 3.75H6A2.25 2.25 0 003.75 6v1.5M16.5 3.75H18A2.25 2.25 0 0120.25 6v1.5M20.25 16.5V18A2.25 2.25 0 0118 20.25h-1.5M3.75 16.5V18A2.25 2.25 0 006 20.25h1.5M12 9v6m-3-3h6"
                  />
                </svg>
                <p className="text-sm font-medium text-gray-500">
                  {hasSearched
                    ? "No nodes found for that search"
                    : "Search for a node to begin exploring"}
                </p>
                <p className="mt-1 text-xs text-gray-400">
                  {hasSearched
                    ? "Try a different hostname or name"
                    : "Enter a hostname or name and press Enter"}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Detail Sidebar */}
        {selectedNode && (
          <div className="ml-3 w-80 flex-shrink-0 overflow-y-auto rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                  {selectedNode.label}
                </h3>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
              <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                {selectedNode.node_type}
              </span>
            </div>
            <div className="px-4 py-3">
              <h4 className="mb-2 text-xs font-medium uppercase text-gray-500 dark:text-gray-400">
                Properties
              </h4>
              <dl className="space-y-2">
                {Object.entries(selectedNode.properties).map(
                  ([key, value]) => (
                    <div key={key}>
                      <dt className="text-xs font-medium text-gray-500 dark:text-gray-400">
                        {key}
                      </dt>
                      <dd className="mt-0.5 break-all text-sm text-gray-900 dark:text-white">
                        {typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value ?? "\u2014")}
                      </dd>
                    </div>
                  ),
                )}
                {Object.keys(selectedNode.properties).length === 0 && (
                  <p className="text-sm text-gray-400">No properties</p>
                )}
              </dl>
            </div>
            <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700">
              <button
                onClick={() => expandMutation.mutate(selectedNode.id)}
                disabled={expandMutation.isPending}
                className="w-full rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
              >
                Expand Neighbors
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Stats bar */}
      {graphNodes.length > 0 && (
        <div className="mt-2 flex-shrink-0 text-xs text-gray-500 dark:text-gray-400">
          {graphNodes.length} nodes, {graphEdges.length} edges
          {selectedNode && <span> | Selected: {selectedNode.label}</span>}
        </div>
      )}
    </div>
  );
}
