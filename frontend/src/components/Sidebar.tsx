import {
  ChatCircle,
  Wrench,
  Database,
  GitBranch,
  Pulse,
  SidebarSimple,
  Terminal,
  Gear,
  User,
  Plus,
  MagnifyingGlass,
  Lightning,
} from "@phosphor-icons/react";
import type { Session } from "../data/demo";

export function Navigation({
  collapsed,
  onToggle,
  onCommands,
}: {
  collapsed: boolean;
  onToggle: () => void;
  onCommands: () => void;
}) {
  const items = [
    { icon: ChatCircle, label: "会话与对话" },
    { icon: Wrench, label: "工具与技能编排" },
    { icon: Database, label: "知识库与向量空间" },
    { icon: GitBranch, label: "提示词与评估" },
    { icon: Pulse, label: "运行日志与追踪" },
  ];
  return (
    <aside className="navigation" aria-label="主导航">
      <div className="navigation-heading">
        <span className="nav-label">工作空间</span>
        <button
          className="icon-button"
          onClick={onToggle}
          aria-label={collapsed ? "展开主导航" : "收起主导航"}
          aria-expanded={!collapsed}
        >
          <SidebarSimple size={19} />
        </button>
      </div>
      <nav>
        {items.map(({ icon: Icon, label }, index) => (
          <button
            key={label}
            className={`nav-item ${index === 0 ? "active" : ""}`}
            disabled={index !== 0}
            title={index ? `${label} · 暂未支持` : label}
            aria-label={label}
            aria-current={index === 0 ? "page" : undefined}
          >
            <Icon size={19} />
            <span className="nav-label">{label}</span>
            {index > 0 && <span className="nav-label soon">待开放</span>}
          </button>
        ))}
      </nav>
      <div className="navigation-footer">
        <div className="connection-card">
          <span className="status-dot" />
          <span className="nav-label">后端尚未连接</span>
        </div>
        <button className="nav-item" onClick={onCommands} title="命令面板">
          <Terminal size={19} />
          <span className="nav-label">快捷命令面板</span>
        </button>
        <button className="nav-item" disabled title="系统设置 · 暂未支持">
          <Gear size={19} />
          <span className="nav-label">系统设置</span>
        </button>
        <div className="profile">
          <span className="avatar">
            <User size={17} />
          </span>
          <div className="nav-label">
            <strong>Local Developer</strong>
            <small>个人工作空间</small>
          </div>
        </div>
      </div>
    </aside>
  );
}

export function History({
  sessions,
  activeId,
  query,
  onQuery,
  onSelect,
  onCreate,
}: {
  sessions: Session[];
  activeId: string;
  query: string;
  onQuery: (value: string) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const filtered = sessions.filter((session) =>
    session.title.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <aside className="history" aria-label="会话历史">
      <div className="history-heading">
        <h2>会话历史</h2>
        <button className="secondary-button" onClick={onCreate}>
          <Plus size={14} />
          新建
        </button>
      </div>
      <label className="search">
        <MagnifyingGlass size={16} />
        <input
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="过滤历史会话…"
          aria-label="过滤历史会话"
        />
      </label>
      <nav className="session-list" aria-label="历史会话">
        {(["今天", "昨天"] as const).map((group) => {
          const entries = filtered.filter((session) => session.group === group);
          return (
            entries.length > 0 && (
              <div key={group}>
                <p className="group-label">
                  {group} / {group === "今天" ? "Today" : "Yesterday"}
                </p>
                {entries.map((session) => (
                  <button
                    className={`session ${activeId === session.id ? "selected" : ""}`}
                    key={session.id}
                    onClick={() => onSelect(session.id)}
                    aria-current={activeId === session.id ? "true" : undefined}
                  >
                    <strong>{session.title}</strong>
                    <span>{session.summary}</span>
                  </button>
                ))}
              </div>
            )
          );
        })}
        {filtered.length === 0 && (
          <div className="no-results">
            <p>没有匹配的会话</p>
            <button className="text-button" onClick={() => onQuery("")}>
              清除过滤
            </button>
          </div>
        )}
      </nav>
      <div className="usage">
        <span>
          <Lightning size={15} />
          当前 Run 用量
        </span>
        <p>暂无用量数据</p>
        <small>运行用量将在连接后展示</small>
      </div>
    </aside>
  );
}
