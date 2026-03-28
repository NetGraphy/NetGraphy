/**
 * DynamicDetailPage — auto-generated detail view for any node instance.
 *
 * Shows all attributes in sections, relationship panels for connected
 * edge types, and a mini graph view centered on this node.
 */

import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { nodesApi } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";

export function DynamicDetailPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id: string }>();
  const { getNodeType, getEdgesForNodeType } = useSchemaStore();

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

      {error ? (
        <div className="text-red-500">Error loading node</div>
      ) : isLoading ? (
        <div className="text-gray-500">Loading...</div>
      ) : (
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

            {/* Relationship panels */}
            {edgeTypes.map((et) => (
              <div
                key={et.metadata.name}
                className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
              >
                <h3 className="mb-2 text-sm font-semibold text-gray-500">
                  {et.metadata.display_name || et.metadata.name}
                </h3>
                {/* TODO: Load and display relationships */}
                <p className="text-xs text-gray-400">
                  {et.source.node_types.join(", ")} &rarr;{" "}
                  {et.target.node_types.join(", ")}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TODO: Tabs for Overview, Relationships, Graph Mini-View, History */}
    </div>
  );
}
