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
  DotsThree,
} from "@phosphor-icons/react";
import type { Session } from "../data/demo";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ListFailure } from "../conversation-state";

interface HistoryPagination {
  loaded: boolean;
  refreshing: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  listError: ListFailure | null;
  pageError: ListFailure | null;
  onMore: (retry?: boolean) => Promise<void>;
  onReload: () => Promise<void>;
}

function useRetrySeconds(retryAt: number) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    setNow(Date.now());
    if (retryAt <= Date.now()) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= retryAt) window.clearInterval(timer);
    }, 250);
    return () => window.clearInterval(timer);
  }, [retryAt]);
  return Math.max(0, Math.ceil((retryAt - now) / 1000));
}

function ListError({ failure, onRetry, onReload }: {
  failure: ListFailure; onRetry: () => void; onReload: () => void;
}) {
  const seconds = useRetrySeconds(failure.retryAt);
  return <div className="list-error" role="alert">
    <p>{failure.invalidCursor ? "分页位置已失效，请重新加载会话列表。" : failure.message}</p>
    {seconds > 0 && <p>{seconds} 秒后可重试</p>}
    <button className="text-button" disabled={seconds > 0}
      onClick={failure.invalidCursor ? onReload : onRetry}>
      {failure.invalidCursor ? "重新加载会话列表" : "重试"}
    </button>
  </div>;
}

