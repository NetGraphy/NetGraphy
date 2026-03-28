/**
 * DynamicDetailPage — auto-generated detail view for any node instance.
 *
 * Provides three tabs:
 * - Overview: all attributes in sections
 * - Relationships: connected nodes grouped by edge type
 * - History: audit trail for this node
 */

import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { nodesApi, api } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";

type TabId = "overview" | "relationships" | "history";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "relationships", label: "Relationships" },
  { id: "history", label: "History" },
];

export function DynamicDetailPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id: string }>();
  const { getNodeType, getEdgesForNodeType } = useSchemaStore();
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const typeDef = nodeType ? getNodeType(nodeType) : undefined;
  const edgeTypes = nodeType ? getEdgesForNodeType(nodeType) : [];

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
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Edit
          </Link>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <nav className="-mb-px flex gap-6">
          {TABS.map((tab) => (
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
              <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">
                {attr.description || name}
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
                <dt className="text-xs text-gray-400">{name}</dt>
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

  // Determine direction label
  const isSource = edgeType.source.node_types.includes(nodeType);
  const isTarget = edgeType.target.node_types.includes(nodeType);
  let directionLabel = "";
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
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-300">
          {isLoading ? "..." : relationships.length}
        </span>
      </div>

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
                id: string;
                target_type?: string;
                source_type?: string;
                target_id?: string;
                source_id?: string;
                label?: string;
                properties?: Record<string, unknown>;
              },
              idx: number,
            ) => {
              // Determine the "other" node
              const otherType =
                rel.target_type !== nodeType
                  ? rel.target_type
                  : rel.source_type;
              const otherId =
                rel.target_id !== nodeId ? rel.target_id : rel.source_id;

              return (
                <li key={rel.id || idx} className="px-4 py-2">
                  <Link
                    to={`/objects/${otherType}/${otherId}`}
                    className="text-sm text-brand-600 hover:text-brand-700"
                  >
                    {rel.label || `${otherType}/${otherId}`}
                  </Link>
                  {rel.properties &&
                    Object.keys(rel.properties).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-2">
                        {Object.entries(rel.properties).map(([k, v]) => (
                          <span
                            key={k}
                            className="text-xs text-gray-400"
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
