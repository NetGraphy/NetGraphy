/**
 * Toolbar for the graph canvas.
 *
 * Provides layout switching, zoom controls, fit-view, node/edge type
 * filter toggles, a node count display, and PNG export.
 */

import { useCallback, useRef } from "react";
import { useReactFlow } from "@xyflow/react";
import {
  ZoomIn,
  ZoomOut,
  Maximize,
  Download,
  LayoutGrid,
  Network,
  Filter,
} from "lucide-react";
import { useSchemaStore } from "@/stores/schemaStore";

export type LayoutType = "hierarchical" | "force";

interface GraphControlsProps {
  layout: LayoutType;
  onLayoutChange: (layout: LayoutType) => void;
  visibleNodeTypes: Set<string>;
  onToggleNodeType: (nodeType: string) => void;
  visibleEdgeTypes: Set<string>;
  onToggleEdgeType: (edgeType: string) => void;
  onSelectAllNodes: () => void;
  onDeselectAllNodes: () => void;
  onSelectAllEdges: () => void;
  onDeselectAllEdges: () => void;
  nodeTypeList: string[];
  edgeTypeList: string[];
  displayedCount: number;
  totalCount: number;
  onToggleFilter?: () => void;
  filterActive?: boolean;
}

const DEFAULT_COLOR = "#6366f1";
const DEFAULT_EDGE_COLOR = "#94a3b8";

