/**
 * Query Builder Store — canonical visual query model.
 *
 * The visual query builder, generated Cypher, and results are all
 * projections of this single model. Supports node patterns, relationship
 * patterns, filters, projections, aggregation, sorting, pagination,
 * parameters, and saved queries.
 */

import { create } from "zustand";

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

export type Direction = "outgoing" | "incoming" | "undirected";
export type MatchType = "match" | "optional_match";

export interface QueryNodePattern {
  id: string;
  alias: string;
  labels: string[]; // Node type labels (e.g., ["Device"])
  matchType: MatchType;
}

export interface QueryRelPattern {
  id: string;
  alias: string;
  types: string[]; // Edge types (e.g., ["LOCATED_IN"])
  direction: Direction;
  fromNodeId: string; // QueryNodePattern ID
  toNodeId: string; // QueryNodePattern ID
  minHops: number | null; // null = exact (1)
  maxHops: number | null;
  matchType: MatchType;
}

export interface QueryFilter {
  id: string;
  targetAlias: string; // Which node/rel alias this filter applies to
  field: string;
  operator: string;
  value: string;
  isParameter: boolean; // If true, value is a parameter name
  logicalGroup: string; // "and" or "or"
}

export interface QueryReturnField {
  id: string;
  expression: string; // e.g., "d.hostname", "count(d)", "d"
  alias: string; // e.g., "hostname", "device_count"
  isAggregate: boolean;
}

export interface QuerySortField {
  field: string; // Alias or expression
  direction: "ASC" | "DESC";
}

export interface QueryParameter {
  name: string;
  label: string;
  type: string; // string, integer, boolean, enum
  required: boolean;
  defaultValue: string;
  enumValues: string[];
  description: string;
}

export interface VisualQueryModel {
  nodes: QueryNodePattern[];
  relationships: QueryRelPattern[];
  filters: QueryFilter[];
  returnFields: QueryReturnField[];
  sortFields: QuerySortField[];
  distinct: boolean;
  limit: number;
  skip: number;
  parameters: QueryParameter[];
}

export interface SavedQueryMeta {
  id?: string;
  name: string;
  description: string;
  tags: string[];
  folder: string;
  visibility: string; // personal, shared
}

// --------------------------------------------------------------------------
// Cypher Generation
// --------------------------------------------------------------------------

