/**
 * Application shell with sidebar navigation and main content area.
 * Navigation is dynamically generated from the schema registry.
 */

import { useEffect } from "react";
import { Outlet, Link, useLocation } from "react-router-dom";
import { useSchemaStore } from "@/stores/schemaStore";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const { loaded, loading, loadSchema } = useSchemaStore();
  const location = useLocation();

  useEffect(() => {
    if (!loaded && !loading) {
      loadSchema();
    }
  }, [loaded, loading, loadSchema]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-gray-500">Loading schema...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-900">
      {/* Sidebar */}
      <Sidebar />

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-6 dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center gap-4">
            {/* TODO: Breadcrumbs */}
          </div>
          <div className="flex items-center gap-4">
            {/* TODO: Global search */}
            <input
              type="text"
              placeholder="Search..."
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-700"
            />
            {/* TODO: User menu */}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
