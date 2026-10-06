import { useState } from 'react';
import type { RunEvent, RunStatus } from '../backend-client';
import type { EventRead } from '../run-event-history';
import type { ContentView } from './MessageBody';
import { CopyContent } from './ContentViewer';

const categoryLabels={lifecycle:'运行',approval:'审批',message:'消息'};
const lifecycleLabels={running:'进入运行中',interrupted:'等待审批',completed:'运行已完成',cancelled:'运行已取消',error:'运行失败'};

export function formatEventTitle(event:RunEvent) {
  if(event.category==='lifecycle') return lifecycleLabels[event.payload.status];
  if(event.category==='approval') return {required:'请求审批',resolved:'审批已处理',invalidated:'审批已失效'}[event.payload.status];
  return {human:'用户消息已保存',ai:'Agent 消息已保存',tool:'工具结果已保存'}[event.payload.type];
}
function EventSummary({event}: {event:RunEvent}) {
  if(event.category==='lifecycle') return <>
    {event.payload.message != null && <p className="event-description">{event.payload.message}</p>}
    {event.payload.error_code != null && <p>错误代码：{event.payload.error_code}</p>}
  </>;
  if(event.category==='message') return <>
    {event.payload.type==='ai' && event.payload.generation_status && event.payload.generation_status!=='complete'
      && <p>中止消息 · {event.payload.generation_status==='cancelled'?'已取消':'生成失败'}</p>}
    {event.payload.type==='tool' && <p>工具状态：{event.payload.status==='error'?'失败':'成功'}</p>}
  </>;
  const payload=event.payload;
  if(payload.status==='invalidated') return <p>因运行取消失效（{payload.reason}）</p>;
  if(payload.status==='resolved') return <div className="event-decisions">
    {Object.entries(payload.responses).map(([interruptId,response])=><div key={interruptId}>
      <p>Interrupt：<span className="run-identity">{interruptId}</span></p>
      {response.decisions.map((decision,index)=><p key={index}>第 {index+1} 项：{decision.type==='approve'?'批准':'拒绝'}
        {decision.type==='reject' && decision.message != null && <span className="event-description">拒绝原因：{decision.message}</span>}
      </p>)}
    </div>)}
  </div>;
  return <div>{payload.interrupts.map(interrupt=>{
    const request=interrupt.value;
    const actions=request && typeof request==='object' && !Array.isArray(request)
      ? (request as Record<string,unknown>).action_requests : undefined;
    const toolNames=Array.isArray(actions) ? actions.flatMap(action=>action && typeof action==='object'
      && typeof action.name==='string' ? [action.name] : []) : [];
    return <p key={interrupt.id}>来源：{interrupt.namespace || '主流程'}
      {toolNames.length>0 && <span> · {toolNames.join('、')}</span>}</p>;
  })}<p>{payload.interrupts.length} 个审批请求 · 完整动作与 checkpoint 可展开查看</p></div>;
}

export function RunEvents({events,eventRead,status,onRefresh,onReload,onView}: {
  events:RunEvent[]; eventRead:EventRead; onRefresh:()=>Promise<void>; onView:(view:ContentView)=>void;
  status?:RunStatus; onReload?:()=>void;
}) {
  const [shouldIncludeMessages,setShouldIncludeMessages]=useState(false);
  const visibleEvents=events.filter(event=>shouldIncludeMessages || event.category!=='message');
  return <section className="run-events" aria-label="已提交运行记录">
    <h3>已提交运行记录</h3>
    <div className="event-toolbar"><label><input type="checkbox" checked={shouldIncludeMessages}
      onChange={event=>setShouldIncludeMessages(event.target.checked)}/>包含消息事件</label>
      <button className="text-button" disabled={eventRead.phase==='reading'} onClick={()=>void onRefresh()}>刷新运行记录</button>
    </div>
    <p className="event-range">已加载 {events.length} 条，当前显示 {visibleEvents.length} 条；后端可能继续产生记录。</p>
    {status && ['completed','cancelled','error'].includes(status) && !events.some(event=>event.category==='lifecycle' && event.payload.status===status)
      && <p>尚未读取对应的终态事件；运行状态仍在运行信息中显示。</p>}
    {eventRead.phase==='reading' && <p role="status">{events.length?'正在刷新运行记录，已有事实保留…':'正在读取运行记录…'}</p>}
    {eventRead.retry && <p role="status">等待重试运行记录（第 {eventRead.retry.attempt} 次）：{new Date(eventRead.retry.at).toLocaleTimeString()}</p>}
    {eventRead.phase==='error' && <section className="details-read-error" aria-label="运行记录读取错误">
      <p role="alert">{eventRead.failure?.status===404?'运行记录不可读取，请重新读取会话定位。'
        : eventRead.failure?.kind==='protocol'?'运行记录协议问题，已有事实保留。':'运行记录读取失败，已有事实保留。'}</p>
      <button className="text-button" onClick={eventRead.failure?.status===404 && onReload ? onReload : ()=>void onRefresh()}>
        {eventRead.failure?.status===404 && onReload?'重新读取会话':'重试运行记录'}</button>
      <button className="text-button" onClick={()=>onView({title:'运行记录读取问题（只读）',text:JSON.stringify(eventRead.failure,null,2)})}>查看读取问题</button>
    </section>}
    {visibleEvents.length===0 && (events.length>0?<p>暂无运行或审批事件</p>
      : eventRead.isLoaded?<p>暂无已提交事件</p>
      : eventRead.phase!=='reading' && <p>尚未读取已提交事件</p>)}
    <ol className="event-timeline">
      {visibleEvents.map(event=>{
        const text=JSON.stringify(event,null,2);
        const createdAt=new Date(event.created_at);
        const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;
        return <li key={event.seq} className="event-row" data-seq={event.seq}>
          <header><span className="badge">{categoryLabels[event.category]}</span><strong>{formatEventTitle(event)}</strong>
            <span className="event-type">{event.event_type}</span></header>
          <p className="event-coordinate">seq {event.seq} · <time dateTime={event.created_at}
            title={`服务端原值：${event.created_at}`}>{createdAt.toLocaleString(undefined,{timeZoneName:'longOffset'})} · {zone}</time></p>
          <EventSummary event={event}/>
          <details className="event-json"><summary>完整事件 JSON</summary>
            <div className="content-actions"><button className="text-button"
              onClick={()=>onView({title:`完整事件 · seq ${event.seq}`,text})}>查看完整事件</button>
              <CopyContent text={text} label="复制完整事件"/>
            </div>
            <pre tabIndex={0} aria-label={`事件 seq ${event.seq} JSON`}>{text}</pre>
          </details>
        </li>;
      })}
    </ol>
  </section>;
}
