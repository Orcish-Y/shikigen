import { useEffect, useState } from 'react';
import type { ConversationView } from '../conversation-state';
import { observationLabels } from '../observation-recovery';

export function ObservationStatus({view, onReconnect, onQuery}: {
  view:ConversationView; onReconnect:() => void; onQuery:() => Promise<void>;
}) {
  const [now, setNow] = useState(Date.now);
  const at = view.retry?.at ?? 0;
  useEffect(() => {
    setNow(Date.now());
    if (at <= Date.now()) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= at) window.clearInterval(timer);
    }, 250);
    return () => window.clearInterval(timer);
  }, [at]);
  if (view.observation !== 'retry_wait' && view.observation !== 'failed') return null;
  const seconds = Math.max(0, Math.ceil((at-now)/1000));
  const failure = view.observationFailure;
  const busy = view.observation === 'retry_wait' || view.querying || view.history === 'loading' || view.sending;
  return <section className="business-notice" aria-label="运行观察恢复" style={{maxHeight:'40vh', overflow:'auto'}}>
    <p role="status" aria-live="polite" aria-atomic="true">
      {observationLabels[view.observation]}{view.retry?.attempt ? ` · 自动尝试 ${view.retry.attempt}/3` : ''}
      {view.querying && ' · 正在查询状态…'}
    </p>
    {view.retry && <p>{seconds} 秒后{view.retry.attempt ? '自动重新连接' : '重新连接'}</p>}
    <p>连接异常不代表运行失败；已读正文和草稿仍保留，重连只恢复观察。</p>
    {failure && <details>
      <summary>查看连接错误{failure.status ? `（HTTP ${failure.status}）` : failure.code ? `（${failure.code}）` : ''}</summary>
      <pre style={{maxHeight:240, overflow:'auto', whiteSpace:'pre-wrap'}}>{JSON.stringify(failure, null, 2)}</pre>
    </details>}
    <button className="secondary-button" onClick={onReconnect} disabled={busy || !view.run}>重新连接</button>
    <button className="text-button" onClick={() => void onQuery()} disabled={busy || !view.run}>查询状态</button>
    {view.queryFailure && <p role="alert">状态查询失败：{view.queryFailure.message}</p>}
  </section>;
}
