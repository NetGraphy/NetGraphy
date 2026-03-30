/**
 * ParserPane — TextFSM parser development IDE.
 *
 * Left: Parser list (registered parsers)
 * Center: TextFSM template editor (Monaco) + metadata
 * Bottom: Test panel — paste command output, see parsed records
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Editor from "@monaco-editor/react";
import { api } from "@/api/client";

interface Parser {
  id: string;
  name: string;
  platform: string;
  command: string;
  template: string;
  description?: string;
  version?: string;
  managed_by?: string;
}

const PLATFORMS = [
  "cisco_ios",
  "cisco_nxos",
  "cisco_iosxe",
  "cisco_iosxr",
  "arista_eos",
  "juniper_junos",
  "paloalto_panos",
  "linux",
  "f5_tmsh",
  "other",
];

const PLATFORM_COLORS: Record<string, string> = {
  cisco_ios: "bg-blue-500/20 text-blue-300",
  cisco_nxos: "bg-blue-500/20 text-blue-300",
  cisco_iosxe: "bg-blue-500/20 text-blue-300",
  cisco_iosxr: "bg-blue-500/20 text-blue-300",
  arista_eos: "bg-green-500/20 text-green-300",
  juniper_junos: "bg-purple-500/20 text-purple-300",
  paloalto_panos: "bg-orange-500/20 text-orange-300",
  linux: "bg-gray-500/20 text-gray-300",
  f5_tmsh: "bg-red-500/20 text-red-300",
};

const SAMPLE_TEMPLATE = `Value HOSTNAME (\\S+)
Value VERSION ([\\d.]+\\S*)
Value SERIAL (\\S+)
Value HARDWARE (\\S+)
Value UPTIME (.+)

Start
  ^\\s*${HOSTNAME}\\s+uptime\\s+is\\s+${UPTIME} -> Continue
  ^.*Version\\s+${VERSION} -> Continue
  ^.*[Pp]rocessor\\s+board\\s+ID\\s+${SERIAL} -> Continue
  ^.*cisco\\s+${HARDWARE}\\s+ -> Continue
  ^\\s*$$
`;

const SAMPLE_OUTPUT = `Cisco IOS Software, ISR Software (X86_64_LINUX_IOSD-UNIVERSALK9-M), Version 16.09.01, RELEASE SOFTWARE (fc2)

router1 uptime is 2 weeks, 3 days, 14 hours, 22 minutes
System returned to ROM by reload at 12:30:22 UTC Wed Mar 1 2026

System image file is "bootflash:isr4400-universalk9.16.09.01.SPA.bin"

cisco ISR4431/K9 (1RU) processor with 3670016K/6147K bytes of memory.
Processor board ID FDO2145A0BC
4 Gigabit Ethernet interfaces
32768K bytes of non-volatile configuration memory.
`;

export function ParserPane() {
  const queryClient = useQueryClient();

  // Editor state
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("cisco_ios");
  const [command, setCommand] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);

  // Test state
  const [rawInput, setRawInput] = useState("");
  const [testResults, setTestResults] = useState<Record<string, unknown>[] | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [showRawInput, setShowRawInput] = useState(true);

  // UI state
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [explorerFilter, setExplorerFilter] = useState("");

  // Queries
  const { data: parsersData } = useQuery({
    queryKey: ["parsers"],
    queryFn: () => api.get("/parsers"),
  });
  const parsers: Parser[] = parsersData?.data?.data || [];

  // Mutations
  const saveMutation = useMutation({
    mutationFn: () =>
      api.post("/parsers", { name, platform, command, template, description }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parsers"] });
      setSaveError(null);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : JSON.stringify(detail) || "Save failed");
    },
  });

  const testMutation = useMutation({
    mutationFn: () => {
      const id = editingId || name;
      return api.post(`/parsers/${id}/test`, {
        raw_output: rawInput,
        template: template || undefined,
      });
    },
    onSuccess: (resp) => {
      const d = resp.data.data;
      setTestResults(d.parsed_records || d.records || []);
      setTestError(null);
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setTestError(typeof detail === "string" ? detail : "Parse error");
      setTestResults(null);
    },
  });

  const loadParser = (p: Parser) => {
    setName(p.name);
    setPlatform(p.platform);
    setCommand(p.command);
    setDescription(p.description || "");
    setTemplate(p.template || "");
    setEditingId(p.id);
    setSaveError(null);
    setSaveSuccess(false);
    setTestResults(null);
    setTestError(null);
  };

  const newParser = () => {
    setName("");
    setPlatform("cisco_ios");
    setCommand("");
    setDescription("");
    setTemplate("");
    setEditingId(null);
    setSaveError(null);
    setTestResults(null);
    setTestError(null);
  };

  const loadSample = () => {
    setName("cisco_ios_show_version");
    setPlatform("cisco_ios");
    setCommand("show version");
    setDescription("Parse Cisco IOS show version output");
    setTemplate(SAMPLE_TEMPLATE);
    setRawInput(SAMPLE_OUTPUT);
    setEditingId(null);
  };

  const filteredParsers = parsers.filter(
    (p) =>
      !explorerFilter ||
      p.name.toLowerCase().includes(explorerFilter.toLowerCase()) ||
      p.platform.toLowerCase().includes(explorerFilter.toLowerCase()) ||
      p.command.toLowerCase().includes(explorerFilter.toLowerCase()),
  );

  // Group parsers by platform
  const grouped = filteredParsers.reduce<Record<string, Parser[]>>((acc, p) => {
    const key = p.platform || "other";
    if (!acc[key]) acc[key] = [];
    acc[key].push(p);
    return acc;
  }, {});

  return (
    <div className="flex h-full">
      {/* ---- Left: Parser Explorer ---- */}
      <div className="flex w-64 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800">
        <div className="flex items-center justify-between border-b border-gray-700 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Parsers
          </span>
          <div className="flex gap-1">
            <button
              onClick={loadSample}
              className="rounded px-1.5 py-0.5 text-xs text-gray-400 hover:bg-gray-700 hover:text-gray-200"
            >
              Sample
            </button>
            <button
              onClick={newParser}
              className="rounded bg-brand-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-brand-500"
            >
              + New
            </button>
          </div>
        </div>

        <div className="border-b border-gray-700 px-3 py-2">
          <input
            type="text"
            value={explorerFilter}
            onChange={(e) => setExplorerFilter(e.target.value)}
            placeholder="Search parsers..."
            className="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200 placeholder-gray-500 focus:border-brand-500 focus:outline-none"
          />
        </div>

        <div className="flex-1 overflow-y-auto">
          {Object.entries(grouped).map(([platform, items]) => (
            <div key={platform} className="mt-1">
              <div className="flex items-center gap-1.5 px-3 py-1.5">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${PLATFORM_COLORS[platform] || "bg-gray-500/20 text-gray-300"}`}>
                  {platform}
                </span>
                <span className="text-[10px] text-gray-500">{items.length}</span>
              </div>
              <div className="space-y-0.5 px-1">
                {items.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => loadParser(p)}
                    className={`flex w-full flex-col rounded px-2 py-1.5 text-left ${
                      editingId === p.id
                        ? "bg-brand-600/20 text-brand-300"
                        : "text-gray-300 hover:bg-gray-700"
                    }`}
                  >
                    <div className="truncate text-sm font-medium">{p.name}</div>
                    <div className="truncate text-xs text-gray-500">
                      <code>{p.command}</code>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
          {filteredParsers.length === 0 && (
            <div className="px-3 py-4 text-center text-xs text-gray-500">
              No parsers registered
            </div>
          )}
        </div>
      </div>

      {/* ---- Center: Editor ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Metadata */}
        <div className="flex items-center gap-3 border-b border-gray-700 px-4 py-3" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <div className="flex-1">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">Parser Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="cisco_ios_show_version"
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
            />
          </div>
          <div className="w-44">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">Platform</label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 text-sm text-gray-200 focus:border-brand-500 focus:outline-none"
            >
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">Command</label>
            <input
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="show version"
              className="w-full rounded border border-gray-600 bg-gray-900 px-2.5 py-1.5 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
            />
          </div>
        </div>

        {/* TextFSM Template Editor */}
        <div className="relative min-h-0 flex-1">
          <div className="absolute right-3 top-2 z-10 flex gap-2">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!name || !template || saveMutation.isPending}
              className="rounded bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-500 disabled:opacity-40"
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>

          {saveError && (
            <div className="absolute left-3 top-2 z-10 rounded bg-red-900/80 px-2 py-1 text-xs text-red-200">
              {saveError}
            </div>
          )}
          {saveSuccess && (
            <div className="absolute left-3 top-2 z-10 rounded bg-green-900/80 px-2 py-1 text-xs text-green-200">
              Parser saved
            </div>
          )}

          <Editor
            height="100%"
            language="plaintext"
            theme="vs-dark"
            value={template}
            onChange={(v) => setTemplate(v || "")}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 2,
              automaticLayout: true,
              padding: { top: 8, bottom: 8 },
            }}
          />
        </div>

        {/* ---- Bottom: Test Panel ---- */}
        <div className="border-t border-gray-700" style={{ backgroundColor: "rgb(30, 33, 40)" }}>
          <div className="flex items-center justify-between border-b border-gray-700/50 px-4 py-1.5">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Test Parser
              </span>
              <button
                onClick={() => setShowRawInput(!showRawInput)}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                {showRawInput ? "Hide Input" : "Show Input"}
              </button>
            </div>
            <button
              onClick={() => testMutation.mutate()}
              disabled={!rawInput || testMutation.isPending}
              className="rounded bg-emerald-600 px-4 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-40"
            >
              {testMutation.isPending ? "Parsing..." : "Run Parser"}
            </button>
          </div>

          {showRawInput && (
            <div className="border-b border-gray-700/50 px-4 py-2">
              <label className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Raw Command Output
              </label>
              <textarea
                value={rawInput}
                onChange={(e) => setRawInput(e.target.value)}
                rows={5}
                placeholder="Paste raw command output here..."
                className="w-full rounded border border-gray-600 bg-gray-900 p-2 font-mono text-xs text-gray-200 placeholder-gray-600 focus:border-brand-500 focus:outline-none"
              />
            </div>
          )}

          {/* Parsed results */}
          {testError && (
            <div className="px-4 py-2">
              <div className="rounded bg-red-900/30 px-3 py-2 text-xs text-red-300">{testError}</div>
            </div>
          )}

          {testResults && (
            <div className="max-h-48 overflow-auto px-4 py-2">
              <div className="mb-1 text-xs text-gray-500">
                {testResults.length} record{testResults.length !== 1 ? "s" : ""} parsed
              </div>
              {testResults.length > 0 && typeof testResults[0] === "object" ? (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-700">
                      {Object.keys(testResults[0]).map((key) => (
                        <th key={key} className="px-2 py-1 text-left font-semibold uppercase text-gray-400">
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {testResults.map((row, i) => (
                      <tr key={i} className="border-b border-gray-700/50 hover:bg-gray-800">
                        {Object.values(row).map((val, j) => (
                          <td key={j} className="px-2 py-1 font-mono text-gray-300">
                            {typeof val === "object" ? JSON.stringify(val) : String(val ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <pre className="text-xs text-gray-300">{JSON.stringify(testResults, null, 2)}</pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