export function GraphControls({
  layout,
  onLayoutChange,
  visibleNodeTypes,
  onToggleNodeType,
  visibleEdgeTypes,
  onToggleEdgeType,
  onSelectAllNodes,
  onDeselectAllNodes,
  onSelectAllEdges,
  onDeselectAllEdges,
  nodeTypeList,
  edgeTypeList,
  displayedCount,
  totalCount,
  onToggleFilter,
  filterActive,
}: GraphControlsProps) {
  const { zoomIn, zoomOut, fitView, getNodes, getEdges } = useReactFlow();
  const nodeTypes = useSchemaStore((s) => s.nodeTypes);
  const edgeTypes = useSchemaStore((s) => s.edgeTypes);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const handleExportPng = useCallback(() => {
    // Use the React Flow viewport element for canvas export
    const viewport = document.querySelector(
      ".react-flow__viewport",
    ) as HTMLElement | null;
    if (!viewport) return;

    // Build a simple JSON snapshot as a fallback export
    const data = {
      nodes: getNodes(),
      edges: getEdges(),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graph-export.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [getNodes, getEdges]);

  return (
    <div
      ref={canvasRef}
      className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white/90 px-3 py-2 shadow-sm backdrop-blur"
    >
      {/* Layout selector */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onLayoutChange("hierarchical")}
          className={`flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            layout === "hierarchical"
              ? "bg-indigo-100 text-indigo-700"
              : "text-gray-600 hover:bg-gray-100"
          }`}
          title="Hierarchical layout"
        >
          <LayoutGrid size={14} />
          Hierarchical
        </button>
        <button
          type="button"
          onClick={() => onLayoutChange("force")}
          className={`flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            layout === "force"
              ? "bg-indigo-100 text-indigo-700"
              : "text-gray-600 hover:bg-gray-100"
          }`}
          title="Force-directed layout"
        >
          <Network size={14} />
          Force
        </button>
      </div>

      <div className="h-5 w-px bg-gray-200" />

      {/* Zoom & fit controls */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => zoomIn()}
          className="rounded p-1 text-gray-600 transition-colors hover:bg-gray-100"
          title="Zoom in"
        >
          <ZoomIn size={16} />
        </button>
        <button
          type="button"
          onClick={() => zoomOut()}
          className="rounded p-1 text-gray-600 transition-colors hover:bg-gray-100"
          title="Zoom out"
        >
          <ZoomOut size={16} />
        </button>
        <button
          type="button"
          onClick={() => fitView({ padding: 0.15, duration: 300 })}
          className="rounded p-1 text-gray-600 transition-colors hover:bg-gray-100"
          title="Fit view"
        >
          <Maximize size={16} />
        </button>
      </div>

      <div className="h-5 w-px bg-gray-200" />

      {/* Node type filters */}
      {nodeTypeList.length > 0 && (
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
            Nodes
          </span>
          <button type="button" onClick={onSelectAllNodes} className="text-[9px] text-brand-600 hover:text-brand-700" title="Select all node types">all</button>
          <span className="text-[9px] text-gray-300">|</span>
          <button type="button" onClick={onDeselectAllNodes} className="text-[9px] text-brand-600 hover:text-brand-700" title="Deselect all node types">none</button>
          {nodeTypeList.map((nt) => {
            const schema = nodeTypes[nt];
            const color =
              schema?.graph?.color ??
              schema?.metadata?.color ??
              DEFAULT_COLOR;
            const label = schema?.metadata?.display_name ?? nt;
            const active = visibleNodeTypes.has(nt);
            return (
              <button
                key={nt}
                type="button"
                onClick={() => onToggleNodeType(nt)}
                className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-all ${
                  active
                    ? "border-transparent text-white"
                    : "border-gray-200 bg-white text-gray-400"
                }`}
                style={
                  active
                    ? { backgroundColor: color, borderColor: color }
                    : undefined
                }
                title={`${active ? "Hide" : "Show"} ${label}`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: active ? "#fff" : color }}
                />
                {label}
              </button>
            );
          })}
        </div>
      )}

      {/* Edge type filters */}
      {edgeTypeList.length > 0 && (
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
            Edges
          </span>
          <button type="button" onClick={onSelectAllEdges} className="text-[9px] text-brand-600 hover:text-brand-700" title="Select all edge types">all</button>
          <span className="text-[9px] text-gray-300">|</span>
          <button type="button" onClick={onDeselectAllEdges} className="text-[9px] text-brand-600 hover:text-brand-700" title="Deselect all edge types">none</button>
          {edgeTypeList.map((et) => {
            const schema = edgeTypes[et];
            const color =
              schema?.graph?.color ??
              schema?.metadata?.color ??
              DEFAULT_EDGE_COLOR;
            const label =
              schema?.metadata?.display_name ?? et.replace(/_/g, " ");
            const active = visibleEdgeTypes.has(et);
            return (
              <button
                key={et}
                type="button"
                onClick={() => onToggleEdgeType(et)}
                className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-all ${
                  active
                    ? "border-transparent text-white"
                    : "border-gray-200 bg-white text-gray-400"
                }`}
                style={
                  active
                    ? { backgroundColor: color, borderColor: color }
                    : undefined
                }
                title={`${active ? "Hide" : "Show"} ${label}`}
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: active ? "#fff" : color }}
                />
                {label}
              </button>
            );
          })}
        </div>
      )}

      <div className="h-5 w-px bg-gray-200" />

      {/* Node count */}
      <span className="text-xs text-gray-500">
        Showing{" "}
        <span className="font-semibold text-gray-700">{displayedCount}</span>
        {totalCount !== displayedCount && (
          <> of <span className="font-semibold text-gray-700">{totalCount}</span></>
        )}{" "}
        nodes
      </span>

      <div className="h-5 w-px bg-gray-200" />

      {/* Power Filter toggle */}
      {onToggleFilter && (
        <button
          type="button"
          onClick={onToggleFilter}
          className="relative flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-100"
          title="Power Filters"
        >
          <Filter size={14} />
          Filter
          {filterActive && (
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-blue-500" />
          )}
        </button>
      )}

      <div className="h-5 w-px bg-gray-200" />

      {/* Export */}
      <button
        type="button"
        onClick={handleExportPng}
        className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-100"
        title="Export graph data"
      >
        <Download size={14} />
        Export
      </button>
    </div>
  );
}
