import type { DraftStorage } from './message-drafts.ts';
import type { ConversationMessage } from './run-projection.ts';

const STORAGE_KEY = 'shikigen.conversation-titles.v1';
const STORAGE_WARNING = '本地标题保存不可用；标题暂存于本次应用内。';
interface TemporaryTitle {
  runId: string;
  seq: number;
  messageId: string;
  title: string;
}

export function displayConversationTitle(serverTitle?: string | null, temporaryTitle?: string) {
  return serverTitle?.trim() ? serverTitle : temporaryTitle || '新会话';
}

/** Only explicit text from the first committed human message supplies a title. */
function deriveTemporaryTitle(messages: ConversationMessage[]): TemporaryTitle | null {
  const firstUserMessage = messages.filter(message => !message.preview && message.content.type === 'human')
    .sort((left, right) => left.seq - right.seq)[0];
  if (!firstUserMessage) return null;
  const body = firstUserMessage.content.content;
  const text = typeof body === 'string' ? body : body.flatMap(block => {
    if (typeof block === 'string') return [block];
    return block.type === 'text' && typeof block.text === 'string' ? [block.text] : [];
  }).join('\n');
  const singleLine = text.replace(/\s+/gu, ' ').trim();
  if (!singleLine) return null;
  const graphemes = [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(singleLine)]
    .map(segment => segment.segment);
  const title = graphemes.length > 48 ? `${graphemes.slice(0, 48).join('')}…` : singleLine;
  return {runId:firstUserMessage.run_id, seq:firstUserMessage.seq,
    messageId:firstUserMessage.content.message_id, title};
}

/** A display cache; never evidence of run acceptance or a backend title write. */
export class ConversationTitles {
  private titles: Record<string, TemporaryTitle> = {};
  private storage: DraftStorage | null = null;
  storageIssue: string | null = null;

  constructor(storage?: DraftStorage | null) {
    try {
      this.storage = storage === undefined ? globalThis.localStorage ?? null : storage;
      if (!this.storage) { this.storageIssue = STORAGE_WARNING; return; }
      const raw = this.storage.getItem(STORAGE_KEY);
      if (!raw) return;
      const cache = JSON.parse(raw);
      if (cache.schema !== 1 || !Array.isArray(cache.titles)) throw new Error('标题缓存格式无效');
      this.titles = Object.fromEntries(cache.titles.map((entry: unknown) => {
        if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string' || !entry[0])
          throw new Error('标题缓存身份无效');
        const source = entry[1];
        if (!source || typeof source.runId !== 'string' || !source.runId
          || !Number.isSafeInteger(source.seq) || source.seq < 1
          || typeof source.messageId !== 'string' || !source.messageId
          || typeof source.title !== 'string' || !source.title.trim()) throw new Error('标题来源无效');
        return [entry[0], {runId:source.runId, seq:source.seq, messageId:source.messageId, title:source.title}];
      }));
    } catch {
      this.storage = null;
      this.storageIssue = STORAGE_WARNING;
    }
  }

  getSnapshot(): Record<string, string> {
    return Object.fromEntries(Object.entries(this.titles).map(([threadId, source]) => [threadId, source.title]));
  }

  reconcileHistory(threadId: string, messages: ConversationMessage[]) {
    this.saveTitle(threadId, deriveTemporaryTitle(messages));
  }

  observeMessages(threadId: string, messages: ConversationMessage[]) {
    const source = deriveTemporaryTitle(messages);
    const previous = Object.hasOwn(this.titles, threadId) ? this.titles[threadId] : null;
    // An SSE or per-run read can omit earlier history. It cannot erase/replace an earlier source.
    if (source && (!previous || source.seq <= previous.seq)) this.saveTitle(threadId, source);
  }

  private saveTitle(threadId: string, source: TemporaryTitle | null) {
    const previous = Object.hasOwn(this.titles, threadId) ? this.titles[threadId] : null;
    if (JSON.stringify(previous) === JSON.stringify(source)) return;
    this.titles = {...this.titles};
    if (source) this.titles[threadId] = source;
    else delete this.titles[threadId];
    if (!this.storage) return;
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify({schema:1, titles:Object.entries(this.titles)}));
    } catch {
      this.storage = null;
      this.storageIssue = STORAGE_WARNING;
    }
  }
}

export function appendTaskExample(draft: string, example: string) {
  return draft.length === 0 ? example : `${draft}\n\n${example}`;
}
