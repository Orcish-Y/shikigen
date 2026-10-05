import { BackendRequestError, type BackendSession, type Run, type RunFrame, type RunEvent, type Thread } from "./backend-client.ts";
import { RunProjection, terminalRun, type ApprovalProjection, type ConversationMessage } from './run-projection.ts';
import { RunProtocolError } from './run-protocol.ts';
import { MessageDrafts, type DraftStorage, type MessageSubmission } from './message-drafts.ts';
import { ObservationRecovery, StreamObservationError, UnexpectedObservationEnd, observationFailure, retryAfterTime, waitUntil, type ObservationState, type ObservationFailure, type RecoveryUpdate } from './observation-recovery.ts';
export type { ConversationMessage } from './run-projection.ts';

const THREAD_PAGE_SIZE = 20;

export interface ListFailure { message: string; retryAt: number; invalidCursor: boolean }
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
  history: "idle" | "loading" | "ready" | "error";
  verified: boolean;
  error: string | null;
  sending: boolean;
  events: ReturnType<RunProjection['snapshot']>['events'];
  approval: ApprovalProjection | null;
  observation: ObservationState;
  retry: RecoveryUpdate['retry'];
  observationFailure: ObservationFailure | null;
  querying: boolean;
  queryFailure: ObservationFailure | null;
  sendFailure: ObservationFailure | null;
  protocolIssue: {message:string; raw:unknown} | null;
  missing: boolean;
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
}
export const emptyConversation: ConversationView = {
  messages: [], run: null, history: "idle", verified: false, error: null, sending: false, events:{}, approval:null, observation:'idle', retry:null, observationFailure:null, querying:false, queryFailure:null, sendFailure:null, protocolIssue:null, missing:false,
};

interface ObservationAttempt {
  controller: AbortController; threadId: string; runId: string | null;
  replay: Map<number, RunEvent>; metadata: boolean; failed: boolean; get: boolean;
}

