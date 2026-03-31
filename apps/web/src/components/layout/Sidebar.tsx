/**
 * Sidebar navigation — dynamically generated from schema categories.
 *
 * Node types are grouped by their 'category' field. Special sections
 * (Query, Parsers, Jobs, Admin) are hardcoded.
 */

import { Link, useLocation } from "react-router-dom";
import { useSchemaStore } from "@/stores/schemaStore";

const SPECIAL_SECTIONS = [
  {
    title: "Development",
    items: [
      { label: "Dev Workbench", path: "/dev" },
      { label: "Schema Designer", path: "/schema-designer" },
      { label: "Cypher Builder", path: "/query/builder" },
      { label: "Query Workbench", path: "/query" },
      { label: "Report Builder", path: "/reports" },
      { label: "Graph Explorer", path: "/graph" },
    ],
  },
  {
    title: "Infrastructure as Code",
    items: [
      { label: "IaC Dashboard", path: "/iac" },
      { label: "Config Profiles", path: "/objects/ConfigProfile" },
      { label: "Compliance Features", path: "/objects/ComplianceFeature" },
      { label: "Compliance Rules", path: "/objects/ComplianceRule" },
      { label: "Compliance Results", path: "/objects/ComplianceResult" },
      { label: "Config Contexts", path: "/objects/ConfigContext" },
      { label: "Transformations", path: "/objects/TransformationMapping" },
    ],
  },
  {
    title: "Automation",
    items: [
      { label: "Jobs", path: "/jobs" },
      { label: "Parsers", path: "/parsers" },
      { label: "Jinja2 Filters", path: "/filters" },
      { label: "Ingestion Runs", path: "/ingestion" },
    ],
  },
  {
    title: "Administration",
    items: [
      { label: "Users & Groups", path: "/admin/users" },
      { label: "AI Configuration", path: "/admin/ai" },
      { label: "Generated Artifacts", path: "/admin/generated" },
      { label: "Schema Explorer", path: "/schema" },
      { label: "Schema Validator", path: "/admin/schema-validator" },
      { label: "Git Sources", path: "/git-sources" },
      { label: "Audit Log", path: "/admin/audit" },
    ],
  },
];

export function Sidebar() {
  const { categories, nodeTypes } = useSchemaStore();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <aside className="flex w-60 flex-col border-r border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      {/* Logo */}
      <div className="flex h-14 items-center border-b border-gray-200 px-4 dark:border-gray-700">
        <Link to="/" className="text-lg font-bold text-brand-600">
          NetGraphy
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {/* Dashboard & Docs */}
        <Link
          to="/"
          className={`mb-1 block rounded-md px-3 py-2 text-sm font-medium ${
            isActive("/")
              ? "bg-brand-50 text-brand-700"
              : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
          }`}
        >
          Dashboard
        </Link>
        <Link
          to="/docs"
          className={`mb-4 block rounded-md px-3 py-2 text-sm font-medium ${
            isActive("/docs")
              ? "bg-brand-50 text-brand-700"
              : "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
          }`}
        >
          Documentation
        </Link>

        {/* Dynamic categories from schema */}
        {categories.map((category) => (
          <div key={category.name} className="mb-4">
            <h3 className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              {category.name}
            </h3>
            {category.node_types.map((typeName) => {
              const nt = nodeTypes[typeName];
              const displayName =
                nt?.metadata.display_name || typeName;
              const path = `/objects/${typeName}`;
              return (
                <Link
                  key={typeName}
                  to={path}
                  className={`block rounded-md px-3 py-1.5 text-sm ${
                    location.pathname.startsWith(path)
                      ? "bg-brand-50 text-brand-700"
                      : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
                  }`}
                >
                  {displayName}
                </Link>
              );
            })}
          </div>
        ))}

        {/* Special sections */}
        {SPECIAL_SECTIONS.map((section) => (
          <div key={section.title} className="mb-4">
            <h3 className="mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              {section.title}
            </h3>
            {section.items.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`block rounded-md px-3 py-1.5 text-sm ${
                  isActive(item.path)
                    ? "bg-brand-50 text-brand-700"
                    : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}
