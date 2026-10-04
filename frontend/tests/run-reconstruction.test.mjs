import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const time = '2026-10-04T00:00:00Z';
const summary = id => ({id, title:null, user_id:null, created_at:time, updated_at:time, run_id:'r', run_status:'running'});
const content = (id, text, extra = {}) => ({type:'ai', message_id:id, content:text, tool_calls:[], ...extra});
const saved = (seq, text, run = 'r') => ({id:seq, thread_id:'t', run_id:run, run_status:'running', seq,
  event_type:'ai_message', category:'message', event_key:`ai:m${seq}`, content:content(`m${seq}`, text), metadata:{}, created_at:time});
const fact = (seq, payload, category = 'message', event_type = 'created') => ({seq, created_at:time, category, event_type, payload});
const metadata = (status = 'running', extra = {}) => ({thread_id:'t', run_id:'r', status, ...extra});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function until(probe) {
  for (let i=0; i<200; i++) { if (probe()) return; await tick(); }
  assert.fail('状态未就绪');
}
function fixture(t, histories = [[saved(1, '已保存')]], snapshot = {id:'r', thread_id:'t', status:'completed'}) {
  const streams = []; let reads = 0;
  const snapshotReads = [];
  const client = new BackendClient(async (url, init) => {
    const path = new URL(url).pathname;
    if (path === '/api/threads') return Response.json({data:[summary('t'), summary('u')], next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:path.includes('/u/') ? [] : histories[Math.min(reads++, histories.length-1)]});
    if (path.endsWith('/stream')) {
      assert.equal(new URL(url).search, '');
      assert.equal(new Headers(init.headers).has('Last-Event-ID'), false);
      return new Response(new ReadableStream({start(controller) {
        streams.push({push(event, data) { controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)); },
          close() { controller.close(); }});
      }}), {headers:{'content-type':'text/event-stream'}});
    }
    snapshotReads.push(path);
    return snapshot instanceof Response ? snapshot : Response.json({data:snapshot});
  });
  const store = new ConversationStore();
  client.update({state:'ready', startup_id:'lease', base_url:'http://127.0.0.1:1'});
  store.setSession(client.session);
  t.after(() => {store.setSession(null); client.update(null);});
  return {client, store, streams, snapshotReads, view:() => store.getSnapshot().views.t};
}

test('full replay merges complete facts without deleting gaps and rebuilds only this run preview', async t => {
  const {store, streams, view} = fixture(t, [[saved(1, '旧运行', 'old'), saved(4, '已保存')], [saved(4, '已保存')]]);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata());
  streams[0].push('delta', {seq:6, message_id:'live', field:'content', value:'同'});
  streams[0].push('delta', {seq:6, message_id:'live', field:'content', value:'同'});
  await until(() => view().messages.at(-1)?.content.content === '同同');
  store.reload();
  await until(() => streams.length === 2);
  assert.equal(view().messages.at(-1).content.content, '同同', '有效 metadata 前保留预览');
  streams[1].push('metadata', metadata());
  streams[1].push('delta', {seq:6, message_id:'live', field:'content', value:'重建'});
  const full = fact(6, content('live', [{type:'text', text:'完整'}, {type:'custom', extra:0}], {custom:{all:true}}));
  streams[1].push('event', full);
  streams[1].push('event', fact(3, content('earlier', '乱序')));
  streams[1].push('event', full);
  streams[1].push('delta', {seq:6, message_id:'live', field:'content', value:'不能追加已保存正文'});
  await until(() => view().messages.length === 4);
  assert.deepEqual(view().messages.map(m => m.seq), [1,3,4,6]);
  assert.deepEqual(view().messages.at(-1).content, full.payload);
  assert.deepEqual(view().events.r.map(e => e.seq), [3,6]);
});

const checkpoint = id => ({configurable:{thread_id:'t', checkpoint_ns:'', checkpoint_id:id}});
const required = (seq, id = 'cp') => fact(seq, {status:'required', checkpoint:checkpoint(id),
  interrupts:[{id:'interrupt', namespace:'', value:{action_requests:[{name:'bash', args:{command:'ls'}}], review_configs:[{action_name:'bash', allowed_decisions:['approve','reject']}]}}]}, 'approval', 'required');

