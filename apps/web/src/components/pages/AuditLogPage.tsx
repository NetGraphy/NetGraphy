/**
 * AuditLogPage — searchable, filterable audit event viewer.
 * Fetches from /audit/events with pagination and filtering.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Pagination } from "@/components/common/Pagination";

interface AuditEvent {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string;
  details: Record<string, unknown> | null;
}

interface AuditResponse {
  data: AuditEvent[];
  total: number;
}

const ACTION_TYPES = ["create", "update", "delete", "login", "logout", "query"];
const RESOURCE_TYPES = [
  "Device",
  "Interface",
  "IPAddress",
  "Circuit",
  "Site",
  "Rack",
  "VLAN",
  "Prefix",
  "User",
];

export function AuditLogPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [actionFilter, setActionFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");

  const params: Record<string, unknown> = {
    page,
    page_size: pageSize,
  };
  if (actionFilter) params.action = actionFilter;
  if (resourceTypeFilter) params.resource_type = resourceTypeFilter;

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit-events", page, pageSize, actionFilter, resourceTypeFilter],
    queryFn: () =>
      api.get<{ data: AuditResponse }>("/audit/events", { params }),
  });

  const events = data?.data?.data?.data || [];
  const totalCount = data?.data?.data?.total || 0;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        Audit Log
      </h1>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Action
          </label>
          <select
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(1);
            }}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          >
            <option value="">All actions</option>
            {ACTION_TYPES.map((action) => (
              <option key={action} value={action}>
                {action}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Resource Type
          </label>
          <select
            value={resourceTypeFilter}
            onChange={(e) => {
              setResourceTypeFilter(e.target.value);
              setPage(1);
            }}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          >
            <option value="">All types</option>
            {RESOURCE_TYPES.map((rt) => (
              <option key={rt} value={rt}>
                {rt}
              </option>
            ))}
          </select>
        </div>

        {(actionFilter || resourceTypeFilter) && (
          <button
            onClick={() => {
              setActionFilter("");
              setResourceTypeFilter("");
              setPage(1);
            }}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="text-gray-500">Loading audit events...</div>
      ) : error ? (
        <div className="text-red-500">Error loading audit events</div>
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
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
                    Resource Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Resource ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {events.map((event: AuditEvent) => (
                  <tr
                    key={event.id}
                    className="hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {new Date(event.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                      {event.actor}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <ActionBadge action={event.action} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                      {event.resource_type}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs dark:bg-gray-700">
                        {event.resource_id}
                      </code>
                    </td>
                    <td className="max-w-xs truncate px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {event.details
                        ? JSON.stringify(event.details)
                        : "\u2014"}
                    </td>
                  </tr>
                ))}
                {events.length === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-sm text-gray-500"
                    >
                      No audit events found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

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

function ActionBadge({ action }: { action: string }) {
  const colorMap: Record<string, string> = {
    create:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    update:
      "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    delete: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    login:
      "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
    logout:
      "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
    query:
      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  };

  const classes =
    colorMap[action] ||
    "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200";

  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {action}
    </span>
  );
}
