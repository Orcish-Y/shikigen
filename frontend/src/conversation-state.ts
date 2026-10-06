import { BackendRequestError, type BackendSession, type Run, type RunFrame, type RunEvent, type Thread } from "./backend-client.ts";
import { RunProjection, sameFact, terminalRun, type ApprovalProjection, type ConversationMessage } from './run-projection.ts';
import { RunProtocolError } from './run-protocol.ts';
import { MessageDrafts, type DraftStorage, type MessageSubmission } from './message-drafts.ts';
import { ObservationRecovery, StreamObservationError, UnexpectedObservationEnd, observationFailure, retryAfterTime, waitUntil, type ObservationState, type ObservationFailure, type RecoveryUpdate } from './observation-recovery.ts';
import { collectApprovalRecords, createApprovalIdentity, buildApprovalResponses, parseApproval, updateApprovalChoice, type ApprovalChoice, type ApprovalDraft } from './approval-decisions.ts';
import { ApprovalDrafts, type ApprovalBackup } from './approval-drafts.ts';
import { RunEventHistoryReader, emptyEventRead, type EventRead } from './run-event-history.ts';
import { UsageVerificationCoordinator, emptyUsageVerification, createUsageTargetKey, type UsageVerification } from './usage-verification.ts';
import { ConversationTitles } from './conversation-titles.ts';
export type { ConversationMessage } from './run-projection.ts';

const THREAD_PAGE_SIZE = 20;
export interface CancelTarget {threadId:string; runId:string; startupId:string; baseUrl:string}
export interface RunWriteState {
  runId:string; kind:'cancel' | 'approval'; phase:'pending' | 'unknown';
  verified:boolean; verifying:boolean; retryAt:number; failure:ObservationFailure | null;
  identity?:string; submissionId?:string;
}

export interface ListFailure { message: string; retryAt: number; invalidCursor: boolean }
export interface SnapshotRead {
  phase:'idle' | 'reading' | 'ready' | 'error';
  failure:ObservationFailure | null;
  retry:RecoveryUpdate['retry'];
}
const emptySnapshotRead:SnapshotRead = {phase:'idle', failure:null, retry:null};
function listFailure(error: unknown): ListFailure {
  const retry = error instanceof BackendRequestError ? error.retryAfter : null;
  const retryAt = retryAfterTime(retry);
  return { message: `读取会话列表失败：${String(error)}`,
    retryAt: Number.isFinite(retryAt) ? retryAt : 0,
    invalidCursor: error instanceof BackendRequestError && error.status === 422 };
}

// 完整历史记录原样保留；SSE 消息和临时正文没有数据库记录的全部外层字段。
export interface ConversationView {
  messages: ConversationMessage[];
  run: Run | null;
  runStatuses:Record<string, Run['status']>;
  history: "idle" | "loading" | "ready" | "error";
  verified: boolean;
  error: string | null;
  sending: boolean;
  acceptedSendId: string | null;
  events: ReturnType<RunProjection['snapshot']>['events'];
  approval: ApprovalProjection | null;
  approvalDraft:ApprovalDraft | null;
  acceptedApproval:string | null;
  observation: ObservationState;
  retry: RecoveryUpdate['retry'];
  observationFailure: ObservationFailure | null;
  querying: boolean;
  queryFailure: ObservationFailure | null;
  sendFailure: ObservationFailure | null;
  protocolIssue: {message:string; raw:unknown} | null;
  missing: boolean;
  write:RunWriteState | null;
  savedContent:'idle' | 'reading' | 'ready' | 'error';
  savedContentFailure:ObservationFailure | null;
  snapshotRead:SnapshotRead;
  eventRead:EventRead;
  usageVerification:UsageVerification;
}
export interface ConversationState {
  threads: Thread[];
  activeId: string;
  views: Record<string, ConversationView>;
  drafts: Record<string, string>;
  listing: boolean;
  listLoaded: boolean;
  loadingMore: boolean;
  nextCursor: string | null;
  pageError: ListFailure | null;
  creating: boolean;
  listError: ListFailure | null;
  notice: string | null;
  storageIssue: string | null;
  submissions: Record<string, MessageSubmission>;
  approvalBackups:ApprovalBackup[];
  temporaryTitles:Record<string, string>;
  titleStorageIssue:string | null;
}
export const emptyConversation: ConversationView = {
  messages: [], run: null, runStatuses:{}, history: "idle", verified: false, error: null, sending: false, acceptedSendId:null, events:{}, approval:null, approvalDraft:null, acceptedApproval:null, observation:'idle', retry:null, observationFailure:null, querying:false, queryFailure:null, sendFailure:null, protocolIssue:null, missing:false, write:null, savedContent:'idle', savedContentFailure:null, snapshotRead:emptySnapshotRead, eventRead:emptyEventRead, usageVerification:emptyUsageVerification,
};

interface ObservationAttempt {
  controller: AbortController; threadId: string; runId: string | null;
  replay: Map<number, RunEvent>; metadata: boolean; failed: boolean; isGet: boolean;
  hasFinished:boolean;
}

/** 应用级会话所有者。Workspace 仅订阅；地址租约撤销只结束读取，不删除事实和输入。 */
export class ConversationStore {
  private state: ConversationState = {
    threads: [], activeId: "", views: {}, drafts: {}, listing: false,
    listLoaded: false, loadingMore: false, nextCursor: null, pageError: null,
    creating: false, listError: null, notice: null, storageIssue:null, submissions:{}, approvalBackups:[], temporaryTitles:{}, titleStorageIssue:null,
  };
  private listeners = new Set<() => void>();
  private session: BackendSession | null = null;
  private visible = true;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private entryQueued = false;
  private entryList = false;
  private selection: AbortController | null = null;
  private listRequest: AbortController | null = null;
  private moreRequest: AbortController | null = null;
  private observing: ObservationAttempt | null = null;
  private recovery: ObservationRecovery | null = null;
  private retryDeadlines = new Map<string, number>();
  private snapshotDeadlines = new Map<string, number>();
  private queryRequest: AbortController | null = null;
  private summaryRequest: AbortController | null = null;
  private summaryTarget: {threadId:string; runId:string | null} | null = null;
  private statusVersions = new Map<string, number>();
  private creation: object | null = null;
  private intent = 0;
  private projections = new Map<string, RunProjection>();
  private inputs: MessageDrafts;
  private approvals:ApprovalDrafts;
  private titles:ConversationTitles;
  private writeRequest:AbortController | null = null;
  private savedRequests = new Map<string, AbortController>();
  private savedReads = new Map<string, 'reading' | 'ready' | 'error'>();
  private savedDeadlines = new Map<string, number>();
  private snapshotRequest: {session:BackendSession; threadId:string; runId:string; controller:AbortController;
    task:Promise<void>; hasStarted:boolean; shouldReadAgain:boolean; isAutomatic:boolean; executionStage:number} | null = null;
  private isDetailsOpen=false;
  private isEventReadPaused=true;
  private usageVerification=new UsageVerificationCoordinator(
    ()=>this.refreshUsageSnapshot(),verification=>{
      const threadId=this.state.activeId;
      if(threadId && this.state.views[threadId]) this.updateView(threadId,{usageVerification:verification});
    });
  private eventHistory=new RunEventHistoryReader((target,events)=>{
    const projection=this.projection(target.threadId);
    projection.mergeEvents(target.runId,events);
    this.titles.observeMessages(target.threadId, projection.snapshot().messages);
    const previousApproval=this.state.views[target.threadId]?.approval;
    const approval=projection.approval(projection.snapshot().events[target.runId] ?? [],false);
    this.updateView(target.threadId,{...projection.snapshot(),approval:approval
      ? {...approval,verified:Boolean(previousApproval?.verified && sameFact(previousApproval.request,approval.request))} : null});
  },(target,eventRead)=>{
    if(this.state.activeId===target.threadId && this.state.views[target.threadId]?.run?.run_id===target.runId)
      this.updateView(target.threadId,{eventRead});
  });

