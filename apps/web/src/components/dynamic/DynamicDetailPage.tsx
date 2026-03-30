/**
 * DynamicDetailPage — auto-generated detail view for any node instance.
 *
 * Provides three tabs:
 * - Overview: all attributes in sections
 * - Relationships: connected nodes grouped by edge type
 * - History: audit trail for this node
 */

import { useState, useMemo } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { nodesApi, api } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";
import { AddRelatedPanel } from "./AddRelatedPanel";
import type { DetailTabDefinition } from "@/types/schema";

export function DynamicDetailPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id: string }>();
  const { getNodeType, getEdgesForNodeType } = useSchemaStore();
  const [activeTab, setActiveTab] = useState("overview");

  const navigate = useNavigate();
  const typeDef = nodeType ? getNodeType(nodeType) : undefined;
  const edgeTypes = nodeType ? getEdgesForNodeType(nodeType) : [];

  const deleteMutation = useMutation({
    mutationFn: () => nodesApi.delete(nodeType!, id!),
    onSuccess: () => navigate(`/objects/${nodeType}`),
  });

  // Build dynamic tabs: overview + schema-defined custom tabs + relationships + history
  const detailTabs = typeDef?.detail_tabs || [];
  const tabs = useMemo(() => {
    const t: { id: string; label: string }[] = [{ id: "overview", label: "Overview" }];
    for (const dt of detailTabs) {
      t.push({ id: `custom:${dt.edge_type}`, label: dt.label });
    }
    t.push({ id: "relationships", label: "Relationships" });
    t.push({ id: "history", label: "History" });
    return t;
  }, [detailTabs]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["node", nodeType, id],
    queryFn: () => nodesApi.get(nodeType!, id!),
    enabled: !!nodeType && !!id,
  });

  if (!typeDef) {
    return <div className="text-red-500">Unknown node type: {nodeType}</div>;
  }

  const node = data?.data?.data;
  const displayName = typeDef.metadata.display_name || nodeType;

  // Group attributes by visibility
  const mainAttributes = Object.entries(typeDef.attributes).filter(
    ([, attr]) => !attr.auto_set && attr.ui.form_visible !== false,
  );
  const autoAttributes = Object.entries(typeDef.attributes).filter(
    ([, attr]) => attr.auto_set,
  );

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Link
              to={`/objects/${nodeType}`}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              {displayName}s
            </Link>
            <span className="text-gray-400">/</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {isLoading
              ? "Loading..."
              : node?.[typeDef.graph.default_label_field || "id"] || id}
          </h1>
        </div>
        <div className="flex gap-2">
          <Link
            to={`/objects/${nodeType}/${id}/edit`}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Edit
          </Link>
          <button
            onClick={() => {
              if (confirm(`Delete this ${displayName}? This action cannot be undone.`)) {
                deleteMutation.mutate();
              }
            }}
            disabled={deleteMutation.isPending}
            className="rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/20"
          >
            {deleteMutation.isPending ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <nav className="-mb-px flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`border-b-2 pb-3 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-brand-600 text-brand-600"
                  : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {error ? (
        <div className="text-red-500">Error loading node</div>
      ) : isLoading ? (
        <div className="text-gray-500">Loading...</div>
      ) : (
        <>
          {activeTab === "overview" && (
            <OverviewTab
              node={node}
              mainAttributes={mainAttributes}
              autoAttributes={autoAttributes}
            />
          )}
          {activeTab.startsWith("custom:") && (() => {
            const edgeType = activeTab.replace("custom:", "");
            const tabDef = detailTabs.find((dt) => dt.edge_type === edgeType);
            if (!tabDef) return null;
            return (
              <CustomRelatedTab
                nodeType={nodeType!}
                nodeId={id!}
                tabDef={tabDef}
              />
            );
          })()}
          {activeTab === "relationships" && (
            <RelationshipsTab
              nodeType={nodeType!}
              nodeId={id!}
              edgeTypes={edgeTypes}
            />
          )}
          {activeTab === "history" && (
            <HistoryTab nodeType={nodeType!} nodeId={id!} />
          )}
        </>
      )}
    </div>
  );
}

