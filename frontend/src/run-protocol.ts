import type { MessageContent, Run, RunEvent, RunFrame, RunStatus } from './backend-client.ts';

export class RunProtocolError extends Error {
  readonly raw: unknown;
  constructor(message: string, raw: unknown) { super(`运行协议问题：${message}`); this.raw = raw; }
}

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const identity = (value: unknown): value is string => typeof value === 'string' && Boolean(value.trim());
const sequence = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const date = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value));
export const validStatus = (value: unknown): value is RunStatus => typeof value === 'string'
  && ['running', 'interrupted', 'completed', 'cancelled', 'error'].includes(value);
const nullableText = (value: unknown) => value === null || typeof value === 'string';
const optional = (data: ObjectValue, key: string, check: (value: unknown) => boolean) => !Object.hasOwn(data, key) || check(data[key]);
function requireValid(valid: unknown, message: string, raw: unknown): asserts valid {
  if (!valid) throw new RunProtocolError(message, raw);
}

export function validateMessage(value: unknown): asserts value is MessageContent {
  requireValid(object(value), '消息不是对象', value);
  requireValid(identity(value.message_id) && ['human','ai','tool'].includes(String(value.type))
    && (typeof value.content === 'string' || Array.isArray(value.content)
      && value.content.every(item => typeof item === 'string' || object(item))), '消息正文或身份无效', value);
  if (value.type === 'ai') {
    requireValid(Array.isArray(value.tool_calls) && value.tool_calls.every(call =>
      object(call) && identity(call.id) && identity(call.name) && object(call.args)), '工具调用结构无效', value);
    requireValid(optional(value, 'generation_status', status => ['complete','cancelled','error'].includes(String(status))), '无法识别消息生成状态', value);
  }
  if (value.type === 'tool') requireValid(identity(value.tool_call_id) && ['success','error'].includes(String(value.status))
    && optional(value, 'name', nullableText), '工具结果结构无效', value);
}

export function validateRun(value: unknown, threadId: string, runId?: string): asserts value is Run {
  requireValid(object(value) && value.thread_id === threadId && identity(value.run_id)
    && (runId === undefined || value.run_id === runId), '运行身份与请求不一致', value);
  requireValid(validStatus(value.status), '无法识别运行状态', value);
  const count = (item: unknown) => Number.isSafeInteger(item) && Number(item) >= 0;
  requireValid(optional(value, 'usage', usage => usage === null || object(usage)
    && count(usage.total_input) && count(usage.total_output) && count(usage.total_tokens)
    && optional(usage, 'calls', count) && optional(usage, 'by_model', models => object(models)
      && Object.values(models).every(model => object(model) && count(model.input) && count(model.output) && count(model.calls))))
    && optional(value, 'usage_pending', item => item === null || typeof item === 'boolean')
    && ['error','error_code'].every(key => optional(value, key, nullableText))
    && ['created_at','updated_at'].every(key => optional(value, key, date))
    && optional(value, 'completed_at', item => item === null || date(item)), '运行可选字段无效', value);
}

function approval(data: ObjectValue, threadId: string): boolean {
  const payload = data.payload;
  if (!object(payload) || payload.status !== data.event_type || !object(payload.checkpoint)
    || !object(payload.checkpoint.configurable)) return false;
  const coordinate = payload.checkpoint.configurable;
  if (coordinate.thread_id !== threadId || coordinate.checkpoint_ns !== '' || !identity(coordinate.checkpoint_id)) return false;
  if (payload.status === 'required') {
    if (!Array.isArray(payload.interrupts) || !payload.interrupts.length) return false;
    const ids = new Set<string>();
    return payload.interrupts.every(item => {
      if (!object(item) || !identity(item.id) || ids.has(item.id) || typeof item.namespace !== 'string' || !Object.hasOwn(item, 'value')) return false;
      ids.add(item.id); return true;
    });
  }
  if (payload.status === 'resolved') return object(payload.responses) && Object.keys(payload.responses).length > 0
    && Object.entries(payload.responses).every(([id, response]) => identity(id) && object(response)
      && Array.isArray(response.decisions) && response.decisions.length > 0 && response.decisions.every(decision => object(decision)
        && (decision.type === 'approve' && !Object.hasOwn(decision, 'message')
          || decision.type === 'reject' && optional(decision, 'message', nullableText))));
  return payload.status === 'invalidated' && payload.reason === 'run_cancelled'
    && Array.isArray(payload.interrupt_ids) && payload.interrupt_ids.length > 0 && payload.interrupt_ids.every(identity)
    && new Set(payload.interrupt_ids).size === payload.interrupt_ids.length;
}

export function validateEvent(value: unknown, threadId: string): asserts value is RunEvent {
  requireValid(object(value) && sequence(value.seq) && date(value.created_at) && object(value.payload), '事件序号、时间或载荷无效', value);
  if (value.category === 'message') {
    requireValid(value.event_type === 'created', '消息事件类型无效', value);
    try { validateMessage(value.payload); } catch { throw new RunProtocolError('消息事件载荷无效', value); }
  } else if (value.category === 'lifecycle') {
    requireValid(value.event_type === 'status_changed' && validStatus(value.payload.status)
      && ['message','error_code'].every(key => optional(value.payload as ObjectValue, key, nullableText)), '生命周期事件载荷无效', value);
  } else requireValid(value.category === 'approval' && approval(value, threadId), '审批事件载荷或身份无效', value);
}

export function validateFrame(event: string, data: unknown, threadId: string, runId?: string): RunFrame {
  if (event === 'metadata') validateRun(data, threadId, runId);
  else if (event === 'event') validateEvent(data, threadId);
  else if (event === 'delta') requireValid(object(data) && sequence(data.seq) && identity(data.message_id)
    && ['content','reasoning'].includes(String(data.field)) && typeof data.value === 'string', '增量载荷无效', data);
  else requireValid(event === 'error' && object(data) && identity(data.code) && identity(data.message)
    && typeof data.recoverable === 'boolean', '观察错误载荷无效', data);
  return {event, data} as RunFrame;
}
