import type { MessageContent, Run, RunFrame, StoredMessage, RunEvent, ApprovalRequired } from './backend-client.ts';
import { RunProtocolError } from './run-protocol.ts';

export type ConversationMessage = Pick<StoredMessage, 'run_id' | 'seq' | 'content'> & Partial<StoredMessage> & { preview?: boolean };
export interface ApprovalProjection { request: RunEvent & { payload: ApprovalRequired }; verified: boolean }
export interface RunFieldVersion {stage:number; executionStage:number; usage:number; outcome:number; status:number}
export interface SnapshotAuthority {shouldPreserveStatus?:boolean; isWrite?:boolean}

// 对象键的次序不属于事实内容；数组次序及省略/null 的区别属于事实。
export function sameFact(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b)
    && a.length === b.length && a.every((factValue, index) => sameFact(factValue, b[index]));
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && sameFact(left[key], right[key]));
}

export const terminalRun = (run: Run) => ['completed', 'cancelled', 'error'].includes(run.status);
const messageFact = (content:MessageContent) => content.type === 'ai'
  ? {...content, generation_status:content.generation_status ?? 'complete'} : content;

/** 一份会话事实。观察连接结束后仍保留，只有预览属于单次观察。 */
export class RunProjection {
  private messages = new Map<number, ConversationMessage>();
  private events = new Map<string, Map<number, RunEvent>>();
  private runs = new Map<string, Run>();
  private versions = new Map<string, RunFieldVersion>();
  private runFloor = 0;
  run: Run | null = null;

  snapshot() {
    const runStatuses:Record<string, Run['status']> = Object.create(null);
    for (const message of this.messages.values()) if (message.run_status) runStatuses[message.run_id] = message.run_status;
    for (const [id, run] of this.runs) {
      // 保存过的终态不可被较早的历史／metadata 降级；此映射仅供各卡片说明所属运行。
      if (terminalRun(run) || !['completed', 'cancelled', 'error'].includes(runStatuses[id])) runStatuses[id] = run.status;
    }
    return { messages: [...this.messages.values()].sort((a, b) => a.seq - b.seq), run: this.run, runStatuses,
      events: Object.fromEntries([...this.events].map(([id, events]) => [id, [...events.values()].sort((a, b) => a.seq - b.seq)])) };
  }

  mergeHistory(records: StoredMessage[]) {
    this.mergeMessages(records);
    const latestMessage = this.snapshot().messages.filter(message => !message.preview).at(-1);
    const discoveredMessage = records.find(record => record.run_id === latestMessage?.run_id);
    if (discoveredMessage && (!this.run || discoveredMessage.run_id === this.run.run_id || latestMessage!.seq > this.runFloor)) {
      this.metadata({ thread_id: discoveredMessage.thread_id, run_id: discoveredMessage.run_id, status: discoveredMessage.run_status });
    }
  }

  /** 只补正文事实；已接受 POST／已核实观察的状态继续以 metadata 为准。 */
  mergeMessages(records:ConversationMessage[]) {
    for (const record of records) this.message(record);
  }

  metadata(incomingRun: Run) {
    const existingRun = this.runs.get(incomingRun.run_id);
    if (existingRun && terminalRun(existingRun) && incomingRun.status !== existingRun.status) return;
    if (this.run?.run_id !== incomingRun.run_id) {
      this.runFloor = 0;
      for (const seq of this.messages.keys()) this.runFloor = Math.max(this.runFloor, seq);
    }
    const updatedRun = { ...existingRun, ...incomingRun };
    const version = this.snapshotVersion(incomingRun.run_id);
    if (existingRun?.status === 'interrupted' && incomingRun.status === 'running') {
      version.stage++; version.executionStage++;
      if (!Object.hasOwn(incomingRun, 'usage_pending')) updatedRun.usage_pending = null;
      version.usage++;
    }
    if (existingRun?.status !== incomingRun.status) version.status++;
    if (['usage','usage_pending'].some(key => Object.hasOwn(incomingRun,key))) version.usage++;
    if (['error','error_code','completed_at'].some(key => Object.hasOwn(incomingRun,key))) version.outcome++;
    this.versions.set(incomingRun.run_id,version);
    this.runs.set(incomingRun.run_id, updatedRun);
    this.run = updatedRun;
  }

