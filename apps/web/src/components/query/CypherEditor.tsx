/**
 * CypherEditor — Monaco-based Cypher query editor with syntax highlighting
 * and schema-aware autocomplete.
 */

import { useCallback, useRef } from "react";
import Editor, { OnMount } from "@monaco-editor/react";
import { useSchemaStore } from "@/stores/schemaStore";
import {
  cypherLanguage,
  cypherLanguageConfig,
  buildCompletionItems,
} from "@/lib/cypher";

interface CypherEditorProps {
  value: string;
  onChange: (value: string) => void;
  onExecute?: () => void;
  height?: string;
}

export function CypherEditor({
  value,
  onChange,
  onExecute,
  height = "200px",
}: CypherEditorProps) {
  const editorRef = useRef<any>(null);
  const { nodeTypes, edgeTypes } = useSchemaStore();

  const handleMount: OnMount = useCallback(
    (editor, monaco) => {
      editorRef.current = editor;

      // Register Cypher language if not already registered
      if (
        !monaco.languages
          .getLanguages()
          .some((lang: any) => lang.id === "cypher")
      ) {
        monaco.languages.register({ id: "cypher" });
        monaco.languages.setMonarchTokensProvider("cypher", cypherLanguage);
        monaco.languages.setLanguageConfiguration(
          "cypher",
          cypherLanguageConfig,
        );

        // Schema-aware autocomplete
        monaco.languages.registerCompletionItemProvider("cypher", {
          provideCompletionItems: (_model: any, position: any) => {
            const ntNames = Object.keys(nodeTypes);
            const etNames = Object.keys(edgeTypes);

            // Collect all property names from all node types
            const propNames = new Set<string>();
            Object.values(nodeTypes).forEach((nt) => {
              Object.keys(nt.attributes).forEach((p) => propNames.add(p));
            });

            const items = buildCompletionItems(
              ntNames,
              etNames,
              Array.from(propNames),
            );

            return {
              suggestions: items.map((item) => ({
                ...item,
                range: {
                  startLineNumber: position.lineNumber,
                  startColumn: position.column,
                  endLineNumber: position.lineNumber,
                  endColumn: position.column,
                },
              })),
            };
          },
        });
      }

      // Ctrl/Cmd+Enter to execute
      editor.addAction({
        id: "execute-query",
        label: "Execute Query",
        keybindings: [
          monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
        ],
        run: () => {
          onExecute?.();
        },
      });

      editor.focus();
    },
    [nodeTypes, edgeTypes, onExecute],
  );

  return (
    <Editor
      height={height}
      language="cypher"
      theme="vs-dark"
      value={value}
      onChange={(v) => onChange(v || "")}
      onMount={handleMount}
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        wordWrap: "on",
        tabSize: 2,
        automaticLayout: true,
        suggestOnTriggerCharacters: true,
        quickSuggestions: true,
        padding: { top: 8, bottom: 8 },
      }}
    />
  );
}
