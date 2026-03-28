# 5. Detailed Frontend Architecture

## 5.1 Technology Stack

| Layer | Technology | Version | Justification |
|---|---|---|---|
| UI Framework | React | 18.3+ | Concurrent features (Suspense, transitions) enable smooth dynamic UI generation; largest ecosystem for graph/editor components |
| Language | TypeScript | 5.4+ | Strict mode. Schema metadata types shared conceptually with backend Pydantic models |
| Build | Vite | 5.x | Sub-second HMR, native ESM dev server, Rollup-based production builds with tree-shaking |
| Server State | TanStack Query (React Query) | 5.x | Declarative caching, background refetch, optimistic mutations, infinite queries for paginated lists |
| Client State | Zustand | 4.x | Minimal boilerplate, no providers needed, supports middleware (persist, devtools); used for schema registry cache and UI preferences only |
| Routing | React Router | 6.x | Loader/action pattern for data-aware routing, nested layouts, type-safe route params |
| Styling | Tailwind CSS 3.x + shadcn/ui | - | Utility-first CSS with zero runtime cost. shadcn/ui provides accessible, composable primitives (Dialog, DropdownMenu, Command, etc.) that are copied into the project -- no package dependency, full control over markup. No heavy framework lock-in like Material UI or Ant Design |
| Graph Visualization | @xyflow/react (React Flow) | 12.x | Best-in-class React graph library. Supports custom node/edge components, multiple layout algorithms via plugins, built-in minimap/controls, handles 1000+ nodes with virtualization. Alternatives considered: vis.js (no React integration), D3 (too low-level), Sigma.js (WebGL but poor React story) |
| Code Editor | @monaco-editor/react | 4.x | Full VS Code editor in-browser. Custom language registration for Cypher syntax highlighting and schema-aware autocomplete |
| Data Tables | TanStack Table | 8.x | Headless -- renders with our own Tailwind/shadcn markup. Supports column sorting, filtering, grouping, pagination, column resizing, and virtual scrolling out of the box. AG Grid was considered but rejected: heavy bundle (300KB+), commercial license required for enterprise features like server-side row model, and opaque DOM that conflicts with Tailwind styling |
| Forms | React Hook Form + Zod | 7.x / 3.x | Uncontrolled form performance, Zod schemas generated dynamically from backend attribute definitions. `@hookform/resolvers/zod` bridges the two |
| HTTP Client | ky | 1.x | Thin wrapper over fetch with retry, timeout, hooks, and JSON parsing. Lighter than axios, no legacy baggage |
| WebSocket | Native WebSocket | - | Thin wrapper with exponential backoff reconnect; no need for Socket.IO overhead given our simple event model |
| Testing | Vitest + React Testing Library + Playwright | - | Vitest for unit/component tests (Vite-native), Playwright for E2E |

---

## 5.2 Dynamic UI Generation System

This is the architectural centerpiece. Every CRUD page, every form field, every table column, and every graph node style is driven by schema metadata served from the backend. Adding a new node type to the schema automatically produces a full UI -- no frontend code changes required.

### 5.2.1 Schema Metadata Contract

The backend exposes `GET /api/v1/schema/ui-metadata` returning the complete schema registry. The frontend TypeScript types that model this response:

```typescript
// src/types/schema.ts

/** Top-level schema registry response */
export interface SchemaRegistry {
  version: string;                          // Monotonic version, e.g. "2024-01-15T10:30:00Z"
  node_types: Record<string, NodeTypeDefinition>;
  edge_types: Record<string, EdgeTypeDefinition>;
  categories: CategoryDefinition[];
  enums: Record<string, EnumDefinition>;
}

/** Defines a single node type (e.g., "Device", "Interface", "IPAddress") */
export interface NodeTypeDefinition {
  name: string;                             // Internal name: "device"
  display_name: string;                     // "Device"
  display_name_plural: string;              // "Devices"
  description: string;
  category: string;                         // "Infrastructure", "Network", etc.
  icon: string;                             // Lucide icon name: "server", "network", "globe"
  color: string;                            // Hex color for graph nodes: "#3B82F6"
  attributes: AttributeDefinition[];
  display_attributes: string[];             // Attribute names shown in list/card views
  search_attributes: string[];              // Attributes indexed for global search
  label_template: string;                   // Jinja-like template: "{{hostname}} ({{site.name}})"
  default_sort: SortDefinition;
  constraints: ConstraintDefinition[];
  ui_hints: NodeUIHints;
}

/** Defines a single attribute on a node or edge type */
export interface AttributeDefinition {
  name: string;                             // "hostname"
  display_name: string;                     // "Hostname"
  description: string;
  type: AttributeType;
  required: boolean;
  unique: boolean;
  read_only: boolean;
  default_value: unknown | null;
  enum_name: string | null;                 // References SchemaRegistry.enums key
  reference: ReferenceDefinition | null;    // For type === "reference"
  validation: ValidationRules;
  ui_hints: AttributeUIHints;
}

/** All supported attribute types */
export type AttributeType =
  | "string"
  | "text"                                  // Multi-line string
  | "integer"
  | "float"
  | "boolean"
  | "datetime"
  | "date"
  | "enum"
  | "reference"
  | "json"
  | "cidr"
  | "ip_address"
  | "mac_address"
  | "url"
  | "email"
  | "list_string"
  | "list_integer";

/** Reference to another node type */
export interface ReferenceDefinition {
  target_type: string;                      // Node type name: "site"
  display_attribute: string;                // Attribute to show: "name"
  search_attributes: string[];              // Attributes to search when selecting: ["name", "slug"]
  allow_multiple: boolean;
  api_endpoint: string;                     // "/api/v1/objects/site" — for fetching options
}

/** Validation rules generated from backend constraints */
export interface ValidationRules {
  min_length: number | null;
  max_length: number | null;
  min_value: number | null;
  max_value: number | null;
  pattern: string | null;                   // Regex pattern
  pattern_description: string | null;       // Human-readable: "Must be a valid hostname"
}

/** Hints controlling how the attribute appears in UI */
export interface AttributeUIHints {
  section: string;                          // Groups attrs in detail/form view: "General", "Network", "Metadata"
  section_order: number;                    // Sort order within sections
  field_order: number;                      // Sort order within a section
  width: "sm" | "md" | "lg" | "xl" | "full"; // Form field width
  list_visible: boolean;                    // Show as column in list view by default
  list_width: number | null;                // Default column width in px
  detail_visible: boolean;
  form_visible: boolean;
  form_placeholder: string | null;
  form_help_text: string | null;
  display_format: string | null;            // e.g., "bytes" → renders 1073741824 as "1 GiB"
  copyable: boolean;                        // Show copy-to-clipboard button
  monospace: boolean;                       // Render in monospace font (configs, IPs, MACs)
}

/** Hints for node type rendering */
export interface NodeUIHints {
  list_default_view: "table" | "card";
  detail_sections: SectionDefinition[];
  graph_node_size: "sm" | "md" | "lg";
  graph_expand_depth: number;               // Default neighbor expansion depth
  enable_config_diff: boolean;              // Show diff viewer for config attributes
  enable_topology_view: boolean;            // Show "View in topology" action
}

export interface SectionDefinition {
  name: string;
  display_name: string;
  order: number;
  collapsible: boolean;
  collapsed_by_default: boolean;
}

/** Defines an edge type (relationship) */
export interface EdgeTypeDefinition {
  name: string;                             // "connected_to"
  display_name: string;                     // "Connected To"
  description: string;
  source_type: string;                      // Node type name
  target_type: string;                      // Node type name
  attributes: AttributeDefinition[];        // Edge properties
  cardinality: "one_to_one" | "one_to_many" | "many_to_many";
  color: string;
  line_style: "solid" | "dashed" | "dotted";
  animated: boolean;                        // Animated flow on edge (e.g., traffic direction)
  ui_hints: EdgeUIHints;
}

export interface EdgeUIHints {
  show_in_source_detail: boolean;           // Show relationship panel on source node's detail page
  show_in_target_detail: boolean;
  inline_create: boolean;                   // Allow creating target from relationship panel
  display_attributes: string[];             // Edge attrs shown in relationship table
}

export interface CategoryDefinition {
  name: string;
  display_name: string;
  icon: string;
  order: number;
  description: string;
}

export interface EnumDefinition {
  name: string;
  values: EnumValue[];
}

export interface EnumValue {
  value: string;
  display_name: string;
  color: string | null;                     // Badge color: "green", "red", "yellow"
  description: string | null;
}

export interface SortDefinition {
  attribute: string;
  direction: "asc" | "desc";
}

export interface ConstraintDefinition {
  type: "unique" | "unique_together" | "required_if" | "immutable_after_create";
  attributes: string[];
  condition: Record<string, unknown> | null;
}
```

### 5.2.2 Schema Registry Store

The Zustand store caches the schema registry and provides selectors:

```typescript
// src/stores/schemaStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  SchemaRegistry,
  NodeTypeDefinition,
  EdgeTypeDefinition,
  AttributeDefinition,
  EnumDefinition,
} from "@/types/schema";

interface SchemaState {
  registry: SchemaRegistry | null;
  version: string | null;
  loading: boolean;
  error: string | null;
  lastFetched: number | null;

  // Actions
  setRegistry: (registry: SchemaRegistry) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  // Selectors (derived, but kept as methods for convenience with Zustand)
  getNodeType: (name: string) => NodeTypeDefinition | undefined;
  getEdgeType: (name: string) => EdgeTypeDefinition | undefined;
  getEnum: (name: string) => EnumDefinition | undefined;
  getNodeTypesByCategory: () => Record<string, NodeTypeDefinition[]>;
  getEdgesForNodeType: (nodeTypeName: string) => {
    outgoing: EdgeTypeDefinition[];
    incoming: EdgeTypeDefinition[];
  };
  getVisibleListAttributes: (nodeTypeName: string) => AttributeDefinition[];
  getFormAttributes: (nodeTypeName: string) => AttributeDefinition[];
}

export const useSchemaStore = create<SchemaState>()(
  persist(
    (set, get) => ({
      registry: null,
      version: null,
      loading: false,
      error: null,
      lastFetched: null,

      setRegistry: (registry) =>
        set({
          registry,
          version: registry.version,
          lastFetched: Date.now(),
          error: null,
        }),

      setLoading: (loading) => set({ loading }),
      setError: (error) => set({ error, loading: false }),

      getNodeType: (name) => get().registry?.node_types[name],

      getEdgeType: (name) => get().registry?.edge_types[name],

      getEnum: (name) => get().registry?.enums[name],

      getNodeTypesByCategory: () => {
        const reg = get().registry;
        if (!reg) return {};
        const grouped: Record<string, NodeTypeDefinition[]> = {};
        for (const nt of Object.values(reg.node_types)) {
          (grouped[nt.category] ??= []).push(nt);
        }
        // Sort categories by their defined order
        const categoryOrder = Object.fromEntries(
          reg.categories.map((c) => [c.name, c.order])
        );
        return Object.fromEntries(
          Object.entries(grouped).sort(
            ([a], [b]) => (categoryOrder[a] ?? 99) - (categoryOrder[b] ?? 99)
          )
        );
      },

      getEdgesForNodeType: (nodeTypeName) => {
        const reg = get().registry;
        if (!reg) return { outgoing: [], incoming: [] };
        const outgoing = Object.values(reg.edge_types).filter(
          (e) => e.source_type === nodeTypeName
        );
        const incoming = Object.values(reg.edge_types).filter(
          (e) => e.target_type === nodeTypeName
        );
        return { outgoing, incoming };
      },

      getVisibleListAttributes: (nodeTypeName) => {
        const nt = get().getNodeType(nodeTypeName);
        if (!nt) return [];
        return nt.attributes
          .filter((a) => a.ui_hints.list_visible)
          .sort((a, b) => a.ui_hints.field_order - b.ui_hints.field_order);
      },

      getFormAttributes: (nodeTypeName) => {
        const nt = get().getNodeType(nodeTypeName);
        if (!nt) return [];
        return nt.attributes
          .filter((a) => a.ui_hints.form_visible && !a.read_only)
          .sort((a, b) => {
            const sectionDiff = a.ui_hints.section_order - b.ui_hints.section_order;
            return sectionDiff !== 0 ? sectionDiff : a.ui_hints.field_order - b.ui_hints.field_order;
          });
      },
    }),
    {
      name: "netgraphy-schema",
      // Only persist the registry and version, not loading/error transient state
      partialize: (state) => ({
        registry: state.registry,
        version: state.version,
        lastFetched: state.lastFetched,
      }),
    }
  )
);
```

