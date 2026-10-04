import { BackendRequestError, type BackendSession, type Run, type RunFrame, type StoredMessage, type Thread } from "./backend-client.ts";

const THREAD_PAGE_SIZE = 20;

export interface ListFailure { message: string; retryAt: number; invalidCursor: boolean }
function listFailure(error: unknown): ListFailure {
  const retry = error instanceof BackendRequestError ? error.retryAfter : null;
  const retryAt = retry === null ? 0 : /^\d+$/.test(retry)
    ? Date.now() + Number(retry) * 1000 : Date.parse(retry);
  return { message: `读取会话列表失败：${String(error)}`,
    retryAt: Number.isFinite(retryAt) ? retryAt : 0,
    invalidCursor: error instanceof BackendRequestError && error.status === 422 };
}

// 完整历史记录原样保留；SSE 消息和临时正文没有数据库记录的全部外层字段。
export type ConversationMessage = Pick<StoredMessage, "run_id" | "seq" | "content"> & Partial<StoredMessage>;
export interface ConversationView {
  messages: ConversationMessage[];
  run: Run | null;
  history: "idle" | "loading" | "ready" | "error";
  verified: boolean;
  error: string | null;
  sending: boolean;
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
}
export const emptyConversation: ConversationView = {
  messages: [], run: null, history: "idle", verified: false, error: null, sending: false,
};

