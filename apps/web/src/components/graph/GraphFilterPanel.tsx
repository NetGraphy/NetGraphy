/**
 * Power Filter Panel — collapsible panel for building graph filters.
 *
 * Allows users to compose attribute and relationship filter rules,
 * toggle AND/OR logic, save/load presets, and see live filtering stats.
 * All filter state is managed through the graphExplorerStore.
 */

import { useCallback, useMemo, useState } from "react";
import { X, Plus, ChevronLeft, ChevronRight, ArrowLeftRight, Trash2 } from "lucide-react";
import { useGraphExplorerStore } from "@/stores/graphExplorerStore";
import { useSchemaStore } from "@/stores/schemaStore";
import { OPERATORS_FOR_TYPE } from "@/lib/graphFilterEngine";
import type {
  FilterRule,
  AttributeFilterRule,
  RelationshipFilterRule,
  FilterOperator,
} from "@/types/graphFilter";
import type { AttributeDefinition } from "@/types/schema";

// ---------------------------------------------------------------------------
// Operator labels
// ---------------------------------------------------------------------------

const OPERATOR_LABELS: Record<FilterOperator, string> = {
  eq: "=",
  neq: "!=",
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<=",
  contains: "contains",
  starts_with: "starts with",
  ends_with: "ends with",
  in: "in",
  not_in: "not in",
  is_set: "is set",
  is_not_set: "is not set",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GraphFilterPanelProps {
  onClose: () => void;
  displayedCount: number;
  totalCount: number;
}

// ---------------------------------------------------------------------------
// FilterRuleEditor — renders a single rule as a compact inline row
// ---------------------------------------------------------------------------

function FilterRuleEditor({
  rule,
  index,
  onChange,
  onDelete,
}: {
  rule: FilterRule;
  index: number;
  onChange: (index: number, rule: FilterRule) => void;
  onDelete: (index: number) => void;
}) {
  const nodeTypes = useSchemaStore((s) => s.nodeTypes);
  const edgeTypes = useSchemaStore((s) => s.edgeTypes);

  const nodeTypeKeys = useMemo(
    () => ["*", ...Object.keys(nodeTypes).sort()],
    [nodeTypes],
  );

  // Get attributes for selected node type
  const attributes = useMemo((): Record<string, AttributeDefinition> => {
    if (rule.node_type === "*") {
      // Merge all attributes across types
      const merged: Record<string, AttributeDefinition> = {};
      for (const nt of Object.values(nodeTypes)) {
        for (const [name, attr] of Object.entries(nt.attributes)) {
          if (!merged[name]) merged[name] = attr;
        }
      }
      return merged;
    }
    return nodeTypes[rule.node_type]?.attributes ?? {};
  }, [rule.node_type, nodeTypes]);

  const attrKeys = useMemo(() => Object.keys(attributes).sort(), [attributes]);

  // Get edge types filtered for the selected node type
  const filteredEdgeTypes = useMemo(() => {
    if (rule.node_type === "*") return Object.keys(edgeTypes).sort();
    return Object.entries(edgeTypes)
      .filter(
        ([, et]) =>
          et.source.node_types.includes(rule.node_type) ||
          et.target.node_types.includes(rule.node_type),
      )
      .map(([name]) => name)
      .sort();
  }, [rule.node_type, edgeTypes]);

  const isAttr = rule.kind === "attribute";

  // Operators for current field
  const operators = useMemo((): FilterOperator[] => {
    if (!isAttr) return [];
    const attrRule = rule as AttributeFilterRule;
    const attr = attributes[attrRule.field];
    const attrType = attr?.type ?? "string";
    return OPERATORS_FOR_TYPE[attrType] ?? OPERATORS_FOR_TYPE.string;
  }, [isAttr, rule, attributes]);

  // Current attribute definition for value input
  const currentAttr = isAttr ? attributes[(rule as AttributeFilterRule).field] : undefined;

  // Change node type, reset dependent fields
  const handleNodeTypeChange = useCallback(
    (newType: string) => {
      if (isAttr) {
        onChange(index, {
          kind: "attribute",
          node_type: newType,
          field: "",
          operator: "eq",
          value: "",
        });
      } else {
        onChange(index, {
          ...(rule as RelationshipFilterRule),
          node_type: newType,
          edge_type: "",
        });
      }
    },
    [index, isAttr, rule, onChange],
  );

  const handleKindToggle = useCallback(
    (newKind: "attribute" | "relationship") => {
      if (newKind === "attribute") {
        onChange(index, {
          kind: "attribute",
          node_type: rule.node_type,
          field: "",
          operator: "eq",
          value: "",
        });
      } else {
        onChange(index, {
          kind: "relationship",
          node_type: rule.node_type,
          edge_type: "",
          direction: "any",
          presence: "has",
        });
      }
    },
    [index, rule.node_type, onChange],
  );

  const noValueNeeded =
    isAttr &&
    ((rule as AttributeFilterRule).operator === "is_set" ||
      (rule as AttributeFilterRule).operator === "is_not_set");

  return (
    <div className="flex items-center gap-1 rounded border border-gray-100 bg-gray-50 px-1.5 py-1">
      {/* Node type */}
      <select
        className="w-20 truncate rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
        value={rule.node_type}
        onChange={(e) => handleNodeTypeChange(e.target.value)}
      >
        {nodeTypeKeys.map((nt) => (
          <option key={nt} value={nt}>
            {nt === "*" ? "Any Type" : nodeTypes[nt]?.metadata?.display_name ?? nt}
          </option>
        ))}
      </select>

      {/* Kind toggle */}
      <div className="flex overflow-hidden rounded border border-gray-200 text-[10px]">
        <button
          type="button"
          className={`px-1.5 py-0.5 ${
            isAttr
              ? "bg-indigo-100 text-indigo-700"
              : "bg-white text-gray-500 hover:bg-gray-50"
          }`}
          onClick={() => handleKindToggle("attribute")}
        >
          Attr
        </button>
        <button
          type="button"
          className={`px-1.5 py-0.5 ${
            !isAttr
              ? "bg-indigo-100 text-indigo-700"
              : "bg-white text-gray-500 hover:bg-gray-50"
          }`}
          onClick={() => handleKindToggle("relationship")}
        >
          Rel
        </button>
      </div>

      {/* Attribute rule fields */}
      {isAttr && (
        <>
          <select
            className="w-24 truncate rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
            value={(rule as AttributeFilterRule).field}
            onChange={(e) =>
              onChange(index, {
                ...(rule as AttributeFilterRule),
                field: e.target.value,
                operator: "eq",
                value: "",
              })
            }
          >
            <option value="">field...</option>
            {attrKeys.map((f) => (
              <option key={f} value={f}>
                {attributes[f]?.display_name ?? f}
              </option>
            ))}
          </select>

          <select
            className="w-20 truncate rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
            value={(rule as AttributeFilterRule).operator}
            onChange={(e) =>
              onChange(index, {
                ...(rule as AttributeFilterRule),
                operator: e.target.value as FilterOperator,
              })
            }
          >
            {operators.map((op) => (
              <option key={op} value={op}>
                {OPERATOR_LABELS[op]}
              </option>
            ))}
          </select>

          {!noValueNeeded && (
            <ValueInput
              attr={currentAttr}
              value={(rule as AttributeFilterRule).value}
              onChange={(val) =>
                onChange(index, {
                  ...(rule as AttributeFilterRule),
                  value: val,
                })
              }
            />
          )}
        </>
      )}

      {/* Relationship rule fields */}
      {!isAttr && (
        <>
          <select
            className="w-28 truncate rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
            value={(rule as RelationshipFilterRule).edge_type}
            onChange={(e) =>
              onChange(index, {
                ...(rule as RelationshipFilterRule),
                edge_type: e.target.value,
              })
            }
          >
            <option value="">edge type...</option>
            {filteredEdgeTypes.map((et) => (
              <option key={et} value={et}>
                {et}
              </option>
            ))}
          </select>

          {/* Direction buttons */}
          <div className="flex overflow-hidden rounded border border-gray-200 text-[10px]">
            <button
              type="button"
              className={`px-1 py-0.5 ${
                (rule as RelationshipFilterRule).direction === "incoming"
                  ? "bg-indigo-100 text-indigo-700"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
              onClick={() =>
                onChange(index, {
                  ...(rule as RelationshipFilterRule),
                  direction: "incoming",
                })
              }
              title="Incoming"
            >
              <ChevronLeft size={12} />
            </button>
            <button
              type="button"
              className={`px-1 py-0.5 ${
                (rule as RelationshipFilterRule).direction === "outgoing"
                  ? "bg-indigo-100 text-indigo-700"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
              onClick={() =>
                onChange(index, {
                  ...(rule as RelationshipFilterRule),
                  direction: "outgoing",
                })
              }
              title="Outgoing"
            >
              <ChevronRight size={12} />
            </button>
            <button
              type="button"
              className={`px-1 py-0.5 ${
                (rule as RelationshipFilterRule).direction === "any"
                  ? "bg-indigo-100 text-indigo-700"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
              onClick={() =>
                onChange(index, {
                  ...(rule as RelationshipFilterRule),
                  direction: "any",
                })
              }
              title="Any direction"
            >
              <ArrowLeftRight size={12} />
            </button>
          </div>

          {/* Has / Has Not toggle */}
          <div className="flex overflow-hidden rounded border border-gray-200 text-[10px]">
            <button
              type="button"
              className={`px-1.5 py-0.5 ${
                (rule as RelationshipFilterRule).presence === "has"
                  ? "bg-green-100 text-green-700"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
              onClick={() =>
                onChange(index, {
                  ...(rule as RelationshipFilterRule),
                  presence: "has",
                })
              }
            >
              Has
            </button>
            <button
              type="button"
              className={`px-1.5 py-0.5 ${
                (rule as RelationshipFilterRule).presence === "has_not"
                  ? "bg-red-100 text-red-700"
                  : "bg-white text-gray-500 hover:bg-gray-50"
              }`}
              onClick={() =>
                onChange(index, {
                  ...(rule as RelationshipFilterRule),
                  presence: "has_not",
                })
              }
            >
              Not
            </button>
          </div>
        </>
      )}

      {/* Delete button */}
      <button
        type="button"
        onClick={() => onDelete(index)}
        className="ml-auto flex-shrink-0 rounded p-0.5 text-red-400 hover:bg-red-50 hover:text-red-600"
        title="Remove rule"
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ValueInput — renders the appropriate input for the attribute type
// ---------------------------------------------------------------------------

function ValueInput({
  attr,
  value,
  onChange,
}: {
  attr: AttributeDefinition | undefined;
  value: unknown;
  onChange: (val: unknown) => void;
}) {
  const attrType = attr?.type ?? "string";

  if (attrType === "enum" && attr?.enum_values) {
    return (
      <select
        className="w-24 truncate rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">value...</option>
        {attr.enum_values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    );
  }

  if (attrType === "boolean") {
    return (
      <select
        className="w-16 rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value === "true")}
      >
        <option value="">--</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }

  if (attrType === "integer" || attrType === "float") {
    return (
      <input
        type="number"
        className="w-20 rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
        placeholder="value"
        value={value != null ? String(value) : ""}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? "" : attrType === "integer" ? parseInt(v, 10) : parseFloat(v));
        }}
      />
    );
  }

  // Default: string input
  return (
    <input
      type="text"
      className="w-24 rounded border border-gray-200 bg-white px-1 py-0.5 text-xs"
      placeholder="value"
      value={String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

// ---------------------------------------------------------------------------
// GraphFilterPanel — main component
// ---------------------------------------------------------------------------

export function GraphFilterPanel({
  onClose,
  displayedCount,
  totalCount,
}: GraphFilterPanelProps) {
  const {
    filter,
    filterPresets,
    toggleFilterEnabled,
    addFilterRule,
    removeFilterRule,
    updateFilterRule,
    setFilterLogic,
    saveFilterPreset,
    loadFilterPreset,
    deleteFilterPreset,
  } = useGraphExplorerStore();

  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  // Find active preset (matches current filter state)
  const activePresetId = useMemo(() => {
    const currentJson = JSON.stringify(filter);
    return filterPresets.find((p) => JSON.stringify(p.filter) === currentJson)?.id ?? null;
  }, [filter, filterPresets]);

  const handleAddRule = useCallback(() => {
    addFilterRule({
      kind: "attribute",
      node_type: "*",
      field: "",
      operator: "eq",
      value: "",
    });
  }, [addFilterRule]);

  const handleSave = useCallback(() => {
    if (!saveName.trim()) return;
    saveFilterPreset(saveName.trim());
    setSaveName("");
    setShowSaveInput(false);
  }, [saveName, saveFilterPreset]);

  return (
    <div className="flex w-80 flex-col rounded-lg border border-gray-200 bg-white shadow-lg">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
        <span className="text-xs font-semibold text-gray-700">Power Filters</span>
        <div className="flex items-center gap-2">
          {/* Enabled toggle */}
          <button
            type="button"
            onClick={toggleFilterEnabled}
            className={`relative h-5 w-9 rounded-full transition-colors ${
              filter.enabled ? "bg-indigo-500" : "bg-gray-300"
            }`}
            title={filter.enabled ? "Disable filter" : "Enable filter"}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                filter.enabled ? "translate-x-4" : "translate-x-0.5"
              }`}
            />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Preset bar */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-gray-100 px-3 py-1.5">
        {filterPresets.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => loadFilterPreset(p.id)}
            onContextMenu={(e) => {
              e.preventDefault();
              if (!p.id.startsWith("builtin:")) deleteFilterPreset(p.id);
            }}
            className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors ${
              activePresetId === p.id
                ? "bg-indigo-100 text-indigo-700"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            title={p.description ?? p.name}
          >
            {p.name}
          </button>
        ))}
        {!showSaveInput ? (
          <button
            type="button"
            onClick={() => setShowSaveInput(true)}
            className="flex-shrink-0 rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-[10px] text-gray-400 hover:border-gray-400 hover:text-gray-600"
          >
            Save
          </button>
        ) : (
          <div className="flex flex-shrink-0 items-center gap-1">
            <input
              type="text"
              className="w-20 rounded border border-gray-200 px-1 py-0.5 text-[10px]"
              placeholder="Preset name"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSave();
                if (e.key === "Escape") setShowSaveInput(false);
              }}
              autoFocus
            />
            <button
              type="button"
              onClick={handleSave}
              className="rounded bg-indigo-500 px-1.5 py-0.5 text-[10px] text-white hover:bg-indigo-600"
            >
              OK
            </button>
          </div>
        )}
      </div>

      {/* Logic toggle */}
      <div className="flex items-center gap-2 px-3 py-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wide text-gray-400">
          Match
        </span>
        <div className="flex overflow-hidden rounded border border-gray-200 text-xs">
          <button
            type="button"
            className={`px-2 py-0.5 font-medium ${
              filter.rootGroup.logic === "and"
                ? "bg-indigo-100 text-indigo-700"
                : "bg-white text-gray-500 hover:bg-gray-50"
            }`}
            onClick={() => setFilterLogic("and")}
          >
            AND
          </button>
          <button
            type="button"
            className={`px-2 py-0.5 font-medium ${
              filter.rootGroup.logic === "or"
                ? "bg-indigo-100 text-indigo-700"
                : "bg-white text-gray-500 hover:bg-gray-50"
            }`}
            onClick={() => setFilterLogic("or")}
          >
            OR
          </button>
        </div>
      </div>

      {/* Rule list */}
      <div className="flex max-h-64 flex-col gap-1 overflow-y-auto px-3 py-1">
        {filter.rootGroup.rules.length === 0 && (
          <p className="py-2 text-center text-xs text-gray-400">
            No rules yet. Add one below.
          </p>
        )}
        {filter.rootGroup.rules.map((rule, i) => (
          <FilterRuleEditor
            key={i}
            rule={rule}
            index={i}
            onChange={updateFilterRule}
            onDelete={removeFilterRule}
          />
        ))}
      </div>

      {/* Add rule button */}
      <div className="border-t border-gray-100 px-3 py-1.5">
        <button
          type="button"
          onClick={handleAddRule}
          className="flex w-full items-center justify-center gap-1 rounded border border-dashed border-gray-300 py-1 text-xs text-gray-500 hover:border-gray-400 hover:text-gray-700"
        >
          <Plus size={12} />
          Add Rule
        </button>
      </div>

      {/* Stats line */}
      <div className="border-t border-gray-100 px-3 py-1.5">
        <span className="text-[10px] text-gray-500">
          Showing{" "}
          <span className="font-semibold text-gray-700">{displayedCount}</span>{" "}
          of{" "}
          <span className="font-semibold text-gray-700">{totalCount}</span>{" "}
          nodes
        </span>
      </div>
    </div>
  );
}
