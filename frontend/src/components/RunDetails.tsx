import { useLayoutEffect, useRef, useState } from 'react';
import { Lightning } from '@phosphor-icons/react';
import { runStatusLabels, type Run } from '../backend-client';
import { observationLabels } from '../observation-recovery';
import type { SnapshotRead } from '../conversation-state';
import type { ContentView } from './MessageBody';
import { ContentViewer, CopyContent } from './ContentViewer';
import { ObservationStatus } from './ObservationStatus';
import type { ConversationView } from '../conversation-state';
import { RunEvents } from './RunEvents';
import { emptyUsageVerification, type UsageVerification } from '../usage-verification';

export function formatRunNumber(value:number | undefined) {
  return value === undefined ? '未提供' : value.toLocaleString();
}
export function usageSettlementLabel(run:Run | null,verification:UsageVerification=emptyUsageVerification) {
  if(run?.usage_pending===true && verification.pauseReason==='limit') return '仍在结算，自动核实已暂停';
  return run?.usage_pending === true ? '仍在结算'
    : run?.usage_pending === false ? '当前用量已保存' : '结算状态待确认';
}
function usageEmptyLabel(run:Run | null, snapshotRead:SnapshotRead, availability:string) {
  if (!run) return availability;
  if (snapshotRead.phase === 'reading' && !Object.hasOwn(run,'usage')) return '正在读取用量';
  return '暂无用量数据';
}

export function RunUsage({run,snapshotRead,availability,verification=emptyUsageVerification,isCompact=false,onDetails,onView,onContinue,onReload,disabled=false}: {
  run:Run | null; snapshotRead:SnapshotRead; availability:string; isCompact?:boolean;
  onDetails?:()=>void; onView?:(view:ContentView)=>void; disabled?:boolean;
  verification?:UsageVerification; onContinue?:()=>Promise<void>; onReload?:()=>void;
}) {
  const usage = run?.usage;
  return <section className={isCompact ? 'usage' : 'run-usage'} aria-label="本次运行用量">
    {isCompact ? <span><Lightning size={15}/>本次运行用量</span> : <h3>本次运行用量</h3>}
    {usage ? <dl className="usage-values">
      {(['输入 Token','输出 Token','合计 Token','模型调用次数（已记录）'] as const).map((label,index)=><div key={label}>
        <dt>{label}</dt><dd>{formatRunNumber([usage.total_input,usage.total_output,usage.total_tokens,usage.calls][index])}</dd>
      </div>)}
    </dl> : <p role="status">{usageEmptyLabel(run,snapshotRead,availability)}</p>}
    {run && <p className="settlement-status" role="status">{usageSettlementLabel(run,verification)}</p>}
    {snapshotRead.phase === 'reading' && usage && <small role="status">正在刷新用量…</small>}
    {snapshotRead.phase === 'error' && <p className="read-failure" role="alert">用量读取失败，已有值保留。</p>}
    {snapshotRead.retry && <p className="settlement-status" role="status">等待后核实用量：{new Date(snapshotRead.retry.at).toLocaleTimeString()}</p>}
    {run?.usage_pending===true && (verification.pauseReason || snapshotRead.phase==='error') && <button
      className="text-button usage-continue" disabled={snapshotRead.phase==='reading' || disabled}
      onClick={snapshotRead.failure?.status===404?onReload:()=>void onContinue?.()}>
      {snapshotRead.failure?.status===404?'重新读取会话':verification.pauseReason==='limit'?'继续核实':'重试核实用量'}
    </button>}
    {!isCompact && <>
      <p>本次运行已记录的累计用量，包含审批继续前的部分。调用次数指模型完成回调，不代表工具次数或账单。</p>
      {usage && <details className="model-usage"><summary>模型分项</summary>
        {usage.by_model === undefined ? <p>模型分项未提供</p>
          : Object.keys(usage.by_model).length === 0 ? <p>暂无模型分项</p>
          : Object.entries(usage.by_model).map(([model,counts])=><section key={model} className="model-usage-row">
            <h4>{model}</h4><dl className="usage-values">
              <div><dt>输入</dt><dd>{formatRunNumber(counts.input)}</dd></div>
              <div><dt>输出</dt><dd>{formatRunNumber(counts.output)}</dd></div>
              <div><dt>已记录调用</dt><dd>{formatRunNumber(counts.calls)}</dd></div>
            </dl>
          </section>)}
        <button className="text-button" onClick={()=>onView?.({title:'完整模型用量',text:JSON.stringify(usage.by_model ?? null,null,2)})}>查看完整模型用量</button>
      </details>}
    </>}
    {onDetails && <button className="text-button" onClick={onDetails} disabled={disabled} title={disabled ? availability : undefined}>查看详情</button>}
  </section>;
}

