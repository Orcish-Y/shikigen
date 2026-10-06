import assert from 'node:assert/strict';
import test from 'node:test';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { ConversationTitles, appendTaskExample, displayConversationTitle } from '../src/conversation-titles.ts';
import { nextConversationTimeRefresh, presentConversationTime } from '../src/conversation-time.ts';

const instant = '2026-10-06T00:00:00.123456Z';
const readySessionState = {revision:1, startup_id:'presentation', base_url:'http://127.0.0.1:45200',
  state:'ready', can_retry:false, error:null};
const summary = id => ({id, user_id:null, title:null, created_at:instant, updated_at:instant, run_id:null, run_status:null});
const message = (seq, body, overrides = {}) => ({id:seq, thread_id:'a', run_id:'run-a', run_status:'completed', seq,
  category:'message', event_type:'human_message', event_key:`human:${seq}`, metadata:{}, created_at:instant,
  content:{type:'human', message_id:`human-${seq}`, content:body}, ...overrides});
function memoryStorage() {
  const entries = new Map();
  return {getItem:key => entries.get(key) ?? null, setItem:(key, value) => entries.set(key, value)};
}
function deferredResponse() {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
}
async function until(predicate) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('expected public state did not arrive');
}
function startStore(storage, fetchFn) {
  const client = new BackendClient(fetchFn);
  client.update(readySessionState);
  const store = new ConversationStore({storage});
  store.setSession(client.session);
  return {store, close:() => {store.setSession(null); client.update(null);}};
}
const runResponse = (threadId = 'a') => Response.json({data:{thread_id:threadId, run_id:'run-a', status:'completed'}});

test('first committed human explicit text supplies a one-line title, not drafts/previews/unknown blocks', () => {
  const titles = new ConversationTitles(memoryStorage());
  const body = ['  第一段\n 缩进 ', {type:'image', text:'不要猜', url:'secret'},
    {type:'text', text:'第二段', additional:'keep raw'}];
  const history = [message(7,'later'), message(2,body), message(1,'preview',{preview:true}),
    message(0,'agent',{content:{type:'ai', message_id:'agent', content:'agent'}})];
  const original = structuredClone(history);
  titles.reconcileHistory('a',history);
  assert.equal(titles.getSnapshot().a, '第一段 缩进 第二段');
  assert.deepEqual(history,original,'deriving a title must not mutate facts');
  titles.reconcileHistory('a',[message(1,[{type:'image', text:'unknown'}]),message(2,'later text')]);
  assert.equal(titles.getSnapshot().a,undefined,'do not use a later message to guess the first message');
});

test('temporary titles preserve graphemes and only shorten the display name', () => {
  const titles = new ConversationTitles(memoryStorage());
  const grapheme = '👩🏽‍💻';
  titles.reconcileHistory('a',[message(1,grapheme.repeat(50))]);
  assert.equal(titles.getSnapshot().a,grapheme.repeat(48)+'…');
});

test('titles persist across restart, revalidate sources, and clear only against complete history', () => {
  const storage = memoryStorage();
  const first = new ConversationTitles(storage);
  first.reconcileHistory('a',[message(1,'最初标题')]);
  const reopened = new ConversationTitles(storage);
  assert.equal(reopened.getSnapshot().a,'最初标题');
  reopened.observeMessages('a',[message(5,'下一次运行')]);
  reopened.observeMessages('a',[]);
  assert.equal(reopened.getSnapshot().a,'最初标题','partial/SSE reads never erase earlier sources');
  reopened.reconcileHistory('a',[message(2,'历史核对标题')]);
  assert.equal(new ConversationTitles(storage).getSnapshot().a,'历史核对标题');
  reopened.reconcileHistory('a',[]);
  assert.equal(new ConversationTitles(storage).getSnapshot().a,undefined);
});

test('formal title wins without erasing temporary cache when null/blank arrives', () => {
  assert.equal(displayConversationTitle('正式标题','本地'),'正式标题');
  assert.equal(displayConversationTitle('  正式标题  ','本地'),'  正式标题  ');
  assert.equal(displayConversationTitle(null,'本地'),'本地');
  assert.equal(displayConversationTitle(' \n ','本地'),'本地');
  assert.equal(displayConversationTitle(null),'新会话');
});

