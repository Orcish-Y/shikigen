import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const time = '2026-10-05T00:00:00Z';
const run = (status = 'running') => ({thread_id:'t', run_id:'r', status});
const row = (id = 't') => ({id, title:null, user_id:null, created_at:time, updated_at:time,
  run_id:id === 't' ? 'r' : null, run_status:id === 't' ? 'running' : null});
const message = {id:1, thread_id:'t', run_id:'r', run_status:'running', seq:1,
  event_type:'human_message', category:'message', event_key:'human:m', metadata:{}, created_at:time,
  content:{type:'human', message_id:'m', content:'已保存原文'}};
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(probe) {
  for (let i=0; i<200; i++) { if (probe()) return; await tick(); }
  assert.fail('恢复状态未就绪');
}
function fixture(t, reply, snapshotStatus = 'running', empty = false, history) {
  t.mock.timers.enable({apis:['Date','setTimeout'], now:Date.parse(time)});
  const requests = [], streams = [];
  const client = new BackendClient(async (url, init) => {
    const path = new URL(url).pathname;
    requests.push({path, method:init.method ?? 'GET', at:Date.now()});
    if (path === '/api/threads') return Response.json({data:[row(), row('u')], next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:history ? history() : path.includes('/t/') && !empty ? [message] : []});
    if (!path.endsWith('/stream')) return Response.json({data:{id:'r', thread_id:'t', status:snapshotStatus}});
    assert.equal(new URL(url).search, '');
    assert.equal(new Headers(init.headers).has('Last-Event-ID'), false);
    if (reply) {
      const response = reply(streams.length, init);
      if (response) { streams.push(null); return response; }
    }
    return new Response(new ReadableStream({start(controller) {
      streams.push({
        push(event, data) {controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));},
        close() {controller.close();}, fail(error = new TypeError('连接中断')) {controller.error(error);},
      });
    }}), {headers:{'content-type':'text/event-stream'}});
  });
  const store = new ConversationStore({storage:null});
  client.update({state:'ready', startup_id:'first', base_url:'http://127.0.0.1:1'});
  store.setSession(client.session);
  t.after(() => {store.setSession(null); client.update(null);});
  const advance = async ms => {t.mock.timers.tick(ms); for(let i=0;i<10;i++) await tick();};
  return {store, client, streams, requests, advance, view:() => store.getSnapshot().views.t};
}

test('unexpected running EOF gets only three GET retries at 1, 2 and 5 seconds; metadata never resets the budget', async t => {
  const {store, streams, requests, advance, view} = fixture(t);
  await until(() => streams.length === 1);
  for (let index=0; index<4; index++) {
    streams[index].push('metadata', run());
    streams[index].close();
    await until(() => ['retry_wait','failed'].includes(view().observation));
    assert.equal(view().run.status, 'running');
    assert.equal(view().messages[0].content.content, '已保存原文');
    if (index < 3) {
      const wait = [1000,2000,5000][index];
      await advance(wait-1);
      assert.equal(streams.length, index+1);
      await advance(1);
      await until(() => streams.length === index+2);
    }
  }
  assert.equal(view().observation, 'failed');
  await store.refreshThreads();
  await advance(60000);
  assert.equal(streams.length, 4, '列表刷新不能重开耗尽的观察');
  assert.deepEqual(requests.filter(r => r.path.endsWith('/stream')).map(r => r.at-Date.parse(time)), [0,1000,3000,8000]);
  assert.ok(requests.every(r => r.method === 'GET'));
});

test('Retry-After survives manual races and re-entry; status query never opens a stream', async t => {
  const {store, streams, advance, view, requests} = fixture(t, index => index === 0
    ? new Response('暂不可读', {status:503, headers:{'Retry-After':'10'}}) : undefined);
  await until(() => view()?.observation === 'retry_wait');
  assert.deepEqual(view().observationFailure, {kind:'http', message:'HTTP 503: 暂不可读',
    status:503, detail:'暂不可读', retryAfter:'10', recoverable:true});
  store.reconnect(); store.reconnect();
  await advance(9999);
  assert.equal(streams.length, 1);
  store.select('t');
  await until(() => view().observation === 'retry_wait');
  await advance(1);
  await until(() => streams.length === 2);
  streams[1].push('error', {code:'bad_replay', message:'停止自动恢复', recoverable:false});
  await until(() => view().observation === 'failed');
  await store.queryStatus();
  assert.equal(streams.length, 2);
  assert.equal(view().run.status, 'running');
  store.reconnect(); store.reconnect();
  await until(() => streams.length === 3);
  assert.equal(requests.filter(r => r.path.endsWith('/stream')).length, 3);
  assert.ok(requests.every(r => r.method === 'GET'));
});

