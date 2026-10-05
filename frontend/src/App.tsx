import { useBackendState } from "./useBackendState";
import { TrayNotice } from "./TrayNotice";
import { BackendLogs } from "./BackendLogs";
import { useEffect, useState } from "react";
import {
  IconContext,
  SidebarSimple,
  ClockCounterClockwise,
  DownloadSimple,
  SlidersHorizontal,
  Terminal,
  Plus,
} from "@phosphor-icons/react";
import { Navigation, History } from "./components/Sidebar";
import { Conversation, Composer } from "./components/Conversation";
import { Overlay } from "./components/Overlay";
import { SendRecovery, DraftCopy } from './components/SendRecovery';
import { ObservationStatus } from './components/ObservationStatus';
import type { BackendSession } from "./backend-client";
import { useConversations } from "./useConversations";
import { useWorkspaceVisibility } from './useWorkspaceVisibility';

function initialCollapsed() {
  try {
    const value = localStorage.getItem("shikigen.navigation-collapsed");
    if (value !== null) return value === "true";
  } catch {
    /* Storage may be disabled in the host. */
  }
  return window.innerWidth < 1440;
}

export default function App() {
  const backend = useBackendState();
  const visible = useWorkspaceVisibility();
  const conversations = useConversations(backend.session, !backend.desktop, visible);
  if (backend.desktop && (backend.error || backend.snapshot?.state !== "ready" || !backend.session)) {
    const state = backend.snapshot;
    const labels = {
      starting: "正在启动后端",
      ready: "后端已就绪",
      stopping: "正在关闭后端",
      reclaiming: "正在回收后端进程",
      failed: "后端启动或运行失败",
      stopped: "后端已停止",
    };
    return (
      <main className="backend-screen" aria-live="polite">
        <TrayNotice />
        <img src="/logo.svg" alt="" width="40" height="40" />
        <h1>{backend.error ? "无法读取后端状态" : labels[state?.state ?? "starting"]}</h1>
        <p>{backend.error ?? state?.error?.message ?? "正在准备运行环境，请稍候。"}</p>
        {state?.state === "failed" && (
          <p>
            {state.error?.code === "reclamation_unconfirmed"
              ? "正在继续确认退出状态，请保持此窗口打开。"
              : state.can_retry
                ? "修正问题后，可以手动重试启动后端。"
                : "正在处理退出，请稍候。"}
          </p>
        )}
        {state?.state === "failed" && (
          <button className="secondary-button" disabled={!state.can_retry || backend.retrying} onClick={() => void backend.retry()}>
            {backend.retrying ? "正在请求重试…" : "重试启动后端"}
          </button>
        )}
        {backend.retryError && <p role="alert">{backend.retryError}</p>}
        {state?.startup_id && state.error && <BackendLogs key={state.startup_id} startupId={state.startup_id} />}
      </main>
    );
  }

  return <Workspace session={backend.session} conversations={conversations} />;
}

