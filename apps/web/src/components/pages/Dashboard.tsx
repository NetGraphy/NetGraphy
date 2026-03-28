/**
 * Dashboard — landing page with summary cards and quick actions.
 */

import { Link } from "react-router-dom";
import { useSchemaStore } from "@/stores/schemaStore";

export function Dashboard() {
  const { nodeTypes, categories } = useSchemaStore();
  const typeCount = Object.keys(nodeTypes).length;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-gray-900 dark:text-white">
        Dashboard
      </h1>

      {/* Summary cards */}
      <div className="mb-8 grid grid-cols-4 gap-4">
        <SummaryCard title="Node Types" value={typeCount} color="blue" />
        <SummaryCard title="Categories" value={categories.length} color="green" />
        {/* TODO: Live counts from API */}
        <SummaryCard title="Active Devices" value="--" color="emerald" />
        <SummaryCard title="Recent Jobs" value="--" color="purple" />
      </div>

      {/* Quick links */}
      <div className="mb-8">
        <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
          Quick Actions
        </h2>
        <div className="grid grid-cols-3 gap-4">
          <QuickLink title="Query Workbench" description="Execute Cypher queries" path="/query" />
          <QuickLink title="Schema Explorer" description="Browse the data model" path="/schema" />
          <QuickLink title="Create Device" description="Add a new device" path="/objects/Device/new" />
        </div>
      </div>

      {/* Recent activity - placeholder */}
      <div>
        <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
          Recent Activity
        </h2>
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800">
          Activity feed will appear here once the audit system is connected.
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  title,
  value,
  color,
}: {
  title: string;
  value: number | string;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <p className="text-sm text-gray-500 dark:text-gray-400">{title}</p>
      <p className="mt-1 text-2xl font-bold text-gray-900 dark:text-white">
        {value}
      </p>
    </div>
  );
}

function QuickLink({
  title,
  description,
  path,
}: {
  title: string;
  description: string;
  path: string;
}) {
  return (
    <Link
      to={path}
      className="rounded-lg border border-gray-200 bg-white p-4 hover:border-brand-300 hover:shadow-sm dark:border-gray-700 dark:bg-gray-800"
    >
      <h3 className="font-medium text-gray-900 dark:text-white">{title}</h3>
      <p className="mt-1 text-sm text-gray-500">{description}</p>
    </Link>
  );
}