export function formatRunTime(timestamp:string) {
  const instant=new Date(timestamp);
  const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;
  return {local:`${instant.toLocaleString(undefined,{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false,timeZoneName:'longOffset'})} · ${zone}`,
    // Preserve the server's UTC precision (Python snapshots can include microseconds).
    utc:/(?:Z|[+-]00:00)$/i.test(timestamp) ? timestamp : instant.toISOString()};
}
function RunTime({label,timestamp,fallback,onView}: {label:string; timestamp?:string | null; fallback:string; onView:(view:ContentView)=>void}) {
  const display=timestamp ? formatRunTime(timestamp) : null;
  return <div><dt>{label}</dt><dd>{display ? <>
    <span>{display.local}</span><span className="run-utc">UTC：{display.utc}</span>
    <CopyContent text={display.utc} label={`复制${label} UTC`}/>
    <button className="text-button" onClick={()=>onView({title:label,text:`本地：${display.local}\nUTC：${display.utc}\n服务端原值：${timestamp}`})}>查看完整时间</button>
  </> : fallback}</dd></div>;
}

export function RunDetails({threadId,title,view,availability,onRefresh,onRefreshEvents=async()=>{},onContinueUsage,onReload,onReconnect,onQuery,onApproval,onClose}: {
  threadId:string; title:string; view:ConversationView; availability:string;
  onRefresh:()=>Promise<void>; onReload:()=>void; onReconnect:()=>void; onQuery:()=>Promise<void>;
  onRefreshEvents?:()=>Promise<void>;
  onContinueUsage?:()=>Promise<void>;
  onApproval:()=>void; onClose:()=>void;
}) {
  const [contentView,setContentView]=useState<ContentView | null>(null);
  const readingArea=useRef<HTMLDivElement>(null);
  const returnPosition=useRef<{scrollTop:number; trigger:HTMLElement | null}>({scrollTop:0,trigger:null});
  const openContent=(nextView:ContentView)=> {
    returnPosition.current={scrollTop:readingArea.current?.scrollTop ?? 0,trigger:document.activeElement as HTMLElement | null};
    setContentView(nextView);
  };
  useLayoutEffect(()=> {
    if(contentView) document.querySelector<HTMLElement>('.run-details-subview button')?.focus();
    else {
      if(readingArea.current) readingArea.current.scrollTop=returnPosition.current.scrollTop;
      if(returnPosition.current.trigger?.isConnected) returnPosition.current.trigger.focus({preventScroll:true});
      else {
        const dialog=document.querySelector<HTMLDialogElement>('dialog[open]');
        if(dialog && !dialog.contains(document.activeElement)) dialog.querySelector<HTMLElement>('.overlay-heading button')?.focus();
      }
    }
  },[contentView]);
  const run=view.run, snapshotRead=view.snapshotRead;
  const errorEvent=run?.status === 'error' ? view.events[run.run_id]?.filter(event=>event.category==='lifecycle'
    && event.payload.status==='error').at(-1) : undefined;
  const lifecycleError=errorEvent?.category==='lifecycle' ? errorEvent.payload : undefined;
  const executionError=run?.error ?? lifecycleError?.message;
  const executionErrorCode=run?.error_code ?? lifecycleError?.error_code;
  return <>
    <div className="details-content run-details" ref={readingArea} hidden={Boolean(contentView)}>
      <span className="badge">{run ? runStatusLabels[run.status] : availability}</span><h3>{title}</h3>
      <button className="secondary-button" disabled={!run || snapshotRead.phase==='reading' || view.eventRead.phase==='reading'} onClick={()=>void onRefresh()}>{snapshotRead.phase==='reading' || view.eventRead.phase==='reading' ? '正在刷新详情…' : '刷新详情'}</button>
      {snapshotRead.retry && <p role="status">等待后重试读取（第 {snapshotRead.retry.attempt} 次）：{new Date(snapshotRead.retry.at).toLocaleTimeString()}</p>}
      {snapshotRead.phase==='error' && <section className="details-read-error" aria-label="运行信息读取错误">
        <p role="alert">{snapshotRead.failure?.status===404 ? '运行不可读取，请重新读取会话定位。' : '运行信息读取失败，已有内容保留。'}</p>
        <button className="text-button" onClick={snapshotRead.failure?.status===404 ? onReload : ()=>void onRefresh()}>{snapshotRead.failure?.status===404 ? '重新读取会话' : '重试读取'}</button>
        <button className="text-button" onClick={()=>openContent({title:'快照读取错误',text:JSON.stringify(snapshotRead.failure,null,2)})}>查看读取错误</button>
      </section>}
      <section aria-label="运行信息"><h3>运行信息</h3>
        <dl className="run-information">
          {([['会话 ID',threadId],['运行 ID',run?.run_id]] as const).map(([label,identity])=><div key={label}><dt>{label}</dt><dd>
            <span className="run-identity">{identity || availability}</span>
            {identity && <><CopyContent text={identity} label={`复制${label}`}/><button className="text-button" onClick={()=>openContent({title:label,text:identity})}>查看完整 ID</button></>}
          </dd></div>)}
          <div><dt>运行状态</dt><dd>{run ? runStatusLabels[run.status] : availability}</dd></div>
          <RunTime label="创建时间" timestamp={run?.created_at} fallback="创建时间未取得" onView={openContent}/>
          <RunTime label="更新时间" timestamp={run?.updated_at} fallback="更新时间未取得" onView={openContent}/>
          <RunTime label="结束时间" timestamp={run?.completed_at} fallback={run && ['running','interrupted'].includes(run.status) ? '尚未结束' : '结束时间未取得'} onView={openContent}/>
        </dl>
        {run?.status==='error' && <section className="details-execution-error" aria-label="执行错误">
          <p role="alert">运行失败</p><p>错误代码：{executionErrorCode ?? '未提供'}</p>
          {executionErrorCode != null && <CopyContent text={executionErrorCode} label="复制错误代码"/>}
          {typeof executionError==='string' ? <>
            {run.error == null && <p>当前运行生命周期事件的错误说明；快照错误详情尚未取得。</p>}
            <pre tabIndex={0}>{executionError}</pre><CopyContent text={executionError} label="复制完整执行错误"/>
            <button className="text-button" onClick={()=>openContent({title:'完整执行错误',text:executionError})}>查看完整执行错误</button></>
            : <p>后端错误详情尚未取得</p>}
        </section>}
      </section>
      <RunUsage run={run} snapshotRead={snapshotRead} verification={view.usageVerification} availability={availability}
        onView={openContent} onContinue={onContinueUsage} onReload={onReload}/>
      <RunEvents events={run ? view.events[run.run_id] ?? [] : []} eventRead={view.eventRead} status={run?.status} onRefresh={onRefreshEvents} onReload={onReload} onView={openContent}/>
      <section aria-label="观察连接"><h3>观察连接</h3><p>{observationLabels[view.observation]}</p><ObservationStatus view={view} onReconnect={onReconnect} onQuery={onQuery}/></section>
      <div className="details-actions">
        {run?.status==='interrupted' && <button className="secondary-button" onClick={onApproval}>处理审批</button>}
        <button className="text-button" onClick={onClose}>返回会话</button>
      </div>
    </div>
    {contentView && <div className="run-details-subview"><button className="text-button" onClick={()=>setContentView(null)}>返回运行详情</button><ContentViewer view={contentView}/></div>}
  </>;
}
