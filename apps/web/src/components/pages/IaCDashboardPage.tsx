/**
 * IaCDashboardPage — Infrastructure as Code overview dashboard.
 *
 * Shows compliance summary, recent runs, and quick actions for
 * backup, intended config generation, and compliance checks.
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";

interface ComplianceSummary {
  overall_compliance_pct: number;
  total_checks: number;
  total_compliant: number;
  total_non_compliant: number;
  by_feature: {
    feature: string;
    total: number;
    compliant: number;
    non_compliant: number;
    compliance_pct: number;
  }[];
}

export function IaCDashboardPage() {
  const [runOutput, setRunOutput] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: ["iac-compliance-summary"],
    queryFn: () => api.get("/iac/compliance/summary"),
  });
  const summary: ComplianceSummary | null = summaryData?.data?.data || null;

  const { data: profilesData } = useQuery({
    queryKey: ["iac-profiles"],
    queryFn: () => api.get("/iac/profiles"),
  });
  const profiles = profilesData?.data?.data || [];

  const { data: featuresData } = useQuery({
    queryKey: ["iac-features"],
    queryFn: () => api.get("/iac/compliance/features"),
  });
  const features = featuresData?.data?.data || [];

  const { data: rulesData } = useQuery({
    queryKey: ["iac-rules"],
    queryFn: () => api.get("/iac/compliance/rules"),
  });
  const rules = rulesData?.data?.data || [];

  const { data: contextsData } = useQuery({
    queryKey: ["iac-contexts"],
    queryFn: () => api.get("/iac/contexts"),
  });
  const contexts = contextsData?.data?.data || [];

  const { data: transformationsData } = useQuery({
    queryKey: ["iac-transformations"],
    queryFn: () => api.get("/iac/transformations"),
  });
  const transformations = transformationsData?.data?.data || [];

  const backupMutation = useMutation({
    mutationFn: () => api.post("/iac/backup/run", { dry_run: false }),
    onSuccess: (resp) => {
      setRunOutput(JSON.stringify(resp.data.data, null, 2));
      setRunError(null);
    },
    onError: (err: unknown) => {
      setRunError(String((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || err));
    },
  });

  const intendedMutation = useMutation({
    mutationFn: () => api.post("/iac/intended/run", { dry_run: false }),
    onSuccess: (resp) => {
      setRunOutput(JSON.stringify(resp.data.data, null, 2));
      setRunError(null);
    },
    onError: (err: unknown) => {
      setRunError(String((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || err));
    },
  });

  const complianceMutation = useMutation({
    mutationFn: () => api.post("/iac/compliance/run", {}),
    onSuccess: (resp) => {
      setRunOutput(JSON.stringify(resp.data.data, null, 2));
      setRunError(null);
    },
    onError: (err: unknown) => {
      setRunError(String((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || err));
    },
  });

  const compliancePct = summary?.overall_compliance_pct ?? 0;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Infrastructure as Code
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Config backup, intended generation, compliance checking, and device transformation
        </p>
      </div>

      {/* Quick Actions */}
      <div className="mb-6 flex flex-wrap gap-3">
        <button
          onClick={() => backupMutation.mutate()}
          disabled={backupMutation.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {backupMutation.isPending ? "Running Backup..." : "Run Config Backup"}
        </button>
        <button
          onClick={() => intendedMutation.mutate()}
          disabled={intendedMutation.isPending}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {intendedMutation.isPending ? "Generating..." : "Generate Intended Configs"}
        </button>
        <button
          onClick={() => complianceMutation.mutate()}
          disabled={complianceMutation.isPending}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {complianceMutation.isPending ? "Checking..." : "Run Compliance Check"}
        </button>
      </div>

      {/* Run output */}
      {(runOutput || runError) && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Run Output</h3>
            <button
              onClick={() => { setRunOutput(null); setRunError(null); }}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Dismiss
            </button>
          </div>
          {runError && (
            <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
              {runError}
            </div>
          )}
          {runOutput && (
            <pre className="max-h-60 overflow-auto rounded bg-gray-50 p-3 text-xs text-gray-700 dark:bg-gray-900 dark:text-gray-300">
              {runOutput}
            </pre>
          )}
        </div>
      )}

      {/* Stats Grid */}
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
        <StatCard
          label="Overall Compliance"
          value={summary ? `${compliancePct}%` : "—"}
          color={compliancePct >= 90 ? "green" : compliancePct >= 70 ? "yellow" : "red"}
        />
        <StatCard label="Compliance Checks" value={summary?.total_checks ?? 0} />
        <StatCard label="Config Profiles" value={profiles.length} />
        <StatCard label="Features" value={features.length} />
        <StatCard label="Rules" value={rules.length} />
        <StatCard label="Config Contexts" value={contexts.length} />
      </div>

      {/* Compliance by Feature */}
      {summary && summary.by_feature.length > 0 && (
        <div className="mb-6 rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Compliance by Feature
            </h2>
          </div>
          <div className="overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Feature</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Compliant</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Non-Compliant</th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Compliance %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {summary.by_feature.map((f) => (
                  <tr key={f.feature} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td className="px-4 py-2 text-sm font-medium text-gray-900 dark:text-white">
                      {f.feature}
                    </td>
                    <td className="px-4 py-2 text-sm text-green-600">{f.compliant}</td>
                    <td className="px-4 py-2 text-sm text-red-600">{f.non_compliant}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-24 rounded-full bg-gray-200 dark:bg-gray-700">
                          <div
                            className={`h-2 rounded-full ${
                              f.compliance_pct >= 90 ? "bg-green-500" : f.compliance_pct >= 70 ? "bg-yellow-500" : "bg-red-500"
                            }`}
                            style={{ width: `${f.compliance_pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500">{f.compliance_pct}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Quick Links Grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <QuickLinkCard
          title="Config Profiles"
          description="Git repo bindings, path templates, and rendering settings per device scope"
          count={profiles.length}
          href="/objects/ConfigProfile"
          color="indigo"
        />
        <QuickLinkCard
          title="Compliance Features"
          description="Named config features (aaa, ntp, bgp, snmp) for compliance checking"
          count={features.length}
          href="/objects/ComplianceFeature"
          color="emerald"
        />
        <QuickLinkCard
          title="Compliance Rules"
          description="Per-platform rules linking features to match patterns and diff settings"
          count={rules.length}
          href="/objects/ComplianceRule"
          color="amber"
        />
        <QuickLinkCard
          title="Config Contexts"
          description="Scoped JSON data for per-device rendering (TACACS, NTP, syslog, etc.)"
          count={contexts.length}
          href="/objects/ConfigContext"
          color="purple"
        />
        <QuickLinkCard
          title="Transformation Mappings"
          description="Hardware replacement automation — interface and state transfer rules"
          count={transformations.length}
          href="/objects/TransformationMapping"
          color="pink"
        />
        <QuickLinkCard
          title="Compliance Results"
          description="Per-device, per-feature compliance check results"
          count={summary?.total_checks ?? 0}
          href="/objects/ComplianceResult"
          color="red"
        />
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const colorClasses = {
    green: "text-green-600 dark:text-green-400",
    yellow: "text-yellow-600 dark:text-yellow-400",
    red: "text-red-600 dark:text-red-400",
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="text-xs font-medium uppercase text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${color ? colorClasses[color as keyof typeof colorClasses] || "text-gray-900 dark:text-white" : "text-gray-900 dark:text-white"}`}>
        {value}
      </div>
    </div>
  );
}

function QuickLinkCard({
  title,
  description,
  count,
  href,
  color,
}: {
  title: string;
  description: string;
  count: number;
  href: string;
  color: string;
}) {
  const borderColors: Record<string, string> = {
    indigo: "border-l-indigo-500",
    emerald: "border-l-emerald-500",
    amber: "border-l-amber-500",
    purple: "border-l-purple-500",
    pink: "border-l-pink-500",
    red: "border-l-red-500",
  };

  return (
    <Link
      to={href}
      className={`block rounded-lg border border-gray-200 border-l-4 ${borderColors[color] || "border-l-gray-500"} bg-white p-4 transition-shadow hover:shadow-md dark:border-gray-700 dark:bg-gray-800`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-300">
          {count}
        </span>
      </div>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>
    </Link>
  );
}