test('only a normal interrupted GET replay verifies the current unresolved approval', async t => {
  const {store, streams, view} = fixture(t, undefined, {id:'r',thread_id:'t',status:'interrupted'});
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('interrupted'));
  streams[0].push('event', required(5));
  await until(() => view().events?.r?.length === 1);
  assert.equal(view().approval?.verified, false);
  streams[0].close();
  await until(() => view().approval?.verified);
  assert.equal(view().approval.request.seq, 5);
  store.reload();
  await until(() => streams.length === 2);
  assert.equal(view().approval.verified, false);
  // 乱序的 resolved 和旧 required 必须按持久 seq 解释。
  streams[1].push('metadata', metadata('interrupted'));
  streams[1].push('event', fact(7, {status:'resolved', checkpoint:checkpoint('cp'), responses:{interrupt:{decisions:[{type:'approve'}]}}}, 'approval', 'resolved'));
  streams[1].push('event', required(5));
  streams[1].push('event', required(9, 'new-cp'));
  streams[1].close();
  await until(() => view().approval?.verified && view().approval.request.seq === 9);
  assert.deepEqual(view().events.r.map(e => e.seq), [5,7,9]);
});

test('conflicting or malformed public facts stop verification and retain confirmed facts and raw error', async t => {
  const {store, streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata());
  streams[0].push('event', fact(3, content('good', '原始事实')));
  await until(() => view().events?.r?.length === 1);
  const conflict = fact(3, content('good', '偷偷改写'));
  streams[0].push('event', conflict);
  await until(() => view().error);
  assert.equal(view().messages.at(-1).content.content, '原始事实');
  assert.equal(view().verified, false);
  assert.deepEqual(view().protocolIssue.raw, conflict);
  store.reload();
  await until(() => streams.length === 2);
  streams[1].push('metadata', metadata('interrupted'));
  const invalid = required(8);
  invalid.payload.checkpoint.configurable.thread_id = 'foreign';
  streams[1].push('event', invalid);
  await until(() => view().error);
  assert.deepEqual(view().events.r.map(e => e.seq), [3]);
  assert.equal(view().approval?.verified ?? false, false);
  assert.deepEqual(view().protocolIssue.raw, invalid);
});

test('terminal metadata and omitted fields survive old lifecycle, metadata, history and list reads', async t => {
  const {store, streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('interrupted', {usage:{total_input:1,total_output:2,total_tokens:3}, usage_pending:false}));
  streams[0].push('metadata', metadata('running'));
  await until(() => view().run?.status === 'running' && view().run?.usage?.total_tokens === 3);
  assert.equal(view().run.usage_pending, null, '新执行阶段不能沿用旧已结算结论');
  assert.equal(view().run.usage.total_tokens, 3);
  streams[0].push('metadata', metadata('error', {error:'真实失败', completed_at:time}));
  streams[0].push('event', fact(10, {status:'running'}, 'lifecycle', 'status_changed'));
  streams[0].push('metadata', metadata('running', {error:null, completed_at:null}));
  streams[0].close();
  await until(() => view().observation === 'closed');
  await store.refreshThreads();
  assert.equal(store.getSnapshot().threads.find(item => item.id === 't').run_status, 'error');
  store.reload();
  await until(() => view().verified && view().history === 'ready');
  assert.equal(view().run.status, 'error');
  assert.equal(view().run.error, '真实失败');
  assert.equal(view().run.completed_at, time);
  assert.equal(view().events.r[0].payload.status, 'running', '历史保留但不作为当前状态');
});

