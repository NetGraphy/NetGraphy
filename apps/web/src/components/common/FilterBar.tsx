/**
 * FilterBar — schema-driven filter controls for list pages.
 *
 * Reads filterable_fields from the node type's API metadata and
 * renders appropriate input widgets for each field based on its type.
 */

import { useState } from "react";
import { useSchemaStore } from "@/stores/schemaStore";

interface FilterBarProps {
  nodeType: string;
  filters: Record<string, string>;
  onFilterChange: (filters: Record<string, string>) => void;
}

export function FilterBar({ nodeType, filters, onFilterChange }: FilterBarProps) {
  const { getNodeType } = useSchemaStore();
  const typeDef = getNodeType(nodeType);

  const [localFilters, setLocalFilters] = useState<Record<string, string>>(filters);

  if (!typeDef) return null;

  const filterableFields = typeDef.api.filterable_fields || [];
  if (filterableFields.length === 0) return null;

  const filterAttributes = filterableFields
    .map((fieldName) => {
      const attr = typeDef.attributes[fieldName];
      return attr ? { name: fieldName, attr } : null;
    })
    .filter(Boolean) as { name: string; attr: (typeof typeDef.attributes)[string] }[];

  if (filterAttributes.length === 0) return null;

  const handleChange = (field: string, value: string) => {
    setLocalFilters((prev) => {
      const next = { ...prev };
      if (value === "") {
        delete next[field];
      } else {
        next[field] = value;
      }
      return next;
    });
  };

  const handleApply = () => {
    onFilterChange(localFilters);
  };

  const handleClear = () => {
    setLocalFilters({});
    onFilterChange({});
  };

  const hasActiveFilters = Object.keys(localFilters).length > 0;

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-800">
      {filterAttributes.map(({ name, attr }) => (
        <div key={name} className="flex flex-col">
          <label className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
            {attr.description || name}
          </label>
          <FilterInput
            attribute={attr}
            value={localFilters[name] || ""}
            onChange={(value) => handleChange(name, value)}
          />
        </div>
      ))}

      <div className="flex gap-2">
        <button
          onClick={handleApply}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
        >
          Apply
        </button>
        {hasActiveFilters && (
          <button
            onClick={handleClear}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

function FilterInput({
  attribute,
  value,
  onChange,
}: {
  attribute: { type: string; enum_values?: string[] | null };
  value: string;
  onChange: (value: string) => void;
}) {
  const baseClass =
    "rounded-md border border-gray-300 px-2.5 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white";

  switch (attribute.type) {
    case "enum":
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={baseClass}
        >
          <option value="">All</option>
          {attribute.enum_values?.map((v) => (
            <option key={v} value={v}>
              {v.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      );

    case "boolean":
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={baseClass}
        >
          <option value="">All</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      );

    case "integer":
    case "float":
      return (
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Filter..."
          className={`${baseClass} w-28`}
        />
      );

    default:
      return (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Filter..."
          className={`${baseClass} w-40`}
        />
      );
  }
}
