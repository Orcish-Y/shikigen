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
  error?: string | null;
  error_code?: string | null;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
}
export interface MessageContent {
  type: "human" | "ai" | "tool";
  message_id: string;
  content: string | (string | Record<string, unknown>)[];
  tool_calls?: { id: string; name: string; args: Record<string, unknown> }[];
  tool_call_id?: string;
  name?: string | null;
  status?: "success" | "error";
  artifact?: unknown;
}
export interface StoredMessage {
  id: number;
  thread_id: string;
  run_id: string;
  run_status: RunStatus;
  seq: number;
  event_type: string;
  category: "message";
  event_key: string | null;
  content: MessageContent;
  metadata: Record<string, unknown>;
  created_at: string;
}

export const runStatusLabels: Record<RunStatus, string> = {
  running: "运行中", interrupted: "等待审批", completed: "已完成",
  cancelled: "已取消", error: "运行失败",
};

function validStatus(value: unknown): value is RunStatus {
  return typeof value === "string" && Object.hasOwn(runStatusLabels, value);
}

function verifiedRun(value: Run, threadId: string, runId?: string): Run {
  if (value.thread_id !== threadId || typeof value.run_id !== "string" || !value.run_id.trim()
      || (runId !== undefined && value.run_id !== runId)) throw new Error("运行身份与请求不一致");
  if (!validStatus(value.status)) throw new Error("无法识别运行状态");
  return value;
}

export class BackendRequestError extends Error {
  readonly status: number;
  readonly retryAfter: string | null;
  constructor(status: number, detail: string, retryAfter: string | null) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.retryAfter = retryAfter;
  }
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
      throw new BackendRequestError(response.status, detail, response.headers.get("Retry-After"));
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
    return this.json<Thread[]>("/api/threads", { cache: "no-store" }, signal);
  }

  async createThread() {
    const result = await this.json<{ thread_id: string }>("/api/threads", { method: "POST" });
    if (typeof result.thread_id !== "string" || !result.thread_id.trim()) throw new Error("新建会话未返回有效身份");
    return result;
  }

  async messages(threadId: string, signal?: AbortSignal) {
    const { data } = await this.json<{ data: StoredMessage[] }>(
      `/api/threads/${encodeURIComponent(threadId)}/messages`, { cache: "no-store" }, signal);
    if (!Array.isArray(data)) throw new Error("会话历史格式无效");
    const statuses = new Map<string, RunStatus>();
    const sequences = new Set<number>();
    for (const message of data) {
      if (message.thread_id !== threadId || typeof message.run_id !== "string" || !message.run_id.trim()) {
        throw new Error("消息身份与会话不一致");
      }
      if (!validStatus(message.run_status) || (statuses.has(message.run_id) && statuses.get(message.run_id) !== message.run_status)) {
        throw new Error("消息所属运行状态无效或不一致");
      }
      if (!Number.isSafeInteger(message.seq) || message.seq < 1 || sequences.has(message.seq)) throw new Error("消息顺序无效");
      statuses.set(message.run_id, message.run_status);
      sequences.add(message.seq);
    }
    return data.sort((a, b) => a.seq - b.seq);
  }

  async runSnapshot(threadId: string, runId: string, signal?: AbortSignal): Promise<Run> {
    const { data } = await this.json<{ data: Omit<Run, "run_id"> & { id: string } }>(
      `/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}`, { cache: "no-store" }, signal);
    const { id, ...fields } = data;
    return verifiedRun({ ...fields, run_id: id }, threadId, runId);
  }

  send(threadId: string, message: string, receive: (frame: RunFrame) => void, signal?: AbortSignal) {
    return this.stream(`/api/threads/${encodeURIComponent(threadId)}/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }),
    }, this.runReceiver(threadId, receive), signal);
  }

  observe(threadId: string, runId: string, receive: (frame: RunFrame) => void, signal?: AbortSignal) {
    return this.stream(`/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/stream`, {}, this.runReceiver(threadId, receive, runId), signal);
  }

  private runReceiver(threadId: string, receive: (frame: RunFrame) => void, runId?: string) {
    return (frame: RunFrame) => {
      if (frame.event === "metadata") {
        verifiedRun(frame.data, threadId, runId);
        runId = frame.data.run_id;
      }
      receive(frame);
    };
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
