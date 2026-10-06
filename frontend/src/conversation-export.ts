import type { ConversationMessage } from './run-projection';
import { sameFact } from './run-projection';
import type { Run, RunEvent } from './backend-client';

export type ExportRunOutcome = Pick<Run, 'run_id' | 'status' | 'error' | 'error_code'> & {message?:string | null};
export interface ConversationExportSnapshot {
  threadId:string;
  title:string;
  capturedAt:string;
  messages:ConversationMessage[];
  runOutcomes:ExportRunOutcome[];
}

/** 摘取已知运行摘要；生命周期文案不是 Run.error，审批等事件不进入导出。 */
export function collectExportRunOutcomes(runStatuses:Record<string,Run['status']>,
  runEvents:Record<string,RunEvent[]>, run:Run | null):ExportRunOutcome[] {
  const outcomes = new Map<string,ExportRunOutcome>();
  for (const [runId,status] of Object.entries(runStatuses)) outcomes.set(runId,{run_id:runId,status});
  for (const [runId,events] of Object.entries(runEvents)) {
    for (const event of events) {
      if (event.category !== 'lifecycle' || !['completed','cancelled','error'].includes(event.payload.status)) continue;
      outcomes.set(runId,{run_id:runId,status:event.payload.status,
        ...(Object.hasOwn(event.payload,'message') ? {message:event.payload.message} : {}),
        ...(Object.hasOwn(event.payload,'error_code') ? {error_code:event.payload.error_code} : {})});
    }
  }
  if (run) outcomes.set(run.run_id,{...outcomes.get(run.run_id),run_id:run.run_id,status:run.status,
    ...(Object.hasOwn(run,'error') ? {error:run.error} : {}),
    ...(Object.hasOwn(run,'error_code') ? {error_code:run.error_code} : {})});
  return [...outcomes.values()];
}

/** 只复制当前已加载事实；不持有投影、草稿、事件或资源读取入口。 */
export function captureConversationExport(conversationFacts:{threadId:string; title:string | null;
  messages:readonly ConversationMessage[]; runOutcomes?:readonly ExportRunOutcome[]; capturedAt?:Date;
}):ConversationExportSnapshot {
  const messages = new Map<number, ConversationMessage>();
  for (const message of conversationFacts.messages) {
    if (message.preview || message.category && message.category !== 'message') continue;
    if (!Number.isSafeInteger(message.seq) || message.seq < 1
      || message.thread_id && message.thread_id !== conversationFacts.threadId) throw new Error('导出消息身份或顺序无效');
    const {preview: _isPreview, ...messageRecord} = message;
    const previousMessage = messages.get(message.seq);
    if (previousMessage && !sameFact(previousMessage, messageRecord)) throw new Error(`导出消息 seq=${message.seq} 冲突`);
    messages.set(message.seq, structuredClone(messageRecord));
  }
  const orderedMessages = [...messages.values()].sort((left, right)=>left.seq-right.seq);
  const runIds = new Set(orderedMessages.map(message=>message.run_id));
  return {threadId:conversationFacts.threadId, title:conversationFacts.title?.trim() ? conversationFacts.title : '会话',
    capturedAt:(conversationFacts.capturedAt ?? new Date()).toISOString(), messages:orderedMessages,
    runOutcomes:structuredClone((conversationFacts.runOutcomes ?? []).filter(outcome=>runIds.has(outcome.run_id)))};
}

function escapeMetadata(metadataText:string):string {
  return metadataText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/[\r\n\u0000-\u001f\u007f\u2028\u2029]/g, character=>
      `\\u${character.charCodeAt(0).toString(16).padStart(4,'0')}`)
    .replace(/([\\`*_{}\[\]()#+.!|~-])/g,'\\$1');
}

export function exportFilename(snapshot:Pick<ConversationExportSnapshot,'title' | 'capturedAt'>):string {
  const title = [...snapshot.title.replace(/[<>:"/\\|?*\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g,'_')]
    .slice(0,80).join('').trim().replace(/[. ]+$/g,'');
  return `${title || '会话'}-${snapshot.capturedAt.replace(/[:.]/g,'-')}.md`;
}

function wrapRawBlock(rawText:string, language:'text' | 'markdown' | 'json'):string {
  let longestFence = 0;
  for (const match of rawText.matchAll(/`+/g)) longestFence = Math.max(longestFence,match[0].length);
  const fence = '`'.repeat(Math.max(3,longestFence+1));
  // 此分隔换行属于围栏结构；围栏里的原文不裁剪、不补写。
  return `${fence}${language}\n${rawText}\n${fence}`;
}

