import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { emptyConversation } from '../src/conversation-state.ts';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RunDetails, RunUsage, formatRunTime } from '../src/components/RunDetails.tsx';

const time = '2026-10-06T00:00:00Z';
const usage = {total_input:101,total_output:23,total_tokens:999,calls:2,
  by_model:{'实际模型':{input:101,output:23,calls:2}}};
const tick = () => new Promise(resolveTick => setImmediate(resolveTick));
async function until(probe) {
  for (let attempt=0;attempt<250;attempt++) {if(probe())return; await tick();}
  assert.fail('公开事实未就绪');
}
function setup(t) {
  const snapshots=[], streams=[];
  const client=new BackendClient(async(url,init)=> {
    const path=new URL(url).pathname;
    if(path==='/api/threads') return Response.json({data:['t','u'].map(id=>({id,title:null,user_id:null,
      created_at:time,updated_at:time,run_id:id==='t'?'r':null,run_status:id==='t'?'running':null})),next_cursor:null});
    if(path.endsWith('/messages')) return Response.json({data:path.includes('/u/')?[]:[{id:1,seq:1,thread_id:'t',run_id:'r',run_status:'running',
      category:'message',event_type:'human_message',event_key:'human:h',metadata:{},created_at:time,
      content:{type:'human',message_id:'h',content:'已提交'}}]});
    if(path.endsWith('/stream')) return new Response(new ReadableStream({start(controller){streams.push({
      push:run=>controller.enqueue(new TextEncoder().encode(`event: metadata\ndata: ${JSON.stringify({thread_id:'t',run_id:'r',...run})}\n\n`)),
      close:()=>controller.close()});}}),{headers:{'Content-Type':'text/event-stream'}});
    return new Promise(resolveResponse=>snapshots.push({path,signal:init.signal,
      respondWithRun:run=>resolveResponse(run instanceof Response?run:Response.json({data:{id:'r',thread_id:'t',status:'running',...run}}))}));
  });
  const store=new ConversationStore({storage:null});
  client.update({state:'ready',startup_id:'lease',base_url:'http://127.0.0.1:45200'});
  store.setSession(client.session);
  t.after(()=>{store.setSession(null);client.update(null);});
  return {store,client,snapshots,streams,view:()=>store.getSnapshot().views.t};
}

test('进入运行会话立即读取用量且不阻塞 SSE，详情复用在读快照，开关不重建观察',async t=>{
  const {store,snapshots,streams,view}=setup(t);
  await until(()=>streams.length===1);
  assert.equal(snapshots.length,1);
  const refreshing=store.refreshRunDetails();
  assert.equal(snapshots.length,1);
  streams[0].push({status:'running'});
  await until(()=>view().verified);
  snapshots[0].respondWithRun({usage,usage_pending:false,created_at:time,updated_at:time,completed_at:null});
  await refreshing;
  await until(()=>view().run?.usage?.calls===2);
  assert.equal(view().run.usage.total_tokens,999,'服务端总量不由分项重算');
  assert.equal(streams.length,1);
  assert.equal(view().snapshotRead.phase,'ready');
});

test('旧快照不能清新用量、错误、结束时间或回退有效 SSE 状态，刷新相同更新时间可补晚量',async t=>{
  const {store,snapshots,streams,view}=setup(t);
  await until(()=>snapshots.length===1 && streams.length===1);
  streams[0].push({status:'error',usage,usage_pending:true,error:'真实错误',error_code:'actual_code',completed_at:time,updated_at:time});
  await until(()=>view().run?.status==='error');
  snapshots[0].respondWithRun({usage:null,usage_pending:false,error:null,error_code:null,completed_at:null,updated_at:time});
  await until(()=>snapshots.length===2);
  snapshots[1].respondWithRun({status:'error',usage,usage_pending:true,error:'真实错误',error_code:'actual_code',completed_at:time,updated_at:time});
  await until(()=>view().snapshotRead.phase==='ready');
  assert.deepEqual(view().run.usage,usage);
  assert.equal(view().run.error,'真实错误');
  assert.equal(view().run.completed_at,time);
  assert.equal(view().run.status,'error');
  const refresh=store.refreshRunDetails();
  await until(()=>snapshots.length===3);
  const lateUsage={...usage,total_input:500,total_tokens:1000};
  snapshots[2].respondWithRun({status:'error',updated_at:time,usage:lateUsage,usage_pending:false});
  await refresh;
  assert.equal(view().run.usage.total_tokens,1000);
  assert.equal(view().run.usage_pending,false);
});

