import { useEffect, useRef, useState } from "react";
import type { BackendSession, MessageContent, Run, RunFrame, StoredMessage, Thread } from "./backend-client";
import { demoSessions, type Message, type Session } from "./data/demo";

function messageText(content: MessageContent["content"]): string {
  return typeof content === "string" ? content : content.map(block => {
    if (typeof block === "string") return block;
    return typeof block.text === "string" ? block.text : JSON.stringify(block);
  }).join("\n");
}

function displayMessage(message: StoredMessage): Message {
  const content = message.content;
  const text = messageText(content.content);
  return {
    id: String(message.seq),
    role: content.type === "human" ? "user" : "assistant",
    text: content.type === "tool" ? "" : text + (content.tool_calls?.length
      ? "\n" + content.tool_calls.map(call => `${call.name}(${JSON.stringify(call.args)})`).join("\n") : ""),
    ...(content.type === "tool" ? { tool: {
      name: content.name ?? "工具", command: content.tool_call_id ?? "",
      output: text, status: content.status,
    } } : {}),
  };
}

interface View {
  messages: StoredMessage[];
  run: Run | null;
  error: string | null;
  loading: boolean;
}
const emptyView: View = { messages: [], run: null, error: null, loading: false };

/** Reconstruct the selected Thread from persisted messages and read-only Run SSE. */
export function useConversations(session: BackendSession | null) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [preview, setPreview] = useState(demoSessions);
  const [activeId, setActiveId] = useState(session ? "" : demoSessions[0].id);
  const [listing, setListing] = useState(Boolean(session));
  const [creating, setCreating] = useState(false);
  const creatingRef = useRef(false);
  const sendingRef = useRef(false);
  const [sending, setSending] = useState(false);
  const [view, setView] = useState<View>(emptyView);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const selection = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    void session.threads(controller.signal).then(items => {
      if (controller.signal.aborted || session.signal.aborted) return;
      setThreads(items);
      setActiveId(current => items.some(item => item.id === current) ? current : items[0]?.id ?? "");
      setLoadError(null);
    }).catch(error => {
      if (!controller.signal.aborted && !session.signal.aborted) setLoadError(String(error));
    }).finally(() => {
      if (!controller.signal.aborted && !session.signal.aborted) setListing(false);
    });
    return () => controller.abort();
  }, [session, refresh]);

  function receiveFor(controller: AbortController, threadId: string, initial: StoredMessage[] = []) {
    const messages = new Map(initial.map(message => [message.seq, message]));
    let run: Run | null = null;
    let error: string | null = null;
    const publish = () => {
      if (controller.signal.aborted || session?.signal.aborted) return;
      setView({ messages: [...messages.values()].sort((a, b) => a.seq - b.seq), run, error, loading: false });
    };
    return (frame: RunFrame) => {
      if (controller.signal.aborted || session?.signal.aborted) return;
      if (frame.event === "metadata") {
        run = { ...run, ...frame.data };
      } else if (frame.event === "event") {
        const data = frame.data;
        if (data.category === "message") messages.set(data.seq, {
          seq: data.seq, run_id: run?.run_id ?? "", content: data.payload,
        });
        if (data.category === "lifecycle") {
          // Lifecycle facts include past pauses/resumes. Metadata supplies the
          // current snapshot and every live status change; replay cannot undo it.
          if (data.payload.message) error = data.payload.message;
        }
      } else if (frame.event === "error") {
        error = `${frame.data.message} (${frame.data.code})`;
      } else if (frame.event === "delta" && frame.data.field === "content") {
        const data = frame.data;
        const prior = messages.get(data.seq);
        // A full persisted message wins over replayed preview deltas.
        if (!prior || prior.content.message_id === `preview:${data.message_id}`) {
          messages.set(data.seq, { seq: data.seq, run_id: run?.run_id ?? "", content: {
            type: "ai", message_id: `preview:${data.message_id}`,
            content: (prior ? messageText(prior.content.content) : "") + data.value,
          } });
        }
      }
      if (run?.thread_id === threadId || !run) publish();
    };
  }

  useEffect(() => {
    if (!session || !activeId) return;
    const controller = new AbortController();
    selection.current = controller;
    setView({ ...emptyView, loading: true });
    void (async () => {
      try {
        const messages = await session.messages(activeId, controller.signal);
        if (controller.signal.aborted || session.signal.aborted) return;
        setView({ ...emptyView, messages });
        const runId = messages.at(-1)?.run_id;
        if (runId) await session.observe(activeId, runId, receiveFor(controller, activeId, messages), controller.signal);
      } catch (error) {
        if (!controller.signal.aborted && !session.signal.aborted) {
          setView(current => ({ ...current, loading: false, error: `读取会话失败：${String(error)}` }));
        }
      }
    })();
    return () => { controller.abort(); if (selection.current === controller) selection.current = null; };
  }, [session, activeId, refresh]);

  function select(id: string) {
    if (id === activeId) return;
    selection.current?.abort();
    setView(emptyView);
    setSending(false);
    sendingRef.current = false;
    setActiveId(id);
  }

  async function create() {
    if (!session) {
      const item: Session = { id: crypto.randomUUID(), title: "新会话", group: "今天", summary: "尚未开始对话", messages: [] };
      setPreview(items => [item, ...items]);
      select(item.id);
      return;
    }
    if (listing || creatingRef.current || session.signal.aborted) return;
    creatingRef.current = true;
    setCreating(true);
    try {
      const { thread_id } = await session.createThread();
      if (session.signal.aborted) return;
      setThreads(await session.threads());
      if (session.signal.aborted) return;
      select(thread_id);
      setLoadError(null);
    } catch (error) {
      if (!session.signal.aborted) setLoadError(`创建会话失败：${String(error)}。请刷新数据确认是否已创建。`);
    } finally {
      creatingRef.current = false;
      if (!session.signal.aborted) setCreating(false);
    }
  }

  const canSend = Boolean(session && activeId && !listing && !view.loading && !sending && !["running", "interrupted"].includes(view.run?.status ?? ""));

  function send(message: string): boolean {
    if (!session || session.signal.aborted || !canSend || sendingRef.current) return false;
    selection.current?.abort();
    const controller = new AbortController();
    selection.current = controller;
    sendingRef.current = true;
    setSending(true);
    setView(current => ({ ...current, error: null }));
    void session.send(activeId, message, receiveFor(controller, activeId, view.messages), controller.signal).catch(error => {
      if (!controller.signal.aborted && !session.signal.aborted) {
        setLoadError(`发送连接中断：${String(error)}。正在读取已保存的结果；不会自动重发。`);
      }
    }).finally(() => {
      if (controller.signal.aborted || session.signal.aborted) return;
      sendingRef.current = false;
      setSending(false);
      // Only GET reads after a send, including uncertain network outcomes.
      setRefresh(value => value + 1);
    });
    return true;
  }

  useEffect(() => () => selection.current?.abort(), []);
  const sessions: Session[] = session ? threads.map(thread => ({
    id: thread.id, title: thread.title || `会话 ${thread.id.slice(0, 8)}`, group: "历史",
    summary: thread.updated_at, messages: thread.id === activeId ? view.messages.map(displayMessage) : [],
  })) : preview;
  const active = sessions.find(item => item.id === activeId) ?? {
    id: "", title: listing ? "正在读取会话" : "新建会话开始对话", group: "历史" as const,
    summary: "", messages: [],
  };
  return {
    sessions, active, activeId, select, create, send, run: view.run,
    loading: listing || view.loading, creating, sending,
    error: loadError ?? view.error,
    canSend,
    reload: () => { selection.current?.abort(); setLoadError(null); setListing(true); setRefresh(value => value + 1); },
  };
}
