import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, CopySimple, X } from "@phosphor-icons/react";

export function TitleBar({ connectionLabel, isPreview = false }: {
  connectionLabel: string;
  isPreview?: boolean;
}) {
  const isDesktop = isTauri();
  const [isMaximized, setIsMaximized] = useState(false);
  const [windowError, setWindowError] = useState<string | null>(null);

  useEffect(() => {
    if (!isDesktop) return;
    const appWindow = getCurrentWindow();
    let isDisposed = false;
    let querySequence = 0;
    let stopListening: (() => void) | undefined;
    async function refreshMaximizedState() {
      const currentSequence = ++querySequence;
      try {
        const nextIsMaximized = await appWindow.isMaximized();
        if (!isDisposed && currentSequence === querySequence) setIsMaximized(nextIsMaximized);
      } catch (error) {
        if (!isDisposed) setWindowError(`无法读取窗口状态：${String(error)}`);
      }
    }
    void appWindow.onResized(() => void refreshMaximizedState()).then(unlisten => {
      if (isDisposed) unlisten();
      else {
        stopListening = unlisten;
        void refreshMaximizedState();
      }
    }).catch(error => {
      if (!isDisposed) setWindowError(`无法监听窗口状态：${String(error)}`);
    });
    return () => { isDisposed = true; stopListening?.(); };
  }, [isDesktop]);

  async function performWindowAction(action: "minimize" | "toggleMaximize" | "close") {
    if (!isDesktop) return;
    setWindowError(null);
    try {
      await getCurrentWindow()[action]();
    } catch (error) {
      setWindowError(`窗口操作失败：${String(error)}`);
    }
  }

  return (
    <header className="app-bar" data-tauri-drag-region={isDesktop ? true : undefined}>
      <div className="brand">
        <img src="/logo.svg" alt="" draggable={false} />
        <strong>shikigen</strong>
        {isPreview && <span className="preview-label">界面预览</span>}
      </div>
      <span className="app-connection">
        <span className="status-dot" />
        {connectionLabel}
      </span>
      {isDesktop && <div className="window-controls">
        <button className="window-control" aria-label="最小化" title="最小化"
          onClick={() => void performWindowAction("minimize")}><Minus size={16} /></button>
        <button className="window-control" aria-label={isMaximized ? "还原" : "最大化"} title={isMaximized ? "还原" : "最大化"}
          onClick={() => void performWindowAction("toggleMaximize")}>
          {isMaximized ? <CopySimple size={15} /> : <Square size={15} />}
        </button>
        <button className="window-control window-close" aria-label="关闭" title="关闭"
          onClick={() => void performWindowAction("close")}><X size={17} /></button>
      </div>}
      {windowError && <span className="window-error" role="alert">{windowError}</span>}
    </header>
  );
}
