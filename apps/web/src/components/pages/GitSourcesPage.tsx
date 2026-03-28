/**
 * GitSourcesPage — manage Git repositories used as data sources.
 * Supports registering, syncing, and previewing changes from Git sources.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface ContentMapping {
  domain: string;
  path: string;
}

interface GitSource {
  id: string;
  name: string;
  url: string;
  branch: string;
  auth_type: string;
  last_sync_at?: string;
  last_sync_status?: string;
  content_mappings?: ContentMapping[];
}

interface SyncResult {
  status: string;
  additions: number;
  modifications: number;
  deletions: number;
  errors: string[];
}

interface PreviewResult {
  additions: { path: string; domain: string }[];
  modifications: { path: string; domain: string }[];
  deletions: { path: string; domain: string }[];
  errors: string[];
}

interface SyncHistoryEntry {
  id: string;
  started_at: string;
  finished_at?: string;
  status: string;
  additions: number;
  modifications: number;
  deletions: number;
  errors: string[];
}

export function GitSourcesPage() {
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [previewSourceId, setPreviewSourceId] = useState<string | null>(null);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(
    null,
  );
  const [syncResultMap, setSyncResultMap] = useState<
    Record<string, SyncResult>
  >({});

  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["git-sources"],
    queryFn: () => api.get<{ data: GitSource[] }>("/git-sources"),
  });

  const sources = data?.data?.data || [];

  const syncMutation = useMutation({
    mutationFn: (sourceId: string) =>
      api.post<{ data: SyncResult }>(`/git-sources/${sourceId}/sync`),
    onSuccess: (response, sourceId) => {
      const result = response.data?.data;
      if (result) {
        setSyncResultMap((prev) => ({ ...prev, [sourceId]: result }));
      }
      queryClient.invalidateQueries({ queryKey: ["git-sources"] });
    },
  });

  const { data: previewData, isLoading: previewLoading } = useQuery({
    queryKey: ["git-source-preview", previewSourceId],
    queryFn: () =>
      api.get<{ data: PreviewResult }>(
        `/git-sources/${previewSourceId}/preview`,
      ),
    enabled: !!previewSourceId,
  });

  const preview = previewData?.data?.data;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Git Sources
        </h1>
        <button
          onClick={() => setShowRegisterForm(!showRegisterForm)}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Register Source
        </button>
      </div>

      {/* Register Form */}
      {showRegisterForm && (
        <RegisterSourceForm
          onClose={() => setShowRegisterForm(false)}
          onSuccess={() => {
            setShowRegisterForm(false);
            queryClient.invalidateQueries({ queryKey: ["git-sources"] });
          }}
        />
      )}

      {/* Preview Panel */}
      {previewSourceId && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Preview Changes
            </h2>
            <button
              onClick={() => setPreviewSourceId(null)}
              className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              Close
            </button>
          </div>
          {previewLoading ? (
            <div className="text-sm text-gray-500">Loading preview...</div>
          ) : preview ? (
            <div className="space-y-3">
              {preview.additions.length > 0 && (
                <div>
                  <h3 className="mb-1 text-xs font-medium text-green-700 dark:text-green-400">
                    Additions ({preview.additions.length})
                  </h3>
                  <ul className="space-y-0.5">
                    {preview.additions.map((item, i) => (
                      <li
                        key={i}
                        className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"
                      >
                        <span className="text-green-600">+</span>
                        <code className="rounded bg-gray-100 px-1 text-xs dark:bg-gray-700">
                          {item.domain}
                        </code>
                        {item.path}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.modifications.length > 0 && (
                <div>
                  <h3 className="mb-1 text-xs font-medium text-blue-700 dark:text-blue-400">
                    Modifications ({preview.modifications.length})
                  </h3>
                  <ul className="space-y-0.5">
                    {preview.modifications.map((item, i) => (
                      <li
                        key={i}
                        className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"
                      >
                        <span className="text-blue-600">~</span>
                        <code className="rounded bg-gray-100 px-1 text-xs dark:bg-gray-700">
                          {item.domain}
                        </code>
                        {item.path}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.deletions.length > 0 && (
                <div>
                  <h3 className="mb-1 text-xs font-medium text-red-700 dark:text-red-400">
                    Deletions ({preview.deletions.length})
                  </h3>
                  <ul className="space-y-0.5">
                    {preview.deletions.map((item, i) => (
                      <li
                        key={i}
                        className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"
                      >
                        <span className="text-red-600">-</span>
                        <code className="rounded bg-gray-100 px-1 text-xs dark:bg-gray-700">
                          {item.domain}
                        </code>
                        {item.path}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.errors.length > 0 && (
                <div>
                  <h3 className="mb-1 text-xs font-medium text-red-700 dark:text-red-400">
                    Errors ({preview.errors.length})
                  </h3>
                  <ul className="space-y-0.5">
                    {preview.errors.map((err, i) => (
                      <li
                        key={i}
                        className="text-sm text-red-500"
                      >
                        {err}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.additions.length === 0 &&
                preview.modifications.length === 0 &&
                preview.deletions.length === 0 &&
                preview.errors.length === 0 && (
                  <p className="text-sm text-gray-500">
                    No changes detected.
                  </p>
                )}
            </div>
          ) : (
            <div className="text-sm text-gray-500">No preview data.</div>
          )}
        </div>
      )}

      {/* Sources Table */}
      {isLoading ? (
        <div className="text-gray-500">Loading Git sources...</div>
      ) : error ? (
        <div className="text-red-500">Error loading Git sources</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  URL
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Branch
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Last Sync
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {sources.map((source: GitSource) => (
                <>
                  <tr
                    key={source.id}
                    className="hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                      {source.name}
                    </td>
                    <td className="max-w-xs truncate px-4 py-3 text-sm">
                      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs dark:bg-gray-700">
                        {source.url}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                      {source.branch}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {source.last_sync_at
                        ? new Date(source.last_sync_at).toLocaleString()
                        : "\u2014"}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {source.last_sync_status ? (
                        <SyncStatusBadge status={source.last_sync_status} />
                      ) : (
                        <span className="text-gray-400">\u2014</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex gap-2">
                        <button
                          onClick={() => syncMutation.mutate(source.id)}
                          disabled={syncMutation.isPending}
                          className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
                        >
                          Sync Now
                        </button>
                        <button
                          onClick={() => setPreviewSourceId(source.id)}
                          className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
                        >
                          Preview
                        </button>
                        <button
                          onClick={() =>
                            setExpandedHistoryId(
                              expandedHistoryId === source.id
                                ? null
                                : source.id,
                            )
                          }
                          className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
                        >
                          History
                        </button>
                      </div>
                    </td>
                  </tr>

                  {/* Sync result inline */}
                  {syncResultMap[source.id] && (
                    <tr key={`${source.id}-sync-result`}>
                      <td
                        colSpan={6}
                        className="border-t-0 bg-green-50 px-4 py-2 dark:bg-green-900/20"
                      >
                        <div className="flex items-center gap-3 text-xs">
                          <span className="font-medium text-green-700 dark:text-green-400">
                            Sync complete:
                          </span>
                          <span className="text-green-600">
                            +{syncResultMap[source.id].additions} added
                          </span>
                          <span className="text-blue-600">
                            ~{syncResultMap[source.id].modifications} modified
                          </span>
                          <span className="text-red-600">
                            -{syncResultMap[source.id].deletions} deleted
                          </span>
                          {syncResultMap[source.id].errors.length > 0 && (
                            <span className="text-red-600">
                              {syncResultMap[source.id].errors.length} errors
                            </span>
                          )}
                          <button
                            onClick={() =>
                              setSyncResultMap((prev) => {
                                const next = { ...prev };
                                delete next[source.id];
                                return next;
                              })
                            }
                            className="ml-auto text-gray-400 hover:text-gray-600"
                          >
                            Dismiss
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}

                  {/* Sync history expandable */}
                  {expandedHistoryId === source.id && (
                    <tr key={`${source.id}-history`}>
                      <td colSpan={6} className="bg-gray-50 px-4 py-3 dark:bg-gray-900">
                        <SyncHistory sourceId={source.id} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
              {sources.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-gray-500"
                  >
                    No Git sources registered.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SyncStatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    success:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    synced:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    running:
      "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    pending:
      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    error: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  };

  const classes =
    colorMap[status.toLowerCase()] ||
    "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200";

  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {status}
    </span>
  );
}

function SyncHistory({ sourceId }: { sourceId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["git-source-history", sourceId],
    queryFn: () =>
      api.get<{ data: SyncHistoryEntry[] }>(
        `/git-sources/${sourceId}/history`,
      ),
  });

  const entries = data?.data?.data || [];

  if (isLoading) {
    return <div className="text-sm text-gray-500">Loading history...</div>;
  }

  if (entries.length === 0) {
    return <div className="text-sm text-gray-500">No sync history.</div>;
  }

  return (
    <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
      <thead>
        <tr>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Time
          </th>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Status
          </th>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Added
          </th>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Modified
          </th>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Deleted
          </th>
          <th className="px-3 py-1.5 text-left text-xs font-medium uppercase text-gray-500">
            Errors
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
        {entries.map((entry: SyncHistoryEntry) => (
          <tr key={entry.id}>
            <td className="px-3 py-1.5 text-xs text-gray-500 dark:text-gray-400">
              {new Date(entry.started_at).toLocaleString()}
            </td>
            <td className="px-3 py-1.5 text-xs">
              <SyncStatusBadge status={entry.status} />
            </td>
            <td className="px-3 py-1.5 text-xs text-green-600">
              +{entry.additions}
            </td>
            <td className="px-3 py-1.5 text-xs text-blue-600">
              ~{entry.modifications}
            </td>
            <td className="px-3 py-1.5 text-xs text-red-600">
              -{entry.deletions}
            </td>
            <td className="px-3 py-1.5 text-xs text-gray-500">
              {entry.errors.length || "\u2014"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RegisterSourceForm({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [authType, setAuthType] = useState("none");
  const [mappings, setMappings] = useState<ContentMapping[]>([
    { domain: "", path: "" },
  ]);

  const registerMutation = useMutation({
    mutationFn: (data: {
      name: string;
      url: string;
      branch: string;
      auth_type: string;
      content_mappings: ContentMapping[];
    }) => api.post("/git-sources", data),
    onSuccess,
  });

  const addMapping = () => {
    setMappings((prev) => [...prev, { domain: "", path: "" }]);
  };

  const updateMapping = (
    index: number,
    field: keyof ContentMapping,
    value: string,
  ) => {
    setMappings((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)),
    );
  };

  const removeMapping = (index: number) => {
    setMappings((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Register New Git Source
        </h2>
        <button
          onClick={onClose}
          className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          Close
        </button>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            placeholder="e.g., network-configs"
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            URL
          </label>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            placeholder="https://github.com/..."
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Branch
          </label>
          <input
            type="text"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Auth Type
          </label>
          <select
            value={authType}
            onChange={(e) => setAuthType(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          >
            <option value="none">None</option>
            <option value="ssh">SSH Key</option>
            <option value="token">Personal Access Token</option>
            <option value="basic">Basic Auth</option>
          </select>
        </div>
      </div>

      {/* Content Mappings */}
      <div className="mb-3">
        <div className="mb-1 flex items-center justify-between">
          <label className="text-xs font-medium text-gray-500 dark:text-gray-400">
            Content Mappings
          </label>
          <button
            onClick={addMapping}
            className="text-xs text-brand-600 hover:text-brand-700"
          >
            + Add Mapping
          </button>
        </div>
        <div className="space-y-2">
          {mappings.map((mapping, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={mapping.domain}
                onChange={(e) => updateMapping(i, "domain", e.target.value)}
                className="flex-1 rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                placeholder="Domain (e.g., devices)"
              />
              <input
                type="text"
                value={mapping.path}
                onChange={(e) => updateMapping(i, "path", e.target.value)}
                className="flex-1 rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                placeholder="Path (e.g., configs/devices/)"
              />
              {mappings.length > 1 && (
                <button
                  onClick={() => removeMapping(i)}
                  className="text-sm text-gray-400 hover:text-red-500"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
        >
          Cancel
        </button>
        <button
          onClick={() =>
            registerMutation.mutate({
              name,
              url,
              branch,
              auth_type: authType,
              content_mappings: mappings.filter(
                (m) => m.domain && m.path,
              ),
            })
          }
          disabled={registerMutation.isPending || !name || !url}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {registerMutation.isPending ? "Registering..." : "Register"}
        </button>
      </div>
      {registerMutation.isError && (
        <div className="mt-2 text-sm text-red-500">
          Error: {String(registerMutation.error)}
        </div>
      )}
    </div>
  );
}
