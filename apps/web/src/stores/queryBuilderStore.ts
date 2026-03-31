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
export type QueryMode = "pattern" | "shortestPath" | "allPaths";

export interface MatchProperty {
  field: string;
  paramName: string; // Uses $paramName in Cypher
}

export interface QueryNodePattern {
  id: string;
  alias: string;
  labels: string[]; // Node type labels (e.g., ["Device"])
  matchType: MatchType;
  properties: MatchProperty[]; // MATCH-level constraints: {field: $param}
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
  queryMode: QueryMode; // pattern (normal), shortestPath, allPaths
  nodes: QueryNodePattern[];
  relationships: QueryRelPattern[];
  filters: QueryFilter[];
  returnFields: QueryReturnField[];
  sortFields: QuerySortField[];
  distinct: boolean;
  limit: number;
  skip: number;
  parameters: QueryParameter[];
  // Path mode settings
  pathStartNodeId: string | null; // Node pattern ID for path start
  pathEndNodeId: string | null; // Node pattern ID for path end
  pathDepthLimit: number; // Max hops for variable-length path
  pathRelTypes: string[]; // Allowed relationship types to traverse
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

// Helper: build node expression with label and MATCH-level properties
function nodeExpr(node: QueryNodePattern): string {
  const label = node.labels.length ? `:${node.labels.join(":")}` : "";
  const props = node.properties.length
    ? ` {${node.properties.map((p) => `${p.field}: $${p.paramName}`).join(", ")}}`
    : "";
  return `(${node.alias}${label}${props})`;
}

// Helper: build filter condition
function buildCondition(f: QueryFilter, paramValues?: Record<string, string>): string {
  const fieldExpr = `${f.targetAlias}.${f.field}`;
  let valueExpr: string;

  if (f.isParameter) {
    valueExpr = `$${f.value}`;
  } else if (f.operator === "is_null" || f.operator === "is_not_null") {
    valueExpr = "";
  } else {
    const raw = paramValues?.[f.value] || f.value;
    valueExpr = /^\d+(\.\d+)?$/.test(raw) || raw === "true" || raw === "false"
      ? raw
      : `"${raw}"`;
  }

  switch (f.operator) {
    case "eq": return `${fieldExpr} = ${valueExpr}`;
    case "neq": return `${fieldExpr} <> ${valueExpr}`;
    case "contains": return `${fieldExpr} CONTAINS ${valueExpr}`;
    case "starts_with": return `${fieldExpr} STARTS WITH ${valueExpr}`;
    case "ends_with": return `${fieldExpr} ENDS WITH ${valueExpr}`;
    case "gt": return `${fieldExpr} > ${valueExpr}`;
    case "gte": return `${fieldExpr} >= ${valueExpr}`;
    case "lt": return `${fieldExpr} < ${valueExpr}`;
    case "lte": return `${fieldExpr} <= ${valueExpr}`;
    case "in": return `${fieldExpr} IN ${valueExpr}`;
    case "is_null": return `${fieldExpr} IS NULL`;
    case "is_not_null": return `${fieldExpr} IS NOT NULL`;
    case "regex": return `${fieldExpr} =~ ${valueExpr}`;
    default: return `${fieldExpr} = ${valueExpr}`;
  }
}

export function generateCypher(model: VisualQueryModel, paramValues?: Record<string, string>): string {
  // ---------- PATH MODE (shortestPath / allPaths) ----------
  if (model.queryMode === "shortestPath" || model.queryMode === "allPaths") {
    return generatePathCypher(model, paramValues);
  }

  // ---------- PATTERN MODE (normal) ----------
  const lines: string[] = [];
  const usedAliases = new Set<string>();

  const matchNodes = model.nodes.filter((n) => n.matchType === "match");
  const optionalNodes = model.nodes.filter((n) => n.matchType === "optional_match");

  const buildPatterns = (nodes: QueryNodePattern[], matchKeyword: string) => {
    const rels = model.relationships.filter(
      (r) => r.matchType === (matchKeyword === "MATCH" ? "match" : "optional_match")
    );
    const coveredNodes = new Set<string>();

    for (const rel of rels) {
      const fromNode = model.nodes.find((n) => n.id === rel.fromNodeId);
      const toNode = model.nodes.find((n) => n.id === rel.toNodeId);
      if (!fromNode || !toNode) continue;

      const relType = rel.types.length ? `:${rel.types.join("|")}` : "";
      const relAlias = rel.alias || "";
      let hops = "";
      if (rel.minHops !== null || rel.maxHops !== null) {
        hops = `*${rel.minHops ?? ""}..${rel.maxHops ?? ""}`;
      }
      const relInner = `[${relAlias}${relType}${hops}]`;

      const arrow = rel.direction === "outgoing" ? `-${relInner}->`
        : rel.direction === "incoming" ? `<-${relInner}-`
        : `-${relInner}-`;

      lines.push(`${matchKeyword} ${nodeExpr(fromNode)}${arrow}${nodeExpr(toNode)}`);
      coveredNodes.add(rel.fromNodeId);
      coveredNodes.add(rel.toNodeId);
      usedAliases.add(fromNode.alias);
      usedAliases.add(toNode.alias);
    }

    for (const node of nodes) {
      if (!coveredNodes.has(node.id)) {
        lines.push(`${matchKeyword} ${nodeExpr(node)}`);
        usedAliases.add(node.alias);
      }
    }
  };

  buildPatterns(matchNodes, "MATCH");
  buildPatterns(optionalNodes, "OPTIONAL MATCH");

  // WHERE
  const activeFilters = model.filters.filter((f) => f.field && f.operator);
  if (activeFilters.length > 0) {
    const conditions = activeFilters.map((f) => buildCondition(f, paramValues));
    lines.push(`WHERE ${conditions.join("\n  AND ")}`);
  }

  // RETURN
  if (model.returnFields.length > 0) {
    const distinct = model.distinct ? "DISTINCT " : "";
    const fields = model.returnFields.map((f) =>
      f.alias && f.alias !== f.expression ? `${f.expression} AS ${f.alias}` : f.expression
    );
    lines.push(`RETURN ${distinct}${fields.join(", ")}`);
  } else {
    const aliases = [...usedAliases];
    if (aliases.length > 0) lines.push(`RETURN ${aliases.join(", ")}`);
  }

  if (model.sortFields.length > 0) {
    lines.push(`ORDER BY ${model.sortFields.map((s) => `${s.field} ${s.direction}`).join(", ")}`);
  }
  if (model.skip > 0) lines.push(`SKIP ${model.skip}`);
  if (model.limit > 0) lines.push(`LIMIT ${model.limit}`);

  return lines.join("\n");
}

function generatePathCypher(model: VisualQueryModel, paramValues?: Record<string, string>): string {
  const lines: string[] = [];

  const startNode = model.pathStartNodeId ? model.nodes.find((n) => n.id === model.pathStartNodeId) : model.nodes[0];
  const endNode = model.pathEndNodeId ? model.nodes.find((n) => n.id === model.pathEndNodeId) : model.nodes[1];

  if (!startNode || !endNode) {
    return "// Add at least two node patterns for path query";
  }

  // MATCH both endpoints
  lines.push(`MATCH ${nodeExpr(startNode)}, ${nodeExpr(endNode)}`);

  // Path function
  const pathFn = model.queryMode === "allPaths" ? "allShortestPaths" : "shortestPath";
  const depthLimit = model.pathDepthLimit || 15;

  // Relationship type filter in path
  let relFilter = "";
  if (model.pathRelTypes.length > 0) {
    relFilter = `:${model.pathRelTypes.join("|")}`;
  }

  lines.push(`MATCH path = ${pathFn}((${startNode.alias})-[${relFilter}*..${depthLimit}]-(${endNode.alias}))`);

  // WHERE — path relationship type filter (if types specified and not already in pattern)
  const whereConditions: string[] = [];

  // Add regular filters
  const activeFilters = model.filters.filter((f) => f.field && f.operator);
  for (const f of activeFilters) {
    whereConditions.push(buildCondition(f, paramValues));
  }

  if (whereConditions.length > 0) {
    lines.push(`WHERE ${whereConditions.join("\n  AND ")}`);
  }

  // RETURN
  if (model.returnFields.length > 0) {
    const fields = model.returnFields.map((f) =>
      f.alias && f.alias !== f.expression ? `${f.expression} AS ${f.alias}` : f.expression
    );
    lines.push(`RETURN ${fields.join(", ")}`);
  } else {
    // Default: return path for graph visualization
    lines.push("RETURN path");
  }

  if (model.limit > 0) lines.push(`LIMIT ${model.limit}`);

  return lines.join("\n");
}

// --------------------------------------------------------------------------
// Store
// --------------------------------------------------------------------------

const uuid = () => crypto.randomUUID();

function emptyModel(): VisualQueryModel {
  return {
    queryMode: "pattern",
    nodes: [],
    relationships: [],
    filters: [],
    returnFields: [],
    sortFields: [],
    distinct: false,
    limit: 25,
    skip: 0,
    parameters: [],
    pathStartNodeId: null,
    pathEndNodeId: null,
    pathDepthLimit: 15,
    pathRelTypes: [],
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
    const node: QueryNodePattern = { id, alias: defaultAlias, labels, matchType: "match", properties: [] };
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
            { id: dId, alias: "d", labels: ["Device"], matchType: "match" as const, properties: [] },
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const, properties: [] },
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
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const, properties: [] },
            { id: dId, alias: "d", labels: ["Device"], matchType: "optional_match" as const, properties: [] },
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
            { id: dId, alias: "d", labels: ["Device"], matchType: "match" as const, properties: [] },
            { id: sId, alias: "s", labels: ["Location"], matchType: "match" as const, properties: [] },
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
            { id: cId, alias: "c", labels: ["Circuit"], matchType: "match" as const, properties: [] },
            { id: pId, alias: "p", labels: ["Provider"], matchType: "match" as const, properties: [] },
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
      "mac-to-mac-path": () => {
        const srcId = uuid(), dstId = uuid();
        return {
          ...emptyModel(),
          queryMode: "shortestPath" as const,
          nodes: [
            { id: srcId, alias: "src", labels: ["MACAddress"], matchType: "match" as const, properties: [{ field: "address", paramName: "src_mac" }] },
            { id: dstId, alias: "dst", labels: ["MACAddress"], matchType: "match" as const, properties: [{ field: "address", paramName: "dst_mac" }] },
          ],
          pathStartNodeId: srcId,
          pathEndNodeId: dstId,
          pathDepthLimit: 30,
          pathRelTypes: ["MAC_ON_INTERFACE", "HAS_INTERFACE", "CONNECTED_TO", "CIRCUIT_HAS_TERMINATION", "TERMINATION_CONNECTED_TO"],
          parameters: [
            { name: "src_mac", label: "Source MAC", type: "string", required: true, defaultValue: "", enumValues: [], description: "Source MAC address" },
            { name: "dst_mac", label: "Destination MAC", type: "string", required: true, defaultValue: "", enumValues: [], description: "Destination MAC address" },
          ],
          limit: 5,
        };
      },
      "device-neighbors": () => {
        const dId = uuid(), nId = uuid();
        return {
          ...emptyModel(),
          queryMode: "shortestPath" as const,
          nodes: [
            { id: dId, alias: "d", labels: ["Device"], matchType: "match" as const, properties: [{ field: "hostname", paramName: "hostname" }] },
            { id: nId, alias: "neighbor", labels: ["Device"], matchType: "match" as const, properties: [] },
          ],
          pathStartNodeId: dId,
          pathEndNodeId: nId,
          pathDepthLimit: 4,
          pathRelTypes: ["HAS_INTERFACE", "CONNECTED_TO"],
          parameters: [
            { name: "hostname", label: "Device Hostname", type: "string", required: true, defaultValue: "", enumValues: [], description: "Starting device hostname" },
          ],
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