export function generateCypher(model: VisualQueryModel, paramValues?: Record<string, string>): string {
  const lines: string[] = [];
  const usedAliases = new Set<string>();

  // Group by match type
  const matchNodes = model.nodes.filter((n) => n.matchType === "match");
  const optionalNodes = model.nodes.filter((n) => n.matchType === "optional_match");

  // Build MATCH clauses
  const buildPatterns = (nodes: QueryNodePattern[], matchKeyword: string) => {
    // Find relationships involving these nodes
    const nodeIds = new Set(nodes.map((n) => n.id));
    const rels = model.relationships.filter(
      (r) => r.matchType === (matchKeyword === "MATCH" ? "match" : "optional_match")
    );

    // Track which nodes have been included in a relationship pattern
    const coveredNodes = new Set<string>();

    for (const rel of rels) {
      const fromNode = model.nodes.find((n) => n.id === rel.fromNodeId);
      const toNode = model.nodes.find((n) => n.id === rel.toNodeId);
      if (!fromNode || !toNode) continue;

      const fromLabel = fromNode.labels.length ? `:${fromNode.labels.join(":")}` : "";
      const toLabel = toNode.labels.length ? `:${toNode.labels.join(":")}` : "";
      const relType = rel.types.length ? `:${rel.types.join("|")}` : "";

      const relAlias = rel.alias ? rel.alias : "";
      let hops = "";
      if (rel.minHops !== null || rel.maxHops !== null) {
        const min = rel.minHops ?? "";
        const max = rel.maxHops ?? "";
        hops = `*${min}..${max}`;
      }

      const relInner = `[${relAlias}${relType}${hops}]`;

      let arrow: string;
      if (rel.direction === "outgoing") {
        arrow = `-${relInner}->`;
      } else if (rel.direction === "incoming") {
        arrow = `<-${relInner}-`;
      } else {
        arrow = `-${relInner}-`;
      }

      lines.push(`${matchKeyword} (${fromNode.alias}${fromLabel})${arrow}(${toNode.alias}${toLabel})`);
      coveredNodes.add(rel.fromNodeId);
      coveredNodes.add(rel.toNodeId);
      usedAliases.add(fromNode.alias);
      usedAliases.add(toNode.alias);
    }

    // Standalone nodes not in any relationship
    for (const node of nodes) {
      if (!coveredNodes.has(node.id)) {
        const label = node.labels.length ? `:${node.labels.join(":")}` : "";
        lines.push(`${matchKeyword} (${node.alias}${label})`);
        usedAliases.add(node.alias);
      }
    }
  };

  buildPatterns(matchNodes, "MATCH");
  buildPatterns(optionalNodes, "OPTIONAL MATCH");

  // WHERE clause
  const activeFilters = model.filters.filter((f) => f.field && f.operator);
  if (activeFilters.length > 0) {
    const conditions: string[] = [];
    for (const f of activeFilters) {
      const fieldExpr = `${f.targetAlias}.${f.field}`;
      let valueExpr: string;

      if (f.isParameter) {
        valueExpr = `$${f.value}`;
      } else if (f.operator === "is_null" || f.operator === "is_not_null") {
        valueExpr = "";
      } else if (f.operator === "in") {
        valueExpr = paramValues?.[f.value] || f.value;
      } else {
        // Quote string values
        const raw = paramValues?.[f.value] || f.value;
        valueExpr = /^\d+(\.\d+)?$/.test(raw) || raw === "true" || raw === "false"
          ? raw
          : `"${raw}"`;
      }

      let condition: string;
      switch (f.operator) {
        case "eq": condition = `${fieldExpr} = ${valueExpr}`; break;
        case "neq": condition = `${fieldExpr} <> ${valueExpr}`; break;
        case "contains": condition = `${fieldExpr} CONTAINS ${valueExpr}`; break;
        case "starts_with": condition = `${fieldExpr} STARTS WITH ${valueExpr}`; break;
        case "ends_with": condition = `${fieldExpr} ENDS WITH ${valueExpr}`; break;
        case "gt": condition = `${fieldExpr} > ${valueExpr}`; break;
        case "gte": condition = `${fieldExpr} >= ${valueExpr}`; break;
        case "lt": condition = `${fieldExpr} < ${valueExpr}`; break;
        case "lte": condition = `${fieldExpr} <= ${valueExpr}`; break;
        case "in": condition = `${fieldExpr} IN ${valueExpr}`; break;
        case "is_null": condition = `${fieldExpr} IS NULL`; break;
        case "is_not_null": condition = `${fieldExpr} IS NOT NULL`; break;
        case "regex": condition = `${fieldExpr} =~ ${valueExpr}`; break;
        default: condition = `${fieldExpr} = ${valueExpr}`;
      }
      conditions.push(condition);
    }

    // Group by logical group
    const andConditions = conditions; // Simplified: all AND for now
    if (andConditions.length > 0) {
      lines.push(`WHERE ${andConditions.join("\n  AND ")}`);
    }
  }

  // RETURN clause
  if (model.returnFields.length > 0) {
    const distinct = model.distinct ? "DISTINCT " : "";
    const fields = model.returnFields.map((f) => {
      if (f.alias && f.alias !== f.expression) {
        return `${f.expression} AS ${f.alias}`;
      }
      return f.expression;
    });
    lines.push(`RETURN ${distinct}${fields.join(", ")}`);
  } else {
    // Default: return all used aliases
    const aliases = [...usedAliases];
    if (aliases.length > 0) {
      lines.push(`RETURN ${aliases.join(", ")}`);
    }
  }

  // ORDER BY
  if (model.sortFields.length > 0) {
    const sorts = model.sortFields.map((s) => `${s.field} ${s.direction}`);
    lines.push(`ORDER BY ${sorts.join(", ")}`);
  }

  // SKIP / LIMIT
  if (model.skip > 0) {
    lines.push(`SKIP ${model.skip}`);
  }
  if (model.limit > 0) {
    lines.push(`LIMIT ${model.limit}`);
  }

  return lines.join("\n");
}

// --------------------------------------------------------------------------
// Store
// --------------------------------------------------------------------------

const uuid = () => crypto.randomUUID();

function emptyModel(): VisualQueryModel {
  return {
    nodes: [],
    relationships: [],
    filters: [],
    returnFields: [],
    sortFields: [],
    distinct: false,
    limit: 25,
    skip: 0,
    parameters: [],
  };
}

interface QueryBuilderState {
  model: VisualQueryModel;
  cypher: string;
  savedMeta: SavedQueryMeta;

  // Selection
  selectedPatternId: string | null;

  // Node patterns
  addNode: (labels?: string[], alias?: string) => string;
  updateNode: (id: string, updates: Partial<QueryNodePattern>) => void;
  removeNode: (id: string) => void;

  // Relationship patterns
  addRelationship: (fromId: string, toId: string, types?: string[], direction?: Direction) => string;
  updateRelationship: (id: string, updates: Partial<QueryRelPattern>) => void;
  removeRelationship: (id: string) => void;

  // Filters
  addFilter: (targetAlias: string) => string;
  updateFilter: (id: string, updates: Partial<QueryFilter>) => void;
  removeFilter: (id: string) => void;

