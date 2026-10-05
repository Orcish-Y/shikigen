import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const date = '2026-10-05T00:00:00Z';
const ready = {revision:1, startup_id:'lease', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null};
const record = (seq, content, extra={}) => ({id:seq, thread_id:'a', run_id:'r', run_status:'running', seq,
  category:'message', event_type:content.type + '_message', event_key:content.type + ':' + content.message_id,
  content, metadata:{}, created_at:date, ...extra});
const human = record(2, {type:'human', message_id:'entry', content:'原文'});
const ai = record(3, {type:'ai', message_id:'answer', content:'  已生成\n    正文 ', tool_calls:[], generation_status:'cancelled'});
const encode = (event, data) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
async function until(probe) {
  for (let i=0;i<200;i++) {if (probe()) return; await new Promise(resolve => setImmediate(resolve));}
  assert.fail('公开状态未达到预期');
}
async function setup(cancel, options={}) {
  let stream, status = options.status ?? 'running', posts=0, reads=0, snapshots=0;
  const client = new BackendClient(async (url, init) => {
    const path = new URL(url).pathname;
    if (path === '/api/threads') return Response.json({data:[{id:'a', title:null, user_id:null, created_at:date, updated_at:date, run_id:'r', run_status:status}], next_cursor:null});
    if (path.endsWith('/cancel')) {posts++; return cancel({setStatus:value=>status=value});}
    if (path.endsWith('/runs/r/messages')) {reads++; return options.messages?.(reads) ?? Response.json({data:[human, {...ai, run_status:status}]});}
    if (path.endsWith('/messages')) return Response.json({data:[{...human, run_status:status}]});
    if (path.endsWith('/stream')) return new Response(new ReadableStream({start:controller=> {
      stream=controller;
      controller.enqueue(encode('metadata', {thread_id:'a', run_id:'r', status}));
      controller.enqueue(encode('delta', {message_id:'answer', seq:3, field:'content', value:'  已生成\n'}));
    }}), {headers:{'Content-Type':'text/event-stream'}});
    snapshots++; return options.snapshot?.(snapshots) ?? Response.json({data:{id:'r', thread_id:'a', status}});
  });
  const store = new ConversationStore({storage:null});
  client.update(ready); store.setSession(client.session);
  await until(()=>store.getSnapshot().views.a?.verified);
  return {store, client, stream:()=>stream, posts:()=>posts, reads:()=>reads, snapshots:()=>snapshots,
    close:()=>{store.setSession(null);client.update(null);}};
}

test('有效取消快照即结束 pending，不等待 SSE；终态一次补读完整事实并替换预览', async()=> {
  let response;
  const app = await setup(({setStatus}) => new Promise(resolve => response=()=> {
    setStatus('cancelled'); resolve(Response.json({data:{id:'r', thread_id:'a', status:'cancelled'}}));
  }));
  try {
    app.store.updateDraft('下一条草稿');
    const target=app.store.cancelTarget();
    assert.ok(target);
    const pending=app.store.cancel(target);
    await until(()=>app.posts()===1);
    assert.equal(app.store.canCancel(), false);
    assert.equal(app.store.canSend(), false);
    assert.equal(app.store.getSnapshot().views.a.write.phase, 'pending');
    assert.equal(await app.store.cancel(target),false,'重复确认不能再发 POST');
    response(); await pending;
    await until(()=>app.reads()===1 && !app.store.getSnapshot().views.a.messages.at(-1)?.preview);
    const view=app.store.getSnapshot().views.a;
    assert.equal(view.run.status,'cancelled'); assert.equal(view.write,null);
    assert.equal(view.messages.at(-1).content.content,'  已生成\n    正文 ');
    assert.equal(app.store.getSnapshot().drafts.a,'下一条草稿');
    app.stream().enqueue(encode('metadata',{thread_id:'a',run_id:'r',status:'cancelled'}));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(app.reads(),1);
  } finally {app.close();}
});

test('取消与完成竞争按有效快照显示 completed 或 error，不伪造 cancelled', async()=> {
  for (const status of ['completed','error']) {
    const app=await setup(({setStatus}) => {setStatus(status);return Response.json({data:{id:'r',thread_id:'a',status}});});
    try {
      assert.equal(await app.store.cancel(app.store.cancelTarget()),true);
      assert.equal(app.store.getSnapshot().views.a.run.status,status);
      assert.equal(app.store.getSnapshot().views.a.write,null);
      assert.equal(app.posts(),1);
    } finally {app.close();}
  }
});

