import { useBackendState } from "./useBackendState";
import { TrayNotice } from "./TrayNotice";
import { BackendLogs } from "./BackendLogs";
import { useEffect, useRef, useState } from "react";
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
import { Conversation, Composer, type ConversationActions } from "./components/Conversation";
import { Overlay } from "./components/Overlay";
import { ContentViewer } from './components/ContentViewer';
import type { ContentView } from './components/MessageBody';
import { SendRecovery, DraftCopy } from './components/SendRecovery';
import { ObservationStatus } from './components/ObservationStatus';
import { RunFailure } from './components/RunFailure';
import type { BackendSession } from "./backend-client";
import type { CancelTarget } from './conversation-state';
import { useConversations } from "./useConversations";
import { ApprovalRecovery } from './components/ApprovalRecovery';
import { useWorkspaceVisibility } from './useWorkspaceVisibility';
import { WorkspaceImageProvider } from './components/WorkspaceImage';
import { FileOpenConfirmation, WorkspaceFileOpenProvider, useWorkspaceFileOpening } from './components/WorkspaceFileOpen';

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
      <main className="backend-screen" tabIndex={-1} aria-live="polite">
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

function isFileSourcePresent(reference:string, messageIdentity:string) {
  return [...document.querySelectorAll<HTMLElement>('.timeline [data-file-reference]')]
    .some(element => element.dataset.fileReference === reference
      && element.dataset.fileMessageIdentity === messageIdentity);
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
  const [overlay, setOverlay] = useState<"commands" | "details" | ContentView | null>(null);
  const [cancelTarget, setCancelTarget] = useState<CancelTarget | null>(null);
  const fileOpening = useWorkspaceFileOpening(session, activeId, conversations.visible);
  function closeFileOpen() {fileOpening.controller?.closeFileOpen();}
  function requestFileOpen(reference:string, messageIdentity:string) {
    if (!session || session.signal.aborted || !conversations.visible || !fileOpening.controller) return;
    if (fileOpening.view.phase === 'preparing' || fileOpening.view.phase === 'opening') return;
    if (!isFileSourcePresent(reference, messageIdentity)) return;
    setOverlay(null); setCancelTarget(null); setMobilePanel(null);
    void fileOpening.controller.prepareFileOpen(reference, messageIdentity);
  }
  useEffect(() => {
    if (fileOpening.view.phase === 'idle') return;
    const checkReference = () => {
      if (!isFileSourcePresent(fileOpening.view.reference, fileOpening.view.messageIdentity))
        fileOpening.controller?.closeFileOpen();
    };
    checkReference();
    const observer = new MutationObserver(checkReference);
    const timeline = document.querySelector('.timeline');
    if (timeline) observer.observe(timeline, {childList:true, subtree:true, attributes:true, attributeFilter:['data-file-reference','data-file-message-identity']});
    return () => observer.disconnect();
  }, [fileOpening.controller, fileOpening.view.reference, fileOpening.view.messageIdentity, fileOpening.view.phase]);
  useEffect(() => {
    setOverlay(currentOverlay => currentOverlay && typeof currentOverlay === 'object' && currentOverlay.image ? null : currentOverlay);
  }, [session, conversations.visible]);
  useEffect(() => {
    if (cancelTarget && (!conversations.visible || !conversations.validCancelTarget(cancelTarget))) setCancelTarget(null);
  }, [cancelTarget, conversations]);
  function requestCancel() {
    const target = conversations.cancelTarget();
    if (!target) return;
    setOverlay(null); setMobilePanel(null); setCancelTarget(target);
  }
  const previousConversation = useRef(activeId);
  const previousRun = useRef(conversations.run?.run_id);
  const timeline = useRef<ConversationActions>(null);
  useEffect(() => {
    if (previousConversation.current !== activeId || previousRun.current !== conversations.run?.run_id) {
      setOverlay(null);
      previousConversation.current = activeId;
      previousRun.current = conversations.run?.run_id;
    }
  }, [activeId, conversations.run?.run_id]);
  const shortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

  function toggleNavigation() {
    setCollapsed((value) => !value);
  }
  function createSession() {
    timeline.current?.rememberReadingPosition();
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
      active.messages.filter(message => !message.preview)
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
        if (document.querySelector('dialog[open]')) {
          if (event.key.toLowerCase() === 'k' && overlay === 'commands') {
            event.preventDefault(); setOverlay(null);
          }
          return;
        }
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
    <WorkspaceFileOpenProvider onRequest={requestFileOpen}>
    <WorkspaceImageProvider session={session} threadId={activeId} isVisible={conversations.visible}>
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
              timeline.current?.rememberReadingPosition();
              conversations.select(id);
              setMobilePanel(null);
            }}
            onCreate={createSession}
            creating={conversations.creating || conversations.loading}
            pagination={conversations.pagination}
          />
          <main className="chat-workspace" tabIndex={-1}>
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
                {conversations.run?.status === 'interrupted' && <button className="text-button"
                  onClick={()=>timeline.current?.locateApproval()}>处理审批</button>}
                <button
                  className="text-button"
                  onClick={exportSession}
                  disabled={!active.messages.some(message => !message.preview)}
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
            <RunFailure run={conversations.run} onView={setOverlay} />
            {session && <ObservationStatus view={conversations.observationView} onReconnect={conversations.reconnect} onQuery={conversations.queryStatus} />}
            {conversations.notice && <p className="business-notice" role="status">{conversations.notice}</p>}
            {conversations.write && <section className="business-notice" aria-label={conversations.write.kind === 'approval' ? '审批结果核实' : '取消结果核实'}>
              <p role="status">{conversations.write.kind === 'approval'
                ? conversations.write.phase === 'pending' ? '正在确认审批提交…'
                  : conversations.write.verifying ? '正在核实审批请求及提交结果…'
                  : conversations.write.verified ? '已核实当前请求。可核对后手动重新提交；先前请求仍可能迟到生效。'
                  : conversations.write.failure?.status === 409 ? '审批已变化，请核实同一运行；以当前请求和实际处理记录为准。'
                  : conversations.write.failure?.status === 422 ? '审批校验未通过，选择和服务端校验详情已保留；核实后可修改并手动提交。'
                  : conversations.write.failure?.status === 503 ? '审批暂不可提交，已保留输入；核实与重新提交需等待服务端指定时间。'
                  : '审批提交结果待确认，请核实当前请求；不会自动再次提交。'
                : conversations.write.phase === 'pending' ? '正在确认取消结果…'
                  : conversations.write.verifying ? '取消结果待确认，正在查询真实状态…'
                  : conversations.write.verified ? '已核实运行仍未结束。可以再次手动确认取消；先前请求仍可能迟到生效。'
                  : '取消结果待确认，请查询真实状态；不会自动再次取消。'}</p>
              {conversations.write.phase === 'unknown' && <button className="secondary-button"
                disabled={conversations.write.verifying} onClick={() => void conversations.queryStatus()}>{conversations.write.kind === 'approval' ? '核实审批结果' : '核实取消结果'}</button>}
              {conversations.write.failure && <details><summary>请求／核实错误详情</summary>
                <pre className="request-error">{JSON.stringify(conversations.write.failure, null, 2)}</pre></details>}
            </section>}
            {conversations.savedContent === 'reading' && <p className="business-notice" role="status">正在读取已保存内容</p>}
            {conversations.savedContent === 'error' && <section className="business-notice" aria-label="保存内容读取">
              <p role="alert">已保存内容读取失败，已有记录和预览已保留，运行结果不变。</p>
              <button className="secondary-button" onClick={() => void conversations.retrySavedContent()}>读取已保存内容</button>
              <details><summary>读取错误详情</summary><pre className="request-error">{JSON.stringify(conversations.savedContentFailure, null, 2)}</pre></details>
            </section>}
            {conversations.sendFailure && conversations.submission?.status !== 'unknown' && <details className="business-notice">
              <summary>发送请求错误详情</summary>
              <pre style={{maxHeight:240, overflow:'auto', whiteSpace:'pre-wrap'}}>{JSON.stringify(conversations.sendFailure, null, 2)}</pre>
            </details>}
            {conversations.verifying && <p className="business-notice" role="status">正在核实当前运行状态…</p>}
            {conversations.storageIssue && <p className="business-notice" role="alert">{conversations.storageIssue}</p>}
            <ApprovalRecovery records={conversations.approvalRecoveryRecords} onView={setOverlay}/>
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
              ref={timeline}
              readingPositions={conversations.readingPositions}
              factsReady={conversations.readingFactsReady}
              visible={conversations.visible}
              acceptedSendId={conversations.acceptedSendId}
              approvalStatus={conversations.approvalStatus}
              approvalIdentity={conversations.run?.run_id}
              approvals={{records:conversations.approvalCards, draft:conversations.approvalDraft,
                activeRunId:conversations.run?.run_id ?? null, canVerify:conversations.canReconnect,
                currentIdentity:conversations.approvalDraft?.identity ?? null, acceptedIdentity:conversations.acceptedApproval,
                isPending:conversations.write?.phase === 'pending' || Boolean(conversations.write?.verifying),
                canEdit:conversations.canEditApproval, canSubmit:conversations.canSubmitApproval,
                onChoose:conversations.chooseApproval, onSubmit:conversations.submitApproval, onVerify:conversations.reconnect}}
              canCancel={conversations.canCancel}
              onCancel={requestCancel}
              toolPreferences={conversations.toolPreferences}
              preview={!session}
              session={active}
              readState={activeId ? conversations.historyState : "ready"}
              onView={view => { setCancelTarget(null); setMobilePanel(null); setOverlay(view); }}
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
                timeline.current?.locateApproval();
              }}
              onCancel={requestCancel}
              canCancel={conversations.canCancel}
              writePending={conversations.write?.phase === 'pending' || conversations.write?.verifying}
            />
          </main>
        </div>
        {fileOpening.view.phase !== 'idle' && <Overlay title="打开本地文件？" initialFocus="#cancel-file-open" onClose={closeFileOpen}>
          <FileOpenConfirmation view={fileOpening.view} onClose={closeFileOpen}
            onConfirm={() => {
              if (!isFileSourcePresent(fileOpening.view.reference, fileOpening.view.messageIdentity)) {closeFileOpen(); return;}
              void fileOpening.controller?.confirmFileOpen();
            }}
            onPrepare={() => void fileOpening.controller?.prepareFileOpen(fileOpening.view.reference, fileOpening.view.messageIdentity)}/>
        </Overlay>}
        {fileOpening.view.phase === 'idle' && cancelTarget && <Overlay title="取消本次运行？" initialFocus="#continue-running" onClose={() => setCancelTarget(null)}>
          <div className="cancel-confirmation">
            <p className="cancel-conversation">所属会话：{sessions.find(item => item.id === cancelTarget.threadId)?.title ?? '新会话'}</p>
            <p>取消不会撤销已经发生的工具操作，已开始的操作也不保证立即停止。</p>
            <div className="confirmation-actions">
              <button id="continue-running" className="secondary-button" onClick={() => setCancelTarget(null)}>继续运行</button>
              <button className="primary-button danger-button" onClick={() => {
                const target = cancelTarget; setCancelTarget(null); void conversations.cancel(target);
              }}>确认取消</button>
            </div>
          </div>
        </Overlay>}
        {fileOpening.view.phase === 'idle' && overlay === "commands" && (
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
        {fileOpening.view.phase === 'idle' && overlay === "details" && (
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
              <RunFailure run={conversations.run} onView={setOverlay} />
              {conversations.error && <p role="alert">{conversations.error}</p>}

            </div>
          </Overlay>
        )}
        {fileOpening.view.phase === 'idle' && overlay && typeof overlay === 'object' && <Overlay title={overlay.title} drawer onClose={() => setOverlay(null)}>
          {overlay.approval && <p className="business-notice">只读参数 · {conversations.approvalCards.some(record=>
            record.identity === overlay.approval!.identity && record.resolution) || ['completed','cancelled','error'].includes(
              conversations.observationView.runStatuses[overlay.approval.runId] ?? '')
            ? '审批已处理或运行已结束，以下为历史内容' : '仅供核对，不在此处审批'}</p>}
          <ContentViewer view={overlay.preview && conversations.run && ['completed','cancelled','error'].includes(conversations.run.status)
            ? {...overlay, generating:false} : overlay} />
        </Overlay>}
      </div>
    </IconContext.Provider>
    </WorkspaceImageProvider>
    </WorkspaceFileOpenProvider>
  );
}