  snapshotVersion(runId:string):RunFieldVersion {
    return {...(this.versions.get(runId) ?? {stage:0,executionStage:0,usage:0,outcome:0,status:0})};
  }

  /** A new GET observation cannot prove it is still the same execution stage. */
  beginObservation(runId:string) {
    const existingRun = this.runs.get(runId);
    if (!existingRun) return;
    const version = this.snapshotVersion(runId);
    version.stage++; version.usage++;
    this.versions.set(runId,version);
    const updatedRun = Object.hasOwn(existingRun,'usage_pending') ? {...existingRun,usage_pending:null} : {...existingRun};
    this.runs.set(runId,updatedRun);
    if (this.run?.run_id === runId) this.run = updatedRun;
  }

  applySnapshot(incomingRun: Run, requestVersion = this.snapshotVersion(incomingRun.run_id), authority:SnapshotAuthority = {}) {
    const existingRun = this.runs.get(incomingRun.run_id);
    const currentVersion = this.snapshotVersion(incomingRun.run_id);
    const updates = { ...incomingRun };
    const hasStaleUsage = (Object.hasOwn(incomingRun,'usage') || Object.hasOwn(incomingRun,'usage_pending'))
      && (requestVersion.stage !== currentVersion.stage || requestVersion.usage !== currentVersion.usage);
    if (requestVersion.stage !== currentVersion.stage || requestVersion.usage !== currentVersion.usage) {
      delete updates.usage; delete updates.usage_pending;
    }
    if (requestVersion.outcome !== currentVersion.outcome || requestVersion.status !== currentVersion.status
      || existingRun && (authority.shouldPreserveStatus || terminalRun(existingRun)) && incomingRun.status !== existingRun.status) {
      delete updates.error; delete updates.error_code; delete updates.completed_at;
    }
    // 查询里的旧空值不能清除流中已确认的失败／完成字段。
    for (const key of ['error','error_code','completed_at'] as const) {
      if (updates[key] === null && existingRun?.[key] != null) delete updates[key];
    }
    if (existingRun && (authority.shouldPreserveStatus || terminalRun(existingRun)
      || !authority.isWrite && requestVersion.status !== currentVersion.status)) updates.status = existingRun.status;
    // Server timestamps can be filled even when metadata advanced during the request.
    if (existingRun?.updated_at && updates.updated_at && Date.parse(updates.updated_at) < Date.parse(existingRun.updated_at)) delete updates.updated_at;
    this.metadata(updates);
    return hasStaleUsage;
  }

  approval(replay: Iterable<RunEvent>, verified: boolean): ApprovalProjection | null {
    let request: ApprovalProjection['request'] | null = null;
    const requests: ApprovalProjection['request'][] = [];
    const processedCheckpoints: ApprovalRequired['checkpoint'][] = [];
    for (const event of [...replay].sort((a, b) => a.seq - b.seq)) {
      if (event.category !== 'approval') continue;
      const payload = event.payload;
      if (payload.status === 'required') {
        if (processedCheckpoints.some(checkpoint => sameFact(checkpoint, payload.checkpoint))) throw new RunProtocolError('已处理或失效的 checkpoint 不能重新请求审批', event);
        const existingApproval = requests.find(approvalRequest => sameFact(approvalRequest.payload.checkpoint, payload.checkpoint));
        if (existingApproval && !sameFact(existingApproval.payload, payload)) throw new RunProtocolError('同一 checkpoint 的审批请求内容冲突', event);
        request = { ...event, payload };
        requests.push(request);
      } else {
        processedCheckpoints.push(payload.checkpoint);
        const requiredRequest = requests.find(approvalRequest => sameFact(approvalRequest.payload.checkpoint, payload.checkpoint));
        if (!requiredRequest) continue; // 查询可以缺项，不凭空补出对应 required。
        const ids = payload.status === 'resolved' ? Object.keys(payload.responses) : payload.interrupt_ids;
        if (ids.length !== requiredRequest.payload.interrupts.length || !requiredRequest.payload.interrupts.every(interrupt => ids.includes(interrupt.id))) {
          throw new RunProtocolError('审批处理身份必须覆盖全部 Interrupt', event);
        }
        if (request && sameFact(request.payload.checkpoint, payload.checkpoint)) request = null;
      }
    }
    return request ? {request, verified:verified && this.run?.status === 'interrupted'} : null;
  }

