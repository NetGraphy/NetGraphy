/**
 * AIConfigPage — Admin UI for managing AI providers, models, and agent settings.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

const PROVIDER_TYPES = [
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure OpenAI" },
  { value: "openai_compatible", label: "OpenAI-Compatible (vLLM, Ollama, etc.)" },
];

export function AIConfigPage() {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    name: "", provider_type: "anthropic", api_key: "", api_base: "",
    default_model: "claude-sonnet-4-20250514", enabled: true,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["ai-providers"],
    queryFn: () => api.get("/agent/providers"),
  });
  const providers = data?.data?.data || [];

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post("/agent/providers", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-providers"] });
      setShowAdd(false);
      setForm({ name: "", provider_type: "anthropic", api_key: "", api_base: "", default_model: "claude-sonnet-4-20250514", enabled: true });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch(`/agent/providers/${id}`, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-providers"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/agent/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-providers"] }),
  });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">AI Configuration</h1>
        <p className="mt-1 text-sm text-gray-500">
          Configure AI model providers, credentials, and default models for the built-in assistant.
        </p>
      </div>

      {/* Status */}
      <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="flex items-center gap-3">
          <div className={`h-3 w-3 rounded-full ${providers.some((p: { enabled: boolean }) => p.enabled) ? "bg-green-500" : "bg-red-500"}`} />
          <span className="text-sm font-medium">
            {providers.some((p: { enabled: boolean }) => p.enabled)
              ? `${providers.filter((p: { enabled: boolean }) => p.enabled).length} provider(s) active`
              : "No providers configured — the AI assistant requires at least one provider"}
          </span>
        </div>
        <p className="mt-2 text-xs text-gray-500">
          You can also set ANTHROPIC_API_KEY or OPENAI_API_KEY as environment variables for quick setup.
        </p>
      </div>

      {/* Add provider */}
      <div className="mb-4 flex justify-end">
        <button onClick={() => setShowAdd(!showAdd)}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          {showAdd ? "Cancel" : "Add Provider"}
        </button>
      </div>

      {showAdd && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <h3 className="mb-3 text-sm font-semibold">Add AI Provider</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Provider Name</label>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g., Production Claude"
                className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Provider Type</label>
              <select value={form.provider_type} onChange={(e) => setForm({ ...form, provider_type: e.target.value })}
                className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                {PROVIDER_TYPES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">API Key</label>
              <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder="sk-... or anthropic key"
                className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-500">Default Model</label>
              <input type="text" value={form.default_model} onChange={(e) => setForm({ ...form, default_model: e.target.value })}
                placeholder="claude-sonnet-4-20250514"
                className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </div>
            {form.provider_type === "openai_compatible" && (
              <div className="col-span-2">
                <label className="mb-1 block text-xs font-medium text-gray-500">API Base URL</label>
                <input type="text" value={form.api_base} onChange={(e) => setForm({ ...form, api_base: e.target.value })}
                  placeholder="http://localhost:8080/v1"
                  className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
              </div>
            )}
          </div>
          <div className="mt-3 flex justify-end">
            <button onClick={() => createMutation.mutate(form)}
              disabled={!form.name || !form.api_key || createMutation.isPending}
              className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700 disabled:opacity-50">
              {createMutation.isPending ? "Adding..." : "Add Provider"}
            </button>
          </div>
        </div>
      )}

      {/* Provider list */}
      {isLoading ? <div className="text-gray-500">Loading...</div> : (
        <div className="space-y-3">
          {providers.map((p: Record<string, unknown>) => (
            <div key={p.id as string} className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`h-2.5 w-2.5 rounded-full ${p.enabled ? "bg-green-500" : "bg-gray-400"}`} />
                  <div>
                    <div className="font-medium text-gray-900 dark:text-white">{p.name as string}</div>
                    <div className="text-xs text-gray-500">
                      {PROVIDER_TYPES.find((pt) => pt.value === p.provider_type)?.label || p.provider_type as string}
                      {p.default_model && <span className="ml-2">| Model: <code>{p.default_model as string}</code></span>}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => toggleMutation.mutate({ id: p.id as string, enabled: !p.enabled })}
                    className={`rounded border px-3 py-1 text-xs ${p.enabled ? "border-gray-300 text-gray-600" : "border-green-300 text-green-600"}`}>
                    {p.enabled ? "Disable" : "Enable"}
                  </button>
                  <button onClick={() => { if (confirm("Delete this provider?")) deleteMutation.mutate(p.id as string); }}
                    className="rounded border border-red-300 px-3 py-1 text-xs text-red-600 hover:bg-red-50">
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
          {providers.length === 0 && !showAdd && (
            <div className="rounded-lg border-2 border-dashed border-gray-300 p-8 text-center dark:border-gray-600">
              <svg className="mx-auto h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              <div className="mt-3 text-sm text-gray-500">No AI providers configured</div>
              <div className="mt-1 text-xs text-gray-400">Add a provider to enable the AI assistant</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