  constructor(options: {storage?: DraftStorage | null} = {}) {
    this.inputs = new MessageDrafts(options.storage);
    this.approvals = new ApprovalDrafts(options.storage);
    this.titles = new ConversationTitles(options.storage);
    this.state = {...this.state, activeId:this.inputs.selected, ...this.inputState()};
  }

  private inputState() {
    return {drafts:Object.fromEntries(Object.entries(this.inputs.drafts).map(([id, draft]) => [id, draft.text])),
      storageIssue:this.approvals.storageIssue ?? this.inputs.storageIssue, titleStorageIssue:this.titles.storageIssue,
      submissions:this.inputs.submissions, approvalBackups:this.approvals.records, temporaryTitles:this.titles.getSnapshot()};
  }

  private publishInputs() { this.publishState(this.inputState()); }

  private projection(threadId: string) {
    let projection = this.projections.get(threadId);
    if (!projection) { projection = new RunProjection(); this.projections.set(threadId, projection); }
    return projection;
  }

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publishState(stateUpdate: Partial<ConversationState>) {
    this.state = { ...this.state, ...stateUpdate };
    this.listeners.forEach(listener => listener());
  }

  private updateView(threadId: string, viewUpdate: Partial<ConversationView>) {
    const previous = this.state.views[threadId];
    if (viewUpdate.run && previous?.run?.run_id !== viewUpdate.run.run_id) {
      this.snapshotRequest?.controller.abort();
      this.snapshotRequest = null;
      viewUpdate = {snapshotRead:emptySnapshotRead,eventRead:emptyEventRead, savedContent:'idle', savedContentFailure:null, write:null, approvalDraft:null, acceptedApproval:null, ...viewUpdate};
      const runId = viewUpdate.run!.run_id;
      queueMicrotask(() => {if(this.state.activeId === threadId && this.state.views[threadId]?.run?.run_id === runId) void this.refreshRunDetails();});
    }
    const run = viewUpdate.run ?? previous?.run;
    if (viewUpdate.approval && run) {
      const identity = createApprovalIdentity(run.run_id, viewUpdate.approval.request.payload);
      if (identity !== previous?.approvalDraft?.identity) {
        viewUpdate = {...viewUpdate, approvalDraft:this.approvals.restoreDraft(threadId,run.run_id,viewUpdate.approval.request.payload)};
      }
    }
    const currentDraft=Object.hasOwn(viewUpdate,'approvalDraft')?viewUpdate.approvalDraft:previous?.approvalDraft;
    const backup=currentDraft?this.approvals.findRecord(threadId,currentDraft.identity):null;
    if(backup?.submission&&run?.run_id===backup.draft.runId){
      if(backup.submission.status==='accepted')viewUpdate={...viewUpdate,acceptedApproval:backup.draft.identity};
      else if(!Object.hasOwn(viewUpdate,'write')&&(!previous?.write||previous.write.kind==='approval'&&previous.write.identity!==backup.draft.identity)){
        viewUpdate={...viewUpdate,write:{runId:run.run_id,kind:'approval',phase:'unknown',verified:false,verifying:false,
          identity:backup.draft.identity,submissionId:backup.submission.id,retryAt:backup.submission.retryAt,failure:backup.submission.failure}};
      }
    }else if(currentDraft&&previous?.write?.kind==='approval'&&previous.write.identity!==currentDraft.identity&&!Object.hasOwn(viewUpdate,'write')){
      viewUpdate={...viewUpdate,write:null};
    }
    const draft = Object.hasOwn(viewUpdate, 'approvalDraft') ? viewUpdate.approvalDraft : previous?.approvalDraft;
    const events=viewUpdate.events??previous?.events??{};
    const processedIdentities=new Set(collectApprovalRecords(events).filter(record=>record.resolution).map(record=>record.identity));
    const hasResolution=Boolean(draft&&processedIdentities.has(draft.identity));
    const statuses={...(viewUpdate.runStatuses??previous?.runStatuses),...(run?{[run.run_id]:run.status}:{})};
    for(const record of this.approvals.records.filter(record=>record.threadId===threadId)){
      if(['completed','cancelled','error'].includes(statuses[record.draft.runId])
        ||processedIdentities.has(record.draft.identity))this.approvals.removeDraft(record.draft.identity);
    }
    if (run && terminalRun(run) || hasResolution) {
      viewUpdate = {...viewUpdate, approvalDraft:null, ...(run && terminalRun(run) || previous?.write?.kind === 'approval' ? {write:null} : {})};
    }
    if(viewUpdate.approvalDraft)this.approvals.saveDraft(threadId,viewUpdate.approvalDraft);
    this.publishState({ ...this.inputState(), views: { ...this.state.views,
      [threadId]: { ...(this.state.views[threadId] ?? emptyConversation), ...viewUpdate },
    } });
    this.syncEventTarget();
    this.syncUsageTarget();
    const view = this.state.views[threadId];
    if (view.verified && view.run && terminalRun(view.run)) {
      queueMicrotask(() => {void this.readSavedContent(threadId, view.run!.run_id);});
    }
  }

  private stopSelection() {
    this.isEventReadPaused=true;
    this.eventHistory.setTarget(null);
    this.usageVerification.setTarget(null);
    const id = this.state.activeId;
    this.writeRequest?.abort();
    this.writeRequest = null;
    const write = this.state.views[id]?.write;
    if(write?.kind==='approval'&&write.phase==='pending'&&write.identity&&write.submissionId){
      this.approvals.markSubmissionUnknown(id,write.identity,write.submissionId,
        {kind:'unknown',message:'审批连接已停止，接受情况待核实；不会撤回服务端决策或自动再次提交。',recoverable:false},write.retryAt);
    }
    if (write) this.updateView(id, {write:{...write, phase:'unknown', verified:false, verifying:false}});
    for (const [key, controller] of this.savedRequests) {
      controller.abort(); this.savedReads.delete(key);
    }
    this.savedRequests.clear();
    this.inputs.markSubmissionUnknown(id, '发送连接已停止，接受情况待核实；不会自动重发。');
    this.publishInputs();
    this.selection?.abort();
    this.selection = null;
    this.observing = null;
    this.recovery = null;
    this.queryRequest?.abort();
    this.queryRequest = null;
    this.summaryRequest?.abort();
    this.summaryRequest = null;
    this.summaryTarget = null;
    this.snapshotRequest?.controller.abort();
    this.snapshotRequest = null;
    if (this.state.views[id]?.snapshotRead.phase === 'reading') this.updateView(id, {snapshotRead:emptySnapshotRead});
    if (id && this.state.views[id]) this.updateView(id, { verified:false, sending: false, observation:'paused', retry:null, querying:false,
      history:this.state.views[id].history === 'loading' ? 'idle' : this.state.views[id].history,
      approval:this.state.views[id].approval ? {...this.state.views[id].approval!, verified:false} : null });
  }

  private revoke = () => {
    this.stopPolling();
    this.stopSelection();
    this.listRequest?.abort();
    this.listRequest = null;
    this.moreRequest?.abort();
    this.moreRequest = null;
    this.creation = null;
    this.publishState({
      listing: false, loadingMore: false, creating: false,
      views: Object.fromEntries(Object.entries(this.state.views).map(([id, view]) => [id, {
        ...view, verified: false, sending: false,
        history: view.history === "loading" ? "idle" : view.history,
      }])),
      ...(this.state.creating ? { notice: "创建结果待确认；后端恢复后请在会话列表核对。" } : {}),
    });
  };

  setSession(session: BackendSession | null) {
    if (this.session === session) return;
    this.session?.signal.removeEventListener("abort", this.revoke);
    this.revoke();
    this.session = session;
    if (!session || session.signal.aborted) return;
    session.signal.addEventListener("abort", this.revoke, { once: true });
    if (!this.visible) return;
    this.enter(true);
  }

