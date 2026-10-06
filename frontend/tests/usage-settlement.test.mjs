import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RunUsage } from '../src/components/RunDetails.tsx';

const instant='2026-10-06T00:00:00Z';
const usage={total_input:10,total_output:4,total_tokens:14,calls:1};
const waitForTurn=()=>new Promise(resolveTurn=>setImmediate(resolveTurn));
async function waitForState(checkState) {
  for(let attempt=0;attempt<200;attempt++) {if(checkState())return; await waitForTurn();}
  assert.fail('公开会话事实未就绪');
}
function createFixture(t,{status='completed'}={}) {
  t.mock.timers.enable({apis:['Date','setTimeout'],now:Date.parse(instant)});
  const requests=[],streams=[];
  let latestStatus=status;
  const client=new BackendClient(async(url,init)=>{
    const path=new URL(url).pathname;
    if(path==='/api/threads') return Response.json({data:['t','u'].map(id=>({id,title:id,user_id:null,
      created_at:instant,updated_at:instant,run_id:id==='t'?'r':null,run_status:id==='t'?latestStatus:null})),next_cursor:null});
    if(path.endsWith('/messages')) return Response.json({data:path.includes('/u/')?[]:[{
      id:1,seq:1,thread_id:'t',run_id:'r',run_status:latestStatus,category:'message',event_type:'human_message',
      event_key:'human:h',metadata:{},created_at:instant,content:{type:'human',message_id:'h',content:'已提交消息'}}]});
    if(path.endsWith('/events')) return Response.json({data:[]});
    if(path.endsWith('/stream')) return new Response(new ReadableStream({start(controller){streams.push({
      pushMetadata:run=>{latestStatus=run.status;controller.enqueue(new TextEncoder().encode(
        `event: metadata\ndata: ${JSON.stringify({thread_id:'t',run_id:'r',...run})}\n\n`));},
      closeStream:()=>controller.close()});}}),{headers:{'Content-Type':'text/event-stream'}});
    const request={path,method:init.method??'GET',signal:init.signal,at:Date.now()};
    requests.push(request);
    return new Promise(resolveResponse=>{request.respondWithRun=run=>resolveResponse(run instanceof Response?run:
      Response.json({data:{id:'r',thread_id:'t',status:latestStatus,usage,usage_pending:true,updated_at:instant,...run}}));});
  });
  const store=new ConversationStore({storage:null});
  const readySessionState={state:'ready',startup_id:'lease',base_url:'http://127.0.0.1:45200'};
  client.update(readySessionState);store.setSession(client.session);
  t.after(()=>{store.setSession(null);client.update(null);});
  const advanceClock=async milliseconds=>{t.mock.timers.tick(milliseconds);for(let turn=0;turn<15;turn++)await waitForTurn();};
  return {store,client,requests,streams,readySessionState,advanceClock,readView:()=>store.getSnapshot().views.t};
}

test('后续核实从请求完成计时，最多十二次；普通刷新和关详情不重置预算，手动继续开启新轮',async t=>{
  const {store,requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);
  requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(4999);assert.equal(requests.length,1);
  await advanceClock(1);assert.equal(requests.length,2);
  await advanceClock(15000);assert.equal(requests.length,2,'慢请求期间不叠轮询');
  for(let followUp=1;followUp<=12;followUp++) {
    requests.at(-1).respondWithRun({});
    await waitForState(()=>readView().snapshotRead.phase==='ready');
    if(followUp<12) {await advanceClock(4999);assert.equal(requests.length,followUp+1);await advanceClock(1);}
  }
  assert.equal(requests.length,13);
  assert.equal(readView().usageVerification.pauseReason,'limit');
  assert.equal(readView().usageVerification.requests,12);
  store.setDetailsOpen(true);store.setDetailsOpen(false);
  await advanceClock(60000);assert.equal(requests.length,13);
  const refreshing=store.refreshRunDetails();await waitForState(()=>requests.length===14);
  requests.at(-1).respondWithRun({});await refreshing;
  await advanceClock(10000);assert.equal(requests.length,14,'普通刷新不会重置已耗尽预算');
  const continuing=store.continueUsageVerification();await waitForState(()=>requests.length===15);
  requests.at(-1).respondWithRun({});await continuing;
  await advanceClock(5000);assert.equal(requests.length,16);
  requests.at(-1).respondWithRun({usage_pending:false});
  await waitForState(()=>readView().run.usage_pending===false);
  await advanceClock(60000);assert.equal(requests.length,16);
  assert.ok(requests.every(request=>request.method==='GET'));
});

