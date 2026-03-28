/**
 * Custom React Flow node component.
 *
 * Renders a compact card with a colored icon circle (first letter of the type),
 * label text, and a type badge. Uses schema metadata for colors.
 * Provides handles on all four sides for flexible edge routing.
 */

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useSchemaStore } from "@/stores/schemaStore";

export interface CustomNodeData {
  nodeType: string;
  label: string;
  properties: Record<string, unknown>;
  /** The original GraphNode id */
  graphNodeId: string;
  [key: string]: unknown;
}

const DEFAULT_COLOR = "#6366f1";

function CustomNodeComponent({ data, selected }: NodeProps) {
  const getNodeType = useSchemaStore((s) => s.getNodeType);
  const nodeData = data as unknown as CustomNodeData;
  const schema = getNodeType(nodeData.nodeType);

  const color = schema?.graph?.color ?? schema?.metadata?.color ?? DEFAULT_COLOR;
  const displayName = schema?.metadata?.display_name ?? nodeData.nodeType;
  const icon = schema?.metadata?.icon;
  const firstLetter = (icon ?? displayName ?? "N")[0].toUpperCase();

  const label =
    nodeData.label ||
    String(
      nodeData.properties?.hostname ??
        nodeData.properties?.name ??
        nodeData.graphNodeId,
    );

  return (
    <div
      className="relative flex items-center gap-2 rounded-lg border-2 bg-white px-3 py-2 shadow-sm transition-shadow hover:shadow-md"
      style={{
        borderColor: selected ? color : `${color}66`,
        minWidth: 120,
        maxWidth: 180,
        boxShadow: selected ? `0 0 0 2px ${color}44` : undefined,
      }}
    >
      {/* Handles on all four sides */}
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-none"
        style={{ background: color }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-none"
        style={{ background: color }}
      />
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        className="!h-2 !w-2 !border-none"
        style={{ background: color }}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="!h-2 !w-2 !border-none"
        style={{ background: color }}
      />

      {/* Icon circle */}
      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
        style={{ backgroundColor: color }}
      >
        {firstLetter}
      </div>

      {/* Label and type badge */}
      <div className="flex min-w-0 flex-col">
        <span
          className="truncate text-xs font-semibold text-gray-800"
          title={label}
        >
          {label}
        </span>
        <span
          className="mt-0.5 inline-block max-w-fit truncate rounded px-1 py-0.5 text-[10px] font-medium leading-none text-white"
          style={{ backgroundColor: `${color}cc` }}
          title={displayName}
        >
          {displayName}
        </span>
      </div>
    </div>
  );
}

export const CustomNode = memo(CustomNodeComponent);