function requiresRawMarkdown(markdownBody:string):boolean {
  // HTML、引用定义和嵌套围栏可能跨消息改变后续记录，保守按原文保存。
  if (/<[!/?a-zA-Z]/.test(markdownBody) || /^ {0,3}\[[^\]\n]+\]:/m.test(markdownBody)) return true;
  let openingFence:{marker:string; length:number} | null = null;
  for (const line of markdownBody.split(/\r?\n/)) {
    const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (!match) {
      if (!openingFence && /(?:`{3,}|~{3,})/.test(line)) return true;
      continue;
    }
    if (!openingFence) {
      // 反引号围栏的 info string 不能含反引号，否则末尾看似闭合的行会成为新开头。
      if (match[1][0] === '`' && match[2].includes('`')) return true;
      openingFence = {marker:match[1][0], length:match[1].length};
    }
    else if (match[1][0] === openingFence.marker && match[1].length >= openingFence.length && !match[2].trim()) openingFence = null;
  }
  return openingFence !== null;
}

export function serializeConversationExport(snapshot:ConversationExportSnapshot):string {
  const messages = snapshot.messages;
  if (!messages.length) throw new Error('暂无已提交内容可导出');
  const runIds = [...new Set(messages.map(message=>message.run_id))];
  const sections = [`# ${escapeMetadata(snapshot.title)}`, `会话 ID：${escapeMetadata(snapshot.threadId)}`,
    `导出时间：${escapeMetadata(snapshot.capturedAt)}（UTC）`, `消息数：${messages.length}`,
    `涉及 Run：${runIds.map(escapeMetadata).join(', ')}`,
    `已加载 seq 范围：${messages[0].seq}–${messages.at(-1)!.seq}`,
    `已加载 seq：${messages.map(message=>message.seq).join(', ')}`,
    '范围说明：仅包含点击时已加载的已提交消息；seq 允许空洞，不代表服务端全部历史。未提交预览、草稿、审批选择和运行事件不包含。本地资源仅保留原引用，不打包图片或文件。'];
  if (snapshot.runOutcomes.length) sections.push('## 已知运行状态与中止原因',
    '以下为点击时已知的运行摘要，未提供的原因不推测；不包含运行事件。',
    wrapRawBlock(JSON.stringify(snapshot.runOutcomes,null,2),'json'));
  for (const message of messages) {
    const {content, ...messageFields} = message;
    const {content:body, ...contentFields} = content;
    const role = content.type === 'human' ? '用户' : content.type === 'tool' ? '工具结果' : 'Agent';
    sections.push(`## seq ${message.seq} · ${role}`, '### 记录字段',
      wrapRawBlock(JSON.stringify({...messageFields, content:contentFields},null,2),'json'));
    if (content.type === 'ai') {
      const generationStatus = content.generation_status ?? 'complete';
      sections.push(`生成状态：${escapeMetadata(generationStatus)}${generationStatus === 'cancelled' ? '（因取消中止）'
        : generationStatus === 'error' ? '（因失败中止）' : ''}`);
    }
    if (content.type === 'tool') sections.push(`工具真实状态：${content.status ? escapeMetadata(content.status) : '未提供'}`);
    sections.push('### 正文');
    if (typeof body !== 'string') sections.push(wrapRawBlock(JSON.stringify(body,null,2),'json'));
    else if (content.type !== 'ai') sections.push(wrapRawBlock(body,'text'));
    else if (content.generation_status && content.generation_status !== 'complete' || requiresRawMarkdown(body)) sections.push(wrapRawBlock(body,'markdown'));
    else sections.push(body);
  }
  return sections.join('\n\n')+'\n';
}

/** 发起标准 Blob 下载；浏览器／系统负责保存或取消，不把派发称为已保存。 */
export function downloadConversationExport(snapshot:ConversationExportSnapshot):string {
  const markdown = serializeConversationExport(snapshot);
  const filename = exportFilename(snapshot);
  const url = URL.createObjectURL(new Blob([markdown],{type:'text/markdown;charset=utf-8'}));
  const link = document.createElement('a');
  try {
    link.href = url; link.download = filename; link.hidden = true;
    document.body.append(link); link.click();
  } catch (failure) {
    URL.revokeObjectURL(url);
    throw failure;
  } finally {link.remove();}
  setTimeout(()=>URL.revokeObjectURL(url),60_000);
  return filename;
}
