import { useRef, useState } from "react";
import { composerEnter } from '../composer-keyboard';
import type { RunStatus } from '../backend-client';
import {
  ArrowUp,
  Copy,
  FileCode,
  Terminal,
  Check,
  ChatCircle,
} from "@phosphor-icons/react";
import type { Message, Session } from "../data/demo";

function CodeBlock({ code }: { code: NonNullable<Message["code"]> }) {
  const [copyState, setCopyState] = useState("复制");
  async function copy() {
    try {
      await navigator.clipboard.writeText(code.content);
      setCopyState("已复制");
    } catch {
      setCopyState("复制失败，请手动选择");
    }
  }
  return (
    <div className="code-block">
      <div className="block-heading">
        <span>
          <FileCode size={16} />
          {code.filename}
        </span>
        <button className="text-button" onClick={copy}>
          <Copy size={14} />
          {copyState}
        </button>
      </div>
      <pre aria-label={code.language}>
        <code>
          {code.content.split("\n").map((line, i) => (
            <span className="code-line" key={i}>
              <span className="line-number" aria-hidden="true">
                {i + 1}
              </span>
              {line || " "}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}

export function Conversation({
  session,
  onSuggestion,
  preview = false,
  readState = "ready",
}: {
  session: Session;
  onSuggestion: (text: string) => void;
  preview?: boolean;
  readState?: "idle" | "loading" | "ready" | "error";
}) {
  return (
    <div className="timeline" key={session.id}>
      <div className="message-container">
        {(readState === "loading" || readState === "idle") && <p className="timeline-caption" role="status">正在读取会话历史…</p>}
        {readState === "error" && <p className="business-notice" role="alert">会话历史读取失败，请刷新重试。已有记录已保留。</p>}
        {session.messages.length ? (
          <>
            {preview && <div className="timeline-caption">示例对话 · 仅用于布局预览</div>}
            {session.messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
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
                        : "shikigen Agent"}
                    </strong>
                    {preview && message.role === "assistant" && (
                      <span className="badge">示例</span>
                    )}
                    {message.preview && <span className="badge">生成中 · 尚未保存</span>}
                  </div>
                  <div className="message-text">
                    {message.text.split("\n\n").map((paragraph, index) => (
                      <p key={index}>{paragraph}</p>
                    ))}
                  </div>
                  {message.code && <CodeBlock code={message.code} />}
                  {message.tool && (
                    <details className="tool-block" open>
                      <summary>
                        <Terminal size={17} />
                        <strong>{message.tool.name}</strong>
                        <span className="success">
                          <Check size={12} />
                          {preview ? "示例结果" : message.tool.status === "error" ? "工具失败" : "工具结果"}
                        </span>
                      </summary>
                      <div className="tool-content">
                        <code>{message.tool.command}</code>
                        <p>{message.tool.output}</p>
                      </div>
                    </details>
                  )}
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
      </div>
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
          {runStatus === 'interrupted' ? <button className="primary-button" onClick={onApproval}>处理审批</button>
            : runStatus === 'running' ? <button className="primary-button" disabled title="取消操作暂不可用">取消运行</button>
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