test('同 Run 审批继续撤销旧结算结论，metadata 省略保留而明确 null 为未知',async t=>{
  const {store,snapshots,streams,view}=setup(t);
  await until(()=>snapshots.length===1 && streams.length===1);
  streams[0].push({status:'interrupted',usage,usage_pending:false});
  await until(()=>view().run?.status==='interrupted');
  snapshots[0].respondWithRun({status:'interrupted'});
  await until(()=>view().snapshotRead.phase==='ready');
  const refresh=store.refreshRunDetails();
  await until(()=>snapshots.length===2);
  streams[0].push({status:'running'});
  await until(()=>view().run?.status==='running');
  assert.equal(view().run.usage_pending,null);
  assert.deepEqual(view().run.usage,usage);
  snapshots[1].respondWithRun({status:'interrupted',usage:null,usage_pending:false});
  await until(()=>snapshots.length===3);
  assert.equal(view().run.usage_pending,null);
  assert.deepEqual(view().run.usage,usage);
  snapshots[2].respondWithRun({status:'running'});
  await refresh;
  assert.equal(view().run.status,'running');
  assert.equal(view().run.usage_pending,null);
  assert.deepEqual(view().run.usage,usage);
  streams[0].push({status:'running',usage:null});
  await until(()=>view().run?.usage===null);
  streams[0].push({status:'running'});
  await tick();
  assert.equal(view().run.usage,null);
});

test('快照读取失败独立保留已知字段、草稿和正常观察；切会话使迟到响应失效',async t=>{
  const {store,snapshots,streams,view}=setup(t);
  await until(()=>snapshots.length===1 && streams.length===1);
  streams[0].push({status:'running',usage,usage_pending:true});
  await until(()=>view().verified);
  store.updateDraft('下一条原文');
  snapshots[0].respondWithRun(new Response('真实查询失败',{status:500}));
  await until(()=>view().snapshotRead.phase==='error');
  assert.equal(view().snapshotRead.failure.status,500);
  assert.equal(view().run.error,undefined);
  assert.equal(view().run.status,'running');
  assert.deepEqual(view().run.usage,usage);
  assert.equal(view().observation,'open');
  assert.equal(store.getSnapshot().drafts.t,'下一条原文');
  const refresh=store.refreshRunDetails();
  await until(()=>snapshots.length===2);
  assert.deepEqual(view().run.usage,usage,'刷新已有值不闪空');
  store.select('u');
  snapshots[1].respondWithRun({usage:null,status:'completed'});
  await refresh;
  await until(()=>store.getSnapshot().views.u?.history==='ready');
  assert.equal(store.getSnapshot().views.u.run,null);
  assert.deepEqual(view().run.usage,usage);
  assert.equal(snapshots[1].signal.aborted,true);
});

