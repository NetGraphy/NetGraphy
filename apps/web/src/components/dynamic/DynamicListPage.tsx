/**
 * DynamicListPage — auto-generated list/table page for any node type.
 *
 * Reads the node type from the URL params, looks up its schema definition,
 * and renders a filterable, sortable data table with columns derived from
 * the schema's `list_column` UI metadata.
 */

import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { nodesApi } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";
import { FilterBar } from "@/components/common/FilterBar";
import { Pagination } from "@/components/common/Pagination";

export function DynamicListPage() {
  const { nodeType } = useParams<{ nodeType: string }>();
  const { getNodeType, getListColumns } = useSchemaStore();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const typeDef = nodeType ? getNodeType(nodeType) : undefined;
  const columns = nodeType ? getListColumns(nodeType) : [];

  const queryParams: Record<string, unknown> = {
    page,
    page_size: pageSize,
    ...filters,
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ["nodes", nodeType, page, pageSize, filters],
    queryFn: () => nodesApi.list(nodeType!, queryParams),
    enabled: !!nodeType,
  });

  if (!typeDef) {
    return <div className="text-red-500">Unknown node type: {nodeType}</div>;
  }

  const displayName = typeDef.metadata.display_name || nodeType;
  const items = data?.data?.data || [];
  const totalCount = data?.data?.total ?? items.length;

  const handleFilterChange = (newFilters: Record<string, string>) => {
    setFilters(newFilters);
    setPage(1); // Reset to first page on filter change
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {displayName}s
          </h1>
          <p className="text-sm text-gray-500">{typeDef.metadata.description}</p>
        </div>
        <Link
          to={`/objects/${nodeType}/new`}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Create {displayName}
        </Link>
      </div>

      {/* Filter bar */}
      {nodeType && (
        <FilterBar
          nodeType={nodeType}
          filters={filters}
          onFilterChange={handleFilterChange}
        />
      )}

      {/* Table */}
      {isLoading ? (
        <div className="text-gray-500">Loading...</div>
      ) : error ? (
        <div className="text-red-500">Error loading data</div>
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  {columns.map(({ name, attr }) => (
                    <th
                      key={name}
                      title={attr.description || undefined}
                      className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400"
                    >
                      {attr.display_name || name}
                    </th>
                  ))}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {items.map((item: Record<string, unknown>) => (
                  <tr
                    key={item.id as string}
                    className="hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    {columns.map(({ name, attr }, colIdx) => (
                      <td key={name} className="px-4 py-3 text-sm">
                        {colIdx === 0 ? (
                          <Link
                            to={`/objects/${nodeType}/${item.id}`}
                            className="font-medium text-brand-600 hover:text-brand-700"
                          >
                            <FieldRenderer
                              value={item[name]}
                              attribute={attr}
                              mode="display"
                            />
                          </Link>
                        ) : (
                          <FieldRenderer
                            value={item[name]}
                            attribute={attr}
                            mode="display"
                          />
                        )}
                      </td>
                    ))}
                    <td className="px-4 py-3" />
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td
                      colSpan={columns.length + 1}
                      className="px-4 py-8 text-center text-sm text-gray-500"
                    >
                      No {displayName?.toLowerCase()}s found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <Pagination
            page={page}
            pageSize={pageSize}
            totalCount={totalCount}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </>
      )}
    </div>
  );
}
