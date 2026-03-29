/**
 * GraphExplorerPage — full-page interactive graph exploration.
 * Search for a starting node, expand neighbors, click to inspect properties.
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { queryApi } from "@/api/client";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import type { GraphNode, GraphEdge, QueryResult } from "@/types/schema";

interface SearchResult {
  id: string;
  label: string;
  node_type: string;
}

export function GraphExplorerPage() {
  const [search, setSearch] = useState("");
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [selectedItems, setSelectedItems] = useState<SearchResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout>>();

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Autocomplete search with debounce
  const handleInputChange = (value: string) => {
    setSearch(value);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    if (value.trim().length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }
    searchTimeout.current = setTimeout(() => {
      queryApi
        .executeCypher(
          "MATCH (n) WHERE toLower(n.hostname) CONTAINS $term OR toLower(n.name) CONTAINS $term OR toLower(n.address) CONTAINS $term OR toLower(n.prefix) CONTAINS $term OR toLower(n.model) CONTAINS $term OR toString(n.asn) CONTAINS $term OR toLower(n.slug) CONTAINS $term RETURN n LIMIT 15",
          { term: value.trim().toLowerCase() },
        )
        .then((r) => {
          const result = r.data.data as QueryResult;
          const items: SearchResult[] = result.nodes.map((node) => ({
            id: node.id,
            label: node.label,
            node_type: node.node_type,
          }));
          setSuggestions(items);
          setShowDropdown(items.length > 0);
        })
        .catch(() => {
          setSuggestions([]);
          setShowDropdown(false);
        });
    }, 250);
  };

  const addSelectedItem = (item: SearchResult) => {
    if (!selectedItems.find((s) => s.id === item.id)) {
      setSelectedItems((prev) => [...prev, item]);
    }
    setSearch("");
    setSuggestions([]);
    setShowDropdown(false);
  };

  const removeSelectedItem = (id: string) => {
    setSelectedItems((prev) => prev.filter((s) => s.id !== id));
  };

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

  // Free-text search mutation — find nodes and expand them directly
  const freeSearchMutation = useMutation({
    mutationFn: (term: string) =>
      queryApi
        .executeCypher(
          "MATCH (n) WHERE toLower(n.hostname) CONTAINS $term OR toLower(n.name) CONTAINS $term OR toLower(n.address) CONTAINS $term OR toLower(n.prefix) CONTAINS $term RETURN n LIMIT 5",
          { term: term.toLowerCase() },
        )
        .then((r) => r.data.data as QueryResult),
    onSuccess: (result) => {
      if (result.nodes.length > 0) {
        for (const node of result.nodes) {
          expandMutation.mutate(node.id);
        }
      }
    },
  });

  const handleSearch = () => {
    setGraphNodes([]);
    setGraphEdges([]);
    setSelectedNode(null);
    setHasSearched(true);

    if (selectedItems.length > 0) {
      // Expand all selected chips
      for (const item of selectedItems) {
        expandMutation.mutate(item.id);
      }
    } else if (search.trim()) {
      // Free-text fallback: search and expand matches
      freeSearchMutation.mutate(search.trim());
    } else {
      return; // nothing to search
    }
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
    setSelectedItems([]);
    setSuggestions([]);
  };

  const isLoading = expandMutation.isPending || freeSearchMutation.isPending;

  return (
    <div className="flex h-full flex-col">
      {/* Search Bar */}
      <div className="mb-4 flex flex-shrink-0 items-center gap-3">
        <div className="relative flex-1" ref={dropdownRef}>
          {/* Selected chips */}
          <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2 py-1.5 focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500">
            {selectedItems.map((item) => (
              <span
                key={item.id}
                className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700"
              >
                {item.label}
                <span className="text-[9px] text-brand-400">{item.node_type}</span>
                <button
                  onClick={() => removeSelectedItem(item.id)}
                  className="ml-0.5 text-brand-400 hover:text-brand-600"
                >
                  &times;
                </button>
              </span>
            ))}
            <input
              type="text"
              value={search}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && showDropdown && suggestions.length > 0) {
                  addSelectedItem(suggestions[0]);
                } else if (e.key === "Enter") {
                  handleSearch();
                } else if (e.key === "Backspace" && !search && selectedItems.length > 0) {
                  removeSelectedItem(selectedItems[selectedItems.length - 1].id);
                }
              }}
              onFocus={() => { if (suggestions.length > 0) setShowDropdown(true); }}
              className="min-w-[120px] flex-1 border-none bg-transparent py-0.5 text-sm outline-none placeholder-gray-400"
              placeholder={selectedItems.length === 0 ? "Search devices, prefixes, locations..." : "Add more..."}
            />
          </div>

          {/* Autocomplete dropdown */}
          {showDropdown && suggestions.length > 0 && (() => {
            const unselected = suggestions.filter(
              (s) => !selectedItems.find((sel) => sel.id === s.id),
            );
            if (unselected.length === 0) return null;
            return (
              <div className="absolute left-0 right-0 z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                {unselected.length > 1 && (
                  <button
                    onMouseDown={(e) => {
                      e.preventDefault();
                      for (const item of unselected) {
                        if (!selectedItems.find((s) => s.id === item.id)) {
                          setSelectedItems((prev) => [...prev, item]);
                        }
                      }
                      setSearch("");
                      setSuggestions([]);
                      setShowDropdown(false);
                    }}
                    className="flex w-full items-center gap-2 border-b border-gray-100 px-3 py-2 text-left text-xs font-medium text-brand-600 hover:bg-brand-50"
                  >
                    + Add all {unselected.length} results
                  </button>
                )}
                {unselected.map((item) => (
                  <button
                    key={item.id}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      addSelectedItem(item);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
                  >
                    <span className="font-medium text-gray-900">{item.label}</span>
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                      {item.node_type}
                    </span>
                  </button>
                ))}
              </div>
            );
          })()}
        </div>
        <button
          onClick={handleSearch}
          disabled={isLoading || (selectedItems.length === 0 && !search.trim())}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {isLoading ? "Loading..." : "Search"}
        </button>
        {graphNodes.length > 0 && (
          <button
            onClick={handleClearGraph}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            Clear
          </button>
        )}
      </div>

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
                    : "Search for nodes to begin exploring"}
                </p>
                <p className="mt-1 text-xs text-gray-400">
                  {hasSearched
                    ? "Try a different search term"
                    : "Type a partial name to find matches, select multiple nodes, then click Search"}
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