test('read/write/corrupt cache failures retain memory and provide a specific warning', () => {
  for (const storage of [null, {getItem:() => {throw new Error('read');},setItem:()=>{}},
    {getItem:() => '{broken',setItem:()=>{}}, {getItem:() => null,setItem:() => {throw new Error('quota');}}]) {
    const titles = new ConversationTitles(storage);
    titles.reconcileHistory('a',[message(1,'内存标题')]);
    assert.equal(titles.getSnapshot().a,'内存标题');
    assert.match(titles.storageIssue,/本地标题保存不可用/);
  }
});

test('public history only reads selected conversation; caches update independently of server title and draft', async () => {
  const paths = [];
  const storage = memoryStorage();
  let serverTitle = null;
  const {store,close} = startStore(storage,async (input,init) => {
    assert.equal(init.method ?? 'GET','GET','title generation never POSTs/PATCHes');
    const path = new URL(input).pathname; paths.push(path);
    if (path === '/api/threads') return Response.json({data:[{...summary('a'),title:serverTitle},summary('b')],next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:[message(1,'  首条原文\n   内容  ')]});
    return runResponse();
  });
  try {
    await until(() => store.getSnapshot().temporaryTitles.a === '首条原文 内容');
    store.updateDraft('不要用这个标题');
    assert.equal(store.getSnapshot().temporaryTitles.b,undefined);
    assert.ok(!paths.includes('/api/threads/b/messages'));
    serverTitle = '真实正式名称'; await store.refreshThreads();
    let state = store.getSnapshot();
    assert.equal(displayConversationTitle(state.threads.find(thread=>thread.id==='a').title,state.temporaryTitles.a),'真实正式名称');
    serverTitle = null; await store.refreshThreads();
    state = store.getSnapshot();
    assert.equal(displayConversationTitle(state.threads.find(thread=>thread.id==='a').title,state.temporaryTitles.a),'首条原文 内容');
    assert.equal(state.drafts.a,'不要用这个标题');
  } finally {close();}
});

test('reopened public history corrects saved titles; failed reads keep verified cached title', async () => {
  const storage = memoryStorage();
  const cache = new ConversationTitles(storage); cache.reconcileHistory('a',[message(1,'旧缓存')]);
  let shouldFail = true;
  const {store,close} = startStore(storage,async input => {
    const path = new URL(input).pathname;
    if (path === '/api/threads') return Response.json({data:[summary('a')],next_cursor:null});
    if (path.endsWith('/messages')) return shouldFail ? Response.json({detail:'unavailable'},{status:500})
      : Response.json({data:[message(1,'实际历史') ]});
    return runResponse();
  });
  try {
    await until(() => store.getSnapshot().views.a?.history === 'error');
    assert.equal(store.getSnapshot().temporaryTitles.a,'旧缓存');
    shouldFail = false; store.reload();
    await until(() => store.getSnapshot().temporaryTitles.a === '实际历史');
    assert.equal(new ConversationTitles(storage).getSnapshot().a,'实际历史');
  } finally {close();}
});

test('a title-only write failure never reports a persisted message draft as memory-only', async () => {
  const storage = memoryStorage();
  const titleFailureStorage = {getItem:storage.getItem, setItem:(key,value) => {
    if (key === 'shikigen.conversation-titles.v1') throw new Error('title quota');
    storage.setItem(key,value);
  }};
  const {store,close} = startStore(titleFailureStorage,async input => {
    const path = new URL(input).pathname;
    if (path === '/api/threads') return Response.json({data:[summary('a')],next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:[message(1,'标题保存失败') ]});
    return runResponse();
  });
  try {
    await until(() => store.getSnapshot().temporaryTitles.a === '标题保存失败');
    store.updateDraft('草稿仍能持久保存');
    assert.equal(store.getSnapshot().storageIssue,null,'message/approval persistence remains available');
    assert.match(store.getSnapshot().titleStorageIssue,/本地标题保存不可用/);
    const savedDrafts = JSON.parse(storage.getItem('shikigen.message-drafts.v1'));
    assert.equal(savedDrafts.drafts.find(([threadId])=>threadId==='a')[1].text,'草稿仍能持久保存');
  } finally {close();}
});

