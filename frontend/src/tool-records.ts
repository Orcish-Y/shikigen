import type { Message, Session } from './data/demo';
import type { MessageContent, RunStatus } from './backend-client';

type ToolCall = NonNullable<MessageContent['tool_calls']>[number];
export interface ToolRecord {
  identity: string;
  call?: { message: Message; value: ToolCall; index: number };
  result?: Message;
  runStatus?: RunStatus;
}
export interface ToolRow { message: Message; tools: ToolRecord[] }

const scope = (session: Session, message: Message, id: string) =>
  JSON.stringify([message.record?.thread_id ?? session.id, message.record?.run_id, id]);
const identity = (session: Session, message: Message, index?: number) =>
  JSON.stringify([session.id, message.record?.thread_id ?? session.id, message.record?.run_id,
    message.record?.seq, message.record?.content.message_id, index]);

/** 仅移动展示位置，不改写事实。调用和结果都唯一时才合并，不依赖到达顺序。 */
export function toolRows(session: Session): ToolRow[] {
  const calls = new Map<string, NonNullable<ToolRecord['call']>[]>();
  const results = new Map<string, Message[]>();
  for (const message of session.messages) {
    if (!message.record || message.preview) continue;
    const content = message.record.content;
    if (content.type === 'ai') content.tool_calls?.forEach((value, index) => {
      const key = scope(session, message, value.id);
      calls.set(key, [...(calls.get(key) ?? []), { message, value, index }]);
    });
    if (content.type === 'tool' && content.tool_call_id) {
      const key = scope(session, message, content.tool_call_id);
      results.set(key, [...(results.get(key) ?? []), message]);
    }
  }
  const paired = new Map<Message, Message>();
  for (const [key, group] of calls) {
    const found = results.get(key);
    if (group.length === 1 && found?.length === 1) paired.set(found[0], group[0].message);
  }
  const status = (message: Message) => session.runStatuses?.[message.record!.run_id] ?? message.record?.run_status;
  return session.messages.flatMap<ToolRow>(message => {
    if (paired.has(message)) return [];
    if (message.role === 'tool') return [{ message, tools: [{ identity: identity(session, message), result: message, runStatus: status(message) }] }];
    const tools = !message.preview && message.record?.content.type === 'ai' ? (message.record.content.tool_calls ?? []).map((value, index) => {
      const key = scope(session, message, value.id);
      const result = calls.get(key)?.length === 1 && results.get(key)?.length === 1 ? results.get(key)![0] : undefined;
      return { identity: identity(session, message, index), call: { message, value, index }, result, runStatus: status(message) };
    }) : [];
    return [{ message, tools }];
  });
}