test('错误身份／非终态／损坏响应只 GET 核实；核实仍活跃恢复人工确认，不自动 POST', async()=> {
  for (const data of [{id:'wrong',thread_id:'a',status:'cancelled'}, {id:'r',thread_id:'a',status:'running'}, null]) {
    const app=await setup(()=>Response.json({data}));
    try {
      assert.equal(await app.store.cancel(app.store.cancelTarget()),false);
      assert.equal(app.posts(),1); assert.equal(app.snapshots(),1);
      const view=app.store.getSnapshot().views.a;
      assert.equal(view.run.status,'running'); assert.equal(view.write.phase,'unknown');
      assert.equal(view.write.verified,true); assert.equal(view.write.verifying,false);
      assert.ok(view.protocolIssue);
      assert.equal(app.store.canCancel(),true); assert.equal(app.store.canSend(),false);
    } finally {app.close();}
  }
});

test('等待审批取消不依赖参数解析或选择；隐藏、旧租约和旧目标零 POST', async()=> {
  const app=await setup(()=>Response.json({data:{id:'r',thread_id:'a',status:'cancelled'}}),{status:'interrupted'});
  try {
    assert.equal(app.store.getSnapshot().views.a.approval,null);
    const target=app.store.cancelTarget(); assert.ok(target);
    assert.equal(await app.store.cancel({...target,runId:'old'}),false);
    assert.equal(await app.store.cancel({...target,startupId:'old'}),false);
    app.store.setVisible(false);
    assert.equal(await app.store.cancel(target),false);
    assert.equal(app.posts(),0);
  } finally {app.close();}
});

test('取消失败尊重 Retry-After，GET 核实后才允许再次人工确认', async t=> {
  t.mock.timers.enable({apis:['Date','setTimeout'],now:Date.parse(date)});
  const app=await setup(()=>new Response('暂不可写',{status:503,headers:{'Retry-After':'10'}}));
  try {
    const pending=app.store.cancel(app.store.cancelTarget());
    await until(()=>app.store.getSnapshot().views.a.write?.verifying);
    assert.equal(app.snapshots(),0); assert.equal(app.store.canCancel(),false);
    t.mock.timers.tick(9999); await new Promise(resolve=>setImmediate(resolve));
    assert.equal(app.snapshots(),0);
    t.mock.timers.tick(1); await pending;
    assert.equal(app.snapshots(),1); assert.equal(app.posts(),1);
    assert.equal(app.store.canCancel(),true);
  } finally {app.close();}
});

test('未知取消的 GET 恢复最多三次，耗尽后保留事实并提供手动核实', async t=> {
  t.mock.timers.enable({apis:['Date','setTimeout'],now:Date.parse(date)});
  let readable=false;
  const app=await setup(()=>Promise.reject(new TypeError('cancel transport lost')), {
    snapshot:()=>{if (!readable) throw new TypeError('GET lost'); return Response.json({data:{id:'r',thread_id:'a',status:'running'}});},
  });
  try {
    const pending=app.store.cancel(app.store.cancelTarget());
    await until(()=>app.snapshots()===1);
    for (const delay of [1000,2000,5000]) {
      t.mock.timers.tick(delay); for(let i=0;i<10;i++) await new Promise(resolve=>setImmediate(resolve));
    }
    await pending;
    assert.equal(app.snapshots(),4); assert.equal(app.posts(),1);
    assert.equal(app.store.canCancel(),false);
    assert.equal(app.store.getSnapshot().views.a.write.verifying,false);
    assert.equal(app.store.getSnapshot().views.a.messages.at(-1).preview,true);
    readable=true; await app.store.queryStatus();
    assert.equal(app.snapshots(),5); assert.equal(app.store.canCancel(),true);
  } finally {app.close();}
});

test('终态内容补读失败不改终态、不丢预览；重复通知不补读，手动读取才恢复', async()=> {
  const app=await setup(({setStatus})=>{setStatus('cancelled');return Response.json({data:{id:'r',thread_id:'a',status:'cancelled'}});}, {
    messages:n=>n===1 ? new Response('read failed',{status:500}) : undefined,
  });
  try {
    await app.store.cancel(app.store.cancelTarget());
    await until(()=>app.store.getSnapshot().views.a.savedContent==='error');
    assert.equal(app.store.getSnapshot().views.a.run.status,'cancelled');
    assert.equal(app.store.getSnapshot().views.a.messages.at(-1).preview,true);
    app.stream().enqueue(encode('metadata',{thread_id:'a',run_id:'r',status:'cancelled'}));
    await new Promise(resolve=>setImmediate(resolve)); assert.equal(app.reads(),1);
    await app.store.retrySavedContent();
    assert.equal(app.reads(),2);
    assert.equal(app.store.getSnapshot().views.a.savedContent,'ready');
    assert.equal(app.store.getSnapshot().views.a.messages.at(-1).preview,undefined);
  } finally {app.close();}
});
