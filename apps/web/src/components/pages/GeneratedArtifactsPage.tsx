/**
 * GeneratedArtifactsPage — preview all schema-derived artifacts.
 *
 * Tabs: Summary | MCP Tools | Agent Capabilities | Validation | Observability | Health Report
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

type Tab = "summary" | "mcp" | "agent" | "validation" | "observability" | "health";

export function GeneratedArtifactsPage() {
  const [tab, setTab] = useState<Tab>("summary");

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Generated Artifacts</h1>
        <p className="mt-1 text-sm text-gray-500">
          All artifacts below are automatically derived from the schema — MCP tools, agent capabilities, validation rules, and observability checks.
        </p>
      </div>

      <div className="mb-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex gap-3">
          {([
            ["summary", "Summary"],
            ["mcp", "MCP Tools"],
            ["agent", "Agent Capabilities"],
            ["validation", "Validation Rules"],
            ["observability", "Observability"],
            ["health", "Health Report"],
          ] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`border-b-2 px-1 pb-2 text-sm font-medium ${
                tab === id ? "border-brand-500 text-brand-600" : "border-transparent text-gray-500 hover:text-gray-700"
              }`}>{label}</button>
          ))}
        </div>
      </div>

      {tab === "summary" && <SummaryTab />}
      {tab === "mcp" && <MCPToolsTab />}
      {tab === "agent" && <AgentTab />}
      {tab === "validation" && <ValidationTab />}
      {tab === "observability" && <ObservabilityTab />}
      {tab === "health" && <HealthTab />}
    </div>
  );
}

function SummaryTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["generated-summary"],
    queryFn: () => api.get("/generated/summary"),
  });
  const summary = data?.data?.data;

  if (isLoading) return <div className="text-gray-500">Loading...</div>;
  if (!summary) return <div className="text-gray-500">No data</div>;

  return (
    <div>
      <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
        <div className="text-xs text-gray-500">Schema Version: <code className="text-brand-600">{summary.schema_version}</code></div>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="MCP Tools" value={summary.mcp_tools_count} />
        <StatCard label="Agent Capabilities" value={summary.agent_capabilities_count} />
        <StatCard label="Validation Rules" value={summary.validation_rules_count} />
        <StatCard label="Observability Rules" value={summary.observability_rules_count} />
      </div>

      {summary.mcp_tools_by_category && (
        <div className="mt-6 grid grid-cols-2 gap-6">
          <CategoryBreakdown title="MCP Tools by Category" data={summary.mcp_tools_by_category} />
          <CategoryBreakdown title="Agent Capabilities by Category" data={summary.agent_capabilities_by_category} />
          <CategoryBreakdown title="Validation Rules by Type" data={summary.validation_rules_by_type} />
          <CategoryBreakdown title="Observability by Type" data={summary.observability_rules_by_type} />
        </div>
      )}
    </div>
  );
}

function MCPToolsTab() {
  const [filter, setFilter] = useState("");
  const [category, setCategory] = useState("");
  const { data } = useQuery({ queryKey: ["mcp-tools", category], queryFn: () => api.get("/generated/mcp-tools", { params: category ? { category } : {} }) });
  const tools = (data?.data?.data || []) as Record<string, unknown>[];
  const filtered = tools.filter((t) => !filter || JSON.stringify(t).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="mb-4 flex gap-3">
        <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search tools..."
          className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option value="">All categories</option>
          {["crud", "search", "relationship", "traversal"].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="text-xs text-gray-500 mb-3">{filtered.length} tools</div>
      <div className="space-y-2">
        {filtered.map((tool, i) => (
          <ToolCard key={i} tool={tool} />
        ))}
      </div>
    </div>
  );
}

function ToolCard({ tool }: { tool: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const catColors: Record<string, string> = {
    crud: "bg-blue-100 text-blue-700", search: "bg-green-100 text-green-700",
    relationship: "bg-purple-100 text-purple-700", traversal: "bg-amber-100 text-amber-700",
  };
  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <button onClick={() => setExpanded(!expanded)} className="flex w-full items-center justify-between px-4 py-2.5 text-left">
        <div className="flex items-center gap-2">
          <code className="text-sm font-semibold text-gray-900 dark:text-white">{tool.name as string}</code>
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${catColors[tool.category as string] || "bg-gray-100 text-gray-700"}`}>
            {tool.category as string}
          </span>
          {tool.node_type && <span className="text-xs text-gray-400">{tool.node_type as string}</span>}
        </div>
        <svg className={`h-4 w-4 text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
      </button>
      {expanded && (
        <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700">
          <p className="mb-2 text-sm text-gray-600 dark:text-gray-400">{tool.description as string}</p>
          {tool.inputSchema && (
            <div>
              <div className="mb-1 text-xs font-semibold text-gray-500">Input Schema</div>
              <pre className="max-h-48 overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-700 dark:bg-gray-900 dark:text-gray-300">
                {JSON.stringify(tool.inputSchema, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AgentTab() {
  const [filter, setFilter] = useState("");
  const [category, setCategory] = useState("");
  const { data } = useQuery({ queryKey: ["agent-caps", category], queryFn: () => api.get("/generated/agent-capabilities", { params: category ? { category } : {} }) });
  const caps = (data?.data?.data || []) as Record<string, unknown>[];
  const filtered = caps.filter((c) => !filter || JSON.stringify(c).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="mb-4 flex gap-3">
        <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search capabilities..."
          className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option value="">All categories</option>
          {["crud", "search", "relationship", "traversal", "health", "audit", "custom"].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="text-xs text-gray-500 mb-3">{filtered.length} capabilities</div>
      <div className="space-y-2">
        {filtered.map((cap, i) => {
          const safetyColors: Record<string, string> = { read: "bg-green-100 text-green-700", write: "bg-amber-100 text-amber-700", destructive: "bg-red-100 text-red-700" };
          return (
            <div key={i} className="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-gray-900 dark:text-white">{cap.display_name as string}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${safetyColors[cap.safety as string] || ""}`}>{cap.safety as string}</span>
                <span className="text-xs text-gray-400">{cap.category as string}</span>
              </div>
              <p className="mt-1 text-xs text-gray-500">{cap.description as string}</p>
              {cap.example_prompts && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {(cap.example_prompts as string[]).map((p, j) => (
                    <span key={j} className="rounded bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600 dark:bg-gray-700 dark:text-gray-300">{p}</span>
                  ))}
                </div>
              )}
              {cap.backing_tools && (cap.backing_tools as string[]).length > 0 && (
                <div className="mt-1 text-[10px] text-gray-400">Tools: {(cap.backing_tools as string[]).join(", ")}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ValidationTab() {
  const [nodeType, setNodeType] = useState("");
  const { data } = useQuery({
    queryKey: ["validation-rules", nodeType],
    queryFn: () => api.get("/generated/validation-rules", { params: nodeType ? { node_type: nodeType } : {} }),
  });
  const rules = (data?.data?.data || []) as Record<string, unknown>[];
  const types = [...new Set(rules.map((r) => (r.node_type || r.edge_type) as string))].filter(Boolean).sort();

  return (
    <div>
      <div className="mb-4">
        <select value={nodeType} onChange={(e) => setNodeType(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option value="">All types ({rules.length} rules)</option>
          {types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
          <thead className="bg-gray-50 dark:bg-gray-900">
            <tr>
              {["Type", "Rule", "Field", "Message", "Severity"].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white dark:divide-gray-700 dark:bg-gray-800">
            {rules.slice(0, 200).map((r, i) => (
              <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                <td className="px-3 py-1.5 text-xs text-gray-500">{(r.node_type || r.edge_type) as string}</td>
                <td className="px-3 py-1.5"><code className="text-xs">{r.rule_type as string}</code></td>
                <td className="px-3 py-1.5 text-xs">{(r.field || "") as string}</td>
                <td className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400">{r.message as string}</td>
                <td className="px-3 py-1.5">
                  <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                    r.severity === "error" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"
                  }`}>{r.severity as string}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ObservabilityTab() {
  const { data } = useQuery({ queryKey: ["obs-rules"], queryFn: () => api.get("/generated/observability-rules") });
  const rules = (data?.data?.data || []) as Record<string, unknown>[];
  const metrics = rules.filter((r) => r.rule_type === "metric");
  const checks = rules.filter((r) => r.rule_type === "health_check");
  const alerts = rules.filter((r) => r.rule_type === "alert");

  return (
    <div className="space-y-6">
      <Section title={`Metrics (${metrics.length})`}>
        {metrics.map((m, i) => (
          <div key={i} className="flex items-center justify-between border-b border-gray-100 px-3 py-1.5 last:border-0 dark:border-gray-700">
            <div>
              <code className="text-sm font-medium text-gray-900 dark:text-white">{m.metric_name as string}</code>
              <span className="ml-2 text-xs text-gray-500">{m.description as string}</span>
            </div>
            <div className="flex gap-1">
              {Object.entries((m.labels || {}) as Record<string, string>).map(([k, v]) => (
                <span key={k} className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-700 dark:text-gray-300">{k}={v}</span>
              ))}
            </div>
          </div>
        ))}
      </Section>
      <Section title={`Health Checks (${checks.length})`}>
        {checks.map((c, i) => (
          <div key={i} className="flex items-center justify-between border-b border-gray-100 px-3 py-1.5 last:border-0 dark:border-gray-700">
            <div>
              <span className="text-sm font-medium">{c.check_name as string}</span>
              <span className="ml-2 text-xs text-gray-500">{c.description as string}</span>
            </div>
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
              c.severity === "critical" ? "bg-red-100 text-red-700" : c.severity === "error" ? "bg-orange-100 text-orange-700" : "bg-amber-100 text-amber-700"
            }`}>{c.severity as string}</span>
          </div>
        ))}
      </Section>
      <Section title={`Alerts (${alerts.length})`}>
        {alerts.map((a, i) => (
          <div key={i} className="border-b border-gray-100 px-3 py-1.5 last:border-0 dark:border-gray-700">
            <span className="text-sm font-medium">{a.alert_name as string}</span>
            <span className="ml-2 text-xs text-gray-500">{a.description as string}</span>
            <code className="ml-2 text-xs text-brand-600">{a.condition as string}</code>
          </div>
        ))}
      </Section>
    </div>
  );
}

function HealthTab() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["health-report"],
    queryFn: () => api.get("/generated/health-report"),
  });
  const report = data?.data?.data;

  const statusColors: Record<string, string> = {
    healthy: "bg-green-100 text-green-800",
    degraded: "bg-amber-100 text-amber-800",
    unhealthy: "bg-orange-100 text-orange-800",
    critical: "bg-red-100 text-red-800",
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {report && (
            <span className={`rounded-full px-3 py-1 text-sm font-bold ${statusColors[report.status] || ""}`}>
              {report.status?.toUpperCase()}
            </span>
          )}
          {report && <span className="text-sm text-gray-500">{report.issues_count} issues found</span>}
        </div>
        <button onClick={() => refetch()} className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white hover:bg-brand-700">
          {isLoading ? "Running..." : "Run Health Checks"}
        </button>
      </div>

      {report?.checks?.length > 0 && (
        <div className="space-y-2">
          {report.checks.map((check: Record<string, unknown>, i: number) => (
            <div key={i} className={`rounded-lg border p-3 ${
              check.passed ? "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/10" : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/10"
            }`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium ${check.passed ? "text-green-700" : "text-red-700"}`}>
                    {check.passed ? "PASS" : "FAIL"} — {check.name as string}
                  </span>
                  <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                    check.severity === "critical" ? "bg-red-200 text-red-800" : "bg-amber-200 text-amber-800"
                  }`}>{check.severity as string}</span>
                </div>
                {!check.passed && <span className="text-xs text-red-600">{check.issue_count as number} issues</span>}
              </div>
              <p className="mt-1 text-xs text-gray-600">{check.description as string}</p>
              {!check.passed && (check.issues as Record<string, unknown>[])?.length > 0 && (
                <div className="mt-2 max-h-24 overflow-auto rounded bg-white p-2 text-xs dark:bg-gray-800">
                  {(check.issues as Record<string, unknown>[]).map((issue, j) => (
                    <div key={j} className="text-gray-600">{JSON.stringify(issue)}</div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="text-xs font-medium uppercase text-gray-500">{label}</div>
      <div className="mt-1 text-3xl font-bold text-gray-900 dark:text-white">{value}</div>
    </div>
  );
}

function CategoryBreakdown({ title, data }: { title: string; data: Record<string, number> }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <h3 className="mb-2 text-xs font-semibold uppercase text-gray-500">{title}</h3>
      <div className="space-y-1">
        {Object.entries(data).map(([key, count]) => (
          <div key={key} className="flex items-center justify-between text-sm">
            <span className="text-gray-600 dark:text-gray-400">{key}</span>
            <span className="font-mono text-gray-900 dark:text-white">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <div className="border-b border-gray-200 px-4 py-2 dark:border-gray-700">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">{title}</h3>
      </div>
      <div>{children}</div>
    </div>
  );
}
