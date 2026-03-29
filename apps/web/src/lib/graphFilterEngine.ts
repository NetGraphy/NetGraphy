/**
 * Graph Filter Engine — pure functions for evaluating filter rules
 * against graph data.
 *
 * The engine is intentionally free of side-effects so it can be used
 * in workers, tests, and server-side rendering without modification.
 */

import type { GraphNode, GraphEdge } from "@/types/schema";
import type {
  FilterOperator,
  FilterRule,
  FilterGroup,
  GraphFilterState,
  AttributeFilterRule,
  RelationshipFilterRule,
} from "@/types/graphFilter";

// ---------------------------------------------------------------------------
// Operator applicability per attribute type
// ---------------------------------------------------------------------------

export const OPERATORS_FOR_TYPE: Record<string, FilterOperator[]> = {
  string: [
    "eq",
    "neq",
    "contains",
    "starts_with",
    "ends_with",
    "in",
    "not_in",
    "is_set",
    "is_not_set",
  ],
  text: [
    "eq",
    "neq",
    "contains",
    "starts_with",
    "ends_with",
    "is_set",
    "is_not_set",
  ],
  integer: [
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "is_set",
    "is_not_set",
  ],
  float: [
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_set",
    "is_not_set",
  ],
  boolean: ["eq", "neq", "is_set", "is_not_set"],
  enum: ["eq", "neq", "in", "not_in", "is_set", "is_not_set"],
  datetime: [
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_set",
    "is_not_set",
  ],
  date: [
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "is_set",
    "is_not_set",
  ],
  ip_address: [
    "eq",
    "neq",
    "contains",
    "starts_with",
    "is_set",
    "is_not_set",
  ],
  cidr: ["eq", "neq", "contains", "starts_with", "is_set", "is_not_set"],
  mac_address: ["eq", "neq", "contains", "is_set", "is_not_set"],
  url: [
    "eq",
    "neq",
    "contains",
    "starts_with",
    "ends_with",
    "is_set",
    "is_not_set",
  ],
  email: [
    "eq",
    "neq",
    "contains",
    "starts_with",
    "ends_with",
    "is_set",
    "is_not_set",
  ],
  json: ["is_set", "is_not_set"],
  reference: ["eq", "neq", "in", "not_in", "is_set", "is_not_set"],
  "list[string]": ["contains", "is_set", "is_not_set"],
  "list[integer]": ["contains", "is_set", "is_not_set"],
};

// ---------------------------------------------------------------------------
// Adjacency index
// ---------------------------------------------------------------------------

export interface NodeAdjacency {
  outgoing: Map<string, Set<string>>; // edgeType -> Set<neighborId>
  incoming: Map<string, Set<string>>; // edgeType -> Set<neighborId>
}

/**
 * Build a per-node adjacency index from an edge list.
 * Key = node id, value = outgoing/incoming edge-type sets.
 */
export function buildAdjacencyIndex(
  edges: GraphEdge[],
): Map<string, NodeAdjacency> {
  const index = new Map<string, NodeAdjacency>();

  const ensure = (id: string): NodeAdjacency => {
    let entry = index.get(id);
    if (!entry) {
      entry = {
        outgoing: new Map(),
        incoming: new Map(),
      };
      index.set(id, entry);
    }
    return entry;
  };

  for (const edge of edges) {
    // Source side — outgoing
    const src = ensure(edge.source_id);
    let srcSet = src.outgoing.get(edge.edge_type);
    if (!srcSet) {
      srcSet = new Set();
      src.outgoing.set(edge.edge_type, srcSet);
    }
    srcSet.add(edge.target_id);

    // Target side — incoming
    const tgt = ensure(edge.target_id);
    let tgtSet = tgt.incoming.get(edge.edge_type);
    if (!tgtSet) {
      tgtSet = new Set();
      tgt.incoming.set(edge.edge_type, tgtSet);
    }
    tgtSet.add(edge.source_id);
  }

  return index;
}

// ---------------------------------------------------------------------------
// Operator evaluation helpers
// ---------------------------------------------------------------------------

function isNullish(v: unknown): v is null | undefined {
  return v === null || v === undefined;
}

function toStr(v: unknown): string {
  return String(v).toLowerCase();
}

function toNum(v: unknown): number {
  return Number(v);
}

