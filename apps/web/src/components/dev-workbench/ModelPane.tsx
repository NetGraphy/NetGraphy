/**
 * ModelPane — Data model explorer for understanding schema types.
 *
 * Left: Node type / Edge type list with search
 * Center: Field definitions with types, constraints, and template usage hints
 * Right: Relationship graph showing connected types
 */

import { useState } from "react";
import { useSchemaStore } from "@/stores/schemaStore";
import type { NodeTypeDefinition, EdgeTypeDefinition } from "@/types/schema";

type ModelTab = "nodes" | "edges";

const TYPE_COLORS: Record<string, string> = {
  string: "text-green-300",
  text: "text-green-300",
  integer: "text-blue-300",
  float: "text-blue-300",
  boolean: "text-amber-300",
  datetime: "text-purple-300",
  date: "text-purple-300",
  ip_address: "text-cyan-300",
  cidr: "text-cyan-300",
  mac_address: "text-cyan-300",
  url: "text-teal-300",
  email: "text-teal-300",
  enum: "text-orange-300",
  json: "text-pink-300",
  reference: "text-rose-300",
  "list[string]": "text-green-200",
  "list[integer]": "text-blue-200",
};

const CARDINALITY_LABELS: Record<string, string> = {
  one_to_one: "1:1",
  one_to_many: "1:N",
  many_to_one: "N:1",
  many_to_many: "N:N",
};