test('a quiet connection stays open; only 30 healthy seconds resets consecutive failures', async t => {
  const {streams, advance, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].fail();
  await until(() => view().observation === 'retry_wait');
  await advance(1000);
  streams[1].push('metadata', run());
  await until(() => view().observation === 'open');
  await advance(29999);
  assert.equal(streams.length, 2);
  streams[1].fail();
  await until(() => view().observation === 'retry_wait');
  assert.equal(view().retry.attempt, 2);
  await advance(2000);
  streams[2].push('metadata', run());
  await until(() => view().observation === 'open');
  await advance(15000);
  streams[2].push('metadata', run());
  await tick();
  await advance(15000);
  assert.equal(view().observation, 'open', '无 delta 不能按输出超时判失败');
  streams[2].fail();
  await until(() => view().observation === 'retry_wait');
  assert.equal(view().retry.attempt, 1);
  await advance(1000);
  assert.equal(streams.length, 4);
});

test('recoverable SSE error plus EOF schedules one retry and retains preview until valid metadata', async t => {
  const {streams, advance, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', run());
  streams[0].push('delta', {seq:3, message_id:'preview', field:'content', value:'已经看到的正文'});
  await until(() => view().messages.at(-1)?.preview);
  streams[0].push('error', {code:'read_unavailable', message:'读取暂不可用', recoverable:true});
  streams[0].close();
  await until(() => view().observation === 'retry_wait');
  assert.deepEqual(view().observationFailure, {kind:'sse', code:'read_unavailable', message:'读取暂不可用', recoverable:true});
  await advance(999);
  assert.equal(streams.length, 1);
  assert.equal(view().messages.at(-1).content.content, '已经看到的正文');
  await advance(1);
  assert.equal(streams.length, 2);
  assert.equal(view().messages.at(-1).content.content, '已经看到的正文');
  streams[1].push('metadata', run());
  await until(() => view().observation === 'open');
  assert.equal(view().messages.length, 1);
});

test('normal interrupted and terminal EOF never reconnect or invent a Run failure', async t => {
  for (const status of ['interrupted','completed','cancelled','error']) {
    await t.test(status, async child => {
      const {streams, advance, view, store} = fixture(child, undefined, status);
      await until(() => streams.length === 1);
      streams[0].push('metadata', run(status)); streams[0].close();
      await until(() => view().observation === 'closed');
      await advance(60000);
      assert.equal(streams.length, 1);
      assert.equal(view().run.status, status);
      assert.equal(view().observationFailure, null);
      store.setSession(null);
    });
  }
});

test('hard HTTP, nonrecoverable SSE, malformed protocol and unclassified errors stop automatically', async t => {
  const cases = [
    ['400', () => new Response('协议不兼容', {status:400}), 'http'],
    ['404', () => new Response('运行不存在', {status:404}), 'http'],
    ['500', () => new Response('读取损坏', {status:500}), 'http'],
    ['unknown', () => {throw new Error('尚未分类的读取错误');}, 'unknown'],
    ['protocol', () => new Response('event: metadata\ndata: {bad json}\n\n', {headers:{'content-type':'text/event-stream'}}), 'protocol'],
    ['SSE', () => new Response('event: error\ndata: {"code":"broken","message":"不可恢复","recoverable":false}\n\n', {headers:{'content-type':'text/event-stream'}}), 'sse'],
  ];
  for (const [name, reply, kind] of cases) await t.test(name, async child => {
    const {view, advance, requests, store} = fixture(child, reply);
    await until(() => view()?.observation === 'failed');
    assert.equal(view().observationFailure.kind, kind);
    assert.equal(view().run.status, 'running');
    assert.equal(view().missing, false, 'Run 404 不表示整个会话删除');
    assert.equal(view().messages[0].content.content, '已保存原文');
    await advance(60000);
    assert.equal(requests.filter(r => r.path.endsWith('/stream')).length, 1);
    assert.ok(requests.every(r => r.method === 'GET'));
    store.setSession(null);
  });
});

test('a normally ended SSE without metadata stops as a protocol failure instead of retrying', async t => {
  const {view, advance, requests} = fixture(t, () => new Response('',
    {headers:{'content-type':'text/event-stream'}}));
  await until(() => view()?.observationFailure);
  assert.equal(view().observation, 'failed');
  assert.equal(view().observationFailure.kind, 'protocol');
  assert.equal(view().observationFailure.recoverable, false);
  assert.equal(view().run.status, 'running');
  assert.equal(view().messages[0].content.content, '已保存原文');
  await advance(60000);
  assert.equal(requests.filter(request => request.path.endsWith('/stream')).length, 1);
});

test('an accepted POST disconnect recovers the known run by bounded GET and preserves a newer draft', async t => {
  const {store, streams, view, requests, advance} = fixture(t, (_index, init) => init.method === 'POST'
    ? new Response(`event: metadata\ndata: ${JSON.stringify(run())}\n\n`, {headers:{'content-type':'text/event-stream'}})
    : undefined, 'completed', true);
  await until(() => store.canSend());
  store.updateDraft('  本次原文\n');
  assert.equal(store.send('  本次原文\n'), true);
  await until(() => view().observation === 'retry_wait');
  store.updateDraft('稍后手动发送');
  assert.equal(store.getSnapshot().submissions.t.status, 'accepted');
  await advance(999);
  assert.equal(streams.length, 1);
  await advance(1);
  assert.equal(streams.length, 2);
  streams[1].push('metadata', run('completed')); streams[1].close();
  await until(() => view().observation === 'closed');
  await advance(60000);
  assert.equal(requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(requests.filter(r => r.method === 'GET' && r.path.endsWith('/stream')).length, 1);
  assert.equal(store.getSnapshot().drafts.t, '稍后手动发送');
});

test('accepted sending reads the committed user message during retry wait, keeping metadata authoritative', async t => {
  let accepted = false;
  const {store, view, streams, advance} = fixture(t, (_index, init) => {
    if (init.method !== 'POST') return;
    accepted = true;
    return new Response(`event: metadata\ndata: ${JSON.stringify(run())}\n\n`, {headers:{'content-type':'text/event-stream'}});
  }, 'running', true, () => accepted ? [{...message, run_status:'interrupted'}] : []);
  await until(() => store.canSend());
  store.send('已保存原文');
  await until(() => view().observation === 'retry_wait');
  await until(() => view().messages.length === 1);
  assert.equal(view().messages[0].content.content, '已保存原文');
  assert.equal(view().run.status, 'running', '正文补读不覆盖最近 metadata 的运行状态');
  assert.equal(streams.length, 1);
  await advance(1000);
  assert.equal(streams.length, 2);
});

test('unaccepted POST 503 retains original error and Retry-After, then only verifies with GET', async t => {
  const {store, requests, view, advance} = fixture(t, () => new Response('接受情况未知',
    {status:503, headers:{'Retry-After':'2'}}), 'running', true);
  await until(() => store.canSend());
  store.updateDraft('  不能自动重发\n');
  store.send('  不能自动重发\n');
  await until(() => store.getSnapshot().submissions.t?.status === 'unknown');
  assert.match(store.getSnapshot().submissions.t.error, /HTTP 503: 接受情况未知/);
  await advance(1999);
  assert.equal(requests.filter(r => r.path.endsWith('/messages')).length, 1);
  await advance(1);
  await until(() => view().history === 'ready');
  assert.equal(requests.filter(r => r.method === 'POST').length, 1);
  assert.equal(requests.filter(r => r.method === 'GET' && r.path.endsWith('/stream')).length, 0);
  assert.equal(store.getSnapshot().drafts.t, '  不能自动重发\n');
  assert.equal(store.getSnapshot().submissions.t.status, 'unknown');
});

test('selection or lease invalidation cancels stale timers; a new lease can retry without cancelling execution', async t => {
  const {store, client, streams, requests, advance, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].fail();
  await until(() => view().observation === 'retry_wait');
  store.updateDraft('恢复期间的草稿');
  store.select('u');
  await until(() => store.getSnapshot().views.u?.verified);
  await advance(10000);
  assert.equal(streams.length, 1);
  assert.equal(view().observation, 'paused');
  assert.equal(store.getSnapshot().drafts.t, '恢复期间的草稿');
  store.select('t');
  await until(() => streams.length === 2);
  streams[1].fail();
  await until(() => view().observation === 'retry_wait');
  client.update(null); store.setSession(null);
  await advance(10000);
  assert.equal(streams.length, 2);
  client.update({state:'ready', startup_id:'second', base_url:'http://127.0.0.1:2'});
  store.setSession(client.session);
  await until(() => streams.length === 3);
  assert.equal(store.getSnapshot().drafts.t, '恢复期间的草稿');
  assert.ok(requests.every(r => r.method === 'GET'));
});

test('HTTP-date Retry-After is respected even after manual reload', async t => {
  const deadline = 'Mon, 05 Oct 2026 00:00:08 GMT';
  const {store, advance, streams, view} = fixture(t, index => index === 0
    ? new Response('稍后', {status:503, headers:{'Retry-After':deadline}}) : undefined);
  await until(() => view()?.observation === 'retry_wait');
  await advance(1000); store.reload();
  await until(() => view().observation === 'retry_wait');
  await advance(6999);
  assert.equal(streams.length, 1);
  await advance(1);
  assert.equal(streams.length, 2);
});