// --- Overview Tab ---

function OverviewTab({
  node,
  mainAttributes,
  autoAttributes,
}: {
  node: Record<string, unknown>;
  mainAttributes: [string, import("@/types/schema").AttributeDefinition][];
  autoAttributes: [string, import("@/types/schema").AttributeDefinition][];
}) {
  return (
    <div className="grid grid-cols-3 gap-6">
      {/* Main attributes */}
      <div className="col-span-2 rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <h2 className="mb-4 text-lg font-semibold">Attributes</h2>
        <dl className="grid grid-cols-2 gap-4">
          {mainAttributes.map(([name, attr]) => (
            <div key={name}>
              <dt title={attr.description || undefined} className="text-sm font-medium text-gray-500 dark:text-gray-400">
                {attr.display_name || name}
              </dt>
              <dd className="mt-1 text-sm">
                <FieldRenderer
                  value={node?.[name]}
                  attribute={attr}
                  mode="display"
                />
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Metadata sidebar */}
      <div className="space-y-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-3 text-sm font-semibold text-gray-500">
            Metadata
          </h3>
          <dl className="space-y-2">
            {autoAttributes.map(([name, attr]) => (
              <div key={name}>
                <dt className="text-xs text-gray-400">{attr.display_name || name}</dt>
                <dd className="text-sm">
                  <FieldRenderer
                    value={node?.[name]}
                    attribute={attr}
                    mode="display"
                  />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}

// --- Relationships Tab ---

function RelationshipsTab({
  nodeType,
  nodeId,
  edgeTypes,
}: {
  nodeType: string;
  nodeId: string;
  edgeTypes: import("@/types/schema").EdgeTypeDefinition[];
}) {
  if (edgeTypes.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800">
        No relationship types defined for this node type.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {edgeTypes.map((et) => (
        <RelationshipPanel
          key={et.metadata.name}
          nodeType={nodeType}
          nodeId={nodeId}
          edgeType={et}
        />
      ))}
    </div>
  );
}

function RelationshipPanel({
  nodeType,
  nodeId,
  edgeType,
}: {
  nodeType: string;
  nodeId: string;
  edgeType: import("@/types/schema").EdgeTypeDefinition;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["relationships", nodeType, nodeId, edgeType.metadata.name],
    queryFn: () => nodesApi.relationships(nodeType, nodeId, edgeType.metadata.name),
  });

  const relationships = data?.data?.data || [];
  const edgeName = edgeType.metadata.display_name || edgeType.metadata.name;
  const [showAdd, setShowAdd] = useState(false);

  // Determine direction label and target type for linking
  const isSource = edgeType.source.node_types.includes(nodeType);
  const isTarget = edgeType.target.node_types.includes(nodeType);
  let directionLabel = "";
  const targetTypes = isSource ? edgeType.target.node_types : edgeType.source.node_types;
  if (isSource && !isTarget) {
    directionLabel = `\u2192 ${edgeType.target.node_types.join(", ")}`;
  } else if (isTarget && !isSource) {
    directionLabel = `\u2190 ${edgeType.source.node_types.join(", ")}`;
  } else {
    directionLabel = `\u2194 ${edgeType.source.node_types.join(", ")} / ${edgeType.target.node_types.join(", ")}`;
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
            {edgeName}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {directionLabel}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="rounded bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-600 hover:bg-brand-100"
          >
            + Add
          </button>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-300">
            {isLoading ? "..." : relationships.length}
          </span>
        </div>
      </div>

      {showAdd && targetTypes.length > 0 && (
        <div className="border-b border-gray-200 p-3">
          <AddRelatedPanel
            sourceNodeType={nodeType}
            sourceNodeId={nodeId}
            edgeType={edgeType.metadata.name}
            targetType={targetTypes[0]}
            label={edgeName}
            onClose={() => setShowAdd(false)}
          />
        </div>
      )}

      {isLoading ? (
        <div className="px-4 py-4 text-sm text-gray-500">Loading...</div>
      ) : relationships.length === 0 ? (
        <div className="px-4 py-4 text-sm text-gray-400">
          No relationships of this type.
        </div>
      ) : (
        <ul className="divide-y divide-gray-100 dark:divide-gray-700">
          {relationships.map(
            (
              rel: {
                edge_type: string;
                edge_properties?: Record<string, unknown>;
                related_type?: string;
                related_id?: string;
                direction?: string;
                label?: string;
              },
              idx: number,
            ) => {
              // Filter out system/internal fields from edge properties
              const HIDDEN = new Set([
                "id", "_source", "_created_by", "_created_at", "_updated_by",
                "_updated_at", "created_by", "created_at", "updated_by",
                "updated_at", "source_type", "confidence_score",
              ]);
              const visibleProps = rel.edge_properties
                ? Object.entries(rel.edge_properties).filter(
                    ([k]) => !HIDDEN.has(k) && !k.startsWith("_"),
                  )
                : [];

              return (
                <li key={rel.related_id || idx} className="px-4 py-2">
                  <Link
                    to={`/objects/${rel.related_type}/${rel.related_id}`}
                    className="text-sm font-medium text-brand-600 hover:text-brand-700"
                  >
                    {rel.label || rel.related_id}
                  </Link>
                  {rel.related_type && (
                    <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                      {rel.related_type}
                    </span>
                  )}
                  {visibleProps.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-2">
                      {visibleProps.map(([k, v]) => (
                        <span
                          key={k}
                          className="rounded bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500"
                        >
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              );
            },
          )}
        </ul>
      )}
    </div>
  );
}

// --- Custom Related Tab (schema-driven table view) ---

function CustomRelatedTab({
  nodeType,
  nodeId,
  tabDef,
}: {
  nodeType: string;
  nodeId: string;
  tabDef: DetailTabDefinition;
}) {
  const { getNodeType } = useSchemaStore();
  const targetSchema = getNodeType(tabDef.target_type);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [showAdd, setShowAdd] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["relationships", nodeType, nodeId, tabDef.edge_type],
    queryFn: () => nodesApi.relationships(nodeType, nodeId, tabDef.edge_type),
  });

  const allRows: Record<string, unknown>[] = (data?.data?.data || []).map(
    (rel: { related_node?: Record<string, unknown>; related_id?: string; related_type?: string }) => ({
      ...rel.related_node,
      _related_id: rel.related_id,
      _related_type: rel.related_type,
    }),
  );

  // Apply filters
  const rows = allRows.filter((row) =>
    Object.entries(filters).every(([k, v]) => {
      if (!v) return true;
      return String(row[k] ?? "").toLowerCase().includes(v.toLowerCase());
    }),
  );

  // Resolve column display names from target schema
  const columns = tabDef.columns.length > 0
    ? tabDef.columns
    : Object.keys(targetSchema?.attributes || {}).slice(0, 6);

  return (
    <div>
      {/* Add button + panel */}
      <div className="mb-4 flex items-center justify-between">
        <div />
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
        >
          + Add {tabDef.label}
        </button>
      </div>
      {showAdd && (
        <div className="mb-4">
          <AddRelatedPanel
            sourceNodeType={nodeType}
            sourceNodeId={nodeId}
            edgeType={tabDef.edge_type}
            targetType={tabDef.target_type}
            label={tabDef.label}
            onClose={() => setShowAdd(false)}
          />
        </div>
      )}

      {/* Filters */}
      {tabDef.filters.length > 0 && (
        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3">
          {tabDef.filters.map((filterKey) => {
            const attrDef = targetSchema?.attributes[filterKey];
            const label = attrDef?.display_name || filterKey;
            const enumValues = attrDef?.enum_values;
            return (
              <div key={filterKey} className="flex flex-col">
                <label className="mb-1 text-xs font-medium text-gray-500">{label}</label>
                {enumValues ? (
                  <select
                    value={filters[filterKey] || ""}
                    onChange={(e) => setFilters((f) => ({ ...f, [filterKey]: e.target.value }))}
                    className="rounded-md border border-gray-300 px-2 py-1 text-sm"
                  >
                    <option value="">All</option>
                    {enumValues.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={filters[filterKey] || ""}
                    onChange={(e) => setFilters((f) => ({ ...f, [filterKey]: e.target.value }))}
                    placeholder="Filter..."
                    className="rounded-md border border-gray-300 px-2 py-1 text-sm"
                  />
                )}
              </div>
            );
          })}
          {Object.values(filters).some(Boolean) && (
            <button
              onClick={() => setFilters({})}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((col) => {
                const attrDef = targetSchema?.attributes[col];
                return (
                  <th
                    key={col}
                    title={attrDef?.description || undefined}
                    className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
                  >
                    {attrDef?.display_name || col}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {isLoading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-4 text-sm text-gray-500">
                  Loading...
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-4 text-center text-sm text-gray-400">
                  No {tabDef.label.toLowerCase()} found.
                </td>
              </tr>
            ) : (
              rows.map((row, idx) => (
                <tr key={(row._related_id as string) || idx} className="hover:bg-gray-50">
                  {columns.map((col, ci) => {
                    const attrDef = targetSchema?.attributes[col];
                    const value = row[col];
                    return (
                      <td key={col} className="px-4 py-2 text-sm">
                        {ci === 0 ? (
                          <Link
                            to={`/objects/${row._related_type || tabDef.target_type}/${row._related_id}`}
                            className="font-medium text-brand-600 hover:text-brand-700"
                          >
                            {attrDef ? (
                              <FieldRenderer value={value} attribute={attrDef} mode="display" />
                            ) : (
                              String(value ?? "—")
                            )}
                          </Link>
                        ) : attrDef ? (
                          <FieldRenderer value={value} attribute={attrDef} mode="display" />
                        ) : (
                          String(value ?? "—")
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
        <div className="border-t border-gray-200 px-4 py-2 text-xs text-gray-500">
          {rows.length} {tabDef.label.toLowerCase()}{allRows.length !== rows.length ? ` (${allRows.length} total, ${allRows.length - rows.length} filtered)` : ""}
        </div>
      </div>
    </div>
  );
}

// --- History Tab ---

function HistoryTab({
  nodeType,
  nodeId,
}: {
  nodeType: string;
  nodeId: string;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["audit", nodeType, nodeId],
    queryFn: () =>
      api.get("/audit/events", {
        params: { resource_type: nodeType, resource_id: nodeId },
      }),
  });

  const events =
    data?.data?.data?.data || data?.data?.data || [];

  if (isLoading) {
    return <div className="text-sm text-gray-500">Loading history...</div>;
  }

  if (error) {
    return <div className="text-sm text-red-500">Error loading history</div>;
  }

  if (events.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800">
        No history events found for this node.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-900">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Timestamp
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Actor
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Action
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Details
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {events.map(
            (
              event: {
                id: string;
                timestamp: string;
                actor: string;
                action: string;
                details: Record<string, unknown> | null;
              },
              idx: number,
            ) => (
              <tr
                key={event.id || idx}
                className="hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                  {new Date(event.timestamp).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                  {event.actor}
                </td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      event.action === "create"
                        ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                        : event.action === "update"
                          ? "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                          : event.action === "delete"
                            ? "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                            : "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200"
                    }`}
                  >
                    {event.action}
                  </span>
                </td>
                <td className="max-w-xs truncate px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                  {event.details
                    ? JSON.stringify(event.details)
                    : "\u2014"}
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
