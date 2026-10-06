import { parseApproval, type ApprovalChoice, type ApprovalDraft, type ApprovalRecord } from '../approval-decisions';
import { ContentBlock } from './ContentViewer';
import type { ContentView } from './MessageBody';

export function ApprovalCard({record, draft, isCurrent, canEdit, canSubmit, canCancel, canVerify, isActiveRun, isPending, isAccepted, hasEnded,
  onChoose, onSubmit, onCancel, onVerify, onView}: {
  record:ApprovalRecord; draft:ApprovalDraft | null; isCurrent:boolean; canEdit:boolean;
  canSubmit:boolean; canCancel:boolean; isPending:boolean; isAccepted:boolean; hasEnded:boolean;
  canVerify:boolean; isActiveRun:boolean;
  onChoose:(identity:string, interruptId:string, index:number, choice:Partial<ApprovalChoice>) => void;
  onSubmit:(identity:string) => void; onCancel:() => void; onVerify:() => void;
  onView:(view:ContentView) => void;
}) {
  const requestModel = parseApproval(record.request);
  const selectionCount = draft ? Object.values(draft.choices).flat().filter(choice=>choice.type).length : 0;
  const title = record.resolution?.status === 'resolved' ? '已处理'
    : record.resolution?.status === 'invalidated' ? '运行已取消，审批失效'
    : hasEnded ? '运行已结束，审批不可操作' : isAccepted ? '决策已接收，等待处理记录'
    : isCurrent ? '等待审批' : '审批尚未核实';
  const viewParameters = (view:ContentView) => onView({...view, approval:{runId:record.runId, identity:record.identity}});
  return <section className={`approval-card ${!record.resolution && !hasEnded && !isAccepted ? 'is-waiting' : ''}`}
    data-reading-anchor={`approval:${record.runId}:${record.seq}`} tabIndex={-1} aria-label="工具审批">
    <header className="approval-heading"><h2 id={isCurrent ? 'current-approval-status' : undefined} tabIndex={-1}>{title}</h2>
      {!record.resolution && !hasEnded && <span role="status">已选择 {selectionCount} / {requestModel.total} 项</span>}
    </header>
    {isCurrent && canEdit && <p className="approval-notice">审批请求已核实，等待处理。</p>}
    {requestModel.issue && <p className="approval-notice" role="status">{requestModel.issue}</p>}
    {requestModel.interrupts.map((interrupt, interruptIndex)=> <section className="approval-interrupt" key={interrupt.id}>
      <h3>来源：{interrupt.namespace || '主流程'}</h3>
      <details className="approval-identity"><summary>请求身份与原始内容（只读）</summary>
        <ContentBlock title="Interrupt 原始 JSON" text={JSON.stringify({id:interrupt.id, namespace:interrupt.namespace, value:interrupt.raw}, null, 2)} onView={viewParameters} />
      </details>
      {interrupt.actions.map((action, index)=> {
        const choice = draft?.choices[interrupt.id]?.[index];
        const decision = record.resolution?.status === 'resolved' ? record.resolution.responses[interrupt.id]?.decisions[index] : null;
        const fieldId = `approval-${record.runId}-${record.seq}-${interruptIndex}-${index}`;
        return <div className="approval-action" key={index}>
          <h4>{index+1}. {action.name}</h4>
          <p className="approval-description">{action.description || '未提供说明'}</p>
          <p className="approval-allowed">允许的决策：{action.allowedDecisions.map(option=>option === 'approve' ? '批准'
            : option === 'reject' ? '拒绝' : `${option}（首版不支持）`).join('、') || '未提供'}</p>
          <details className="approval-parameters"><summary><span className="when-closed">查看参数</span><span className="when-open">收起参数</span></summary>
            <ContentBlock title={`${action.name} · 完整参数`} text={JSON.stringify(action.args, null, 2)} onView={view=>onView({
              ...view, approval:{runId:record.runId, identity:record.identity, namespace:interrupt.namespace, description:action.description},
            })} />
          </details>
          {decision ? <div className="approval-decision"><strong>实际决策：{decision.type === 'approve' ? '批准' : '拒绝'}</strong>
            {decision.type === 'reject' && decision.message != null && <p className="approval-reason">拒绝原因：{decision.message || '未提供'}</p>}
          </div> : !record.resolution && !hasEnded ? <>
            <fieldset className="approval-options" disabled={!canEdit}>
              <legend>{action.name} 的审批选择</legend>
              {action.allowedChoices.map(option=> <label key={option}><input type="radio" name={fieldId} value={option}
                checked={choice?.type === option} onChange={()=>onChoose(record.identity, interrupt.id, index, {type:option})} />
                {option === 'approve' ? '批准' : '拒绝'}</label>)}
            </fieldset>
            {choice?.type === 'reject' && <label className="approval-reason-input" htmlFor={`${fieldId}-reason`}>拒绝原因（可选）
              <textarea id={`${fieldId}-reason`} rows={2} disabled={!canEdit} value={choice.reason}
                onChange={event=>onChoose(record.identity, interrupt.id, index, {reason:event.target.value})} />
            </label>}
          </> : null}
        </div>;
      })}
    </section>)}
    {!record.resolution && !hasEnded && <footer className="approval-footer">
      <p role="status">{isPending ? '提交中…，暂时不能编辑或取消' : isAccepted ? '已确认接收，等待服务端实际处理记录'
        : requestModel.issue ? '本组只读，请核实或取消运行' : !canEdit ? '正在核实审批，当前只读'
        : canSubmit ? '全部动作已选择，核对后提交' : '请逐项选择所有动作后统一提交'}</p>
      <div className="approval-actions">
        <button className="primary-button" disabled={!canSubmit} onClick={()=>onSubmit(record.identity)}>提交决策</button>
        <button className="secondary-button" disabled={!canCancel} onClick={onCancel}>取消运行</button>
        {!canEdit && !isPending && !isAccepted && <button className="secondary-button" disabled={!canVerify} onClick={onVerify}>重新核实审批</button>}
      </div>
    </footer>}
    {!record.resolution && hasEnded && <footer className="approval-footer">
      <p>尚未读取服务端审批处理记录；本请求已停止操作。</p>
      {isActiveRun && <button className="secondary-button" disabled={!canVerify} onClick={onVerify}>读取审批记录</button>}
    </footer>}
  </section>;
}