/** 应用级会话所有者。Workspace 仅订阅；地址租约撤销只结束读取，不删除事实和输入。 */
export class ConversationStore {
  private state: ConversationState = {
    threads: [], activeId: "", views: {}, drafts: {}, listing: false,
    listLoaded: false, loadingMore: false, nextCursor: null, pageError: null,
    creating: false, listError: null, notice: null, storageIssue:null, submissions:{},
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
  private queryRequest: AbortController | null = null;
  private summaryRequest: AbortController | null = null;
  private summaryTarget: {threadId:string; runId:string | null} | null = null;
  private statusVersions = new Map<string, number>();
  private creation: object | null = null;
  private intent = 0;
  private projections = new Map<string, RunProjection>();
  private inputs: MessageDrafts;

  constructor(options: {storage?: DraftStorage | null} = {}) {
    this.inputs = new MessageDrafts(options.storage);
    this.state = {...this.state, activeId:this.inputs.selected, ...this.inputState()};
  }

  private inputState() {
    return {drafts:Object.fromEntries(Object.entries(this.inputs.drafts).map(([id, draft]) => [id, draft.text])),
      storageIssue:this.inputs.storageIssue, submissions:this.inputs.submissions};
  }

  private publishInputs() { this.publish(this.inputState()); }

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

  private publish(change: Partial<ConversationState>) {
    this.state = { ...this.state, ...change };
    this.listeners.forEach(listener => listener());
  }

  private view(threadId: string, change: Partial<ConversationView>) {
    this.publish({ views: { ...this.state.views,
      [threadId]: { ...(this.state.views[threadId] ?? emptyConversation), ...change },
    } });
  }

  private stopSelection() {
    const id = this.state.activeId;
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
    if (id && this.state.views[id]) this.view(id, { verified:false, sending: false, observation:'paused', retry:null, querying:false,
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
    this.publish({
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
      this.view(this.state.activeId, {history:'loading', verified:false});
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
    this.publish({ threads: [...merged.values()].sort((a, b) =>
      a.updated_at === b.updated_at ? (a.id === b.id ? 0 : a.id > b.id ? -1 : 1)
        : a.updated_at > b.updated_at ? -1 : 1) });
  }

  private syncRun(threadId: string, run: Run) {
    this.statusVersions.set(threadId, (this.statusVersions.get(threadId) ?? 0) + 1);
    this.publish({ threads: this.state.threads.map(thread => thread.id === threadId
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
      this.publish({ loadingMore: false });
    }
    const controller = this.listRequest = new AbortController();
    const intent = this.intent;
    const versions = new Map(this.statusVersions);
    this.publish({ listing: true, listError: null });
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
      if (reset || !this.state.listLoaded) this.publish({
        nextCursor: page.data.length < THREAD_PAGE_SIZE ? null : page.next_cursor, pageError: null,
      });
      this.publish({ listLoaded: true });
      if (chooseInitial && !this.state.activeId && intent === this.intent && page.data.length) this.select(page.data[0].id);
    } catch (error) {
      if (this.live(session, controller)) this.publish({ listError: listFailure(error) });
    } finally {
      if (this.live(session, controller)) {
        this.listRequest = null;
        this.publish({ listing: false });
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
    this.publish({ loadingMore: true, pageError: null });
    try {
      const page = await session.threads(THREAD_PAGE_SIZE, controller.signal, cursor);
      if (!this.live(session, controller)) return;
      if (page.data.length === THREAD_PAGE_SIZE && page.next_cursor === cursor) throw new Error("分页游标未前进，请重新加载会话列表");
      this.mergeThreads(page.data, versions);
      this.publish({ nextCursor: page.data.length < THREAD_PAGE_SIZE ? null : page.next_cursor });
    } catch (error) {
      if (this.live(session, controller)) this.publish({ pageError: listFailure(error) });
    } finally {
      if (this.live(session, controller)) {
        this.moreRequest = null;
        this.publish({ loadingMore: false });
      }
    }
  };

  select(threadId: string) {
    if (!threadId || !this.state.threads.some(thread => thread.id === threadId)) return;
    this.intent++;
    this.stopSelection();
    this.publish({ activeId: threadId });
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
    this.publish({ creating: true, notice: null });
    try {
      const { thread_id } = await session.createThread();
      if (this.session !== session || session.signal.aborted) return;
      if (!this.state.threads.some(thread => thread.id === thread_id)) {
        // 创建响应不提供时间，不制造本地时间冒充服务端事实。
        this.publish({ threads: [{ id: thread_id, user_id: null, title: null, created_at: "", updated_at: "", run_id: null, run_status: null }, ...this.state.threads] });
      }
      if (intent === this.intent) this.select(thread_id);
      else this.publish({ notice: `会话已创建（${thread_id}），已保留在列表中，继续当前会话。` });
      await this.loadThreads(false);
      return thread_id;
    } catch (error) {
      if (this.session !== session || session.signal.aborted) return;
      this.publish({ notice: `创建结果待确认：${String(error)}。请核对会话列表；不会自动再次创建。` });
      await this.loadThreads(false);
    } finally {
      if (this.creation === creation) {
        this.creation = null;
        this.publish({ creating: false });
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
    this.publish({notice:'文字已复制到新会话，请核对后手动发送；原会话文字仍保留。'});
  };

  private canStartRun() {
    const view = this.state.views[this.state.activeId];
    return Boolean(this.visible && this.session && !this.session.signal.aborted && view?.history === "ready"
      && view.verified && !view.sending && !this.state.creating
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
    this.view(threadId, { sending: true, error: null, sendFailure:null });
    const receive = this.receiver(session, controller, threadId);
    let normal = false;
    let failure:unknown;
    void session.send(threadId, message, frame => {
      if (!this.live(session, controller) || this.state.activeId !== threadId) return;
      if (frame.event === 'metadata' && frame.data.run_id === submission.previousRunId) {
        throw new RunProtocolError('本次发送返回旧运行身份，接受情况待核实', frame.data);
      }
      receive(frame);
      if (!this.live(session, controller) || this.state.activeId !== threadId) return;
      if (frame.event === 'metadata') {
        this.inputs.accept(threadId, submission.id, frame.data.run_id);
        this.publishInputs();
        this.view(threadId, {sending:false});
      }
    }, controller.signal)
      .then(() => { if (this.live(session, controller)) normal = this.finishObservation(controller); })
      .catch(error => {
        failure = error;
        if (this.live(session, controller)) {
          if (error instanceof BackendRequestError && [400,409,422].includes(error.status)) this.inputs.rejected(threadId);
          else this.inputs.markSubmissionUnknown(threadId, String(error), listFailure(error).retryAt, observationFailure(error));
          this.publishInputs();
          this.view(threadId, {verified:false, observation:'failed', sendFailure:observationFailure(error),
            ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
          this.publish({notice: `发送请求异常：${String(error)}。正在读取已保存的结果；不会自动重发。`});
        }
      }).finally(async () => {
        if (!this.live(session, controller)) return;
        this.inputs.markSubmissionUnknown(threadId, '发送流在确认接受前结束，请核对已保存消息。');
        this.publishInputs();
        this.view(threadId, { sending: false });
        if (this.observing?.controller === controller) this.observing = null;
        const accepted = this.inputs.submissions[threadId];
        if (accepted?.id === submission.id && accepted.status === 'accepted' && accepted.runId) {
          if (!normal) {
            const recovering = this.observeRun(session, controller, threadId, accepted.runId,
              failure ?? new UnexpectedObservationEnd('已接受发送，观察连接意外结束。'));
            // 首 metadata 后即断流也补读真实正文，不把已接受发送显示为空会话。
            // 正文 JSON 与同 Run SSE 分工读取；观察仍只有一个恢复任务。
            void this.readCommittedHistory(session, controller, threadId);
            normal = await recovering;
          }
          if (normal && this.live(session, controller)) {
            await this.readCommittedHistory(session, controller, threadId);
            await this.readSnapshot(session, controller, threadId, accepted.runId);
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

  reconnect = () => {
    const session = this.session;
    const threadId = this.state.activeId;
    const view = this.state.views[threadId];
    if (!this.visible || !session || session.signal.aborted || !view?.run || view.history !== 'ready'
      || view.sending || this.recovery || this.observing || this.queryRequest) return;
    const runId = view.run.run_id;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.view(threadId, {verified:false, error:null});
    void this.observeRun(session, controller, threadId, runId).then(async normal => {
      if (normal && this.live(session, controller)) {
        await this.readCommittedHistory(session, controller, threadId);
        await this.readSnapshot(session, controller, threadId, runId);
      }
    });
  };

  queryStatus = async () => {
    const session = this.session;
    const threadId = this.state.activeId;
    const view = this.state.views[threadId];
    if (!this.visible || !session || session.signal.aborted || !view?.run || this.queryRequest
      || view.sending || view.history !== 'ready' || this.recovery || this.observing) return;
    const controller = this.queryRequest = new AbortController();
    const runId = view.run.run_id;
    this.view(threadId, {querying:true, queryFailure:null});
    try {
      await waitUntil(this.retryDeadlines.get(`${threadId}:${runId}`) ?? 0, AbortSignal.any([controller.signal, session.signal]));
      if (this.live(session, controller)) await this.readSnapshot(session, controller, threadId, runId);
    } catch (error) {
      if (this.live(session, controller)) this.view(threadId, {queryFailure:observationFailure(error)});
    } finally {
      if (this.queryRequest === controller) {
        this.queryRequest = null;
        this.view(threadId, {querying:false});
      }
    }
  };

  private async readCommittedHistory(session:BackendSession, controller:AbortController, threadId:string) {
    try {
      const messages = await session.messages(threadId, controller.signal);
      if (!this.live(session, controller)) return;
      const projection = this.projection(threadId);
      projection.mergeMessages(messages);
      this.view(threadId, {...projection.snapshot(), history:'ready'});
    } catch (error) {
      if (this.live(session, controller)) this.view(threadId, {error:`读取已保存消息失败：${String(error)}`,
        ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
    }
  }

  private async openSelected() {
    const session = this.session;
    const threadId = this.state.activeId;
    if (!this.visible || !session || session.signal.aborted || !threadId) return;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.view(threadId, { history: "loading", verified: false, error: null, missing:false });
    let historyRead = false;
    try {
      await waitUntil(this.inputs.submissions[threadId]?.retryAt ?? 0, AbortSignal.any([controller.signal, session.signal]));
      const messages = await session.messages(threadId, controller.signal);
      if (!this.live(session, controller)) return;
      historyRead = true;
      const projection = this.projection(threadId);
      projection.mergeHistory(messages);
      const accepted = this.inputs.submissions[threadId];
      // 接受身份是恢复线索；历史可能尚未包含该 Run，必须重新 GET 核实。
      if (accepted?.status === 'accepted' && accepted.runId
        && (!projection.run || projection.run.run_id === accepted.previousRunId)) {
        const snapshot = await session.runSnapshot(threadId, accepted.runId, controller.signal);
        if (!this.live(session, controller)) return;
        projection.metadata(snapshot);
      }
      await this.restoreSelectedRun(session, controller, threadId);
    } catch (error) {
      if (this.live(session, controller)) this.view(threadId, {
        history: this.state.views[threadId].history === "loading" ? "error" : "ready",
        verified: false, observation:'failed', error: historyRead && error instanceof BackendRequestError && error.status === 404
          ? `运行不可读取：${String(error)}` : `读取会话失败：${String(error)}`,
        missing:!historyRead && error instanceof BackendRequestError && error.status === 404,
        ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {}),
      });
    }
  }

  private async restoreSelectedRun(session:BackendSession, controller:AbortController, threadId:string) {
    const projection = this.projection(threadId);
    const run = projection.run;
    this.view(threadId, {...projection.snapshot(), history:'ready', verified:!run});
    if (!run) {this.view(threadId, {observation:'idle', retry:null, observationFailure:null}); return;}
    if (run.status === 'running' || run.status === 'interrupted') {
      const completed = await this.observeRun(session, controller, threadId, run.run_id);
      if (completed) await this.readSnapshot(session, controller, threadId, run.run_id);
    } else {
      // 终态无需 SSE；完成本轮读取后不能沿用隐藏时的主动暂停状态。
      this.view(threadId, {observation:'idle', retry:null, observationFailure:null});
      await this.readSnapshot(session, controller, threadId, run.run_id);
      if (this.live(session, controller) && this.state.views[threadId].verified) {
        this.view(threadId, {observation:'closed'});
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
      // 同 Run 的摘要不触发新恢复轮次，也不回退当前 metadata 状态。
      if (messages.at(-1)?.run_id !== previousRun) projection.mergeHistory(messages);
      this.view(summary.id, projection.snapshot());
      if (projection.run?.run_id === previousRun) return;
      this.stopSelection();
      const selection = this.selection = new AbortController();
      await this.restoreSelectedRun(session, selection, summary.id);
    } catch (error) {
      if (this.live(session, controller)) this.view(summary.id, {error:`核实会话新运行失败：${String(error)}`});
    } finally {
      if (this.summaryRequest === controller) this.summaryRequest = null;
    }
  }

  private async observeRun(session:BackendSession, controller:AbortController, threadId:string, runId:string, initialFailure?:unknown) {
    const key = `${threadId}:${runId}`;
    const recovery = new ObservationRecovery(AbortSignal.any([controller.signal, session.signal]), this.retryDeadlines.get(key) ?? 0, update => {
      if (!this.live(session, controller) || this.recovery !== recovery) return;
      this.retryDeadlines.set(key, recovery.retryAt);
      this.view(threadId, {...update,
        ...(update.observation === 'retry_wait' || update.observation === 'failed' ? {verified:false,
          error:update.observationFailure?.status === 404 ? `运行不可读取：${update.observationFailure.message}` : update.observationFailure?.message ?? null,
          ...(update.observationFailure?.kind === 'protocol' ? {protocolIssue:{message:update.observationFailure.message, raw:update.observationFailure.raw}} : {}),
          approval:this.state.views[threadId].approval ? {...this.state.views[threadId].approval!, verified:false} : null} : {})});
    });
    this.recovery = recovery;
    try {
      return await recovery.run(async () => {
        try {
          await session.observe(threadId, runId, this.receiver(session, controller, threadId, runId), controller.signal);
          return this.live(session, controller) && this.finishObservation(controller);
        } finally {
          if (this.observing?.controller === controller) this.observing = null;
        }
      }, initialFailure);
    } finally {
      if (this.recovery === recovery) this.recovery = null;
    }
  }

  private async readSnapshot(session: BackendSession, controller: AbortController, threadId: string, runId: string) {
    const version = this.statusVersions.get(threadId);
    try {
      const snapshot = await session.runSnapshot(threadId, runId, controller.signal);
      if (!this.live(session, controller) || this.state.views[threadId].run?.run_id !== runId
        || version !== this.statusVersions.get(threadId)) return;
      const projection = this.projection(threadId);
      projection.applySnapshot(snapshot);
      const approval = this.state.views[threadId].approval;
      this.view(threadId, {...projection.snapshot(), verified:true, queryFailure:null,
        approval:approval ? {...approval, verified:approval.verified && projection.run?.status === 'interrupted'} : null});
      this.syncRun(threadId, projection.run!);
    } catch (error) {
      if (this.live(session, controller)) {
        const failure = observationFailure(error);
        const key = `${threadId}:${runId}`;
        this.retryDeadlines.set(key, Math.max(this.retryDeadlines.get(key) ?? 0, retryAfterTime(failure.retryAfter ?? null)));
        this.view(threadId, {error:`读取运行快照失败：${String(error)}`, queryFailure:failure,
        ...(error instanceof RunProtocolError ? {protocolIssue:{message:error.message, raw:error.raw}} : {})});
      }
    }
  }

  private finishObservation(controller: AbortController) {
    const attempt = this.observing;
    if (!attempt || attempt.controller !== controller) return false;
    if (!attempt.metadata) throw new RunProtocolError('事件流结束前未收到有效运行身份。', null);
    const projection = this.projection(attempt.threadId);
    const normal = !attempt.failed && attempt.metadata && projection.run
      && (projection.run.status === 'interrupted' || terminalRun(projection.run));
    this.view(attempt.threadId, {observation:normal ? 'closed' : 'failed',
      approval:projection.approval(attempt.replay.values(), Boolean(normal && attempt.get)),
      ...(!normal ? {verified:false, error:this.state.views[attempt.threadId].error ?? '观察连接结束，运行结果尚未核实。请刷新数据。'} : {})});
    return Boolean(normal);
  }

  private receiver(session: BackendSession, controller: AbortController, threadId: string, targetRun?: string) {
    const projection = this.projection(threadId);
    const attempt: ObservationAttempt = {controller, threadId, runId:targetRun ?? null,
      replay:new Map(), metadata:false, failed:false, get:targetRun !== undefined};
    this.observing = attempt;
    this.view(threadId, {observation:'connecting'});
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
        this.view(threadId, { ...projection.snapshot(), verified: !attempt.failed, observation:'open', retry:null, error:null,
          approval:projection.approval(attempt.replay.values(), false) });
        return;
      }
      if (frame.event === "error") {
        attempt.failed = true;
        throw new StreamObservationError(frame.data);
      }
      if (!attempt.metadata || !attempt.runId) throw new Error("事件流缺少有效运行身份");
      if (frame.event === 'event') {
        projection.event(attempt.runId, frame.data);
        attempt.replay.set(frame.data.seq, frame.data);
      } else if (frame.event === 'delta') projection.delta(attempt.runId, frame.data);
      // 历史 lifecycle 不覆盖当前 metadata 中的状态。
      this.view(threadId, {...projection.snapshot(), approval:projection.approval(attempt.replay.values(), false)});
    };
  }
}
