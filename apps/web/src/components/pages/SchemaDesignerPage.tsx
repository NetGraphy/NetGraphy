/**
 * SchemaDesignerPage — Visual ERD + YAML schema designer.
 *
 * Three synchronized views of the canonical schema model:
 * 1. ERD Canvas (React Flow) — visual node/edge diagram
 * 2. Property Panel — edit selected node/edge/attribute details
 * 3. YAML Editor (Monaco) — live generated YAML with round-trip editing
 *
 * The Zustand store (schemaDesignerStore) is the single source of truth.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Node,
  Edge,
  Handle,
  Position,
  NodeProps,
  MarkerType,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Editor from "@monaco-editor/react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import {
  useSchemaDesignerStore,
  SchemaNode,
  SchemaEdge,
  SchemaAttribute,
  CanonicalSchema,
} from "@/stores/schemaDesignerStore";

// ========================================================================
// YAML Serialization / Deserialization
// ========================================================================

function schemaToYaml(
  schema: CanonicalSchema,
  getNodeById: (id: string) => SchemaNode | undefined,
  importedNames: Set<string> = new Set(),
): string {
  const lines: string[] = [];

  // Node types — only NEW nodes (skip imported existing ones)
  const newNodes = schema.nodes.filter((n) => !importedNames.has(n.name));
  for (const node of [...newNodes].sort((a, b) => a.name.localeCompare(b.name))) {
    lines.push("---");
    lines.push("kind: NodeType");
    lines.push("version: v1");
    lines.push("metadata:");
    lines.push(`  name: ${node.name}`);
    lines.push(`  display_name: "${node.display_name}"`);
    if (node.description) lines.push(`  description: "${node.description}"`);
    if (node.icon) lines.push(`  icon: ${node.icon}`);
    if (node.color) lines.push(`  color: "${node.color}"`);
    if (node.category) lines.push(`  category: ${node.category}`);
    if (node.tags.length) lines.push(`  tags: [${node.tags.join(", ")}]`);
    lines.push("");

    if (node.attributes.length > 0) {
      lines.push("attributes:");
      for (const attr of node.attributes) {
        lines.push(`  ${attr.name}:`);
        lines.push(`    type: ${attr.type}`);
        if (attr.required) lines.push("    required: true");
        if (attr.unique) lines.push("    unique: true");
        if (attr.indexed) lines.push("    indexed: true");
        if (attr.default_value !== null && attr.default_value !== "") {
          lines.push(`    default: ${attr.default_value}`);
        }
        if (attr.enum_values && attr.enum_values.length > 0) {
          lines.push(`    enum_values: [${attr.enum_values.join(", ")}]`);
        }
        if (attr.description) lines.push(`    description: "${attr.description}"`);
      }
    }

    if (node.mixins.length > 0) {
      lines.push("");
      lines.push("mixins:");
      for (const m of node.mixins) lines.push(`  - ${m}`);
    }
    lines.push("");
  }

  // Edge types
  for (const edge of [...schema.edges].sort((a, b) => a.name.localeCompare(b.name))) {
    const fromNode = getNodeById(edge.from_node_id);
    const toNode = getNodeById(edge.to_node_id);
    if (!fromNode || !toNode) continue;

    lines.push("---");
    lines.push("kind: EdgeType");
    lines.push("version: v1");
    lines.push("metadata:");
    lines.push(`  name: ${edge.name}`);
    lines.push(`  display_name: "${edge.display_name}"`);
    if (edge.description) lines.push(`  description: "${edge.description}"`);
    lines.push("");
    lines.push("source:");
    lines.push(`  node_types: [${fromNode.name}]`);
    lines.push("");
    lines.push("target:");
    lines.push(`  node_types: [${toNode.name}]`);
    lines.push("");
    lines.push(`cardinality: ${edge.cardinality}`);
    if (edge.inverse_name) lines.push(`inverse_name: ${edge.inverse_name}`);

    if (edge.attributes.length > 0) {
      lines.push("");
      lines.push("attributes:");
      for (const attr of edge.attributes) {
        lines.push(`  ${attr.name}:`);
        lines.push(`    type: ${attr.type}`);
        if (attr.required) lines.push("    required: true");
      }
    }

    if (edge.constraints.unique_source || edge.constraints.unique_target) {
      lines.push("");
      lines.push("constraints:");
      if (edge.constraints.unique_source) lines.push("  unique_source: true");
      if (edge.constraints.unique_target) lines.push("  unique_target: true");
    }
    lines.push("");
  }

  return lines.join("\n");
}

// ========================================================================
// ERD Node Component (React Flow custom node)
// ========================================================================

const ATTR_TYPE_COLORS: Record<string, string> = {
  string: "#3B82F6", integer: "#10B981", float: "#10B981",
  boolean: "#F59E0B", enum: "#8B5CF6", datetime: "#EC4899",
  ip_address: "#06B6D4", json: "#6B7280",
};

function ErdNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as { schemaNode: SchemaNode; onSelect: (id: string) => void };
  const node = nodeData.schemaNode;

  return (
    <div
      className={`rounded-lg border-2 bg-white shadow-md dark:bg-gray-800 min-w-[200px] ${
        selected ? "border-brand-500 ring-2 ring-brand-200" : "border-gray-300 dark:border-gray-600"
      }`}
      onClick={() => nodeData.onSelect(node.id)}
    >
      <Handle type="target" position={Position.Left} className="!bg-brand-500 !w-3 !h-3" />
      <Handle type="source" position={Position.Right} className="!bg-brand-500 !w-3 !h-3" />

      {/* Header */}
      <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-600 rounded-t-lg"
        style={{ backgroundColor: node.color + "15" }}>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: node.color }} />
          <span className="font-bold text-sm text-gray-900 dark:text-white">{node.name}</span>
        </div>
        {node.category && (
          <span className="text-[9px] text-gray-500 uppercase">{node.category}</span>
        )}
      </div>

      {/* Attributes */}
      <div className="px-3 py-1">
        {node.attributes.length === 0 && (
          <div className="py-1 text-[10px] text-gray-400 italic">No attributes</div>
        )}
        {node.attributes.slice(0, 8).map((attr) => (
          <div key={attr.id} className="flex items-center gap-1.5 py-0.5">
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: ATTR_TYPE_COLORS[attr.type] || "#6B7280" }}
            />
            <span className="text-[11px] text-gray-700 dark:text-gray-300 truncate">
              {attr.name}
            </span>
            <span className="text-[9px] text-gray-400 ml-auto">{attr.type}</span>
            {attr.required && <span className="text-[8px] text-red-400">*</span>}
            {attr.unique && <span className="text-[8px] text-amber-400">U</span>}
            {attr.indexed && <span className="text-[8px] text-blue-400">I</span>}
          </div>
        ))}
        {node.attributes.length > 8 && (
          <div className="text-[9px] text-gray-400 py-0.5">
            +{node.attributes.length - 8} more
          </div>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { erdNode: ErdNodeComponent };

// ========================================================================
// Cardinality labels for edge display
// ========================================================================

const CARD_LABELS: Record<string, string> = {
  one_to_one: "1:1",
  one_to_many: "1:N",
  many_to_one: "N:1",
  many_to_many: "N:N",
};

// ========================================================================
// Property Panel
// ========================================================================

function PropertyPanel() {
  const {
    schema, selectedNodeId, selectedEdgeId, selectedAttributeId,
    updateNode, removeNode, addAttribute, updateAttribute, removeAttribute,
    updateEdge, removeEdge, addEdgeAttribute, updateEdgeAttribute, removeEdgeAttribute,
    getNodeById, getEdgeById, selectAttribute,
  } = useSchemaDesignerStore();

  const selectedNode = selectedNodeId ? getNodeById(selectedNodeId) : null;
  const selectedEdge = selectedEdgeId ? getEdgeById(selectedEdgeId) : null;

  if (!selectedNode && !selectedEdge) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400 text-sm p-4 text-center">
        Select a node or edge on the canvas to edit its properties
      </div>
    );
  }

  // --- Node properties ---
  if (selectedNode) {
    return (
      <div className="overflow-y-auto h-full">
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Node Type</span>
            <button onClick={() => { if (confirm(`Delete ${selectedNode.name}?`)) removeNode(selectedNode.id); }}
              className="text-[10px] text-red-500 hover:underline">Delete</button>
          </div>
          <input value={selectedNode.name} onChange={(e) => updateNode(selectedNode.id, { name: e.target.value })}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm font-bold dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        </div>

        <div className="p-3 border-b border-gray-200 dark:border-gray-700 space-y-2">
          <div>
            <label className="text-[10px] font-medium text-gray-500">Display Name</label>
            <input value={selectedNode.display_name} onChange={(e) => updateNode(selectedNode.id, { display_name: e.target.value })}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Description</label>
            <textarea value={selectedNode.description} onChange={(e) => updateNode(selectedNode.id, { description: e.target.value })} rows={2}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-medium text-gray-500">Category</label>
              <input value={selectedNode.category} onChange={(e) => updateNode(selectedNode.id, { category: e.target.value })}
                className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            <div className="w-20">
              <label className="text-[10px] font-medium text-gray-500">Color</label>
              <input type="color" value={selectedNode.color} onChange={(e) => updateNode(selectedNode.id, { color: e.target.value })}
                className="w-full h-7 rounded border border-gray-300 cursor-pointer" />
            </div>
          </div>
        </div>

        {/* Attributes */}
        <div className="p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Attributes ({selectedNode.attributes.length})</span>
            <button onClick={() => addAttribute(selectedNode.id)} className="text-[10px] text-brand-600 hover:underline">+ Add</button>
          </div>
          {selectedNode.attributes.map((attr) => (
            <div key={attr.id}
              className={`mb-2 rounded border p-2 cursor-pointer ${selectedAttributeId === attr.id ? "border-brand-500 bg-brand-50 dark:bg-brand-900/20" : "border-gray-200 dark:border-gray-600"}`}
              onClick={() => selectAttribute(attr.id)}>
              <div className="flex items-center justify-between">
                <input value={attr.name} onClick={(e) => e.stopPropagation()}
                  onChange={(e) => updateAttribute(selectedNode.id, attr.id, { name: e.target.value })}
                  className="text-xs font-medium bg-transparent border-none p-0 focus:outline-none w-24 dark:text-white" />
                <div className="flex items-center gap-1">
                  <select value={attr.type} onChange={(e) => updateAttribute(selectedNode.id, attr.id, { type: e.target.value })}
                    className="text-[10px] rounded border border-gray-300 px-1 py-0.5 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    {["string", "text", "integer", "float", "boolean", "datetime", "date", "enum", "json", "ip_address", "cidr", "mac_address", "url", "email"].map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                  <button onClick={(e) => { e.stopPropagation(); removeAttribute(selectedNode.id, attr.id); }}
                    className="text-red-400 hover:text-red-600 text-[10px]">x</button>
                </div>
              </div>
              {selectedAttributeId === attr.id && (
                <div className="mt-2 space-y-1 border-t border-gray-200 pt-2 dark:border-gray-600">
                  <div className="flex gap-3 text-[10px]">
                    <label className="flex items-center gap-1">
                      <input type="checkbox" checked={attr.required}
                        onChange={(e) => updateAttribute(selectedNode.id, attr.id, { required: e.target.checked })} />
                      Required
                    </label>
                    <label className="flex items-center gap-1">
                      <input type="checkbox" checked={attr.unique}
                        onChange={(e) => updateAttribute(selectedNode.id, attr.id, { unique: e.target.checked })} />
                      Unique
                    </label>
                    <label className="flex items-center gap-1">
                      <input type="checkbox" checked={attr.indexed}
                        onChange={(e) => updateAttribute(selectedNode.id, attr.id, { indexed: e.target.checked })} />
                      Indexed
                    </label>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-500">Description</label>
                    <input value={attr.description} onChange={(e) => updateAttribute(selectedNode.id, attr.id, { description: e.target.value })}
                      className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                  </div>
                  {attr.type === "enum" && (
                    <div>
                      <label className="text-[10px] text-gray-500">Enum values (comma separated)</label>
                      <input value={(attr.enum_values || []).join(", ")}
                        onChange={(e) => updateAttribute(selectedNode.id, attr.id, { enum_values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })}
                        className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                    </div>
                  )}
                  <div>
                    <label className="text-[10px] text-gray-500">Default value</label>
                    <input value={attr.default_value || ""}
                      onChange={(e) => updateAttribute(selectedNode.id, attr.id, { default_value: e.target.value || null })}
                      className="w-full rounded border border-gray-300 px-1 py-0.5 text-[10px] dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // --- Edge properties ---
  if (selectedEdge) {
    const fromNode = getNodeById(selectedEdge.from_node_id);
    const toNode = getNodeById(selectedEdge.to_node_id);

    return (
      <div className="overflow-y-auto h-full">
        <div className="p-3 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Edge Type</span>
            <button onClick={() => { if (confirm(`Delete ${selectedEdge.name}?`)) removeEdge(selectedEdge.id); }}
              className="text-[10px] text-red-500 hover:underline">Delete</button>
          </div>
          <input value={selectedEdge.name} onChange={(e) => updateEdge(selectedEdge.id, { name: e.target.value })}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm font-bold dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        </div>

        <div className="p-3 border-b border-gray-200 dark:border-gray-700 space-y-2">
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-medium text-gray-500">From</label>
              <div className="text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded px-2 py-1">
                {fromNode?.name || "Unknown"}
              </div>
            </div>
            <div className="flex-1">
              <label className="text-[10px] font-medium text-gray-500">To</label>
              <div className="text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded px-2 py-1">
                {toNode?.name || "Unknown"}
              </div>
            </div>
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Cardinality</label>
            <select value={selectedEdge.cardinality}
              onChange={(e) => updateEdge(selectedEdge.id, { cardinality: e.target.value as SchemaEdge["cardinality"] })}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              <option value="one_to_one">One to One (1:1)</option>
              <option value="one_to_many">One to Many (1:N)</option>
              <option value="many_to_one">Many to One (N:1)</option>
              <option value="many_to_many">Many to Many (N:N)</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Display Name</label>
            <input value={selectedEdge.display_name} onChange={(e) => updateEdge(selectedEdge.id, { display_name: e.target.value })}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Inverse Name</label>
            <input value={selectedEdge.inverse_name} onChange={(e) => updateEdge(selectedEdge.id, { inverse_name: e.target.value })}
              placeholder="e.g., INTERFACE_OF"
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div>
            <label className="text-[10px] font-medium text-gray-500">Description</label>
            <textarea value={selectedEdge.description} onChange={(e) => updateEdge(selectedEdge.id, { description: e.target.value })} rows={2}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
          </div>
          <div className="flex gap-3 text-[10px]">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={selectedEdge.constraints.unique_source}
                onChange={(e) => updateEdge(selectedEdge.id, { constraints: { ...selectedEdge.constraints, unique_source: e.target.checked } })} />
              Unique Source
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={selectedEdge.constraints.unique_target}
                onChange={(e) => updateEdge(selectedEdge.id, { constraints: { ...selectedEdge.constraints, unique_target: e.target.checked } })} />
              Unique Target
            </label>
          </div>
        </div>

        {/* Edge attributes */}
        <div className="p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 uppercase">Edge Attributes ({selectedEdge.attributes.length})</span>
            <button onClick={() => addEdgeAttribute(selectedEdge.id)} className="text-[10px] text-brand-600 hover:underline">+ Add</button>
          </div>
          {selectedEdge.attributes.map((attr) => (
            <div key={attr.id} className="mb-2 rounded border border-gray-200 p-2 dark:border-gray-600">
              <div className="flex items-center justify-between">
                <input value={attr.name} onChange={(e) => updateEdgeAttribute(selectedEdge.id, attr.id, { name: e.target.value })}
                  className="text-xs font-medium bg-transparent border-none p-0 focus:outline-none w-24 dark:text-white" />
                <div className="flex items-center gap-1">
                  <select value={attr.type} onChange={(e) => updateEdgeAttribute(selectedEdge.id, attr.id, { type: e.target.value })}
                    className="text-[10px] rounded border border-gray-300 px-1 py-0.5 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    {["string", "integer", "float", "boolean", "enum"].map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                  <button onClick={() => removeEdgeAttribute(selectedEdge.id, attr.id)}
                    className="text-red-400 hover:text-red-600 text-[10px]">x</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return null;
}

// ========================================================================
// Main Page
// ========================================================================

export function SchemaDesignerPage() {
  const store = useSchemaDesignerStore();
  const {
    schema, selectedNodeId, selectedEdgeId, errors,
    addNode, selectNode, selectEdge, clearSelection,
    updateNode, addEdge: addSchemaEdge, loadSchema, validate,
    undo, redo, resetSchema, getNodeById,
  } = store;

  // Load existing node types for the "Import" picker (NOT auto-placed on canvas)
  const { data: nodeTypesData } = useQuery({
    queryKey: ["schema-node-types"],
    queryFn: () => api.get("/schema/node-types"),
  });
  const existingNodeTypes: any[] = nodeTypesData?.data?.data || [];
  // Track which nodes are imported (read-only references) vs new
  const [importedNames, setImportedNames] = useState<Set<string>>(new Set());

  const importExistingNode = useCallback((nt: any) => {
    const name = nt.metadata?.name || nt.name;
    if (schema.nodes.find((n) => n.name === name)) return; // Already on canvas

    const attrs: SchemaAttribute[] = Object.entries(nt.attributes || {}).map(([attrName, def]: [string, any]) => ({
      id: crypto.randomUUID(),
      name: attrName,
      type: def.type || "string",
      required: def.required || false,
      unique: def.unique || false,
      indexed: def.indexed || false,
      default_value: def.default !== undefined ? String(def.default) : null,
      enum_values: def.enum_values || null,
      description: def.description || "",
    }));

    const nodeCount = schema.nodes.length;
    const col = nodeCount % 4;
    const row = Math.floor(nodeCount / 4);

    addNode(name, { x: 100 + col * 280, y: 100 + row * 200 });
    // Find the newly added node and update its full data
    const newId = store.getState().schema.nodes.find((n) => n.name === name)?.id;
    if (newId) {
      updateNode(newId, {
        display_name: nt.metadata?.display_name || name,
        description: nt.metadata?.description || "",
        category: nt.metadata?.category || "",
        icon: nt.metadata?.icon || "box",
        color: nt.metadata?.color || "#94A3B8",
        tags: nt.metadata?.tags || [],
        mixins: nt.mixins || [],
      });
      // Add attributes
      for (const attr of attrs) {
        store.getState().addAttribute(newId, attr);
      }
    }
    setImportedNames((prev) => new Set([...prev, name]));
  }, [schema.nodes, addNode, updateNode, store]);

  const [showYaml, setShowYaml] = useState(true);
  const [yamlValue, setYamlValue] = useState("");
  const [newNodeName, setNewNodeName] = useState("");
  const [showAddNode, setShowAddNode] = useState(false);
  const [connectingName, setConnectingName] = useState("");
  const [showConnectDialog, setShowConnectDialog] = useState(false);
  const [pendingConnection, setPendingConnection] = useState<Connection | null>(null);
  // Manual edge creation via toolbar
  const [showAddEdge, setShowAddEdge] = useState(false);
  const [manualEdgeFrom, setManualEdgeFrom] = useState("");
  const [manualEdgeTo, setManualEdgeTo] = useState("");
  const [manualEdgeName, setManualEdgeName] = useState("");
  const [manualEdgeCardinality, setManualEdgeCardinality] = useState("many_to_many");
  // Import existing node picker
  const [showImport, setShowImport] = useState(false);
  const [importSearch, setImportSearch] = useState("");

  // --- Sync store → React Flow nodes ---
  const rfNodes: Node[] = useMemo(() =>
    schema.nodes.map((n) => ({
      id: n.id,
      type: "erdNode",
      position: n.position,
      data: { schemaNode: n, onSelect: selectNode },
      selected: n.id === selectedNodeId,
    })),
    [schema.nodes, selectedNodeId, selectNode]
  );

  const rfEdges: Edge[] = useMemo(() =>
    schema.edges.map((e) => ({
      id: e.id,
      source: e.from_node_id,
      target: e.to_node_id,
      label: `${e.display_name} (${CARD_LABELS[e.cardinality] || e.cardinality})`,
      labelStyle: { fontSize: 10, fill: "#6B7280" },
      labelBgStyle: { fill: "#F9FAFB", fillOpacity: 0.9 },
      labelBgPadding: [4, 2] as [number, number],
      style: { stroke: selectedEdgeId === e.id ? "#6366F1" : "#94A3B8", strokeWidth: selectedEdgeId === e.id ? 2.5 : 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: selectedEdgeId === e.id ? "#6366F1" : "#94A3B8" },
      animated: selectedEdgeId === e.id,
    })),
    [schema.edges, selectedEdgeId]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rfEdges);

  // Sync when store changes
  useEffect(() => { setNodes(rfNodes); }, [rfNodes, setNodes]);
  useEffect(() => { setEdges(rfEdges); }, [rfEdges, setEdges]);

  // Sync YAML
  useEffect(() => {
    setYamlValue(schemaToYaml(schema, getNodeById, importedNames));
  }, [schema, getNodeById, importedNames]);

  // --- Handlers ---

  const onNodeDragStop = useCallback((_: any, node: Node) => {
    updateNode(node.id, { position: node.position });
  }, [updateNode]);

  const onConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      setPendingConnection(connection);
      setConnectingName("");
      setShowConnectDialog(true);
    }
  }, []);

  const confirmConnect = useCallback(() => {
    if (pendingConnection?.source && pendingConnection?.target && connectingName) {
      addSchemaEdge(connectingName, pendingConnection.source, pendingConnection.target);
    }
    setShowConnectDialog(false);
    setPendingConnection(null);
  }, [pendingConnection, connectingName, addSchemaEdge]);

  const onEdgeClick = useCallback((_: any, edge: Edge) => {
    selectEdge(edge.id);
  }, [selectEdge]);

  const onPaneClick = useCallback(() => {
    clearSelection();
  }, [clearSelection]);

  const handleAddNode = useCallback(() => {
    if (!newNodeName.trim()) return;
    addNode(newNodeName.trim());
    setNewNodeName("");
    setShowAddNode(false);
  }, [newNodeName, addNode]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [undo, redo]);

  const validationErrors = useMemo(() => validate(), [schema]);

  return (
    <div className="flex h-[calc(100vh-64px)]">
      {/* ERD Canvas */}
      <div className={`flex-1 relative ${showYaml ? "" : ""}`}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={onNodeDragStop}
          onConnect={onConnect}
          onEdgeClick={onEdgeClick}
          onPaneClick={onPaneClick}
          nodeTypes={nodeTypes}
          fitView
          snapToGrid
          snapGrid={[16, 16]}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} />
          <Controls position="bottom-left" />
          <MiniMap position="bottom-right" nodeStrokeWidth={3} />

          {/* Toolbar */}
          <Panel position="top-left">
            <div className="flex items-center gap-2 bg-white dark:bg-gray-800 rounded-lg shadow-md border border-gray-200 dark:border-gray-600 px-3 py-2">
              {showAddNode ? (
                <div className="flex items-center gap-1">
                  <input value={newNodeName} onChange={(e) => setNewNodeName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAddNode()}
                    placeholder="NodeType name..."
                    autoFocus
                    className="rounded border border-gray-300 px-2 py-1 text-xs w-36 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                  <button onClick={handleAddNode} className="rounded bg-brand-600 px-2 py-1 text-[10px] text-white">Add</button>
                  <button onClick={() => setShowAddNode(false)} className="text-[10px] text-gray-500">Cancel</button>
                </div>
              ) : (
                <button onClick={() => setShowAddNode(true)}
                  className="rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700">
                  + Add Node
                </button>
              )}
              <button onClick={() => { setShowImport(true); setImportSearch(""); }}
                className="rounded bg-amber-600 px-3 py-1 text-xs text-white hover:bg-amber-700">
                Import Existing
              </button>
              <button onClick={() => { setShowAddEdge(true); setManualEdgeFrom(""); setManualEdgeTo(""); setManualEdgeName(""); setManualEdgeCardinality("many_to_many"); }}
                disabled={schema.nodes.length < 1}
                className="rounded bg-green-600 px-3 py-1 text-xs text-white hover:bg-green-700 disabled:opacity-50">
                + Add Edge
              </button>
              <button onClick={undo} title="Undo (Ctrl+Z)" className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300">Undo</button>
              <button onClick={redo} title="Redo (Ctrl+Shift+Z)" className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300">Redo</button>
              <button onClick={() => setShowYaml(!showYaml)}
                className={`rounded border px-2 py-1 text-xs ${showYaml ? "border-brand-500 text-brand-600 bg-brand-50" : "border-gray-300 text-gray-600"}`}>
                YAML
              </button>
              {validationErrors.length > 0 && (
                <span className="text-[10px] text-red-500">{validationErrors.length} error(s)</span>
              )}
            </div>
          </Panel>
        </ReactFlow>

        {/* Connect dialog */}
        {showConnectDialog && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-50"
            onClick={() => { setShowConnectDialog(false); setPendingConnection(null); }}>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-80" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-bold mb-2">Create Relationship</h3>
              <p className="text-xs text-gray-500 mb-3">
                {getNodeById(pendingConnection?.source || "")?.name} &rarr; {getNodeById(pendingConnection?.target || "")?.name}
              </p>
              <input value={connectingName} onChange={(e) => setConnectingName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && confirmConnect()}
                placeholder="Relationship name (e.g., HAS_INTERFACE)"
                autoFocus
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm mb-3 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              <div className="flex justify-end gap-2">
                <button onClick={() => { setShowConnectDialog(false); setPendingConnection(null); }}
                  className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-600">Cancel</button>
                <button onClick={confirmConnect} disabled={!connectingName.trim()}
                  className="rounded bg-brand-600 px-3 py-1 text-xs text-white disabled:opacity-50">Create</button>
              </div>
            </div>
          </div>
        )}

        {/* Add Edge dialog (toolbar-triggered) */}
        {showAddEdge && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-50"
            onClick={() => setShowAddEdge(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-96" onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-bold mb-3">Add Relationship</h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 block mb-1">Relationship Name</label>
                  <input value={manualEdgeName} onChange={(e) => setManualEdgeName(e.target.value)}
                    placeholder="e.g., HAS_INTERFACE, LOCATED_IN"
                    autoFocus
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-xs font-medium text-gray-500 block mb-1">From (Source)</label>
                    <select value={manualEdgeFrom} onChange={(e) => setManualEdgeFrom(e.target.value)}
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                      <option value="">Select node...</option>
                      {schema.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className="text-xs font-medium text-gray-500 block mb-1">To (Target)</label>
                    <select value={manualEdgeTo} onChange={(e) => setManualEdgeTo(e.target.value)}
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                      <option value="">Select node...</option>
                      {schema.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 block mb-1">Cardinality</label>
                  <select value={manualEdgeCardinality} onChange={(e) => setManualEdgeCardinality(e.target.value)}
                    className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                    <option value="one_to_one">One to One (1:1)</option>
                    <option value="one_to_many">One to Many (1:N)</option>
                    <option value="many_to_one">Many to One (N:1)</option>
                    <option value="many_to_many">Many to Many (N:N)</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <button onClick={() => setShowAddEdge(false)}
                  className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-600">Cancel</button>
                <button
                  onClick={() => {
                    if (manualEdgeName.trim() && manualEdgeFrom && manualEdgeTo) {
                      addSchemaEdge(manualEdgeName.trim(), manualEdgeFrom, manualEdgeTo, manualEdgeCardinality);
                      setShowAddEdge(false);
                    }
                  }}
                  disabled={!manualEdgeName.trim() || !manualEdgeFrom || !manualEdgeTo}
                  className="rounded bg-brand-600 px-3 py-1.5 text-xs text-white disabled:opacity-50">
                  Create Relationship
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Import Existing Node picker */}
        {showImport && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 z-50"
            onClick={() => setShowImport(false)}>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-96 max-h-[500px] flex flex-col"
              onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-bold">Import Existing Node Type</h3>
                <button onClick={() => setShowImport(false)} className="text-gray-400 hover:text-gray-600 text-xs">Close</button>
              </div>
              <input value={importSearch} onChange={(e) => setImportSearch(e.target.value)}
                placeholder="Search node types..."
                autoFocus
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm mb-3 dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              <div className="flex-1 overflow-y-auto space-y-1">
                {existingNodeTypes
                  .filter((nt) => {
                    const name = (nt.metadata?.name || nt.name || "").toLowerCase();
                    const display = (nt.metadata?.display_name || "").toLowerCase();
                    const search = importSearch.toLowerCase();
                    return !search || name.includes(search) || display.includes(search);
                  })
                  .map((nt) => {
                    const name = nt.metadata?.name || nt.name;
                    const alreadyOnCanvas = !!schema.nodes.find((n) => n.name === name);
                    const category = nt.metadata?.category || "";
                    const attrCount = Object.keys(nt.attributes || {}).length;
                    return (
                      <button key={name} onClick={() => { importExistingNode(nt); }}
                        disabled={alreadyOnCanvas}
                        className={`w-full flex items-center justify-between rounded px-3 py-2 text-left text-xs ${
                          alreadyOnCanvas
                            ? "bg-gray-100 text-gray-400 cursor-not-allowed dark:bg-gray-700"
                            : "hover:bg-brand-50 text-gray-700 dark:text-gray-300 dark:hover:bg-gray-700"
                        }`}>
                        <div className="flex items-center gap-2">
                          <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: nt.metadata?.color || "#94A3B8" }} />
                          <span className="font-medium">{name}</span>
                          {category && <span className="text-gray-400">({category})</span>}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-gray-400">{attrCount} attrs</span>
                          {alreadyOnCanvas && <span className="text-green-500 text-[10px]">on canvas</span>}
                        </div>
                      </button>
                    );
                  })}
              </div>
              <div className="mt-3 text-[10px] text-gray-400">
                Imported nodes appear on the canvas as references. Only new nodes appear in the generated YAML.
              </div>
            </div>
          </div>
        )}
      </div>

      {/* YAML Editor */}
      {showYaml && (
        <div className="w-[400px] border-l border-gray-200 dark:border-gray-700 flex flex-col">
          <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 uppercase">Generated YAML</span>
              <span className="text-[10px] text-gray-400">
                {schema.nodes.filter((n) => !importedNames.has(n.name)).length} new, {importedNames.size} imported, {schema.edges.length} edges
              </span>
            </div>
          </div>
          <div className="flex-1">
            <Editor
              language="yaml"
              value={yamlValue}
              theme="vs-light"
              options={{
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                wordWrap: "on",
                readOnly: true,
              }}
            />
          </div>
        </div>
      )}

      {/* Property Panel */}
      <div className="w-[300px] border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <PropertyPanel />
      </div>
    </div>
  );
}
