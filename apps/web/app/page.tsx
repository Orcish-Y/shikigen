"use client";

import { useChat } from "@ai-sdk/react";

export default function ChatPage() {
  const { messages, input, handleInputChange, handleSubmit, status } = useChat(
    {
      api: "/api/chat",
    }
  );

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
            <p className="text-sm whitespace-pre-wrap">{m.content}</p>
          </div>
        ))}
        {status === "submitted" && (
          <p className="text-zinc-500 text-sm">Thinking…</p>
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
