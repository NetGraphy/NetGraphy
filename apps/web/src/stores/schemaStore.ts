/**
 * Schema Registry Store — caches schema metadata from the API.
 *
 * This is the central source of truth for the frontend's understanding
 * of what node types, edge types, and attributes exist. It powers the
 * entire dynamic UI system: navigation, forms, tables, graph views.
 *
 * Refreshed on startup and on schema.changed WebSocket events.
 */

import { create } from "zustand";
import { schemaApi } from "@/api/client";
import type {
  NodeTypeDefinition,
  EdgeTypeDefinition,
  Category,
  UIMetadata,
} from "@/types/schema";

interface SchemaState {
  nodeTypes: Record<string, NodeTypeDefinition>;
  edgeTypes: Record<string, EdgeTypeDefinition>;
  categories: Category[];
  loaded: boolean;
  loading: boolean;
  error: string | null;

  // Actions
  loadSchema: () => Promise<void>;
  getNodeType: (name: string) => NodeTypeDefinition | undefined;
  getEdgeType: (name: string) => EdgeTypeDefinition | undefined;
  getEdgesForNodeType: (nodeType: string) => EdgeTypeDefinition[];
  getListColumns: (nodeType: string) => { name: string; attr: import("@/types/schema").AttributeDefinition }[];
}

export const useSchemaStore = create<SchemaState>((set, get) => ({
  nodeTypes: {},
  edgeTypes: {},
  categories: [],
  loaded: false,
  loading: false,
  error: null,

  loadSchema: async () => {
    set({ loading: true, error: null });
    try {
      const response = await schemaApi.getUIMetadata();
      const data: UIMetadata = response.data.data;

      const nodeTypes: Record<string, NodeTypeDefinition> = {};
      for (const nt of data.node_types) {
        nodeTypes[nt.metadata.name] = nt;
      }

      const edgeTypes: Record<string, EdgeTypeDefinition> = {};
      for (const et of data.edge_types) {
        edgeTypes[et.metadata.name] = et;
      }

      set({
        nodeTypes,
        edgeTypes,
        categories: data.categories,
        loaded: true,
        loading: false,
      });
    } catch (err) {
      set({ error: String(err), loading: false });
    }
  },

  getNodeType: (name: string) => get().nodeTypes[name],

  getEdgeType: (name: string) => get().edgeTypes[name],

  getEdgesForNodeType: (nodeType: string) => {
    return Object.values(get().edgeTypes).filter(
      (et) =>
        et.source.node_types.includes(nodeType) ||
        et.target.node_types.includes(nodeType),
    );
  },

  getListColumns: (nodeType: string) => {
    const nt = get().nodeTypes[nodeType];
    if (!nt) return [];

    return Object.entries(nt.attributes)
      .filter(([, attr]) => attr.ui.list_column)
      .sort(
        (a, b) =>
          (a[1].ui.list_column_order ?? 999) -
          (b[1].ui.list_column_order ?? 999),
      )
      .map(([name, attr]) => ({ name, attr }));
  },
}));