function Workspace({ session, conversations }: {
  session: BackendSession | null;
  conversations: ReturnType<typeof useConversations>;
}) {
  const backendReady = Boolean(session);
  const { sessions, active, activeId } = conversations;
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [query, setQuery] = useState("");
  const [mobilePanel, setMobilePanel] = useState<
    "navigation" | "history" | null
  >(null);
  const [overlay, setOverlay] = useState<"commands" | "details" | null>(null);
  const shortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

  function toggleNavigation() {
    setCollapsed((value) => !value);
  }
  function createSession() {
    void conversations.create();
    setQuery("");
    setMobilePanel(null);
    setOverlay(null);
  }
  function updateDraft(value: string) {
    conversations.updateDraft(value);
  }
  function exportSession() {
    const content =
      `# ${active.title}\n\n${session ? "" : "> 页面框架预览：示例消息。\n\n"}` +
      active.messages
        .map(
          (message) =>
            `## ${message.role === "user" ? "用户" : "shikigen Agent"}\n\n${message.text}${message.code ? `\n\n\`\`\`${message.code.language}\n${message.code.content}\n\`\`\`` : ""}${message.tool ? `\n\n工具：${message.tool.name}\n\n${message.tool.command}\n\n${message.tool.output}` : ""}`,
        )
        .join("\n\n");
    const url = URL.createObjectURL(
      new Blob([content], { type: "text/markdown;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${active.title}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  useEffect(() => {
    try {
      localStorage.setItem("shikigen.navigation-collapsed", String(collapsed));
    } catch {
      /* Keep the in-memory preference. */
    }
  }, [collapsed]);
  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        !event.isComposing
      ) {
        if (event.key.toLowerCase() === "k") {
          event.preventDefault();
          setOverlay((value) => (value === "commands" ? null : "commands"));
        }
        if (event.key.toLowerCase() === "n") {
          event.preventDefault();
          createSession();
        }
      }
      if (event.key === "Escape") setMobilePanel(null);
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  });


  return (
    <IconContext.Provider value={{ weight: "regular", size: 18 }}>
      <div
        className={`app ${collapsed ? "is-collapsed" : ""} ${mobilePanel ? `show-${mobilePanel}` : ""}`}
      >
        <header className="app-bar">
          <div className="brand">
            <img src="/logo.svg" alt="" />
            <strong>shikigen</strong>
            {!session && <span className="preview-label">界面预览</span>}
          </div>
          <span className="app-connection">
            <span className="status-dot" />
            {backendReady ? "后端已就绪" : "后端未连接"} · {conversations.observationLabel}
          </span>
          <button
            className="text-button"
            onClick={() => setOverlay("commands")}
            aria-label="打开命令面板"
          >
            <Terminal size={15} />
            <span className="top-command-label">命令面板</span>
            <kbd>{shortcut} K</kbd>
          </button>
        </header>
        <TrayNotice />
        <div className="workspace">
          {mobilePanel && (
            <button
              className="panel-backdrop"
              aria-label="关闭侧栏"
              onClick={() => setMobilePanel(null)}
            />
          )}
          <Navigation
            backendReady={backendReady}
            observationLabel={conversations.observationLabel}
            collapsed={collapsed}
            onToggle={toggleNavigation}
            onCommands={() => setOverlay("commands")}
          />
          <History
            sessions={sessions}
            activeId={activeId}
            query={query}
            onQuery={setQuery}
            onSelect={(id) => {
              conversations.select(id);
              setMobilePanel(null);
            }}
            onCreate={createSession}
            creating={conversations.creating || conversations.loading}
            pagination={conversations.pagination}
          />
          <main className="chat-workspace">
            <div className="chat-toolbar">
              <button
                className="icon-button mobile-navigation"
                aria-label="打开主导航"
                onClick={() => setMobilePanel("navigation")}
              >
                <SidebarSimple />
              </button>
              <button
                className="icon-button history-toggle"
                aria-label="打开会话历史"
                onClick={() => setMobilePanel("history")}
              >
                <ClockCounterClockwise />
              </button>
              <h1 title={activeId ? `${active.title}\n会话 ID：${activeId}` : undefined}>{active.title}</h1>
              <span className="badge toolbar-badge">
                {conversations.statusLabel}
              </span>
              <div className="toolbar-actions">
                <button
                  className="text-button"
                  onClick={exportSession}
                  disabled={!active.messages.length}
                  aria-label="导出当前对话"
                >
                  <DownloadSimple />
                  <span>导出</span>
                </button>
                <button
                  className="secondary-button"
                  onClick={() => setOverlay("details")}
                  aria-label="运行详情"
                >
                  <SlidersHorizontal />
                  <span>运行详情</span>
                </button>
              </div>
            </div>
            {conversations.error && <p className="business-notice" role="alert">{conversations.error}</p>}
            {session && <ObservationStatus view={conversations.observationView} onReconnect={conversations.reconnect} onQuery={conversations.queryStatus} />}
            {conversations.notice && <p className="business-notice" role="status">{conversations.notice}</p>}
            {conversations.sendFailure && conversations.submission?.status !== 'unknown' && <details className="business-notice">
              <summary>发送请求错误详情</summary>
              <pre style={{maxHeight:240, overflow:'auto', whiteSpace:'pre-wrap'}}>{JSON.stringify(conversations.sendFailure, null, 2)}</pre>
            </details>}
            {conversations.verifying && <p className="business-notice" role="status">正在核实当前运行状态…</p>}
            {conversations.approvalStatus && <p id="current-approval-status" tabIndex={-1} className="business-notice" role="status">{conversations.approvalStatus}</p>}
            {conversations.storageIssue && <p className="business-notice" role="alert">{conversations.storageIssue}</p>}
            {conversations.missing && <section className="business-notice" aria-label="会话文字保留">
              <p>会话不存在；草稿和提交原文仍保留，可以复制到新会话后手动发送。</p>
              <DraftCopy text={conversations.draft || conversations.submission?.text || ''}
                onTransfer={() => void conversations.copyDraftToNewConversation()} />
            </section>}
            {conversations.submission?.status === 'unknown' && <SendRecovery key={`${activeId}:${conversations.submission.id}`}
              record={conversations.submission} messages={conversations.submittedUserMessages}
              ready={conversations.canConfirmSend} canStart={conversations.canSendAsNewTask}
              loading={conversations.loading} status={conversations.statusLabel} onQuery={conversations.reload}
              onConfirm={conversations.confirmSend} onNewTask={conversations.sendAsNewTask} />}
            {conversations.protocolIssue && <details className="business-notice">
              <summary>最近协议问题（只读原文）</summary>
              <p>{conversations.protocolIssue.message}</p>
              <pre style={{maxHeight:320, overflow:'auto', whiteSpace:'pre-wrap'}}>{typeof conversations.protocolIssue.raw === 'string'
                ? conversations.protocolIssue.raw : JSON.stringify(conversations.protocolIssue.raw, null, 2)}</pre>
            </details>}
            {session && <button className="text-button" onClick={conversations.reload} disabled={conversations.sending || conversations.loading}>刷新数据</button>}
            <Conversation
              preview={!session}
              session={active}
              readState={activeId ? conversations.historyState : "ready"}
              onSuggestion={(text) => {
                updateDraft(text);
                document.getElementById("message-draft")?.focus();
              }}
            />
            <Composer
              backendReady={backendReady}
              canSend={conversations.canSend}
              sending={conversations.sending}
              onSend={() => {
                conversations.send(conversations.draft);
              }}
              draft={conversations.draft}
              hasConversation={Boolean(activeId)}
              onChange={updateDraft}
              onCommands={() => setOverlay("commands")}
              shortcut={shortcut}
              runStatus={conversations.run?.status}
              storageIssue={conversations.storageIssue}
              sendUnknown={conversations.submission?.status === 'unknown'}
              onApproval={() => {
                const target = document.getElementById('current-approval-status');
                target?.scrollIntoView({block:'nearest'});
                target?.focus();
              }}
            />
          </main>
        </div>
        {overlay === "commands" && (
          <Overlay title="命令面板" onClose={() => setOverlay(null)}>
            <div className="commands">
              <button onClick={createSession}>
                <Plus />
                新建会话<kbd>{shortcut} N</kbd>
              </button>
              <button
                onClick={() => {
                  toggleNavigation();
                  setOverlay(null);
                }}
              >
                <SidebarSimple />
                {collapsed ? "展开" : "收起"}主导航
              </button>
              <button
                onClick={() => {
                  setOverlay(null);
                  setMobilePanel("history");
                  document
                    .querySelector<HTMLInputElement>(".search input")
                    ?.focus();
                }}
              >
                <ClockCounterClockwise />
                查找会话
              </button>
              <button onClick={() => setOverlay("details")}>
                <SlidersHorizontal />
                查看运行详情
              </button>
            </div>
          </Overlay>
        )}
        {overlay === "details" && (
          <Overlay title="运行详情" drawer onClose={() => setOverlay(null)}>
            <div className="details-content">
              <span className="badge">{conversations.statusLabel}</span>
              <h3>{active.title}</h3>
              <dl>
                {[
                  ["会话 ID", activeId || undefined],
                  ["Run ID", conversations.run?.run_id],
                  ["状态", conversations.statusLabel],
                  ["输入 Token", conversations.run?.usage?.total_input],
                  ["输出 Token", conversations.run?.usage?.total_output],
                ].map(([label, value]) => (
                  <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>
                ))}
              </dl>
              {conversations.run?.status === "interrupted" && <p>此运行正在等待审批。</p>}
              {conversations.run?.error && <p role="alert">{conversations.run.error}</p>}
              {conversations.error && <p role="alert">{conversations.error}</p>}

            </div>
          </Overlay>
        )}
      </div>
    </IconContext.Provider>
  );
}