test('pre-metadata failure keeps preview; error plus EOF cannot verify an approval', async t => {
  const {store, streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata());
  streams[0].push('delta', {seq:12, message_id:'preview', field:'content', value:'已显示正文'});
  await until(() => view().messages.at(-1)?.preview);
  store.reload();
  await until(() => streams.length === 2);
  streams[1].push('error', {code:'unavailable', message:'观察失败', recoverable:true});
  streams[1].close();
  await until(() => view().observation === 'failed');
  assert.equal(view().messages.at(-1).content.content, '已显示正文');
  store.reload();
  await until(() => streams.length === 3);
  streams[2].push('metadata', metadata('interrupted'));
  streams[2].push('event', required(8));
  streams[2].push('error', {code:'failed', message:'回放未核实', recoverable:false});
  streams[2].push('metadata', metadata('interrupted'));
  streams[2].close();
  await until(() => view().observation === 'failed');
  assert.equal(view().messages.length, 1, 'metadata 已有效建立，应清除本 Run 的旧预览');
  assert.equal(view().approval.verified, false);
  assert.equal(view().verified, false);
});

test('invalidated requests remain history and never become actionable at interrupted EOF', async t => {
  const {streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('interrupted'));
  streams[0].push('event', fact(11, {status:'invalidated', checkpoint:checkpoint('cp'), interrupt_ids:['interrupt'], reason:'run_cancelled'}, 'approval', 'invalidated'));
  streams[0].push('event', required(5));
  streams[0].close();
  await until(() => view().observation === 'closed');
  assert.equal(view().approval, null);
  assert.deepEqual(view().events.r.map(event => event.event_type), ['required','invalidated']);
});

test('a newer selection discards queued frames and never cancels the server run', async t => {
  const {store, streams, view} = fixture(t);
  await until(() => streams.length === 1);
  let selected = false;
  const unsubscribe = store.subscribe(() => {
    if (!selected && view()?.run?.status === 'completed') { selected = true; store.select('u'); }
  });
  t.after(unsubscribe);
  streams[0].push('metadata', metadata('completed'));
  streams[0].push('event', fact(20, content('late', '不能接入')));
  await until(() => store.getSnapshot().views.u?.verified);
  assert.equal(store.getSnapshot().activeId, 'u');
  assert.deepEqual(store.getSnapshot().views.u.messages, []);
  assert.deepEqual(view().messages.map(message => message.seq), [1]);
});

