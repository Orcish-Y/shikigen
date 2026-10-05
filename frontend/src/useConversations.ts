import { useEffect, useState, useSyncExternalStore } from "react";
import { runStatusLabels, type BackendSession, type MessageContent } from "./backend-client";
import { ConversationStore, emptyConversation, type ConversationMessage } from "./conversation-state";
import { demoSessions, type Message, type Session } from "./data/demo";
import { observationLabels } from './observation-recovery';

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
    preview: message.preview === true,
    role: content.type === "human" ? "user" : content.type === 'tool' ? 'tool' : "assistant",
    content:content.content,
    toolCalls:content.tool_calls,
    text: content.type === "tool" ? "" : text,
    ...(content.type === "tool" ? { tool: {
      name: content.name ?? "工具", command: content.tool_call_id ?? "",
      output: text, status: content.status,
    } } : {}),
  };
}

/** 在 App 中挂载，工作台卸载或 BackendSession 换代不会重建会话所有者。 */
export function useConversations(session: BackendSession | null, previewMode = false, visible = true) {
  const [store] = useState(() => new ConversationStore());
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const [preview, setPreview] = useState(demoSessions);
  const [previewId, setPreviewId] = useState(demoSessions[0].id);
  const [previewDrafts, setPreviewDrafts] = useState<Record<string, string>>({});
  useEffect(() => {store.setVisible(visible);}, [store, visible]);
  useEffect(() => {
    store.setSession(session);
    return () => store.setSession(null);
  }, [store, session]);

  const activeId = previewMode ? previewId : state.activeId;
  const view = state.views[activeId] ?? emptyConversation;
  const sessions: Session[] = previewMode ? preview : state.threads.map(thread => ({
    id: thread.id, title: thread.title?.trim() ? thread.title : "新会话", group: "历史",
    summary: thread.updated_at || "更新时间待核实",
    status: thread.run_status ? runStatusLabels[thread.run_status] : "未开始",
    messages: (state.views[thread.id]?.messages ?? []).map(displayMessage),
  }));
  const active = sessions.find(item => item.id === activeId) ?? {
    id: activeId, title: activeId ? '会话待核实' : state.listing ? "正在读取会话" : "新建会话开始对话", group: "历史" as const,
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
    submission: state.submissions[activeId],
    confirmSend: (seq:number, id:string) => store.confirmSend(seq, id),
    sendAsNewTask: (id:string) => store.sendAsNewTask(id),
    canSendAsNewTask: !previewMode && store.canSendAsNewTask(),
    submittedUserMessages: view.messages.filter(message => message.content.type === 'human' && !message.preview),
    canConfirmSend: view.verified && view.history === 'ready',
    missing: view.missing,
    copyDraftToNewConversation: store.copyDraftToNewConversation,
    storageIssue: state.storageIssue,
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
    error: view.error,
    protocolIssue:view.protocolIssue,
    sendFailure:view.sendFailure,
    observationView:view,
    observationLabel:previewMode ? '示例观察' : observationLabels[view.observation],
    reconnect:store.reconnect,
    queryStatus:store.queryStatus,
    approvalStatus: previewMode || view.run?.status !== 'interrupted' ? null
      : view.approval?.verified ? '审批请求已核实，等待处理。'
      : view.observation === 'connecting' || view.observation === 'open' ? '正在重建审批请求…'
      : '审批尚未恢复，请刷新数据重新核实。',
    pagination: previewMode ? undefined : {
      loaded: state.listLoaded, refreshing: state.listing, loadingMore: state.loadingMore,
      hasMore: state.nextCursor !== null, listError: state.listError, pageError: state.pageError,
      onMore: store.loadMore, onReload: store.reloadThreads,
    },
    notice: state.notice,
    canSend: !previewMode && store.canSend(),
    reload: store.reload,
  };
}
