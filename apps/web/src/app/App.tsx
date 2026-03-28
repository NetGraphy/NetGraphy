import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Dashboard } from "@/components/pages/Dashboard";
import { DynamicListPage } from "@/components/dynamic/DynamicListPage";
import { DynamicDetailPage } from "@/components/dynamic/DynamicDetailPage";
import { DynamicFormPage } from "@/components/dynamic/DynamicFormPage";
import { QueryWorkbench } from "@/components/query/QueryWorkbench";
import { SchemaExplorer } from "@/components/pages/SchemaExplorer";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/objects/:nodeType" element={<DynamicListPage />} />
            <Route path="/objects/:nodeType/new" element={<DynamicFormPage />} />
            <Route path="/objects/:nodeType/:id" element={<DynamicDetailPage />} />
            <Route path="/objects/:nodeType/:id/edit" element={<DynamicFormPage />} />
            <Route path="/query" element={<QueryWorkbench />} />
            <Route path="/schema" element={<SchemaExplorer />} />
            {/* TODO: Add routes for parsers, jobs, git-sources, admin */}
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