/** 应用级会话所有者。Workspace 仅订阅；地址租约撤销只结束读取，不删除事实和输入。 */
export class ConversationStore {
  private state: ConversationState = {
    threads: [], activeId: "", views: {}, drafts: {}, listing: false,
    listLoaded: false, loadingMore: false, nextCursor: null, pageError: null,
    creating: false, listError: null, notice: null,
  };
  private listeners = new Set<() => void>();
  private session: BackendSession | null = null;
  private selection: AbortController | null = null;
  private listRequest: AbortController | null = null;
  private moreRequest: AbortController | null = null;
  private observing: { controller: AbortController; threadId: string } | null = null;
  private statusVersions = new Map<string, number>();
  private creation: object | null = null;
  private intent = 0;

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
    this.selection?.abort();
    this.selection = null;
    this.observing = null;
    const id = this.state.activeId;
    if (id && this.state.views[id]) this.view(id, { sending: false });
  }

  private revoke = () => {
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
    void this.loadThreads(true, true);
    if (this.state.activeId) void this.openSelected();
  }

  private live(session: BackendSession, controller: AbortController) {
    return this.session === session && !session.signal.aborted && !controller.signal.aborted;
  }

  private mergeThreads(items: Thread[], versions: Map<string, number>) {
    const merged = new Map(this.state.threads.map(thread => [thread.id, thread]));
    for (const item of items) {
      const previous = merged.get(item.id);
      if (previous && previous.updated_at && item.updated_at < previous.updated_at) continue;
      const protectedStatus = previous && (this.observing?.threadId === item.id
        || versions.get(item.id) !== this.statusVersions.get(item.id));
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
    if (!session || session.signal.aborted) return;
    if (Date.now() < (this.state.listError?.retryAt ?? 0)
      || Date.now() < (this.state.pageError?.retryAt ?? 0)) return;
    if (this.listRequest && !reset) return;
    this.listRequest?.abort();
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
      }
    }
  }

  refreshThreads = () => this.loadThreads(false);
  reloadThreads = () => this.loadThreads(true, true);

  loadMore = async (retry = false) => {
    const session = this.session;
    const cursor = this.state.nextCursor;
    if (!session || session.signal.aborted || !cursor || this.moreRequest || this.listRequest
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
    void this.openSelected();
  }

  updateDraft(value: string) {
    const id = this.state.activeId;
    if (!id) return;
    this.publish({ drafts: { ...this.state.drafts, [id]: value } });
  }

  async create() {
    const session = this.session;
    if (!session || session.signal.aborted || this.creation || this.state.listing) return;
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

  canSend() {
    const view = this.state.views[this.state.activeId];
    return Boolean(this.session && !this.session.signal.aborted && view?.history === "ready"
      && view.verified && !view.sending && !this.state.creating
      && (!view.run || ["completed", "cancelled", "error"].includes(view.run.status)));
  }

  send(message: string): boolean {
    const session = this.session;
    const threadId = this.state.activeId;
    if (!session || !this.canSend() || !message.trim()) return false;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.view(threadId, { sending: true, error: null });
    void session.send(threadId, message, this.receiver(session, controller, threadId), controller.signal)
      .catch(error => {
        if (this.live(session, controller)) this.publish({
          notice: `发送连接中断：${String(error)}。正在读取已保存的结果；不会自动重发。`,
        });
      }).finally(() => {
        if (!this.live(session, controller)) return;
        this.view(threadId, { sending: false });
        // 发出 POST 后只用 GET 核实，包括连接结果未知的情况。
        this.reload();
      });
    return true;
  }

  reload = () => {
    void this.loadThreads();
    void this.openSelected();
  };

  private async openSelected() {
    const session = this.session;
    const threadId = this.state.activeId;
    if (!session || session.signal.aborted || !threadId) return;
    this.stopSelection();
    const controller = this.selection = new AbortController();
    this.view(threadId, { history: "loading", verified: false, error: null });
    try {
      const messages = await session.messages(threadId, controller.signal);
      if (!this.live(session, controller)) return;
      const last = messages.at(-1);
      const run: Run | null = last ? { thread_id: threadId, run_id: last.run_id, status: last.run_status } : null;
      this.view(threadId, { messages, run, history: "ready", verified: !run });
      if (!run) return;
      if (run.status === "running" || run.status === "interrupted") {
        try {
          await session.observe(threadId, run.run_id, this.receiver(session, controller, threadId), controller.signal);
        } finally {
          if (this.observing?.controller === controller) this.observing = null;
        }
      } else {
        const snapshot = await session.runSnapshot(threadId, run.run_id, controller.signal);
        if (this.live(session, controller)) {
          this.view(threadId, { run: snapshot, verified: true });
          this.syncRun(threadId, snapshot);
        }
      }
    } catch (error) {
      if (this.live(session, controller)) this.view(threadId, {
        history: this.state.views[threadId].history === "loading" ? "error" : "ready",
        verified: false, error: `读取会话失败：${String(error)}`,
      });
    }
  }

  private receiver(session: BackendSession, controller: AbortController, threadId: string) {
    const messages = new Map(this.state.views[threadId].messages.map(message => [message.seq, message]));
    let run = this.state.views[threadId].run;
    let receivedMetadata = false;
    return (frame: RunFrame) => {
      if (!this.live(session, controller)) return;
      if (frame.event === "metadata") {
        run = run?.run_id === frame.data.run_id ? { ...run, ...frame.data } : frame.data;
        receivedMetadata = true;
        this.observing = { controller, threadId };
        this.syncRun(threadId, run);
        this.view(threadId, { run, verified: true });
        return;
      }
      if (frame.event === "error") {
        this.view(threadId, { verified: false, error: `${frame.data.message} (${frame.data.code})` });
        return;
      }
      if (!receivedMetadata || !run) throw new Error("事件流缺少有效运行身份");
      if (frame.event === "event" && frame.data.category === "message") {
        messages.set(frame.data.seq, {
          ...messages.get(frame.data.seq),
          seq: frame.data.seq, run_id: run.run_id, content: frame.data.payload,
        });
      } else if (frame.event === "delta" && frame.data.field === "content") {
        const data = frame.data;
        const prior = messages.get(data.seq);
        if (!prior || prior.content.message_id === `preview:${data.message_id}`) {
          messages.set(data.seq, { seq: data.seq, run_id: run.run_id, content: {
            type: "ai", message_id: `preview:${data.message_id}`,
            content: (typeof prior?.content.content === "string" ? prior.content.content : "") + data.value,
          } });
        }
      }
      // 历史 lifecycle 不覆盖当前 metadata 中的状态。
      this.view(threadId, { messages: [...messages.values()].sort((a, b) => a.seq - b.seq) });
    };
  }
}
