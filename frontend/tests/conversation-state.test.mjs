import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const ready = (revision, startup_id = 'first') => ({revision, startup_id,
  base_url:`http://127.0.0.1:${revision}`, state:'ready', can_retry:false, error:null});
const thread = id => ({id, title:null, created_at:'2026-10-04T00:00:00Z', updated_at:'2026-10-04T00:00:00Z'});
const message = (thread_id, text, status = 'completed') => ({id:1, thread_id, run_id:`run-${thread_id}`,
  run_status:status, seq:2, event_type:'human_message', category:'message', event_key:'human:m',
  metadata:{source:'history'}, created_at:'2026-10-04T00:00:00Z',
  content:{type:'human', message_id:`m-${thread_id}`, content:text}});
async function until(probe) {
  for (let i = 0; i < 100; i++) {
    if (probe()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('会话状态未就绪');
}

test('opening a terminal conversation preserves complete facts, selection and drafts across a host lease change', async () => {
  const paths = [];
  const client = new BackendClient(async url => {
    const path = new URL(url).pathname;
    paths.push(path);
    if (path === '/api/threads') return Response.json([thread('t')]);
    if (path.endsWith('/messages')) return Response.json({data:[message('t', '已保存正文')]});
    if (path.endsWith('/runs/run-t')) return Response.json({data:{id:'run-t', thread_id:'t', status:'completed', usage:null}});
    assert.fail(`终态不应开启观察：${path}`);
  });
  const store = new ConversationStore();
  store.updateDraft('没有会话的输入');
  assert.deepEqual(store.getSnapshot().drafts, {});
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => store.getSnapshot().views.t?.verified);
  store.updateDraft('保留我的草稿\n  缩进');
  const unsubscribe = store.subscribe(() => {});
  unsubscribe(); // Workspace 离开不会销毁应用持有的数据。
  client.update(null);
  store.setSession(null);
  assert.equal(store.getSnapshot().activeId, 't');
  assert.deepEqual(store.getSnapshot().views.t.messages, [message('t', '已保存正文')]);
  assert.equal(store.getSnapshot().drafts.t, '保留我的草稿\n  缩进');
  assert.equal(store.canSend(), false);
  client.update(ready(3, 'restarted'));
  store.setSession(client.session);
  await until(() => store.getSnapshot().views.t?.verified);
  assert.equal(store.getSnapshot().activeId, 't');
  assert.equal(store.getSnapshot().drafts.t, '保留我的草稿\n  缩进');
  assert.equal(store.getSnapshot().views.t.run.status, 'completed');
  assert.equal(store.canSend(), true);
  assert.ok(paths.includes('/api/threads/t/runs/run-t'));
  store.setSession(null);
  client.update(null);
});

test('late history from a previous selection cannot replace the selected conversation or its draft', async () => {
  let release;
  const client = new BackendClient(async url => {
    const path = new URL(url).pathname;
    if (path === '/api/threads') return Response.json([thread('a'), thread('b')]);
    if (path === '/api/threads/a/messages') return {
      ok:true, json: () => new Promise(resolve => release = resolve),
    };
    if (path === '/api/threads/b/messages') return Response.json({data:[]});
    assert.fail(path);
  });
  const store = new ConversationStore();
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => release);
  assert.equal(store.getSnapshot().views.a.history, 'loading');
  assert.equal(store.canSend(), false);
  store.select('b');
  store.updateDraft('b 的文字');
  await until(() => store.getSnapshot().views.b?.verified);
  release({data:[message('a', '迟到正文')]});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(store.getSnapshot().activeId, 'b');
  assert.deepEqual(store.getSnapshot().views.b.messages, []);
  assert.equal(store.getSnapshot().views.b.run, null);
  assert.equal(store.getSnapshot().drafts.b, 'b 的文字');
  assert.equal(store.canSend(), true);
  store.setSession(null);
  client.update(null);
});

test('a confirmed creation is retained after list failure and does not steal a newer selection', async () => {
  let release, failList = false, posts = 0;
  const client = new BackendClient(async (url, init) => {
    if (init.method === 'POST') {
      posts++;
      return new Promise(resolve => release = resolve);
    }
    if (url.endsWith('/messages')) return Response.json({data:[]});
    if (failList) return new Response('temporarily unavailable', {status:503});
    return Response.json([thread('a'), thread('b')]);
  });
  const store = new ConversationStore();
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => store.getSnapshot().views.a?.verified);
  const create = store.create();
  await until(() => release);
  store.select('b');
  store.updateDraft('继续这段对话');
  failList = true;
  release(Response.json({thread_id:'new'}));
  await create;
  await until(() => !store.getSnapshot().listing);
  assert.equal(store.getSnapshot().activeId, 'b');
  assert.ok(store.getSnapshot().threads.some(item => item.id === 'new'));
  assert.equal(store.getSnapshot().drafts.b, '继续这段对话');
  assert.match(store.getSnapshot().notice, /已创建/);
  assert.match(store.getSnapshot().listError, /列表/);
  assert.equal(posts, 1);
  store.setSession(null);
  client.update(null);
});

const stream = frames => new Response(frames.map(([event, data]) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), {headers:{'content-type':'text/event-stream'}});

