import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const instant = '2026-10-05T00:00:00Z';
const row = (id='t', fields={}) => ({id, title:id, user_id:null, created_at:instant,
  updated_at:instant, run_id:null, run_status:null, ...fields});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(probe) {
  for(let i=0;i<100;i++) {if(probe()) return; await tick();}
  assert.fail('会话状态未就绪');
}
function fixture(t, fetcher) {
  t.mock.timers.enable({apis:['Date','setTimeout'], now:Date.parse(instant)});
  const calls = [];
  const client = new BackendClient(async (input, init) => {
    const url = new URL(input);
    calls.push({url, init, at:Date.now()});
    return fetcher(url, init);
  });
  const store = new ConversationStore({storage:null});
  const ready = {state:'ready', startup_id:'one', base_url:'http://127.0.0.1:1'};
  client.update(ready);
  store.setSession(client.session);
  t.after(() => {store.setSession(null); client.update(null);});
  const advance = async ms => {t.mock.timers.tick(ms); for(let i=0;i<10;i++) await tick();};
  return {store, client, calls, ready, advance};
}
const lists = calls => calls.filter(call => call.url.pathname === '/api/threads');
const human = (run_id, seq, run_status='running') => ({id:seq, thread_id:'t', run_id, run_status, seq,
  category:'message', event_type:'human_message', event_key:`human:m${seq}`, metadata:{}, created_at:instant,
  content:{type:'human', message_id:`m${seq}`, content:`任务${run_id}`}});
const metadata = run_id => new Response(new ReadableStream({start(controller) {
  controller.enqueue(new TextEncoder().encode(`event: metadata\ndata: ${JSON.stringify({thread_id:'t', run_id, status:'running'})}\n\n`));
}}), {headers:{'content-type':'text/event-stream'}});

test('visible ready polls page one after five seconds and never overlaps a slow list request', async t => {
  let resolvePoll, reads = 0;
  const {store, calls, advance} = fixture(t, url => {
    if(url.pathname !== '/api/threads') return Response.json({data:[]});
    if(++reads === 2) return new Promise(resolve => resolvePoll = resolve);
    return Response.json({data:[row()], next_cursor:null});
  });
  await until(() => store.getSnapshot().views.t?.verified);
  await advance(4999);
  assert.equal(lists(calls).length, 1);
  await advance(1);
  assert.equal(lists(calls).length, 2);
  await advance(15000);
  assert.equal(lists(calls).length, 2);
  resolvePoll(Response.json({data:[row()], next_cursor:null}));
  await until(() => !store.getSnapshot().listing);
  await advance(5000);
  assert.equal(lists(calls).length, 3);
  assert.ok(lists(calls).every(call => call.url.searchParams.get('limit') === '20' && !call.url.searchParams.has('cursor')));
});

test('a different list run is verified through history before switching streams; stale summaries cannot reclaim the target', async t => {
  let resolveHistory, reads=0, summaryRun='r1';
  const {store, calls, advance} = fixture(t, url => {
    if(url.pathname === '/api/threads') return Response.json({data:[row('t',{run_id:summaryRun, run_status:'running'})], next_cursor:null});
    if(url.pathname.endsWith('/messages')) {
      if(++reads === 1) return Response.json({data:[human('r1',1)]});
      if(reads === 2) return new Promise(resolve => resolveHistory=resolve);
      return Response.json({data:[human('r1',1), human('r2',2)]});
    }
    return metadata(url.pathname.includes('/r2/') ? 'r2' : 'r1');
  });
  await until(() => store.getSnapshot().views.t?.observation === 'open');
  store.updateDraft('新运行也保留');
  summaryRun='r2';
  await advance(5000);
  assert.equal(reads, 2);
  const old = calls.find(call => call.url.pathname.endsWith('/stream'));
  assert.equal(old.init.signal.aborted, false, '核实历史前保留原观察');
  assert.equal(store.getSnapshot().views.t.run.run_id, 'r1');
  resolveHistory(Response.json({data:[human('r1',1,'completed'), human('r2',2)]}));
  await until(() => store.getSnapshot().views.t?.run?.run_id === 'r2');
  await until(() => calls.filter(call => call.url.pathname.endsWith('/stream')).length === 2);
  assert.equal(old.init.signal.aborted, true);
  summaryRun='r1';
  await advance(5000);
  assert.equal(store.getSnapshot().views.t.run.run_id, 'r2');
  assert.equal(calls.filter(call => call.url.pathname.endsWith('/stream')).length, 2);
  assert.equal(store.getSnapshot().drafts.t, '新运行也保留');
});

