/**
 * Schema Designer Store — canonical in-memory schema model.
 *
 * This Zustand store is the SINGLE source of truth. Both the ERD canvas
 * and the YAML editor are projections of this model. All mutations go
 * through this store, and both views react to changes.
 *
 * Every entity has a stable UUID that never changes. Names are editable
 * but IDs are immutable references.
 */

import { create } from "zustand";
const uuid = () => crypto.randomUUID();

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

export interface SchemaAttribute {
  id: string;
  name: string;
  type: string; // string, integer, float, boolean, datetime, date, enum, json, ip_address, cidr, mac_address, url, email
  required: boolean;
  unique: boolean;
  indexed: boolean;
  default_value: string | null;
  enum_values: string[] | null;
  description: string;
}

export interface SchemaNode {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  icon: string;
  color: string;
  tags: string[];
  attributes: SchemaAttribute[];
  mixins: string[];
  // Canvas position
  position: { x: number; y: number };
}

export interface SchemaEdge {
  id: string;
  name: string;
  display_name: string;
  description: string;
  from_node_id: string; // UUID reference
  to_node_id: string; // UUID reference
  cardinality: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";
  inverse_name: string;
  attributes: SchemaAttribute[];
  constraints: {
    unique_source: boolean;
    unique_target: boolean;
  };
}

export interface CanonicalSchema {
  nodes: SchemaNode[];
  edges: SchemaEdge[];
}

interface ValidationError {
  type: "error" | "warning";
  path: string;
  message: string;
}

// --------------------------------------------------------------------------
// Undo/Redo history
// --------------------------------------------------------------------------

interface HistoryEntry {
  schema: CanonicalSchema;
  label: string;
}

// --------------------------------------------------------------------------
// Store
// --------------------------------------------------------------------------

interface SchemaDesignerState {
  // Canonical model
  schema: CanonicalSchema;

  // Selection
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  selectedAttributeId: string | null;

  // Validation
  errors: ValidationError[];

  // Undo/redo
  history: HistoryEntry[];
  historyIndex: number;

  // YAML sync flag
  yamlDirty: boolean;

  // --- Node operations ---
  addNode: (name: string, position?: { x: number; y: number }) => string;
  updateNode: (id: string, updates: Partial<Omit<SchemaNode, "id" | "attributes">>) => void;
  removeNode: (id: string) => void;

  // --- Attribute operations ---
  addAttribute: (nodeId: string, attr?: Partial<SchemaAttribute>) => string;
  updateAttribute: (nodeId: string, attrId: string, updates: Partial<SchemaAttribute>) => void;
  removeAttribute: (nodeId: string, attrId: string) => void;

  // --- Edge operations ---
  addEdge: (name: string, fromNodeId: string, toNodeId: string, cardinality?: string) => string;
  updateEdge: (id: string, updates: Partial<Omit<SchemaEdge, "id">>) => void;
  removeEdge: (id: string) => void;
  addEdgeAttribute: (edgeId: string, attr?: Partial<SchemaAttribute>) => string;
  updateEdgeAttribute: (edgeId: string, attrId: string, updates: Partial<SchemaAttribute>) => void;
  removeEdgeAttribute: (edgeId: string, attrId: string) => void;

  // --- Selection ---
  selectNode: (id: string | null) => void;
  selectEdge: (id: string | null) => void;
  selectAttribute: (id: string | null) => void;
  clearSelection: () => void;

  // --- Schema operations ---
  loadSchema: (schema: CanonicalSchema) => void;
  resetSchema: () => void;
  validate: () => ValidationError[];

  // --- Undo/Redo ---
  undo: () => void;
  redo: () => void;
  pushHistory: (label: string) => void;

  // --- Helpers ---
  getNodeById: (id: string) => SchemaNode | undefined;
  getNodeByName: (name: string) => SchemaNode | undefined;
  getEdgeById: (id: string) => SchemaEdge | undefined;
}

function createDefaultAttribute(overrides?: Partial<SchemaAttribute>): SchemaAttribute {
  return {
    id: uuid(),
    name: overrides?.name || "new_field",
    type: "string",
    required: false,
    unique: false,
    indexed: false,
    default_value: null,
    enum_values: null,
    description: "",
    ...overrides,
  };
}

const EMPTY_SCHEMA: CanonicalSchema = { nodes: [], edges: [] };

