/**
 * Sidebar navigation — dynamically generated from schema categories.
 *
 * Node types are grouped by their 'category' field. Special sections
 * (Query, Parsers, Jobs, Admin) are hardcoded.
 */

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
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
      { label: "Architecture Viewer", path: "/architecture" },
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
  const sectionKeys = useMemo(
    () => [
      ...categories.map((category) => `schema:${category.name}`),
      ...SPECIAL_SECTIONS.map((section) => `special:${section.title}`),
    ],
    [categories],
  );
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    () => new Set(),
  );

  const isActive = (path: string) => location.pathname === path;
  const isObjectActive = (typeName: string) =>
    location.pathname.startsWith(`/objects/${typeName}`);
  const isSpecialActive = (path: string) =>
    location.pathname === path || location.pathname.startsWith(`${path}/`);

  useEffect(() => {
    const activeSections = new Set<string>();

    for (const category of categories) {
      if (category.node_types.some((typeName) => isObjectActive(typeName))) {
        activeSections.add(`schema:${category.name}`);
      }
    }

    for (const section of SPECIAL_SECTIONS) {
      if (section.items.some((item) => isSpecialActive(item.path))) {
        activeSections.add(`special:${section.title}`);
      }
    }

    if (activeSections.size > 0) {
      setExpandedSections((current) => {
        const next = new Set(current);
        for (const key of activeSections) {
          next.add(key);
        }
        return next;
      });
    }
  }, [categories, location.pathname]);

  const toggleSection = (key: string) => {
    setExpandedSections((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const expandAll = () => setExpandedSections(new Set(sectionKeys));
  const collapseAll = () => setExpandedSections(new Set());

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

        <div className="mb-3 flex items-center justify-between px-3 text-[11px] font-medium uppercase tracking-wider text-gray-400">
          <span>Browse</span>
          <div className="flex items-center gap-2 normal-case tracking-normal">
            <button
              type="button"
              onClick={expandAll}
              className="text-gray-500 hover:text-brand-700 dark:text-gray-400 dark:hover:text-brand-300"
            >
              Expand
            </button>
            <button
              type="button"
              onClick={collapseAll}
              className="text-gray-500 hover:text-brand-700 dark:text-gray-400 dark:hover:text-brand-300"
            >
              Collapse
            </button>
          </div>
        </div>

        {/* Dynamic categories from schema */}
        {categories.map((category) => {
          const key = `schema:${category.name}`;
          const isExpanded = expandedSections.has(key);
          const hasActiveItem = category.node_types.some((typeName) =>
            isObjectActive(typeName),
          );

          return (
            <SidebarSection
              key={category.name}
              title={category.name}
              count={category.node_types.length}
              expanded={isExpanded}
              active={hasActiveItem}
              onToggle={() => toggleSection(key)}
            >
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
                      isObjectActive(typeName)
                        ? "bg-brand-50 text-brand-700"
                        : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
                    }`}
                  >
                    {displayName}
                  </Link>
                );
              })}
            </SidebarSection>
          );
        })}

        {/* Special sections */}
        {SPECIAL_SECTIONS.map((section) => {
          const key = `special:${section.title}`;
          const isExpanded = expandedSections.has(key);
          const hasActiveItem = section.items.some((item) =>
            isSpecialActive(item.path),
          );

          return (
            <SidebarSection
              key={section.title}
              title={section.title}
              count={section.items.length}
              expanded={isExpanded}
              active={hasActiveItem}
              onToggle={() => toggleSection(key)}
            >
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
            </SidebarSection>
          );
        })}
      </nav>
    </aside>
  );
}

interface SidebarSectionProps {
  title: string;
  count: number;
  expanded: boolean;
  active: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function SidebarSection({
  title,
  count,
  expanded,
  active,
  onToggle,
  children,
}: SidebarSectionProps) {
  const Icon = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="mb-1">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider transition-colors ${
          active
            ? "bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
            : "text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
        }`}
      >
        <Icon className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-500 dark:bg-gray-700 dark:text-gray-300">
          {count}
        </span>
      </button>
      {expanded && <div className="mt-1 space-y-0.5 pl-5">{children}</div>}
    </div>
  );
}