test('公开展示明确区分未知与真实零，缺字段不补零或模型，总量不重算，时间只用服务端值',()=>{
  const snapshotRead={phase:'ready',failure:null,retry:null};
  const unknown=renderToStaticMarkup(createElement(RunUsage,{run:{thread_id:'t',run_id:'r',status:'cancelled',usage:null,usage_pending:true},snapshotRead,availability:'查看当前运行'}));
  assert.match(unknown,/暂无用量数据/); assert.match(unknown,/仍在结算/);
  assert.doesNotMatch(unknown,/<dd>0<\/dd>/);
  const zero=renderToStaticMarkup(createElement(RunUsage,{run:{thread_id:'t',run_id:'r',status:'completed',
    usage:{total_input:0,total_output:0,total_tokens:99,by_model:{}},usage_pending:false},snapshotRead,availability:'查看当前运行'}));
  assert.match(zero,/<dd>0<\/dd>/); assert.match(zero,/<dd>99<\/dd>/);
  assert.match(zero,/模型调用次数（已记录）<\/dt><dd>未提供/);
  assert.match(zero,/暂无模型分项/); assert.doesNotMatch(zero,/demo|unknown-model/);
  const noop=()=>{}, detail=renderToStaticMarkup(createElement(RunDetails,{threadId:'t',title:'当前会话',
    view:{...emptyConversation,run:{thread_id:'t',run_id:'r',status:'cancelled',created_at:time,completed_at:null}},
    availability:'查看当前运行',onRefresh:async()=>{},onReload:noop,onReconnect:noop,onQuery:async()=>{},onApproval:noop,onClose:noop}));
  assert.match(detail,/结束时间未取得/); assert.doesNotMatch(detail,/尚未结束/);
  assert.match(detail,/2026-10-06T00:00:00Z/);
  assert.equal(formatRunTime(time).utc,'2026-10-06T00:00:00Z');
  assert.equal(formatRunTime('2026-10-06T00:00:00.123456+00:00').utc,'2026-10-06T00:00:00.123456+00:00');
});

test('错误快照尚未取得可先只读显示本 Run 的真实生命周期原因，不混旧运行或查询错误',()=>{
  const noop=()=>{};
  const detail=renderToStaticMarkup(createElement(RunDetails,{threadId:'t',title:'当前会话',
    view:{...emptyConversation,run:{thread_id:'t',run_id:'r',status:'error'},
      snapshotRead:{phase:'error',failure:{status:500,message:'这是读取错误',kind:'http',recoverable:false},retry:null},
      events:{old:[{seq:1,created_at:time,category:'lifecycle',event_type:'status_changed',payload:{status:'error',message:'不属于当前运行'}}],
        r:[{seq:5,created_at:time,category:'lifecycle',event_type:'status_changed',payload:{status:'error',message:'当前真实执行说明',error_code:'actual_code'}}]}},
    availability:'查看当前运行',onRefresh:async()=>{},onReload:noop,onReconnect:noop,onQuery:async()=>{},onApproval:noop,onClose:noop}));
  assert.match(detail,/当前真实执行说明/); assert.match(detail,/actual_code/);
  assert.match(detail,/当前运行生命周期事件的错误说明/);
  assert.match(detail,/运行信息读取失败/);
  assert.doesNotMatch(detail,/不属于当前运行|<pre[^>]*>这是读取错误/);
});

test('重建 GET 观察先撤销旧 false，隐藏与租约换代拒绝迟到快照且只恢复一次读取',async t=>{
  const {store,client,snapshots,streams,view}=setup(t);
  await until(()=>snapshots.length===1 && streams.length===1);
  snapshots[0].respondWithRun({usage,usage_pending:false});
  await until(()=>view().snapshotRead.phase==='ready');
  streams[0].push({status:'running'});
  await until(()=>view().verified);
  store.reload();
  await until(()=>snapshots.length===2 && streams.length===2);
  assert.equal(view().run.usage_pending,null,'新 GET 首帧之前就撤销旧结算结论');
  assert.deepEqual(view().run.usage,usage);
  streams[1].push({status:'running'});
  await until(()=>view().observation==='open');
  assert.equal(view().run.usage_pending,null);
  assert.deepEqual(view().run.usage,usage);
  store.setVisible(false);
  snapshots[1].respondWithRun({usage:null,usage_pending:false});
  await tick();
  assert.deepEqual(view().run.usage,usage);
  assert.equal(view().run.usage_pending,null);
  client.update({state:'ready',startup_id:'new-lease',base_url:'http://127.0.0.1:45201'});
  store.setSession(client.session);
  assert.equal(snapshots.length,2);
  store.setVisible(true);
  await until(()=>snapshots.length===3 && streams.length===3);
  snapshots[2].respondWithRun({usage:null,usage_pending:true});
  await until(()=>view().snapshotRead.phase==='ready');
  assert.equal(view().run.usage,null);
  assert.equal(snapshots[1].signal.aborted,true);
});
