/**
 * DevWorkbenchPage — Full-screen IDE for developing and testing ingestion components.
 *
 * Tabs:
 *   - Filters: Custom Jinja2 filter development with Monaco editor + test runner
 *   - Parsers: TextFSM parser development with command output testing
 *   - Mappings: YAML mapping editor with template preview
 *   - Pipeline: End-to-end parse -> map -> graph mutation preview
 *   - Models: Data model explorer with fields, relationships, and mapping reference
 */

import { useState } from "react";
import { FilterPane } from "@/components/dev-workbench/FilterPane";
import { ParserPane } from "@/components/dev-workbench/ParserPane";
import { MappingPane } from "@/components/dev-workbench/MappingPane";
import { PipelinePane } from "@/components/dev-workbench/PipelinePane";
import { ModelPane } from "@/components/dev-workbench/ModelPane";

type WorkbenchTab = "filters" | "parsers" | "mappings" | "pipeline" | "models";

const TABS: { id: WorkbenchTab; label: string; icon: string }[] = [
  { id: "filters", label: "Filters", icon: "funnel" },
  { id: "parsers", label: "Parsers", icon: "code" },
  { id: "mappings", label: "Mappings", icon: "arrows" },
  { id: "pipeline", label: "Pipeline", icon: "play" },
  { id: "models", label: "Models", icon: "cube" },
];

function TabIcon({ icon }: { icon: string }) {
  switch (icon) {
    case "funnel":
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
        </svg>
      );
    case "code":
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
      );
    case "arrows":
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
        </svg>
      );
    case "play":
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
    case "cube":
      return (
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
        </svg>
      );
    default:
      return null;
  }
}

export function DevWorkbenchPage() {
  const [activeTab, setActiveTab] = useState<WorkbenchTab>("filters");

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] flex-col bg-gray-900">
      {/* Tab Bar */}
      <div className="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-2">
        <div className="flex items-center">
          <div className="flex items-center gap-1.5 px-3 py-2">
            <svg className="h-5 w-5 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span className="text-sm font-semibold text-gray-200">Dev Workbench</span>
          </div>
          <div className="flex">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? "border-brand-400 text-brand-300"
                    : "border-transparent text-gray-400 hover:border-gray-600 hover:text-gray-200"
                }`}
              >
                <TabIcon icon={tab.icon} />
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 pr-2">
          <span className="text-xs text-gray-500">Ctrl+S to save</span>
        </div>
      </div>

      {/* Tab Content */}
      <div className="min-h-0 flex-1">
        {activeTab === "filters" && <FilterPane />}
        {activeTab === "parsers" && <ParserPane />}
        {activeTab === "mappings" && <MappingPane />}
        {activeTab === "pipeline" && <PipelinePane />}
        {activeTab === "models" && <ModelPane />}
      </div>
    </div>
  );
}