Schema hydration hook, used at app startup and on WebSocket events:

```typescript
// src/hooks/useSchemaRegistry.ts

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { apiClient } from "@/api/client";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { SchemaRegistry } from "@/types/schema";

export function useSchemaRegistry() {
  const store = useSchemaStore();

  const query = useQuery<SchemaRegistry>({
    queryKey: ["schema", "ui-metadata"],
    queryFn: () => apiClient.get("schema/ui-metadata").json(),
    staleTime: 5 * 60 * 1000,               // Consider fresh for 5 min
    gcTime: 30 * 60 * 1000,                  // Keep in cache for 30 min
    refetchOnWindowFocus: false,             // WebSocket handles invalidation
    // Seed from persisted Zustand store for instant render
    placeholderData: store.registry ?? undefined,
  });

  // Sync query result into Zustand store
  useEffect(() => {
    if (query.data) {
      store.setRegistry(query.data);
    }
  }, [query.data]);

  // Listen for schema change events via WebSocket
  const { lastMessage } = useWebSocket("schema");
  useEffect(() => {
    if (lastMessage?.type === "schema.changed") {
      query.refetch();
    }
  }, [lastMessage]);

  return {
    registry: store.registry,
    isLoading: query.isLoading && !store.registry,   // Only show loading if no cached data
    error: query.error,
    refetch: query.refetch,
  };
}
```

### 5.2.3 Component Registry (Field Renderers)

The field renderer registry maps `AttributeType` values to React components for both display and edit modes. This is the core dispatch table of the dynamic UI.

```typescript
// src/lib/fieldRenderers.ts

import { type ComponentType, lazy } from "react";
import type { AttributeDefinition, EnumDefinition } from "@/types/schema";

/** Props every display renderer receives */
export interface DisplayRendererProps {
  attribute: AttributeDefinition;
  value: unknown;
  enumDef?: EnumDefinition;
}

/** Props every edit renderer receives */
export interface EditRendererProps {
  attribute: AttributeDefinition;
  enumDef?: EnumDefinition;
  // React Hook Form integration — the field is registered by the parent,
  // these come from the controller render prop
  field: {
    value: unknown;
    onChange: (value: unknown) => void;
    onBlur: () => void;
    name: string;
    ref: React.Ref<unknown>;
  };
  error?: string;
  disabled?: boolean;
}

interface RendererEntry {
  display: ComponentType<DisplayRendererProps>;
  edit: ComponentType<EditRendererProps>;
}

// Lazy-load heavy components (Monaco-based JSON editor, date pickers)
const JsonDisplay = lazy(() => import("@/components/renderers/JsonDisplay"));
const JsonEditor = lazy(() => import("@/components/renderers/JsonEditor"));
const DateTimePicker = lazy(() => import("@/components/renderers/DateTimePicker"));

// Eagerly loaded lightweight components
import { TextDisplay, TextInput } from "@/components/renderers/TextRenderers";
import { TextAreaDisplay, TextAreaInput } from "@/components/renderers/TextAreaRenderers";
import { NumberDisplay, NumberInput } from "@/components/renderers/NumberRenderers";
import { BooleanBadge, Toggle } from "@/components/renderers/BooleanRenderers";
import { DateTimeDisplay } from "@/components/renderers/DateTimeRenderers";
import { EnumBadge, EnumSelect } from "@/components/renderers/EnumRenderers";
import { ReferenceLink, ReferenceSelector } from "@/components/renderers/ReferenceRenderers";
import { IPDisplay, IPInput } from "@/components/renderers/IPRenderers";
import { CIDRDisplay, CIDRInput } from "@/components/renderers/CIDRRenderers";
import { MACDisplay, MACInput } from "@/components/renderers/MACRenderers";
import { URLDisplay, URLInput } from "@/components/renderers/URLRenderers";
import { EmailDisplay, EmailInput } from "@/components/renderers/EmailRenderers";
import { ListStringDisplay, ListStringInput } from "@/components/renderers/ListRenderers";
import { ListIntegerDisplay, ListIntegerInput } from "@/components/renderers/ListRenderers";

import type { AttributeType } from "@/types/schema";

const RENDERER_REGISTRY: Record<AttributeType, RendererEntry> = {
  string:       { display: TextDisplay,       edit: TextInput },
  text:         { display: TextAreaDisplay,   edit: TextAreaInput },
  integer:      { display: NumberDisplay,     edit: NumberInput },
  float:        { display: NumberDisplay,     edit: NumberInput },
  boolean:      { display: BooleanBadge,      edit: Toggle },
  datetime:     { display: DateTimeDisplay,   edit: DateTimePicker },
  date:         { display: DateTimeDisplay,   edit: DateTimePicker },
  enum:         { display: EnumBadge,         edit: EnumSelect },
  reference:    { display: ReferenceLink,     edit: ReferenceSelector },
  json:         { display: JsonDisplay,       edit: JsonEditor },
  cidr:         { display: CIDRDisplay,       edit: CIDRInput },
  ip_address:   { display: IPDisplay,         edit: IPInput },
  mac_address:  { display: MACDisplay,        edit: MACInput },
  url:          { display: URLDisplay,        edit: URLInput },
  email:        { display: EmailDisplay,      edit: EmailInput },
  list_string:  { display: ListStringDisplay, edit: ListStringInput },
  list_integer: { display: ListIntegerDisplay,edit: ListIntegerInput },
};

export function getDisplayRenderer(type: AttributeType): ComponentType<DisplayRendererProps> {
  return RENDERER_REGISTRY[type]?.display ?? TextDisplay;
}

export function getEditRenderer(type: AttributeType): ComponentType<EditRendererProps> {
  return RENDERER_REGISTRY[type]?.edit ?? TextInput;
}
```

The `FieldRenderer` component dispatches to the appropriate renderer:

```typescript
// src/components/dynamic/FieldRenderer.tsx

import { Suspense } from "react";
import { Controller, useFormContext } from "react-hook-form";
import { Skeleton } from "@/components/ui/skeleton";
import { getDisplayRenderer, getEditRenderer } from "@/lib/fieldRenderers";
import { useSchemaStore } from "@/stores/schemaStore";
import type { AttributeDefinition } from "@/types/schema";

interface FieldRendererProps {
  attribute: AttributeDefinition;
  value?: unknown;
  mode: "display" | "edit";
}

export function FieldRenderer({ attribute, value, mode }: FieldRendererProps) {
  const getEnum = useSchemaStore((s) => s.getEnum);
  const enumDef = attribute.enum_name ? getEnum(attribute.enum_name) : undefined;

  if (mode === "display") {
    const DisplayComponent = getDisplayRenderer(attribute.type);
    return (
      <Suspense fallback={<Skeleton className="h-5 w-32" />}>
        <DisplayComponent attribute={attribute} value={value} enumDef={enumDef} />
      </Suspense>
    );
  }

  // Edit mode — integrate with React Hook Form via Controller
  const { control } = useFormContext();
  return (
    <Suspense fallback={<Skeleton className="h-9 w-full" />}>
      <Controller
        name={attribute.name}
        control={control}
        render={({ field, fieldState }) => {
          const EditComponent = getEditRenderer(attribute.type);
          return (
            <div className="space-y-1">
              <label
                htmlFor={attribute.name}
                className="text-sm font-medium text-foreground"
              >
                {attribute.display_name}
                {attribute.required && <span className="text-destructive ml-0.5">*</span>}
              </label>
              <EditComponent
                attribute={attribute}
                enumDef={enumDef}
                field={field}
                error={fieldState.error?.message}
              />
              {attribute.ui_hints.form_help_text && (
                <p className="text-xs text-muted-foreground">
                  {attribute.ui_hints.form_help_text}
                </p>
              )}
              {fieldState.error?.message && (
                <p className="text-xs text-destructive">{fieldState.error.message}</p>
              )}
            </div>
          );
        }}
      />
    </Suspense>
  );
}
```

### 5.2.4 Dynamic Zod Schema Generation

Forms need validation. Instead of hand-writing Zod schemas per type, we generate them from `AttributeDefinition[]`:

```typescript
// src/lib/zodSchemaBuilder.ts

import { z, type ZodTypeAny } from "zod";
import type { AttributeDefinition, EnumDefinition, SchemaRegistry } from "@/types/schema";

export function buildZodSchema(
  attributes: AttributeDefinition[],
  registry: SchemaRegistry,
  mode: "create" | "edit"
): z.ZodObject<Record<string, ZodTypeAny>> {
  const shape: Record<string, ZodTypeAny> = {};

  for (const attr of attributes) {
    if (attr.read_only) continue;
    if (!attr.ui_hints.form_visible) continue;

    let field = buildFieldSchema(attr, registry);

    // In edit mode, all fields are optional (partial update / PATCH semantics)
    if (mode === "edit") {
      field = field.optional();
    } else if (!attr.required) {
      field = field.optional().nullable();
    }

    shape[attr.name] = field;
  }

  return z.object(shape);
}

function buildFieldSchema(attr: AttributeDefinition, registry: SchemaRegistry): ZodTypeAny {
  const v = attr.validation;

  switch (attr.type) {
    case "string":
    case "text": {
      let s = z.string();
      if (v.min_length != null) s = s.min(v.min_length, `Minimum ${v.min_length} characters`);
      if (v.max_length != null) s = s.max(v.max_length, `Maximum ${v.max_length} characters`);
      if (v.pattern) s = s.regex(new RegExp(v.pattern), v.pattern_description ?? "Invalid format");
      if (attr.required) s = s.min(1, `${attr.display_name} is required`);
      return s;
    }

    case "integer": {
      let n = z.number().int();
      if (v.min_value != null) n = n.min(v.min_value);
      if (v.max_value != null) n = n.max(v.max_value);
      return n;
    }

    case "float": {
      let n = z.number();
      if (v.min_value != null) n = n.min(v.min_value);
      if (v.max_value != null) n = n.max(v.max_value);
      return n;
    }

    case "boolean":
      return z.boolean();

    case "datetime":
    case "date":
      return z.string().datetime({ message: "Must be a valid ISO datetime" });

    case "enum": {
      const enumDef = attr.enum_name ? registry.enums[attr.enum_name] : null;
      if (enumDef) {
        const values = enumDef.values.map((v) => v.value) as [string, ...string[]];
        return z.enum(values);
      }
      return z.string();
    }

    case "reference":
      return attr.reference?.allow_multiple
        ? z.array(z.string().uuid())
        : z.string().uuid();

    case "json":
      return z.unknown();

    case "ip_address":
      return z.string().regex(
        /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$|^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$/,
        "Must be a valid IPv4 or IPv6 address"
      );

    case "cidr":
      return z.string().regex(
        /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\/(?:3[0-2]|[12]?\d)$|^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\/(?:12[0-8]|1[01]\d|[1-9]?\d)$/,
        "Must be valid CIDR notation (e.g., 10.0.0.0/24)"
      );

    case "mac_address":
      return z.string().regex(
        /^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/,
        "Must be a valid MAC address (e.g., AA:BB:CC:DD:EE:FF)"
      );

    case "url":
      return z.string().url("Must be a valid URL");

    case "email":
      return z.string().email("Must be a valid email address");

    case "list_string":
      return z.array(z.string());

    case "list_integer":
      return z.array(z.number().int());

    default:
      return z.unknown();
  }
}
```

### 5.2.5 Page Generators

#### DynamicListPage

Renders a paginated, filterable, sortable table for any node type. Columns are derived entirely from schema metadata.