export function Navigation({
  backendReady,
  observationLabel,
  collapsed,
  onToggle,
  onCommands,
}: {
  backendReady: boolean;
  observationLabel: string;
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
        <div className="connection-card" title={`${backendReady ? '后端已就绪' : '后端尚未连接'} · ${observationLabel}`}>
          <span className="status-dot" />
          <span className="nav-label">{backendReady ? "后端已就绪" : "后端尚未连接"}<br />{observationLabel}</span>
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
  creating = false,
  pagination,
  usageSummary,
  onInspect,
}: {
  sessions: Session[];
  activeId: string;
  query: string;
  onQuery: (value: string) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  creating?: boolean;
  pagination?: HistoryPagination;
  usageSummary?:ReactNode;
  onInspect:(id:string) => void;
}) {
  const list = useRef<HTMLElement>(null);
  const wheelGesture = useRef(false);
  const wheelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touchY = useRef<number | null>(null);
  const scrollTop = useRef(0);
  const hasFilter = query.length > 0;
  const { onMore, loadingMore, refreshing, loaded, hasMore, listError, pageError } = pagination ?? {};
  const retrySeconds = useRetrySeconds(Math.max(listError?.retryAt ?? 0, pageError?.retryAt ?? 0));
  const canLoad = Boolean(loaded && hasMore && !loadingMore && !refreshing && !listError && !pageError);
  const atBottom = () => {
    const element = list.current;
    return Boolean(element && element.scrollTop + element.clientHeight >= element.scrollHeight - 2);
  };
  const loadNext = () => { if (canLoad) void onMore?.(); };
  useEffect(() => {
    const element = list.current;
    if (!element || hasFilter || !canLoad) return;
    const fill = () => {
      if (element.clientHeight > 0 && element.scrollHeight <= element.clientHeight + 2) void onMore?.();
    };
    fill();
    const observer = new ResizeObserver(fill);
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasFilter, canLoad, sessions.length, onMore]);
  useEffect(() => () => { if (wheelTimer.current) clearTimeout(wheelTimer.current); }, []);
  const filtered = sessions.filter((session) =>
    session.title.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <aside className="history" aria-label="会话列表">
      <div className="history-heading">
        <h2>会话列表</h2>
        <button className="secondary-button" onClick={onCreate} disabled={creating}>
          <Plus size={14} />
          新建
        </button>
      </div>
      <label className="search">
        <MagnifyingGlass size={16} />
        <input
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="过滤已加载会话…"
          aria-label="过滤已加载会话"
        />
      </label>
      <div className="list-scope">
        <span>仅筛选已加载会话</span>
        {pagination && <button className="text-button" onClick={() => void pagination.onReload()}
          disabled={refreshing || loadingMore || retrySeconds > 0}>
          重载列表
        </button>}
      </div>
      {listError && pagination && <ListError failure={listError}
        onRetry={pagination.onReload} onReload={pagination.onReload} />}
      <nav className="session-list" aria-label="会话列表内容" tabIndex={0} ref={list}
        aria-busy={Boolean(refreshing || loadingMore)}
        onScroll={() => {
          const next = list.current?.scrollTop ?? 0;
          if (next > scrollTop.current && atBottom()) loadNext();
          scrollTop.current = next;
        }}
        onWheel={event => {
          if (wheelTimer.current) clearTimeout(wheelTimer.current);
          wheelTimer.current = setTimeout(() => { wheelGesture.current = false; }, 200);
          if (event.deltaY > 0 && atBottom() && !wheelGesture.current) {
            wheelGesture.current = true;
            loadNext();
          }
        }}
        onTouchStart={event => { touchY.current = event.touches[0]?.clientY ?? null; }}
        onTouchMove={event => {
          if (touchY.current !== null && event.touches[0]?.clientY < touchY.current - 12 && atBottom()) {
            touchY.current = null;
            loadNext();
          }
        }}
        onKeyDown={event => {
          if (event.repeat || event.nativeEvent.isComposing || !["End", "PageDown"].includes(event.key)) return;
          const element = list.current;
          if (element && (event.key === "End" || element.scrollTop + 2 * element.clientHeight >= element.scrollHeight)) {
            event.preventDefault();
            element.scrollTop = element.scrollHeight;
            loadNext();
          }
        }}>
        {refreshing && sessions.length === 0 && <div aria-label="正在加载会话列表" role="status">
          {Array.from({ length: 6 }, (_, index) => <div className="session-skeleton" key={index}><i /><i /></div>)}
        </div>}
        {refreshing && sessions.length > 0 && <p className="list-feedback" role="status">正在刷新会话列表…</p>}
        {(["今天", "昨天", "更早", "日期待确认"] as const).map((group) => {
          const entries = filtered.filter((session) => session.group === group);
          return (
            entries.length > 0 && (
              <div key={group}>
                <p className="group-label">
                  {group}
                </p>
                {entries.map((session) => (
                  <div className="session-entry" key={session.id}>
                  <button
                    className={`session ${activeId === session.id ? "selected" : ""}`}
                    data-conversation-id={session.id}
                    title={`${session.title}\n会话 ID：${session.id}`}
                    onClick={() => onSelect(session.id)}
                    aria-current={activeId === session.id ? "true" : undefined}
                  >
                    <strong>{session.title}</strong>
                    <span className="session-meta"><span>{session.summary}</span>
                      {session.status && <span className="session-status">{session.status}</span>}
                    </span>
                  </button>
                  <button className="icon-button session-inspect" aria-label={`查看会话标题与时间：${session.title}`}
                    title="查看完整标题与时间" onClick={() => onInspect(session.id)}><DotsThree size={17}/></button>
                  </div>
                ))}
              </div>
            )
          );
        })}
        {filtered.length === 0 && (loaded || !pagination) && !refreshing && !listError && (
          <div className="no-results">
            <p>{hasFilter ? "已加载会话中没有匹配结果" : "还没有会话"}</p>
            {hasFilter && <>
            <button className="text-button" onClick={() => onQuery("")}>
              清除过滤
            </button>
            {hasMore && <p>向下滚动或按 End 可继续读取更早会话</p>}
            </>}
            {!hasFilter && <button className="secondary-button" onClick={onCreate} disabled={creating}><Plus size={14}/>新建会话</button>}
          </div>
        )}
        {loadingMore && <p className="list-feedback" role="status">正在加载更早会话…</p>}
        {pageError && pagination && <ListError failure={pageError}
          onRetry={() => void pagination.onMore(true)} onReload={pagination.onReload} />}
        {loaded && !hasMore && !pageError && <p className="list-feedback" role="status">没有更多</p>}
      </nav>
      {usageSummary}
    </aside>
  );
}
