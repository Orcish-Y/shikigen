import type { ApprovalBackup } from '../approval-drafts';
import type { ContentView } from './MessageBody';
import { ContentBlock } from './ContentViewer';

/** 本地输入供核对；不在服务端事实时间线中生成 required / resolved。 */
export function ApprovalRecovery({records,onView}:{records:ApprovalBackup[];onView:(view:ContentView)=>void}) {
  if(!records.length)return null;
  return <section className="business-notice" aria-label="本地审批草稿核对">
    <p>本地审批输入已保留，仅供核对。未提交选择不属于审批历史；当前请求核实成功后才能操作。</p>
    {records.map(record=><details key={record.draft.identity}>
      <summary>本地审批草稿 · 运行 {record.draft.runId}{record.submission?.status==='unknown'?' · 提交结果待核实':''}</summary>
      <ContentBlock title="本地审批输入（只读）" text={JSON.stringify({thread_id:record.threadId,run_id:record.draft.runId,
        version:record.draft.version,request:record.draft.request,choices:record.draft.choices,
        submission:record.submission},null,2)} onView={onView}/>
    </details>)}
  </section>;
}
