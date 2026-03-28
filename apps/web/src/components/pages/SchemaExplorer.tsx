/**
 * SchemaExplorer — browse all node types, edge types, and their definitions.
 */

import { useSchemaStore } from "@/stores/schemaStore";
import { Link } from "react-router-dom";

export function SchemaExplorer() {
  const { nodeTypes, edgeTypes, categories } = useSchemaStore();

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        Schema Explorer
      </h1>

      {/* Node types */}
      <section className="mb-8">
        <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
          Node Types ({Object.keys(nodeTypes).length})
        </h2>
        <div className="grid grid-cols-3 gap-4">
          {Object.values(nodeTypes).map((nt) => (
            <div
              key={nt.metadata.name}
              className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
            >
              <div className="flex items-center gap-2">
                <div
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: nt.metadata.color || "#94A3B8" }}
                />
                <h3 className="font-medium text-gray-900 dark:text-white">
                  {nt.metadata.display_name || nt.metadata.name}
                </h3>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                {nt.metadata.description}
              </p>
              <div className="mt-2 flex gap-2">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-700">
                  {Object.keys(nt.attributes).length} attributes
                </span>
                <span className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-700">
                  {nt.metadata.category}
                </span>
              </div>
              <Link
                to={`/objects/${nt.metadata.name}`}
                className="mt-3 block text-sm text-brand-600 hover:text-brand-700"
              >
                Browse instances &rarr;
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Edge types */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
          Edge Types ({Object.keys(edgeTypes).length})
        </h2>
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Edge Type
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Source
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Target
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-gray-500">
                  Cardinality
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {Object.values(edgeTypes).map((et) => (
                <tr key={et.metadata.name}>
                  <td className="px-4 py-3 text-sm font-medium">
                    {et.metadata.display_name || et.metadata.name}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {et.source.node_types.join(", ")}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {et.target.node_types.join(", ")}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-700">
                      {et.cardinality.replace(/_/g, ":")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