test('running 不轮询；正常等待审批 EOF 合并一次补读，省略 pending 和重复详情通知不会造已结算',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running',usage_pending:true});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'running'});
  await waitForState(()=>readView().observation==='open');
  await advanceClock(60000);assert.equal(requests.length,1);
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});
  streams[0].closeStream();
  await waitForState(()=>requests.length===2);
  store.setDetailsOpen(true);store.setDetailsOpen(true);
  const refreshing=store.refreshRunDetails();
  assert.equal(requests.length,2);
  requests[1].respondWithRun({status:'interrupted'});await refreshing;
  assert.equal(readView().usageVerification.requests,0,'EOF 首次补读不消耗后续预算');
  assert.equal(readView().run.usage_pending,true);
  await advanceClock(5000);assert.equal(requests.length,3);
  requests[2].respondWithRun({status:'interrupted',usage_pending:false});
  await waitForState(()=>readView().run.usage_pending===false);
  await advanceClock(60000);assert.equal(requests.length,3);
});

test('同一核实任务按 1/2/5 秒重试三次，所有失败计入十二次，成功 true 不重置预算',async t=>{
  const {requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(5000);assert.equal(requests.length,2);
  requests.at(-1).respondWithRun(new Response('busy',{status:503}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===1);
  await advanceClock(999);assert.equal(requests.length,2);await advanceClock(1);assert.equal(requests.length,3);
  requests.at(-1).respondWithRun(new Response('busy',{status:503}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===2);
  await advanceClock(1999);assert.equal(requests.length,3);await advanceClock(1);assert.equal(requests.length,4);
  requests.at(-1).respondWithRun(new Response('busy',{status:503}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===3);
  await advanceClock(4999);assert.equal(requests.length,4);await advanceClock(1);assert.equal(requests.length,5);
  requests.at(-1).respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().usageVerification.requests,4);
  await advanceClock(5000);assert.equal(requests.length,6);
  requests.at(-1).respondWithRun({usage_pending:false});
  await waitForState(()=>readView().run.usage_pending===false);
});

test('三次自动重试仍失败后停止，不由五秒任务绕过；保留用量、草稿、Run 结果和读取错误',async t=>{
  const {store,requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');store.updateDraft('仍然可编辑');
  await advanceClock(5000);
  for(let attempt=0;attempt<4;attempt++) {
    requests.at(-1).respondWithRun(new Response('busy',{status:503}));
    if(attempt<3) {await waitForState(()=>readView().snapshotRead.retry?.attempt===attempt+1);await advanceClock([1000,2000,5000][attempt]);}
  }
  await waitForState(()=>readView().snapshotRead.phase==='error');
  assert.equal(readView().usageVerification.pauseReason,'error');
  assert.equal(readView().usageVerification.requests,4);
  await advanceClock(120000);assert.equal(requests.length,5);
  assert.deepEqual(readView().run.usage,usage);assert.equal(readView().run.status,'completed');
  assert.equal(readView().run.error,undefined);assert.equal(store.getSnapshot().drafts.t,'仍然可编辑');
  const continuing=store.continueUsageVerification();await waitForState(()=>requests.length===6);
  requests.at(-1).respondWithRun({usage_pending:false});await continuing;
});

test('Retry-After 与手动动作共用单一等待；隐藏主动 Abort 不报故障，返回同阶段预算保留',async t=>{
  const {store,requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');await advanceClock(5000);
  requests[1].respondWithRun(new Response('busy',{status:503,headers:{'Retry-After':'30'}}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===1);
  const refreshing=store.refreshRunDetails();
  await advanceClock(10000);assert.equal(requests.length,2);
  store.setVisible(false);await refreshing;
  await advanceClock(10000);assert.equal(requests.length,2);assert.equal(readView().snapshotRead.failure,null);
  store.setVisible(true);await waitForState(()=>readView().history==='ready');
  await advanceClock(9999);assert.equal(requests.length,2);
  await advanceClock(1);assert.equal(requests.length,3);
  requests.at(-1).respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().usageVerification.requests,1);
  await advanceClock(5000);assert.equal(requests.length,4);
  store.select('u');requests.at(-1).respondWithRun({usage:null,usage_pending:false});
  await waitForState(()=>store.getSnapshot().views.u?.history==='ready');
  await advanceClock(60000);assert.equal(requests.length,4);
  assert.deepEqual(readView().run.usage,usage);assert.equal(requests.at(-1).signal.aborted,true);
  store.select('t');await waitForState(()=>requests.length===5);
  requests.at(-1).respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().usageVerification.requests,2,'切换不会重置已发出请求的预算');
});

for(const failureKind of ['404','500','protocol']) test(`${failureKind} 立即停止核实，保留最后值且不改变执行状态`,async t=>{
  const {requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');await advanceClock(5000);
  requests.at(-1).respondWithRun(failureKind==='protocol'?Response.json({data:{id:'wrong',thread_id:'t',status:'completed'}}):
    new Response('read failed',{status:Number(failureKind)}));
  await waitForState(()=>readView().snapshotRead.phase==='error');
  await advanceClock(120000);assert.equal(requests.length,2);
  assert.deepEqual(readView().run.usage,usage);assert.equal(readView().run.status,'completed');
  assert.equal(readView().run.error,undefined);
});

test('预算耗尽后隐藏、切回与重新观察同阶段不重置；新租约允许新轮并拒绝旧响应',async t=>{
  const {store,client,requests,advanceClock,readySessionState,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  for(let followUp=0;followUp<12;followUp++) {
    await advanceClock(5000);requests.at(-1).respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  }
  store.setVisible(false);store.setVisible(true);await waitForState(()=>requests.length===14);
  requests.at(-1).respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(15000);assert.equal(requests.length,14);assert.equal(readView().usageVerification.requests,12);
  const oldRead=store.refreshRunDetails();await waitForState(()=>requests.length===15);
  client.update({...readySessionState,startup_id:'new-lease'});store.setSession(client.session);
  await waitForState(()=>requests.length===16);
  requests[14].respondWithRun({usage:null,usage_pending:false});await oldRead;
  assert.deepEqual(readView().run.usage,usage);
  requests[15].respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(5000);assert.equal(requests.length,17);assert.equal(readView().usageVerification.requests,1);
});

test('中断后继续为新执行阶段，旧组快照不能清新值；同 updated_at 的取消晚量可补',async t=>{
  const {requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>streams.length===1 && requests.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage,usage_pending:true});
  await waitForState(()=>readView().run.status==='interrupted');
  await advanceClock(5000);assert.equal(requests.length,2);
  streams[0].pushMetadata({status:'running',usage_pending:true});await waitForState(()=>readView().run.status==='running');
  requests[1].respondWithRun({status:'interrupted',usage:null,usage_pending:false});
  await waitForTurn();assert.equal(requests[1].signal.aborted,true);
  assert.equal(readView().run.usage_pending,true);assert.deepEqual(readView().run.usage,usage);
  await advanceClock(60000);assert.equal(requests.length,2,'审批继续使旧自动读取失效，running 不补另一条用量 GET');
  streams[0].pushMetadata({status:'cancelled',usage,usage_pending:true,updated_at:instant});streams[0].closeStream();
  await waitForState(()=>requests.length===3);
  requests[2].respondWithRun({status:'cancelled'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().usageVerification.requests,0);
  await advanceClock(5000);assert.equal(requests.length,4);
  requests[3].respondWithRun({status:'cancelled',usage:{...usage,total_tokens:35},usage_pending:false,updated_at:instant});
  await waitForState(()=>readView().run.usage_pending===false);
  assert.equal(readView().run.usage.total_tokens,35);assert.equal(readView().run.status,'cancelled');
});

test('摘要与详情共用暂停文案和主动继续入口，查询失败不是运行失败',()=>{
  const markup=renderToStaticMarkup(createElement(RunUsage,{run:{thread_id:'t',run_id:'r',status:'completed',usage,usage_pending:true},
    snapshotRead:{phase:'ready',failure:null,retry:null},availability:'当前运行',isCompact:true,
    verification:{phase:'paused',requests:12,pauseReason:'limit',nextAt:null,failure:null},onContinue:async()=>{}}));
  assert.match(markup,/仍在结算，自动核实已暂停/);assert.match(markup,/继续核实/);assert.doesNotMatch(markup,/运行失败/);
});

test('第十二次失败不再安排重试，不能通过错误任务突破请求上限',async t=>{
  const {requests,advanceClock,readView}=createFixture(t);
  await waitForState(()=>requests.length===1);requests[0].respondWithRun({});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  for(let followUp=0;followUp<11;followUp++) {
    await advanceClock(5000);requests.at(-1).respondWithRun({});await waitForState(()=>readView().snapshotRead.phase==='ready');
  }
  await advanceClock(5000);assert.equal(requests.length,13);
  requests.at(-1).respondWithRun(new Response('busy',{status:503,headers:{'Retry-After':'30'}}));
  await waitForState(()=>readView().snapshotRead.phase==='error');
  assert.equal(readView().usageVerification.requests,12);assert.equal(readView().usageVerification.pauseReason,'limit');
  await advanceClock(120000);assert.equal(requests.length,13);
  assert.equal(readView().run.usage_pending,true);
});

test('有效取消快照立即显示，五秒后才核实晚量，不等聊天 SSE 结束',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running',usage_pending:true});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'running'});await waitForState(()=>readView().observation==='open');
  const cancellation=store.cancel(store.cancelTarget());await waitForState(()=>requests.length===2);
  requests[1].respondWithRun({status:'cancelled',usage_pending:true,updated_at:instant});
  assert.equal(await cancellation,true);assert.equal(readView().run.status,'cancelled');
  assert.equal(readView().run.usage_pending,true);assert.equal(requests.length,2);
  await advanceClock(4999);assert.equal(requests.length,2);await advanceClock(1);assert.equal(requests.length,3);
  requests[2].respondWithRun({status:'cancelled',usage:{...usage,total_tokens:41},usage_pending:false,updated_at:instant});
  await waitForState(()=>readView().run.usage_pending===false);
  assert.equal(readView().run.usage.total_tokens,41);assert.equal(readView().run.status,'cancelled');
  await advanceClock(60000);assert.equal(requests.length,3);
});

test('同阶段 GET 重新观察不重置耗尽预算；真正 interrupted→running 后新阶段有完整预算',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>streams.length===1 && requests.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  for(let followUp=0;followUp<12;followUp++) {
    await advanceClock(5000);requests.at(-1).respondWithRun({status:'interrupted'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  }
  assert.equal(readView().usageVerification.requests,12);
  store.reload();await waitForState(()=>streams.length===2 && requests.length===14);
  streams[1].pushMetadata({status:'interrupted',usage_pending:true});
  requests[13].respondWithRun({status:'interrupted'});await waitForState(()=>requests.length===15);
  requests[14].respondWithRun({status:'interrupted'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(10000);assert.equal(requests.length,15);assert.equal(readView().usageVerification.requests,12);
  streams[1].pushMetadata({status:'running',usage_pending:true});await waitForState(()=>readView().run.status==='running');
  streams[1].pushMetadata({status:'interrupted',usage_pending:true});streams[1].closeStream();
  await waitForState(()=>requests.length===16);requests[15].respondWithRun({status:'interrupted'});
  await waitForState(()=>readView().snapshotRead.phase==='ready');assert.equal(readView().usageVerification.requests,0);
  await advanceClock(5000);assert.equal(requests.length,17);assert.equal(readView().usageVerification.requests,1);
});

test('第十二次自动 GET 在读时取消，首次确认后补读仍不计预算且与旧读串行',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  for(let followUp=0;followUp<11;followUp++) {
    await advanceClock(5000);requests.at(-1).respondWithRun({status:'interrupted'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  }
  await advanceClock(5000);assert.equal(requests.length,13);
  const cancellation=store.cancel(store.cancelTarget());await waitForState(()=>requests.length===14);
  requests[13].respondWithRun({status:'cancelled',usage_pending:true});assert.equal(await cancellation,true);
  assert.equal(requests.length,14,'旧 GET 未结束时不能并发补读');
  requests[12].respondWithRun({status:'interrupted'});await waitForState(()=>requests.length===15);
  assert.equal(readView().run.status,'cancelled');assert.equal(readView().usageVerification.requests,12);
  requests[14].respondWithRun({status:'cancelled',usage_pending:false});await waitForState(()=>readView().run.usage_pending===false);
  await advanceClock(60000);assert.equal(requests.length,15);
});

test('自动在读期间收到适用 false 立即停，不因旧组返回再安排用量查询',async t=>{
  const {requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  await advanceClock(5000);assert.equal(requests.length,2);
  streams[0].pushMetadata({status:'interrupted',usage:{...usage,total_tokens:97},usage_pending:false});
  await waitForState(()=>readView().run.usage_pending===false);
  requests[1].respondWithRun({status:'interrupted',usage:null,usage_pending:true});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  await advanceClock(60000);assert.equal(requests.length,2);
  assert.equal(readView().run.usage_pending,false);assert.equal(readView().run.usage.total_tokens,97);
});

test('第十二次遇到过时同组仍 true，拒绝超预算补读后结束 reading，继续核实入口可用',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  for(let followUp=0;followUp<11;followUp++) {
    await advanceClock(5000);requests.at(-1).respondWithRun({status:'interrupted'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  }
  await advanceClock(5000);
  streams[0].pushMetadata({status:'interrupted',usage:{...usage,total_tokens:99},usage_pending:true});
  await waitForState(()=>readView().run.usage.total_tokens===99);
  requests[12].respondWithRun({status:'interrupted'});
  await waitForState(()=>readView().usageVerification.pauseReason==='limit');
  assert.equal(readView().snapshotRead.phase,'ready','配额拒绝不应将 UI 永久留在读取中');
  const markup=renderToStaticMarkup(createElement(RunUsage,{run:readView().run,snapshotRead:readView().snapshotRead,
    verification:readView().usageVerification,availability:'当前运行',onContinue:store.continueUsageVerification}));
  assert.doesNotMatch(markup,/<button[^>]*disabled[^>]*>继续核实/);
  await advanceClock(60000);assert.equal(requests.length,13);
  const continuing=store.continueUsageVerification();await waitForState(()=>requests.length===14);
  requests[13].respondWithRun({status:'interrupted',usage:{...usage,total_tokens:99},usage_pending:false});await continuing;
  assert.equal(readView().run.usage.total_tokens,99);assert.equal(readView().run.usage_pending,false);
});

test('审批继续主动停止旧阶段自动重试，旧失败不能暂停新阶段待结算轮次',async t=>{
  const {requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  await advanceClock(5000);requests[1].respondWithRun(new Response('old stage busy',{status:503}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===1);
  streams[0].pushMetadata({status:'running',usage_pending:true});await waitForState(()=>readView().run.status==='running');
  assert.equal(requests[1].signal.aborted,true);
  await advanceClock(60000);assert.equal(requests.length,2);
  assert.equal(readView().snapshotRead.failure,null);assert.equal(readView().usageVerification.pauseReason,null);
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});streams[0].closeStream();
  await waitForState(()=>requests.length===3);requests[2].respondWithRun({status:'interrupted'});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().usageVerification.requests,0);assert.equal(readView().usageVerification.pauseReason,null);
  await advanceClock(5000);assert.equal(requests.length,4);
  requests[3].respondWithRun({status:'interrupted',usage_pending:false});await waitForState(()=>readView().run.usage_pending===false);
});

test('旧阶段手动详情读取失败只归属旧轮次，不把失败暂停写入新阶段预算',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  const refreshing=store.refreshRunDetails();await waitForState(()=>requests.length===2);
  streams[0].pushMetadata({status:'running',usage_pending:true});await waitForState(()=>readView().run.status==='running');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  requests[1].respondWithRun(new Response('old manual read failed',{status:500}));await refreshing;
  assert.equal(readView().run.status,'interrupted');assert.equal(readView().run.error,undefined);
  assert.equal(readView().usageVerification.pauseReason,null,'旧手动失败不能停新阶段自动轮次');
  assert.equal(readView().usageVerification.requests,0);
  await advanceClock(4999);assert.equal(requests.length,2);await advanceClock(1);assert.equal(requests.length,3);
  requests[2].respondWithRun({status:'interrupted',usage_pending:false});await waitForState(()=>readView().run.usage_pending===false);
});

test('旧阶段手动 GET 的三次恢复不消耗新阶段预算，结束后新轮仍按完成加五秒启动',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  const refreshing=store.refreshRunDetails();await waitForState(()=>requests.length===2);
  streams[0].pushMetadata({status:'running',usage_pending:true});await waitForState(()=>readView().run.status==='running');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  for(let retryAttempt=0;retryAttempt<4;retryAttempt++) {
    requests.at(-1).respondWithRun(new Response('old manual busy',{status:503}));
    if(retryAttempt<3) {await waitForState(()=>readView().snapshotRead.retry?.attempt===retryAttempt+1);await advanceClock([1000,2000,5000][retryAttempt]);}
  }
  await refreshing;
  assert.equal(readView().usageVerification.pauseReason,null);assert.equal(readView().usageVerification.requests,0);
  assert.equal(requests.length,5);
  await advanceClock(4999);assert.equal(requests.length,5);await advanceClock(1);assert.equal(requests.length,6);
  assert.equal(readView().usageVerification.requests,1);
  requests[5].respondWithRun({status:'interrupted',usage_pending:false});await waitForState(()=>readView().run.usage_pending===false);
});

test('同阶段 false 立即停止自动错误等待与重试，明确手动刷新仍能读取',async t=>{
  const {store,requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  await advanceClock(5000);requests[1].respondWithRun(new Response('busy',{status:503,headers:{'Retry-After':'30'}}));
  await waitForState(()=>readView().snapshotRead.retry?.attempt===1);
  streams[0].pushMetadata({status:'interrupted',usage_pending:false});await waitForState(()=>readView().run.usage_pending===false);
  assert.equal(requests[1].signal.aborted,true,'有效 false 不能仅清计时器而留自动错误恢复活跃');
  await advanceClock(60000);assert.equal(requests.length,2);assert.equal(readView().snapshotRead.failure,null);
  const refreshing=store.refreshRunDetails();await waitForState(()=>requests.length===3);
  assert.equal(requests[2].signal.aborted,false,'主动快照刷新不受自动核实停止规则影响');
  requests[2].respondWithRun({status:'interrupted',usage_pending:false});await refreshing;
  assert.equal(readView().run.usage_pending,false);assert.equal(readView().run.status,'interrupted');
});

test('EOF 已合并自动在读 GET 时，旧读 false 不吞首次边界补读，时间由新快照确认',async t=>{
  const {requests,streams,advanceClock,readView}=createFixture(t,{status:'running'});
  await waitForState(()=>requests.length===1 && streams.length===1);
  requests[0].respondWithRun({status:'running'});await waitForState(()=>readView().snapshotRead.phase==='ready');
  streams[0].pushMetadata({status:'interrupted',usage_pending:true});await waitForState(()=>readView().run.status==='interrupted');
  await advanceClock(5000);assert.equal(requests.length,2);
  streams[0].closeStream();await waitForState(()=>readView().observation==='closed');
  assert.equal(requests.length,2,'正常 EOF 不并发打开第二个读');
  requests[1].respondWithRun({status:'interrupted',usage_pending:false});
  await waitForState(()=>requests.length===3);
  const confirmedTime='2026-10-06T00:01:00Z';
  requests[2].respondWithRun({status:'interrupted',usage_pending:false,updated_at:confirmedTime});
  await waitForState(()=>readView().snapshotRead.phase==='ready');
  assert.equal(readView().run.updated_at,confirmedTime);assert.equal(readView().usageVerification.requests,1);
  await advanceClock(60000);assert.equal(requests.length,3);assert.equal(readView().run.usage_pending,false);
});
