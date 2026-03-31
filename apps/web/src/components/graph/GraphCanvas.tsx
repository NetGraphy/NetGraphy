/**
 * Main graph visualization component.
 *
 * Converts GraphNode/GraphEdge (from QueryResult) to React Flow format,
 * applies layout (dagre hierarchical by default), renders custom nodes/edges,
 * and provides interactive controls including zoom, fit-view, layout switching,
 * and type filtering.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type NodeMouseHandler,
  Controls,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { GraphNode, GraphEdge } from "@/types/schema";
import { CustomNode, type CustomNodeData } from "./CustomNode";
import { CustomEdge } from "./CustomEdge";
import { GraphControls, type LayoutType } from "./GraphControls";
import { GraphFilterPanel } from "./GraphFilterPanel";
import { applyLayout } from "@/lib/graphLayout";
import { applyGraphFilter } from "@/lib/graphFilterEngine";
import { useGraphExplorerStore } from "@/stores/graphExplorerStore";

// ---------- Types ----------

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeSelect?: (node: GraphNode) => void;
  onNodeExpand?: (node: GraphNode) => void;
  maxNodes?: number;
  className?: string;
}

// ---------- React Flow custom type maps ----------

const nodeTypes = { custom: CustomNode };
const edgeTypes = { custom: CustomEdge };

// ---------- Conversion helpers ----------

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
    } satisfies CustomNodeData,
  }));
}

function toFlowEdges(graphEdges: GraphEdge[]): Edge[] {
  return graphEdges.map((ge) => ({
    id: ge.id,
    source: ge.source_id,
    target: ge.target_id,
    type: "custom",
    data: {
      edgeType: ge.edge_type,
      properties: ge.properties,
    },
  }));
}

// ---------- Inner component (needs ReactFlowProvider context) ----------

function GraphCanvasInner({
  nodes: inputNodes,
  edges: inputEdges,
  onNodeSelect,
  onNodeExpand,
  maxNodes = 200,
  className,
}: GraphCanvasProps) {
  const { fitView } = useReactFlow();

  // Layout state
  const [layout, setLayout] = useState<LayoutType>("hierarchical");

  // Power filter panel state
  const [showFilterPanel, setShowFilterPanel] = useState(false);
  const graphFilter = useGraphExplorerStore((s) => s.filter);

  // Truncation
  const isTruncated = inputNodes.length > maxNodes;
  const truncatedNodes = useMemo(
    () => (isTruncated ? inputNodes.slice(0, maxNodes) : inputNodes),
    [inputNodes, maxNodes, isTruncated],
  );

  // Collect unique types for filters
  const allNodeTypes = useMemo(
    () => [...new Set(truncatedNodes.map((n) => n.node_type))],
    [truncatedNodes],
  );
  const allEdgeTypes = useMemo(
    () => [...new Set(inputEdges.map((e) => e.edge_type))],
    [inputEdges],
  );

  // Default: show ALL node and edge types from the data
  const [visibleNodeTypes, setVisibleNodeTypes] = useState<Set<string>>(
    () => new Set(allNodeTypes),
  );
  const [visibleEdgeTypes, setVisibleEdgeTypes] = useState<Set<string>>(
    () => new Set(allEdgeTypes),
  );

  // Add newly discovered types automatically
  useEffect(() => {
    setVisibleNodeTypes((prev) => {
      const updated = new Set(prev);
      for (const t of allNodeTypes) {
        updated.add(t);
      }
      return updated;
    });
  }, [allNodeTypes]);

  useEffect(() => {
    setVisibleEdgeTypes((prev) => {
      const updated = new Set(prev);
      for (const t of allEdgeTypes) {
        updated.add(t);
      }
      return updated;
    });
  }, [allEdgeTypes]);

  // Filter nodes/edges
  const filteredGraphNodes = useMemo(
    () => truncatedNodes.filter((n) => visibleNodeTypes.has(n.node_type)),
    [truncatedNodes, visibleNodeTypes],
  );

  const filteredNodeIds = useMemo(
    () => new Set(filteredGraphNodes.map((n) => n.id)),
    [filteredGraphNodes],
  );

  const filteredGraphEdges = useMemo(
    () =>
      inputEdges.filter(
        (e) =>
          visibleEdgeTypes.has(e.edge_type) &&
          filteredNodeIds.has(e.source_id) &&
          filteredNodeIds.has(e.target_id),
      ),
    [inputEdges, visibleEdgeTypes, filteredNodeIds],
  );

  // Apply power filter (from graphExplorerStore)
  const powerFiltered = useMemo(
    () => applyGraphFilter(filteredGraphNodes, filteredGraphEdges, graphFilter),
    [filteredGraphNodes, filteredGraphEdges, graphFilter],
  );

  // Convert to React Flow format
  const rawFlowNodes = useMemo(
    () => toFlowNodes(powerFiltered.nodes),
    [powerFiltered.nodes],
  );
  const flowEdges = useMemo(
    () => toFlowEdges(powerFiltered.edges),
    [powerFiltered.edges],
  );

  // Apply layout using the unified layout dispatcher
  const laidOutNodes = useMemo(() => {
    if (rawFlowNodes.length === 0) return [];
    return applyLayout(layout as any, rawFlowNodes, flowEdges, "TB");
  }, [rawFlowNodes, flowEdges, layout]);

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState(laidOutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(flowEdges);

  // Sync layout results into React Flow state
  useEffect(() => {
    setNodes(laidOutNodes);
    setEdges(flowEdges);
  }, [laidOutNodes, flowEdges, setNodes, setEdges]);

  // Fit view after nodes are rendered
  useEffect(() => {
    if (nodes.length > 0) {
      // Small delay to let React Flow render nodes before fitting
      const timer = setTimeout(() => {
        fitView({ padding: 0.15, duration: 300 });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [nodes.length, fitView, layout]);

  // Build a lookup from node id to GraphNode for callbacks
  const graphNodeMap = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const n of inputNodes) {
      map.set(n.id, n);
    }
    return map;
  }, [inputNodes]);

  // Interaction handlers
  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const gn = graphNodeMap.get(node.id);
      if (gn && onNodeSelect) {
        onNodeSelect(gn);
      }
    },
    [graphNodeMap, onNodeSelect],
  );

  const handleNodeDoubleClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const gn = graphNodeMap.get(node.id);
      if (gn && onNodeExpand) {
        onNodeExpand(gn);
      }
    },
    [graphNodeMap, onNodeExpand],
  );

  // Toggle handlers for filters
  const handleToggleNodeType = useCallback((nodeType: string) => {
    setVisibleNodeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeType)) {
        next.delete(nodeType);
      } else {
        next.add(nodeType);
      }
      return next;
    });
  }, []);

  const handleToggleEdgeType = useCallback((edgeType: string) => {
    setVisibleEdgeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(edgeType)) {
        next.delete(edgeType);
      } else {
        next.add(edgeType);
      }
      return next;
    });
  }, []);

  const handleSelectAllNodes = useCallback(() => setVisibleNodeTypes(new Set(allNodeTypes)), [allNodeTypes]);
  const handleDeselectAllNodes = useCallback(() => setVisibleNodeTypes(new Set()), []);
  const handleSelectAllEdges = useCallback(() => setVisibleEdgeTypes(new Set(allEdgeTypes)), [allEdgeTypes]);
  const handleDeselectAllEdges = useCallback(() => setVisibleEdgeTypes(new Set()), []);

  // Empty state
  if (inputNodes.length === 0) {
    return (
      <div
        className={`flex h-full w-full items-center justify-center text-gray-400 ${className ?? ""}`}
      >
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
          <p className="text-sm font-medium">No graph data</p>
          <p className="mt-1 text-xs">
            Run a query to visualize nodes and relationships
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative flex h-full w-full flex-col ${className ?? ""}`}>
      {/* Truncation warning */}
      {isTruncated && (
        <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
          <svg
            className="h-4 w-4 flex-shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
            />
          </svg>
          <span>
            Showing {maxNodes} of {inputNodes.length} nodes. Refine your query
            for a complete view.
          </span>
        </div>
      )}

      {/* Controls toolbar */}
      <div className="absolute left-3 top-3 z-10">
        <GraphControls
          layout={layout}
          onLayoutChange={setLayout}
          visibleNodeTypes={visibleNodeTypes}
          onToggleNodeType={handleToggleNodeType}
          visibleEdgeTypes={visibleEdgeTypes}
          onToggleEdgeType={handleToggleEdgeType}
          onSelectAllNodes={handleSelectAllNodes}
          onDeselectAllNodes={handleDeselectAllNodes}
          onSelectAllEdges={handleSelectAllEdges}
          onDeselectAllEdges={handleDeselectAllEdges}
          nodeTypeList={allNodeTypes}
          edgeTypeList={allEdgeTypes}
          displayedCount={powerFiltered.nodes.length}
          totalCount={inputNodes.length}
          onToggleFilter={() => setShowFilterPanel((prev) => !prev)}
          filterActive={graphFilter.enabled && graphFilter.rootGroup.rules.length > 0}
        />
      </div>

      {/* Power Filter panel */}
      {showFilterPanel && (
        <div className="absolute right-3 top-3 z-10">
          <GraphFilterPanel
            onClose={() => setShowFilterPanel(false)}
            displayedCount={powerFiltered.nodes.length}
            totalCount={inputNodes.length}
          />
        </div>
      )}

      {/* React Flow canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
          onNodeDoubleClick={handleNodeDoubleClick}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={4}
          defaultEdgeOptions={{
            type: "custom",
          }}
          proOptions={{ hideAttribution: true }}
        >
          <Controls
            showInteractive={false}
            className="!bottom-3 !right-3 !left-auto"
          />
        </ReactFlow>
      </div>
    </div>
  );
}

// ---------- Exported wrapper with ReactFlowProvider ----------

export function GraphCanvas(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
