import type { ConversationMessage } from './run-projection';
import type { Message } from './data/demo';

/** 展示适配只增加角色和检索文字，完整事实仍保留在 record 中。 */
export function presentMessage(record: ConversationMessage): Message {
  const content = record.content;
  return {
    id: JSON.stringify([record.run_id, record.seq, content.message_id]),
    preview: record.preview === true,
    role: content.type === 'human' ? 'user' : content.type === 'tool' ? 'tool' : 'assistant',
    content: content.content,
    text: typeof content.content === 'string' ? content.content : JSON.stringify(content.content, null, 2),
    record,
  };
}