  setVisible(visible: boolean) {
    if (this.visible === visible) return;
    this.visible = visible;
    if (!visible) this.revoke();
    else this.enter(true);
  }

  /** 同一轮显示、选择和租约就绪只定位一次，微任务读取最新目标。 */
  private enter(refreshList = false) {
    // 排队不等于已经核实：调用者立即看到读取中，不能沿用上次的发送资格。
    if (this.visible && this.session && !this.session.signal.aborted && this.state.activeId) {
      this.updateView(this.state.activeId, {history:'loading', verified:false});
    }
    this.entryList ||= refreshList;
    if (this.entryQueued) return;
    this.entryQueued = true;
    queueMicrotask(() => {
      this.entryQueued = false;
      const list = this.entryList;
      this.entryList = false;
      if (!this.visible || !this.session || this.session.signal.aborted) return;
      if (list) void this.loadThreads(true);
      if (this.state.activeId) void this.openSelected();
    });
  }

  private live(session: BackendSession, controller: AbortController) {
    return this.visible && this.session === session && !session.signal.aborted && !controller.signal.aborted;
  }

  private stopPolling() {
    if (this.pollTimer !== null) clearTimeout(this.pollTimer);
    this.pollTimer = null;
  }

  private schedulePoll() {
    this.stopPolling();
    if (!this.visible || !this.session || this.session.signal.aborted || this.listRequest) return;
    const delay = Math.max(5000, (this.state.listError?.retryAt ?? 0) - Date.now(),
      (this.state.pageError?.retryAt ?? 0) - Date.now());
    this.pollTimer = setTimeout(() => {this.pollTimer = null; void this.loadThreads(false);}, Math.min(delay, 2_147_483_647));
  }

  private mergeThreads(items: Thread[], versions: Map<string, number>) {
    const merged = new Map(this.state.threads.map(thread => [thread.id, thread]));
    for (const item of items) {
      const previous = merged.get(item.id);
      if (previous && previous.updated_at && item.updated_at < previous.updated_at) continue;
      const protectedStatus = previous && (this.observing?.metadata && this.observing.threadId === item.id
        || versions.get(item.id) !== this.statusVersions.get(item.id)
        || previous.run_id === item.run_id && previous.run_status !== null
          && ['completed','cancelled','error'].includes(previous.run_status) && previous.run_status !== item.run_status);
      merged.set(item.id, protectedStatus ? { ...item,
        run_id: previous.run_id, run_status: previous.run_status } : item);
    }
    this.publishState({ threads: [...merged.values()].sort((a, b) =>
      a.updated_at === b.updated_at ? (a.id === b.id ? 0 : a.id > b.id ? -1 : 1)
        : a.updated_at > b.updated_at ? -1 : 1) });
  }

  private syncRun(threadId: string, run: Run) {
    this.statusVersions.set(threadId, (this.statusVersions.get(threadId) ?? 0) + 1);
    this.publishState({ threads: this.state.threads.map(thread => thread.id === threadId
      ? { ...thread, run_id: run.run_id, run_status: run.status } : thread) });
  }

  private async loadThreads(chooseInitial = true, reset = false) {
    const session = this.session;
    if (!this.visible || !session || session.signal.aborted) return;
    if (Date.now() < (this.state.listError?.retryAt ?? 0)
      || Date.now() < (this.state.pageError?.retryAt ?? 0)) {this.schedulePoll(); return;}
    if (this.listRequest && !reset) return;
    this.listRequest?.abort();
    this.stopPolling();
    if (reset) {
      this.moreRequest?.abort();
      this.moreRequest = null;
      this.publishState({ loadingMore: false });
    }
    const controller = this.listRequest = new AbortController();
    const intent = this.intent;
    const versions = new Map(this.statusVersions);
    this.publishState({ listing: true, listError: null });
    try {
      const page = await session.threads(THREAD_PAGE_SIZE, controller.signal);
      if (!this.live(session, controller)) return;
      const selected = page.data.find(item => item.id === this.state.activeId);
      const previous = this.state.threads.find(item => item.id === selected?.id);
      if (selected && (!previous?.updated_at || selected.updated_at >= previous.updated_at)
        && versions.get(selected.id) === this.statusVersions.get(selected.id)) {
        void this.reconcileSummary(session, selected);
      }
      this.mergeThreads(page.data, versions);
      if (reset || !this.state.listLoaded) this.publishState({
        nextCursor: page.data.length < THREAD_PAGE_SIZE ? null : page.next_cursor, pageError: null,
      });
      this.publishState({ listLoaded: true });
      if (chooseInitial && !this.state.activeId && intent === this.intent && page.data.length) this.select(page.data[0].id);
    } catch (error) {
      if (this.live(session, controller)) this.publishState({ listError: listFailure(error) });
    } finally {
      if (this.live(session, controller)) {
        this.listRequest = null;
        this.publishState({ listing: false });
        this.schedulePoll();
      }
    }
  }

  refreshThreads = () => this.loadThreads(false);
  reloadThreads = () => this.loadThreads(true, true);

  loadMore = async (retry = false) => {
    const session = this.session;
    const cursor = this.state.nextCursor;
    if (!this.visible || !session || session.signal.aborted || !cursor || this.moreRequest || this.listRequest
        || this.state.listError || this.state.pageError?.invalidCursor
        || (this.state.pageError && (!retry || Date.now() < this.state.pageError.retryAt))) return;
    const controller = this.moreRequest = new AbortController();
    const versions = new Map(this.statusVersions);
    this.publishState({ loadingMore: true, pageError: null });
    try {
      const page = await session.threads(THREAD_PAGE_SIZE, controller.signal, cursor);
      if (!this.live(session, controller)) return;
      if (page.data.length === THREAD_PAGE_SIZE && page.next_cursor === cursor) throw new Error("分页游标未前进，请重新加载会话列表");
      this.mergeThreads(page.data, versions);
      this.publishState({ nextCursor: page.data.length < THREAD_PAGE_SIZE ? null : page.next_cursor });
    } catch (error) {
      if (this.live(session, controller)) this.publishState({ pageError: listFailure(error) });
    } finally {
      if (this.live(session, controller)) {
        this.moreRequest = null;
        this.publishState({ loadingMore: false });
      }
    }
  };

  select(threadId: string) {
    if (!threadId || !this.state.threads.some(thread => thread.id === threadId)) return;
    this.intent++;
    this.stopSelection();
    this.publishState({ activeId: threadId });
    this.inputs.select(threadId);
    this.publishInputs();
    this.enter();
  }

  updateDraft(value: string) {
    const id = this.state.activeId;
    if (!id) return;
    this.inputs.update(id, value);
    this.publishInputs();
  }

  async create() {
    const session = this.session;
    if (!this.visible || !session || session.signal.aborted || this.creation || this.state.listing) return;
    const intent = ++this.intent;
    const creation = this.creation = {};
    this.publishState({ creating: true, notice: null });
    try {
      const { thread_id } = await session.createThread();
      if (this.session !== session || session.signal.aborted) return;
      if (!this.state.threads.some(thread => thread.id === thread_id)) {
        // 创建响应不提供时间，不制造本地时间冒充服务端事实。
        this.publishState({ threads: [{ id: thread_id, user_id: null, title: null, created_at: "", updated_at: "", run_id: null, run_status: null }, ...this.state.threads] });
      }
      if (intent === this.intent) this.select(thread_id);
      else this.publishState({ notice: `会话已创建（${thread_id}），已保留在列表中，继续当前会话。` });
      await this.loadThreads(false);
      return thread_id;
    } catch (error) {
      if (this.session !== session || session.signal.aborted) return;
      this.publishState({ notice: `创建结果待确认：${String(error)}。请核对会话列表；不会自动再次创建。` });
      await this.loadThreads(false);
    } finally {
      if (this.creation === creation) {
        this.creation = null;
        this.publishState({ creating: false });
      }
    }
  }

