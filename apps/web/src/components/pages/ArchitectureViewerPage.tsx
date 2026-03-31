/**
 * ArchitectureViewerPage — Curated, saved graph architecture views.
 *
 * Supports:
 * - Create architecture from a Cypher query
 * - Multiple layout modes (hierarchical, tiered, force, radial, path)
 * - Manual node arrangement with drag-and-pin
 * - Save/load persistent layouts
 * - Architecture library for reuse
 * - Interface collapse/expand per node
 * - Node grouping by type
 */

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Controls,
  MiniMap,
  Background,
  Panel,
  type Node,
  type Edge,
  type NodeDragHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, queryApi } from "@/api/client";
import { applyLayout, type LayoutMode } from "@/lib/graphLayout";
import { CustomNode } from "@/components/graph/CustomNode";
import { CustomEdge } from "@/components/graph/CustomEdge";
import type { GraphNode, GraphEdge } from "@/types/schema";

const nodeTypes = { custom: CustomNode };
const edgeTypes = { custom: CustomEdge };

// Convert graph data to React Flow format
function toFlowNodes(graphNodes: GraphNode[]): Node[] {
  return graphNodes.map((gn) => ({
    id: gn.id,
    type: "custom",
    position: { x: 0, y: 0 },
    data: {
      nodeType: gn.node_type,
      label: gn.label,
      properties: gn.properties,
      graphNodeId: gn.id,
    },
  }));
}

function toFlowEdges(graphEdges: GraphEdge[]): Edge[] {
  return graphEdges.map((ge) => ({
    id: ge.id,
    source: ge.source_id,
    target: ge.target_id,
    type: "custom",
    data: { edgeType: ge.edge_type, properties: ge.properties },
  }));
}

// --------------------------------------------------------------------------
// Architecture Viewer Inner (needs ReactFlowProvider)
// --------------------------------------------------------------------------