test('a newer polled run invalidates an older history probe before it can take over observation', async t => {
  let summaryRun='r1', reads=0, resolveOld;
  const {store, calls, advance} = fixture(t, url => {
    if(url.pathname === '/api/threads') return Response.json({data:[row('t',{run_id:summaryRun, run_status:'running'})], next_cursor:null});
    if(url.pathname.endsWith('/messages')) {
      if(++reads === 1) return Response.json({data:[human('r1',1)]});
      if(reads === 2) return new Promise(resolve => resolveOld=resolve);
      return Response.json({data:[human('r1',1,'completed'), human('r2',2,'completed'), human('r3',3)]});
    }
    return metadata(url.pathname.includes('/r3/') ? 'r3' : url.pathname.includes('/r2/') ? 'r2' : 'r1');
  });
  await until(() => store.getSnapshot().views.t?.observation === 'open');
  summaryRun='r2';
  await advance(5000);
  const oldProbe = calls.filter(call => call.url.pathname.endsWith('/messages')).at(-1);
  summaryRun='r3';
  await advance(5000);
  assert.equal(reads, 3, '新身份不等待旧探针');
  assert.equal(oldProbe.init.signal.aborted, true);
  await until(() => store.getSnapshot().views.t.run.run_id === 'r3');
  resolveOld(Response.json({data:[human('r1',1,'completed'), human('r2',2)]}));
  await tick();
  assert.equal(store.getSnapshot().views.t.run.run_id, 'r3');
  assert.deepEqual(calls.filter(call => call.url.pathname.endsWith('/stream')).map(call => call.url.pathname),
    ['/api/threads/t/runs/r1/stream', '/api/threads/t/runs/r3/stream']);
});

test('hiding aborts the observation and all polling; show, select and ready coalesce into one history read', async t => {
  let cancelled = 0;
  const human = {id:1, thread_id:'t', run_id:'r', run_status:'running', seq:1,
    category:'message', event_type:'human_message', event_key:'human:m', metadata:{}, created_at:instant,
    content:{type:'human', message_id:'m', content:'已保存正文'}};
  const {store, client, calls, ready, advance} = fixture(t, url => {
    if(url.pathname === '/api/threads') return Response.json({data:[row('t',{run_id:'r', run_status:'running'})], next_cursor:null});
    if(url.pathname.endsWith('/messages')) return Response.json({data:[human]});
    return new Response(new ReadableStream({start(controller) {
      controller.enqueue(new TextEncoder().encode('event: metadata\ndata: {"thread_id":"t","run_id":"r","status":"running"}\n\n'));
    }, cancel() {cancelled++;}}), {headers:{'content-type':'text/event-stream'}});
  });
  await until(() => store.getSnapshot().views.t?.observation === 'open');
  store.updateDraft('显示后还要继续编辑');
  store.setVisible(false);
  await advance(60000);
  assert.equal(cancelled, 1);
  assert.equal(lists(calls).length, 1);
  assert.equal(store.getSnapshot().views.t.observation, 'paused');
  assert.equal(store.getSnapshot().views.t.messages[0].content.content, '已保存正文');
  assert.equal(store.canSend(), false);
  store.setSession(null);
  client.update({...ready, startup_id:'two'});
  store.setSession(client.session);
  store.setVisible(true);
  store.select('t');
  store.setVisible(true);
  await until(() => calls.filter(call => call.url.pathname.endsWith('/messages')).length === 2);
  await until(() => store.getSnapshot().views.t.observation === 'open');
  assert.equal(calls.filter(call => call.url.pathname.endsWith('/messages')).length, 2);
  assert.equal(lists(calls).length, 2);
  assert.equal(store.getSnapshot().drafts.t, '显示后还要继续编辑');
  assert.ok(calls.every(call => (call.init.method ?? 'GET') === 'GET'));
});

test('503 delays the next list poll without clearing rows, resetting pagination or adding stream retries', async t => {
  let first=0;
  const {store, calls, advance} = fixture(t, url => {
    if(url.pathname.endsWith('/messages')) return Response.json({data:[]});
    if(url.searchParams.has('cursor')) return Response.json({data:Array.from({length:20},(_,i) => row(`old-${i}`)), next_cursor:'older-2'});
    if(++first === 2) return new Response('繁忙', {status:503, headers:{'Retry-After':'12'}});
    return Response.json({data:Array.from({length:20},(_,i) => row(`t-${i}`)), next_cursor:`first-${first}`});
  });
  await until(() => store.getSnapshot().listLoaded);
  await until(() => store.getSnapshot().views[store.getSnapshot().activeId]?.verified);
  store.updateDraft('轮询保留');
  await store.loadMore();
  const selected = store.getSnapshot().activeId;
  await advance(5000);
  assert.match(store.getSnapshot().listError.message, /503/);
  assert.equal(store.getSnapshot().threads.length, 40);
  await advance(11999);
  assert.equal(first, 2);
  await advance(1);
  assert.equal(first, 3);
  assert.equal(store.getSnapshot().nextCursor, 'older-2');
  assert.equal(store.getSnapshot().activeId, selected);
  assert.equal(store.getSnapshot().drafts[selected], '轮询保留');
  assert.equal(calls.filter(call => call.url.pathname.endsWith('/stream')).length, 0);
  store.setVisible(false);
  store.setVisible(true);
  await until(() => first === 4);
  assert.equal(store.getSnapshot().nextCursor, 'older-2', '显示恢复不重建分页游标');
  assert.equal(store.getSnapshot().threads.length, 40);
});

