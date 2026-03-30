/**
 * PipelinePane — End-to-end ingestion pipeline testing.
 *
 * Steps: Command Output -> Parse -> Map -> Graph Mutation Preview
 *
 * Left: Step navigator + parser/mapping selection
 * Center: Input/output for current step
 * Right: Generated mutations and model preview
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { api } from "@/api/client";

interface Parser {
  id: string;
  name: string;
  platform: string;
  command: string;
}

interface PipelineResult {
  step: string;
  records: Record<string, unknown>[];
  record_count: number;
  headers: string[];
  mutations: MutationPreview[];
  mutation_count: number;
  mapping_errors: string[];
  has_mapping: boolean;
  error?: string;
}

interface MutationPreview {
  operation: string;
  node_type?: string;
  edge_type?: string;
  match_on?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
  source_match?: Record<string, unknown>;
  target_match?: Record<string, unknown>;
}

const SAMPLE_OUTPUT = `Cisco IOS Software, ISR Software (X86_64_LINUX_IOSD-UNIVERSALK9-M), Version 16.09.01, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport

router1 uptime is 2 weeks, 3 days, 14 hours, 22 minutes
System returned to ROM by reload at 12:30:22 UTC Wed Mar 1 2026

System image file is "bootflash:isr4400-universalk9.16.09.01.SPA.bin"

cisco ISR4431/K9 (1RU) processor with 3670016K/6147K bytes of memory.
Processor board ID FDO2145A0BC
4 Gigabit Ethernet interfaces
32768K bytes of non-volatile configuration memory.
16777216K bytes of physical memory.
`;

type PipelineStep = "input" | "parsed" | "mapped" | "mutations";

const STEPS: { id: PipelineStep; label: string; num: number }[] = [
  { id: "input", label: "Command Output", num: 1 },
  { id: "parsed", label: "Parsed Records", num: 2 },
  { id: "mapped", label: "Mapping Applied", num: 3 },
  { id: "mutations", label: "Graph Mutations", num: 4 },
];

function MutationIcon({ operation }: { operation: string }) {
  if (operation === "upsert_node") {
    return (
      <svg className="h-4 w-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
    </svg>
  );
}

export function PipelinePane() {
  // State
  const [rawOutput, setRawOutput] = useState("");
  const [selectedParserId, setSelectedParserId] = useState("");
  const [activeStep, setActiveStep] = useState<PipelineStep>("input");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  // Queries
  const { data: parsersData } = useQuery({
    queryKey: ["parsers"],
    queryFn: () => api.get("/parsers"),
  });
  const parsers: Parser[] = parsersData?.data?.data || [];

  // Pipeline execution
  const runMutation = useMutation({
    mutationFn: () =>
      api.post("/dev/test-pipeline", {
        raw_output: rawOutput,
        parser_id: selectedParserId,
      }),
    onSuccess: (resp) => {
      const d = resp.data.data as PipelineResult;
      if (d.error) {
        setPipelineError(d.error);
        setResult(null);
      } else {
        setResult(d);
        setPipelineError(null);
        // Auto-advance to results
        if (d.mutations?.length > 0) {
          setActiveStep("mutations");
        } else if (d.records?.length > 0) {
          setActiveStep("parsed");
        }
      }
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setPipelineError(typeof detail === "string" ? detail : "Pipeline error");
      setResult(null);
    },
  });

  const loadSample = () => {
    setRawOutput(SAMPLE_OUTPUT);
    // Try to auto-select a matching parser
    const match = parsers.find((p) => p.name.includes("show_version") && p.platform === "cisco_ios");
    if (match) setSelectedParserId(match.id || match.name);
  };

  return (
    <div className="flex h-full">
      {/* ---- Left: Pipeline Steps + Config ---- */}
      <div className="flex w-72 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800">
        <div className="flex items-center justify-between border-b border-gray-700 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Pipeline
          </span>
          <button
            onClick={loadSample}
            className="rounded px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700 hover:text-gray-200"
          >
            Sample
          </button>
        </div>

        {/* Steps */}
        <div className="border-b border-gray-700 px-3 py-3">
          <div className="space-y-1">
            {STEPS.map((step) => {
              const isComplete =
                result &&
                ((step.id === "parsed" && result.record_count > 0) ||
                  (step.id === "mapped" && result.has_mapping) ||
                  (step.id === "mutations" && result.mutation_count > 0));
              const isCurrent = activeStep === step.id;

              return (
                <button
                  key={step.id}
                  onClick={() => setActiveStep(step.id)}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${
                    isCurrent
                      ? "bg-brand-600/20 text-brand-300"
                      : "text-gray-400 hover:bg-gray-700 hover:text-gray-200"
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                      isComplete
                        ? "bg-green-500/20 text-green-300"
                        : isCurrent
                          ? "bg-brand-500/20 text-brand-300"
                          : "bg-gray-700 text-gray-500"
                    }`}
                  >
                    {isComplete ? (
                      <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      step.num
                    )}
                  </span>
                  {step.label}
                  {step.id === "parsed" && result && (
                    <span className="ml-auto text-xs text-gray-500">
                      {result.record_count}
                    </span>
                  )}
                  {step.id === "mutations" && result && (
                    <span className="ml-auto text-xs text-gray-500">
                      {result.mutation_count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Configuration */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          <div className="mb-3">
            <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Parser
            </label>
            <select
              value={selectedParserId}
              onChange={(e) => setSelectedParserId(e.target.value)}
              className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200 focus:border-brand-500 focus:outline-none"
            >
              <option value="">Select a parser...</option>
              {parsers.map((p) => (
                <option key={p.id || p.name} value={p.id || p.name}>
                  {p.name} ({p.platform})
                </option>
              ))}
            </select>
          </div>

          {/* Selected parser info */}
          {selectedParserId && (() => {
            const p = parsers.find((x) => x.id === selectedParserId || x.name === selectedParserId);
            return p ? (
              <div className="rounded border border-gray-700 bg-gray-900/50 p-2">
                <div className="text-xs font-medium text-gray-300">{p.name}</div>
                <div className="mt-1 text-[10px] text-gray-500">
                  Platform: <span className="text-gray-400">{p.platform}</span>
                </div>
                <div className="text-[10px] text-gray-500">
                  Command: <code className="text-brand-300">{p.command}</code>
                </div>
              </div>
            ) : null;
          })()}

          {/* Run pipeline button */}
          <button
            onClick={() => runMutation.mutate()}
            disabled={!rawOutput || !selectedParserId || runMutation.isPending}
            className="mt-4 w-full rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-500 disabled:opacity-40"
          >
            {runMutation.isPending ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Running Pipeline...
              </span>
            ) : (
              "Run Full Pipeline"
            )}
          </button>

          {/* Summary */}
          {result && (
            <div className="mt-4 space-y-2 rounded border border-gray-700 bg-gray-900/50 p-3">
              <div className="text-xs font-semibold uppercase text-gray-400">Pipeline Summary</div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Records Parsed</span>
                <span className="font-mono text-gray-200">{result.record_count}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Mutations Generated</span>
                <span className="font-mono text-gray-200">{result.mutation_count}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Mapping Applied</span>
                <span className={`font-mono ${result.has_mapping ? "text-green-300" : "text-amber-300"}`}>
                  {result.has_mapping ? "Yes" : "No mapping found"}
                </span>
              </div>
              {result.mapping_errors.length > 0 && (
                <div className="mt-1">
                  <div className="text-xs font-medium text-red-400">
                    Errors ({result.mapping_errors.length})
                  </div>
                  {result.mapping_errors.map((err, i) => (
                    <div key={i} className="mt-0.5 text-[10px] text-red-300">{err}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ---- Center: Content Area ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Step: Input */}
        {activeStep === "input" && (
          <div className="flex h-full flex-col">
            <div className="border-b border-gray-700 px-4 py-2" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Step 1: Raw Command Output
                </span>
                <span className="text-xs text-gray-500">
                  Paste the output of a show command or collect from a device
                </span>
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <Editor
                height="100%"
                language="plaintext"
                theme="vs-dark"
                value={rawOutput}
                onChange={(v) => setRawOutput(v || "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 13,
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                  automaticLayout: true,
                  padding: { top: 8, bottom: 8 },
                }}
              />
            </div>
          </div>
        )}

        {/* Step: Parsed Records */}
        {activeStep === "parsed" && (
          <div className="flex h-full flex-col">
            <div className="border-b border-gray-700 px-4 py-2" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Step 2: Parsed Records
                </span>
                {result && (
                  <span className="text-xs text-gray-500">
                    {result.record_count} record{result.record_count !== 1 ? "s" : ""} |{" "}
                    {result.headers.length} field{result.headers.length !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {!result ? (
                <div className="text-center text-sm text-gray-500">
                  Run the pipeline to see parsed records
                </div>
              ) : result.records.length === 0 ? (
                <div className="text-center text-sm text-amber-400">
                  No records parsed. Check your parser template and command output.
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700">
                      {result.headers.map((h) => (
                        <th key={h} className="px-3 py-2 text-left text-xs font-semibold uppercase text-gray-400">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.records.map((record, i) => (
                      <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-800">
                        {result.headers.map((h) => (
                          <td key={h} className="px-3 py-2 font-mono text-sm text-gray-300">
                            {typeof record[h] === "object"
                              ? JSON.stringify(record[h])
                              : String(record[h] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* Step: Mapping Applied */}
        {activeStep === "mapped" && (
          <div className="flex h-full flex-col">
            <div className="border-b border-gray-700 px-4 py-2" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Step 3: Mapping Applied
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {!result ? (
                <div className="text-center text-sm text-gray-500">
                  Run the pipeline to see mapping results
                </div>
              ) : !result.has_mapping ? (
                <div className="text-center">
                  <div className="text-sm text-amber-400">
                    No mapping definition found for this parser
                  </div>
                  <div className="mt-2 text-xs text-gray-500">
                    Create a mapping in the Mappings tab that references this parser
                  </div>
                </div>
              ) : (
                <div>
                  <div className="mb-4 rounded border border-green-500/20 bg-green-900/10 p-3">
                    <div className="text-sm font-medium text-green-300">
                      Mapping applied successfully
                    </div>
                    <div className="mt-1 text-xs text-gray-400">
                      {result.record_count} records processed, {result.mutation_count} mutations generated
                    </div>
                  </div>
                  {result.mapping_errors.length > 0 && (
                    <div className="mb-4 rounded border border-red-500/20 bg-red-900/10 p-3">
                      <div className="text-sm font-medium text-red-300">Mapping Errors</div>
                      {result.mapping_errors.map((err, i) => (
                        <div key={i} className="mt-1 text-xs text-red-300">{err}</div>
                      ))}
                    </div>
                  )}
                  <pre className="rounded border border-gray-700 bg-gray-900 p-4 text-xs text-gray-300">
                    {JSON.stringify(result.mutations, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Step: Generated Mutations */}
        {activeStep === "mutations" && (
          <div className="flex h-full flex-col">
            <div className="border-b border-gray-700 px-4 py-2" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Step 4: Graph Mutations Preview
                </span>
                {result && (
                  <span className="text-xs text-gray-500">
                    {result.mutation_count} mutation{result.mutation_count !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-4">
              {!result || result.mutations.length === 0 ? (
                <div className="text-center text-sm text-gray-500">
                  {result
                    ? "No mutations generated. Check your mapping definition."
                    : "Run the pipeline to see generated mutations"}
                </div>
              ) : (
                <div className="space-y-3">
                  {result.mutations.map((m, i) => (
                    <div
                      key={i}
                      className="rounded border border-gray-700 bg-gray-900/50 p-3"
                    >
                      <div className="flex items-center gap-2">
                        <MutationIcon operation={m.operation} />
                        <span className="text-sm font-medium text-gray-200">
                          {m.operation === "upsert_node" ? "UPSERT" : "UPSERT EDGE"}
                        </span>
                        <code className="rounded bg-gray-700 px-1.5 py-0.5 text-xs font-medium text-brand-300">
                          {m.node_type || m.edge_type}
                        </code>
                      </div>

                      {m.match_on && Object.keys(m.match_on).length > 0 && (
                        <div className="mt-2">
                          <div className="text-[10px] font-semibold uppercase text-gray-500">Match On</div>
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            {Object.entries(m.match_on).map(([k, v]) => (
                              <span key={k} className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs">
                                <span className="text-amber-300">{k}</span>
                                <span className="text-gray-500"> = </span>
                                <span className="text-gray-300">{String(v)}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.attributes && Object.keys(m.attributes).length > 0 && (
                        <div className="mt-2">
                          <div className="text-[10px] font-semibold uppercase text-gray-500">Attributes</div>
                          <div className="mt-0.5 space-y-0.5">
                            {Object.entries(m.attributes).map(([k, v]) => (
                              <div key={k} className="text-xs">
                                <span className="text-gray-400">{k}:</span>{" "}
                                <span className="font-mono text-gray-200">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.source_match && (
                        <div className="mt-2">
                          <div className="text-[10px] font-semibold uppercase text-gray-500">Source</div>
                          <div className="mt-0.5 space-y-0.5">
                            {Object.entries(m.source_match).map(([k, v]) => (
                              <div key={k} className="text-xs">
                                <span className="text-gray-400">{k}:</span>{" "}
                                <span className="font-mono text-gray-200">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {m.target_match && (
                        <div className="mt-2">
                          <div className="text-[10px] font-semibold uppercase text-gray-500">Target</div>
                          <div className="mt-0.5 space-y-0.5">
                            {Object.entries(m.target_match).map(([k, v]) => (
                              <div key={k} className="text-xs">
                                <span className="text-gray-400">{k}:</span>{" "}
                                <span className="font-mono text-gray-200">{String(v)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {pipelineError && (
          <div className="border-t border-gray-700 px-4 py-3" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
            <div className="rounded bg-red-900/30 px-3 py-2 text-xs text-red-300">
              {pipelineError}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
