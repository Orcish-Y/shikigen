import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { RunProjection } from '../src/run-projection.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { RunEvents } from '../src/components/RunEvents.tsx';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const time='2026-10-06T00:00:00Z';
const createLifecycleEvent=(seq,status='running')=>({seq,created_at:time,category:'lifecycle',event_type:'status_changed',payload:{status}});

test('公开事件查询和 SSE 共用校验，原字段、空洞、乱序保留，重复重放只保留原事实',async()=>{
  let receivedRequest;
  const events=[createLifecycleEvent(9,'completed'),createLifecycleEvent(2),createLifecycleEvent(2)];
  const client=new BackendClient(async(url,init)=>{
    receivedRequest={url,init};return Response.json({data:events});
  });
  client.update({state:'ready',startup_id:'lease',base_url:'http://127.0.0.1:45200'});
  const history=await client.session.getRunEvents('会话','运行');
  assert.equal(receivedRequest.init.cache,'no-store');
  assert.match(receivedRequest.url,/%E4%BC%9A%E8%AF%9D\/runs\/%E8%BF%90%E8%A1%8C\/events$/);
  const projection=new RunProjection();
  projection.metadata({thread_id:'会话',run_id:'运行',status:'running'});
  projection.mergeEvents('运行',history);
  projection.mergeEvent('运行',createLifecycleEvent(9,'completed'));
  assert.deepEqual(projection.snapshot().events['运行'],[createLifecycleEvent(2),createLifecycleEvent(9,'completed')]);
  assert.equal(projection.run.status,'running','历史生命周期不改当前状态');
  projection.mergeEvents('运行',[]);
  assert.equal(projection.snapshot().events['运行'].length,2,'查询缺项不删除');
  assert.throws(()=>projection.mergeEvents('运行',[createLifecycleEvent(12),createLifecycleEvent(9,'cancelled')]),/协议问题/);
  assert.deepEqual(projection.snapshot().events['运行'],[createLifecycleEvent(2),createLifecycleEvent(9,'completed')],'整批冲突只读保留');
  client.update(null);
});

