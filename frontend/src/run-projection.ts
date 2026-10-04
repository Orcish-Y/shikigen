import type { MessageContent, Run, RunFrame, StoredMessage, RunEvent, ApprovalRequired } from './backend-client.ts';
import { RunProtocolError } from './run-protocol.ts';

export type ConversationMessage = Pick<StoredMessage, 'run_id' | 'seq' | 'content'> & Partial<StoredMessage> & { preview?: boolean };
export interface ApprovalProjection { request: RunEvent & { payload: ApprovalRequired }; verified: boolean }

// 对象键的次序不属于事实内容；数组次序及省略/null 的区别属于事实。
export function sameFact(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b)
    && a.length === b.length && a.every((item, index) => sameFact(item, b[index]));
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && sameFact(left[key], right[key]));
}

export const terminalRun = (run: Run) => ['completed', 'cancelled', 'error'].includes(run.status);

/** 一份会话事实。观察连接结束后仍保留，只有预览属于单次观察。 */
export class RunProjection {
  private messages = new Map<number, ConversationMessage>();
  private events = new Map<string, Map<number, RunEvent>>();
  private runs = new Map<string, Run>();
  private runFloor = 0;
  run: Run | null = null;

  snapshot() {
    return { messages: [...this.messages.values()].sort((a, b) => a.seq - b.seq), run: this.run,
      events: Object.fromEntries([...this.events].map(([id, events]) => [id, [...events.values()].sort((a, b) => a.seq - b.seq)])) };
  }

  mergeHistory(records: StoredMessage[]) {
    for (const record of records) this.message(record);
    const last = this.snapshot().messages.filter(message => !message.preview).at(-1);
    const discovered = records.find(record => record.run_id === last?.run_id);
    if (discovered && (!this.run || discovered.run_id === this.run.run_id || last!.seq > this.runFloor)) {
      this.metadata({ thread_id: discovered.thread_id, run_id: discovered.run_id, status: discovered.run_status });
    }
  }

  metadata(incoming: Run) {
    const previous = this.runs.get(incoming.run_id);
    if (previous && terminalRun(previous) && incoming.status !== previous.status) return;
    if (this.run?.run_id !== incoming.run_id) {
      this.runFloor = 0;
      for (const seq of this.messages.keys()) this.runFloor = Math.max(this.runFloor, seq);
    }
    const next = { ...previous, ...incoming };
    if (previous?.status === 'interrupted' && incoming.status === 'running' && !Object.hasOwn(incoming, 'usage_pending')) next.usage_pending = null;
    this.runs.set(incoming.run_id, next);
    this.run = next;
  }

  applySnapshot(incoming: Run) {
    const previous = this.runs.get(incoming.run_id);
    const updates = { ...incoming };
    // 查询里的旧空值不能清除流中已确认的失败／完成字段。
    for (const key of ['error','error_code','completed_at'] as const) {
      if (updates[key] === null && previous?.[key] != null) delete updates[key];
    }
    this.metadata(updates);
  }

  approval(replay: Iterable<RunEvent>, verified: boolean): ApprovalProjection | null {
    let request: ApprovalProjection['request'] | null = null;
    const requests: ApprovalProjection['request'][] = [];
    const processed: ApprovalRequired['checkpoint'][] = [];
    for (const event of [...replay].sort((a, b) => a.seq - b.seq)) {
      if (event.category !== 'approval') continue;
      const payload = event.payload;
      if (payload.status === 'required') {
        if (processed.some(checkpoint => sameFact(checkpoint, payload.checkpoint))) throw new RunProtocolError('已处理或失效的 checkpoint 不能重新请求审批', event);
        const previous = requests.find(item => sameFact(item.payload.checkpoint, payload.checkpoint));
        if (previous && !sameFact(previous.payload, payload)) throw new RunProtocolError('同一 checkpoint 的审批请求内容冲突', event);
        request = { ...event, payload };
        requests.push(request);
      } else {
        processed.push(payload.checkpoint);
        const required = requests.find(item => sameFact(item.payload.checkpoint, payload.checkpoint));
        if (!required) continue; // 查询可以缺项，不凭空补出对应 required。
        const ids = payload.status === 'resolved' ? Object.keys(payload.responses) : payload.interrupt_ids;
        if (ids.length !== required.payload.interrupts.length || !required.payload.interrupts.every(item => ids.includes(item.id))) {
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
      || !sameFact(fact.event.payload, message.content)
      || message.created_at && fact.event.created_at !== message.created_at)) {
      throw new RunProtocolError(`消息 seq=${message.seq} 与已确认事件冲突`, message);
    }
    const previous = this.messages.get(message.seq);
    const conflicts = previous && (previous.run_id !== message.run_id || previous.content.message_id !== message.content.message_id
      || !previous.preview && Object.entries(message).some(([key, value]) => key !== 'run_status' && key !== 'preview'
        && Object.hasOwn(previous, key) && !sameFact((previous as Record<string, unknown>)[key], value)));
    if (conflicts) {
      throw new RunProtocolError(`消息 seq=${message.seq} 与已确认事实冲突`, message);
    }
    const complete = { ...previous, ...message };
    delete complete.preview;
    this.messages.set(message.seq, complete);
  }

  event(runId: string, event: RunEvent) {
    // seq 是会话级顺序，不能被另一 Run 或类别重新占用。
    const previous = this.eventAt(event.seq);
    if (previous && (previous.runId !== runId || !sameFact(previous.event, event))) throw new RunProtocolError(`事件 seq=${event.seq} 与已确认事实冲突`, event);
    const message = this.messages.get(event.seq);
    if (message && (message.run_id !== runId || event.category !== 'message')) throw new RunProtocolError(`事件 seq=${event.seq} 与消息身份冲突`, event);
    if (message?.created_at && message.created_at !== event.created_at) throw new RunProtocolError(`事件 seq=${event.seq} 与已确认时间冲突`, event);
    if (event.category === 'approval') this.approval([...(this.events.get(runId)?.values() ?? []), event], false);
    if (event.category === 'message') this.message({seq:event.seq, run_id:runId, created_at:event.created_at, content:event.payload});
    const events = this.events.get(runId) ?? new Map<number, RunEvent>();
    events.set(event.seq, event);
    this.events.set(runId, events);
  }

  delta(runId: string, data: Extract<RunFrame, {event:'delta'}>['data']) {
    if (data.field !== 'content') return;
    const previous = this.messages.get(data.seq);
    const fact = this.eventAt(data.seq);
    if (fact && (fact.runId !== runId || fact.event.category !== 'message')) throw new RunProtocolError('增量 seq 与已确认事件冲突', data);
    if (previous && (previous.run_id !== runId || previous.content.message_id !== data.message_id)) throw new RunProtocolError('增量消息身份冲突', data);
    if (previous && !previous.preview) return;
    const text = typeof previous?.content.content === 'string' ? previous.content.content : '';
    const content: MessageContent = {type:'ai', message_id:data.message_id, content:text + data.value, tool_calls:[]};
    this.messages.set(data.seq, {run_id:runId, seq:data.seq, preview:true, content});
  }
}
