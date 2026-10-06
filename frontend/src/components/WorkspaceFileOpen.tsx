import { createContext, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from 'react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import type { BackendSession } from '../backend-client';
import { WorkspaceFileOpening, type FileOpenView } from '../workspace-file-open';
import { CopyContent } from './ContentViewer';

const idleView:FileOpenView = {phase:'idle', reference:'', messageIdentity:'', intent:null, error:''};
const FileOpenContext = createContext<((reference:string, messageIdentity:string) => void) | null>(null);
export function WorkspaceFileOpenProvider({onRequest, children}:{onRequest:(reference:string, messageIdentity:string) => void; children:ReactNode}) {
  return <FileOpenContext.Provider value={onRequest}>{children}</FileOpenContext.Provider>;
}
export function useWorkspaceFileOpening(session:BackendSession | null, threadId:string | null, isVisible:boolean) {
  const [controller, setController] = useState<WorkspaceFileOpening | null>(null);
  const [view, setView] = useState<FileOpenView>(idleView);
  useLayoutEffect(() => {
    const opening = session && isVisible ? new WorkspaceFileOpening(session.startupId, invoke) : null;
    setController(opening); setView(idleView);
    const unsubscribeFileOpen = opening?.subscribeFileOpen(setView);
    const closeOnLeaseLoss = () => opening?.closeFileOpen();
    session?.signal.addEventListener('abort', closeOnLeaseLoss, {once:true});
    return () => {
      unsubscribeFileOpen?.(); opening?.disposeFileOpening();
      session?.signal.removeEventListener('abort', closeOnLeaseLoss);
    };
  }, [session, threadId, isVisible]);
  return {controller, view};
}
export function WorkspaceFileButton({reference, messageIdentity, children = '用系统打开'}:{reference:string; messageIdentity:string; children?:ReactNode}) {
  const requestFileOpen = useContext(FileOpenContext);
  const [error, setError] = useState('');
  if (/[\\/]$/.test(reference)) return <span className="reference-note">目录引用暂不支持打开（只读）</span>;
  return <span className="file-open-control">
    <button className="markdown-link" data-file-reference={reference} data-file-message-identity={messageIdentity} title={reference} onClick={() => {
      setError('');
      if (!isTauri() || !requestFileOpen) {setError('本地文件打开仅在桌面应用中可用，当前为只读引用'); return;}
      requestFileOpen(reference, messageIdentity);
    }}>{children}</button>
    {error && <span className="content-error" role="alert">{error}</span>}
  </span>;
}
export function FileOpenConfirmation({view, onClose, onConfirm, onPrepare}:{
  view:FileOpenView; onClose:() => void; onConfirm:() => void; onPrepare:() => void;
}) {
  useEffect(() => {
    if (view.phase === 'prepared') document.getElementById('cancel-file-open')?.focus();
  }, [view.phase, view.intent?.request_id]);
  const isPending = view.phase === 'preparing' || view.phase === 'opening';
  return <div className="file-open-confirmation">
    <p>使用系统默认程序打开当前磁盘文件。文件内容可能已与生成时不同。</p>
    {view.intent ? <dl className="file-open-metadata">
      <div><dt>文件名</dt><dd>{view.intent.name}</dd></div>
      <div><dt>完整路径</dt><dd className="reference-path">{view.intent.absolute_path}</dd></div>
      <div><dt>文件大小</dt><dd>{view.intent.size} 字节</dd></div>
      <div><dt>修改时间</dt><dd>{view.intent.modified_at}</dd></div>
    </dl> : <><p>原始引用</p><pre className="reference-path">{view.reference}</pre></>}
    <CopyContent text={view.intent?.absolute_path ?? view.reference} label={view.intent ? '复制完整路径' : '复制引用'} />
    {isPending && <p role="status">{view.phase === 'preparing' ? '正在核实工作目录与真实文件…' : '正在请求系统打开…'}</p>}
    {view.error && <p className="content-error" role="alert">{view.error}</p>}
    {view.phase === 'error' && !view.intent && <p>本次准备未打开文件，当前引用只读。</p>}
    {view.phase === 'error' && <p>本次确认不能重用。重新准备后，请核对新的文件信息并再次确认。</p>}
    {view.phase === 'accepted' && <p role="status">系统已接受打开请求。是否显示文件由默认程序决定，不会自动再打开。</p>}
    <div className="confirmation-actions">
      <button id="cancel-file-open" className="secondary-button" onClick={onClose}>{view.phase === 'accepted' ? '关闭' : '取消'}</button>
      {view.phase === 'error' && <button className="secondary-button" onClick={onPrepare}>重新准备</button>}
      {view.phase !== 'accepted' && view.phase !== 'error' && <button className="primary-button" disabled={view.phase !== 'prepared'} onClick={onConfirm}>确认打开</button>}
    </div>
  </div>;
}
