/**
 * SchemaValidatorPage — paste YAML schema definitions and validate them
 * against the schema engine rules and live registry cross-references.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";

const SAMPLE_NODE = `kind: NodeType
version: v1
metadata:
  name: MyNewType
  display_name: My New Type
  description: "A custom node type"
  icon: box
  color: "#3B82F6"
  category: Infrastructure
  tags: [custom]

attributes:
  name:
    type: string
    display_name: Name
    required: true
    unique: true
    indexed: true
    max_length: 255
    description: "Display name"
    ui:
      list_column: true
      list_column_order: 1
      search_weight: 10
      form_order: 1

  status:
    type: enum
    display_name: Status
    enum_values: [active, planned, decommissioned]
    default: active
    required: true
    ui:
      list_column: true
      list_column_order: 2
      form_order: 2
      filter: true
      badge_colors:
        active: green
        planned: blue
        decommissioned: red

  description:
    type: text
    display_name: Description
    required: false
    ui:
      form_order: 10
      form_widget: textarea

mixins:
  - lifecycle_mixin

search:
  enabled: true
  primary_field: name
  search_fields: [name, description]

graph:
  default_label_field: name

api:
  plural_name: my-new-types
  filterable_fields: [name, status]
  sortable_fields: [name, status]
  default_sort: name

permissions:
  default_read: authenticated
  default_write: editor
  default_delete: admin`;

const SAMPLE_EDGE = `kind: EdgeType
version: v1
metadata:
  name: MY_EDGE
  display_name: "My Edge"
  description: "A relationship between two types"
  category: Infrastructure

source:
  node_types: [Device]

target:
  node_types: [Location]

cardinality: many_to_one
inverse_name: HAS_MY_THING

graph:
  style: solid
  color: "#3B82F6"
  show_label: false

api:
  exposed: true`;

interface ValidationResult {
  valid: boolean;
  warnings: string[];
  errors: string[];
  document_count?: number;
}

export function SchemaValidatorPage() {
  const [yaml, setYaml] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);

  const validateMutation = useMutation({
    mutationFn: async (yamlText: string) => {
      const resp = await api.post("/schema/validate-yaml", { yaml: yamlText });
      return resp.data.data as ValidationResult;
    },
    onSuccess: (data) => setResult(data),
    onError: (err: unknown) => {
      const message =
        err &&
        typeof err === "object" &&
        "response" in err &&
        (err as { response?: { data?: { error?: { message?: string } } } })
          .response?.data?.error?.message;
      setResult({
        valid: false,
        warnings: [],
        errors: [message || "Validation request failed"],
      });
    },
  });

  const handleValidate = () => {
    if (!yaml.trim()) return;
    setResult(null);
    validateMutation.mutate(yaml);
  };

  const loadSample = (sample: string) => {
    setYaml(sample);
    setResult(null);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Schema Validator</h1>
          <p className="mt-1 text-sm text-gray-500">
            Paste a YAML schema definition to validate structure, attribute
            types, and cross-references against the live registry.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => loadSample(SAMPLE_NODE)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Sample Node Type
          </button>
          <button
            onClick={() => loadSample(SAMPLE_EDGE)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Sample Edge Type
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Editor */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            Schema YAML (supports multi-document with ---)
          </label>
          <textarea
            value={yaml}
            onChange={(e) => {
              setYaml(e.target.value);
              setResult(null);
            }}
            rows={28}
            spellCheck={false}
            className="w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 font-mono text-sm leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            placeholder="Paste your schema YAML here..."
          />
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleValidate}
              disabled={!yaml.trim() || validateMutation.isPending}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {validateMutation.isPending ? "Validating..." : "Validate Schema"}
            </button>
            {yaml.trim() && (
              <button
                onClick={() => {
                  setYaml("");
                  setResult(null);
                }}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Results */}
        <div>
          {result ? (
            <div className="space-y-4">
              {/* Status banner */}
              <div
                className={`rounded-lg border px-4 py-3 ${
                  result.valid
                    ? "border-green-200 bg-green-50 text-green-800"
                    : "border-red-200 bg-red-50 text-red-800"
                }`}
              >
                <div className="flex items-center gap-2">
                  {result.valid ? (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  ) : (
                    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  )}
                  <span className="font-medium">
                    {result.valid ? "Schema is valid" : "Schema has errors"}
                  </span>
                  {result.document_count !== undefined && (
                    <span className="text-sm opacity-75">
                      ({result.document_count} document{result.document_count !== 1 ? "s" : ""})
                    </span>
                  )}
                </div>
              </div>

              {/* Errors */}
              {result.errors.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-white">
                  <div className="border-b border-red-100 px-4 py-2">
                    <h3 className="text-sm font-medium text-red-700">
                      Errors ({result.errors.length})
                    </h3>
                  </div>
                  <ul className="divide-y divide-red-50">
                    {result.errors.map((err, i) => (
                      <li key={i} className="flex items-start gap-2 px-4 py-2 text-sm text-red-700">
                        <span className="mt-0.5 flex-shrink-0 text-red-400">&times;</span>
                        <span className="font-mono text-xs">{err}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Warnings */}
              {result.warnings.length > 0 && (
                <div className="rounded-lg border border-yellow-200 bg-white">
                  <div className="border-b border-yellow-100 px-4 py-2">
                    <h3 className="text-sm font-medium text-yellow-700">
                      Warnings ({result.warnings.length})
                    </h3>
                  </div>
                  <ul className="divide-y divide-yellow-50">
                    {result.warnings.map((warn, i) => (
                      <li key={i} className="flex items-start gap-2 px-4 py-2 text-sm text-yellow-700">
                        <span className="mt-0.5 flex-shrink-0">&#9888;</span>
                        <span className="font-mono text-xs">{warn}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* All clear */}
              {result.valid && result.warnings.length === 0 && (
                <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
                  No errors or warnings. This schema definition is ready to be
                  added to the <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">schemas/</code> directory
                  and deployed.
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border-2 border-dashed border-gray-200 py-20">
              <div className="text-center text-gray-400">
                <svg className="mx-auto mb-3 h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                </svg>
                <p className="text-sm font-medium">Paste YAML and click Validate</p>
                <p className="mt-1 text-xs">
                  Checks structure, attribute types, cross-references, and best practices
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
