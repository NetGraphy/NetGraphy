/**
 * Custom React Flow edge component.
 *
 * Renders a bezier edge styled according to schema metadata:
 * - Color from schema graph.color or metadata.color
 * - Dashed style for certain edge types (configurable via schema graph.style)
 * - Label appears on hover showing the edge type display name
 * - Animated stroke when selected
 */

import { memo, useState } from "react";
import {
  BaseEdge,
  getBezierPath,
  EdgeLabelRenderer,
  type EdgeProps,
} from "@xyflow/react";
import { useSchemaStore } from "@/stores/schemaStore";

const DEFAULT_EDGE_COLOR = "#94a3b8";

function CustomEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  data,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const getEdgeType = useSchemaStore((s) => s.getEdgeType);

  const edgeTypeName = (data?.edgeType as string) ?? "";
  const schema = getEdgeType(edgeTypeName);

  const color =
    schema?.graph?.color ?? schema?.metadata?.color ?? DEFAULT_EDGE_COLOR;
  const displayName =
    schema?.metadata?.display_name ?? edgeTypeName.replace(/_/g, " ");
  const isDashed = schema?.graph?.style === "dashed";

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const strokeDasharray = isDashed ? "6 3" : undefined;

  return (
    <>
      {/* Invisible wider path for easier hover/click targeting */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      />

      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: selected ? color : `${color}${hovered ? "ee" : "99"}`,
          strokeWidth: selected ? 2.5 : hovered ? 2 : 1.5,
          strokeDasharray,
          transition: "stroke 0.15s, stroke-width 0.15s",
          animation: selected ? "edgePulse 1.5s ease-in-out infinite" : undefined,
        }}
      />

      {/* Label shown on hover or when selected */}
      {(hovered || selected) && displayName && (
        <EdgeLabelRenderer>
          <div
            className="pointer-events-none absolute rounded bg-gray-800 px-2 py-0.5 text-[10px] font-medium text-white shadow"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {displayName}
          </div>
        </EdgeLabelRenderer>
      )}

      {/* Global CSS for the pulse animation, injected once */}
      <style>{`
        @keyframes edgePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </>
  );
}

export const CustomEdge = memo(CustomEdgeComponent);