const waitForTurn=()=>new Promise(resolveTick=>setImmediate(resolveTick));
async function waitForState(checkState) {
  for(let attempt=0;attempt<300;attempt++){if(checkState())return;await waitForTurn();}
  assert.fail('公开运行记录未达到预期');
}
function createEventWorkbench(t) {
  const queries=[],snapshots=[],streams=[],requests=[];
  const client=new BackendClient(async(url,init)=>{
    const path=new URL(url).pathname;requests.push({path,method:init.method ?? 'GET',signal:init.signal});
    if(path==='/api/threads') return Response.json({data:['t','u'].map(id=>({id,title:null,user_id:null,
      created_at:time,updated_at:time,run_id:id==='t'?'r':null,run_status:id==='t'?'running':null})),next_cursor:null});
    if(path.endsWith('/messages')) return Response.json({data:path.includes('/u/')?[]:[{id:1,seq:2,
      thread_id:'t',run_id:'r',run_status:'running',category:'message',event_type:'human_message',event_key:'human:h',
      metadata:{},created_at:time,content:{type:'human',message_id:'h',content:'真实正文'}}]});
    if(path.endsWith('/cancel')) return Response.json({data:{id:'r',thread_id:'t',status:'cancelled',usage_pending:false}});
    if(path.endsWith('/stream')) return new Response(new ReadableStream({start(controller){streams.push({
      pushFrame:(event,payload)=>controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`)),
      closeStream:()=>controller.close()});}}),{headers:{'Content-Type':'text/event-stream'}});
    const queue=path.endsWith('/events')?queries:snapshots;
    return new Promise(resolveResponse=>queue.push({path,signal:init.signal,
      respondWithBody:value=>resolveResponse(value instanceof Response?value:Response.json({data:value}))}));
  });
  const store=new ConversationStore({storage:null});
  client.update({state:'ready',startup_id:'lease',base_url:'http://127.0.0.1:45200'});
  store.setSession(client.session);
  t.after(()=>{store.setDetailsOpen(false);store.setSession(null);client.update(null);});
  return {store,client,queries,snapshots,streams,requests,readView:()=>store.getSnapshot().views.t};
}

test('详情并行读取，刷新各自复用请求，一区失败保留另一区事实与观察',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  await waitForState(()=>readView().verified);
  assert.equal(queries.length,0,'进入会话不主动读全量事件');
  store.setDetailsOpen(true);
  const readTask=store.refreshDetails();
  await waitForState(()=>queries.length===1);
  assert.equal(snapshots.length,1);
  snapshots[0].respondWithBody(new Response('快照失败',{status:500}));
  queries[0].respondWithBody([createLifecycleEvent(8,'completed'),createLifecycleEvent(1)]);
  await readTask;
  assert.equal(readView().snapshotRead.phase,'error');
  assert.equal(readView().eventRead.phase,'ready');
  assert.deepEqual(readView().events.r.map(event=>event.seq),[1,8]);
  assert.equal(readView().run.status,'running');
  assert.equal(readView().run.error,undefined);
  const eventsOnly=store.refreshRunEvents();
  await waitForState(()=>queries.length===2);
  assert.equal(readView().events.r.length,2,'正在刷新保留事实');
  queries[1].respondWithBody([createLifecycleEvent(9),createLifecycleEvent(8,'cancelled')]);
  await eventsOnly;
  assert.equal(readView().eventRead.failure.kind,'protocol');
  assert.deepEqual(readView().events.r.map(event=>event.seq),[1,8]);
  assert.equal(readView().observation,'open');
  store.setDetailsOpen(false);
  assert.equal(streams.length,1);
});

test('取消确认前事件请求只合并一次确认后补读，取消响应和终态不伪造事件',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified && readView().snapshotRead.phase==='ready');
  store.setDetailsOpen(true);
  await waitForState(()=>queries.length===1);
  assert.equal(await store.cancel(store.cancelTarget()),true);
  assert.equal(readView().run.status,'cancelled');
  assert.equal(readView().events.r,undefined,'HTTP 200 和取消终态不造记录');
  assert.equal(queries.length,1,'确认前在读不重叠');
  queries[0].respondWithBody([createLifecycleEvent(1)]);
  await waitForState(()=>queries.length===2);
  queries[1].respondWithBody([createLifecycleEvent(1),createLifecycleEvent(6,'cancelled')]);
  await waitForState(()=>readView().eventRead.phase==='ready');
  assert.deepEqual(readView().events.r.map(event=>event.seq),[1,6]);
  await waitForTurn();
  assert.equal(queries.length,2);
});

test('关闭详情只作废专属读取，保留 SSE；重新打开的缺项不删除，切会话拒绝迟到响应',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified);
  store.setDetailsOpen(true);
  const reading=store.refreshRunEvents();
  await waitForState(()=>queries.length===1);
  store.setDetailsOpen(false);
  assert.equal(queries[0].signal.aborted,true);
  queries[0].respondWithBody([createLifecycleEvent(9)]);
  await reading;
  assert.equal(readView().events.r,undefined);
  streams[0].pushFrame('event',createLifecycleEvent(1));
  await waitForState(()=>readView().events.r?.length===1);
  assert.equal(readView().observation,'open');
  store.setDetailsOpen(true);
  await waitForState(()=>queries.length===2);
  queries[1].respondWithBody([]);
  await waitForState(()=>readView().eventRead.phase==='ready');
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
  const previousReadTask=store.refreshRunEvents();
  await waitForState(()=>queries.length===3);
  store.select('u');
  queries[2].respondWithBody([createLifecycleEvent(12,'error')]);
  await previousReadTask;
  await waitForState(()=>store.getSnapshot().views.u?.history==='ready');
  assert.equal(queries[2].signal.aborted,true);
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
  assert.equal(store.getSnapshot().views.u.run,null);
});

test('未校验响应整批留在只读问题中，不形成消息或当前审批，也不伪造运行失败',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified);
  store.setDetailsOpen(true);
  await waitForState(()=>queries.length===1);
  const invalidEvent={seq:5,created_at:time,category:'approval',event_type:'required',payload:{status:'required',
    checkpoint:{configurable:{thread_id:'other',checkpoint_ns:'',checkpoint_id:'c'}},interrupts:[{id:'i',namespace:'',value:{}}]}};
  queries[0].respondWithBody([createLifecycleEvent(1),invalidEvent]);
  await waitForState(()=>readView().eventRead.phase==='error');
  assert.equal(readView().events.r,undefined);
  assert.equal(readView().approval,null);
  assert.equal(readView().messages.length,1);
  assert.equal(readView().run.status,'running');
  assert.deepEqual(readView().eventRead.failure.raw,invalidEvent);
});

test('正常等待审批 EOF 触发一次补读，metadata 本身不造终态事件',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified);
  store.setDetailsOpen(true);
  await waitForState(()=>queries.length===1);
  queries[0].respondWithBody([]);
  await waitForState(()=>readView().eventRead.phase==='ready');
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'interrupted'});
  await waitForState(()=>readView().run.status==='interrupted');
  assert.equal(queries.length,1);
  assert.equal(readView().events.r,undefined);
  streams[0].closeStream();
  await waitForState(()=>queries.length===2 && snapshots.length===2);
  queries[1].respondWithBody([createLifecycleEvent(6,'interrupted')]);
  snapshots[1].respondWithBody({id:'r',thread_id:'t',status:'interrupted'});
  await waitForState(()=>readView().eventRead.phase==='ready');
  assert.deepEqual(readView().events.r,[createLifecycleEvent(6,'interrupted')]);
  assert.equal(readView().observation,'closed');
});

test('事件展示使用真实类别、时间和序号；过滤空态不同于未取得，载荷链接和图片只作原文',()=>{
  const eventRead={phase:'ready',isLoaded:true,failure:null,retry:null},onRefresh=async()=>{},onView=()=>{};
  const message={seq:4,created_at:time,category:'message',event_type:'created',payload:{type:'human',message_id:'h',content:'![图](local.png) [网页](https://example.org)'}};
  const filteredMarkup=renderToStaticMarkup(createElement(RunEvents,{events:[message],eventRead,onRefresh,onView}));
  assert.match(filteredMarkup,/暂无运行或审批事件/);
  assert.doesNotMatch(filteredMarkup,/暂无已提交事件|<img|<a /);
  const emptyMarkup=renderToStaticMarkup(createElement(RunEvents,{events:[],eventRead,onRefresh,onView}));
  assert.match(emptyMarkup,/暂无已提交事件/);
  const pendingMarkup=renderToStaticMarkup(createElement(RunEvents,{events:[],eventRead:{...eventRead,isLoaded:false,phase:'reading'},onRefresh,onView}));
  assert.match(pendingMarkup,/正在读取运行记录/);assert.doesNotMatch(pendingMarkup,/暂无已提交事件/);
  const eventMarkup=renderToStaticMarkup(createElement(RunEvents,{events:[{...createLifecycleEvent(7,'error'),payload:{status:'error',message:'![图片](x.png) https://example.org/raw',error_code:'true_code'}}],eventRead,onRefresh,onView}));
  assert.match(eventMarkup,/seq 7|2026-10-06T00:00:00Z/);assert.match(eventMarkup,/true_code/);
  assert.doesNotMatch(eventMarkup,/<img|<a /);assert.match(eventMarkup,/复制完整事件|完整事件 JSON/);
});

test('事件 503 重试遵守 Retry-After，关闭即停止等待，既有事实和快照保持',async t=>{
  t.mock.timers.enable({apis:['setTimeout','Date'],now:Date.parse(time)});
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified);
  store.setDetailsOpen(true);
  const task=store.refreshRunEvents();
  await waitForState(()=>queries.length===1);
  queries[0].respondWithBody(new Response('busy',{status:503,headers:{'Retry-After':'30'}}));
  await waitForState(()=>readView().eventRead.retry?.attempt===1);
  t.mock.timers.tick(29000);await waitForTurn();
  assert.equal(queries.length,1);
  store.setDetailsOpen(false);
  await task;
  t.mock.timers.tick(30000);await waitForTurn();
  assert.equal(queries.length,1);
  assert.equal(readView().eventRead.phase,'idle');
  assert.equal(readView().snapshotRead.phase,'ready');
  assert.equal(readView().run.status,'running');
});

test('事件自动重试最多三次，达到上限保留 SSE 事实，手动刷新可恢复',async t=>{
  t.mock.timers.enable({apis:['setTimeout','Date'],now:Date.parse(time)});
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  streams[0].pushFrame('event',createLifecycleEvent(1));
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified && readView().events.r?.length===1);
  store.setDetailsOpen(true);
  await waitForState(()=>queries.length===1);
  for(let attempt=0;attempt<4;attempt++) {
    queries[attempt].respondWithBody(new Response('busy',{status:503}));
    if(attempt<3){
      await waitForState(()=>readView().eventRead.retry?.attempt===attempt+1);
      t.mock.timers.tick([1000,2000,5000][attempt]);
      await waitForState(()=>queries.length===attempt+2);
    }
  }
  await waitForState(()=>readView().eventRead.phase==='error');
  t.mock.timers.tick(30000);await waitForTurn();
  assert.equal(queries.length,4);
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
  assert.equal(readView().run.status,'running');
  const readTask=store.refreshRunEvents();
  await waitForState(()=>queries.length===5);
  queries[4].respondWithBody([createLifecycleEvent(1)]);
  await readTask;
  assert.equal(readView().eventRead.phase,'ready');
});

test('新后端租约废止旧事件响应，详情为新租约重读一次并保留已确认事实',async t=>{
  const {store,client,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  streams[0].pushFrame('event',createLifecycleEvent(1));
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified && readView().events.r?.length===1);
  store.setDetailsOpen(true);
  const previousLeaseReadTask=store.refreshRunEvents();
  await waitForState(()=>queries.length===1);
  client.update({state:'ready',startup_id:'lease2',base_url:'http://127.0.0.1:45201'});
  store.setSession(client.session);
  queries[0].respondWithBody([createLifecycleEvent(99,'error')]);
  await previousLeaseReadTask;
  await waitForState(()=>queries.length===2 && streams.length===2);
  assert.equal(queries[0].signal.aborted,true);
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
  queries[1].respondWithBody([]);
  await waitForState(()=>readView().eventRead.phase==='ready');
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
});

test('事件 404、500 和坏 JSON 均停止自动重试，分区保留快照与原事实，坏正文可只读核对',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  streams[0].pushFrame('event',createLifecycleEvent(1));
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified && readView().events.r?.length===1);
  store.setDetailsOpen(true);
  for(const [index,response] of [new Response('missing',{status:404}),new Response('query failed',{status:500}),new Response('{broken JSON')].entries()) {
    const reading=store.refreshRunEvents();
    await waitForState(()=>queries.length===index+1);
    queries[index].respondWithBody(response);
    await reading;
    assert.equal(readView().eventRead.phase,'error');
    assert.equal(readView().eventRead.retry,null);
    assert.equal(readView().snapshotRead.phase,'ready');
    assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
    assert.equal(readView().run.error,undefined);
    assert.equal(readView().observation,'open');
    assert.equal(readView().eventRead.failure.recoverable,false);
  }
  assert.equal(readView().eventRead.failure.kind,'protocol');
  assert.equal(readView().eventRead.failure.raw,'{broken JSON');
  assert.equal(queries.length,3);
});

test('持久记录不兼容的结构化 500 只展示诊断原文，不接入事实或自动重试',async t=>{
  const {store,queries,snapshots,streams,readView}=createEventWorkbench(t);
  await waitForState(()=>streams.length===1 && snapshots.length===1);
  streams[0].pushFrame('metadata',{thread_id:'t',run_id:'r',status:'running'});
  streams[0].pushFrame('event',createLifecycleEvent(1));
  snapshots[0].respondWithBody({id:'r',thread_id:'t',status:'running'});
  await waitForState(()=>readView().verified && readView().events.r?.length===1);
  store.setDetailsOpen(true);
  const reading=store.refreshRunEvents();
  await waitForState(()=>queries.length===1);
  const rawEvent={seq:90,category:'lifecycle',event_type:'run_future',content:{status:'future',extra:{path:'![原文](x.png)'}}};
  queries[0].respondWithBody(Response.json({detail:{code:'invalid_run_event',raw_event:rawEvent}},{status:500}));
  await reading;
  assert.equal(readView().eventRead.phase,'error');
  assert.equal(readView().eventRead.failure.kind,'protocol');
  assert.deepEqual(readView().eventRead.failure.raw,rawEvent);
  assert.equal(readView().eventRead.retry,null);
  assert.deepEqual(readView().events.r,[createLifecycleEvent(1)]);
  assert.equal(readView().snapshotRead.phase,'ready');
  assert.equal(readView().run.status,'running');
  assert.equal(readView().observation,'open');
  assert.equal(queries.length,1);
});
