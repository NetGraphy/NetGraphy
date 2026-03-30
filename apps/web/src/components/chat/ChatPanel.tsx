/**
 * ChatPanel — Embedded AI assistant panel that docks to the right side of the app.
 *
 * Features:
 * - Streaming SSE responses
 * - Conversation history
 * - Tool invocation display
 * - Confirmation cards for destructive actions
 * - Minimizable/maximizable
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

interface Message {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
}

interface Conversation {
  id: string;
  title: string;
  status: string;
  created_at: string;
  messages?: Message[];
}

export function ChatPanel({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Conversation list
  const { data: convsData } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.get("/agent/conversations"),
    enabled: showHistory,
  });
  const conversations: Conversation[] = convsData?.data?.data || [];

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when panel opens
  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const loadConversation = useCallback(async (convId: string) => {
    const resp = await api.get(`/agent/conversations/${convId}`);
    const conv = resp.data.data;
    setConversationId(convId);
    setMessages(
      (conv.messages || []).map((m: Message) => ({
        role: m.role || "user",
        content: m.content || "",
        metadata: m.metadata,
      }))
    );
    setShowHistory(false);
  }, []);

  const newConversation = () => {
    setConversationId(null);
    setMessages([]);
  };

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isStreaming) return;
    const userMsg = input.trim();
    setInput("");

    // Add user message immediately
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setIsStreaming(true);

    try {
      // Use non-streaming endpoint for reliability
      const resp = await api.post("/agent/chat", {
        message: userMsg,
        conversation_id: conversationId,
      });

      const data = resp.data.data;
      if (!conversationId && data.conversation_id) {
        setConversationId(data.conversation_id);
      }

      // Add assistant response
      const assistantMsg: Message = {
        role: "assistant",
        content: data.content || "",
        metadata: {
          model: data.model,
          provider: data.provider,
          tool_calls: data.tool_calls_made,
          steps: data.steps,
        },
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Handle confirmation required
      if (data.confirmation_required) {
        setMessages((prev) => [
          ...prev,
          {
            role: "system",
            content: `Confirmation required for **${data.confirmation_required.tool}**. Reply "yes" to proceed.`,
          },
        ]);
      }
    } catch (err: unknown) {
      const errMsg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to get response";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${errMsg}` },
      ]);
    } finally {
      setIsStreaming(false);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }
  }, [input, isStreaming, conversationId, queryClient]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const [copySuccess, setCopySuccess] = useState(false);
  const copyConversation = useCallback(() => {
    const formatted = messages
      .map((msg) => {
        const label =
          msg.role === "user"
            ? "User"
            : msg.role === "assistant"
              ? "NetGraphy AI"
              : "System";
        return `${label}:\n${msg.content}`;
      })
      .join("\n\n---\n\n");
    navigator.clipboard.writeText(formatted).then(() => {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    });
  }, [messages]);

  if (!isOpen) return null;

  return (
    <div className="flex w-96 flex-col border-l border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <svg className="h-5 w-5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          <span className="text-sm font-semibold text-gray-900 dark:text-white">AI Assistant</span>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button onClick={copyConversation} title="Copy conversation"
              className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700">
              {copySuccess ? (
                <svg className="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              )}
            </button>
          )}
          <button onClick={() => setShowHistory(!showHistory)}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </button>
          <button onClick={newConversation}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Conversation history sidebar */}
      {showHistory && (
        <div className="border-b border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-900">
          <div className="mb-1 text-xs font-semibold text-gray-500">Recent Conversations</div>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {conversations.map((c) => (
              <button key={c.id} onClick={() => loadConversation(c.id)}
                className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs ${
                  conversationId === c.id ? "bg-brand-100 text-brand-700" : "hover:bg-gray-100 dark:hover:bg-gray-700"
                }`}>
                <span className="truncate">{c.title || "Untitled"}</span>
              </button>
            ))}
            {conversations.length === 0 && <div className="py-2 text-center text-xs text-gray-400">No conversations</div>}
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <svg className="mb-3 h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
            <div className="text-sm text-gray-500">Ask specific questions for best results</div>
            <div className="mt-1 mb-2 text-[10px] text-gray-400 max-w-[280px]">
              Tip: Narrow queries by site, status, role, or relationship to avoid large result sets.
            </div>
            <div className="mt-1 flex flex-wrap justify-center gap-1">
              {[
                "Devices in the Dallas data center",
                "Active circuits from AT&T",
                "Sites with no devices",
                "Count devices by role",
              ].map((q) => (
                <button key={q} onClick={() => { setInput(q); }}
                  className="rounded-full bg-gray-100 px-2 py-1 text-[10px] text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`mb-3 ${msg.role === "user" ? "flex justify-end" : ""}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "bg-brand-600 text-white"
                : msg.role === "system"
                  ? "border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300"
                  : "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200"
            }`}>
              <div className="whitespace-pre-wrap">{msg.content}</div>
              {msg.metadata?.steps && (msg.metadata.steps as { type: string; tool: string }[]).length > 0 && (
                <div className="mt-2 border-t border-gray-200 pt-1 dark:border-gray-600">
                  <div className="text-[10px] font-medium text-gray-500">Steps:</div>
                  {(msg.metadata.steps as { type: string; tool: string; content: string }[]).map((s, j) => (
                    <div key={j} className="text-[10px] text-gray-400">
                      {s.type === "tool_call" || s.type === "tool_result"
                        ? `Tool: ${s.tool}`
                        : s.type}
                    </div>
                  ))}
                </div>
              )}
              {msg.metadata?.model && (
                <div className="mt-1 text-[10px] text-gray-400">
                  {msg.metadata.model as string} | {msg.metadata.tool_calls as number || 0} tool calls
                </div>
              )}
            </div>
          </div>
        ))}

        {isStreaming && (
          <div className="mb-3">
            <div className="inline-flex items-center gap-1 rounded-lg bg-gray-100 px-3 py-2 dark:bg-gray-700">
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: "0ms" }} />
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: "150ms" }} />
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: "300ms" }} />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-3 dark:border-gray-700">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your network..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming}
            className="rounded-lg bg-brand-600 px-3 py-2 text-white hover:bg-brand-700 disabled:opacity-50"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
        <div className="mt-1 text-[10px] text-gray-400">Enter to send, Shift+Enter for new line</div>
      </div>
    </div>
  );
}