export const useSchemaDesignerStore = create<SchemaDesignerState>((set, get) => ({
  schema: { ...EMPTY_SCHEMA },
  selectedNodeId: null,
  selectedEdgeId: null,
  selectedAttributeId: null,
  errors: [],
  history: [],
  historyIndex: -1,
  yamlDirty: false,

  // --- Node operations ---

  addNode: (name, position) => {
    const id = uuid();
    const node: SchemaNode = {
      id,
      name,
      display_name: name,
      description: "",
      category: "Custom",
      icon: "box",
      color: "#6366F1",
      tags: [],
      attributes: [],
      mixins: ["lifecycle_mixin"],
      position: position || { x: 100 + Math.random() * 400, y: 100 + Math.random() * 300 },
    };
    set((s) => ({
      schema: { ...s.schema, nodes: [...s.schema.nodes, node] },
      selectedNodeId: id,
      selectedEdgeId: null,
    }));
    get().pushHistory(`Add node ${name}`);
    return id;
  },

  updateNode: (id, updates) => {
    set((s) => ({
      schema: {
        ...s.schema,
        nodes: s.schema.nodes.map((n) => (n.id === id ? { ...n, ...updates } : n)),
      },
    }));
    get().pushHistory("Update node");
  },

  removeNode: (id) => {
    set((s) => ({
      schema: {
        nodes: s.schema.nodes.filter((n) => n.id !== id),
        edges: s.schema.edges.filter((e) => e.from_node_id !== id && e.to_node_id !== id),
      },
      selectedNodeId: s.selectedNodeId === id ? null : s.selectedNodeId,
    }));
    get().pushHistory("Remove node");
  },

  // --- Attribute operations ---

  addAttribute: (nodeId, attr) => {
    const newAttr = createDefaultAttribute(attr);
    set((s) => ({
      schema: {
        ...s.schema,
        nodes: s.schema.nodes.map((n) =>
          n.id === nodeId ? { ...n, attributes: [...n.attributes, newAttr] } : n
        ),
      },
      selectedAttributeId: newAttr.id,
    }));
    get().pushHistory("Add attribute");
    return newAttr.id;
  },

  updateAttribute: (nodeId, attrId, updates) => {
    set((s) => ({
      schema: {
        ...s.schema,
        nodes: s.schema.nodes.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                attributes: n.attributes.map((a) => (a.id === attrId ? { ...a, ...updates } : a)),
              }
            : n
        ),
      },
    }));
  },

  removeAttribute: (nodeId, attrId) => {
    set((s) => ({
      schema: {
        ...s.schema,
        nodes: s.schema.nodes.map((n) =>
          n.id === nodeId ? { ...n, attributes: n.attributes.filter((a) => a.id !== attrId) } : n
        ),
      },
      selectedAttributeId: s.selectedAttributeId === attrId ? null : s.selectedAttributeId,
    }));
    get().pushHistory("Remove attribute");
  },

  // --- Edge operations ---

  addEdge: (name, fromNodeId, toNodeId, cardinality = "many_to_many") => {
    const id = uuid();
    const edge: SchemaEdge = {
      id,
      name: name.toUpperCase().replace(/\s+/g, "_"),
      display_name: name,
      description: "",
      from_node_id: fromNodeId,
      to_node_id: toNodeId,
      cardinality: cardinality as SchemaEdge["cardinality"],
      inverse_name: "",
      attributes: [],
      constraints: { unique_source: false, unique_target: false },
    };
    set((s) => ({
      schema: { ...s.schema, edges: [...s.schema.edges, edge] },
      selectedEdgeId: id,
      selectedNodeId: null,
    }));
    get().pushHistory(`Add edge ${name}`);
    return id;
  },

  updateEdge: (id, updates) => {
    set((s) => ({
      schema: {
        ...s.schema,
        edges: s.schema.edges.map((e) => (e.id === id ? { ...e, ...updates } : e)),
      },
    }));
    get().pushHistory("Update edge");
  },

  removeEdge: (id) => {
    set((s) => ({
      schema: {
        ...s.schema,
        edges: s.schema.edges.filter((e) => e.id !== id),
      },
      selectedEdgeId: s.selectedEdgeId === id ? null : s.selectedEdgeId,
    }));
    get().pushHistory("Remove edge");
  },

  addEdgeAttribute: (edgeId, attr) => {
    const newAttr = createDefaultAttribute(attr);
    set((s) => ({
      schema: {
        ...s.schema,
        edges: s.schema.edges.map((e) =>
          e.id === edgeId ? { ...e, attributes: [...e.attributes, newAttr] } : e
        ),
      },
    }));
    get().pushHistory("Add edge attribute");
    return newAttr.id;
  },

  updateEdgeAttribute: (edgeId, attrId, updates) => {
    set((s) => ({
      schema: {
        ...s.schema,
        edges: s.schema.edges.map((e) =>
          e.id === edgeId
            ? { ...e, attributes: e.attributes.map((a) => (a.id === attrId ? { ...a, ...updates } : a)) }
            : e
        ),
      },
    }));
  },

  removeEdgeAttribute: (edgeId, attrId) => {
    set((s) => ({
      schema: {
        ...s.schema,
        edges: s.schema.edges.map((e) =>
          e.id === edgeId ? { ...e, attributes: e.attributes.filter((a) => a.id !== attrId) } : e
        ),
      },
    }));
    get().pushHistory("Remove edge attribute");
  },

  // --- Selection ---

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null, selectedAttributeId: null }),
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null, selectedAttributeId: null }),
  selectAttribute: (id) => set({ selectedAttributeId: id }),
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null, selectedAttributeId: null }),

  // --- Schema operations ---

  loadSchema: (schema) => {
    set({ schema, history: [], historyIndex: -1, selectedNodeId: null, selectedEdgeId: null });
    get().pushHistory("Load schema");
  },

  resetSchema: () => {
    set({ schema: { nodes: [], edges: [] }, history: [], historyIndex: -1, selectedNodeId: null, selectedEdgeId: null });
  },

  validate: () => {
    const { schema } = get();
    const errs: ValidationError[] = [];

    // Duplicate node names
    const nodeNames = new Set<string>();
    for (const n of schema.nodes) {
      if (nodeNames.has(n.name)) {
        errs.push({ type: "error", path: `node:${n.name}`, message: `Duplicate node name: ${n.name}` });
      }
      nodeNames.add(n.name);

      // Duplicate attribute names within node
      const attrNames = new Set<string>();
      for (const a of n.attributes) {
        if (attrNames.has(a.name)) {
          errs.push({ type: "error", path: `node:${n.name}.${a.name}`, message: `Duplicate attribute: ${a.name}` });
        }
        attrNames.add(a.name);

        // Enum without values
        if (a.type === "enum" && (!a.enum_values || a.enum_values.length === 0)) {
          errs.push({ type: "error", path: `node:${n.name}.${a.name}`, message: "Enum type requires values" });
        }
      }
    }

    // Edge validation
    const edgeNames = new Set<string>();
    for (const e of schema.edges) {
      if (edgeNames.has(e.name)) {
        errs.push({ type: "error", path: `edge:${e.name}`, message: `Duplicate edge name: ${e.name}` });
      }
      edgeNames.add(e.name);

      // Invalid references
      if (!schema.nodes.find((n) => n.id === e.from_node_id)) {
        errs.push({ type: "error", path: `edge:${e.name}`, message: "Source node not found" });
      }
      if (!schema.nodes.find((n) => n.id === e.to_node_id)) {
        errs.push({ type: "error", path: `edge:${e.name}`, message: "Target node not found" });
      }
    }

    set({ errors: errs });
    return errs;
  },

  // --- Undo/Redo ---

  pushHistory: (label) => {
    const { schema, history, historyIndex } = get();
    const entry: HistoryEntry = { schema: JSON.parse(JSON.stringify(schema)), label };
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push(entry);
    // Keep max 50 entries
    if (newHistory.length > 50) newHistory.shift();
    set({ history: newHistory, historyIndex: newHistory.length - 1 });
  },

  undo: () => {
    const { history, historyIndex } = get();
    if (historyIndex > 0) {
      const prev = history[historyIndex - 1];
      set({ schema: JSON.parse(JSON.stringify(prev.schema)), historyIndex: historyIndex - 1 });
    }
  },

  redo: () => {
    const { history, historyIndex } = get();
    if (historyIndex < history.length - 1) {
      const next = history[historyIndex + 1];
      set({ schema: JSON.parse(JSON.stringify(next.schema)), historyIndex: historyIndex + 1 });
    }
  },

  // --- Helpers ---

  getNodeById: (id) => get().schema.nodes.find((n) => n.id === id),
  getNodeByName: (name) => get().schema.nodes.find((n) => n.name === name),
  getEdgeById: (id) => get().schema.edges.find((e) => e.id === id),
}));
