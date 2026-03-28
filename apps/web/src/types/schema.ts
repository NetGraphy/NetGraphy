/**
 * TypeScript types matching the backend schema models.
 * These define the contract between the API and the dynamic UI system.
 */

export type AttributeType =
  | "string"
  | "text"
  | "integer"
  | "float"
  | "boolean"
  | "datetime"
  | "date"
  | "json"
  | "ip_address"
  | "cidr"
  | "mac_address"
  | "url"
  | "email"
  | "enum"
  | "reference"
  | "list[string]"
  | "list[integer]";

export type Cardinality =
  | "one_to_one"
  | "one_to_many"
  | "many_to_one"
  | "many_to_many";

export interface UIAttributeMetadata {
  list_column: boolean;
  list_column_order: number | null;
  search_weight: number;
  form_order: number | null;
  form_widget: string | null;
  form_visible: boolean;
  badge_colors: Record<string, string> | null;
  filter: boolean;
}

export interface AttributeDefinition {
  name: string;
  type: AttributeType;
  required: boolean;
  unique: boolean;
  indexed: boolean;
  default: unknown;
  description: string | null;
  enum_values: string[] | null;
  ui: UIAttributeMetadata;
}

export interface SchemaMetadata {
  name: string;
  display_name: string | null;
  description: string | null;
  icon: string | null;
  color: string | null;
  category: string | null;
  tags: string[];
}

export interface SearchMetadata {
  enabled: boolean;
  primary_field: string | null;
  search_fields: string[];
}

export interface GraphMetadata {
  default_label_field: string | null;
  size_field: string | null;
  group_by: string | null;
  style: string;
  color: string | null;
  show_label: boolean;
}

export interface APIMetadata {
  plural_name: string | null;
  filterable_fields: string[];
  sortable_fields: string[];
  default_sort: string | null;
  exposed: boolean;
}

export interface NodeTypeDefinition {
  kind: "NodeType";
  version: string;
  metadata: SchemaMetadata;
  attributes: Record<string, AttributeDefinition>;
  search: SearchMetadata;
  graph: GraphMetadata;
  api: APIMetadata;
}

export interface EdgeSourceTarget {
  node_types: string[];
}

export interface EdgeTypeDefinition {
  kind: "EdgeType";
  version: string;
  metadata: SchemaMetadata;
  source: EdgeSourceTarget;
  target: EdgeSourceTarget;
  cardinality: Cardinality;
  inverse_name: string | null;
  attributes: Record<string, AttributeDefinition>;
  graph: GraphMetadata;
  api: APIMetadata;
}

export interface Category {
  name: string;
  node_types: string[];
}

export interface UIMetadata {
  node_types: NodeTypeDefinition[];
  edge_types: EdgeTypeDefinition[];
  enum_types: unknown[];
  categories: Category[];
}

/** Query result from the backend — supports both table and graph rendering */
export interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  node_type: string;
  label: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  edge_type: string;
  source_id: string;
  target_id: string;
  properties: Record<string, unknown>;
}