```typescript
// src/components/dynamic/DynamicListPage.tsx

import { useMemo, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  type ColumnDef,
  flexRender,
} from "@tanstack/react-table";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { FieldRenderer } from "./FieldRenderer";
import { FilterBar, type FilterValue } from "@/components/common/FilterBar";
import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { AttributeDefinition, NodeTypeDefinition } from "@/types/schema";

interface ListResponse {
  items: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
}

export function DynamicListPage() {
  const { nodeType } = useParams<{ nodeType: string }>();
  const navigate = useNavigate();
  const getNodeType = useSchemaStore((s) => s.getNodeType);
  const getVisibleListAttributes = useSchemaStore((s) => s.getVisibleListAttributes);

  const typeDef = getNodeType(nodeType!);
  if (!typeDef) {
    return <div className="p-8 text-destructive">Unknown object type: {nodeType}</div>;
  }

  const visibleAttributes = getVisibleListAttributes(nodeType!);

  // Pagination and filter state
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });
  const [sorting, setSorting] = useState([
    { id: typeDef.default_sort.attribute, desc: typeDef.default_sort.direction === "desc" },
  ]);
  const [filters, setFilters] = useState<FilterValue[]>([]);

  // Build query params from table state
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      page: String(pagination.pageIndex + 1),
      page_size: String(pagination.pageSize),
    };
    if (sorting.length > 0) {
      params.sort = `${sorting[0].desc ? "-" : ""}${sorting[0].id}`;
    }
    for (const f of filters) {
      params[`filter[${f.attribute}][${f.operator}]`] = f.value;
    }
    return params;
  }, [pagination, sorting, filters]);

  // Fetch data
  const { data, isLoading } = useQuery<ListResponse>({
    queryKey: ["objects", nodeType, queryParams],
    queryFn: () =>
      apiClient
        .get(`objects/${nodeType}`, { searchParams: queryParams })
        .json(),
    placeholderData: keepPreviousData,  // Keep showing old data while new page loads
  });

  // Build TanStack Table column definitions from schema attributes
  const columns = useMemo<ColumnDef<Record<string, unknown>>[]>(() => {
    return visibleAttributes.map((attr: AttributeDefinition) => ({
      id: attr.name,
      accessorKey: attr.name,
      header: attr.display_name,
      size: attr.ui_hints.list_width ?? undefined,
      enableSorting: true,
      cell: ({ row }) => (
        <FieldRenderer
          attribute={attr}
          value={row.original[attr.name]}
          mode="display"
        />
      ),
    }));
  }, [visibleAttributes]);

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { pagination, sorting },
    onPaginationChange: setPagination,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    pageCount: data ? Math.ceil(data.total / pagination.pageSize) : -1,
  });

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{typeDef.display_name_plural}</h1>
          <p className="text-sm text-muted-foreground">{typeDef.description}</p>
        </div>
        <Button asChild>
          <Link to={`/objects/${nodeType}/new`}>
            <Plus className="mr-2 h-4 w-4" />
            Add {typeDef.display_name}
          </Link>
        </Button>
      </div>

      {/* Filter bar */}
      <FilterBar
        attributes={typeDef.attributes}
        value={filters}
        onChange={setFilters}
      />

      {/* Table */}
      <div className="rounded-md border">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b bg-muted/50">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="h-10 px-4 text-left text-sm font-medium text-muted-foreground cursor-pointer select-none"
                    style={{ width: header.getSize() }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{ asc: " ↑", desc: " ↓" }[
                      header.column.getIsSorted() as string
                    ] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={columns.length} className="h-24 text-center">
                  Loading...
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b hover:bg-muted/30 cursor-pointer"
                  onClick={() => navigate(`/objects/${nodeType}/${row.original.id}`)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-2 text-sm">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {data
            ? `Showing ${pagination.pageIndex * pagination.pageSize + 1}-${Math.min(
                (pagination.pageIndex + 1) * pagination.pageSize,
                data.total
              )} of ${data.total}`
            : ""}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
```

#### DynamicDetailPage

Renders a detail view for a single node instance. Attribute sections, relationship panels, and a graph mini-view are all driven by schema metadata.

```typescript
// src/components/dynamic/DynamicDetailPage.tsx — structural overview

import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { FieldRenderer } from "./FieldRenderer";
import { DynamicRelationshipPanel } from "./DynamicRelationshipPanel";
import { GraphMiniView } from "@/components/graph/GraphMiniView";
import { apiClient } from "@/api/client";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Pencil } from "lucide-react";
import type { AttributeDefinition, SectionDefinition } from "@/types/schema";

export function DynamicDetailPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id: string }>();
  const getNodeType = useSchemaStore((s) => s.getNodeType);
  const getEdgesForNodeType = useSchemaStore((s) => s.getEdgesForNodeType);

  const typeDef = getNodeType(nodeType!);
  if (!typeDef) return <NotFound />;

  const { data: node, isLoading } = useQuery({
    queryKey: ["objects", nodeType, id],
    queryFn: () => apiClient.get(`objects/${nodeType}/${id}`).json<Record<string, unknown>>(),
  });

  const edges = getEdgesForNodeType(nodeType!);

  // Group attributes by section, respecting ui_hints.section and ordering
  const sections = useMemo(() => {
    return groupAttributesBySection(
      typeDef.attributes.filter((a) => a.ui_hints.detail_visible),
      typeDef.ui_hints.detail_sections
    );
  }, [typeDef]);

  if (isLoading) return <DetailSkeleton />;
  if (!node) return <NotFound />;

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header with title from label_template and edit button */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            {renderLabelTemplate(typeDef.label_template, node)}
          </h1>
          <p className="text-sm text-muted-foreground">{typeDef.display_name}</p>
        </div>
        <Button variant="outline" asChild>
          <Link to={`/objects/${nodeType}/${id}/edit`}>
            <Pencil className="mr-2 h-4 w-4" /> Edit
          </Link>
        </Button>
      </div>

      <Tabs defaultValue="attributes">
        <TabsList>
          <TabsTrigger value="attributes">Attributes</TabsTrigger>
          <TabsTrigger value="relationships">
            Relationships ({edges.outgoing.length + edges.incoming.length})
          </TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
        </TabsList>

        <TabsContent value="attributes">
          {/* Render each section as a collapsible card */}
          {sections.map((section) => (
            <AttributeSection
              key={section.name}
              section={section.definition}
              attributes={section.attributes}
              values={node}
            />
          ))}
        </TabsContent>

        <TabsContent value="relationships">
          {/* Outgoing relationships */}
          {edges.outgoing
            .filter((e) => e.ui_hints.show_in_source_detail)
            .map((edgeDef) => (
              <DynamicRelationshipPanel
                key={edgeDef.name}
                edgeType={edgeDef}
                nodeId={id!}
                direction="outgoing"
              />
            ))}
          {/* Incoming relationships */}
          {edges.incoming
            .filter((e) => e.ui_hints.show_in_target_detail)
            .map((edgeDef) => (
              <DynamicRelationshipPanel
                key={edgeDef.name}
                edgeType={edgeDef}
                nodeId={id!}
                direction="incoming"
              />
            ))}
        </TabsContent>

        <TabsContent value="graph">
          <GraphMiniView
            centerId={id!}
            centerType={nodeType!}
            depth={typeDef.ui_hints.graph_expand_depth}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Groups attributes into their UI sections, ordered correctly */
function groupAttributesBySection(
  attributes: AttributeDefinition[],
  sectionDefs: SectionDefinition[]
): { definition: SectionDefinition; attributes: AttributeDefinition[] }[] {
  const sectionMap = new Map<string, AttributeDefinition[]>();

  for (const attr of attributes) {
    const key = attr.ui_hints.section || "General";
    if (!sectionMap.has(key)) sectionMap.set(key, []);
    sectionMap.get(key)!.push(attr);
  }

  // Sort attributes within each section by field_order
  for (const attrs of sectionMap.values()) {
    attrs.sort((a, b) => a.ui_hints.field_order - b.ui_hints.field_order);
  }

  // Match to section definitions and sort by section order
  const sectionDefMap = new Map(sectionDefs.map((s) => [s.name, s]));
  return Array.from(sectionMap.entries())
    .map(([name, attrs]) => ({
      definition: sectionDefMap.get(name) ?? {
        name,
        display_name: name,
        order: 99,
        collapsible: true,
        collapsed_by_default: false,
      },
      attributes: attrs,
    }))
    .sort((a, b) => a.definition.order - b.definition.order);
}

/** Resolves a label template like "{{hostname}} ({{site.name}})" against node data */
function renderLabelTemplate(template: string, data: Record<string, unknown>): string {
  return template.replace(/\{\{(\w+(?:\.\w+)*)\}\}/g, (_, path: string) => {
    const value = path.split(".").reduce<unknown>((obj, key) => {
      if (obj != null && typeof obj === "object") return (obj as Record<string, unknown>)[key];
      return undefined;
    }, data);
    return value != null ? String(value) : "";
  });
}
```

#### DynamicFormPage

Generates a validated form from schema metadata:

```typescript
// src/components/dynamic/DynamicFormPage.tsx — structural overview

import { useParams, useNavigate } from "react-router-dom";
import { useForm, FormProvider } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { buildZodSchema } from "@/lib/zodSchemaBuilder";
import { FieldRenderer } from "./FieldRenderer";
import { apiClient } from "@/api/client";

export function DynamicFormPage() {
  const { nodeType, id } = useParams<{ nodeType: string; id?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const store = useSchemaStore();

  const typeDef = store.getNodeType(nodeType!);
  if (!typeDef) return <NotFound />;

  const mode = id ? "edit" : "create";
  const formAttributes = store.getFormAttributes(nodeType!);

  // Generate Zod schema from attribute definitions
  const validationSchema = useMemo(
    () => buildZodSchema(formAttributes, store.registry!, mode),
    [formAttributes, store.registry, mode]
  );

  // For edit mode, fetch existing data to populate form
  const { data: existingNode } = useQuery({
    queryKey: ["objects", nodeType, id],
    queryFn: () => apiClient.get(`objects/${nodeType}/${id}`).json(),
    enabled: mode === "edit" && !!id,
  });

  const form = useForm({
    resolver: zodResolver(validationSchema),
    defaultValues: mode === "edit" ? existingNode : buildDefaultValues(formAttributes),
    // Reset form when existing data loads (edit mode)
    values: mode === "edit" ? existingNode : undefined,
  });

  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      mode === "create"
        ? apiClient.post(`objects/${nodeType}`, { json: values }).json()
        : apiClient.patch(`objects/${nodeType}/${id}`, { json: values }).json(),
    onSuccess: (result: { id: string }) => {
      // Invalidate list queries and the specific object query
      queryClient.invalidateQueries({ queryKey: ["objects", nodeType] });
      navigate(`/objects/${nodeType}/${result.id ?? id}`);
    },
  });

  // Group form fields by section, same logic as detail page
  const sections = useMemo(
    () => groupAttributesBySection(formAttributes, typeDef.ui_hints.detail_sections),
    [formAttributes, typeDef]
  );

  return (
    <div className="max-w-3xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">
        {mode === "create" ? `New ${typeDef.display_name}` : `Edit ${typeDef.display_name}`}
      </h1>

      <FormProvider {...form}>
        <form onSubmit={form.handleSubmit((v) => mutation.mutate(v))} className="space-y-8">
          {sections.map((section) => (
            <fieldset key={section.definition.name} className="space-y-4">
              <legend className="text-lg font-semibold">{section.definition.display_name}</legend>
              <div className="grid grid-cols-12 gap-4">
                {section.attributes.map((attr) => (
                  <div
                    key={attr.name}
                    className={widthToColSpan(attr.ui_hints.width)}
                  >
                    <FieldRenderer attribute={attr} mode="edit" />
                  </div>
                ))}
              </div>
            </fieldset>
          ))}

          <div className="flex gap-3 pt-4">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Saving..." : mode === "create" ? "Create" : "Save Changes"}
            </Button>
            <Button type="button" variant="outline" onClick={() => navigate(-1)}>
              Cancel
            </Button>
          </div>

          {mutation.isError && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {(mutation.error as Error).message}
            </div>
          )}
        </form>
      </FormProvider>
    </div>
  );
}

/** Maps the width hint from schema to Tailwind grid column spans */
function widthToColSpan(width: string): string {
  switch (width) {
    case "sm":   return "col-span-3";
    case "md":   return "col-span-6";
    case "lg":   return "col-span-9";
    case "xl":   return "col-span-12";
    case "full": return "col-span-12";
    default:     return "col-span-6";
  }
}

/** Builds default form values from attribute definitions */
function buildDefaultValues(
  attributes: AttributeDefinition[]
): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const attr of attributes) {
    if (attr.default_value !== null && attr.default_value !== undefined) {
      defaults[attr.name] = attr.default_value;
    } else {
      defaults[attr.name] = attr.type === "boolean" ? false : "";
    }
  }
  return defaults;
}
```

#### DynamicRelationshipPanel

Renders a table of related nodes for a given edge type, with add/remove capabilities:

