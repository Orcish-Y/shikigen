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
import { demoSessions, type Session } from "./data/demo";

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
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [sessions, setSessions] = useState<Session[]>(demoSessions);
  const [activeId, setActiveId] = useState(demoSessions[0].id);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [mobilePanel, setMobilePanel] = useState<
    "navigation" | "history" | null
  >(null);
  const [overlay, setOverlay] = useState<"commands" | "details" | null>(null);
  const active = sessions.find((session) => session.id === activeId)!;
  const shortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

  function toggleNavigation() {
    setCollapsed((value) => !value);
  }
  function createSession() {
    const session: Session = {
      id: crypto.randomUUID(),
      title: "新会话",
      group: "今天",
      summary: "尚未开始对话",
      messages: [],
    };
    setSessions((current) => [session, ...current]);
    setActiveId(session.id);
    setQuery("");
    setMobilePanel(null);
    setOverlay(null);
  }
  function updateDraft(value: string) {
    setDrafts((current) => ({ ...current, [activeId]: value }));
  }
  function exportSession() {
    const content =
      `# ${active.title}\n\n> 页面框架预览：仅导出当前已加载的示例消息，不含草稿。\n\n` +
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
  }, []);

  return (
    <IconContext.Provider value={{ weight: "regular", size: 18 }}>
      <div
        className={`app ${collapsed ? "is-collapsed" : ""} ${mobilePanel ? `show-${mobilePanel}` : ""}`}
      >
        <header className="app-bar">
          <div className="brand">
            <img src="/logo.svg" alt="" />
            <strong>shikigen</strong>
            <span className="preview-label">界面预览</span>
          </div>
          <span className="app-connection">
            <span className="status-dot" />
            后端未连接
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
        <div className="workspace">
          {mobilePanel && (
            <button
              className="panel-backdrop"
              aria-label="关闭侧栏"
              onClick={() => setMobilePanel(null)}
            />
          )}
          <Navigation
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
              setActiveId(id);
              setMobilePanel(null);
            }}
            onCreate={createSession}
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
                {active.messages.length ? "示例会话" : "就绪"}
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
            <Conversation
              session={active}
              onSuggestion={(text) => {
                updateDraft(text);
                document.getElementById("message-draft")?.focus();
              }}
            />
            <Composer
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
              <span className="badge">尚无真实运行</span>
              <h3>{active.title}</h3>
              <p>
                当前展示页面框架，连接后端后将在这里显示运行状态、用量与事件。
              </p>
              <dl>
                {["Run ID", "模型", "输入 Token", "输出 Token", "工具调用"].map(
                  (label) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>—</dd>
                    </div>
                  ),
                )}
              </dl>
              <h3>生命周期事件</h3>
              <p>暂无事件</p>
            </div>
          </Overlay>
        )}
      </div>
    </IconContext.Provider>
  );
}
