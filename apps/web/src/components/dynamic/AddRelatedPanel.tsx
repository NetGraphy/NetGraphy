/**
 * AddRelatedPanel — create new related nodes and link existing ones.
 *
 * Supports two modes:
 * - "create": create a new node and automatically link it via an edge
 * - "link": search for an existing node and link it
 *
 * Also supports bulk create for repetitive items (e.g. interfaces).
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, nodesApi, queryApi } from "@/api/client";
import { useSchemaStore } from "@/stores/schemaStore";
import type { AttributeDefinition, QueryResult } from "@/types/schema";

interface AddRelatedPanelProps {
  sourceNodeType: string;
  sourceNodeId: string;
  edgeType: string;
  targetType: string;
  label: string;
  onClose: () => void;
}

export function AddRelatedPanel({
  sourceNodeType,
  sourceNodeId,
  edgeType,
  targetType,
  label,
  onClose,
}: AddRelatedPanelProps) {
  const [mode, setMode] = useState<"create" | "link" | "bulk">("create");

  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Add {label}</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">&times;</button>
      </div>

      {/* Mode tabs */}
      <div className="mb-4 flex gap-2">
        {(["create", "link", "bulk"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              mode === m
                ? "bg-brand-600 text-white"
                : "bg-white text-gray-600 hover:bg-gray-100"
            }`}
          >
            {m === "create" ? "Create New" : m === "link" ? "Link Existing" : "Bulk Create"}
          </button>
        ))}
      </div>

      {mode === "create" && (
        <CreateForm
          sourceNodeId={sourceNodeId}
          sourceNodeType={sourceNodeType}
          edgeType={edgeType}
          targetType={targetType}
          onClose={onClose}
        />
      )}
      {mode === "link" && (
        <LinkForm
          sourceNodeId={sourceNodeId}
          sourceNodeType={sourceNodeType}
          edgeType={edgeType}
          targetType={targetType}
          onClose={onClose}
        />
      )}
      {mode === "bulk" && (
        <BulkCreateForm
          sourceNodeId={sourceNodeId}
          sourceNodeType={sourceNodeType}
          edgeType={edgeType}
          targetType={targetType}
          label={label}
          onClose={onClose}
        />
      )}
    </div>
  );
}

// --- Create Form ---

function CreateForm({
  sourceNodeId,
  sourceNodeType,
  edgeType,
  targetType,
  onClose,
}: {
  sourceNodeId: string;
  sourceNodeType: string;
  edgeType: string;
  targetType: string;
  onClose: () => void;
}) {
  const { getNodeType } = useSchemaStore();
  const targetSchema = getNodeType(targetType);
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);

  const editableAttrs = Object.entries(targetSchema?.attributes || {}).filter(
    ([, attr]) => !attr.auto_set && attr.ui.form_visible !== false,
  );

  const createMutation = useMutation({
    mutationFn: async () => {
      // 1. Create the node
      const nodeResp = await nodesApi.create(targetType, form);
      const nodeId = nodeResp.data.data.id;
      // 2. Create the edge
      await api.post(`/edges/${edgeType}`, {
        source_id: sourceNodeId,
        target_id: nodeId,
      });
      return nodeId;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relationships", sourceNodeType, sourceNodeId] });
      setForm({});
      setError(null);
      onClose();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message;
      setError(msg || "Failed to create");
    },
  });

  return (
    <div>
      {error && <div className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>}
      <div className="grid grid-cols-2 gap-3">
        {editableAttrs.map(([name, attr]) => (
          <FieldInput key={name} name={name} attr={attr} value={form[name]} onChange={(v) => setForm((f) => ({ ...f, [name]: v }))} />
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {createMutation.isPending ? "Creating..." : `Create ${targetType}`}
        </button>
        <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
      </div>
    </div>
  );
}

// --- Link Form ---

function LinkForm({
  sourceNodeId,
  sourceNodeType,
  edgeType,
  targetType,
  onClose,
}: {
  sourceNodeId: string;
  sourceNodeType: string;
  edgeType: string;
  targetType: string;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<{ id: string; label: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    if (!search.trim()) return;
    setSearching(true);
    try {
      const resp = await queryApi.executeCypher(
        `MATCH (n:${targetType}) WHERE toLower(n.name) CONTAINS $term OR toLower(n.hostname) CONTAINS $term OR toLower(n.address) CONTAINS $term OR toLower(n.label) CONTAINS $term OR toLower(n.prefix) CONTAINS $term OR toLower(n.cid) CONTAINS $term RETURN n LIMIT 20`,
        { term: search.trim().toLowerCase() },
      );
      const data = resp.data.data as QueryResult;
      setResults(data.nodes.map((n) => ({ id: n.id, label: n.label })));
    } catch {
      setResults([]);
    }
    setSearching(false);
  };

  const linkMutation = useMutation({
    mutationFn: (targetId: string) =>
      api.post(`/edges/${edgeType}`, { source_id: sourceNodeId, target_id: targetId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["relationships", sourceNodeType, sourceNodeId] });
      setError(null);
      onClose();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message;
      setError(msg || "Failed to link");
    },
  });

  return (
    <div>
      {error && <div className="mb-3 rounded bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div>}
      <div className="flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          placeholder={`Search ${targetType}...`}
          className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          className="rounded-md bg-gray-100 px-3 py-1.5 text-sm hover:bg-gray-200"
        >
          {searching ? "..." : "Search"}
        </button>
      </div>
      {results.length > 0 && (
        <div className="mt-2 max-h-48 overflow-y-auto rounded-md border border-gray-200">
          {results.map((r) => (
            <button
              key={r.id}
              onClick={() => linkMutation.mutate(r.id)}
              disabled={linkMutation.isPending}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-gray-50"
            >
              <span>{r.label}</span>
              <span className="text-xs text-brand-600">Link</span>
            </button>
          ))}
        </div>
      )}
      <div className="mt-3">
        <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
      </div>
    </div>
  );
}

// --- Bulk Create Form ---

function BulkCreateForm({
  sourceNodeId,
  sourceNodeType,
  edgeType,
  targetType,
  label,
  onClose,
}: {
  sourceNodeId: string;
  sourceNodeType: string;
  edgeType: string;
  targetType: string;
  label: string;
  onClose: () => void;
}) {
  const { getNodeType } = useSchemaStore();
  const targetSchema = getNodeType(targetType);
  const queryClient = useQueryClient();
  const [pattern, setPattern] = useState("");
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(4);
  const [defaults, setDefaults] = useState<Record<string, unknown>>({});
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<{ created: number; errors: number } | null>(null);

  // Common default fields for the target type
  const defaultableAttrs = Object.entries(targetSchema?.attributes || {}).filter(
    ([, attr]) => !attr.auto_set && attr.ui.form_visible !== false && (attr.type === "enum" || attr.type === "integer" || attr.type === "boolean"),
  );

  const preview = [];
  for (let i = rangeStart; i <= rangeEnd; i++) {
    preview.push(pattern.replace(/\{i\}/g, String(i)).replace(/\{n\}/g, String(i)));
  }

  const handleBulkCreate = async () => {
    setCreating(true);
    let created = 0;
    let errors = 0;

    for (let i = rangeStart; i <= rangeEnd; i++) {
      const name = pattern.replace(/\{i\}/g, String(i)).replace(/\{n\}/g, String(i));
      try {
        const nodeResp = await nodesApi.create(targetType, { name, ...defaults });
        const nodeId = nodeResp.data.data.id;
        await api.post(`/edges/${edgeType}`, { source_id: sourceNodeId, target_id: nodeId });
        created++;
      } catch {
        errors++;
      }
    }

    setResult({ created, errors });
    setCreating(false);
    queryClient.invalidateQueries({ queryKey: ["relationships", sourceNodeType, sourceNodeId] });
  };

  return (
    <div>
      <p className="mb-3 text-xs text-gray-500">
        Create multiple {label.toLowerCase()} using a naming pattern. Use <code className="rounded bg-gray-100 px-1">{"{i}"}</code> for the counter.
      </p>

      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-3">
          <label className="mb-1 block text-xs font-medium text-gray-500">Name Pattern</label>
          <input
            type="text"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="e.g. GigabitEthernet0/0/{i} or Ethernet{i}/1"
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-500">From</label>
          <input
            type="number"
            value={rangeStart}
            onChange={(e) => setRangeStart(parseInt(e.target.value) || 0)}
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-500">To</label>
          <input
            type="number"
            value={rangeEnd}
            onChange={(e) => setRangeEnd(parseInt(e.target.value) || 0)}
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-500">Count</label>
          <div className="px-3 py-1.5 text-sm text-gray-700">{Math.max(0, rangeEnd - rangeStart + 1)} items</div>
        </div>
      </div>

      {/* Default values for common fields */}
      {defaultableAttrs.length > 0 && (
        <div className="mt-3">
          <label className="mb-1 block text-xs font-medium text-gray-500">Default Values</label>
          <div className="grid grid-cols-2 gap-2">
            {defaultableAttrs.map(([name, attr]) => (
              <FieldInput key={name} name={name} attr={attr} value={defaults[name]} onChange={(v) => setDefaults((d) => ({ ...d, [name]: v }))} />
            ))}
          </div>
        </div>
      )}

      {/* Preview */}
      {pattern && preview.length > 0 && (
        <div className="mt-3">
          <label className="mb-1 block text-xs font-medium text-gray-500">Preview</label>
          <div className="max-h-24 overflow-y-auto rounded bg-gray-50 px-3 py-2 font-mono text-xs text-gray-600">
            {preview.slice(0, 8).map((name) => (
              <div key={name}>{name}</div>
            ))}
            {preview.length > 8 && <div className="text-gray-400">... and {preview.length - 8} more</div>}
          </div>
        </div>
      )}

      {result && (
        <div className={`mt-3 rounded px-3 py-2 text-xs ${result.errors > 0 ? "bg-yellow-50 text-yellow-700" : "bg-green-50 text-green-700"}`}>
          Created {result.created} {label.toLowerCase()}{result.errors > 0 ? `, ${result.errors} failed` : ""}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          onClick={handleBulkCreate}
          disabled={creating || !pattern || rangeEnd < rangeStart}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {creating ? "Creating..." : `Create ${Math.max(0, rangeEnd - rangeStart + 1)} ${label}`}
        </button>
        <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
      </div>
    </div>
  );
}

// --- Shared field input ---

function FieldInput({
  name,
  attr,
  value,
  onChange,
}: {
  name: string;
  attr: AttributeDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = attr.display_name || name;

  if (attr.type === "enum" && attr.enum_values) {
    return (
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">{label}</label>
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value || undefined)}
          className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        >
          <option value="">—</option>
          {attr.enum_values.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>
    );
  }

  if (attr.type === "boolean") {
    return (
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">{label}</label>
        <select
          value={value === true ? "true" : value === false ? "false" : ""}
          onChange={(e) => onChange(e.target.value === "true" ? true : e.target.value === "false" ? false : undefined)}
          className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        >
          <option value="">—</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
    );
  }

  if (attr.type === "integer" || attr.type === "float") {
    return (
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">{label}</label>
        <input
          type="number"
          value={value != null ? String(value) : ""}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v ? (attr.type === "integer" ? parseInt(v) : parseFloat(v)) : undefined);
          }}
          className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        />
      </div>
    );
  }

  if (attr.type === "text") {
    return (
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-500">{label}</label>
        <textarea
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value || undefined)}
          rows={2}
          className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
        />
      </div>
    );
  }

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-gray-500">{label}{attr.required && <span className="text-red-500"> *</span>}</label>
      <input
        type="text"
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
      />
    </div>
  );
}