  resetPreview(runId: string) {
    for (const [seq, message] of this.messages) if (message.run_id === runId && message.preview) this.messages.delete(seq);
  }

  private eventAt(seq: number) {
    for (const [runId, events] of this.events) {
      const event = events.get(seq);
      if (event) return {runId, event};
    }
    return null;
  }

  private message(message: ConversationMessage) {
    const fact = this.eventAt(message.seq);
    if (fact && (fact.runId !== message.run_id || fact.event.category !== 'message'
      || !sameFact(messageFact(fact.event.payload), messageFact(message.content))
      || message.created_at && fact.event.created_at !== message.created_at)) {
      throw new RunProtocolError(`消息 seq=${message.seq} 与已确认事件冲突`, message);
    }
    const existingMessage = this.messages.get(message.seq);
    const conflicts = existingMessage && (existingMessage.run_id !== message.run_id || existingMessage.content.message_id !== message.content.message_id
      || !existingMessage.preview && Object.entries(message).some(([key, value]) => key !== 'run_status' && key !== 'preview'
        && Object.hasOwn(existingMessage, key) && !sameFact(key === 'content' ? messageFact(existingMessage.content)
          : (existingMessage as Record<string, unknown>)[key], key === 'content' ? messageFact(message.content) : value)));
    if (conflicts) {
      throw new RunProtocolError(`消息 seq=${message.seq} 与已确认事实冲突`, message);
    }
    const completeMessage = { ...existingMessage, ...message };
    delete completeMessage.preview;
    this.messages.set(message.seq, completeMessage);
  }

  mergeEvent(runId: string, event: RunEvent) {
    // seq 是会话级顺序，不能被另一 Run 或类别重新占用。
    const existingEvent = this.eventAt(event.seq);
    const normalizeEvent = (runEvent:RunEvent) => runEvent.category === 'message' ? {...runEvent, payload:messageFact(runEvent.payload)} : runEvent;
    if (existingEvent && (existingEvent.runId !== runId || !sameFact(normalizeEvent(existingEvent.event), normalizeEvent(event)))) throw new RunProtocolError(`事件 seq=${event.seq} 与已确认事实冲突`, event);
    if (existingEvent) return;
    const message = this.messages.get(event.seq);
    if (message && (message.run_id !== runId || event.category !== 'message')) throw new RunProtocolError(`事件 seq=${event.seq} 与消息身份冲突`, event);
    if (message?.created_at && message.created_at !== event.created_at) throw new RunProtocolError(`事件 seq=${event.seq} 与已确认时间冲突`, event);
    if (event.category === 'approval') this.approval([...(this.events.get(runId)?.values() ?? []), event], false);
    if (event.category === 'message') this.message({seq:event.seq, run_id:runId, created_at:event.created_at, content:event.payload});
    const events = this.events.get(runId) ?? new Map<number, RunEvent>();
    events.set(event.seq, event);
    this.events.set(runId, events);
  }

  /** A conflicting query remains a read-only protocol issue; none of its batch replaces facts. */
  mergeEvents(runId:string, events:RunEvent[]) {
    const previousMessages=this.messages, previousEvents=this.events;
    this.messages=new Map(previousMessages);
    this.events=new Map([...previousEvents].map(([id,records])=>[id,new Map(records)]));
    try {
      for (const event of [...events].sort((left,right)=>left.seq-right.seq)) this.mergeEvent(runId,event);
    } catch (error) {
      this.messages=previousMessages; this.events=previousEvents;
      throw error;
    }
  }

  delta(runId: string, data: Extract<RunFrame, {event:'delta'}>['data']) {
    if (data.field !== 'content') return;
    const existingMessage = this.messages.get(data.seq);
    const fact = this.eventAt(data.seq);
    if (fact && (fact.runId !== runId || fact.event.category !== 'message')) throw new RunProtocolError('增量 seq 与已确认事件冲突', data);
    if (existingMessage && (existingMessage.run_id !== runId || existingMessage.content.message_id !== data.message_id)) throw new RunProtocolError('增量消息身份冲突', data);
    if (existingMessage && !existingMessage.preview) return;
    const text = typeof existingMessage?.content.content === 'string' ? existingMessage.content.content : '';
    const content: MessageContent = {type:'ai', message_id:data.message_id, content:text + data.value, tool_calls:[]};
    this.messages.set(data.seq, {run_id:runId, seq:data.seq, preview:true, content});
  }
}
