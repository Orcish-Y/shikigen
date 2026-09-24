import { useState } from "react";
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
}: {
  session: Session;
  onSuggestion: (text: string) => void;
}) {
  return (
    <div className="timeline" key={session.id}>
      <div className="message-container">
        {session.messages.length ? (
          <>
            <div className="timeline-caption">示例对话 · 仅用于布局预览</div>
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
                    {message.role === "assistant" && (
                      <span className="badge">示例</span>
                    )}
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
                          示例结果
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
        ) : (
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
        )}
      </div>
    </div>
  );
}

export function Composer({
  draft,
  onChange,
  onCommands,
  shortcut,
}: {
  draft: string;
  onChange: (text: string) => void;
  onCommands: () => void;
  shortcut: string;
}) {
  return (
    <div className="composer-area">
      <div className="composer">
        <textarea
          id="message-draft"
          aria-label="消息草稿"
          placeholder="向 shikigen 发送指令或提问…"
          rows={3}
          value={draft}
          onChange={(event) => onChange(event.target.value)}
        />
        <div className="composer-toolbar">
          <span className="composer-status">
            <span className="status-dot" />
            后端未连接 · 可编辑草稿
          </span>
          <button
            className="primary-button"
            disabled
            title="连接后端后可发送消息"
          >
            发送
            <ArrowUp size={16} />
          </button>
        </div>
      </div>
      <div className="composer-footer">
        <span>草稿仅保留在当前页面</span>
        <button className="text-button" onClick={onCommands}>
          <kbd>{shortcut} K</kbd>命令面板
        </button>
      </div>
    </div>
  );
}