test('running and interrupted history reopens the existing stream; replay cannot override metadata', async () => {
  for (const status of ['running', 'interrupted']) {
    let observations = 0;
    const client = new BackendClient(async (url, init) => {
      assert.notEqual(init.method, 'POST');
      if (url.endsWith('/api/threads')) return Response.json([thread('t')]);
      if (url.endsWith('/messages')) return Response.json({data:[message('t', '已有任务', status)]});
      observations++;
      assert.ok(url.endsWith('/runs/run-t/stream'));
      return stream([
        ['metadata', {thread_id:'t', run_id:'run-t', status:'running'}],
        ['event', {seq:2, category:'message', payload:message('t', '已有任务', status).content}],
        ['event', {seq:4, category:'lifecycle', payload:{status:'interrupted'}}],
        ['metadata', {thread_id:'t', run_id:'run-t', status}],
      ]);
    });
    const store = new ConversationStore();
    client.update(ready(1));
    store.setSession(client.session);
    await until(() => store.getSnapshot().views.t?.verified);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(store.getSnapshot().views.t.run.status, status);
    assert.deepEqual(store.getSnapshot().views.t.messages, [message('t', '已有任务', status)]);
    assert.equal(store.canSend(), false);
    assert.equal(observations, 1);
    store.setSession(null);
    client.update(null);
  }
});

test('new run metadata does not inherit the previous failed runs error, usage or completion time', async () => {
  let live;
  const client = new BackendClient(async (url, init) => {
    if (init.method === 'POST') return new Response(new ReadableStream({start(controller) {
      live = controller;
      controller.enqueue(new TextEncoder().encode('event: metadata\ndata: {"thread_id":"t","run_id":"new-run","status":"running"}\n\n'));
    }}), {headers:{'content-type':'text/event-stream'}});
    if (url.endsWith('/api/threads')) return Response.json([thread('t')]);
    if (url.endsWith('/messages')) return Response.json({data:[message('t', '旧任务', 'error')]});
    return Response.json({data:{id:'run-t', thread_id:'t', status:'error', error:'上一轮失败',
      completed_at:'2026-10-04T01:00:00Z', usage:{total_tokens:99}}});
  });
  const store = new ConversationStore();
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => store.canSend());
  store.send('新任务');
  await until(() => store.getSnapshot().views.t.run.run_id === 'new-run');
  assert.deepEqual(store.getSnapshot().views.t.run, {thread_id:'t', run_id:'new-run', status:'running'});
  assert.ok(live);
  store.setSession(null);
  client.update(null);
});

test('normal send remains explicit and committed history is readable after the stream ends', async () => {
  let sent = false, posts = 0;
  const saved = message('t', '正常发送');
  const client = new BackendClient(async (url, init) => {
    if (init.method === 'POST') {
      posts++;
      assert.deepEqual(JSON.parse(init.body), {message:'正常发送'});
      sent = true;
      return stream([
        ['metadata', {thread_id:'t', run_id:'run-t', status:'running'}],
        ['event', {seq:2, category:'message', payload:saved.content}],
        ['metadata', {thread_id:'t', run_id:'run-t', status:'completed'}],
      ]);
    }
    if (url.endsWith('/api/threads')) return Response.json([thread('t')]);
    if (url.endsWith('/messages')) return Response.json({data:sent ? [saved] : []});
    return Response.json({data:{id:'run-t', thread_id:'t', status:'completed'}});
  });
  const store = new ConversationStore();
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => store.canSend());
  assert.equal(posts, 0);
  assert.equal(store.send('正常发送'), true);
  assert.equal(store.send('重复发送'), false);
  await until(() => store.canSend());
  assert.deepEqual(store.getSnapshot().views.t.messages, [saved]);
  assert.equal(posts, 1);
  store.setSession(null);
  client.update(null);
});

test('unknown creation outcome only reads the list and does not select a guessed new conversation', async () => {
  for (const reply of [() => { throw new TypeError('connection lost'); }, () => Response.json({thread_id:''})]) {
    let posts = 0, listReads = 0;
    const client = new BackendClient(async (url, init) => {
      if (init.method === 'POST') { posts++; return reply(); }
      if (url.endsWith('/messages')) return Response.json({data:[]});
      listReads++;
      return Response.json(listReads === 1 ? [thread('t')] : [thread('new'), thread('t')]);
    });
    const store = new ConversationStore();
    client.update(ready(1));
    store.setSession(client.session);
    await until(() => store.canSend());
    store.updateDraft('原来的输入');
    await store.create();
    assert.equal(posts, 1);
    assert.equal(listReads, 2);
    assert.equal(store.getSnapshot().activeId, 't');
    assert.equal(store.getSnapshot().drafts.t, '原来的输入');
    assert.match(store.getSnapshot().notice, /创建结果待确认/);
    store.setSession(null);
    client.update(null);
  }
});

test('failed or invalid history is not an empty conversation and keeps previous facts', async () => {
  let mode = 'valid';
  const client = new BackendClient(async url => {
    if (url.endsWith('/api/threads')) return Response.json([thread('t')]);
    if (url.endsWith('/messages')) {
      if (mode === 'unavailable') return new Response('unavailable', {status:503, headers:{'Retry-After':'1'}});
      return Response.json({data:[message('t', '已加载事实', mode === 'valid' ? 'completed' : 'unknown')]});
    }
    return Response.json({data:{id:'run-t', thread_id:'t', status:'completed'}});
  });
  const store = new ConversationStore();
  client.update(ready(1));
  store.setSession(client.session);
  await until(() => store.canSend());
  for (const next of ['unavailable', 'invalid']) {
    mode = next;
    store.reload();
    await until(() => store.getSnapshot().views.t.history === 'error');
    assert.deepEqual(store.getSnapshot().views.t.messages, [message('t', '已加载事实')]);
    assert.equal(store.getSnapshot().views.t.run.status, 'completed');
    assert.equal(store.canSend(), false);
  }
  store.setSession(null);
  client.update(null);
});
