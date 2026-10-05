import type { Run } from '../backend-client';
import type { ContentView } from './MessageBody';
import { ContentBlock } from './ContentViewer';

/** 只呈现已核实的 Run 错误；连接与工具错误各自使用原来的提示。 */
export function RunFailure({run, onView}: {run:Run | null; onView:(view:ContentView) => void}) {
  if (run?.status !== 'error') return null;
  return <section className="business-notice run-failure" aria-label="运行失败原因">
    <p role="alert">运行失败，已保存的消息仍可阅读。</p>
    <p>错误代码：{run.error_code ?? '未提供'}</p>
    {typeof run.error === 'string'
      ? <ContentBlock title="失败原因" text={run.error} onView={onView} />
      : <p>后端未提供失败原因。</p>}
  </section>;
}