  // Return fields
  addReturnField: (expression: string, alias?: string, isAggregate?: boolean) => void;
  removeReturnField: (id: string) => void;
  updateReturnField: (id: string, updates: Partial<QueryReturnField>) => void;
  clearReturnFields: () => void;

  // Sort
  setSortFields: (fields: QuerySortField[]) => void;

  // Model-level
  setDistinct: (v: boolean) => void;
  setLimit: (v: number) => void;
  setSkip: (v: number) => void;
  setModel: (model: VisualQueryModel) => void;
  resetModel: () => void;
  setSavedMeta: (meta: Partial<SavedQueryMeta>) => void;
  selectPattern: (id: string | null) => void;

  // Templates
  loadTemplate: (name: string) => void;
}

function regen(model: VisualQueryModel): string {
  return generateCypher(model);
}

export const useQueryBuilderStore = create<QueryBuilderState>((set, get) => ({
  model: emptyModel(),
  cypher: "",
  savedMeta: { name: "", description: "", tags: [], folder: "", visibility: "personal" },
  selectedPatternId: null,

  addNode: (labels = [], alias) => {
    const id = uuid();
    const existingAliases = get().model.nodes.map((n) => n.alias);
    const defaultAlias = alias || `n${existingAliases.length}`;
    const node: QueryNodePattern = { id, alias: defaultAlias, labels, matchType: "match" };
    set((s) => {
      const model = { ...s.model, nodes: [...s.model.nodes, node] };
      return { model, cypher: regen(model), selectedPatternId: id };
    });
    return id;
  },

  updateNode: (id, updates) => set((s) => {
    const model = { ...s.model, nodes: s.model.nodes.map((n) => n.id === id ? { ...n, ...updates } : n) };
    return { model, cypher: regen(model) };
  }),

  removeNode: (id) => set((s) => {
    const model = {
      ...s.model,
      nodes: s.model.nodes.filter((n) => n.id !== id),
      relationships: s.model.relationships.filter((r) => r.fromNodeId !== id && r.toNodeId !== id),
    };
    return { model, cypher: regen(model), selectedPatternId: null };
  }),

  addRelationship: (fromId, toId, types = [], direction = "outgoing") => {
    const id = uuid();
    const existingAliases = get().model.relationships.map((r) => r.alias);
    const rel: QueryRelPattern = {
      id, alias: `r${existingAliases.length}`, types, direction,
      fromNodeId: fromId, toNodeId: toId,
      minHops: null, maxHops: null, matchType: "match",
    };
    set((s) => {
      const model = { ...s.model, relationships: [...s.model.relationships, rel] };
      return { model, cypher: regen(model), selectedPatternId: id };
    });
    return id;
  },

  updateRelationship: (id, updates) => set((s) => {
    const model = { ...s.model, relationships: s.model.relationships.map((r) => r.id === id ? { ...r, ...updates } : r) };
    return { model, cypher: regen(model) };
  }),

  removeRelationship: (id) => set((s) => {
    const model = { ...s.model, relationships: s.model.relationships.filter((r) => r.id !== id) };
    return { model, cypher: regen(model) };
  }),

  addFilter: (targetAlias) => {
    const id = uuid();
    const filter: QueryFilter = { id, targetAlias, field: "", operator: "eq", value: "", isParameter: false, logicalGroup: "and" };
    set((s) => {
      const model = { ...s.model, filters: [...s.model.filters, filter] };
      return { model, cypher: regen(model) };
    });
    return id;
  },

  updateFilter: (id, updates) => set((s) => {
    const model = { ...s.model, filters: s.model.filters.map((f) => f.id === id ? { ...f, ...updates } : f) };
    return { model, cypher: regen(model) };
  }),

  removeFilter: (id) => set((s) => {
    const model = { ...s.model, filters: s.model.filters.filter((f) => f.id !== id) };
    return { model, cypher: regen(model) };
  }),

  addReturnField: (expression, alias, isAggregate = false) => {
    const id = uuid();
    const field: QueryReturnField = { id, expression, alias: alias || expression, isAggregate };
    set((s) => {
      const model = { ...s.model, returnFields: [...s.model.returnFields, field] };
      return { model, cypher: regen(model) };
    });
  },

  removeReturnField: (id) => set((s) => {
    const model = { ...s.model, returnFields: s.model.returnFields.filter((f) => f.id !== id) };
    return { model, cypher: regen(model) };
  }),

  updateReturnField: (id, updates) => set((s) => {
    const model = { ...s.model, returnFields: s.model.returnFields.map((f) => f.id === id ? { ...f, ...updates } : f) };
    return { model, cypher: regen(model) };
  }),

  clearReturnFields: () => set((s) => {
    const model = { ...s.model, returnFields: [] };
    return { model, cypher: regen(model) };
  }),

  setSortFields: (fields) => set((s) => {
    const model = { ...s.model, sortFields: fields };
    return { model, cypher: regen(model) };
  }),

  setDistinct: (v) => set((s) => {
    const model = { ...s.model, distinct: v };
    return { model, cypher: regen(model) };
  }),

  setLimit: (v) => set((s) => {
    const model = { ...s.model, limit: v };
    return { model, cypher: regen(model) };
  }),

  setSkip: (v) => set((s) => {
    const model = { ...s.model, skip: v };
    return { model, cypher: regen(model) };
  }),

  setModel: (model) => set({ model, cypher: regen(model) }),
  resetModel: () => set({ model: emptyModel(), cypher: "", selectedPatternId: null, savedMeta: { name: "", description: "", tags: [], folder: "", visibility: "personal" } }),
  setSavedMeta: (meta) => set((s) => ({ savedMeta: { ...s.savedMeta, ...meta } })),
  selectPattern: (id) => set({ selectedPatternId: id }),

  loadTemplate: (name) => {
    const templates: Record<string, () => VisualQueryModel> = {
      "devices-by-site": () => {
        const dId = uuid(), sId = uuid(), rId = uuid();
        return {
          ...emptyModel(),
          nodes: [
            { id: dId, alias: "d", labels: ["Device"], matchType: "match" as const },
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const },
          ],
          relationships: [
            { id: rId, alias: "", types: ["LOCATED_IN"], direction: "outgoing" as const, fromNodeId: dId, toNodeId: sId, minHops: null, maxHops: null, matchType: "match" as const },
          ],
          returnFields: [
            { id: uuid(), expression: "d.hostname", alias: "hostname", isAggregate: false },
            { id: uuid(), expression: "d.status", alias: "status", isAggregate: false },
            { id: uuid(), expression: "d.role", alias: "role", isAggregate: false },
            { id: uuid(), expression: "s.name", alias: "site_name", isAggregate: false },
            { id: uuid(), expression: "s.city", alias: "city", isAggregate: false },
          ],
          limit: 50,
        };
      },
      "sites-no-devices": () => {
        const sId = uuid(), dId = uuid(), rId = uuid();
        return {
          ...emptyModel(),
          nodes: [
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const },
            { id: dId, alias: "d", labels: ["Device"], matchType: "optional_match" as const },
          ],
          relationships: [
            { id: rId, alias: "", types: ["LOCATED_IN"], direction: "incoming" as const, fromNodeId: sId, toNodeId: dId, minHops: null, maxHops: null, matchType: "optional_match" as const },
          ],
          filters: [
            { id: uuid(), targetAlias: "d", field: "id", operator: "is_null", value: "", isParameter: false, logicalGroup: "and" },
          ],
          returnFields: [
            { id: uuid(), expression: "s.name", alias: "site_name", isAggregate: false },
            { id: uuid(), expression: "s.city", alias: "city", isAggregate: false },
          ],
          limit: 50,
        };
      },
      "count-devices-by-city": () => {
        const dId = uuid(), sId = uuid(), rId = uuid();
        return {
          ...emptyModel(),
          nodes: [
            { id: dId, alias: "d", labels: ["Device"], matchType: "match" as const },
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const },
          ],
          relationships: [
            { id: rId, alias: "", types: ["LOCATED_IN"], direction: "outgoing" as const, fromNodeId: dId, toNodeId: sId, minHops: null, maxHops: null, matchType: "match" as const },
          ],
          returnFields: [
            { id: uuid(), expression: "s.city", alias: "city", isAggregate: false },
            { id: uuid(), expression: "count(d)", alias: "device_count", isAggregate: true },
          ],
          sortFields: [{ field: "device_count", direction: "DESC" }],
          limit: 50,
        };
      },
      "circuits-by-provider": () => {
        const cId = uuid(), pId = uuid(), rId = uuid();
        return {
          ...emptyModel(),
          nodes: [
            { id: cId, alias: "c", labels: ["Circuit"], matchType: "match" as const },
            { id: pId, alias: "p", labels: ["Provider"], matchType: "match" as const },
          ],
          relationships: [
            { id: rId, alias: "", types: ["CIRCUIT_FROM_PROVIDER"], direction: "outgoing" as const, fromNodeId: cId, toNodeId: pId, minHops: null, maxHops: null, matchType: "match" as const },
          ],
          returnFields: [
            { id: uuid(), expression: "p.name", alias: "provider", isAggregate: false },
            { id: uuid(), expression: "count(c)", alias: "circuit_count", isAggregate: true },
          ],
          sortFields: [{ field: "circuit_count", direction: "DESC" }],
          limit: 25,
        };
      },
    };

    const builder = templates[name];
    if (builder) {
      const model = builder();
      set({ model, cypher: regen(model), selectedPatternId: null });
    }
  },
}));
