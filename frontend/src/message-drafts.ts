/** 只持久保存输入与提交线索。后端地址、连接及运行事实由应用重新查询。 */
export interface DraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}
export interface MessageDraft { text: string; version: number }
export interface MessageSubmission {
  id: string; text: string; version: number; previousRunId: string | null;
  status: 'pending' | 'unknown' | 'accepted'; runId: string | null;
  error: string | null; retryAt: number;
}
const STORAGE_KEY = 'shikigen.message-drafts.v1';
const STORAGE_WARNING = '本地保存不可用；文字暂存于本次应用内，请及时复制。';

export class MessageDrafts {
  drafts: Record<string, MessageDraft> = {};
  submissions: Record<string, MessageSubmission> = {};
  selected = '';
  storageIssue: string | null = null;
  private storage: DraftStorage | null;

  constructor(storage?: DraftStorage | null) {
    try {
      this.storage = storage === undefined ? globalThis.localStorage ?? null : storage;
      if (!this.storage) { this.storageIssue = STORAGE_WARNING; return; }
      const raw = this.storage?.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved.schema !== 1 || typeof saved.selected !== 'string' || !Array.isArray(saved.drafts)) throw new Error('草稿格式无效');
      const entries: [string, MessageDraft][] = saved.drafts.map((entry: unknown) => {
        if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string' || !entry[0]
          || typeof entry[1]?.text !== 'string' || !Number.isSafeInteger(entry[1]?.version) || entry[1].version < 0) throw new Error('草稿字段无效');
        return [entry[0], {text:entry[1].text, version:entry[1].version}];
      });
      this.drafts = Object.fromEntries(entries);
      if (!Array.isArray(saved.submissions)) throw new Error('提交线索格式无效');
      this.submissions = Object.fromEntries(saved.submissions.map((entry: unknown) => {
        if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string' || !entry[0]) throw new Error('提交线索身份无效');
        const value = entry[1];
        if (!value || typeof value.id !== 'string' || !value.id || typeof value.text !== 'string'
          || !Number.isSafeInteger(value.version) || value.version < 0
          || !['pending','unknown','accepted'].includes(value.status)
          || !(value.previousRunId === null || typeof value.previousRunId === 'string')
          || !(value.error === null || typeof value.error === 'string')
          || !Number.isFinite(value.retryAt) || value.retryAt < 0
          || !(value.runId === null || typeof value.runId === 'string' && value.runId)
          || value.status === 'accepted' && !value.runId) throw new Error('提交线索字段无效');
        return [entry[0], {id:value.id, text:value.text, version:value.version, previousRunId:value.previousRunId,
          status:value.status === 'pending' ? 'unknown' : value.status, runId:value.runId,
          error:value.status === 'pending' ? '应用重开，旧请求的接受情况待核实。' : value.error, retryAt:value.retryAt}];
      }));
      this.selected = saved.selected;
    } catch {
      this.storage = null;
      this.storageIssue = STORAGE_WARNING;
    }
  }

  get(threadId: string): MessageDraft {
    return Object.hasOwn(this.drafts, threadId) ? this.drafts[threadId] : {text:'', version:0};
  }

  update(threadId: string, text: string) {
    if (this.get(threadId).text === text) return;
    this.drafts = {...this.drafts, [threadId]:{text, version:this.get(threadId).version + 1}};
    this.save();
  }

  select(threadId: string) { this.selected = threadId; this.save(); }

  begin(threadId: string, text: string, previousRunId: string | null, version = this.get(threadId).version) {
    const submission: MessageSubmission = {id:crypto.randomUUID(), text, version, previousRunId,
      status:'pending', runId:null, error:null, retryAt:0};
    this.submissions = {...this.submissions, [threadId]:submission};
    this.save();
    return submission;
  }

  markSubmissionUnknown(threadId: string, error: string, retryAt = 0) {
    const record = this.submissions[threadId];
    if (record?.status !== 'pending') return;
    this.submissions = {...this.submissions, [threadId]:{...record, status:'unknown', error, retryAt}};
    this.save();
  }

  accept(threadId: string, id: string, runId: string) {
    const record = this.submissions[threadId];
    if (!record || record.id !== id || record.status !== 'pending') return;
    this.clearSubmittedDraft(threadId, record);
    this.submissions = {...this.submissions, [threadId]:{...record, status:'accepted', runId, error:null, retryAt:0}};
    this.save();
  }

  confirm(threadId: string) {
    const record = this.submissions[threadId];
    if (record?.status !== 'unknown') return;
    this.clearSubmittedDraft(threadId, record);
    const submissions = {...this.submissions};
    delete submissions[threadId];
    this.submissions = submissions;
    this.save();
  }

  rejected(threadId: string) {
    if (this.submissions[threadId]?.status !== 'pending') return;
    const submissions = {...this.submissions};
    delete submissions[threadId];
    this.submissions = submissions;
    this.save();
  }

  private clearSubmittedDraft(threadId: string, record: MessageSubmission) {
    const draft = this.get(threadId);
    if (draft.version === record.version && draft.text === record.text) this.update(threadId, '');
  }

  private save() {
    if (!this.storage) return;
    try {
      this.storage.setItem(STORAGE_KEY, JSON.stringify({schema:1, selected:this.selected,
        drafts:Object.entries(this.drafts), submissions:Object.entries(this.submissions)}));
    } catch {
      this.storage = null;
      this.storageIssue = STORAGE_WARNING;
    }
  }
}
