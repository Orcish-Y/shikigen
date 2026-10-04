import { useState } from 'react';
import type { MessageSubmission } from '../message-drafts';
import type { ConversationMessage } from '../conversation-state';
import { Overlay } from './Overlay';

export function DraftCopy({text, onTransfer}: {text:string; onTransfer:() => void}) {
  const [copied, setCopied] = useState('复制文字');
  return <div>
    <button className="text-button" onClick={() => {
      void navigator.clipboard.writeText(text).then(() => setCopied('已复制'), () => setCopied('复制失败，请手动选择文字'));
    }}>{copied}</button>
    <button className="text-button" onClick={onTransfer}>复制到新会话</button>
  </div>;
}

export function SendRecovery({record, messages, ready, canStart, loading, status, onQuery, onConfirm, onNewTask}: {
  record:MessageSubmission; messages:ConversationMessage[]; ready:boolean; canStart:boolean;
  loading:boolean; status:string; onQuery:() => void; onConfirm:(seq:number, id:string) => boolean;
  onNewTask:(id:string) => boolean;
}) {
  const [selected, setSelected] = useState('');
  const [confirmNew, setConfirmNew] = useState(false);
  return <section className="business-notice" aria-label="发送结果核对" style={{maxHeight:'40vh', overflow:'auto', flexShrink:0}}>
    <strong>发送结果待确认</strong>
    <p>{record.error} 查询未发现新消息也不能证明此前请求未执行。</p>
    <details>
      <summary>查看本次提交原文</summary>
      <pre style={{whiteSpace:'pre-wrap', maxHeight:320, overflow:'auto'}}>{record.text}</pre>
    </details>
    <p>当前会话：{status}。请核对已提交用户消息及所属运行，再确认对应记录。</p>
    <label>已提交用户消息
      <select style={{maxWidth:'100%'}} value={selected} onChange={event => setSelected(event.target.value)} disabled={!ready}>
        <option value="">请选择对应消息</option>
        {[...messages].reverse().map(message => <option key={message.seq} value={message.seq}>
          #{message.seq} · {message.run_id} · {typeof message.content.content === 'string'
            ? message.content.content.slice(0, 100) : '内容块（选择后查看原文）'}
        </option>)}
      </select>
    </label>
    {selected && messages.filter(message => String(message.seq) === selected).map(message => <pre key={message.seq}
      style={{whiteSpace:'pre-wrap', maxHeight:320, overflow:'auto'}}>{typeof message.content.content === 'string'
        ? message.content.content : JSON.stringify(message.content.content, null, 2)}</pre>)}
    <div>
      <button className="text-button" disabled={loading} onClick={onQuery}>查询状态</button>
      <button className="text-button" disabled={!ready || !selected} onClick={() => onConfirm(Number(selected), record.id)}>
        确认此消息对应本次发送
      </button>
      <button className="text-button" disabled={!canStart} onClick={() => setConfirmNew(true)}>作为新任务发送</button>
    </div>
    {record.retryAt > Date.now() && <p>请在 {new Date(record.retryAt).toLocaleString()} 后查询并核实，再发起新任务。</p>}
    {confirmNew && <Overlay title="作为新任务发送？" onClose={() => setConfirmNew(false)}>
      <div className="details-content">
        <p>这将用本次提交原文创建新任务。此前请求仍可能生效，可能造成重复执行。当前草稿中的新文字会保留。</p>
        <pre style={{whiteSpace:'pre-wrap', maxHeight:320, overflow:'auto'}}>{record.text}</pre>
        <button className="secondary-button" autoFocus onClick={() => setConfirmNew(false)}>返回核对</button>
        <button className="primary-button" disabled={!canStart} onClick={() => {
          if (onNewTask(record.id)) setConfirmNew(false);
        }}>确认发起新任务</button>
      </div>
    </Overlay>}
  </section>;
}
