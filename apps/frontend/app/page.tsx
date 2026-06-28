"use client";

import { useChat } from "@ai-sdk/react";
import { useState } from "react";

function ToolCallCard({
  name,
  input,
  output,
}: {
  name: string;
  input: Record<string, unknown>;
  output?: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="my-2 text-xs border border-zinc-700 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-zinc-400">{expanded ? "▾" : "▸"}</span>
        <span className="text-yellow-400 font-mono">{name}</span>
        {output ? (
          <span className="text-green-400 ml-auto">✓</span>
        ) : (
          <span className="text-zinc-500 ml-auto animate-pulse">…</span>
        )}
      </button>
      {expanded && (
        <div className="px-3 py-2 space-y-1 bg-zinc-900/50">
          <div>
            <span className="text-zinc-500">Input:</span>
            <pre className="text-zinc-300 mt-0.5 whitespace-pre-wrap">
              {JSON.stringify(input, null, 2)}
            </pre>
          </div>
          {output && (
            <div>
              <span className="text-zinc-500">Output:</span>
              <pre className="text-green-300 mt-0.5 whitespace-pre-wrap max-h-32 overflow-y-auto">
                {output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessagePart({
  part,
}: {
  part: {
    type: string;
    text?: string;
    toolName?: string;
    input?: Record<string, unknown>;
    output?: string;
    state?: string;
  };
}) {
  switch (part.type) {
    case "text":
      return <p className="text-sm whitespace-pre-wrap">{part.text}</p>;
    case "tool-call":
    case "tool-result":
      return (
        <ToolCallCard
          name={part.toolName || "unknown"}
          input={part.input || {}}
          output={part.output}
        />
      );
    default:
      return null;
  }
}

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit, status } = useChat({
    api: "/api/chat",
  });

  return (
    <main className="flex flex-col h-screen max-w-2xl mx-auto p-4">
      <h1 className="text-lg font-bold py-4 border-b border-zinc-800">
        Shikigen
      </h1>

      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`p-3 rounded-lg max-w-[85%] ${
              m.role === "user"
                ? "bg-zinc-700 ml-auto"
                : "bg-zinc-800 mr-auto"
            }`}
          >
            {m.parts ? (
              m.parts.map((part, i) => <MessagePart key={i} part={part} />)
            ) : (
              <p className="text-sm whitespace-pre-wrap">{m.content}</p>
            )}
          </div>
        ))}
        {status === "submitted" && (
          <div className="flex items-center gap-2 text-zinc-500 text-sm">
            <span className="animate-spin">⏳</span>
            Thinking…
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="py-4 border-t border-zinc-800">
        <input
          className="w-full p-3 rounded-lg bg-zinc-800 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-zinc-600"
          value={input}
          placeholder="Send a message…"
          onChange={handleInputChange}
        />
      </form>
    </main>
  );
}