test('late selected history cannot change the next conversation title or draft', async () => {
  const delayed = deferredResponse();
  const {store,close} = startStore(memoryStorage(),async input => {
    const path = new URL(input).pathname;
    if (path === '/api/threads') return Response.json({data:[summary('b'),summary('a')],next_cursor:null});
    if (path === '/api/threads/a/messages') return delayed.promise;
    return Response.json({data:[]});
  });
  try {
    await until(() => store.getSnapshot().listLoaded);
    store.select('a');
    await until(() => store.getSnapshot().views.a?.history === 'loading');
    store.select('b'); await until(() => store.canSend()); store.updateDraft('保持原文');
    delayed.resolve(Response.json({data:[message(1,'迟到消息')]}));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(store.getSnapshot().activeId,'b');
    assert.equal(store.getSnapshot().drafts.b,'保持原文');
    assert.equal(store.getSnapshot().temporaryTitles.a,undefined);
  } finally {close();}
});

test('time relative thresholds use elapsed duration and keep the original UTC precision', () => {
  const start = Date.parse(instant);
  for (const [elapsed, expected] of [[0,'刚刚'],[59999,'刚刚'],[60000,'1 分钟前'],
    [3599999,'59 分钟前'],[3600000,'1 小时前'],[86399999,'23 小时前'],
    [86400000,'1 天前'],[604799999,'6 天前'],[604800000,'2026/10/06']]) {
    const time = presentConversationTime(instant,start+elapsed,'Asia/Shanghai');
    assert.equal(time.relative,expected);
    assert.equal(time.utc,instant);
    assert.match(time.local,/GMT\+08:00.*Asia\/Shanghai/);
  }
});

test('local calendar grouping respects midnight, UTC day differences, DST, and year boundaries', () => {
  const now = Date.parse('2026-10-06T16:00:00Z');
  assert.equal(presentConversationTime('2026-10-06T15:59:59Z',now,'Asia/Shanghai').group,'昨天');
  assert.equal(presentConversationTime('2026-10-06T16:00:00Z',now,'Asia/Shanghai').group,'今天');
  assert.equal(presentConversationTime('2026-10-05T15:00:00Z',now,'Asia/Shanghai').group,'更早');
  const newYear = Date.parse('2027-01-01T00:00:00Z');
  assert.equal(presentConversationTime('2026-12-31T23:59:59Z',newYear,'UTC').group,'昨天');
  const springForward = Date.parse('2026-03-09T04:30:00Z');
  const dstTime = presentConversationTime('2026-03-08T05:30:00Z',springForward,'America/New_York');
  assert.equal(dstTime.group,'昨天');
  assert.equal(dstTime.relative,'23 小时前','calendar yesterday is independent of a 24-hour difference');
});

test('future timestamps are absolute, future local dates and invalid timestamps are unconfirmed', () => {
  const now = Date.parse('2026-10-06T00:00:00Z');
  const futureToday = presentConversationTime('2026-10-06T01:00:00Z',now,'Asia/Shanghai');
  assert.equal(futureToday.group,'今天'); assert.equal(futureToday.relative,'2026/10/06 09:00');
  assert.equal(presentConversationTime('2026-10-07T01:00:00Z',now,'Asia/Shanghai').group,'日期待确认');
  for (const timestamp of [undefined,null,'','unknown','2026-02-30T00:00:00Z','2026-10-06','2026-10-06T24:00:00Z',
    '2026-10-06T00:00:00+25:00','2026-10-06T00:00:00']) {
    const time = presentConversationTime(timestamp,now,'Asia/Shanghai');
    assert.equal(time.relative,'时间未知'); assert.equal(time.group,'日期待确认'); assert.equal(time.utc,null);
  }
  assert.equal(presentConversationTime('2026-10-06T08:00:00+08:00',now,'Asia/Shanghai').utc,'2026-10-06T00:00:00.000Z');
});

test('display refresh aligns to local midnight minute without adding a poll request', () => {
  assert.equal(nextConversationTimeRefresh(Date.parse('2026-10-06T15:59:59.123Z')),877);
  assert.equal(nextConversationTimeRefresh(Date.parse('2026-10-06T16:00:00Z')),60000);
});

test('examples preserve every original whitespace and append without trimming or sending', () => {
  const example = '解释当前项目的目录结构';
  assert.equal(appendTaskExample('',example),example);
  assert.equal(appendTaskExample('  原文\n 缩进  \n',example),'  原文\n 缩进  \n\n\n'+example);
  assert.equal(appendTaskExample(' \n',example),' \n\n\n'+example);
});
