import { useBackendState } from "./useBackendState";
import { TrayNotice } from "./TrayNotice";
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
import type { BackendSession } from "./backend-client";
import { useConversations } from "./useConversations";

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
      </main>
    );
  }

  return <Workspace key={backend.session?.startupId ?? "preview"} session={backend.session} />;
}

function Workspace({ session }: { session: BackendSession | null }) {
  const backendReady = Boolean(session);
  const conversations = useConversations(session);
  const { sessions, active, activeId } = conversations;
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
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
    setDrafts((current) => ({ ...current, [activeId]: value }));
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
            {backendReady ? "后端已就绪" : "后端未连接"}
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
              <h1>{active.title}</h1>
              <span className="badge toolbar-badge">
                {session ? conversations.run?.status ?? (conversations.loading ? "读取中" : "就绪") : "示例会话"}
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
            {session && <button className="text-button" onClick={conversations.reload} disabled={conversations.sending || conversations.loading}>刷新数据</button>}
            <Conversation
              preview={!session}
              session={active}
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
                const text = drafts[activeId]?.trim();
                if (text && conversations.send(text)) updateDraft("");
              }}
              draft={drafts[activeId] ?? ""}
              onChange={updateDraft}
              onCommands={() => setOverlay("commands")}
              shortcut={shortcut}
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
              <span className="badge">{conversations.run?.status ?? "尚无真实运行"}</span>
              <h3>{active.title}</h3>
              <dl>
                {[
                  ["Run ID", conversations.run?.run_id],
                  ["状态", conversations.run?.status],
                  ["输入 Token", conversations.run?.usage?.total_input],
                  ["输出 Token", conversations.run?.usage?.total_output],
                ].map(([label, value]) => (
                  <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>
                ))}
              </dl>
              {conversations.run?.status === "interrupted" && <p>此运行正在等待审批。</p>}
              {conversations.error && <p role="alert">{conversations.error}</p>}

            </div>
          </Overlay>
        )}
      </div>
    </IconContext.Provider>
  );
}