test('public SSE rejects malformed envelopes, wrong identities, missing metadata and truncated frames', async t => {
  const cases = [
    ['event', fact(1, content('m', '无 metadata'))],
    ['metadata', {...metadata(), run_id:'foreign'}],
    ['delta', {seq:0, message_id:'m', field:'content', value:'invalid'}],
    ['event', {...fact(1, content('m','invalid')), created_at:undefined}],
    ['event', fact(1, {...content('m','invalid'), tool_calls:null})],
    ['event', {...required(1), event_type:'resolved'}],
    ['metadata', {...metadata(), usage_pending:'false'}],
  ];
  for (const [event, data] of cases) {
    const prefix = event === 'metadata' ? '' : `event: metadata\ndata: ${JSON.stringify(metadata())}\n\n`;
    const text = (event === 'event' && data.seq === 1 && data.payload?.content === '无 metadata' ? '' : prefix)
      + `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    const client = new BackendClient(async () => new Response(text, {headers:{'content-type':'text/event-stream'}}));
    client.update({state:'ready', startup_id:'validation', base_url:'http://127.0.0.1:1'});
    t.after(() => client.update(null));
    const seen = [];
    await assert.rejects(client.session.observe('t','r', frame => seen.push(frame)), /协议问题/);
    assert.ok(seen.every(frame => frame.event === 'metadata'));
  }
  for (const text of ['event: metadata\ndata: {bad}\n\n', `event: metadata\ndata: ${JSON.stringify(metadata())}`]) {
    const client = new BackendClient(async () => new Response(text, {headers:{'content-type':'text/event-stream'}}));
    client.update({state:'ready', startup_id:'parse', base_url:'http://127.0.0.1:1'});
    t.after(() => client.update(null));
    await assert.rejects(client.session.observe('t','r', () => assert.fail('无效载荷不能接入')), /协议问题/);
  }
});

test('new POST identity survives a sparse follow-up query and starts with its own facts', async t => {
  let postStream, getStream;
  const client = new BackendClient(async (url, init) => {
    const path = new URL(url).pathname;
    if (path === '/api/threads') return Response.json({data:[summary('t')],next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:[{...saved(1,'旧运行','old'), run_status:'error'}]});
    if (init.method === 'POST' || path.endsWith('/stream')) return new Response(new ReadableStream({start(controller) {
      const source = {push(event, data) {controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));}, close(){controller.close();}};
      if (init.method === 'POST') postStream = source; else {getStream = source; assert.ok(path.endsWith('/runs/new/stream'));}
    }}), {headers:{'content-type':'text/event-stream'}});
    return Response.json({data:{id:'old',thread_id:'t',status:'error',error:'旧错误',usage:{total_input:5,total_output:5,total_tokens:10},completed_at:time}});
  });
  const store = new ConversationStore();
  client.update({state:'ready',startup_id:'new-target',base_url:'http://127.0.0.1:1'});
  store.setSession(client.session);
  t.after(() => {store.setSession(null);client.update(null);});
  await until(() => store.canSend());
  store.send('新任务');
  await until(() => postStream);
  postStream.push('metadata', {...metadata(),run_id:'new'});
  postStream.close();
  await until(() => getStream);
  getStream.push('metadata', {...metadata(),run_id:'new'});
  await until(() => store.getSnapshot().views.t.verified);
  assert.deepEqual(store.getSnapshot().views.t.run, {thread_id:'t',run_id:'new',status:'running'});
  assert.deepEqual(store.getSnapshot().views.t.messages.map(message => message.run_id), ['old']);
  assert.equal(store.getSnapshot().views.t.events.new, undefined);
});

test('explicit null usage stays unknown and preserves other omitted fields', async t => {
  const {streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('running', {usage:{total_input:0,total_output:0,total_tokens:0}, usage_pending:false, error:null}));
  streams[0].push('metadata', metadata('interrupted', {usage:null}));
  streams[0].close();
  await until(() => view().observation === 'closed');
  assert.equal(view().run.usage, null);
  assert.equal(view().run.usage_pending, false);
  assert.equal(view().run.error, null);
  assert.equal(Object.hasOwn(view().run, 'completed_at'), false);
});

test('history cannot reuse an already committed lifecycle sequence', async t => {
  const {store, streams, view} = fixture(t, [[saved(1,'消息')], [saved(1,'消息'), saved(9,'不合法复用')]]);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata());
  streams[0].push('event', fact(9, {status:'running'}, 'lifecycle', 'status_changed'));
  await until(() => view().events?.r?.length === 1);
  store.reload();
  await until(() => view().history !== 'loading');
  assert.equal(view().verified, false);
  assert.match(view().error, /协议问题/);
  assert.deepEqual(view().messages.map(message => message.seq), [1]);
  assert.equal(streams.length, 1, '冲突历史不应继续建立观察');
});

test('delta cannot reuse an already committed lifecycle sequence', async t => {
  const {streams, view} = fixture(t);
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata());
  streams[0].push('event', fact(9, {status:'running'}, 'lifecycle', 'status_changed'));
  streams[0].push('delta', {seq:9, message_id:'illegal', field:'content', value:'不能写预览'});
  await until(() => view().error);
  assert.match(view().error, /协议问题/);
  assert.deepEqual(view().messages.map(message => message.seq), [1]);
  assert.equal(view().events.r[0].category, 'lifecycle');
});

test('normal GET EOF reads one snapshot without replacing the verified replay identity', async t => {
  const {streams, snapshotReads, view} = fixture(t, undefined, {id:'r', thread_id:'t', status:'interrupted',
    usage:{total_input:5,total_output:2,total_tokens:7},usage_pending:false,updated_at:time});
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('interrupted'));
  streams[0].push('event', required(5));
  streams[0].close();
  await until(() => view().approval?.verified);
  await tick();
  assert.deepEqual(snapshotReads, ['/api/threads/t/runs/r']);
  assert.equal(view().run.usage.total_tokens, 7);
  assert.equal(view().run.usage_pending, false);
  assert.equal(view().run.status, 'interrupted');
  assert.equal(view().approval.verified, true);
});

test('partial resolved and invalidated IDs are protocol problems and retain the full confirmed request', async t => {
  for (const type of ['resolved','invalidated']) {
    await t.test(type, async t => {
      const {streams, view} = fixture(t);
      await until(() => streams.length === 1);
      const fullRequest = required(5);
      fullRequest.payload.interrupts.push({...fullRequest.payload.interrupts[0], id:'second'});
      streams[0].push('metadata', metadata('interrupted'));
      streams[0].push('event', fullRequest);
      await until(() => view().approval?.request.payload.interrupts.length === 2);
      const partial = fact(7, type === 'resolved'
        ? {status:type, checkpoint:checkpoint('cp'), responses:{interrupt:{decisions:[{type:'approve'}]}}}
        : {status:type, checkpoint:checkpoint('cp'), interrupt_ids:['interrupt'],reason:'run_cancelled'}, 'approval', type);
      streams[0].push('event', partial);
      streams[0].close();
      await until(() => view().observation === 'failed' || view().observation === 'closed');
      assert.match(view().error, /协议问题/);
      assert.deepEqual(view().events.r, [fullRequest]);
      assert.equal(view().approval.request.seq, 5);
      assert.equal(view().approval.verified, false);
      assert.deepEqual(view().protocolIssue.raw, partial);
    });
  }
});

test('failed post-replay snapshot does not revoke an identity already checked by GET', async t => {
  const {streams, snapshotReads, view} = fixture(t, undefined, new Response('临时不可读', {status:503}));
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('interrupted'));
  streams[0].push('event', required(5));
  streams[0].close();
  await until(() => view().error?.includes('运行快照'));
  assert.equal(view().observation, 'closed');
  assert.equal(view().verified, true);
  assert.equal(view().approval.verified, true);
  assert.equal(view().run.status, 'interrupted');
  assert.deepEqual(snapshotReads, ['/api/threads/t/runs/r']);
});

test('query nulls do not clear confirmed failure fields after normal EOF', async t => {
  const {streams, snapshotReads, view} = fixture(t, undefined, {id:'r',thread_id:'t',status:'error',error:null,error_code:null,completed_at:null,usage:null});
  await until(() => streams.length === 1);
  streams[0].push('metadata', metadata('error',{error:'真实失败',error_code:'tool_failed',completed_at:time}));
  streams[0].close();
  await until(() => snapshotReads.length === 1);
  await tick();
  assert.equal(view().run.error, '真实失败');
  assert.equal(view().run.error_code, 'tool_failed');
  assert.equal(view().run.completed_at, time);
  assert.equal(view().run.usage, null);
});

test('a resolved or invalidated checkpoint cannot resurrect through a newer identical required event', async t => {
  for (const type of ['resolved','invalidated']) {
    await t.test(type, async t => {
      const {streams, view} = fixture(t);
      await until(() => streams.length === 1);
      streams[0].push('metadata', metadata('interrupted'));
      streams[0].push('event', required(5));
      const processed = fact(7, type === 'resolved'
        ? {status:type, checkpoint:checkpoint('cp'), responses:{interrupt:{decisions:[{type:'approve'}]}}}
        : {status:type,checkpoint:checkpoint('cp'),interrupt_ids:['interrupt'],reason:'run_cancelled'}, 'approval', type);
      streams[0].push('event', processed);
      await until(() => view().events?.r?.length === 2);
      const revived = required(9);
      streams[0].push('event', revived);
      streams[0].close();
      await until(() => ['failed','closed'].includes(view().observation));
      assert.match(view().error, /协议问题/);
      assert.equal(view().approval, null);
      assert.deepEqual(view().events.r.map(event => event.seq), [5,7]);
      assert.deepEqual(view().protocolIssue.raw, revived);
    });
  }
});
