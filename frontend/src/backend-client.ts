import type { BackendSnapshot } from "./backend-state";

export interface Thread {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
export type RunStatus = "running" | "completed" | "cancelled" | "interrupted" | "error";
export interface Run {
  thread_id: string;
  run_id: string;
  status: RunStatus;
  usage?: { total_input: number; total_output: number; total_tokens: number } | null;
  usage_pending?: boolean;
}
export interface MessageContent {
  type: "human" | "ai" | "tool";
  message_id: string;
  content: string | (string | Record<string, unknown>)[];
  tool_calls?: { id: string; name: string; args: Record<string, unknown> }[];
  tool_call_id?: string;
  name?: string | null;
  status?: "success" | "error";
}
export interface StoredMessage {
  run_id: string;
  seq: number;
  content: MessageContent;
}
export type RunFrame =
  | { event: "metadata"; data: Run }
  | { event: "delta"; data: { seq: number; message_id: string; field: "content" | "reasoning"; value: string } }
  | { event: "event"; data:
    | { seq: number; category: "message"; payload: MessageContent }
    | { seq: number; category: "lifecycle"; payload: { status: RunStatus; message?: string; error_code?: string } }
    | { seq: number; category: "approval"; payload: unknown } }
  | { event: "error"; data: { code: string; message: string; recoverable: boolean } };

/** One address lease. Retained callers can never use it after the host revokes it. */
export class BackendSession {
  readonly startupId: string;
  readonly baseUrl: string;
  readonly signal: AbortSignal;
  private fetcher: typeof fetch;

  constructor(startupId: string, baseUrl: string, signal: AbortSignal, fetcher: typeof fetch) {
    this.startupId = startupId;
    this.baseUrl = baseUrl;
    this.signal = signal;
    this.fetcher = fetcher;
  }

  private async request(path: string, init: RequestInit, signal?: AbortSignal) {
    const combined = signal ? AbortSignal.any([this.signal, signal]) : this.signal;
    combined.throwIfAborted();
    const response = await this.fetcher(this.baseUrl + path, { ...init, signal: combined });
    if (combined.aborted) {
      await response.body?.cancel().catch(() => {});
      combined.throwIfAborted();
    }
    if (!response.ok) {
      const detail = await response.text();
      combined.throwIfAborted();
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    return { signal: combined, response };
  }

  private async json<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
    const request = await this.request(path, init, signal);
    const data = await request.response.json();
    request.signal.throwIfAborted();
    return data as T;
  }

  threads(signal?: AbortSignal) {
    return this.json<Thread[]>("/api/threads", {}, signal);
  }

  createThread() {
    return this.json<{ thread_id: string }>("/api/threads", { method: "POST" });
  }

  async messages(threadId: string, signal?: AbortSignal) {
    return (await this.json<{ data: StoredMessage[] }>(`/api/threads/${encodeURIComponent(threadId)}/messages`, {}, signal)).data;
  }

  send(threadId: string, message: string, receive: (frame: RunFrame) => void, signal?: AbortSignal) {
    return this.stream(`/api/threads/${encodeURIComponent(threadId)}/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }),
    }, receive, signal);
  }

  observe(threadId: string, runId: string, receive: (frame: RunFrame) => void, signal?: AbortSignal) {
    return this.stream(`/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/stream`, {}, receive, signal);
  }

  private async stream(path: string, init: RequestInit, receive: (frame: RunFrame) => void, signal?: AbortSignal) {
    const request = await this.request(path, init, signal);
    const response = request.response;
    if (!response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
      throw new Error("后端未返回事件流");
    }
    const reader = response.body.getReader();
    const cancel = () => { void reader.cancel().catch(() => {}); };
    request.signal.addEventListener("abort", cancel, { once: true });
    const decoder = new TextDecoder();
    let buffer = "", event = "", data: string[] = [];
    try {
      while (true) {
        const chunk = await reader.read();
        request.signal.throwIfAborted();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        let newline: number;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, newline).replace(/\r$/, "");
          buffer = buffer.slice(newline + 1);
          if (!line) {
            request.signal.throwIfAborted();
            if (data.length && ["metadata", "delta", "event", "error"].includes(event)) {
              receive({ event, data: JSON.parse(data.join("\n")) } as RunFrame);
            }
            event = "";
            data = [];
          } else if (line.startsWith("event:")) event = line.slice(6).replace(/^ /, "");
          else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        }
      }
    } finally {
      request.signal.removeEventListener("abort", cancel);
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}

/** Updated synchronously by the ordered host subscription, before React renders. */
export class BackendClient {
  session: BackendSession | null = null;
  private controller: AbortController | null = null;
  private fetcher: typeof fetch;

  constructor(fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) { this.fetcher = fetcher; }

  update(snapshot: BackendSnapshot | null) {
    const ready = snapshot?.state === "ready" && snapshot.startup_id && snapshot.base_url;
    if (ready && this.session?.startupId === snapshot.startup_id && this.session.baseUrl === snapshot.base_url) return;
    this.controller?.abort();
    this.controller = null;
    this.session = null;
    if (ready) {
      this.controller = new AbortController();
      this.session = new BackendSession(snapshot.startup_id!, snapshot.base_url!, this.controller.signal, this.fetcher);
    }
  }
}
