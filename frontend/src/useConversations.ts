import { useEffect, useState, useSyncExternalStore } from "react";
import { runStatusLabels, type BackendSession } from "./backend-client";
import { ConversationStore, emptyConversation } from "./conversation-state";
import { demoSessions, type Session } from "./data/demo";
import { presentMessage } from './message-presentation';
import { ToolCardPreferences } from './tool-card-preferences';
import { ChatReadingPositions, readingHistoryReady } from './chat-reading-position';
import { observationLabels } from './observation-recovery';
import { collectApprovalRecords, type ApprovalChoice } from './approval-decisions';

/** 在 App 中挂载，工作台卸载或 BackendSession 换代不会重建会话所有者。 */
export function useConversations(session: BackendSession | null, previewMode = false, visible = true) {
  const [store] = useState(() => new ConversationStore());
  const [toolPreferences] = useState(() => new ToolCardPreferences());
  const [readingPositions] = useState(() => new ChatReadingPositions());
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
    messages: (state.views[thread.id]?.messages ?? []).map(presentMessage),
    runStatuses:state.views[thread.id]?.runStatuses,
  }));
  const active = sessions.find(conversation => conversation.id === activeId) ?? {
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
    sessions, active, activeId, toolPreferences, readingPositions, visible,
    readingFactsReady:previewMode || readingHistoryReady(view),
    acceptedSendId:view.acceptedSendId,
    select: (id: string) => previewMode ? setPreviewId(id) : store.select(id),
    create: async () => {
      if (!previewMode) return store.create();
      const conversation: Session = { id: crypto.randomUUID(), title: "新会话", group: "今天", summary: "尚未开始对话", messages: [] };
      setPreview(conversations => [conversation, ...conversations]);
      setPreviewId(conversation.id);
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
    canReconnect:!previewMode && store.canReconnect(),
    queryStatus:store.queryStatus,
    canCancel:!previewMode && store.canCancel(),
    cancelTarget:() => store.cancelTarget(),
    cancel:(target:Parameters<ConversationStore['cancel']>[0]) => store.cancel(target),
    validCancelTarget:(target:Parameters<ConversationStore['canCancel']>[0]) => store.canCancel(target),
    write:view.write,
    approvalCards:previewMode ? [] : collectApprovalRecords(view.events),
    approvalRecoveryRecords:previewMode ? [] : state.approvalBackups.filter(record=>record.threadId===activeId
      &&(record.submission?.status==='unknown'||!collectApprovalRecords(view.events).some(approval=>approval.identity===record.draft.identity))),
    approvalDraft:view.approvalDraft,
    currentApproval:view.approval,
    acceptedApproval:view.acceptedApproval,
    canEditApproval:(identity:string) => !previewMode && store.canEditApproval(identity),
    canSubmitApproval:(identity:string) => !previewMode && store.canSubmitApproval(identity),
    chooseApproval:(identity:string, interruptId:string, index:number, choice:Partial<ApprovalChoice>) => store.chooseApproval(identity, interruptId, index, choice),
    submitApproval:(identity:string) => store.submitApproval(identity),
    savedContent:view.savedContent,
    savedContentFailure:view.savedContentFailure,
    retrySavedContent:store.retrySavedContent,
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
