/**
 * Cypher language definition for Monaco Editor.
 *
 * Provides syntax highlighting via Monarch tokenizer and basic
 * schema-aware autocomplete suggestions.
 */

import type { languages } from "monaco-editor";

/**
 * Monarch tokenizer for Cypher query language.
 * Covers keywords, functions, operators, strings, numbers, comments, and parameters.
 */
export const cypherLanguage: languages.IMonarchLanguage = {
  defaultToken: "",
  ignoreCase: true,

  keywords: [
    "MATCH", "OPTIONAL", "WHERE", "RETURN", "WITH", "UNWIND", "ORDER", "BY",
    "SKIP", "LIMIT", "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE",
    "ON", "AS", "AND", "OR", "NOT", "IN", "IS", "NULL", "TRUE", "FALSE",
    "CASE", "WHEN", "THEN", "ELSE", "END", "DISTINCT", "ASC", "DESC",
    "ASCENDING", "DESCENDING", "EXISTS", "UNION", "ALL", "CALL", "YIELD",
    "FOREACH", "EXPLAIN", "PROFILE", "USING", "INDEX", "CONSTRAINT",
    "ASSERT", "UNIQUE", "NODE", "RELATIONSHIP", "TYPE",
  ],

  functions: [
    "count", "collect", "sum", "avg", "min", "max", "stdev", "percentileDisc",
    "percentileCont", "head", "last", "tail", "size", "length", "type",
    "startNode", "endNode", "id", "elementId", "labels", "keys", "properties",
    "nodes", "relationships", "range", "reduce", "extract", "filter", "any",
    "none", "single", "exists", "coalesce", "timestamp", "date", "datetime",
    "duration", "time", "localtime", "localdatetime", "toString", "toInteger",
    "toFloat", "toBoolean", "toLower", "toUpper", "trim", "ltrim", "rtrim",
    "replace", "split", "reverse", "substring", "left", "right",
    "abs", "ceil", "floor", "round", "sign", "rand", "log", "log10", "sqrt",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "pi", "e",
    "point", "distance", "shortestPath", "allShortestPaths",
  ],

  operators: [
    "=", "<>", "<", ">", "<=", ">=", "+", "-", "*", "/", "%", "^",
    "=~", "STARTS WITH", "ENDS WITH", "CONTAINS",
  ],

  symbols: /[=><!~?:&|+\-*/^%]+/,

  tokenizer: {
    root: [
      // Comments
      [/\/\/.*$/, "comment"],

      // Strings
      [/"([^"\\]|\\.)*$/, "string.invalid"],
      [/'([^'\\]|\\.)*$/, "string.invalid"],
      [/"/, "string", "@doubleString"],
      [/'/, "string", "@singleString"],

      // Parameters
      [/\$[a-zA-Z_]\w*/, "variable"],

      // Numbers
      [/\d*\.\d+([eE][-+]?\d+)?/, "number.float"],
      [/\d+/, "number"],

      // Labels and relationship types
      [/:[A-Z][A-Za-z0-9_]*/, "type.identifier"],

      // Identifiers and keywords
      [
        /[a-zA-Z_]\w*/,
        {
          cases: {
            "@keywords": "keyword",
            "@functions": "predefined",
            "@default": "identifier",
          },
        },
      ],

      // Operators
      [/@symbols/, "operator"],

      // Brackets
      [/[{}()[\]]/, "@brackets"],

      // Delimiters
      [/[,;.]/, "delimiter"],
    ],

    doubleString: [
      [/[^\\"]+/, "string"],
      [/\\./, "string.escape"],
      [/"/, "string", "@pop"],
    ],

    singleString: [
      [/[^\\']+/, "string"],
      [/\\./, "string.escape"],
      [/'/, "string", "@pop"],
    ],
  },
};

/**
 * Cypher language configuration for bracket matching and auto-closing.
 */
export const cypherLanguageConfig: languages.LanguageConfiguration = {
  comments: { lineComment: "//" },
  brackets: [
    ["{", "}"],
    ["[", "]"],
    ["(", ")"],
  ],
  autoClosingPairs: [
    { open: "{", close: "}" },
    { open: "[", close: "]" },
    { open: "(", close: ")" },
    { open: '"', close: '"' },
    { open: "'", close: "'" },
  ],
  surroundingPairs: [
    { open: "{", close: "}" },
    { open: "[", close: "]" },
    { open: "(", close: ")" },
    { open: '"', close: '"' },
    { open: "'", close: "'" },
  ],
};

/**
 * Build schema-aware autocomplete suggestions from the schema store.
 */
export function buildCompletionItems(
  nodeTypes: string[],
  edgeTypes: string[],
  propertyNames: string[],
): languages.CompletionItem[] {
  const items: languages.CompletionItem[] = [];

  // Node type labels
  for (const nt of nodeTypes) {
    items.push({
      label: nt,
      kind: 1, // Class
      insertText: nt,
      detail: "Node Type",
      documentation: `Match nodes with label :${nt}`,
    } as languages.CompletionItem);
  }

  // Edge type labels
  for (const et of edgeTypes) {
    items.push({
      label: et,
      kind: 2, // Function
      insertText: et,
      detail: "Edge Type",
      documentation: `Relationship type [:${et}]`,
    } as languages.CompletionItem);
  }

  // Property names
  for (const prop of propertyNames) {
    items.push({
      label: prop,
      kind: 5, // Field
      insertText: prop,
      detail: "Property",
    } as languages.CompletionItem);
  }

  return items;
}
