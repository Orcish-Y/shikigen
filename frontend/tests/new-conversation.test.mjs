import assert from 'node:assert/strict';
import test from 'node:test';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { MessageDrafts } from '../src/message-drafts.ts';

const instant = '2026-10-24T00:00:00Z';
const thread = id => ({id, title:null, user_id:null, created_at:instant, updated_at:instant, run_id:null, run_status:null});
const ready = {revision:1, startup_id:'startup', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null};
const memory = () => {
  const entries = new Map();
  return {getItem:key => entries.get(key) ?? null, setItem:(key, value) => entries.set(key, value)};
};
async function until(predicate) {
  for (let attempt=0; attempt<200; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('新会话状态未就绪');
}
function fixture(t, {storage=memory(), respond} = {}) {
  const requests=[];
  const client=new BackendClient(async (url, init) => {
    const path=new URL(url).pathname;
    requests.push({path, method:init.method ?? 'GET', body:init.body && JSON.parse(init.body)});
    if (respond) {
      const response=await respond(path, init);
      if (response) return response;
    }
    if (path==='/api/threads') return Response.json({data:[thread('existing')], next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:[]});
    assert.fail(`意外请求：${path}`);
  });
  const store=new ConversationStore({storage});
  client.update(ready);
  store.setSession(client.session);
  t.after(() => {store.setSession(null); client.update(null);});
  return {store, client, requests, storage};
}
const acceptance = (threadId='created') => new Response(new ReadableStream({start(controller) {
  controller.enqueue(new TextEncoder().encode(`event: metadata\ndata: ${JSON.stringify({thread_id:threadId, run_id:'first-run', status:'running'})}\n\n`));
}}), {headers:{'content-type':'text/event-stream'}});

test('启动忽略缓存选中项，只读侧栏列表并保留历史草稿和提交线索', async t => {
  const storage=memory();
  const drafts=new MessageDrafts(storage);
  drafts.select('deleted');
  drafts.update('deleted', '旧会话草稿');
  drafts.begin('deleted', '提交结果待确认', null);
  const {store, requests}=fixture(t, {storage});
  await until(() => store.getSnapshot().listLoaded);
  assert.equal(store.getSnapshot().activeId, '');
  assert.deepEqual(store.getSnapshot().views, {});
  assert.equal(store.getSnapshot().drafts.deleted, '旧会话草稿');
  assert.equal(store.getSnapshot().submissions.deleted.text, '提交结果待确认');
  assert.deepEqual(requests.map(request => request.path), ['/api/threads']);
  await store.reloadThreads();
  assert.equal(store.getSnapshot().activeId, '', '刷新列表也不选择历史会话');
});

test('欢迎页草稿独立持久保存，完整重启仍停留欢迎页', async t => {
  const {store, storage}=fixture(t);
  store.updateDraft('  新会话\n    原文草稿  ');
  assert.equal(store.getSnapshot().newConversationDraft, '  新会话\n    原文草稿  ');
  assert.deepEqual(store.getSnapshot().drafts, {}, '不使用伪造或空会话 ID 保存草稿');
  const reopened=new ConversationStore({storage});
  assert.equal(reopened.getSnapshot().activeId, '');
  assert.equal(reopened.getSnapshot().newConversationDraft, '  新会话\n    原文草稿  ');
});

test('首发只创建一次会话并提交一次原文，创建期间新编辑的草稿不被接受响应清除', async t => {
  let releaseCreation;
  const {store, requests, storage}=fixture(t, {respond:(path, init) => {
    if (path==='/api/threads' && init.method==='POST') return new Promise(resolve => {releaseCreation=resolve;});
    if (path.endsWith('/stream')) return acceptance();
  }});
  await until(() => store.getSnapshot().listLoaded);
  const original='  首次发送\n    保留缩进  ';
  store.updateDraft(original);
  assert.equal(store.send(original), true);
  assert.equal(store.send(original), false, '连续点击不会重复创建');
  await until(() => releaseCreation);
  store.updateDraft('创建期间编辑的下一条');
  releaseCreation(Response.json({thread_id:'created'}));
  await until(() => store.getSnapshot().submissions.created?.status==='accepted');
  assert.equal(store.getSnapshot().activeId, 'created');
  assert.equal(store.getSnapshot().drafts.created, '创建期间编辑的下一条');
  assert.equal(store.getSnapshot().newConversationDraft, '');
  assert.deepEqual(requests.filter(request => request.method==='POST').map(({path, body}) => ({path, body})), [
    {path:'/api/threads', body:undefined},
    {path:'/api/threads/created/stream', body:{message:original}},
  ]);
  const reopened=new ConversationStore({storage});
  assert.equal(reopened.getSnapshot().activeId, '');
  assert.equal(reopened.getSnapshot().drafts.created, '创建期间编辑的下一条');
});

test('没有历史会话也可直接发送，只有有效接受响应才清除原文草稿', async t => {
  let releaseAcceptance;
  const {store, requests}=fixture(t, {respond:(path, init) => {
    if (path==='/api/threads') return Response.json(init.method==='POST' ? {thread_id:'created'} : {data:[], next_cursor:null});
    if (path.endsWith('/stream')) return new Promise(resolve => {releaseAcceptance=resolve;});
  }});
  await until(() => store.getSnapshot().listLoaded);
  assert.equal(store.canSend(), true);
  store.updateDraft('第一条原文');
  store.send('第一条原文');
  await until(() => releaseAcceptance);
  assert.equal(store.getSnapshot().drafts.created, '第一条原文');
  releaseAcceptance(acceptance());
  await until(() => store.getSnapshot().submissions.created?.status==='accepted');
  assert.equal(store.getSnapshot().drafts.created, '');
  assert.equal(requests.filter(request => request.method==='POST').length, 2);
});

test('创建会话失败保留欢迎页与原文，刷新列表不自动重试创建或发送', async t => {
  const {store, requests, storage}=fixture(t, {respond:(path, init) => {
    if (init.method==='POST') return Response.json({detail:'创建暂不可用'}, {status:503});
  }});
  await until(() => store.getSnapshot().listLoaded);
  store.updateDraft('  创建失败仍保留\n');
  store.send('  创建失败仍保留\n');
  await until(() => !store.getSnapshot().creating);
  assert.equal(store.getSnapshot().activeId, '');
  assert.equal(store.getSnapshot().newConversationDraft, '  创建失败仍保留\n');
  assert.match(store.getSnapshot().notice, /创建结果待确认/);
  await store.reloadThreads();
  assert.deepEqual(requests.filter(request => request.method==='POST').map(request => request.path), ['/api/threads']);
  assert.equal(new ConversationStore({storage}).getSnapshot().newConversationDraft, '  创建失败仍保留\n');
});

test('创建期间选择历史会话，迟到结果保留在列表但不抢选择也不发送', async t => {
  let releaseCreation;
  const {store, requests}=fixture(t, {respond:(path, init) => {
    if (init.method==='POST') return new Promise(resolve => {releaseCreation=resolve;});
  }});
  await until(() => store.getSnapshot().listLoaded);
  store.updateDraft('准备发给新会话');
  store.send('准备发给新会话');
  await until(() => releaseCreation);
  store.select('existing');
  store.updateDraft('历史会话新草稿');
  releaseCreation(Response.json({thread_id:'created'}));
  await until(() => !store.getSnapshot().creating);
  assert.equal(store.getSnapshot().activeId, 'existing');
  assert.equal(store.getSnapshot().drafts.existing, '历史会话新草稿');
  assert.equal(store.getSnapshot().newConversationDraft, '准备发给新会话');
  assert.ok(store.getSnapshot().threads.some(conversation => conversation.id==='created'));
  assert.equal(requests.filter(request => request.method==='POST').length, 1);
});

test('创建期间隐藏并重新显示，旧创建响应不迁移草稿或继续发送', async t => {
  let releaseCreation;
  const {store, requests}=fixture(t, {respond:(path, init) => {
    if (init.method==='POST') return new Promise(resolve => {releaseCreation=resolve;});
  }});
  await until(() => store.getSnapshot().listLoaded);
  store.updateDraft('隐藏前的原文');
  store.send('隐藏前的原文');
  await until(() => releaseCreation);
  store.setVisible(false);
  store.setVisible(true);
  releaseCreation(Response.json({thread_id:'created'}));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(store.getSnapshot().activeId, '');
  assert.equal(store.getSnapshot().newConversationDraft, '隐藏前的原文');
  assert.equal(requests.filter(request => request.method==='POST').length, 1);
});

test('首次发送接受情况未知时，原文归属已创建会话且不自动重发', async t => {
  const {store, requests, storage}=fixture(t, {respond:(path, init) => {
    if (path==='/api/threads' && init.method==='POST') return Response.json({thread_id:'created'});
    if (path.endsWith('/stream')) throw new TypeError('连接中断');
  }});
  await until(() => store.getSnapshot().listLoaded);
  store.updateDraft('需要核实的原文');
  store.send('需要核实的原文');
  await until(() => store.getSnapshot().submissions.created?.status==='unknown' && store.getSnapshot().views.created?.verified);
  assert.equal(store.getSnapshot().drafts.created, '需要核实的原文');
  assert.equal(store.getSnapshot().newConversationDraft, '');
  assert.equal(store.canSend(), false);
  await store.reloadThreads();
  assert.equal(requests.filter(request => request.method==='POST').length, 2);
  const reopened=new ConversationStore({storage});
  assert.equal(reopened.getSnapshot().activeId, '');
  assert.equal(reopened.getSnapshot().submissions.created.text, '需要核实的原文');
});

test('欢迎页与历史会话草稿相互独立，新建入口只切换页面', async t => {
  const {store, requests}=fixture(t);
  await until(() => store.getSnapshot().listLoaded);
  store.updateDraft('欢迎页草稿');
  store.select('existing');
  await until(() => store.getSnapshot().views.existing?.verified);
  store.updateDraft('历史草稿');
  const requestCount=requests.length;
  store.openNewConversation();
  assert.equal(store.getSnapshot().activeId, '');
  assert.equal(store.getSnapshot().newConversationDraft, '欢迎页草稿');
  assert.equal(store.getSnapshot().drafts.existing, '历史草稿');
  assert.equal(requests.length, requestCount);
  assert.equal(requests.some(request => request.method==='POST'), false);
});

test('托盘显示和后端租约更新保持本次已选会话，完整重启才回欢迎页', async t => {
  const {store, client, storage}=fixture(t);
  await until(() => store.getSnapshot().listLoaded);
  store.select('existing');
  await until(() => store.getSnapshot().views.existing?.verified);
  store.updateDraft('继续这个会话');
  store.setVisible(false);
  assert.equal(store.canSend(), false);
  client.update({...ready, revision:2, startup_id:'restarted'});
  store.setSession(client.session);
  store.setVisible(true);
  await until(() => store.getSnapshot().views.existing?.verified);
  assert.equal(store.getSnapshot().activeId, 'existing');
  assert.equal(store.getSnapshot().drafts.existing, '继续这个会话');
  assert.equal(new ConversationStore({storage}).getSnapshot().activeId, '');
});

test('离线欢迎页可编辑草稿，后端恢复后不自动提交', async t => {
  const {store, client, requests}=fixture(t);
  await until(() => store.getSnapshot().listLoaded);
  client.update(null);
  store.setSession(null);
  store.updateDraft('离线编辑');
  assert.equal(store.send('离线编辑'), false);
  client.update({...ready, revision:2, startup_id:'online'});
  store.setSession(client.session);
  await until(() => !store.getSnapshot().listing);
  assert.equal(store.getSnapshot().activeId, '');
  assert.equal(store.getSnapshot().newConversationDraft, '离线编辑');
  assert.equal(requests.some(request => request.method==='POST'), false);
});

test('本地保存不可用时欢迎页草稿仍保存在内存，旧版缓存保持兼容', t => {
  const store=new ConversationStore({storage:{getItem:()=>null, setItem:()=>{throw new Error('quota');}}});
  store.updateDraft('内存草稿');
  assert.equal(store.getSnapshot().newConversationDraft, '内存草稿');
  assert.match(store.getSnapshot().storageIssue, /本地保存不可用/);
  const storage=memory();
  storage.setItem('shikigen.message-drafts.v1', JSON.stringify({schema:1, selected:'deleted', drafts:[['deleted',{text:'旧版原文', version:1}]], submissions:[]}));
  const compatible=new ConversationStore({storage});
  assert.equal(compatible.getSnapshot().activeId, '');
  assert.equal(compatible.getSnapshot().drafts.deleted, '旧版原文');
  assert.equal(compatible.getSnapshot().newConversationDraft, '');
});