function evaluateOperator(
  fieldValue: unknown,
  operator: FilterOperator,
  ruleValue: unknown,
): boolean {
  switch (operator) {
    case "is_set":
      return !isNullish(fieldValue) && fieldValue !== "";
    case "is_not_set":
      return isNullish(fieldValue) || fieldValue === "";

    case "eq":
      return toStr(fieldValue) === toStr(ruleValue);
    case "neq":
      return toStr(fieldValue) !== toStr(ruleValue);

    case "gt":
      return toNum(fieldValue) > toNum(ruleValue);
    case "gte":
      return toNum(fieldValue) >= toNum(ruleValue);
    case "lt":
      return toNum(fieldValue) < toNum(ruleValue);
    case "lte":
      return toNum(fieldValue) <= toNum(ruleValue);

    case "contains":
      return toStr(fieldValue).includes(toStr(ruleValue));
    case "starts_with":
      return toStr(fieldValue).startsWith(toStr(ruleValue));
    case "ends_with":
      return toStr(fieldValue).endsWith(toStr(ruleValue));

    case "in": {
      const list = Array.isArray(ruleValue) ? ruleValue : [];
      const needle = toStr(fieldValue);
      return list.some((item) => toStr(item) === needle);
    }
    case "not_in": {
      const list = Array.isArray(ruleValue) ? ruleValue : [];
      const needle = toStr(fieldValue);
      return !list.some((item) => toStr(item) === needle);
    }

    default:
      return false;
  }
}

// ---------------------------------------------------------------------------
// Rule evaluation
// ---------------------------------------------------------------------------

function evaluateAttributeRule(
  node: GraphNode,
  rule: AttributeFilterRule,
): boolean {
  // Type guard: skip nodes that don't match the target type
  if (rule.node_type !== "*" && node.node_type !== rule.node_type) {
    // When the rule targets a specific type and the node is a different type,
    // the rule is considered non-applicable — treat as passing (true) so
    // AND-groups don't discard unrelated node types.
    return true;
  }

  const fieldValue = node.properties[rule.field];
  return evaluateOperator(fieldValue, rule.operator, rule.value);
}

function evaluateRelationshipRule(
  node: GraphNode,
  rule: RelationshipFilterRule,
  adjacency: Map<string, NodeAdjacency>,
): boolean {
  // Type guard
  if (rule.node_type !== "*" && node.node_type !== rule.node_type) {
    return true;
  }

  const adj = adjacency.get(node.id);
  if (!adj) {
    return rule.presence === "has_not";
  }

  let hasEdge = false;

  if (rule.direction === "outgoing" || rule.direction === "any") {
    const outSet = adj.outgoing.get(rule.edge_type);
    if (outSet && outSet.size > 0) {
      hasEdge = true;
    }
  }

  if (!hasEdge && (rule.direction === "incoming" || rule.direction === "any")) {
    const inSet = adj.incoming.get(rule.edge_type);
    if (inSet && inSet.size > 0) {
      hasEdge = true;
    }
  }

  return rule.presence === "has" ? hasEdge : !hasEdge;
}

/**
 * Evaluate a single filter rule against a node.
 */
export function evaluateRule(
  node: GraphNode,
  rule: FilterRule,
  adjacency: Map<string, NodeAdjacency>,
): boolean {
  switch (rule.kind) {
    case "attribute":
      return evaluateAttributeRule(node, rule);
    case "relationship":
      return evaluateRelationshipRule(node, rule, adjacency);
    default:
      return true;
  }
}

// ---------------------------------------------------------------------------
// Group evaluation
// ---------------------------------------------------------------------------

function evaluateGroup(
  node: GraphNode,
  group: FilterGroup,
  adjacency: Map<string, NodeAdjacency>,
): boolean {
  if (group.rules.length === 0) {
    return true;
  }

  if (group.logic === "and") {
    return group.rules.every((rule) => evaluateRule(node, rule, adjacency));
  }

  // "or"
  return group.rules.some((rule) => evaluateRule(node, rule, adjacency));
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Apply a filter state to a set of graph nodes and edges.
 *
 * Returns only the nodes that pass the filter and edges whose
 * source and target both survive.
 */
export function applyGraphFilter(
  nodes: GraphNode[],
  edges: GraphEdge[],
  filter: GraphFilterState,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (!filter.enabled) {
    return { nodes, edges };
  }

  // 1. Build adjacency index from all edges (before filtering)
  const adjacency = buildAdjacencyIndex(edges);

  // 2. Filter nodes
  const survivingNodes = nodes.filter((node) =>
    evaluateGroup(node, filter.rootGroup, adjacency),
  );

  // 3. Build surviving ID set for edge pruning
  const survivingIds = new Set(survivingNodes.map((n) => n.id));

  // 4. Keep only edges where both endpoints survived
  const survivingEdges = edges.filter(
    (edge) =>
      survivingIds.has(edge.source_id) && survivingIds.has(edge.target_id),
  );

  return { nodes: survivingNodes, edges: survivingEdges };
}
