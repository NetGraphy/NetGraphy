import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/common/ProtectedRoute";
import { LoginPage } from "@/components/pages/LoginPage";
import { Dashboard } from "@/components/pages/Dashboard";
import { DynamicListPage } from "@/components/dynamic/DynamicListPage";
import { DynamicDetailPage } from "@/components/dynamic/DynamicDetailPage";
import { DynamicFormPage } from "@/components/dynamic/DynamicFormPage";
import { QueryWorkbench } from "@/components/query/QueryWorkbench";
import { SchemaExplorer } from "@/components/pages/SchemaExplorer";
import { AuditLogPage } from "@/components/pages/AuditLogPage";
import { PlaceholderPage } from "@/components/pages/PlaceholderPage";
import { ParserRegistryPage } from "@/components/pages/ParserRegistryPage";
import { JobRegistryPage } from "@/components/pages/JobRegistryPage";
import { GitSourcesPage } from "@/components/pages/GitSourcesPage";
import { GraphExplorerPage } from "@/components/pages/GraphExplorerPage";
import { SchemaValidatorPage } from "@/components/pages/SchemaValidatorPage";
import { FilterEditorPage } from "@/components/pages/FilterEditorPage";
import { DevWorkbenchPage } from "@/components/pages/DevWorkbenchPage";
import { IaCDashboardPage } from "@/components/pages/IaCDashboardPage";
import { UserManagementPage } from "@/components/pages/UserManagementPage";
import { GeneratedArtifactsPage } from "@/components/pages/GeneratedArtifactsPage";
import { AIConfigPage } from "@/components/pages/AIConfigPage";
import { DocsPage } from "@/components/pages/DocsPage";
import { ReportBuilderPage } from "@/components/pages/ReportBuilderPage";
import { SchemaDesignerPage } from "@/components/pages/SchemaDesignerPage";
import { GraphQueryBuilderPage } from "@/components/pages/GraphQueryBuilderPage";
import { ArchitectureViewerPage } from "@/components/pages/ArchitectureViewerPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function AuthInitializer({ children }: { children: React.ReactNode }) {
  const { loadFromStorage } = useAuthStore();

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return <>{children}</>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthInitializer>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<LoginPage />} />

            {/* Protected routes */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/objects/:nodeType" element={<DynamicListPage />} />
                <Route path="/objects/:nodeType/new" element={<DynamicFormPage />} />
                <Route path="/objects/:nodeType/:id" element={<DynamicDetailPage />} />
                <Route path="/objects/:nodeType/:id/edit" element={<DynamicFormPage />} />
                <Route path="/query" element={<QueryWorkbench />} />
                <Route path="/query/builder" element={<GraphQueryBuilderPage />} />
                <Route path="/reports" element={<ReportBuilderPage />} />
                <Route path="/schema" element={<SchemaExplorer />} />
                <Route path="/schema-designer" element={<SchemaDesignerPage />} />

                {/* Infrastructure as Code */}
                <Route path="/iac" element={<IaCDashboardPage />} />

                {/* Automation */}
                <Route path="/parsers" element={<ParserRegistryPage />} />
                <Route path="/filters" element={<FilterEditorPage />} />
                <Route path="/dev" element={<DevWorkbenchPage />} />
                <Route path="/jobs" element={<JobRegistryPage />} />
                <Route path="/ingestion" element={<PlaceholderPage title="Ingestion Runs" description="Monitor data ingestion pipeline runs and their results." />} />

                {/* Administration */}
                <Route path="/git-sources" element={<GitSourcesPage />} />
                <Route path="/admin/audit" element={<AuditLogPage />} />
                <Route path="/admin/schema-validator" element={<SchemaValidatorPage />} />
                <Route path="/admin/users" element={<UserManagementPage />} />
                <Route path="/admin/generated" element={<GeneratedArtifactsPage />} />
                <Route path="/admin/ai" element={<AIConfigPage />} />
                <Route path="/docs" element={<DocsPage />} />

                {/* Graph */}
                <Route path="/graph" element={<GraphExplorerPage />} />
                <Route path="/architecture" element={<ArchitectureViewerPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthInitializer>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
