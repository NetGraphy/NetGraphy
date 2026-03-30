/**
 * DocsPage — Self-hosted documentation viewer with navigation tree,
 * markdown rendering, search, and schema-linked references.
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";

interface NavCategory {
  category: string;
  pages: { title: string; slug: string; status: string }[];
}

interface DocPage {
  id: string;
  title: string;
  slug: string;
  summary: string;
  category: string;
  content: string;
  status: string;
  tags: string;
  author: string;
  updated_at: string;
  version: number;
}

export function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentSlug = searchParams.get("page") || "overview";
  const [searchQuery, setSearchQuery] = useState("");
  const [showEditor, setShowEditor] = useState(false);
  const queryClient = useQueryClient();

  // Navigation
  const { data: navData } = useQuery({
    queryKey: ["docs-nav"],
    queryFn: () => api.get("/docs/nav"),
  });
  const nav: NavCategory[] = navData?.data?.data || [];

  // Current page
  const { data: pageData, isLoading: pageLoading } = useQuery({
    queryKey: ["docs-page", currentSlug],
    queryFn: () => api.get(`/docs/pages/${currentSlug}`),
  });
  const page: DocPage | null = pageData?.data?.data || null;

  // Search
  const { data: searchData } = useQuery({
    queryKey: ["docs-search", searchQuery],
    queryFn: () => api.get("/docs/search", { params: { q: searchQuery } }),
    enabled: searchQuery.length >= 2,
  });
  const searchResults = searchData?.data?.data || [];

  // Generate docs
  const generateMutation = useMutation({
    mutationFn: () => api.post("/docs/generate"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["docs-nav"] });
      queryClient.invalidateQueries({ queryKey: ["docs-page"] });
    },
  });

  const navigateTo = (slug: string) => {
    setSearchParams({ page: slug });
    setSearchQuery("");
  };

  // Category order for nav
  const categoryOrder = ["Overview", "Getting Started", "Core Concepts", "Reference"];

  const sortedNav = [...nav].sort((a, b) => {
    const ai = categoryOrder.indexOf(a.category);
    const bi = categoryOrder.indexOf(b.category);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)]">
      {/* Left: Navigation */}
      <div className="flex w-64 flex-shrink-0 flex-col border-r border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-gray-900 dark:text-white">Documentation</h2>
            <button onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="rounded px-1.5 py-0.5 text-[10px] text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700"
              title="Generate docs from schema">
              {generateMutation.isPending ? "..." : "Generate"}
            </button>
          </div>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search docs..."
            className="mt-2 w-full rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          />
        </div>

        {/* Search results */}
        {searchQuery.length >= 2 && searchResults.length > 0 && (
          <div className="border-b border-gray-200 bg-blue-50 px-3 py-2 dark:border-gray-700 dark:bg-blue-900/20">
            <div className="mb-1 text-[10px] font-semibold text-blue-600">Search Results</div>
            {searchResults.map((r: { slug: string; title: string; summary: string }) => (
              <button key={r.slug} onClick={() => navigateTo(r.slug)}
                className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-blue-100 dark:hover:bg-blue-800/30">
                <div className="font-medium text-gray-900 dark:text-white">{r.title}</div>
                {r.summary && <div className="truncate text-gray-500">{r.summary}</div>}
              </button>
            ))}
          </div>
        )}

        {/* Nav tree */}
        <div className="flex-1 overflow-y-auto px-3 py-2">
          {sortedNav.map((cat) => (
            <div key={cat.category} className="mb-3">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                {cat.category}
              </div>
              {cat.pages.map((p) => (
                <button key={p.slug} onClick={() => navigateTo(p.slug)}
                  className={`block w-full rounded px-2 py-1 text-left text-sm ${
                    currentSlug === p.slug
                      ? "bg-brand-50 font-medium text-brand-700 dark:bg-brand-900/20"
                      : "text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-700"
                  }`}>
                  {p.title}
                </button>
              ))}
            </div>
          ))}
          {nav.length === 0 && (
            <div className="py-8 text-center">
              <div className="text-sm text-gray-500">No documentation yet</div>
              <button onClick={() => generateMutation.mutate()}
                className="mt-2 rounded bg-brand-600 px-3 py-1 text-xs text-white hover:bg-brand-700">
                Generate from Schema
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Center: Content */}
      <div className="flex min-w-0 flex-1 flex-col overflow-auto">
        {pageLoading ? (
          <div className="p-8 text-gray-500">Loading...</div>
        ) : page ? (
          <div className="mx-auto max-w-4xl px-8 py-6">
            {/* Page header */}
            <div className="mb-6 border-b border-gray-200 pb-4 dark:border-gray-700">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-gray-400">{page.category}</div>
                  <h1 className="text-3xl font-bold text-gray-900 dark:text-white">{page.title}</h1>
                  {page.summary && <p className="mt-1 text-gray-500">{page.summary}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    page.status === "published" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
                  }`}>{page.status}</span>
                  <button onClick={() => setShowEditor(!showEditor)}
                    className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-700">
                    {showEditor ? "Preview" : "Edit"}
                  </button>
                </div>
              </div>
              <div className="mt-2 text-xs text-gray-400">
                v{page.version} | {page.author && `by ${page.author} | `}{page.updated_at}
              </div>
            </div>

            {/* Content */}
            {showEditor ? (
              <DocEditor slug={currentSlug} content={page.content} onSave={() => {
                queryClient.invalidateQueries({ queryKey: ["docs-page", currentSlug] });
                setShowEditor(false);
              }} />
            ) : (
              <MarkdownRenderer content={page.content} />
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="text-lg text-gray-400">Page not found</div>
              <button onClick={() => navigateTo("overview")}
                className="mt-2 text-sm text-brand-600 hover:text-brand-700">Go to Overview</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MarkdownRenderer({ content }: { content: string }) {
  // Simple markdown-to-HTML renderer for common patterns
  const html = content
    // Headers
    .replace(/^### (.+)$/gm, '<h3 class="mt-6 mb-2 text-lg font-semibold text-gray-900 dark:text-white">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="mt-8 mb-3 text-xl font-bold text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-700 pb-2">$1</h2>')
    .replace(/^# (.+)$/gm, '')  // Title already shown in header
    // Bold/italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="rounded bg-gray-100 px-1 py-0.5 text-sm font-mono text-brand-600 dark:bg-gray-700 dark:text-brand-400">$1</code>')
    // Tables
    .replace(/^\| (.+) \|$/gm, (match) => {
      const cells = match.split("|").filter(c => c.trim()).map(c => c.trim());
      if (cells.every(c => /^-+$/.test(c))) return '<tr class="border-b border-gray-200 dark:border-gray-700"></tr>';
      const tag = match.includes("---") ? "th" : "td";
      return `<tr>${cells.map(c => `<${tag} class="px-3 py-1.5 text-sm text-left">${c}</${tag}>`).join("")}</tr>`;
    })
    // Lists
    .replace(/^- (.+)$/gm, '<li class="ml-4 text-sm text-gray-700 dark:text-gray-300">$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 text-sm text-gray-700 dark:text-gray-300 list-decimal">$1</li>')
    // Paragraphs
    .replace(/^(?!<[hltru]|$)(.+)$/gm, '<p class="mb-3 text-sm text-gray-700 leading-relaxed dark:text-gray-300">$1</p>')
    // Wrap tables
    .replace(/(<tr>[\s\S]*?<\/tr>)/g, '<div class="my-4 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700"><table class="min-w-full">$1</table></div>');

  return <div className="prose-netgraphy" dangerouslySetInnerHTML={{ __html: html }} />;
}

function DocEditor({ slug, content, onSave }: { slug: string; content: string; onSave: () => void }) {
  const [editContent, setEditContent] = useState(content);

  const saveMutation = useMutation({
    mutationFn: () => api.patch(`/docs/pages/${slug}`, { content: editContent }),
    onSuccess: onSave,
  });

  return (
    <div>
      <textarea
        value={editContent}
        onChange={(e) => setEditContent(e.target.value)}
        rows={30}
        className="w-full rounded border border-gray-300 bg-gray-50 p-4 font-mono text-sm leading-relaxed dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
        spellCheck={false}
      />
      <div className="mt-3 flex justify-end gap-2">
        <button onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="rounded bg-brand-600 px-4 py-1.5 text-sm text-white hover:bg-brand-700 disabled:opacity-50">
          {saveMutation.isPending ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
