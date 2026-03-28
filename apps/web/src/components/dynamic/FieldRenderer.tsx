/**
 * FieldRenderer — the component registry that maps attribute types
 * to appropriate display and edit components.
 *
 * This is the heart of the dynamic UI system. Given an attribute definition
 * and a value, it renders the right widget for display or editing.
 */

import type { AttributeDefinition } from "@/types/schema";

interface FieldRendererProps {
  value: unknown;
  attribute: AttributeDefinition;
  mode: "display" | "edit";
  onChange?: (value: unknown) => void;
}

export function FieldRenderer({
  value,
  attribute,
  mode,
  onChange,
}: FieldRendererProps) {
  if (mode === "display") {
    return <DisplayField value={value} attribute={attribute} />;
  }
  return <EditField value={value} attribute={attribute} onChange={onChange} />;
}

// --- Display Renderers ---

function DisplayField({
  value,
  attribute,
}: {
  value: unknown;
  attribute: AttributeDefinition;
}) {
  if (value === null || value === undefined) {
    return <span className="text-gray-400">&mdash;</span>;
  }

  switch (attribute.type) {
    case "boolean":
      return (
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
            value ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
          }`}
        >
          {value ? "Yes" : "No"}
        </span>
      );

    case "enum":
      return <EnumBadge value={String(value)} attribute={attribute} />;

    case "datetime":
    case "date":
      return (
        <span className="text-gray-900 dark:text-gray-100">
          {new Date(String(value)).toLocaleString()}
        </span>
      );

    case "ip_address":
    case "cidr":
      return (
        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-sm dark:bg-gray-700">
          {String(value)}
        </code>
      );

    case "mac_address":
      return (
        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-sm dark:bg-gray-700">
          {String(value)}
        </code>
      );

    case "url":
      return (
        <a
          href={String(value)}
          target="_blank"
          rel="noreferrer"
          className="text-brand-600 hover:underline"
        >
          {String(value)}
        </a>
      );

    case "json":
      return (
        <pre className="max-h-40 overflow-auto rounded bg-gray-100 p-2 text-xs dark:bg-gray-700">
          {JSON.stringify(value, null, 2)}
        </pre>
      );

    case "list[string]":
    case "list[integer]":
      return (
        <div className="flex flex-wrap gap-1">
          {(value as unknown[]).map((v, i) => (
            <span
              key={i}
              className="rounded bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-700"
            >
              {String(v)}
            </span>
          ))}
        </div>
      );

    default:
      return (
        <span className="text-gray-900 dark:text-gray-100">
          {String(value)}
        </span>
      );
  }
}

function EnumBadge({
  value,
  attribute,
}: {
  value: string;
  attribute: AttributeDefinition;
}) {
  const colorMap = attribute.ui.badge_colors || {};
  const color = colorMap[value] || "gray";

  const colorClasses: Record<string, string> = {
    green: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
    red: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    yellow: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
    blue: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    orange: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
    purple: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
    gray: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  };

  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colorClasses[color] || colorClasses.gray}`}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

// --- Edit Renderers ---

function EditField({
  value,
  attribute,
  onChange,
}: {
  value: unknown;
  attribute: AttributeDefinition;
  onChange?: (value: unknown) => void;
}) {
  const baseClass =
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700";

  switch (attribute.type) {
    case "boolean":
      return (
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange?.(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300"
        />
      );

    case "enum":
      return (
        <select
          value={String(value || "")}
          onChange={(e) => onChange?.(e.target.value)}
          className={baseClass}
        >
          <option value="">Select...</option>
          {attribute.enum_values?.map((v) => (
            <option key={v} value={v}>
              {v.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      );

    case "integer":
      return (
        <input
          type="number"
          value={value !== undefined ? Number(value) : ""}
          onChange={(e) => onChange?.(parseInt(e.target.value, 10))}
          className={baseClass}
        />
      );

    case "float":
      return (
        <input
          type="number"
          step="any"
          value={value !== undefined ? Number(value) : ""}
          onChange={(e) => onChange?.(parseFloat(e.target.value))}
          className={baseClass}
        />
      );

    case "text":
      return attribute.ui.form_widget === "textarea" ? (
        <textarea
          value={String(value || "")}
          onChange={(e) => onChange?.(e.target.value)}
          rows={4}
          className={baseClass}
        />
      ) : (
        <input
          type="text"
          value={String(value || "")}
          onChange={(e) => onChange?.(e.target.value)}
          className={baseClass}
        />
      );

    case "datetime":
    case "date":
      return (
        <input
          type={attribute.type === "date" ? "date" : "datetime-local"}
          value={String(value || "")}
          onChange={(e) => onChange?.(e.target.value)}
          className={baseClass}
        />
      );

    default:
      return (
        <input
          type="text"
          value={String(value || "")}
          onChange={(e) => onChange?.(e.target.value)}
          className={baseClass}
          placeholder={attribute.description || undefined}
        />
      );
  }
}