  copyDraftToNewConversation = async () => {
    const sourceId = this.state.activeId;
    const text = this.inputs.get(sourceId).text || this.inputs.submissions[sourceId]?.text || '';
    if (!sourceId || !text) return;
    const targetId = await this.create();
    if (!targetId) return;
    const targetText = this.inputs.get(targetId).text;
    this.inputs.update(targetId, targetText ? `${targetText}\n\n${text}` : text);
    this.publishInputs();
    this.publishState({notice:'文字已复制到新会话，请核对后手动发送；原会话文字仍保留。'});
  };

  private canStartRun() {
    const view = this.state.views[this.state.activeId];
    return Boolean(this.visible && this.session && !this.session.signal.aborted && view?.history === "ready"
      && view.verified && !view.sending && !view.write && !this.state.creating
      && (!view.run || ["completed", "cancelled", "error"].includes(view.run.status)));
  }

  canSend() {
    const submission = this.inputs.submissions[this.state.activeId];
    return this.canStartRun() && (!submission || submission.status === 'accepted');
  }

  canSendAsNewTask() {
    const record = this.inputs.submissions[this.state.activeId];
    return this.canStartRun() && record?.status === 'unknown' && Date.now() >= record.retryAt;
  }

  sendAsNewTask(submissionId: string): boolean {
    const record = this.inputs.submissions[this.state.activeId];
    if (record?.id !== submissionId || !this.canSendAsNewTask()) return false;
    return this.startSend(record.text, record.version);
  }

  confirmSend(seq: number, submissionId: string): boolean {
    const threadId = this.state.activeId;
    const record = this.inputs.submissions[threadId];
    const view = this.state.views[threadId];
    if (!record || record.id !== submissionId || record.status !== 'unknown' || view?.history !== 'ready'
      || !view.verified || !view.messages.some(message => message.seq === seq
        && message.content.type === 'human' && !message.preview)) return false;
    this.inputs.confirm(threadId);
    this.publishInputs();
    return true;
  }

  send(message: string): boolean {
    const session = this.session;
    if (!session || !this.canSend() || !message.trim()) return false;
    return this.startSend(message);
  }