export function ModelPane() {
  const { nodeTypes, edgeTypes } = useSchemaStore();

  const [modelTab, setModelTab] = useState<ModelTab>("nodes");
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [searchFilter, setSearchFilter] = useState("");
  const [showTemplateHints, setShowTemplateHints] = useState(true);

  const ntList = Object.values(nodeTypes).sort((a, b) =>
    (a.metadata.display_name || a.metadata.name).localeCompare(b.metadata.display_name || b.metadata.name),
  );

  const etList = Object.values(edgeTypes).sort((a, b) =>
    a.metadata.name.localeCompare(b.metadata.name),
  );

  const filteredNT = ntList.filter(
    (nt) =>
      !searchFilter ||
      nt.metadata.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
      nt.metadata.display_name?.toLowerCase().includes(searchFilter.toLowerCase()) ||
      nt.metadata.category?.toLowerCase().includes(searchFilter.toLowerCase()),
  );

  const filteredET = etList.filter(
    (et) =>
      !searchFilter ||
      et.metadata.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
      et.metadata.display_name?.toLowerCase().includes(searchFilter.toLowerCase()),
  );

  // Group node types by category
  const categorizedNT = filteredNT.reduce<Record<string, NodeTypeDefinition[]>>((acc, nt) => {
    const cat = nt.metadata.category || "Other";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(nt);
    return acc;
  }, {});

  const selectedNodeType = selectedType && modelTab === "nodes" ? nodeTypes[selectedType] : null;
  const selectedEdgeType = selectedType && modelTab === "edges" ? edgeTypes[selectedType] : null;

  // Find all relationships for a selected node type
  const relatedEdges = selectedType && modelTab === "nodes"
    ? Object.values(edgeTypes).filter(
        (et) =>
          et.source.node_types.includes(selectedType) ||
          et.target.node_types.includes(selectedType),
      )
    : [];

  // For edge type, find related node types
  const relatedNodes = selectedEdgeType
    ? [...new Set([...selectedEdgeType.source.node_types, ...selectedEdgeType.target.node_types])]
    : [];

  return (
    <div className="flex h-full">
      {/* ---- Left: Type Explorer ---- */}
      <div className="flex w-64 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800">
        {/* Tab toggle */}
        <div className="flex border-b border-gray-700">
          <button
            onClick={() => { setModelTab("nodes"); setSelectedType(null); }}
            className={`flex-1 py-2 text-center text-xs font-semibold uppercase ${
              modelTab === "nodes"
                ? "border-b-2 border-brand-400 text-brand-300"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Node Types ({ntList.length})
          </button>
          <button
            onClick={() => { setModelTab("edges"); setSelectedType(null); }}
            className={`flex-1 py-2 text-center text-xs font-semibold uppercase ${
              modelTab === "edges"
                ? "border-b-2 border-brand-400 text-brand-300"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Edge Types ({etList.length})
          </button>
        </div>

        {/* Search */}
        <div className="border-b border-gray-700 px-3 py-2">
          <input
            type="text"
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            placeholder="Search types..."
            className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          />
        </div>

        {/* Type list */}
        <div className="flex-1 overflow-y-auto">
          {modelTab === "nodes" ? (
            Object.entries(categorizedNT).map(([category, types]) => (
              <div key={category} className="mt-1">
                <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                  {category}
                </div>
                <div className="space-y-0.5 px-1">
                  {types.map((nt) => (
                    <button
                      key={nt.metadata.name}
                      onClick={() => setSelectedType(nt.metadata.name)}
                      className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left ${
                        selectedType === nt.metadata.name
                          ? "bg-brand-600/20 text-brand-300"
                          : "text-gray-300 hover:bg-gray-700"
                      }`}
                    >
                      {nt.metadata.color && (
                        <span
                          className="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                          style={{ backgroundColor: nt.metadata.color }}
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {nt.metadata.display_name || nt.metadata.name}
                        </div>
                        <div className="text-[10px] text-gray-500">
                          {Object.keys(nt.attributes).length} fields
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div className="space-y-0.5 px-1 pt-1">
              {filteredET.map((et) => (
                <button
                  key={et.metadata.name}
                  onClick={() => setSelectedType(et.metadata.name)}
                  className={`flex w-full flex-col rounded px-2 py-1.5 text-left ${
                    selectedType === et.metadata.name
                      ? "bg-brand-600/20 text-brand-300"
                      : "text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  <div className="truncate text-sm font-medium">{et.metadata.name}</div>
                  <div className="truncate text-[10px] text-gray-500">
                    {et.source.node_types.join("|")} {"-> "} {et.target.node_types.join("|")}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---- Center: Type Details ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {!selectedType ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <svg className="mx-auto h-12 w-12 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
              </svg>
              <div className="mt-3 text-sm text-gray-500">
                Select a type to explore its fields and relationships
              </div>
            </div>
          </div>
        ) : selectedNodeType ? (
          <NodeTypeDetail
            nt={selectedNodeType}
            relatedEdges={relatedEdges}
            showTemplateHints={showTemplateHints}
            onToggleHints={() => setShowTemplateHints(!showTemplateHints)}
            onSelectType={(t) => { setModelTab("edges"); setSelectedType(t); }}
          />
        ) : selectedEdgeType ? (
          <EdgeTypeDetail
            et={selectedEdgeType}
            relatedNodes={relatedNodes}
            nodeTypes={nodeTypes}
            onSelectNode={(t) => { setModelTab("nodes"); setSelectedType(t); }}
          />
        ) : null}
      </div>
    </div>
  );
}

function NodeTypeDetail({
  nt,
  relatedEdges,
  showTemplateHints,
  onToggleHints,
  onSelectType,
}: {
  nt: NodeTypeDefinition;
  relatedEdges: EdgeTypeDefinition[];
  showTemplateHints: boolean;
  onToggleHints: () => void;
  onSelectType: (t: string) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 px-6 py-4" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
        <div className="flex items-center gap-3">
          {nt.metadata.color && (
            <span
              className="h-4 w-4 rounded"
              style={{ backgroundColor: nt.metadata.color }}
            />
          )}
          <div>
            <h2 className="text-lg font-semibold text-gray-100">
              {nt.metadata.display_name || nt.metadata.name}
            </h2>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <code className="text-gray-400">{nt.metadata.name}</code>
              {nt.metadata.category && (
                <>
                  <span className="text-gray-600">|</span>
                  <span>{nt.metadata.category}</span>
                </>
              )}
              <span className="text-gray-600">|</span>
              <span>{Object.keys(nt.attributes).length} fields</span>
              <span className="text-gray-600">|</span>
              <span>{relatedEdges.length} relationships</span>
            </div>
          </div>
          <div className="ml-auto">
            <button
              onClick={onToggleHints}
              className={`rounded px-2 py-1 text-xs ${
                showTemplateHints
                  ? "bg-brand-600/20 text-brand-300"
                  : "text-gray-400 hover:bg-gray-700"
              }`}
            >
              Template Hints
            </button>
          </div>
        </div>
        {nt.metadata.description && (
          <p className="mt-2 text-sm text-gray-400">{nt.metadata.description}</p>
        )}
      </div>

      {/* Content: two columns - fields & relationships */}
      <div className="flex min-h-0 flex-1">
        {/* Fields */}
        <div className="flex min-w-0 flex-1 flex-col overflow-auto border-r border-gray-700">
          <div className="sticky top-0 border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Fields
          </div>
          <div className="divide-y divide-gray-800">
            {Object.entries(nt.attributes).map(([attrName, attr]) => (
              <div key={attrName} className="px-4 py-2.5 hover:bg-gray-800/50">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <code className="text-sm font-medium text-gray-200">{attrName}</code>
                    {attr.display_name && attr.display_name !== attrName && (
                      <span className="text-xs text-gray-500">({attr.display_name})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs font-mono ${TYPE_COLORS[attr.type] || "text-gray-400"}`}>
                      {attr.type}
                    </span>
                  </div>
                </div>

                <div className="mt-1 flex items-center gap-2">
                  {attr.required && (
                    <span className="rounded bg-amber-500/10 px-1 py-0.5 text-[10px] font-medium text-amber-400">
                      required
                    </span>
                  )}
                  {attr.unique && (
                    <span className="rounded bg-purple-500/10 px-1 py-0.5 text-[10px] font-medium text-purple-400">
                      unique
                    </span>
                  )}
                  {attr.indexed && (
                    <span className="rounded bg-blue-500/10 px-1 py-0.5 text-[10px] font-medium text-blue-400">
                      indexed
                    </span>
                  )}
                  {attr.default !== null && attr.default !== undefined && (
                    <span className="text-[10px] text-gray-500">
                      default: <code className="text-gray-400">{String(attr.default)}</code>
                    </span>
                  )}
                </div>

                {attr.enum_values && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {attr.enum_values.map((v) => (
                      <span key={v} className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-300">
                        {v}
                      </span>
                    ))}
                  </div>
                )}

                {attr.description && (
                  <div className="mt-1 text-xs text-gray-500">{attr.description}</div>
                )}

                {showTemplateHints && (
                  <div className="mt-1">
                    <code className="text-[10px] text-brand-400/60">
                      {"{{ parsed." + attrName.toUpperCase() + " }}"}
                    </code>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Relationships */}
        <div className="flex w-80 flex-shrink-0 flex-col overflow-auto">
          <div className="sticky top-0 border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Relationships ({relatedEdges.length})
          </div>
          <div className="space-y-2 p-3">
            {relatedEdges.map((et) => {
              const isSource = et.source.node_types.includes(nt.metadata.name);
              const targetTypes = isSource ? et.target.node_types : et.source.node_types;

              return (
                <button
                  key={et.metadata.name}
                  onClick={() => onSelectType(et.metadata.name)}
                  className="w-full rounded border border-gray-700 bg-gray-900/50 p-3 text-left transition-colors hover:border-gray-600 hover:bg-gray-800"
                >
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      isSource ? "bg-blue-500/20 text-blue-300" : "bg-emerald-500/20 text-emerald-300"
                    }`}>
                      {isSource ? "OUT" : "IN"}
                    </span>
                    <code className="text-sm font-medium text-gray-200">
                      {et.metadata.name}
                    </code>
                  </div>

                  <div className="mt-1.5 flex items-center gap-1 text-xs">
                    <span className="text-gray-400">{nt.metadata.name}</span>
                    <span className="text-gray-600">
                      {isSource ? " -> " : " <- "}
                    </span>
                    <span className="text-brand-300">{targetTypes.join(" | ")}</span>
                  </div>

                  <div className="mt-1 flex items-center gap-2 text-[10px]">
                    <span className="text-gray-500">
                      Cardinality: {CARDINALITY_LABELS[et.cardinality] || et.cardinality}
                    </span>
                    {et.inverse_name && (
                      <span className="text-gray-600">
                        inverse: {et.inverse_name}
                      </span>
                    )}
                  </div>

                  {et.metadata.description && (
                    <div className="mt-1 text-[10px] text-gray-500">
                      {et.metadata.description}
                    </div>
                  )}

                  {/* Mapping template hint */}
                  {showTemplateHints && (
                    <div className="mt-2 rounded bg-gray-800 p-1.5">
                      <div className="text-[10px] font-medium text-gray-500">Mapping template:</div>
                      <pre className="mt-0.5 text-[10px] text-brand-400/60">
{`- target_edge_type: ${et.metadata.name}
  source:
    node_type: ${isSource ? nt.metadata.name : targetTypes[0]}
    match_on:
      <field>: "{{ parsed.<FIELD> }}"
  target:
    node_type: ${isSource ? targetTypes[0] : nt.metadata.name}
    match_on:
      <field>: "{{ parsed.<FIELD> }}"`}
                      </pre>
                    </div>
                  )}
                </button>
              );
            })}
            {relatedEdges.length === 0 && (
              <div className="py-4 text-center text-xs text-gray-500">
                No relationships defined
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function EdgeTypeDetail({
  et,
  relatedNodes,
  nodeTypes,
  onSelectNode,
}: {
  et: EdgeTypeDefinition;
  relatedNodes: string[];
  nodeTypes: Record<string, NodeTypeDefinition>;
  onSelectNode: (t: string) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-700 px-6 py-4" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
        <h2 className="text-lg font-semibold text-gray-100">{et.metadata.name}</h2>
        <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
          <span>{et.source.node_types.join(" | ")}</span>
          <span className="text-gray-600">{"-> "}</span>
          <span>{et.target.node_types.join(" | ")}</span>
          <span className="text-gray-600">|</span>
          <span>{CARDINALITY_LABELS[et.cardinality] || et.cardinality}</span>
          {et.inverse_name && (
            <>
              <span className="text-gray-600">|</span>
              <span>inverse: {et.inverse_name}</span>
            </>
          )}
        </div>
        {et.metadata.description && (
          <p className="mt-2 text-sm text-gray-400">{et.metadata.description}</p>
        )}
      </div>

      {/* Content */}
      <div className="flex min-h-0 flex-1">
        {/* Edge attributes */}
        <div className="flex min-w-0 flex-1 flex-col overflow-auto border-r border-gray-700">
          <div className="sticky top-0 border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Edge Attributes ({Object.keys(et.attributes).length})
          </div>
          {Object.keys(et.attributes).length > 0 ? (
            <div className="divide-y divide-gray-800">
              {Object.entries(et.attributes).map(([attrName, attr]) => (
                <div key={attrName} className="px-4 py-2.5">
                  <div className="flex items-center justify-between">
                    <code className="text-sm font-medium text-gray-200">{attrName}</code>
                    <span className={`text-xs font-mono ${TYPE_COLORS[attr.type] || "text-gray-400"}`}>
                      {attr.type}
                    </span>
                  </div>
                  {attr.description && (
                    <div className="mt-1 text-xs text-gray-500">{attr.description}</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              No attributes on this edge type
            </div>
          )}

          {/* Mapping template */}
          <div className="mt-auto border-t border-gray-700 p-4">
            <div className="text-xs font-semibold uppercase text-gray-500">Mapping Template</div>
            <pre className="mt-2 rounded border border-gray-700 bg-gray-900 p-3 text-xs text-brand-400/80">
{`- target_edge_type: ${et.metadata.name}
  source:
    node_type: ${et.source.node_types[0]}
    match_on:
      <field>: "{{ parsed.<FIELD> }}"
  target:
    node_type: ${et.target.node_types[0]}
    match_on:
      <field>: "{{ parsed.<FIELD> }}"${Object.keys(et.attributes).length > 0 ? `
  attributes:${Object.entries(et.attributes).map(([k]) => `
    ${k}: "{{ parsed.${k.toUpperCase()} }}"`).join("")}` : ""}`}
            </pre>
          </div>
        </div>

        {/* Connected node types */}
        <div className="flex w-72 flex-shrink-0 flex-col overflow-auto">
          <div className="sticky top-0 border-b border-gray-700 bg-gray-900 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            Connected Types
          </div>
          <div className="space-y-2 p-3">
            {/* Source types */}
            <div className="text-[10px] font-semibold uppercase text-gray-500">Source Types</div>
            {et.source.node_types.map((ntName) => {
              const nt = nodeTypes[ntName];
              return (
                <button
                  key={`src-${ntName}`}
                  onClick={() => onSelectNode(ntName)}
                  className="w-full rounded border border-gray-700 bg-gray-900/50 p-2 text-left hover:border-gray-600 hover:bg-gray-800"
                >
                  <div className="flex items-center gap-2">
                    {nt?.metadata.color && (
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: nt.metadata.color }} />
                    )}
                    <span className="text-sm font-medium text-gray-200">
                      {nt?.metadata.display_name || ntName}
                    </span>
                  </div>
                  {nt && (
                    <div className="mt-1 text-[10px] text-gray-500">
                      {Object.keys(nt.attributes).length} fields
                    </div>
                  )}
                </button>
              );
            })}

            {/* Target types */}
            <div className="mt-2 text-[10px] font-semibold uppercase text-gray-500">Target Types</div>
            {et.target.node_types.map((ntName) => {
              const nt = nodeTypes[ntName];
              return (
                <button
                  key={`tgt-${ntName}`}
                  onClick={() => onSelectNode(ntName)}
                  className="w-full rounded border border-gray-700 bg-gray-900/50 p-2 text-left hover:border-gray-600 hover:bg-gray-800"
                >
                  <div className="flex items-center gap-2">
                    {nt?.metadata.color && (
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: nt.metadata.color }} />
                    )}
                    <span className="text-sm font-medium text-gray-200">
                      {nt?.metadata.display_name || ntName}
                    </span>
                  </div>
                  {nt && (
                    <div className="mt-1 text-[10px] text-gray-500">
                      {Object.keys(nt.attributes).length} fields
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