```typescript
// src/components/dynamic/DynamicRelationshipPanel.tsx

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSchemaStore } from "@/stores/schemaStore";
import { apiClient } from "@/api/client";
import { FieldRenderer } from "./FieldRenderer";
import { ReferenceSelector } from "@/components/renderers/ReferenceRenderers";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Plus, Trash2 } from "lucide-react";
import type { EdgeTypeDefinition } from "@/types/schema";

interface Props {
  edgeType: EdgeTypeDefinition;
  nodeId: string;
  direction: "outgoing" | "incoming";
}

export function DynamicRelationshipPanel({ edgeType, nodeId, direction }: Props) {
  const queryClient = useQueryClient();
  const getNodeType = useSchemaStore((s) => s.getNodeType);
  const [addDialogOpen, setAddDialogOpen] = useState(false);

  // Determine the "other" side
  const relatedTypeName =
    direction === "outgoing" ? edgeType.target_type : edgeType.source_type;
  const relatedTypeDef = getNodeType(relatedTypeName);

  // Fetch relationships
  const { data: relationships } = useQuery({
    queryKey: ["relationships", edgeType.name, nodeId, direction],
    queryFn: () =>
      apiClient
        .get(`objects/${direction === "outgoing" ? edgeType.source_type : edgeType.target_type}/${nodeId}/relationships/${edgeType.name}`, {
          searchParams: { direction },
        })
        .json<{ items: RelationshipItem[] }>(),
  });

  // Add relationship
  const addMutation = useMutation({
    mutationFn: (targetId: string) =>
      apiClient
        .post(`relationships/${edgeType.name}`, {
          json: {
            source_id: direction === "outgoing" ? nodeId : targetId,
            target_id: direction === "outgoing" ? targetId : nodeId,
          },
        })
        .json(),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["relationships", edgeType.name, nodeId],
      });
      setAddDialogOpen(false);
    },
  });

  // Remove relationship
  const removeMutation = useMutation({
    mutationFn: (relationshipId: string) =>
      apiClient.delete(`relationships/${edgeType.name}/${relationshipId}`).json(),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["relationships", edgeType.name, nodeId],
      });
    },
  });

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">
          {edgeType.display_name} → {relatedTypeDef?.display_name_plural ?? relatedTypeName}
        </h3>
        <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm">
              <Plus className="mr-1 h-3 w-3" /> Add
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add {edgeType.display_name}</DialogTitle>
            </DialogHeader>
            {/* ReferenceSelector searches for nodes of the related type */}
            <ReferenceSelector
              targetType={relatedTypeName}
              onSelect={(selectedId) => addMutation.mutate(selectedId)}
            />
          </DialogContent>
        </Dialog>
      </div>

      {/* Relationship table */}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="pb-2">{relatedTypeDef?.display_name ?? "Name"}</th>
            {edgeType.ui_hints.display_attributes.map((attrName) => {
              const attr = edgeType.attributes.find((a) => a.name === attrName);
              return <th key={attrName} className="pb-2">{attr?.display_name ?? attrName}</th>;
            })}
            <th className="pb-2 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {(relationships?.items ?? []).map((rel) => (
            <tr key={rel.relationship_id} className="border-b">
              <td className="py-2">
                <Link
                  to={`/objects/${relatedTypeName}/${rel.related_node.id}`}
                  className="text-primary hover:underline"
                >
                  {rel.related_node.display_label}
                </Link>
              </td>
              {edgeType.ui_hints.display_attributes.map((attrName) => {
                const attr = edgeType.attributes.find((a) => a.name === attrName);
                return (
                  <td key={attrName} className="py-2">
                    {attr && (
                      <FieldRenderer
                        attribute={attr}
                        value={rel.edge_attributes[attrName]}
                        mode="display"
                      />
                    )}
                  </td>
                );
              })}
              <td className="py-2">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeMutation.mutate(rel.relationship_id)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface RelationshipItem {
  relationship_id: string;
  related_node: {
    id: string;
    type: string;
    display_label: string;
  };
  edge_attributes: Record<string, unknown>;
}
```

---

## 5.3 Application Shell and Navigation

### 5.3.1 Auto-Generated Sidebar

The sidebar navigation is entirely driven by the schema registry. Node types are grouped by their `category` field, and categories are ordered by `CategoryDefinition.order`.

```typescript
// src/components/layout/Sidebar.tsx

import { NavLink } from "react-router-dom";
import { useSchemaStore } from "@/stores/schemaStore";
import { getLucideIcon } from "@/lib/icons";
import {
  Search,
  Network,
  FileCode,
  PlayCircle,
  GitBranch,
  Shield,
  ScrollText,
  LayoutDashboard,
  Boxes,
} from "lucide-react";

const STATIC_NAV_SECTIONS = [
  { label: "Dashboard", to: "/", icon: LayoutDashboard },
  { label: "Query Workbench", to: "/query", icon: Search },
  { label: "Graph Explorer", to: "/graph", icon: Network },
  { label: "Schema Explorer", to: "/schema", icon: Boxes },
] as const;

const STATIC_NAV_BOTTOM = [
  { label: "Parsers", to: "/parsers", icon: FileCode },
  { label: "Jobs", to: "/jobs", icon: PlayCircle },
  { label: "Git Sources", to: "/git-sources", icon: GitBranch },
  { label: "RBAC Admin", to: "/admin/rbac", icon: Shield },
  { label: "Audit Log", to: "/admin/audit", icon: ScrollText },
] as const;

export function Sidebar() {
  const registry = useSchemaStore((s) => s.registry);
  const getNodeTypesByCategory = useSchemaStore((s) => s.getNodeTypesByCategory);
  const categorized = getNodeTypesByCategory();
  const categories = registry?.categories ?? [];
  const categoryMap = new Map(categories.map((c) => [c.name, c]));

  return (
    <aside className="flex h-full w-60 flex-col border-r bg-background">
      {/* Logo */}
      <div className="flex h-14 items-center border-b px-4 font-bold text-lg">
        NetGraphy
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {/* Static top sections */}
        {STATIC_NAV_SECTIONS.map(({ label, to, icon: Icon }) => (
          <NavItem key={to} to={to} icon={<Icon className="h-4 w-4" />} label={label} />
        ))}

        <hr className="my-2 mx-3" />

        {/* Dynamic schema-driven sections */}
        {Object.entries(categorized).map(([categoryName, nodeTypes]) => {
          const catDef = categoryMap.get(categoryName);
          const CategoryIcon = catDef ? getLucideIcon(catDef.icon) : Boxes;
          return (
            <div key={categoryName}>
              <h3 className="px-4 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {catDef?.display_name ?? categoryName}
              </h3>
              {nodeTypes.map((nt) => {
                const NtIcon = getLucideIcon(nt.icon);
                return (
                  <NavItem
                    key={nt.name}
                    to={`/objects/${nt.name}`}
                    icon={<NtIcon className="h-4 w-4" />}
                    label={nt.display_name_plural}
                  />
                );
              })}
            </div>
          );
        })}

        <hr className="my-2 mx-3" />

        {/* Static bottom sections */}
        {STATIC_NAV_BOTTOM.map(({ label, to, icon: Icon }) => (
          <NavItem key={to} to={to} icon={<Icon className="h-4 w-4" />} label={label} />
        ))}
      </nav>
    </aside>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-md mx-2 px-3 py-1.5 text-sm transition-colors ${
          isActive
            ? "bg-primary/10 text-primary font-medium"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        }`
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}
```

### 5.3.2 Top Bar

```typescript
// src/components/layout/TopBar.tsx — key features

// - Global search input: schema-aware, powered by Command (cmdk) palette
//   Searches all node types in search_attributes, shows results grouped by type
//   Keyboard shortcut: Cmd+K / Ctrl+K
// - User avatar dropdown: profile, preferences (theme, table density), logout
// - Notification bell: unread count badge, dropdown with recent job completions/failures
// - Breadcrumbs: auto-generated from current route + schema display names
```

### 5.3.3 Breadcrumb Generation

```typescript
// src/components/layout/Breadcrumbs.tsx

import { useMatches, Link } from "react-router-dom";
import { useSchemaStore } from "@/stores/schemaStore";
import { ChevronRight } from "lucide-react";

/**
 * Breadcrumbs are derived from the route path and enriched with schema display names.
 * Route: /objects/device/abc-123 → ["Objects", "Devices", "switch01.nyc"]
 * The label for a specific node (abc-123) comes from the loader data or a query.
 */
