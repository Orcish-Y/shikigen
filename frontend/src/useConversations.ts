import { useEffect, useState, useSyncExternalStore } from "react";
import { runStatusLabels, type BackendSession, type MessageContent } from "./backend-client";
import { ConversationStore, emptyConversation, type ConversationMessage } from "./conversation-state";
import { demoSessions, type Message, type Session } from "./data/demo";

function messageText(content: MessageContent["content"]): string {
  return typeof content === "string" ? content : content.map(block => {
    if (typeof block === "string") return block;
    return typeof block.text === "string" ? block.text : JSON.stringify(block);
  }).join("\n");
}

function displayMessage(message: ConversationMessage): Message {
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

/** 在 App 中挂载，工作台卸载或 BackendSession 换代不会重建会话所有者。 */
export function useConversations(session: BackendSession | null, previewMode = false) {
  const [store] = useState(() => new ConversationStore());
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const [preview, setPreview] = useState(demoSessions);
  const [previewId, setPreviewId] = useState(demoSessions[0].id);
  const [previewDrafts, setPreviewDrafts] = useState<Record<string, string>>({});
  useEffect(() => {
    store.setSession(session);
    return () => store.setSession(null);
  }, [store, session]);

  const activeId = previewMode ? previewId : state.activeId;
  const view = state.views[activeId] ?? emptyConversation;
  const sessions: Session[] = previewMode ? preview : state.threads.map(thread => ({
    id: thread.id, title: thread.title?.trim() ? thread.title : "新会话", group: "历史",
    summary: thread.updated_at || "更新时间待核实",
    messages: (state.views[thread.id]?.messages ?? []).map(displayMessage),
  }));
  const active = sessions.find(item => item.id === activeId) ?? {
    id: "", title: state.listing ? "正在读取会话" : "新建会话开始对话", group: "历史" as const,
    summary: "", messages: [],
  };
  let statusLabel = "未选择会话";
  if (activeId) {
    if (view.run) statusLabel = runStatusLabels[view.run.status];
    else if (view.history === "ready" && view.verified) statusLabel = "未开始";
    else if (view.history === "error") statusLabel = "读取失败";
    else statusLabel = "读取中";
  }
  return {
    sessions, active, activeId,
    select: (id: string) => previewMode ? setPreviewId(id) : store.select(id),
    create: async () => {
      if (!previewMode) return store.create();
      const item: Session = { id: crypto.randomUUID(), title: "新会话", group: "今天", summary: "尚未开始对话", messages: [] };
      setPreview(items => [item, ...items]);
      setPreviewId(item.id);
    },
    send: (message: string) => store.send(message),
    draft: (previewMode ? previewDrafts[activeId] : state.drafts[activeId]) ?? "",
    updateDraft: (value: string) => {
      if (!activeId) return;
      if (previewMode) setPreviewDrafts(current => ({ ...current, [activeId]: value }));
      else store.updateDraft(value);
    },
    run: view.run, statusLabel: previewMode ? "示例会话" : statusLabel,
    historyState: previewMode ? "ready" as const : view.history,
    loading: state.listing || view.history === "loading",
    verifying: Boolean(view.run && !view.verified && !view.error),
    creating: state.creating, sending: view.sending,
    error: state.listError ?? view.error,
    notice: state.notice,
    canSend: !previewMode && store.canSend(),
    reload: store.reload,
  };
}