test('hidden initial ready makes no requests; showing starts once even with repeated ready and visibility inputs', async t => {
  const {store, client, calls, advance} = fixture(t, url => Response.json(
    url.pathname === '/api/threads' ? {data:[row()], next_cursor:null} : {data:[]}
  ));
  store.setVisible(false);
  await advance(60000);
  assert.equal(calls.length, 0);
  store.setVisible(true);
  store.setVisible(true);
  store.setSession(client.session);
  await until(() => store.canSend());
  assert.equal(lists(calls).length, 1);
  assert.equal(calls.filter(call => call.url.pathname.endsWith('/messages')).length, 1);
});

test('HTTP-date Retry-After delays a single ordinary list poll', async t => {
  let reads=0;
  const deadline = new Date(Date.parse(instant)+25000).toUTCString();
  const {store, calls, advance} = fixture(t, url => {
    if(url.pathname !== '/api/threads') return Response.json({data:[]});
    if(++reads === 2) return new Response('busy', {status:503, headers:{'Retry-After':deadline}});
    return Response.json({data:[row()], next_cursor:null});
  });
  await until(() => store.canSend());
  await advance(5000);
  await advance(19999);
  assert.equal(reads, 2);
  await advance(1);
  assert.equal(reads, 3);
  assert.equal(lists(calls).length, 3);
});

test('showing a conversation completed while hidden closes observation after the verified snapshot', async t => {
  let completed=false;
  const {store} = fixture(t, url => {
    if(url.pathname === '/api/threads') return Response.json({data:[row('t',{run_id:'r',run_status:completed ? 'completed' : 'running'})],next_cursor:null});
    if(url.pathname.endsWith('/messages')) return Response.json({data:[human('r',1,completed ? 'completed' : 'running')]});
    if(url.pathname.endsWith('/stream')) return metadata('r');
    return Response.json({data:{id:'r',thread_id:'t',status:'completed'}});
  });
  await until(() => store.getSnapshot().views.t?.observation === 'open');
  store.setVisible(false);
  completed=true;
  store.setVisible(true);
  await until(() => store.getSnapshot().views.t.verified);
  assert.equal(store.getSnapshot().views.t.run.status, 'completed');
  assert.equal(store.getSnapshot().views.t.observation, 'closed', '已完成的恢复读取不沿用旧暂停状态');
});

test('hidden unconfirmed POST keeps the submission unknown and never automatically resends', async t => {
  let resolvePost;
  const {store, calls, advance} = fixture(t, (url, init) => {
    if(init.method === 'POST') return new Promise(resolve => resolvePost=resolve);
    if(url.pathname === '/api/threads') return Response.json({data:[row()], next_cursor:null});
    return Response.json({data:[]});
  });
  await until(() => store.canSend());
  store.updateDraft('  原文\n');
  assert.equal(store.send('  原文\n'), true);
  await until(() => resolvePost);
  store.updateDraft('下一条');
  store.setVisible(false);
  const post = calls.find(call => call.init.method === 'POST');
  assert.equal(post.init.signal.aborted, true);
  assert.equal(store.getSnapshot().submissions.t.status, 'unknown');
  assert.equal(store.getSnapshot().submissions.t.text, '  原文\n');
  resolvePost(metadata('server-run'));
  await advance(60000);
  assert.equal(calls.length, 3, '隐藏时不继续 GET 或 POST');
  store.setVisible(true);
  await until(() => store.getSnapshot().views.t.verified);
  assert.equal(calls.filter(call => call.init.method === 'POST').length, 1);
  assert.equal(store.getSnapshot().submissions.t.status, 'unknown');
  assert.equal(store.getSnapshot().drafts.t, '下一条');
});

test('hidden slow history and page results are aborted and cannot publish after show or a new startup lease', async t => {
  let resolveHistory, resolveList, listsRead=0;
  const {store, client, calls, ready, advance} = fixture(t, (url) => {
    if(url.pathname === '/api/threads') {
      if(++listsRead === 2) return new Promise(resolve => resolveList=resolve);
      return Response.json({data:[row()], next_cursor:null});
    }
    if(!resolveHistory) return new Promise(resolve => resolveHistory=resolve);
    return Response.json({data:[]});
  });
  await until(() => resolveHistory);
  await advance(5000);
  await until(() => resolveList);
  const oldReads = calls.slice();
  store.setVisible(false);
  client.update({...ready, startup_id:'new', base_url:'http://127.0.0.1:2'});
  store.setSession(client.session);
  store.setVisible(true);
  await until(() => store.getSnapshot().views.t.verified);
  resolveList(Response.json({data:[row('stale')], next_cursor:'stale-cursor'}));
  resolveHistory(Response.json({data:[human('old-run',1)]}));
  await tick();
  assert.equal(store.getSnapshot().threads.some(thread => thread.id === 'stale'), false);
  assert.equal(store.getSnapshot().views.t.run, null);
  assert.deepEqual(store.getSnapshot().views.t.messages, []);
  assert.ok(oldReads.every(call => call.init.signal.aborted));
  assert.ok(calls.slice(oldReads.length).every(call => call.url.port === '2'));
});
