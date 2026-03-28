/**
 * ParserRegistryPage — browse, test, and register data parsers.
 * Fetches from GET /parsers, supports testing parsers with raw output.
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";

interface Parser {
  id: string;
  name: string;
  platform: string;
  command: string;
  version: string;
  description?: string;
}

interface ParsedRecord {
  [key: string]: unknown;
}

export function ParserRegistryPage() {
  const [testParserId, setTestParserId] = useState<string | null>(null);
  const [testParserName, setTestParserName] = useState("");
  const [rawInput, setRawInput] = useState("");
  const [showRegisterDialog, setShowRegisterDialog] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["parsers"],
    queryFn: () => api.get<{ data: Parser[] }>("/parsers"),
  });

  const parsers = data?.data?.data || [];

  const testMutation = useMutation({
    mutationFn: ({ parserId, input }: { parserId: string; input: string }) =>
      api.post<{ data: { records: ParsedRecord[] } }>(
        `/parsers/${parserId}/test`,
        { raw_output: input },
      ),
  });

  const testResult = testMutation.data?.data?.data?.records;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Parser Registry
        </h1>
        <button
          onClick={() => setShowRegisterDialog(true)}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Register Parser
        </button>
      </div>

      {/* Register Dialog */}
      {showRegisterDialog && (
        <RegisterParserDialog onClose={() => setShowRegisterDialog(false)} />
      )}

      {/* Test Parser Panel */}
      {testParserId && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Test Parser: {testParserName}
            </h2>
            <button
              onClick={() => {
                setTestParserId(null);
                setRawInput("");
                testMutation.reset();
              }}
              className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              Close
            </button>
          </div>
          <textarea
            value={rawInput}
            onChange={(e) => setRawInput(e.target.value)}
            rows={6}
            className="mb-3 w-full rounded-md border border-gray-300 bg-gray-50 p-3 font-mono text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
            placeholder="Paste raw command output here..."
          />
          <div className="mb-3 flex items-center gap-2">
            <button
              onClick={() =>
                testMutation.mutate({
                  parserId: testParserId,
                  input: rawInput,
                })
              }
              disabled={testMutation.isPending || !rawInput.trim()}
              className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {testMutation.isPending ? "Running..." : "Run Parser"}
            </button>
            {testMutation.isError && (
              <span className="text-sm text-red-500">
                Error: {String(testMutation.error)}
              </span>
            )}
          </div>

          {/* Parsed Results */}
          {testResult && (
            <div className="rounded-md border border-gray-200 dark:border-gray-700">
              <div className="border-b border-gray-200 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-500 dark:border-gray-700 dark:bg-gray-900">
                {testResult.length} record{testResult.length !== 1 ? "s" : ""}{" "}
                parsed
              </div>
              <div className="max-h-80 overflow-auto">
                {testResult.length > 0 &&
                typeof testResult[0] === "object" ? (
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-900">
                      <tr>
                        {Object.keys(testResult[0]).map((key) => (
                          <th
                            key={key}
                            className="px-3 py-2 text-left text-xs font-medium uppercase text-gray-500"
                          >
                            {key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                      {testResult.map((record, i) => (
                        <tr
                          key={i}
                          className="hover:bg-gray-50 dark:hover:bg-gray-700"
                        >
                          {Object.values(record).map((val, j) => (
                            <td
                              key={j}
                              className="px-3 py-2 text-sm text-gray-700 dark:text-gray-300"
                            >
                              {typeof val === "object"
                                ? JSON.stringify(val)
                                : String(val ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <pre className="p-3 text-sm text-gray-700 dark:text-gray-300">
                    {JSON.stringify(testResult, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Parser Table */}
      {isLoading ? (
        <div className="text-gray-500">Loading parsers...</div>
      ) : error ? (
        <div className="text-red-500">Error loading parsers</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Platform
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Command
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Version
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {parsers.map((parser: Parser) => (
                <tr
                  key={parser.id}
                  className="hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">
                    {parser.name}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <PlatformBadge platform={parser.platform} />
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs dark:bg-gray-700">
                      {parser.command}
                    </code>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                    {parser.version}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <button
                      onClick={() => {
                        setTestParserId(parser.id);
                        setTestParserName(parser.name);
                        testMutation.reset();
                        setRawInput("");
                      }}
                      className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
                    >
                      Test Parser
                    </button>
                  </td>
                </tr>
              ))}
              {parsers.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-sm text-gray-500"
                  >
                    No parsers registered.
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

function PlatformBadge({ platform }: { platform: string }) {
  const colorMap: Record<string, string> = {
    cisco_ios:
      "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    cisco_nxos:
      "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    arista_eos:
      "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    juniper_junos:
      "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
    paloalto_panos:
      "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  };

  const classes =
    colorMap[platform] ||
    "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200";

  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}
    >
      {platform}
    </span>
  );
}

function RegisterParserDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState("");
  const [command, setCommand] = useState("");

  const registerMutation = useMutation({
    mutationFn: (data: { name: string; platform: string; command: string }) =>
      api.post("/parsers", data),
    onSuccess: () => onClose(),
  });

  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Register New Parser
        </h2>
        <button
          onClick={onClose}
          className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
        >
          Close
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            placeholder="e.g., show_interfaces"
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Platform
          </label>
          <input
            type="text"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            placeholder="e.g., cisco_ios"
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            Command
          </label>
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            className="rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white"
            placeholder="e.g., show interfaces"
          />
        </div>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
        >
          Cancel
        </button>
        <button
          onClick={() =>
            registerMutation.mutate({ name, platform, command })
          }
          disabled={registerMutation.isPending || !name || !platform || !command}
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
