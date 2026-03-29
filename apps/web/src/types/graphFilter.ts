/**
 * Graph Explorer Power Filtering — type definitions.
 *
 * These types describe the filter DSL used by the graph explorer to
 * narrow down visible nodes and edges. Filters are composable via
 * AND/OR groups and support both attribute checks and relationship
 * presence checks.
 */

export type FilterOperator =
  | "eq"
  | "neq"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "contains"
  | "starts_with"
  | "ends_with"
  | "in"
  | "not_in"
  | "is_set"
  | "is_not_set";

export interface AttributeFilterRule {
  kind: "attribute";
  /** Node type to match, or "*" for all types. */
  node_type: string;
  field: string;
  operator: FilterOperator;
  value: unknown;
}

export interface RelationshipFilterRule {
  kind: "relationship";
  node_type: string;
  edge_type: string;
  direction: "any" | "outgoing" | "incoming";
  presence: "has" | "has_not";
}

export type FilterRule = AttributeFilterRule | RelationshipFilterRule;

export interface FilterGroup {
  logic: "and" | "or";
  rules: FilterRule[];
}

export interface GraphFilterState {
  enabled: boolean;
  rootGroup: FilterGroup;
}

export interface FilterPreset {
  id: string;
  name: string;
  description?: string;
  filter: GraphFilterState;
}
