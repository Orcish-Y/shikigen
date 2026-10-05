import { useImperativeHandle, useRef, useState, type Ref } from "react";
import { composerEnter } from '../composer-keyboard';
import type { RunStatus } from '../backend-client';
import {
  ArrowUp,
  ArrowDown,
  ChatCircle,
} from "@phosphor-icons/react";
import type { Session } from "../data/demo";
import { MessageBody, type ContentView } from './MessageBody';
import { ContentBlock } from './ContentViewer';
import { toolRows } from '../tool-records';
import { ToolCard } from './ToolCard';
import { ToolCardPreferences } from '../tool-card-preferences';
import { ChatReadingPositions } from '../chat-reading-position';
import { useChatReading } from '../useChatReading';

export interface ConversationHandle { remember:() => void; locateApproval:() => void }

export function Conversation({
  session,
  onSuggestion,
  preview = false,
  readState = "ready",
  onView,
  toolPreferences,
  readingPositions,
  factsReady = readState === 'ready',
  visible = true,
  acceptedSendId = null,
  approvalStatus,
  approvalIdentity,
  onCancel,
  canCancel = false,
  ref,
}: {
  session: Session;
  onSuggestion: (text: string) => void;
  preview?: boolean;
  readState?: "idle" | "loading" | "ready" | "error";
  onView:(view:ContentView) => void;
  toolPreferences?:ToolCardPreferences;
  readingPositions?:ChatReadingPositions;
  factsReady?:boolean;
  visible?:boolean;
  acceptedSendId?:string | null;
  approvalStatus?:string | null;
  approvalIdentity?:string;
  onCancel?:() => void;
  canCancel?:boolean;
  ref?:Ref<ConversationHandle>;
}) {
  const [localPreferences] = useState(() => new ToolCardPreferences());
  const [localReading] = useState(() => new ChatReadingPositions());
  const reading = useChatReading(session, readingPositions ?? localReading, factsReady, visible, acceptedSendId);
  useImperativeHandle(ref, () => ({remember:reading.remember, locateApproval:() => {
    const target = reading.timeline.current?.querySelector<HTMLElement>('#current-approval-status');
    if (target) reading.locate(target);
  }}));
  return (
    <div className="conversation-timeline">
    <div className="timeline" key={session.id} ref={reading.timeline} tabIndex={0} aria-label="聊天消息">
      <div className="message-container">
        {(readState === "loading" || readState === "idle") && <p className="timeline-caption" role="status">正在读取会话历史…</p>}
        {readState === "error" && <p className="business-notice" role="alert">会话历史读取失败，请刷新重试。已有记录已保留。</p>}
        {session.messages.length ? (
          <>
            {preview && <div className="timeline-caption">示例对话 · 仅用于布局预览</div>}
            {toolRows(session).map(({message, tools}) => (
              <article className={`message ${message.role}`} key={message.id} data-reading-anchor={`message:${message.id}`}>
                <div
                  className={`avatar ${message.role === "assistant" ? "agent-avatar" : ""}`}
                >
                  {message.role === "user" ? (
                    "ME"
                  ) : (
                    <img src="/logo.svg" alt="" />
                  )}
                </div>
                <div className="message-body">
                  <div className="message-heading">
                    <strong>
                      {message.role === "user"
                        ? "Local Developer"
                        : message.role === 'tool' ? '工具结果' : "shikigen Agent"}
                    </strong>
                    {preview && message.role === "assistant" && (
                      <span className="badge">示例</span>
                    )}
                    {message.preview && <span className="badge">{['cancelled','completed','error'].includes(session.runStatuses?.[message.record?.run_id ?? ''] ?? '')
                      ? '预览 · 尚未读取保存事实' : '生成中 · 尚未保存'}</span>}
                    {!message.preview && message.record?.content.type === 'ai'
                      && ['cancelled','error'].includes(message.record.content.generation_status ?? '')
                      && <span className={`badge generation-${message.record.content.generation_status}`}>{message.record.content.generation_status === 'error' ? '因失败中止' : '因取消中止'}</span>}
                  </div>
                  {message.role !== 'tool' && <MessageBody role={message.role} content={message.content ?? message.text}
                    identity={`${session.id}:${message.id}`} preview={message.preview}
                    generating={message.preview && !['cancelled','completed','error'].includes(session.runStatuses?.[message.record?.run_id ?? ''] ?? '')} onView={onView} />}
                  {tools.map(record => <ToolCard key={record.identity} record={record} preferences={toolPreferences ?? localPreferences} onView={onView} />)}
                  {message.code && <ContentBlock title={`${message.code.filename} · ${message.code.language}`}
                    text={message.code.content} onView={onView} />}
                </div>
              </article>
            ))}
          </>
        ) : readState === "ready" ? (
          <div className="empty-conversation">
            <img src="/logo.svg" alt="" />
            <h2>从一个想法开始</h2>
            <p>向 shikigen 描述你想完成的任务。</p>
            <div className="suggestions">
              {[
                "解释当前项目的目录结构",
                "搜索项目中的工具注册逻辑",
                "总结一个指定网页的内容",
              ].map((text) => (
                <button key={text} onClick={() => onSuggestion(text)}>
                  <ChatCircle size={17} />
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {approvalStatus && <section id="current-approval-status" data-reading-anchor={`approval:${approvalIdentity}`}
          tabIndex={-1} className="business-notice" aria-label="当前审批">
          <p role="status">{approvalStatus}</p>
          <button className="secondary-button" disabled={!canCancel} onClick={onCancel}>取消运行</button>
        </section>}
      </div>
    </div>
    {!reading.following && <div className="reading-controls">
      {reading.hasNewContent && <span role="status">有新内容</span>}
      <button className="secondary-button" onClick={reading.latest}><ArrowDown size={15} />回到最新</button>
    </div>}
    </div>
  );
}

export function Composer({
  backendReady,
  draft,
  onChange,
  onCommands,
  shortcut,
  canSend = false,
  sending = false,
  onSend,
  hasConversation = true,
  runStatus,
  onApproval,
  storageIssue,
  sendUnknown = false,
  onCancel,
  canCancel = false,
  writePending = false,
}: {
  backendReady: boolean;
  draft: string;
  onChange: (text: string) => void;
  onCommands: () => void;
  shortcut: string;
  canSend?: boolean;
  sending?: boolean;
  onSend: () => void;
  hasConversation?: boolean;
  runStatus?: RunStatus;
  onApproval?: () => void;
  storageIssue?: string | null;
  sendUnknown?: boolean;
  onCancel?:() => void;
  canCancel?:boolean;
  writePending?:boolean;
}) {
  const composition = useRef({active:false, endedAt:-Infinity});
  return (
    <div className="composer-area">
      <div className="composer">
        <textarea
          id="message-draft"
          aria-label="消息草稿"
          placeholder={hasConversation ? "向 shikigen 发送指令或提问…" : "请先新建或选择会话"}
          disabled={!hasConversation}
          rows={3}
          value={draft}
          onChange={(event) => onChange(event.target.value)}
          onCompositionStart={() => { composition.current.active = true; }}
          onCompositionEnd={event => { composition.current = {active:false, endedAt:event.timeStamp}; }}
          onKeyDown={event => composerEnter(event.nativeEvent, canSend && Boolean(draft.trim()), onSend,
            composition.current.active, composition.current.endedAt)}
        />
        <div className="composer-toolbar">
          <span className="composer-status">
            <span className="status-dot" />
            {backendReady ? "后端已就绪" : "后端未连接"} · 可编辑草稿
          </span>
          {runStatus === 'interrupted' ? <button className="primary-button" disabled={writePending} onClick={onApproval}>处理审批</button>
            : runStatus === 'running' ? <button className="primary-button" disabled={!canCancel} onClick={onCancel}>{writePending ? '确认取消中…' : '取消运行'}</button>
            : <button
            className="primary-button"
            disabled={!canSend || !draft.trim()}
            onClick={onSend}
          >
            {sending ? "确认发送中…" : "发送"}
            <ArrowUp size={16} />
          </button>}
        </div>
      </div>
      <div className="composer-footer">
        <span role="status" aria-live="polite" aria-atomic="true">{sending ? '确认发送中，可继续编辑草稿'
          : sendUnknown ? '发送结果待确认，请核对已提交消息；可编辑草稿'
          : storageIssue ? '草稿仅在本次应用中保留' : runStatus === 'running' || runStatus === 'interrupted'
          ? '可编辑草稿，运行结束后手动发送' : '草稿在本地保存，重启后保留'}</span>
        <button className="text-button" onClick={onCommands}>
          <kbd>{shortcut} K</kbd>命令面板
        </button>
      </div>
    </div>
  );
}