function ArchitectureViewerInner() {
  const queryClient = useQueryClient();
  const { fitView } = useReactFlow();

  // Architecture state
  const [architectureId, setArchitectureId] = useState<string | null>(null);
  const [architectureName, setArchitectureName] = useState("New Architecture");
  const [architectureType, setArchitectureType] = useState("topology");
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("role-tiered");
  const [description, setDescription] = useState("");

  // Query input
  const [cypherQuery, setCypherQuery] = useState(
    "MATCH (d:Device)-[:HAS_INTERFACE]->(i:Interface)-[:CONNECTED_TO]-(i2:Interface)<-[:HAS_INTERFACE]-(d2:Device)\nWHERE d.hostname CONTAINS 'DAL'\nRETURN d, i, i2, d2\nLIMIT 100"
  );
  const [queryError, setQueryError] = useState("");

  // Graph data
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);

  // Pinned nodes (manually positioned)
  const [pinnedPositions, setPinnedPositions] = useState<Map<string, { x: number; y: number }>>(new Map());

  // UI state
  const [showLibrary, setShowLibrary] = useState(false);
  const [showQuery, setShowQuery] = useState(true);
  const [saveFeedback, setSaveFeedback] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Architecture library
  const { data: archData } = useQuery({
    queryKey: ["architectures"],
    queryFn: () => api.get("/architectures"),
    enabled: showLibrary,
  });
  const architectures: any[] = archData?.data?.data || [];

  // Convert to flow format
  const rawFlowNodes = useMemo(() => toFlowNodes(graphNodes), [graphNodes]);
  const flowEdges = useMemo(() => toFlowEdges(graphEdges), [graphEdges]);

  // Apply layout with pinned node overrides
  const laidOutNodes = useMemo(() => {
    if (rawFlowNodes.length === 0) return [];
    const laid = applyLayout(layoutMode, rawFlowNodes, flowEdges, "TB");
    // Override positions for pinned nodes
    return laid.map((node) => {
      const pinned = pinnedPositions.get(node.id);
      if (pinned) {
        return { ...node, position: pinned };
      }
      return node;
    });
  }, [rawFlowNodes, flowEdges, layoutMode, pinnedPositions]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidOutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  useEffect(() => { setNodes(laidOutNodes); }, [laidOutNodes, setNodes]);
  useEffect(() => { setEdges(flowEdges); }, [flowEdges, setEdges]);
  useEffect(() => { if (nodes.length > 0) setTimeout(() => fitView({ padding: 0.1 }), 100); }, [nodes.length]);

  // --- Actions ---

  const executeQuery = useCallback(async () => {
    setLoading(true);
    setQueryError("");
    try {
      const resp = await queryApi.executeCypher(cypherQuery);
      const data = resp.data.data;
      setGraphNodes(data.nodes || []);
      setGraphEdges(data.edges || []);
      setPinnedPositions(new Map());
      if ((data.nodes?.length || 0) === 0) {
        setQueryError("Query returned no graph nodes. Use RETURN with full nodes, not scalar fields.");
      }
    } catch (err: any) {
      setQueryError(err?.response?.data?.detail || "Query failed");
    } finally {
      setLoading(false);
    }
  }, [cypherQuery]);

  const onNodeDragStop: NodeDragHandler = useCallback((_event, node) => {
    setPinnedPositions((prev) => {
      const next = new Map(prev);
      next.set(node.id, node.position);
      return next;
    });
  }, []);

  const unpinAll = useCallback(() => {
    setPinnedPositions(new Map());
  }, []);

  const unpinNode = useCallback((nodeId: string) => {
    setPinnedPositions((prev) => {
      const next = new Map(prev);
      next.delete(nodeId);
      return next;
    });
  }, []);

  // Save architecture
  const saveArchitecture = useCallback(async () => {
    try {
      const positions = nodes.map((n) => ({
        node_id: n.id,
        x: Math.round(n.position.x),
        y: Math.round(n.position.y),
        pinned: pinnedPositions.has(n.id),
        layer: 0,
        group_id: "",
      }));

      if (architectureId) {
        // Update existing
        await api.patch(`/architectures/${architectureId}`, {
          name: architectureName,
          description,
          layout_mode: layoutMode,
          architecture_type: architectureType,
        });
        await api.put(`/architectures/${architectureId}/layout`, { positions });
      } else {
        // Create new
        const resp = await api.post("/architectures", {
          name: architectureName,
          description,
          architecture_type: architectureType,
          scope_query: cypherQuery,
          layout_mode: layoutMode,
        });
        const newId = resp.data?.data?.id;
        if (newId) {
          setArchitectureId(newId);
          await api.put(`/architectures/${newId}/layout`, { positions });
        }
      }
      setSaveFeedback("Saved");
      setTimeout(() => setSaveFeedback(""), 2000);
      queryClient.invalidateQueries({ queryKey: ["architectures"] });
    } catch {
      setSaveFeedback("Failed");
      setTimeout(() => setSaveFeedback(""), 2000);
    }
  }, [architectureId, architectureName, description, layoutMode, architectureType, cypherQuery, nodes, pinnedPositions, queryClient]);

  // Load architecture
  const loadArchitecture = useCallback(async (arch: any) => {
    setArchitectureId(arch.id);
    setArchitectureName(arch.name || "");
    setDescription(arch.description || "");
    setArchitectureType(arch.architecture_type || "topology");
    setLayoutMode(arch.layout_mode || "role-tiered");
    if (arch.scope_query) setCypherQuery(arch.scope_query);
    setShowLibrary(false);

    // Load layout positions
    try {
      const resp = await api.get(`/architectures/${arch.id}`);
      const data = resp.data?.data;
      const layouts: any[] = data?.node_layouts || [];

      // If there's a scope query, re-execute to get fresh graph data
      if (arch.scope_query) {
        const qr = await queryApi.executeCypher(arch.scope_query);
        const qdata = qr.data.data;
        setGraphNodes(qdata.nodes || []);
        setGraphEdges(qdata.edges || []);
      }

      // Apply saved positions
      const pinned = new Map<string, { x: number; y: number }>();
      for (const layout of layouts) {
        if (layout.x !== undefined && layout.y !== undefined) {
          pinned.set(layout.node_id, { x: layout.x, y: layout.y });
        }
      }
      setPinnedPositions(pinned);
    } catch { /* ignore load errors */ }
  }, []);

  const deleteArchitecture = useCallback(async (id: string) => {
    try {
      await api.delete(`/architectures/${id}`);
      queryClient.invalidateQueries({ queryKey: ["architectures"] });
      if (architectureId === id) {
        setArchitectureId(null);
        setArchitectureName("New Architecture");
      }
    } catch { /* ignore */ }
  }, [architectureId, queryClient]);

  // Selected node details
  const selectedNode = selectedNodeId ? graphNodes.find((n) => n.id === selectedNodeId) : null;

  return (
    <div className="flex h-[calc(100vh-64px)]">
      {/* LEFT — Controls */}
      <div className="w-[340px] flex-shrink-0 border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-y-auto">
        {/* Header */}
        <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-gray-900 dark:text-white">Architecture Viewer</h2>
            <button onClick={() => { setShowLibrary(!showLibrary); }}
              className="text-[10px] text-brand-600 hover:underline">
              {showLibrary ? "Hide Library" : "Library"}
            </button>
          </div>
        </div>

        {/* Library */}
        {showLibrary && (
          <div className="p-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 max-h-48 overflow-y-auto">
            <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1">Saved Architectures</div>
            {architectures.map((a) => (
              <div key={a.id} className="flex items-center justify-between mb-1">
                <button onClick={() => loadArchitecture(a)}
                  className="flex-1 text-left rounded px-2 py-1 text-xs hover:bg-brand-50 dark:hover:bg-gray-700 truncate">
                  {a.name} <span className="text-gray-400">({a.architecture_type})</span>
                </button>
                <button onClick={() => { if (confirm(`Delete "${a.name}"?`)) deleteArchitecture(a.id); }}
                  className="text-red-400 hover:text-red-600 text-[10px] px-1">x</button>
              </div>
            ))}
            {architectures.length === 0 && <div className="text-[10px] text-gray-400">No saved architectures</div>}
          </div>
        )}

        {/* Architecture metadata */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700 space-y-2">
          <div>
            <label className="text-[10px] font-medium text-gray-500">Name</label>
            <input value={architectureName} onChange={(e) => setArchitectureName(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-medium text-gray-500">Type</label>
              <select value={architectureType} onChange={(e) => setArchitectureType(e.target.value)}
                className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                {["topology", "circuit_path", "service_map", "wan", "campus", "custom"].map((t) => (
                  <option key={t} value={t}>{t.replace("_", " ")}</option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="text-[10px] font-medium text-gray-500">Layout</label>
              <select value={layoutMode} onChange={(e) => setLayoutMode(e.target.value as LayoutMode)}
                className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                {[
                  { value: "role-tiered", label: "Tiered (Network)" },
                  { value: "hierarchical", label: "Hierarchical" },
                  { value: "force", label: "Force Directed" },
                  { value: "radial", label: "Radial" },
                  { value: "path", label: "Path (L→R)" },
                ].map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Description</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
        </div>

        {/* Query */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-1">
            <label className="text-[10px] font-medium text-gray-500">Scope Query (Cypher)</label>
            <button onClick={() => setShowQuery(!showQuery)} className="text-[10px] text-gray-400">
              {showQuery ? "Hide" : "Show"}
            </button>
          </div>
          {showQuery && (
            <>
              <textarea value={cypherQuery} onChange={(e) => setCypherQuery(e.target.value)} rows={4}
                className="w-full rounded border border-gray-300 px-2 py-1 text-[10px] font-mono dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              {queryError && <div className="text-[10px] text-red-500 mt-1">{queryError}</div>}
              <button onClick={executeQuery} disabled={loading}
                className="mt-2 rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700 disabled:opacity-50 w-full">
                {loading ? "Loading..." : "Load Graph"}
              </button>
            </>
          )}
        </div>

        {/* Layout actions */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Layout</div>
          <div className="flex flex-wrap gap-1.5">
            <button onClick={unpinAll}
              className="rounded border border-gray-300 px-2 py-1 text-[10px] text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400">
              Unpin All ({pinnedPositions.size})
            </button>
            <button onClick={() => fitView({ padding: 0.1 })}
              className="rounded border border-gray-300 px-2 py-1 text-[10px] text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400">
              Fit View
            </button>
          </div>
          <div className="mt-2 text-[10px] text-gray-400">
            Drag nodes to arrange. Positions auto-pin on drop.
            {pinnedPositions.size > 0 && ` ${pinnedPositions.size} node(s) pinned.`}
          </div>
        </div>

        {/* Save */}
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <button onClick={saveArchitecture} disabled={graphNodes.length === 0}
            className="w-full rounded bg-brand-600 px-3 py-1.5 text-xs text-white hover:bg-brand-700 disabled:opacity-50">
            {saveFeedback || (architectureId ? "Update Architecture" : "Save Architecture")}
          </button>
        </div>

        {/* Selected node details */}
        {selectedNode && (
          <div className="p-3">
            <div className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5">Selected: {selectedNode.node_type}</div>
            <div className="text-xs font-bold text-gray-900 dark:text-white mb-2">{selectedNode.label}</div>
            <div className="space-y-1">
              {Object.entries(selectedNode.properties || {}).slice(0, 12).map(([key, val]) => (
                <div key={key} className="flex justify-between text-[10px]">
                  <span className="text-gray-500">{key}</span>
                  <span className="text-gray-700 dark:text-gray-300 truncate max-w-[150px]">{String(val ?? "")}</span>
                </div>
              ))}
            </div>
            {pinnedPositions.has(selectedNode.id) && (
              <button onClick={() => unpinNode(selectedNode.id)}
                className="mt-2 rounded border border-gray-300 px-2 py-0.5 text-[10px] text-gray-500 hover:bg-gray-50">
                Unpin this node
              </button>
            )}
          </div>
        )}

        {/* Stats */}
        <div className="p-3 text-[10px] text-gray-400">
          {graphNodes.length} nodes, {graphEdges.length} edges
          {architectureId && <span className="ml-2 text-green-500">(saved)</span>}
        </div>
      </div>

      {/* RIGHT — Graph Canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(_e, node) => setSelectedNodeId(node.id)}
          onPaneClick={() => setSelectedNodeId(null)}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          snapToGrid
          snapGrid={[8, 8]}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} />
          <Controls position="bottom-left" />
          <MiniMap position="bottom-right" nodeStrokeWidth={3} />

          {/* Stats overlay */}
          <Panel position="top-right">
            <div className="rounded bg-white/90 dark:bg-gray-800/90 px-3 py-1.5 shadow text-[10px] text-gray-500">
              {nodes.length} nodes | {edges.length} edges | {pinnedPositions.size} pinned | Layout: {layoutMode}
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Wrapper with ReactFlowProvider
// --------------------------------------------------------------------------

export function ArchitectureViewerPage() {
  return (
    <ReactFlowProvider>
      <ArchitectureViewerInner />
    </ReactFlowProvider>
  );
}
