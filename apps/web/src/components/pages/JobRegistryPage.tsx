/**
 * JobRegistryPage — browse, run, and monitor automation jobs.
 * Fetches from GET /jobs, supports executing with parameters and viewing history.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface JobParameter {
  name: string;
  type: string;
  required: boolean;
  default?: unknown;
  description?: string;
  enum_values?: string[];
}

interface Job {
  name: string;
  description?: string;
  runtime: string;
  schedule?: string;
  last_run_status?: string;
  last_run_at?: string;
  parameters?: JobParameter[];
}

interface JobExecution {
  id: string;
  job_name: string;
  status: string;
  started_at: string;
  finished_at?: string;
  duration_ms?: number;
  error?: string;
}

export function JobRegistryPage() {
  const [runJobName, setRunJobName] = useState<string | null>(null);
  const [runJobParams, setRunJobParams] = useState<JobParameter[]>([]);
  const [paramValues, setParamValues] = useState<Record<string, unknown>>({});
  const [historyJobName, setHistoryJobName] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<{ data: Job[] }>("/jobs"),
  });

  const jobs = data?.data?.data || [];

  const executeMutation = useMutation({
    mutationFn: ({
      name,
      parameters,
    }: {
      name: string;
      parameters: Record<string, unknown>;
    }) => api.post(`/jobs/${name}/execute`, { parameters }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setRunJobName(null);
    },
  });

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["job-history", historyJobName],
    queryFn: () =>
      api.get<{ data: JobExecution[] }>(`/jobs/${historyJobName}/executions`),
    enabled: !!historyJobName,
  });

  const executions = historyData?.data?.data || [];

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        Job Registry
      </h1>

      {/* Run Job Dialog */}
      {runJobName && (
        <RunJobDialog
          jobName={runJobName}
          parameters={runJobParams}
          paramValues={paramValues}
          onParamChange={(key, value) =>
            setParamValues((prev) => ({ ...prev, [key]: value }))
          }
          onClose={() => {
            setRunJobName(null);
            setParamValues({});
            executeMutation.reset();
          }}
          onRun={() =>
            executeMutation.mutate({
              name: runJobName,
              parameters: paramValues,
            })
          }
          isPending={executeMutation.isPending}
          error={executeMutation.error}
          isSuccess={executeMutation.isSuccess}
        />
      )}

      {/* Job Execution History */}
      {historyJobName && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Execution History: {historyJobName}
            </h2>
            <button
              onClick={() => setHistoryJobName(null)}
              className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              Close
            </button>
          </div>
          {historyLoading ? (
            <div className="text-sm text-gray-500">Loading history...</div>
          ) : (
            <div className="overflow-hidden rounded-md border border-gray-200 dark:border-gray-700">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-900">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Status
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Started
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Duration
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">
                      Error
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {executions.map((exec: JobExecution) => (
                    <tr
                      key={exec.id}
                      className="hover:bg-gray-50 dark:hover:bg-gray-700"
                    >
                      <td className="px-3 py-2 text-sm">
                        <StatusBadge status={exec.status} />
                      </td>
                      <td className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                        {new Date(exec.started_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                        {exec.duration_ms != null
                          ? `${(exec.duration_ms / 1000).toFixed(1)}s`
                          : "\u2014"}
                      </td>
                      <td className="max-w-xs truncate px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                        {exec.error || "\u2014"}
                      </td>
                    </tr>
                  ))}
                  {executions.length === 0 && (
                    <tr>
                      <td
                        colSpan={4}
                        className="px-3 py-6 text-center text-sm text-gray-500"
                      >
                        No executions found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Jobs List */}
      {isLoading ? (
        <div className="text-gray-500">Loading jobs...</div>
      ) : error ? (
        <div className="text-red-500">Error loading jobs</div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((job: Job) => (
            <div
              key={job.name}
              className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
            >
              <div className="mb-2 flex items-start justify-between">
                <h3 className="font-medium text-gray-900 dark:text-white">
                  {job.name}
                </h3>
                <RuntimeBadge runtime={job.runtime} />
              </div>
              {job.description && (
                <p className="mb-3 text-sm text-gray-500 dark:text-gray-400">
                  {job.description}
                </p>
              )}
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                {job.schedule && (
                  <span className="rounded bg-gray-100 px-2 py-0.5 text-gray-600 dark:bg-gray-700 dark:text-gray-400">
                    {job.schedule}
                  </span>
                )}
                {job.last_run_status && (
                  <StatusBadge status={job.last_run_status} />
                )}
                {job.last_run_at && (
                  <span className="text-gray-400">
                    Last: {new Date(job.last_run_at).toLocaleString()}
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setRunJobName(job.name);
                    setRunJobParams(job.parameters || []);
                    setParamValues(
                      (job.parameters || []).reduce(
                        (acc, p) => {
                          if (p.default !== undefined)
                            acc[p.name] = p.default;
                          return acc;
                        },
                        {} as Record<string, unknown>,
                      ),
                    );
                  }}
                  className="rounded-md bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-700"
                >
                  Run Job
                </button>
                <button
                  onClick={() => setHistoryJobName(job.name)}
                  className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
                >
                  View History
                </button>
              </div>
            </div>
          ))}
          {jobs.length === 0 && (
            <div className="col-span-full flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-12 dark:border-gray-600 dark:bg-gray-800">
              <p className="text-sm text-gray-500">No jobs registered.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RuntimeBadge({ runtime }: { runtime: string }) {
  const colorMap: Record<string, string> = {
    python:
      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    go: "bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200",
  };

  const classes =
    colorMap[runtime.toLowerCase()] ||
    "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200";

  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {runtime}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    success:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    completed:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    running:
      "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    queued:
      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
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

function RunJobDialog({
  jobName,
  parameters,
  paramValues,
  onParamChange,
  onClose,
  onRun,
  isPending,
  error,
  isSuccess,
}: {
  jobName: string;
  parameters: JobParameter[];
  paramValues: Record<string, unknown>;
  onParamChange: (key: string, value: unknown) => void;
  onClose: () => void;
  onRun: () => void;
  isPending: boolean;
  error: Error | null;
  isSuccess: boolean;
}) {
  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Run Job: {jobName}
        </h2>
        <button
          onClick={onClose}
          className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          Close
        </button>
      </div>

      {parameters.length > 0 ? (
        <div className="mb-3 space-y-3">
          {parameters.map((param) => (
            <div key={param.name} className="flex flex-col">
              <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
                {param.name}
                {param.required && (
                  <span className="ml-0.5 text-red-500">*</span>
                )}
                {param.description && (
                  <span className="ml-1 font-normal text-gray-400">
                    - {param.description}
                  </span>
                )}
              </label>
              {param.enum_values ? (
                <select
                  value={String(paramValues[param.name] ?? "")}
                  onChange={(e) => onParamChange(param.name, e.target.value)}
                  className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                >
                  <option value="">Select...</option>
                  {param.enum_values.map((val) => (
                    <option key={val} value={val}>
                      {val}
                    </option>
                  ))}
                </select>
              ) : param.type === "boolean" ? (
                <select
                  value={String(paramValues[param.name] ?? "")}
                  onChange={(e) =>
                    onParamChange(param.name, e.target.value === "true")
                  }
                  className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                >
                  <option value="">Select...</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : param.type === "integer" || param.type === "float" ? (
                <input
                  type="number"
                  value={String(paramValues[param.name] ?? "")}
                  onChange={(e) =>
                    onParamChange(
                      param.name,
                      param.type === "integer"
                        ? parseInt(e.target.value, 10)
                        : parseFloat(e.target.value),
                    )
                  }
                  className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                />
              ) : (
                <input
                  type="text"
                  value={String(paramValues[param.name] ?? "")}
                  onChange={(e) => onParamChange(param.name, e.target.value)}
                  className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  placeholder={`Enter ${param.name}...`}
                />
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="mb-3 text-sm text-gray-500">
          This job has no configurable parameters.
        </p>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
        >
          Cancel
        </button>
        <button
          onClick={onRun}
          disabled={isPending}
          className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {isPending ? "Submitting..." : "Execute"}
        </button>
        {isSuccess && (
          <span className="text-sm text-green-600">Job queued successfully</span>
        )}
        {error && (
          <span className="text-sm text-red-500">
            Error: {String(error)}
          </span>
        )}
      </div>
    </div>
  );
}