  private startSend(message: string, version?: number): boolean {
    const session = this.session!;
    const threadId = this.state.activeId;
    if (!message.trim()) return false;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    const submission = this.inputs.begin(threadId, message, this.state.views[threadId].run?.run_id ?? null, version);
    this.publishInputs();
    this.updateView(threadId, { sending: true, error: null, sendFailure:null });
    const receiveFrame = this.createFrameReceiver(session, controller, threadId);
    let normal = false;
    let failure:unknown;
    void session.send(threadId, message, frame => {
      if (!this.live(session, controller) || this.state.activeId !== threadId) return;
      if (frame.event === 'metadata' && frame.data.run_id === submission.previousRunId) {
        throw new RunProtocolError('本次发送返回旧运行身份，接受情况待核实', frame.data);
      }
      receiveFrame(frame);
      if (!this.live(session, controller) || this.state.activeId !== threadId) return;
      if (frame.event === 'metadata') {
        this.inputs.accept(threadId, submission.id, frame.data.run_id);
        this.publishInputs();
        // 仅本次 POST 的有效接受允许恢复阅读跟随；GET metadata 不发此信号。
        this.updateView(threadId, {sending:false, acceptedSendId:submission.id});
      }
    }, controller.signal)
      .then(() => { if (this.live(session, controller)) normal = this.finishObservation(controller); })
      .catch(error => {
        failure = error;
        if (this.live(session, controller)) {
          if (error instanceof BackendRequestError && [400,409,422].includes(error.status)) this.inputs.rejected(threadId);
          else this.inputs.markSubmissionUnknown(threadId, String(error), listFailure(error).retryAt, observationFailure(error));
          this.publishInputs();
          this.updateView(threadId, {verified:false, observation:'failed', sendFailure:observationFailure(error),
            ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
          this.publishState({notice: `发送请求异常：${String(error)}。正在读取已保存的结果；不会自动重发。`});
        }
      }).finally(async () => {
        if (!this.live(session, controller)) return;
        this.inputs.markSubmissionUnknown(threadId, '发送流在确认接受前结束，请核对已保存消息。');
        this.publishInputs();
        this.updateView(threadId, { sending: false });
        if (this.observing?.controller === controller) this.observing = null;
        const submissionRecord = this.inputs.submissions[threadId];
        if (submissionRecord?.id === submission.id && submissionRecord.status === 'accepted' && submissionRecord.runId) {
          if (!normal) {
            const recoveryTask = this.observeRun(session, controller, threadId, submissionRecord.runId,
              failure ?? new UnexpectedObservationEnd('已接受发送，观察连接意外结束。'));
            // 首 metadata 后即断流也补读真实正文，不把已接受发送显示为空会话。
            // 正文 JSON 与同 Run SSE 分工读取；观察仍只有一个恢复任务。
            void this.readCommittedHistory(session, controller, threadId);
            normal = await recoveryTask;
          }
          if (normal && this.live(session, controller) && this.projection(threadId).run?.status === 'interrupted') {
            // POST 的 required 先只读；自动 GET 重建并验证 checkpoint 后才开放审批。
            normal = await this.observeRun(session, controller, threadId, submissionRecord.runId);
          }
          if (normal && this.live(session, controller)) {
            await this.readCommittedHistory(session, controller, threadId);
            void this.loadThreads(false);
          }
        } else {
          // 接受前结果未知，只 GET 核实；不重发 POST。
          this.reload();
        }
      });
    return true;
  }

  reload = () => {
    this.stopSelection();
    this.enter(true);
  };

  canReconnect():boolean {
    const session = this.session, view = this.state.views[this.state.activeId];
    return Boolean(this.visible && session && !session.signal.aborted && view?.run && view.history === 'ready'
      && !view.sending && !this.writeRequest && !this.recovery && !this.observing && !this.queryRequest);
  }

  reconnect = () => {
    const session = this.session;
    const threadId = this.state.activeId;
    const view = this.state.views[threadId];
    if (!this.canReconnect()) return;
    const runId = view.run!.run_id;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.updateView(threadId, {verified:false, error:null});
    void this.observeRun(session!, controller, threadId, runId).then(async normal => {
      if (normal && this.live(session!, controller)) {
        await this.readCommittedHistory(session!, controller, threadId);
      }
    });
  };

  queryStatus = async () => {
    if (this.state.views[this.state.activeId]?.write?.phase === 'unknown') {
      if (this.state.views[this.state.activeId].write?.kind === 'approval') this.reconnect();
      else await this.verifyCancellation();
      return;
    }
    const session = this.session;
    const threadId = this.state.activeId;
    const view = this.state.views[threadId];
    if (!this.visible || !session || session.signal.aborted || !view?.run || this.queryRequest
      || view.sending || view.history !== 'ready' || this.recovery || this.observing) return;
    const controller = this.queryRequest = new AbortController();
    const runId = view.run.run_id;
    this.updateView(threadId, {querying:true, queryFailure:null});
    try {
      await waitUntil(this.retryDeadlines.get(`${threadId}:${runId}`) ?? 0, AbortSignal.any([controller.signal, session.signal]));
      if (this.live(session, controller)) await this.readSnapshot(session, controller, threadId, runId);
    } catch (error) {
      if (this.live(session, controller)) this.updateView(threadId, {queryFailure:observationFailure(error)});
    } finally {
      if (this.queryRequest === controller) {
        this.queryRequest = null;
        this.updateView(threadId, {querying:false});
      }
    }
  };

  cancelTarget():CancelTarget | null {
    if (!this.canCancel()) return null;
    return {threadId:this.state.activeId, runId:this.state.views[this.state.activeId].run!.run_id,
      startupId:this.session!.startupId, baseUrl:this.session!.baseUrl};
  }

  canCancel(target?:CancelTarget):boolean {
    const id = this.state.activeId, session = this.session, view = this.state.views[id];
    const write = view?.write;
    return Boolean(this.visible && session && !session.signal.aborted && view?.run && view.verified
      && ['running','interrupted'].includes(view.run.status) && !view.sending && !this.state.creating
      && (!write || write.phase === 'unknown' && write.verified
        && !write.verifying && Date.now() >= write.retryAt)
      && (!target || target.threadId === id && target.runId === view.run.run_id
        && target.startupId === session.startupId && target.baseUrl === session.baseUrl));
  }

  canEditApproval(identity:string):boolean {
    const view = this.state.views[this.state.activeId], session = this.session;
    const draft = view?.approvalDraft, write = view?.write;
    return Boolean(this.visible && session && !session.signal.aborted && view?.verified
      && view.run?.status === 'interrupted' && view.approval?.verified && draft?.identity === identity
      && draft.runId === view.run.run_id && sameFact(draft.request, view.approval.request.payload)
      && view.acceptedApproval !== identity && !view.sending && !this.state.creating
      && !parseApproval(draft.request).issue
      && (!write || write.kind === 'approval' && write.phase === 'unknown' && write.verified
        && !write.verifying && Date.now() >= write.retryAt));
  }

  canSubmitApproval(identity:string):boolean {
    return this.canEditApproval(identity) && Boolean(buildApprovalResponses(this.state.views[this.state.activeId].approvalDraft!));
  }

  chooseApproval(identity:string, interruptId:string, index:number, choiceUpdate:Partial<ApprovalChoice>):boolean {
    if (!this.canEditApproval(identity)) return false;
    const threadId = this.state.activeId;
    const draft = this.state.views[threadId].approvalDraft!;
    const nextDraft = updateApprovalChoice(draft, interruptId, index, choiceUpdate);
    if (nextDraft === draft) return false;
    this.updateView(threadId, {approvalDraft:nextDraft});
    return true;
  }

  submitApproval(identity:string):boolean {
    if (!this.canSubmitApproval(identity)) return false;
    const session = this.session!, threadId = this.state.activeId;
    const draft = this.state.views[threadId].approvalDraft!, runId = draft.runId;
    const responses = buildApprovalResponses(draft)!;
    this.stopSelection();
    const submission=this.approvals.beginSubmission(threadId,draft,responses);
    const controller = this.selection = this.writeRequest = new AbortController();
    this.updateView(threadId, {write:{runId, kind:'approval', phase:'pending', verified:false, verifying:false, retryAt:0, failure:null,
      identity,submissionId:submission.id}});
    const receiveFrame = this.createFrameReceiver(session, controller, threadId, runId, false);
    let isAccepted = false, endedNormally = false, streamFailure:unknown;
    void session.submitApproval(threadId, runId, responses, frame=> {
      if (!this.live(session, controller) || this.state.activeId !== threadId) return;
      receiveFrame(frame);
      if (!this.live(session, controller) || this.state.views[threadId].run?.run_id !== runId) return;
      if (frame.event === 'metadata' && !isAccepted) {
        isAccepted = true;
        this.approvals.acceptSubmission(threadId,identity,submission.id);
        if (this.writeRequest === controller) this.writeRequest = null;
        // 仅本次 POST 的有效 metadata 确认接收；历史决策仍等待 resolved 事实。
        this.updateView(threadId, {write:null, acceptedApproval:identity});
      }
    }, controller.signal).then(()=> {
      if (this.live(session, controller)) endedNormally = this.finishObservation(controller);
    }).catch(error=> {
      streamFailure = error;
      if (!this.live(session, controller)) return;
      const failure = observationFailure(error);
      if (!isAccepted) {
        const retryAt = retryAfterTime(failure.retryAfter ?? null);
        const key = `${threadId}:${runId}`;
        this.approvals.markSubmissionUnknown(threadId,identity,submission.id,failure,retryAt);
        this.retryDeadlines.set(key, Math.max(this.retryDeadlines.get(key) ?? 0, retryAt));
        this.updateView(threadId, {verified:false, write:{runId, kind:'approval', phase:'unknown', verified:false,
          verifying:false, retryAt, failure,identity,submissionId:submission.id}});
      }
      this.updateView(threadId, {observation:'failed', ...(error instanceof RunProtocolError
        ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
    }).finally(async ()=> {
      if (this.writeRequest === controller) this.writeRequest = null;
      if (!this.live(session, controller)) return;
      if (this.observing?.controller === controller) this.observing = null;
      if (!isAccepted && this.state.views[threadId].write?.phase === 'pending') {
        const failure=observationFailure(new UnexpectedObservationEnd('审批接收确认前连接结束'));
        this.approvals.markSubmissionUnknown(threadId,identity,submission.id,failure);
        this.updateView(threadId, {verified:false, write:{runId, kind:'approval', phase:'unknown', verified:false,
          verifying:false, retryAt:0, failure,identity,submissionId:submission.id}});
      }
      // 未确认的 POST 先 GET 核实；已接收的断流只恢复观察，绝不再 POST。
      if (!endedNormally || this.projection(threadId).run?.status === 'interrupted') {
        const write = this.state.views[threadId].write;
        if (write?.phase === 'unknown') this.updateView(threadId, {write:{...write, verifying:true}});
        endedNormally = await this.observeRun(session, controller, threadId, runId,
          isAccepted && !endedNormally ? streamFailure ?? new UnexpectedObservationEnd('审批已接收，观察连接意外结束') : undefined);
      }
      if (endedNormally && this.live(session, controller)) {
        await this.readCommittedHistory(session, controller, threadId);
      }
      const writeState = this.state.views[threadId].write;
      if (this.live(session, controller) && writeState?.kind === 'approval' && writeState.verifying) {
        this.updateView(threadId, {write:{...writeState, verifying:false}});
      }
    });
    return true;
  }

  async cancel(target:CancelTarget):Promise<boolean> {
    if (!this.canCancel(target)) return false;
    const session = this.session!, {threadId, runId} = target;
    const controller = this.writeRequest = new AbortController();
    const version = this.projection(threadId).snapshotVersion(runId);
    this.updateView(threadId, {write:{runId, kind:'cancel', phase:'pending', verified:false, verifying:false, retryAt:0, failure:null}});
    try {
      const snapshot = await session.cancel(threadId, runId, controller.signal);
      if (!this.live(session, controller) || this.state.activeId !== threadId
        || this.state.views[threadId].run?.run_id !== runId) return false;
      const hasStaleUsage = this.applyWriteSnapshot(threadId, snapshot,version);
      this.notifyEventBoundary(threadId,runId);
      if (hasStaleUsage || this.snapshotRequest?.hasStarted) void this.refreshRunDetails(true);
      return true;
    } catch (error) {
      if (this.live(session, controller) && this.state.views[threadId].run?.run_id === runId) {
        const failure = observationFailure(error);
        this.updateView(threadId, {verified:false, write:{runId, kind:'cancel', phase:'unknown', verified:false, verifying:false,
          retryAt:retryAfterTime(failure.retryAfter ?? null), failure},
          ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
      }
    } finally {
      if (this.writeRequest === controller) this.writeRequest = null;
    }
    if (this.live(session, controller)) await this.verifyCancellation();
    return false;
  }

  private applyWriteSnapshot(threadId:string, snapshot:Run, version?:ReturnType<RunProjection['snapshotVersion']>) {
    const projection = this.projection(threadId);
    const hasStaleUsage = projection.applySnapshot(snapshot,version,{isWrite:true});
    this.syncRun(threadId, projection.run!);
    const write = this.state.views[threadId].write;
    this.updateView(threadId, {...projection.snapshot(), verified:true,
      write:terminalRun(projection.run!) ? null : write ? {...write, phase:'unknown', verified:true, verifying:false} : null,
      approval:terminalRun(projection.run!) ? null : this.state.views[threadId].approval});
    if(terminalRun(projection.run!)) this.notifyEventBoundary(threadId,snapshot.run_id);
    return hasStaleUsage;
  }

  private async verifyCancellation() {
    const threadId = this.state.activeId, session = this.session, view = this.state.views[threadId];
    const write = view?.write;
    if (!this.visible || !session || session.signal.aborted || !write || write.phase !== 'unknown'
      || write.verifying || this.writeRequest || view.run?.run_id !== write.runId) return;
    const controller = this.writeRequest = new AbortController();
    this.updateView(threadId, {write:{...write, verifying:true}});
    try {
      await this.readSnapshot(session,controller,threadId,write.runId);
      const remaining = this.state.views[threadId].write;
      if (this.live(session,controller) && remaining && this.state.views[threadId].snapshotRead.failure) {
        this.updateView(threadId,{write:{...remaining,failure:this.state.views[threadId].snapshotRead.failure,
          retryAt:Math.max(remaining.retryAt,this.retryDeadlines.get(`${threadId}:${write.runId}`) ?? 0)}});
      }
    } finally {
      if (this.writeRequest === controller) {
        this.writeRequest = null;
        const remaining = this.state.views[threadId].write;
        if (remaining) this.updateView(threadId, {write:{...remaining, verifying:false}});
      }
    }
  }

  readSavedContent = async (threadId=this.state.activeId, runId=this.state.views[threadId]?.run?.run_id, manual=false) => {
    const session = this.session;
    if (!runId || !this.visible || !session || session.signal.aborted || this.state.activeId !== threadId
      || this.state.views[threadId]?.run?.run_id !== runId || !terminalRun(this.state.views[threadId].run!)) return;
    const key = `${threadId}:${runId}`;
    if (this.savedRequests.has(key) || this.savedReads.has(key) && !manual) return;
    const controller = new AbortController();
    this.savedRequests.set(key, controller); this.savedReads.set(key, 'reading');
    this.updateView(threadId, {savedContent:'reading', savedContentFailure:null});
    try {
      await waitUntil(this.savedDeadlines.get(key) ?? 0, AbortSignal.any([controller.signal, session.signal]));
      const records = await session.runMessages(threadId, runId, controller.signal);
      if (!this.live(session, controller) || this.state.views[threadId].run?.run_id !== runId) return;
      const projection = this.projection(threadId);
      projection.mergeMessages(records);
      this.titles.observeMessages(threadId, projection.snapshot().messages);
      const unconfirmed = projection.snapshot().messages.some(message => message.run_id === runId && message.preview);
      this.updateView(threadId, projection.snapshot());
      if (unconfirmed) throw new RunProtocolError('已保存消息尚未覆盖全部预览，请手动再次读取', records);
      this.savedReads.set(key, 'ready');
      this.updateView(threadId, {...projection.snapshot(), savedContent:'ready'});
    } catch (error) {
      if (this.live(session, controller)) {
        this.savedReads.set(key, 'error');
        this.savedDeadlines.set(key, retryAfterTime(observationFailure(error).retryAfter ?? null));
        this.updateView(threadId, {savedContent:'error', savedContentFailure:observationFailure(error)});
      }
    } finally {
      if (this.savedRequests.get(key) === controller) this.savedRequests.delete(key);
    }
  };

  retrySavedContent = () => this.readSavedContent(this.state.activeId, this.state.views[this.state.activeId]?.run?.run_id, true);

  private async readCommittedHistory(session:BackendSession, controller:AbortController, threadId:string) {
    try {
      const messages = await session.messages(threadId, controller.signal);
      if (!this.live(session, controller)) return;
      const projection = this.projection(threadId);
      projection.mergeMessages(messages);
      this.titles.reconcileHistory(threadId, messages);
      this.updateView(threadId, {...projection.snapshot(), history:'ready'});
    } catch (error) {
      if (this.live(session, controller)) this.updateView(threadId, {error:`读取已保存消息失败：${String(error)}`,
        ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
    }
  }

  private async openSelected() {
    const session = this.session;
    const threadId = this.state.activeId;
    if (!this.visible || !session || session.signal.aborted || !threadId) return;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.updateView(threadId, { history: "loading", verified: false, error: null, missing:false });
    let historyRead = false;
    try {
      await waitUntil(this.inputs.submissions[threadId]?.retryAt ?? 0, AbortSignal.any([controller.signal, session.signal]));
      const messages = await session.messages(threadId, controller.signal);
      if (!this.live(session, controller)) return;
      historyRead = true;
      const projection = this.projection(threadId);
      projection.mergeHistory(messages);
      this.titles.reconcileHistory(threadId, messages);
      const submissionRecord = this.inputs.submissions[threadId];
      // 接受身份是恢复线索；历史可能尚未包含该 Run，必须重新 GET 核实。
      if (submissionRecord?.status === 'accepted' && submissionRecord.runId
        && (!projection.run || projection.run.run_id === submissionRecord.previousRunId)) {
        const snapshot = await session.runSnapshot(threadId, submissionRecord.runId, controller.signal);
        if (!this.live(session, controller)) return;
        projection.metadata(snapshot);
      }
      await this.restoreSelectedRun(session, controller, threadId);
    } catch (error) {
      if (this.live(session, controller)) this.updateView(threadId, {
        history: this.state.views[threadId].history === "loading" ? "error" : "ready",
        verified: false, observation:'failed', error: historyRead && error instanceof BackendRequestError && error.status === 404
          ? `运行不可读取：${String(error)}` : `读取会话失败：${String(error)}`,
        missing:!historyRead && error instanceof BackendRequestError && error.status === 404,
        ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {}),
      });
    }
  }

  private async restoreSelectedRun(session:BackendSession, controller:AbortController, threadId:string) {
    this.isEventReadPaused=false;
    const projection = this.projection(threadId);
    const run = projection.run;
    this.updateView(threadId, {...projection.snapshot(), history:'ready', verified:!run});
    if (!run) {this.updateView(threadId, {observation:'idle', retry:null, observationFailure:null}); return;}
    void this.readSnapshot(session, controller, threadId, run.run_id);
    const retryAt=Math.max(0,...this.approvals.records.filter(record=>record.threadId===threadId&&record.draft.runId===run.run_id)
      .map(record=>record.submission?.retryAt??0));
    this.retryDeadlines.set(`${threadId}:${run.run_id}`,Math.max(this.retryDeadlines.get(`${threadId}:${run.run_id}`)??0,retryAt));
    if (run.status === 'running' || run.status === 'interrupted') {
      await this.observeRun(session, controller, threadId, run.run_id);
    } else {
      // 终态无需 SSE；完成本轮读取后不能沿用隐藏时的主动暂停状态。
      this.updateView(threadId, {observation:'idle', retry:null, observationFailure:null});
      await this.readSnapshot(session, controller, threadId, run.run_id);
      if (this.live(session, controller) && this.state.views[threadId].verified) {
        this.updateView(threadId, {observation:'closed'});
      }
    }
  }

  /** 摘要只提示可能出现新 Run；历史确认身份后才撤销旧观察。 */
  private async reconcileSummary(session:BackendSession, summary:Thread) {
    if (this.summaryTarget?.threadId !== summary.id || this.summaryTarget.runId !== summary.run_id) {
      this.summaryRequest?.abort();
      this.summaryRequest = null;
      this.summaryTarget = {threadId:summary.id, runId:summary.run_id};
    }
    const target = this.summaryTarget;
    const view = this.state.views[summary.id];
    if (!summary.run_id || summary.run_id === view?.run?.run_id || view?.history !== 'ready'
      || view.sending || this.queryRequest || this.summaryRequest || this.entryQueued) return;
    const previousRun = view.run?.run_id;
    const controller = this.summaryRequest = new AbortController();
    try {
      await waitUntil(this.inputs.submissions[summary.id]?.retryAt ?? 0, AbortSignal.any([controller.signal, session.signal]));
      const messages = await session.messages(summary.id, controller.signal);
      if (!this.live(session, controller) || this.state.activeId !== summary.id
        || this.summaryTarget !== target
        || this.state.views[summary.id].run?.run_id !== previousRun) return;
      const projection = this.projection(summary.id);
      projection.mergeMessages(messages);
      this.titles.reconcileHistory(summary.id, messages);
      // 同 Run 的摘要不触发新恢复轮次，也不回退当前 metadata 状态。
      if (messages.at(-1)?.run_id !== previousRun) projection.mergeHistory(messages);
      this.updateView(summary.id, projection.snapshot());
      if (projection.run?.run_id === previousRun) return;
      this.stopSelection();
      const selection = this.selection = new AbortController();
      await this.restoreSelectedRun(session, selection, summary.id);
    } catch (error) {
      if (this.live(session, controller)) this.updateView(summary.id, {error:`核实会话新运行失败：${String(error)}`});
    } finally {
      if (this.summaryRequest === controller) this.summaryRequest = null;
    }
  }

  private async observeRun(session:BackendSession, controller:AbortController, threadId:string, runId:string, initialFailure?:unknown) {
    const key = `${threadId}:${runId}`;
    const recovery = new ObservationRecovery(AbortSignal.any([controller.signal, session.signal]), this.retryDeadlines.get(key) ?? 0, update => {
      if (!this.live(session, controller) || this.recovery !== recovery) return;
      this.retryDeadlines.set(key, recovery.retryAt);
      const write=this.state.views[threadId].write;
      if(write?.kind==='approval'&&write.identity&&write.submissionId&&recovery.retryAt>write.retryAt){
        this.approvals.markSubmissionUnknown(threadId,write.identity,write.submissionId,
          update.observationFailure??write.failure??{kind:'unknown',message:'审批结果仍待核实',recoverable:false},recovery.retryAt);
        this.updateView(threadId,{write:{...write,retryAt:recovery.retryAt}});
      }
      this.updateView(threadId, {...update,
        ...(update.observation === 'retry_wait' || update.observation === 'failed' ? {verified:false,
          error:update.observationFailure?.status === 404 ? `运行不可读取：${update.observationFailure.message}` : update.observationFailure?.message ?? null,
          ...(update.observationFailure?.kind === 'protocol' ? {protocolIssue:{message:update.observationFailure.message, raw:update.observationFailure.raw}} : {}),
          approval:this.state.views[threadId].approval ? {...this.state.views[threadId].approval!, verified:false} : null} : {})});
    });
    this.recovery = recovery;
    try {
      return await recovery.run(async () => {
        try {
          await session.observe(threadId, runId, this.createFrameReceiver(session, controller, threadId, runId), controller.signal);
          return this.live(session, controller) && this.finishObservation(controller);
        } finally {
          if (this.observing?.controller === controller) this.observing = null;
        }
      }, initialFailure);
    } finally {
      if (this.recovery === recovery) this.recovery = null;
    }
  }

  refreshRunDetails = (shouldReadAfterBoundary = false):Promise<void> => {
    const session = this.session, threadId = this.state.activeId;
    const runId = this.state.views[threadId]?.run?.run_id;
    if (!this.visible || !session || session.signal.aborted || !runId) return Promise.resolve();
    return this.readSnapshot(session, new AbortController(), threadId, runId,shouldReadAfterBoundary);
  };

  private syncUsageTarget() {
    const threadId=this.state.activeId, view=this.state.views[threadId], session=this.session;
    const run=view?.run;
    const executionStage=run?this.projection(threadId).snapshotVersion(run.run_id).executionStage:0;
    const request=this.snapshotRequest;
    const hasSettledUsage=run?.usage_pending===false;
    if(request?.isAutomatic && (request.executionStage!==executionStage || hasSettledUsage)) {
      // Stage changes and confirmed settlement stop the automatic GET and its retry task.
      const shouldReadBoundary=hasSettledUsage && request.executionStage===executionStage && request.shouldReadAgain;
      request.controller.abort();this.snapshotRequest=null;
      this.updateView(threadId,{snapshotRead:{...emptySnapshotRead,phase:hasSettledUsage?'ready':'idle'},queryFailure:null});
      if(shouldReadBoundary) queueMicrotask(()=>{
        // A coalesced EOF/cancel supplement remains a normal read after automatic work stops.
        if(this.session===request.session && !request.session.signal.aborted && this.visible && !this.isEventReadPaused
          && this.state.activeId===request.threadId && this.state.views[request.threadId]?.run?.run_id===request.runId
          && this.projection(request.threadId).snapshotVersion(request.runId).executionStage===request.executionStage)
          void this.refreshRunDetails();
      });
    }
    this.usageVerification.setTarget(!this.isEventReadPaused && this.visible && session && !session.signal.aborted && run
      ? {session,threadId,runId:run.run_id,executionStage,
        isEligible:view.verified && (run.status==='interrupted' || terminalRun(run)) && run.usage_pending===true,
        isReading:Boolean(this.snapshotRequest)} : null);
  }
  private refreshUsageSnapshot=():Promise<void>=>{
    const session=this.session,threadId=this.state.activeId,run=this.state.views[threadId]?.run;
    if(!session || !this.visible || session.signal.aborted || !run) return Promise.resolve();
    return this.readSnapshot(session,new AbortController(),threadId,run.run_id,false,true);
  };
  continueUsageVerification=():Promise<void>=>{
    if(!this.usageVerification.continueVerification()) return Promise.resolve();
    return this.refreshRunDetails();
  };

  setDetailsOpen=(isOpen:boolean)=>{
    this.isDetailsOpen=isOpen;
    if(isOpen && this.visible && this.state.views[this.state.activeId]?.history==='ready') this.isEventReadPaused=false;
    this.syncEventTarget();
  };
  private syncEventTarget() {
    const threadId=this.state.activeId, runId=this.state.views[threadId]?.run?.run_id;
    this.eventHistory.setTarget(this.isDetailsOpen && !this.isEventReadPaused && this.visible && this.session && !this.session.signal.aborted && runId
      ? {session:this.session,threadId,runId} : null);
  }
  private notifyEventBoundary(threadId:string,runId:string) {
    if(this.state.activeId!==threadId || this.state.views[threadId]?.run?.run_id!==runId) return;
    const projection=this.projection(threadId);
    this.eventHistory.notifyBoundary(`${runId}:${projection.snapshotVersion(runId).stage}:${projection.run?.status}`);
  }
  refreshDetails=async()=>{await Promise.all([this.refreshRunDetails(),this.eventHistory.refreshHistory()]);};
  refreshRunEvents=()=>this.eventHistory.refreshHistory();

  private readSnapshot(session:BackendSession, caller:AbortController, threadId:string, runId:string,shouldReadAfterBoundary=false,isAutomatic=false):Promise<void> {
    if (!this.live(session,caller) || this.state.activeId !== threadId
      || this.state.views[threadId]?.run?.run_id !== runId) return Promise.resolve();
    const existing = this.snapshotRequest;
    if (existing?.session === session && existing.threadId === threadId && existing.runId === runId) {
      if (shouldReadAfterBoundary && existing.hasStarted) existing.shouldReadAgain = true;
      return existing.task;
    }
    existing?.controller.abort();
    const controller = new AbortController();
    const request = {session, threadId, runId, controller, task:Promise.resolve(),hasStarted:false,shouldReadAgain:false,
      isAutomatic,executionStage:this.projection(threadId).snapshotVersion(runId).executionStage};
    this.snapshotRequest = request;
    this.syncUsageTarget();
    // Defer until ownership is recorded; every trigger joins this same task.
    request.task = Promise.resolve().then(async () => {
      const isCurrent = () => this.snapshotRequest === request && this.live(session,controller)
        && this.state.activeId === threadId && this.state.views[threadId]?.run?.run_id === runId;
      const observationKey = `${threadId}:${runId}`;
      const deadlineKey=createUsageTargetKey({session,threadId,runId,executionStage:0});
      const signal=AbortSignal.any([controller.signal,session.signal]);
      let finalFailure:ObservationFailure | null=null;
      const publishRead=(phase:SnapshotRead['phase'],failure:ObservationFailure | null,retry:SnapshotRead['retry']=null)=>{
        if(!isCurrent())return;
        this.updateView(threadId,{snapshotRead:{phase,failure,retry},
          ...(failure?{queryFailure:failure}:{}),
          ...(failure?.status===404?{verified:false,
            approval:this.state.views[threadId].approval?{...this.state.views[threadId].approval!,verified:false}:null}:{})});
      };
      try {
        let needsFreshSnapshot = false;
        const readSnapshotOnce = async (shouldChargeInitial=isAutomatic) => {
          let failure:ObservationFailure | null=null;
          const isSameExecutionStage=()=>this.projection(threadId).snapshotVersion(runId).executionStage===request.executionStage;
          for(let retryAttempt=0;retryAttempt<=3 && isCurrent();retryAttempt++) {
            if((shouldChargeInitial || retryAttempt>0 && isSameExecutionStage()) && !this.usageVerification.hasBudget()) {
              finalFailure=failure;
              publishRead(failure?'error':'ready',failure);
              return false;
            }
            const retryAt=Math.max(this.snapshotDeadlines.get(deadlineKey) ?? 0,this.retryDeadlines.get(observationKey) ?? 0,
              failure?Date.now()+[1000,2000,5000][retryAttempt-1]:0);
            publishRead('reading',failure,retryAt>Date.now()?{attempt:retryAttempt,at:retryAt}:null);
            await waitUntil(retryAt,signal);
            if(!isCurrent())return false;
            try {
              const write = this.state.views[threadId].write;
              if (write?.phase === 'unknown') await waitUntil(write.retryAt,signal);
              if(!isCurrent())return false;
              if((shouldChargeInitial || retryAttempt>0 && isSameExecutionStage()) && !this.usageVerification.chargeRequest()) {
                publishRead(failure?'error':'ready',failure);return false;
              }
              const projection = this.projection(threadId);
              const version = projection.snapshotVersion(runId);
              request.hasStarted = true;
              const snapshot = await session.runSnapshot(threadId,runId,controller.signal);
              if (!isCurrent()) return false;
              const currentWrite = this.state.views[threadId].write;
              const canVerifyWrite = currentWrite?.phase === 'unknown' && write?.phase === 'unknown' && currentWrite === write;
              if (canVerifyWrite) {
                needsFreshSnapshot = this.applyWriteSnapshot(threadId,snapshot,version);
              } else {
                needsFreshSnapshot = projection.applySnapshot(snapshot,version,{shouldPreserveStatus:Boolean(this.observing && this.observing.threadId === threadId)})
                  || currentWrite?.phase === 'unknown';
                const approval = this.state.views[threadId].approval;
                this.updateView(threadId,{...projection.snapshot(),verified:true,queryFailure:null,
                  approval:approval ? {...approval,verified:approval.verified && projection.run?.status === 'interrupted'} : null});
                this.syncRun(threadId,projection.run!);
              }
              return true;
            } catch(error) {
              if(!isCurrent())return false;
              failure=observationFailure(error);
              const deadline=Math.max(this.snapshotDeadlines.get(deadlineKey) ?? 0,retryAfterTime(failure.retryAfter ?? null));
              this.snapshotDeadlines.set(deadlineKey,deadline);
              this.retryDeadlines.set(observationKey,Math.max(this.retryDeadlines.get(observationKey) ?? 0,deadline));
              if(!failure.recoverable || retryAttempt===3 || !this.usageVerification.hasBudget()) {
                finalFailure=failure;publishRead('error',failure);return false;
              }
            }
          }
          return false;
        };
        let succeeded = await readSnapshotOnce();
        // At most one fresh read for this invalidated group; never chase an active stream indefinitely.
        if (succeeded && (needsFreshSnapshot || request.shouldReadAgain) && isCurrent()) {
          const shouldChargeSupplement=isAutomatic && !request.shouldReadAgain;
          request.shouldReadAgain = false;
          if(!shouldChargeSupplement || this.projection(threadId).run?.usage_pending!==false)
            succeeded = await readSnapshotOnce(shouldChargeSupplement);
        }
        if (isCurrent() && succeeded) this.updateView(threadId,{snapshotRead:{phase:'ready',failure:null,retry:null}});
      } catch(error) {
        if(isCurrent()) {finalFailure=observationFailure(error);publishRead('error',finalFailure);}
      } finally {
        if (this.snapshotRequest === request) {
          this.snapshotRequest = null;
          this.usageVerification.completeRead(request.executionStage,finalFailure);
          this.syncUsageTarget();
        }
      }
    });
    return request.task;
  }

  private finishObservation(controller: AbortController) {
    const attempt = this.observing;
    if (!attempt || attempt.controller !== controller) return false;
    if (!attempt.metadata) throw new RunProtocolError('事件流结束前未收到有效运行身份。', null);
    const projection = this.projection(attempt.threadId);
    const normal = !attempt.failed && attempt.metadata && projection.run
      && (projection.run.status === 'interrupted' || terminalRun(projection.run));
    if(attempt.hasFinished)return Boolean(normal);
    attempt.hasFinished=true;
    const writeState = this.state.views[attempt.threadId].write;
    this.updateView(attempt.threadId, {observation:normal ? 'closed' : 'failed',
      approval:projection.approval(attempt.replay.values(), Boolean(normal && attempt.isGet)),
      ...(normal && attempt.isGet && writeState?.kind === 'approval' && writeState.phase === 'unknown'
        && writeState.runId === projection.run?.run_id
        ? {write:{...writeState, verified:true, verifying:false}} : {}),
      ...(!normal ? {verified:false, error:this.state.views[attempt.threadId].error ?? '观察连接结束，运行结果尚未核实。请刷新数据。'} : {})});
    if(normal && projection.run) {
      this.notifyEventBoundary(attempt.threadId,projection.run.run_id);
      void this.readSnapshot(this.session!,controller,attempt.threadId,projection.run.run_id,true);
    }
    return Boolean(normal);
  }

  private createFrameReceiver(session: BackendSession, controller: AbortController, threadId: string, targetRun?: string, isGet = targetRun !== undefined) {
    this.isEventReadPaused=false;
    const projection = this.projection(threadId);
    if (isGet && targetRun) projection.beginObservation(targetRun);
    const attempt: ObservationAttempt = {controller, threadId, runId:targetRun ?? null,
      replay:new Map(), metadata:false, failed:false, isGet,hasFinished:false};
    this.observing = attempt;
    this.updateView(threadId, {...projection.snapshot(),observation:'connecting'});
    return (frame: RunFrame) => {
      if (!this.live(session, controller) || this.observing !== attempt || this.state.activeId !== threadId) return;
      if (frame.event === "metadata") {
        if (!attempt.metadata && targetRun) projection.resetPreview(targetRun);
        projection.metadata(frame.data);
        attempt.runId = frame.data.run_id;
        attempt.metadata = true;
        this.recovery?.established();
        this.syncRun(threadId, projection.run!);
        if (!this.live(session, controller) || this.observing !== attempt) return;
        this.updateView(threadId, { ...projection.snapshot(), verified: !attempt.failed, observation:'open', retry:null, error:null,
          approval:projection.approval(attempt.replay.values(), false) });
        return;
      }
      if (frame.event === "error") {
        attempt.failed = true;
        throw new StreamObservationError(frame.data);
      }
      if (!attempt.metadata || !attempt.runId) throw new Error("事件流缺少有效运行身份");
      if (frame.event === 'event') {
        projection.mergeEvent(attempt.runId, frame.data);
        this.titles.observeMessages(threadId, projection.snapshot().messages);
        attempt.replay.set(frame.data.seq, frame.data);
      } else if (frame.event === 'delta') projection.delta(attempt.runId, frame.data);
      // 历史 lifecycle 不覆盖当前 metadata 中的状态。
      this.updateView(threadId, {...projection.snapshot(), approval:projection.approval(attempt.replay.values(), false)});
    };
  }
}