export function Breadcrumbs() {
  const matches = useMatches();
  const getNodeType = useSchemaStore((s) => s.getNodeType);

  const crumbs = matches
    .filter((m) => m.handle?.breadcrumb)
    .map((m) => {
      const crumb = (m.handle as { breadcrumb: BreadcrumbFn }).breadcrumb(m, getNodeType);
      return { label: crumb.label, to: crumb.to };
    });

  return (
    <nav className="flex items-center gap-1 text-sm text-muted-foreground">
      {crumbs.map((crumb, i) => (
        <span key={crumb.to} className="flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3 w-3" />}
          {i < crumbs.length - 1 ? (
            <Link to={crumb.to} className="hover:text-foreground">
              {crumb.label}
            </Link>
          ) : (
            <span className="text-foreground font-medium">{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
```

---

## 5.4 Routing Strategy

```typescript
// src/app/routes.tsx

import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";

const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        path: "/",
        lazy: () => import("@/pages/Dashboard"),
        handle: { breadcrumb: () => ({ label: "Dashboard", to: "/" }) },
      },

      // Dynamic object CRUD — single route config covers ALL node types
      {
        path: "/objects/:nodeType",
        handle: {
          breadcrumb: (match, getNodeType) => {
            const nt = getNodeType(match.params.nodeType!);
            return {
              label: nt?.display_name_plural ?? match.params.nodeType,
              to: match.pathname,
            };
          },
        },
        children: [
          {
            index: true,
            lazy: () => import("@/pages/ObjectList"),
          },
          {
            path: "new",
            lazy: () => import("@/pages/ObjectCreate"),
            handle: { breadcrumb: () => ({ label: "New", to: "" }) },
          },
          {
            path: ":id",
            lazy: () => import("@/pages/ObjectDetail"),
            handle: {
              breadcrumb: (match) => ({
                // The actual label is resolved by the page component from loaded data
                label: match.data?.displayLabel ?? match.params.id,
                to: match.pathname,
              }),
            },
          },
          {
            path: ":id/edit",
            lazy: () => import("@/pages/ObjectEdit"),
            handle: { breadcrumb: () => ({ label: "Edit", to: "" }) },
          },
        ],
      },

      // Query Workbench
      {
        path: "/query",
        lazy: () => import("@/pages/QueryWorkbench"),
        handle: { breadcrumb: () => ({ label: "Query Workbench", to: "/query" }) },
      },
      {
        path: "/query/saved",
        lazy: () => import("@/pages/SavedQueries"),
        handle: { breadcrumb: () => ({ label: "Saved Queries", to: "/query/saved" }) },
      },

      // Graph Explorer
      {
        path: "/graph",
        lazy: () => import("@/pages/GraphExplorer"),
        handle: { breadcrumb: () => ({ label: "Graph Explorer", to: "/graph" }) },
      },

      // Schema Explorer
      {
        path: "/schema",
        lazy: () => import("@/pages/SchemaExplorer"),
        handle: { breadcrumb: () => ({ label: "Schema", to: "/schema" }) },
      },
      {
        path: "/schema/:nodeType",
        lazy: () => import("@/pages/SchemaTypeDetail"),
      },

      // Parsers
      {
        path: "/parsers",
        lazy: () => import("@/pages/ParserRegistry"),
        handle: { breadcrumb: () => ({ label: "Parsers", to: "/parsers" }) },
      },
      {
        path: "/parsers/:id/test",
        lazy: () => import("@/pages/ParserTest"),
      },

      // Ingestion
      {
        path: "/ingestion",
        lazy: () => import("@/pages/IngestionHistory"),
        handle: { breadcrumb: () => ({ label: "Ingestion", to: "/ingestion" }) },
      },

      // Jobs
      {
        path: "/jobs",
        lazy: () => import("@/pages/JobRegistry"),
        handle: { breadcrumb: () => ({ label: "Jobs", to: "/jobs" }) },
      },
      {
        path: "/jobs/:id/runs",
        lazy: () => import("@/pages/JobRunHistory"),
      },
      {
        path: "/jobs/:id/runs/:runId",
        lazy: () => import("@/pages/JobRunDetail"),
      },

      // Git Sources
      {
        path: "/git-sources",
        lazy: () => import("@/pages/GitSources"),
        handle: { breadcrumb: () => ({ label: "Git Sources", to: "/git-sources" }) },
      },

      // Admin
      {
        path: "/admin/rbac",
        lazy: () => import("@/pages/RBACAdmin"),
        handle: { breadcrumb: () => ({ label: "RBAC", to: "/admin/rbac" }) },
      },
      {
        path: "/admin/audit",
        lazy: () => import("@/pages/AuditLog"),
        handle: { breadcrumb: () => ({ label: "Audit Log", to: "/admin/audit" }) },
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
```

Key routing design decisions:

- **Lazy loading everywhere**: Every page is code-split via `lazy()`. The initial bundle contains only the shell, schema store, and router.
- **Single route for all CRUD**: `/objects/:nodeType` handles every node type. No route-per-type. The `nodeType` param drives schema lookup, which drives the entire UI.
- **Breadcrumb handles**: Each route can export a `breadcrumb` function in its `handle`. The `Breadcrumbs` component walks `useMatches()` to build the trail.

---

## 5.5 Graph Visualization Architecture

### 5.5.1 Core Components

```typescript
// src/components/graph/GraphCanvas.tsx

import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type OnNodeClick,
  type OnNodeDoubleClick,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useSchemaStore } from "@/stores/schemaStore";
import { GraphControls } from "./GraphControls";
import { NodeDetailSidebar } from "./NodeDetailSidebar";
import { ContextMenu } from "./ContextMenu";
import { useGraphData } from "@/hooks/useGraphData";
import { applyLayout, type LayoutAlgorithm } from "@/lib/graphLayout";
import { createCustomNodeType, createCustomEdgeType } from "@/lib/graphStyles";

interface GraphCanvasProps {
  initialQuery?: string;              // Cypher query to seed the graph
  centerId?: string;                  // Node ID to center on
  centerType?: string;                // Node type of center
  depth?: number;                     // Expansion depth
}

export function GraphCanvas({ initialQuery, centerId, centerType, depth = 1 }: GraphCanvasProps) {
  const registry = useSchemaStore((s) => s.registry);
  const [layout, setLayout] = useState<LayoutAlgorithm>("dagre");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [maxNodes] = useState(200);

  // Fetch graph data from backend
  const { graphData, expandNode, isLoading } = useGraphData({
    initialQuery,
    centerId,
    centerType,
    depth,
    maxNodes,
  });

  // Generate custom node types from schema — one per node type with correct icon, color, badges
  const nodeTypes = useMemo<NodeTypes>(() => {
    if (!registry) return {};
    return Object.fromEntries(
      Object.values(registry.node_types).map((nt) => [
        nt.name,
        createCustomNodeType(nt),
      ])
    );
  }, [registry]);

  // Generate custom edge types from schema
  const edgeTypes = useMemo<EdgeTypes>(() => {
    if (!registry) return {};
    return Object.fromEntries(
      Object.values(registry.edge_types).map((et) => [
        et.name,
        createCustomEdgeType(et),
      ])
    );
  }, [registry]);

  // Apply layout algorithm to position nodes
  const { layoutNodes, layoutEdges } = useMemo(
    () => applyLayout(graphData.nodes, graphData.edges, layout),
    [graphData, layout]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges);

  // Click: select and show detail sidebar
  const onNodeClick: OnNodeClick = useCallback((_event, node) => {
    setSelectedNodeId(node.id);
  }, []);

  // Double-click: expand neighbors
  const onNodeDoubleClick: OnNodeDoubleClick = useCallback(
    (_event, node) => {
      expandNode(node.id, node.type!);
    },
    [expandNode]
  );

  // Right-click: context menu
  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      event.preventDefault();
      setContextMenu({
        x: event.clientX,
        y: event.clientY,
        nodeId: node.id,
        nodeType: node.type!,
      });
    },
    []
  );

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeContextMenu={onNodeContextMenu}
        onPaneClick={() => {
          setSelectedNodeId(null);
          setContextMenu(null);
        }}
        fitView
        minZoom={0.1}
        maxZoom={4}
        defaultEdgeOptions={{ animated: false }}
      >
        <Background />
        <Controls />
        <MiniMap
          nodeColor={(node) => {
            const nt = registry?.node_types[node.type!];
            return nt?.color ?? "#666";
          }}
        />
      </ReactFlow>

      {/* Toolbar overlay */}
      <GraphControls
        layout={layout}
        onLayoutChange={setLayout}
        nodeCount={nodes.length}
        edgeCount={edges.length}
        maxNodes={maxNodes}
        registry={registry}
      />

      {/* Detail sidebar */}
      {selectedNodeId && (
        <NodeDetailSidebar
          nodeId={selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
        />
      )}

      {/* Context menu */}
      {contextMenu && (
        <ContextMenu
          {...contextMenu}
          onExpand={() => expandNode(contextMenu.nodeId, contextMenu.nodeType)}
          onNavigate={() => window.location.href = `/objects/${contextMenu.nodeType}/${contextMenu.nodeId}`}
          onHide={() => {
            setNodes((ns) => ns.filter((n) => n.id !== contextMenu.nodeId));
            setContextMenu(null);
          }}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}
```

### 5.5.2 Custom Node Components

Each node type gets a custom React Flow node with icon, label, status badge, and the type's color:

```typescript
// src/lib/graphStyles.ts

import { memo, type ComponentType } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { getLucideIcon } from "@/lib/icons";
import type { NodeTypeDefinition, EdgeTypeDefinition } from "@/types/schema";

interface CustomNodeData {
  label: string;
  status?: string;
  statusColor?: string;
  attributes: Record<string, unknown>;
}

export function createCustomNodeType(
  typeDef: NodeTypeDefinition
): ComponentType<NodeProps<CustomNodeData>> {
  const Icon = getLucideIcon(typeDef.icon);
  const sizeMap = { sm: "w-32", md: "w-40", lg: "w-48" };
  const nodeWidth = sizeMap[typeDef.ui_hints.graph_node_size] ?? "w-40";

  const CustomNode = memo(({ data, selected }: NodeProps<CustomNodeData>) => (
    <div
      className={`
        ${nodeWidth} rounded-lg border-2 bg-background shadow-sm
        transition-shadow
        ${selected ? "ring-2 ring-primary shadow-md" : ""}
      `}
      style={{ borderColor: typeDef.color }}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />

      <div className="flex items-center gap-2 p-2">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-md"
          style={{ backgroundColor: typeDef.color + "20", color: typeDef.color }}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium truncate">{data.label}</div>
          <div className="text-[10px] text-muted-foreground">{typeDef.display_name}</div>
        </div>
        {data.status && (
          <div
            className="h-2.5 w-2.5 rounded-full flex-shrink-0"
            style={{ backgroundColor: data.statusColor ?? "#888" }}
            title={data.status}
          />
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  ));

  CustomNode.displayName = `GraphNode_${typeDef.name}`;
  return CustomNode;
}

export function createCustomEdgeType(edgeDef: EdgeTypeDefinition) {
  // Returns a custom edge component with the edge type's color, line style, and optional animation
  // Uses @xyflow/react's BaseEdge or BezierEdge internally
  // Implementation follows the same pattern as custom nodes
  // ...
}
```

### 5.5.3 Layout Algorithms

```typescript
// src/lib/graphLayout.ts

import dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";

export type LayoutAlgorithm = "dagre" | "elk" | "force" | "radial";

export function applyLayout(
  nodes: Node[],
  edges: Edge[],
  algorithm: LayoutAlgorithm
): { layoutNodes: Node[]; layoutEdges: Edge[] } {
  switch (algorithm) {
    case "dagre":
      return applyDagreLayout(nodes, edges);
    case "elk":
      return applyElkLayout(nodes, edges);   // Uses elkjs, async
    case "force":
      return applyForceLayout(nodes, edges);  // Uses d3-force
    case "radial":
      return applyRadialLayout(nodes, edges);
    default:
      return { layoutNodes: nodes, layoutEdges: edges };
  }
}

function applyDagreLayout(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80 });

  for (const node of nodes) {
    g.setNode(node.id, { width: 160, height: 60 });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: { x: pos.x - 80, y: pos.y - 30 },
    };
  });

  return { layoutNodes, layoutEdges: edges };
}
```

### 5.5.4 Graph Data Hook

```typescript
// src/hooks/useGraphData.ts

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { useSchemaStore } from "@/stores/schemaStore";
import type { Node, Edge } from "@xyflow/react";

interface GraphQueryResponse {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  truncated: boolean;            // True if maxNodes limit was hit
  total_nodes: number;
  total_edges: number;
}

interface GraphNodeData {
  id: string;
  type: string;                  // Node type name
  label: string;                 // Pre-rendered from label_template
  status: string | null;
  attributes: Record<string, unknown>;
}

interface GraphEdgeData {
  id: string;
  type: string;                  // Edge type name
  source_id: string;
  target_id: string;
  attributes: Record<string, unknown>;
}

export function useGraphData(opts: {
  initialQuery?: string;
  centerId?: string;
  centerType?: string;
  depth?: number;
  maxNodes: number;
}) {
  const registry = useSchemaStore((s) => s.registry);
  const [graphData, setGraphData] = useState<{ nodes: Node[]; edges: Edge[] }>({
    nodes: [],
    edges: [],
  });
  const [expandedNodeIds] = useState<Set<string>>(new Set());

  // Convert backend graph data to React Flow nodes/edges, merging with existing state
  const mergeGraphData = useCallback(
    (response: GraphQueryResponse) => {
      setGraphData((prev) => {
        const existingNodeIds = new Set(prev.nodes.map((n) => n.id));
        const existingEdgeIds = new Set(prev.edges.map((e) => e.id));

        const newNodes: Node[] = response.nodes
          .filter((n) => !existingNodeIds.has(n.id))
          .map((n) => ({
            id: n.id,
            type: n.type,
            position: { x: 0, y: 0 },          // Layout algorithm positions these
            data: {
              label: n.label,
              status: n.status,
              statusColor: getStatusColor(n.status),
              attributes: n.attributes,
            },
          }));

        const newEdges: Edge[] = response.edges
          .filter((e) => !existingEdgeIds.has(e.id))
          .map((e) => {
            const edgeDef = registry?.edge_types[e.type];
            return {
              id: e.id,
              type: e.type,
              source: e.source_id,
              target: e.target_id,
              label: edgeDef?.display_name,
              style: {
                stroke: edgeDef?.color ?? "#888",
                strokeDasharray: edgeDef?.line_style === "dashed" ? "5,5" :
                                 edgeDef?.line_style === "dotted" ? "2,2" : undefined,
              },
              animated: edgeDef?.animated ?? false,
              data: e.attributes,
            };
          });

        return {
          nodes: [...prev.nodes, ...newNodes],
          edges: [...prev.edges, ...newEdges],
        };
      });
    },
    [registry]
  );

  // Expand a node's neighbors
  const expandMutation = useMutation({
    mutationFn: ({ nodeId, nodeType }: { nodeId: string; nodeType: string }) =>
      apiClient
        .get(`graph/neighbors/${nodeType}/${nodeId}`, {
          searchParams: { depth: "1", max_nodes: String(opts.maxNodes) },
        })
        .json<GraphQueryResponse>(),
    onSuccess: (data) => mergeGraphData(data),
  });

  const expandNode = useCallback(
    (nodeId: string, nodeType: string) => {
      if (expandedNodeIds.has(nodeId)) return;
      expandedNodeIds.add(nodeId);
      expandMutation.mutate({ nodeId, nodeType });
    },
    [expandMutation, expandedNodeIds]
  );

  return {
    graphData,
    expandNode,
    isLoading: expandMutation.isPending,
  };
}

function getStatusColor(status: string | null): string {
  switch (status?.toLowerCase()) {
    case "active":
    case "up":
    case "online":
      return "#22c55e";   // green-500
    case "down":
    case "offline":
    case "failed":
      return "#ef4444";   // red-500
    case "admin_down":
    case "maintenance":
    case "disabled":
      return "#f97316";   // orange-500
    case "planned":
    case "provisioning":
      return "#3b82f6";   // blue-500
    default:
      return "#888888";
  }
}
```

### 5.5.5 Performance Strategy

| Concern | Strategy |
|---|---|
| Large graphs (>200 nodes) | Default render capped at 200 nodes. Pagination controls: "Showing 200 of 1,432 nodes. Load more / Adjust filters." User can increase limit or apply type/attribute filters |
| Off-screen nodes | React Flow's built-in viewport culling. Nodes outside the viewport are not rendered in the DOM |
| Smooth interaction | `useDeferredValue` on filter inputs so layout recalculation does not block typing |
| Edge bundling | For dense graphs, group parallel edges between the same pair of nodes into a single multi-edge |
| Minimap | Renders a simplified SVG at all times for orientation in large graphs |
| Export | Canvas-to-PNG via `html-to-image`, SVG export via React Flow's `toObject()` serialization |

---

## 5.6 Query Workbench Design

### 5.6.1 Layout

Three-panel layout using a resizable split pane (`react-resizable-panels`):

```
+------------------+------------------------------------------+
|  Saved Queries   |  Cypher Editor (Monaco)          [Run]   |
|  (tree view)     |  [Cypher] [Builder] tabs                 |
|                  +------------------------------------------+
|  Templates       |  Results                                 |
|  - Recent        |  [Table] [Graph] [JSON] tabs             |
|  - By category   |  Execution time: 42ms | Rows: 156       |
+------------------+------------------------------------------+
```

### 5.6.2 Cypher Editor

```typescript
// src/components/query/CypherEditor.tsx

import { useRef, useCallback } from "react";
import Editor, { type OnMount, type BeforeMount } from "@monaco-editor/react";
import { cypherLanguageDefinition, cypherTheme } from "@/lib/cypher";
import { useSchemaStore } from "@/stores/schemaStore";
import type { editor, languages } from "monaco-editor";

interface CypherEditorProps {
  value: string;
  onChange: (value: string) => void;
  onExecute: () => void;                     // Triggered by Ctrl+Enter / Cmd+Enter
}

export function CypherEditor({ value, onChange, onExecute }: CypherEditorProps) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const registry = useSchemaStore((s) => s.registry);

  // Register Cypher language and theme before the editor mounts
  const handleBeforeMount: BeforeMount = useCallback((monaco) => {
    // Register language
    monaco.languages.register({ id: "cypher" });
    monaco.languages.setMonarchTokensProvider("cypher", cypherLanguageDefinition);
    monaco.editor.defineTheme("cypher-dark", cypherTheme);

    // Register schema-aware completion provider
    monaco.languages.registerCompletionItemProvider("cypher", {
      provideCompletionItems: (model, position) => {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };

        const suggestions: languages.CompletionItem[] = [];

        if (!registry) return { suggestions };

        // Suggest node type labels after (:  or (n:
        const textBeforeCursor = model.getValueInRange({
          startLineNumber: position.lineNumber,
          startColumn: 1,
          endLineNumber: position.lineNumber,
          endColumn: position.column,
        });

        if (/\(\w*:$/.test(textBeforeCursor) || /\(:$/.test(textBeforeCursor)) {
          for (const nt of Object.values(registry.node_types)) {
            suggestions.push({
              label: nt.name,
              kind: monaco.languages.CompletionItemKind.Class,
              detail: nt.display_name,
              documentation: nt.description,
              insertText: nt.name,
              range,
            });
          }
        }

        // Suggest relationship types after -[:  or -[r:
        if (/-\[\w*:$/.test(textBeforeCursor)) {
          for (const et of Object.values(registry.edge_types)) {
            suggestions.push({
              label: et.name.toUpperCase(),
              kind: monaco.languages.CompletionItemKind.Function,
              detail: `${et.source_type} → ${et.target_type}`,
              insertText: et.name.toUpperCase(),
              range,
            });
          }
        }

        // Suggest property names after a dot
        if (/\.\w*$/.test(textBeforeCursor)) {
          // Attempt to resolve the variable type from context (basic heuristic)
          const allAttributes = new Set<string>();
          for (const nt of Object.values(registry.node_types)) {
            for (const attr of nt.attributes) {
              allAttributes.add(attr.name);
            }
          }
          for (const attrName of allAttributes) {
            suggestions.push({
              label: attrName,
              kind: monaco.languages.CompletionItemKind.Property,
              insertText: attrName,
              range,
            });
          }
        }

        // Suggest Cypher keywords
        const keywords = [
          "MATCH", "WHERE", "RETURN", "WITH", "ORDER BY", "LIMIT", "SKIP",
          "CREATE", "MERGE", "SET", "DELETE", "DETACH DELETE", "REMOVE",
          "OPTIONAL MATCH", "UNWIND", "FOREACH", "CALL", "YIELD",
          "AND", "OR", "NOT", "IN", "STARTS WITH", "ENDS WITH", "CONTAINS",
          "IS NULL", "IS NOT NULL", "AS", "DISTINCT", "COUNT", "COLLECT",
          "EXPLAIN", "PROFILE",
        ];
        for (const kw of keywords) {
          suggestions.push({
            label: kw,
            kind: monaco.languages.CompletionItemKind.Keyword,
            insertText: kw,
            range,
          });
        }

        return { suggestions };
      },
    });
  }, [registry]);

  const handleMount: OnMount = useCallback(
    (editor) => {
      editorRef.current = editor;

      // Bind Ctrl+Enter / Cmd+Enter to execute query
      editor.addAction({
        id: "execute-query",
        label: "Execute Query",
        keybindings: [
          // monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter
          2048 | 3,
        ],
        run: () => onExecute(),
      });
    },
    [onExecute]
  );

  return (
    <Editor
      height="300px"
      language="cypher"
      theme="cypher-dark"
      value={value}
      onChange={(v) => onChange(v ?? "")}
      beforeMount={handleBeforeMount}
      onMount={handleMount}
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        wordWrap: "on",
        tabSize: 2,
        suggestOnTriggerCharacters: true,
        quickSuggestions: true,
        parameterHints: { enabled: true },
      }}
    />
  );
}
```

### 5.6.3 Cypher Language Definition

```typescript
// src/lib/cypher.ts — Monarch tokenizer for Cypher

import type { languages, editor } from "monaco-editor";

export const cypherLanguageDefinition: languages.IMonarchLanguage = {
  defaultToken: "",
  ignoreCase: true,

  keywords: [
    "MATCH", "OPTIONAL", "WHERE", "RETURN", "WITH", "ORDER", "BY",
    "LIMIT", "SKIP", "CREATE", "MERGE", "DELETE", "DETACH", "SET",
    "REMOVE", "FOREACH", "UNWIND", "CALL", "YIELD", "UNION",
    "AS", "DISTINCT", "ON", "CASE", "WHEN", "THEN", "ELSE", "END",
    "AND", "OR", "XOR", "NOT", "IN", "STARTS", "ENDS", "CONTAINS",
    "IS", "NULL", "TRUE", "FALSE", "COUNT", "COLLECT", "SUM", "AVG",
    "MIN", "MAX", "EXISTS", "ALL", "ANY", "NONE", "SINGLE",
    "EXPLAIN", "PROFILE",
  ],

  typeKeywords: [
    "String", "Integer", "Float", "Boolean", "Date", "DateTime",
    "Duration", "Point", "List", "Map",
  ],

  operators: [
    "=", "<>", "<", ">", "<=", ">=", "+", "-", "*", "/", "%", "^",
    "=~", ".", ":", "|",
  ],

  tokenizer: {
    root: [
      // Node labels after colon: (:Device)
      [/:[A-Z]\w*/, "type.identifier"],
      // Relationship types: -[:CONNECTED_TO]->
      [/\[:\w+\]/, "type.identifier"],
      // Parameters: $paramName
      [/\$\w+/, "variable"],
      // Identifiers and keywords
      [
        /[a-zA-Z_]\w*/,
        {
          cases: {
            "@keywords": "keyword",
            "@typeKeywords": "type",
            "@default": "identifier",
          },
        },
      ],
      // Numbers
      [/\d+\.\d*/, "number.float"],
      [/\d+/, "number"],
      // Strings
      [/"/, { token: "string.quote", bracket: "@open", next: "@string_double" }],
      [/'/, { token: "string.quote", bracket: "@open", next: "@string_single" }],
      // Comments
      [/\/\/.*$/, "comment"],
      // Operators
      [/[<>]=?|<>|=~?|\+|-|\*|\/|%|\^/, "operator"],
      // Delimiters
      [/[{}()\[\]]/, "@brackets"],
      [/[,;.]/, "delimiter"],
    ],

    string_double: [
      [/[^"\\]+/, "string"],
      [/\\./, "string.escape"],
      [/"/, { token: "string.quote", bracket: "@close", next: "@pop" }],
    ],

    string_single: [
      [/[^'\\]+/, "string"],
      [/\\./, "string.escape"],
      [/'/, { token: "string.quote", bracket: "@close", next: "@pop" }],
    ],
  },
};

export const cypherTheme: editor.IStandaloneThemeData = {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "keyword", foreground: "569CD6", fontStyle: "bold" },
    { token: "type.identifier", foreground: "4EC9B0" },
    { token: "identifier", foreground: "D4D4D4" },
    { token: "variable", foreground: "CE9178" },
    { token: "string", foreground: "CE9178" },
    { token: "string.escape", foreground: "D7BA7D" },
    { token: "number", foreground: "B5CEA8" },
    { token: "number.float", foreground: "B5CEA8" },
    { token: "operator", foreground: "D4D4D4" },
    { token: "comment", foreground: "6A9955", fontStyle: "italic" },
    { token: "type", foreground: "4EC9B0" },
  ],
  colors: {
    "editor.background": "#1E1E1E",
  },
};
```

### 5.6.4 Structured Query Builder

For users who do not know Cypher, a form-based query builder that generates Cypher:

```typescript
// src/components/query/StructuredQueryBuilder.tsx — data model

interface StructuredQuery {
  /** Root node match */
  rootType: string;                        // e.g., "device"
  rootAlias: string;                       // e.g., "d"
  filters: QueryFilter[];                  // WHERE clauses on root
  /** Optional relationship traversals */
  traversals: QueryTraversal[];
  /** Fields to return */
  returnFields: ReturnField[];
  /** Sorting */
  orderBy: { field: string; direction: "asc" | "desc" }[];
  limit: number;
}

interface QueryFilter {
  attribute: string;
  operator: "eq" | "neq" | "contains" | "starts_with" | "ends_with"
           | "gt" | "gte" | "lt" | "lte" | "in" | "is_null" | "is_not_null"
           | "regex";
  value: unknown;
}

interface QueryTraversal {
  edgeType: string;
  direction: "outgoing" | "incoming" | "both";
  targetType: string;
  alias: string;
  filters: QueryFilter[];                  // Filters on traversed nodes
}

interface ReturnField {
  alias: string;                           // Node alias (d, i, s)
  attribute: string;                       // Attribute name
  displayAs: string | null;                // Column alias
}

/**
 * Generates Cypher from the structured query model.
 * Example output:
 *   MATCH (d:device)-[:has_interface]->(i:interface)
 *   WHERE d.site = "NYC" AND i.status = "active"
 *   RETURN d.hostname, i.name, i.ip_address
 *   ORDER BY d.hostname ASC
 *   LIMIT 100
 */
function toCypher(query: StructuredQuery): string {
  const parts: string[] = [];

  // MATCH clause
  let matchPattern = `(${query.rootAlias}:${query.rootType})`;
  for (const t of query.traversals) {
    const arrow = t.direction === "outgoing" ? `-[:${t.edgeType}]->`
                : t.direction === "incoming" ? `<-[:${t.edgeType}]-`
                : `-[:${t.edgeType}]-`;
    matchPattern += `${arrow}(${t.alias}:${t.targetType})`;
  }
  parts.push(`MATCH ${matchPattern}`);

  // WHERE clause
  const allFilters = [
    ...query.filters.map((f) => filterToCypher(query.rootAlias, f)),
    ...query.traversals.flatMap((t) =>
      t.filters.map((f) => filterToCypher(t.alias, f))
    ),
  ];
  if (allFilters.length > 0) {
    parts.push(`WHERE ${allFilters.join(" AND ")}`);
  }

  // RETURN clause
  const returnExprs = query.returnFields.map((rf) => {
    const expr = `${rf.alias}.${rf.attribute}`;
    return rf.displayAs ? `${expr} AS ${rf.displayAs}` : expr;
  });
  parts.push(`RETURN ${returnExprs.join(", ")}`);

  // ORDER BY
  if (query.orderBy.length > 0) {
    const orderExprs = query.orderBy.map(
      (o) => `${o.field} ${o.direction.toUpperCase()}`
    );
    parts.push(`ORDER BY ${orderExprs.join(", ")}`);
  }

  // LIMIT
  parts.push(`LIMIT ${query.limit}`);

  return parts.join("\n");
}

function filterToCypher(alias: string, filter: QueryFilter): string {
  const prop = `${alias}.${filter.attribute}`;
  switch (filter.operator) {
    case "eq":          return `${prop} = ${quote(filter.value)}`;
    case "neq":         return `${prop} <> ${quote(filter.value)}`;
    case "contains":    return `${prop} CONTAINS ${quote(filter.value)}`;
    case "starts_with": return `${prop} STARTS WITH ${quote(filter.value)}`;
    case "ends_with":   return `${prop} ENDS WITH ${quote(filter.value)}`;
    case "gt":          return `${prop} > ${filter.value}`;
    case "gte":         return `${prop} >= ${filter.value}`;
    case "lt":          return `${prop} < ${filter.value}`;
    case "lte":         return `${prop} <= ${filter.value}`;
    case "in":          return `${prop} IN [${(filter.value as unknown[]).map(quote).join(", ")}]`;
    case "is_null":     return `${prop} IS NULL`;
    case "is_not_null": return `${prop} IS NOT NULL`;
    case "regex":       return `${prop} =~ ${quote(filter.value)}`;
    default:            return `${prop} = ${quote(filter.value)}`;
  }
}

function quote(value: unknown): string {
  if (typeof value === "string") return `"${value.replace(/"/g, '\\"')}"`;
  return String(value);
}
```

### 5.6.5 Query Results

```typescript
// src/components/query/QueryResults.tsx — result views

interface QueryResultData {
  columns: string[];
  rows: Record<string, unknown>[];
  metadata: {
    execution_time_ms: number;
    row_count: number;
    query_plan: string | null;         // Present if EXPLAIN/PROFILE was used
  };
  graph_data: {                         // Present if query returns nodes/edges
    nodes: GraphNodeData[];
    edges: GraphEdgeData[];
  } | null;
}

// The results panel renders three views toggled by tabs:
//
// 1. Table View — TanStack Table with columns derived from result columns[].
//    Supports column resizing, sorting (client-side on current page), and CSV export.
//
// 2. Graph View — GraphCanvas component seeded with graph_data (when the query
//    returns graph elements rather than scalar projections).
//
// 3. JSON View — raw JSON display of the result rows, using a read-only Monaco
//    editor with JSON language for syntax highlighting and collapsible sections.
//
// The metadata bar at the bottom shows: execution time, row count, and a
// "View Query Plan" button (if EXPLAIN data is available).
```

---

## 5.7 Real-time Updates

### 5.7.1 WebSocket Hook

```typescript
// src/hooks/useWebSocket.ts

import { useEffect, useRef, useState, useCallback } from "react";

interface WebSocketMessage {
  type: string;                              // e.g., "schema.changed", "job.status", "sync.complete"
  payload: Record<string, unknown>;
  timestamp: string;
}

interface UseWebSocketReturn {
  lastMessage: WebSocketMessage | null;
  connectionState: "connecting" | "connected" | "disconnected" | "reconnecting";
  send: (message: unknown) => void;
}

const WS_BASE_URL = import.meta.env.VITE_WS_URL ?? `ws://${window.location.host}/api/v1/ws`;

/**
 * Subscribes to a WebSocket channel. Handles reconnection with exponential backoff.
 *
 * @param channel - Channel to subscribe to: "schema", "jobs", "sync", or "*" for all
 */
export function useWebSocket(channel: string): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>();
  const reconnectAttempts = useRef(0);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [connectionState, setConnectionState] =
    useState<UseWebSocketReturn["connectionState"]>("connecting");

  const connect = useCallback(() => {
    const ws = new WebSocket(`${WS_BASE_URL}?channel=${channel}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState("connected");
      reconnectAttempts.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as WebSocketMessage;
        setLastMessage(message);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      if (event.code === 1000) {
        setConnectionState("disconnected");
        return;
      }
      // Reconnect with exponential backoff: 1s, 2s, 4s, 8s, max 30s
      setConnectionState("reconnecting");
      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
      reconnectAttempts.current++;
      reconnectTimeout.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [channel]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimeout.current);
      wsRef.current?.close(1000, "Component unmounted");
    };
  }, [connect]);

  const send = useCallback((message: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { lastMessage, connectionState, send };
}
```

### 5.7.2 Event Integration Points

| Event | Source | Consumer | Action |
|---|---|---|---|
| `schema.changed` | Schema mutation API / migration | `useSchemaRegistry` | Refetch `/api/v1/schema/ui-metadata`, update Zustand store; sidebar re-renders with new/removed types |
| `job.status` | Job runner | Job list page, notification bell | Update job row status badge in real time; show toast on completion/failure |
| `job.progress` | Job runner (long jobs) | Job detail page | Update progress bar percentage |
| `sync.complete` | Git sync worker | Git Sources page | Update last sync timestamp and status |
| `sync.error` | Git sync worker | Git Sources page, notification bell | Show error toast, update status to failed |
| `ingestion.complete` | Parser pipeline | Ingestion history | Append new ingestion result row |

---

## 5.8 Network-Specific UX

### 5.8.1 IP Address Components

```typescript
// src/components/renderers/IPRenderers.tsx

import { forwardRef } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Copy } from "lucide-react";
import type { DisplayRendererProps, EditRendererProps } from "@/lib/fieldRenderers";

/** Display: monospace text with copy button, color-coded version badge */
export function IPDisplay({ value }: DisplayRendererProps) {
  if (value == null) return <span className="text-muted-foreground">-</span>;
  const str = String(value);
  const version = str.includes(":") ? "v6" : "v4";

  return (
    <span className="inline-flex items-center gap-1.5">
      <code className="font-mono text-sm">{str}</code>
      <Badge variant="outline" className="text-[10px] px-1 py-0">
        {version}
      </Badge>
      <button
        onClick={(e) => {
          e.stopPropagation();
          navigator.clipboard.writeText(str);
        }}
        className="opacity-0 group-hover:opacity-100 transition-opacity"
        title="Copy to clipboard"
      >
        <Copy className="h-3 w-3 text-muted-foreground" />
      </button>
    </span>
  );
}

/** Edit: validates IPv4 and IPv6, shows inline error for malformed input */
export function IPInput({ field, error, attribute }: EditRendererProps) {
  return (
    <Input
      {...field}
      value={String(field.value ?? "")}
      onChange={(e) => field.onChange(e.target.value)}
      placeholder={attribute.ui_hints.form_placeholder ?? "e.g., 192.168.1.1 or 2001:db8::1"}
      className={`font-mono ${error ? "border-destructive" : ""}`}
      autoComplete="off"
      spellCheck={false}
    />
  );
}
```

### 5.8.2 Natural Sort for Interface Names

Network interfaces must sort naturally: `Gi0/0/1 < Gi0/0/2 < Gi0/0/10` (not lexicographic `Gi0/0/1 < Gi0/0/10 < Gi0/0/2`).

```typescript
// src/lib/naturalSort.ts

/**
 * Natural sort comparator that handles network interface naming conventions.
 * Splits strings into alphabetic and numeric segments and compares segment by segment.
 *
 * Examples:
 *   Gi0/0/1  < Gi0/0/2   < Gi0/0/10
 *   eth0     < eth1       < eth10
 *   Vlan100  < Vlan200    < Vlan1000
 *   xe-0/0/0 < xe-0/0/1  < xe-1/0/0
 */
export function naturalCompare(a: string, b: string): number {
  const segmentsA = tokenize(a);
  const segmentsB = tokenize(b);

  for (let i = 0; i < Math.max(segmentsA.length, segmentsB.length); i++) {
    const sa = segmentsA[i];
    const sb = segmentsB[i];

    if (sa === undefined) return -1;
    if (sb === undefined) return 1;

    if (sa.type === "number" && sb.type === "number") {
      const diff = sa.numValue - sb.numValue;
      if (diff !== 0) return diff;
    } else {
      const cmp = sa.strValue.localeCompare(sb.strValue);
      if (cmp !== 0) return cmp;
    }
  }
  return 0;
}

interface Segment {
  type: "string" | "number";
  strValue: string;
  numValue: number;
}

function tokenize(s: string): Segment[] {
  const segments: Segment[] = [];
  const regex = /(\d+)|(\D+)/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(s)) !== null) {
    if (match[1]) {
      segments.push({ type: "number", strValue: match[1], numValue: parseInt(match[1], 10) });
    } else {
      segments.push({ type: "string", strValue: match[2], numValue: 0 });
    }
  }
  return segments;
}
```

### 5.8.3 Status Color Coding

Consistent status colors applied across tables, graph nodes, and badges:

```typescript
// src/lib/statusColors.ts

export interface StatusStyle {
  bg: string;          // Tailwind bg class
  text: string;        // Tailwind text class
  dot: string;         // Hex color for graph node dots
  label: string;       // Human-readable label
}

const STATUS_MAP: Record<string, StatusStyle> = {
  active:        { bg: "bg-green-100",  text: "text-green-800",  dot: "#22c55e", label: "Active" },
  up:            { bg: "bg-green-100",  text: "text-green-800",  dot: "#22c55e", label: "Up" },
  online:        { bg: "bg-green-100",  text: "text-green-800",  dot: "#22c55e", label: "Online" },
  connected:     { bg: "bg-green-100",  text: "text-green-800",  dot: "#22c55e", label: "Connected" },
  down:          { bg: "bg-red-100",    text: "text-red-800",    dot: "#ef4444", label: "Down" },
  offline:       { bg: "bg-red-100",    text: "text-red-800",    dot: "#ef4444", label: "Offline" },
  failed:        { bg: "bg-red-100",    text: "text-red-800",    dot: "#ef4444", label: "Failed" },
  error:         { bg: "bg-red-100",    text: "text-red-800",    dot: "#ef4444", label: "Error" },
  admin_down:    { bg: "bg-orange-100", text: "text-orange-800", dot: "#f97316", label: "Admin Down" },
  maintenance:   { bg: "bg-orange-100", text: "text-orange-800", dot: "#f97316", label: "Maintenance" },
  disabled:      { bg: "bg-orange-100", text: "text-orange-800", dot: "#f97316", label: "Disabled" },
  decommissioned:{ bg: "bg-orange-100", text: "text-orange-800", dot: "#f97316", label: "Decommissioned" },
  planned:       { bg: "bg-blue-100",   text: "text-blue-800",   dot: "#3b82f6", label: "Planned" },
  provisioning:  { bg: "bg-blue-100",   text: "text-blue-800",   dot: "#3b82f6", label: "Provisioning" },
  staged:        { bg: "bg-blue-100",   text: "text-blue-800",   dot: "#3b82f6", label: "Staged" },
  unknown:       { bg: "bg-gray-100",   text: "text-gray-800",   dot: "#888888", label: "Unknown" },
};

export function getStatusStyle(status: string | null | undefined): StatusStyle {
  if (!status) return STATUS_MAP.unknown;
  return STATUS_MAP[status.toLowerCase()] ?? STATUS_MAP.unknown;
}
```

### 5.8.4 Configuration Diff View

For node types with `enable_config_diff: true` (e.g., device configurations), the detail page includes a diff viewer comparing the current config against a previous version or a rendered template:

```typescript
// Rendered using @monaco-editor/react in diff mode:
//
// import { DiffEditor } from "@monaco-editor/react";
//
// <DiffEditor
//   original={previousConfig}
//   modified={currentConfig}
//   language="text"      // or "cisco-ios", "junos" if we register custom languages
//   options={{
//     readOnly: true,
//     renderSideBySide: true,
//     minimap: { enabled: false },
//   }}
// />
//
// Version selector dropdown allows choosing which historical version to diff against.
// Versions come from the audit/changelog API for the node.
```

### 5.8.5 Topology-Aware Graph Layouts

When viewing network topology, the layout engine applies domain-aware heuristics:

1. **Layer grouping**: Nodes with a `role` attribute (e.g., "spine", "leaf", "access", "core") are grouped into horizontal layers using dagre's `rank` assignment.
2. **Site clustering**: If the graph spans multiple sites, nodes are clustered into subgraphs per site with visible group boundaries.
3. **Interface alignment**: When showing device-to-device connections via interfaces, interfaces are positioned on the edges of their parent device node.

---

## 5.9 Component Architecture

### 5.9.1 Directory Structure

```
src/
├── app/
│   ├── App.tsx                          # Root component: <RouterProvider>
│   ├── routes.tsx                       # Route definitions (Section 5.4)
│   └── providers.tsx                    # Composition root for providers
│
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx                 # <Sidebar> + <TopBar> + <Outlet>
│   │   ├── Sidebar.tsx                  # Schema-driven navigation (Section 5.3.1)
│   │   ├── TopBar.tsx                   # Search, user menu, notifications
│   │   └── Breadcrumbs.tsx             # Route-aware breadcrumbs (Section 5.3.3)
│   │
│   ├── dynamic/
│   │   ├── DynamicListPage.tsx          # Schema-driven data table (Section 5.2.5)
│   │   ├── DynamicDetailPage.tsx        # Schema-driven detail view (Section 5.2.5)
│   │   ├── DynamicFormPage.tsx          # Schema-driven form (Section 5.2.5)
│   │   ├── DynamicRelationshipPanel.tsx # Edge CRUD panel (Section 5.2.5)
│   │   └── FieldRenderer.tsx           # Type-dispatch component (Section 5.2.3)
│   │
│   ├── renderers/                       # One file per attribute type
│   │   ├── TextRenderers.tsx            # TextDisplay, TextInput
│   │   ├── TextAreaRenderers.tsx        # TextAreaDisplay, TextAreaInput
│   │   ├── NumberRenderers.tsx          # NumberDisplay, NumberInput
│   │   ├── BooleanRenderers.tsx         # BooleanBadge, Toggle
│   │   ├── DateTimeRenderers.tsx        # DateTimeDisplay, DateTimePicker
│   │   ├── EnumRenderers.tsx            # EnumBadge, EnumSelect
│   │   ├── ReferenceRenderers.tsx       # ReferenceLink, ReferenceSelector
│   │   ├── JsonDisplay.tsx              # Read-only JSON tree (lazy loaded)
│   │   ├── JsonEditor.tsx              # Monaco JSON editor (lazy loaded)
│   │   ├── IPRenderers.tsx              # IPDisplay, IPInput (Section 5.8.1)
│   │   ├── CIDRRenderers.tsx            # CIDRDisplay, CIDRInput
│   │   ├── MACRenderers.tsx             # MACDisplay, MACInput
│   │   ├── URLRenderers.tsx             # URLDisplay (clickable link), URLInput
│   │   ├── EmailRenderers.tsx           # EmailDisplay (mailto link), EmailInput
│   │   └── ListRenderers.tsx            # ListStringDisplay/Input, ListIntegerDisplay/Input
│   │
│   ├── graph/
│   │   ├── GraphCanvas.tsx              # Main graph view (Section 5.5.1)
│   │   ├── GraphControls.tsx            # Layout selector, filters, export toolbar
│   │   ├── GraphMiniView.tsx            # Embedded graph on detail pages
│   │   ├── NodeDetailSidebar.tsx        # Slide-over with node details
│   │   └── ContextMenu.tsx              # Right-click menu on graph nodes
│   │
│   ├── query/
│   │   ├── CypherEditor.tsx             # Monaco Cypher editor (Section 5.6.2)
│   │   ├── StructuredQueryBuilder.tsx   # Form-based query builder (Section 5.6.4)
│   │   ├── QueryResults.tsx             # Table/Graph/JSON result views (Section 5.6.5)
│   │   └── SavedQueries.tsx             # Tree view of saved/template queries
│   │
│   ├── common/
│   │   ├── DataTable.tsx                # Reusable TanStack Table wrapper with our styling
│   │   ├── FilterBar.tsx                # Dynamic filter builder from attribute definitions
│   │   ├── SearchBar.tsx                # Global search (Command/cmdk palette)
│   │   └── StatusBadge.tsx              # Status-colored badge component
│   │
│   └── ui/                              # shadcn/ui primitives (generated, not hand-written)
│       ├── button.tsx
│       ├── input.tsx
│       ├── dialog.tsx
│       ├── dropdown-menu.tsx
│       ├── badge.tsx
│       ├── skeleton.tsx
│       ├── tabs.tsx
│       ├── command.tsx                  # cmdk-based command palette
│       ├── collapsible.tsx
│       └── ... (other shadcn/ui components as needed)
│
├── hooks/
│   ├── useSchemaRegistry.ts             # Schema fetch + WS refresh (Section 5.2.2)
│   ├── useNodes.ts                      # CRUD hooks for node instances
│   ├── useEdges.ts                      # CRUD hooks for relationships
│   ├── useGraphData.ts                  # Graph data fetching + expansion (Section 5.5.4)
│   ├── useGraphQuery.ts                 # Execute Cypher queries
│   └── useWebSocket.ts                  # WebSocket with reconnect (Section 5.7.1)
│
├── stores/
│   ├── schemaStore.ts                   # Zustand schema registry (Section 5.2.2)
│   └── uiStore.ts                       # UI preferences (theme, sidebar collapsed, table density)
│
├── pages/                               # Thin page components that compose dynamic components
│   ├── Dashboard.tsx
│   ├── ObjectList.tsx                   # Renders <DynamicListPage />
│   ├── ObjectCreate.tsx                 # Renders <DynamicFormPage mode="create" />
│   ├── ObjectDetail.tsx                 # Renders <DynamicDetailPage />
│   ├── ObjectEdit.tsx                   # Renders <DynamicFormPage mode="edit" />
│   ├── QueryWorkbench.tsx
│   ├── SavedQueries.tsx
│   ├── GraphExplorer.tsx
│   ├── SchemaExplorer.tsx
│   ├── SchemaTypeDetail.tsx
│   ├── ParserRegistry.tsx
│   ├── ParserTest.tsx
│   ├── IngestionHistory.tsx
│   ├── JobRegistry.tsx
│   ├── JobRunHistory.tsx
│   ├── JobRunDetail.tsx
│   ├── GitSources.tsx
│   ├── RBACAdmin.tsx
│   └── AuditLog.tsx
│
├── api/
│   └── client.ts                        # ky-based HTTP client with auth interceptor
│
├── types/
│   ├── schema.ts                        # Schema metadata types (Section 5.2.1)
│   └── api.ts                           # API response/request types
│
└── lib/
    ├── fieldRenderers.ts                # Component registry (Section 5.2.3)
    ├── zodSchemaBuilder.ts              # Dynamic Zod schema generation (Section 5.2.4)
    ├── graphStyles.ts                   # Custom node/edge factories (Section 5.5.2)
    ├── graphLayout.ts                   # Layout algorithms (Section 5.5.3)
    ├── cypher.ts                        # Cypher language for Monaco (Section 5.6.3)
    ├── naturalSort.ts                   # Interface name sorting (Section 5.8.2)
    ├── statusColors.ts                  # Status color mapping (Section 5.8.3)
    └── icons.ts                         # Lucide icon lookup by string name
```

### 5.9.2 Providers Composition

```typescript
// src/app/providers.tsx

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
      staleTime: 30_000,                    // 30 seconds default
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,                              // Do not retry mutations
    },
  },
});

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" storageKey="netgraphy-theme">
        {children}
        <Toaster />
      </ThemeProvider>
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
```

### 5.9.3 API Client

```typescript
// src/api/client.ts

import ky from "ky";

const API_BASE = import.meta.env.VITE_API_URL ?? "/api/v1";

export const apiClient = ky.create({
  prefixUrl: API_BASE,
  timeout: 30_000,
  retry: {
    limit: 2,
    methods: ["get"],                       // Only retry idempotent methods
    statusCodes: [408, 500, 502, 503, 504],
  },
  hooks: {
    beforeRequest: [
      (request) => {
        // Attach auth token from cookie or localStorage
        const token = getAuthToken();
        if (token) {
          request.headers.set("Authorization", `Bearer ${token}`);
        }
      },
    ],
    afterResponse: [
      async (_request, _options, response) => {
        if (response.status === 401) {
          // Redirect to login
          window.location.href = "/login";
        }
      },
    ],
    beforeError: [
      async (error) => {
        // Attempt to parse backend error response for user-friendly messages
        try {
          const body = await error.response.json() as { detail?: string };
          if (body.detail) {
            error.message = body.detail;
          }
        } catch {
          // Response was not JSON; keep default error message
        }
        return error;
      },
    ],
  },
});

function getAuthToken(): string | null {
  return localStorage.getItem("netgraphy-auth-token");
}
```

### 5.9.4 Data Fetching Hooks

```typescript
// src/hooks/useNodes.ts

import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { toast } from "sonner";

/** Fetch a paginated list of nodes */
export function useNodeList(
  nodeType: string,
  params: Record<string, string>
) {
  return useQuery({
    queryKey: ["objects", nodeType, params],
    queryFn: () => apiClient.get(`objects/${nodeType}`, { searchParams: params }).json(),
    placeholderData: keepPreviousData,
  });
}

/** Fetch a single node by ID */
export function useNode(nodeType: string, id: string) {
  return useQuery({
    queryKey: ["objects", nodeType, id],
    queryFn: () => apiClient.get(`objects/${nodeType}/${id}`).json(),
    enabled: !!id,
  });
}

/** Create a new node */
export function useCreateNode(nodeType: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiClient.post(`objects/${nodeType}`, { json: data }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["objects", nodeType] });
      toast.success("Created successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to create: ${error.message}`);
    },
  });
}

/** Update an existing node (PATCH) */
export function useUpdateNode(nodeType: string, id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiClient.patch(`objects/${nodeType}/${id}`, { json: data }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["objects", nodeType, id] });
      qc.invalidateQueries({ queryKey: ["objects", nodeType], exact: false });
      toast.success("Saved successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to save: ${error.message}`);
    },
  });
}

/** Delete a node */
export function useDeleteNode(nodeType: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiClient.delete(`objects/${nodeType}/${id}`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["objects", nodeType] });
      toast.success("Deleted successfully");
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete: ${error.message}`);
    },
  });
}
```

### 5.9.5 UI Preferences Store

```typescript
// src/stores/uiStore.ts

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UIState {
  sidebarCollapsed: boolean;
  tableDensity: "compact" | "normal" | "comfortable";
  graphDefaultLayout: "dagre" | "elk" | "force" | "radial";
  queryResultsView: "table" | "graph" | "json";
  recentNodeTypes: string[];               // Last 10 visited node types for quick access

  toggleSidebar: () => void;
  setTableDensity: (density: UIState["tableDensity"]) => void;
  setGraphDefaultLayout: (layout: UIState["graphDefaultLayout"]) => void;
  setQueryResultsView: (view: UIState["queryResultsView"]) => void;
  addRecentNodeType: (nodeType: string) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      tableDensity: "normal",
      graphDefaultLayout: "dagre",
      queryResultsView: "table",
      recentNodeTypes: [],

      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

      setTableDensity: (density) => set({ tableDensity: density }),

      setGraphDefaultLayout: (layout) => set({ graphDefaultLayout: layout }),

      setQueryResultsView: (view) => set({ queryResultsView: view }),

      addRecentNodeType: (nodeType) =>
        set((s) => ({
          recentNodeTypes: [
            nodeType,
            ...s.recentNodeTypes.filter((t) => t !== nodeType),
          ].slice(0, 10),
        })),
    }),
    { name: "netgraphy-ui" }
  )
);
```

---

## 5.10 Build and Bundle Strategy

### 5.10.1 Code Splitting

| Chunk | Contents | Load Trigger |
|---|---|---|
| `vendor-react` | React, React DOM, React Router | Always (initial) |
| `vendor-query` | TanStack Query | Always (initial) |
| `app-shell` | AppShell, Sidebar, TopBar, Breadcrumbs, schema store | Always (initial) |
| `dynamic-core` | FieldRenderer, field registry, lightweight renderers | First object page visit |
| `graph` | @xyflow/react, layout algorithms, custom nodes | Graph Explorer or detail page graph tab |
| `monaco` | Monaco editor, Cypher language | Query Workbench |
| `json-editor` | Monaco JSON mode | JSON attribute editing |
| `page-*` | Each page component | Route navigation |

### 5.10.2 Vite Configuration Highlights

```typescript
// vite.config.ts — relevant sections

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-query": ["@tanstack/react-query"],
          "vendor-table": ["@tanstack/react-table"],
          "vendor-graph": ["@xyflow/react"],
          "vendor-monaco": ["monaco-editor"],
        },
      },
    },
    target: "es2022",
    sourcemap: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/api/v1/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
```

### 5.10.3 Target Bundle Sizes

| Chunk | Target (gzipped) |
|---|---|
| Initial load (shell + vendors) | < 120 KB |
| Dynamic core (renderers + forms) | < 40 KB |
| Graph visualization | < 80 KB |
| Monaco editor | < 150 KB (lazy, only on query page) |
| Total initial TTI | < 200 KB transferred |
