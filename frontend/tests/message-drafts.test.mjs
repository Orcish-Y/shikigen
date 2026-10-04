import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { composerEnter } from '../src/composer-keyboard.ts';

const date = '2026-10-05T00:00:00Z';
const thread = id => ({id, title:null, user_id:null, created_at:date, updated_at:date, run_id:null, run_status:null});
const ready = {revision:1, startup_id:'lease', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null};
const memory = () => {
  const values = new Map();
  return {getItem:key => values.get(key) ?? null, setItem:(key, value) => values.set(key, value)};
};
async function until(probe) {
  for (let i = 0; i < 200; i++) {
    if (probe()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('公开会话状态没有就绪');
}
function setup(storage, transport = async (url, init) => {
  assert.notEqual(init.method, 'POST', '恢复文字不能恢复执行');
  return new URL(url).pathname === '/api/threads'
    ? Response.json({data:[thread('a'), thread('b')], next_cursor:null}) : Response.json({data:[]});
}) {
  const client = new BackendClient(transport);
  const store = new ConversationStore({storage});
  client.update(ready);
  store.setSession(client.session);
  return {store, close:() => {store.setSession(null); client.update(null);}};
}

test('会话草稿按原文跨切换和应用重启保留，恢复不发出 POST', async () => {
  const storage = memory();
  const first = setup(storage);
  await until(() => first.store.canSend());
  first.store.updateDraft('  第一条\n    中文缩进\n');
  first.store.select('b');
  await until(() => first.store.canSend());
  first.store.updateDraft('第二个会话');
  first.close();
  const second = setup(storage);
  await until(() => second.store.canSend());
  assert.equal(second.store.getSnapshot().activeId, 'b');
  assert.equal(second.store.getSnapshot().drafts.b, '第二个会话');
  second.store.select('a');
  assert.equal(second.store.getSnapshot().drafts.a, '  第一条\n    中文缩进\n');
  second.close();
});

test('Enter 与按钮共享发送资格，IME/候选确认/长按不提交，不可发时只允许 Shift+Enter 换行', () => {
  let sent = 0;
  const key = (overrides = {}) => {
    let blocked = false;
    const event = {key:'Enter', shiftKey:false, repeat:false, isComposing:false, keyCode:13,
      timeStamp:1000, preventDefault:() => blocked = true, ...overrides};
    return {event, blocked:() => blocked};
  };
  const ordinary = key(); composerEnter(ordinary.event, true, () => sent++);
  assert.equal(sent, 1); assert.equal(ordinary.blocked(), true);
  for (const allowed of [false, true]) {
    const held = key({repeat:true}); composerEnter(held.event, allowed, () => sent++);
    assert.equal(held.blocked(), true);
    const shift = key({shiftKey:true}); composerEnter(shift.event, allowed, () => sent++);
    assert.equal(shift.blocked(), false);
  }
  const disabled = key(); composerEnter(disabled.event, false, () => sent++);
  assert.equal(disabled.blocked(), true);
  for (const options of [{isComposing:true}, {keyCode:229}]) {
    const candidate = key(options); composerEnter(candidate.event, true, () => sent++);
    assert.equal(candidate.blocked(), false);
  }
  const candidate = key(); composerEnter(candidate.event, true, () => sent++, false, 980);
  assert.equal(candidate.blocked(), false);
  assert.equal(sent, 1);
});

test('确认接受清对应版本，已知运行断流/重开仅 GET，稀疏历史仍核实已接受 Run', async () => {
  const storage = memory();
  let stream, posts = 0;
  const first = setup(storage, async (url, init) => {
    if (init.method === 'POST') {
      posts++;
      return new Response(new ReadableStream({start:controller => stream = controller}), {headers:{'Content-Type':'text/event-stream'}});
    }
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => first.store.canSend());
  first.store.updateDraft('原文'); first.store.send('原文');
  await until(() => stream);
  stream.enqueue(encode('metadata', {thread_id:'a', run_id:'accepted', status:'running'}));
  await until(() => first.store.getSnapshot().drafts.a === '');
  first.store.updateDraft('下一条草稿');
  first.close();
  const reads = [];
  const second = setup(storage, async (url, init) => {
    assert.notEqual(init.method, 'POST'); reads.push(new URL(url).pathname);
    if (url.endsWith('/messages')) return Response.json({data:[]});
    if (new URL(url).pathname === '/api/threads') return Response.json({data:[thread('a')], next_cursor:null});
    return Response.json({data:{id:'accepted', thread_id:'a', status:'completed'}});
  });
  await until(() => second.store.canSend());
  assert.equal(second.store.getSnapshot().views.a.run.run_id, 'accepted');
  assert.equal(second.store.getSnapshot().drafts.a, '下一条草稿');
  assert.ok(reads.includes('/api/threads/a/runs/accepted'));
  assert.equal(posts, 1);
  second.close();
});

test('旧 pending 在重开后是待核实；查询无消息仍保留，用户确认新任务才再次 POST', async () => {
  const storage = memory();
  let posts = 0;
  const first = setup(storage, async (url, init) => {
    if (init.method === 'POST') { posts++; return new Promise(() => {}); }
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => first.store.canSend());
  first.store.updateDraft('原请求'); first.store.send('原请求');
  // 模拟突然退出，重建前不要让原 owner 将 pending 改成 unknown。
  const second = setup(storage, async (url, init) => {
    if (init.method === 'POST') {
      posts++; assert.equal(JSON.parse(init.body).message, '原请求');
      return new Response(encode('metadata', {thread_id:'a', run_id:'new-task', status:'completed'}), {headers:{'Content-Type':'text/event-stream'}});
    }
    if (new URL(url).pathname === '/api/threads') return Response.json({data:[thread('a')], next_cursor:null});
    if (url.endsWith('/messages')) return Response.json({data:[]});
    return Response.json({data:{id:'new-task', thread_id:'a', status:'completed'}});
  });
  await until(() => second.store.getSnapshot().views.a?.verified);
  const record = second.store.getSnapshot().submissions.a;
  assert.equal(record.status, 'unknown');
  assert.equal(second.store.canSend(), false);
  assert.equal(posts, 1);
  second.store.updateDraft('新编辑的文字');
  assert.equal(second.store.sendAsNewTask('过期记录'), false);
  assert.equal(second.store.sendAsNewTask(record.id), true);
  await until(() => second.store.getSnapshot().submissions.a.status === 'accepted');
  assert.equal(second.store.getSnapshot().drafts.a, '新编辑的文字');
  assert.equal(posts, 2);
  first.close(); second.close();
});

const encode = (event, data) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
test('本次 POST metadata 才确认接受；原文发送，改写后同文的新版本不被清空', async () => {
  let stream, posts = 0;
  const {store, close} = setup(memory(), async (url, init) => {
    if (init.method === 'POST') {
      posts++;
      assert.equal(JSON.parse(init.body).message, '  中文\n    缩进\n');
      return new Response(new ReadableStream({start:controller => stream = controller}), {headers:{'Content-Type':'text/event-stream'}});
    }
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => store.canSend());
  store.updateDraft('  中文\n    缩进\n');
  assert.equal(store.send(store.getSnapshot().drafts.a), true);
  await until(() => stream);
  assert.equal(store.getSnapshot().submissions.a.status, 'pending');
  assert.equal(store.getSnapshot().drafts.a, '  中文\n    缩进\n');
  store.updateDraft('下一条');
  store.updateDraft('  中文\n    缩进\n');
  assert.equal(store.send('重复'), false);
  stream.enqueue(encode('metadata', {thread_id:'a', run_id:'new', status:'running'}));
  await until(() => store.getSnapshot().views.a.run?.run_id === 'new');
  assert.equal(store.getSnapshot().submissions.a.status, 'accepted');
  assert.equal(store.getSnapshot().views.a.sending, false);
  assert.equal(store.getSnapshot().drafts.a, '  中文\n    缩进\n');
  store.updateDraft('下一条运行草稿');
  assert.equal(posts, 1);
  close();
});

test('接受前 POST 500 只 GET 核对；同文历史不解锁，人工确认才清对应版本', async () => {
  let posts = 0, sent = false;
  const original = '  保留原文\n';
  const saved = {id:1, thread_id:'a', run_id:'existing', run_status:'completed', seq:2, event_type:'created', category:'message',
    event_key:null, metadata:{}, created_at:date, content:{type:'human', message_id:'same-text', content:original}};
  const {store, close} = setup(memory(), async (url, init) => {
    const path = new URL(url).pathname;
    if (init.method === 'POST') { posts++; sent = true; return Response.json({detail:'服务失败'}, {status:500}); }
    if (path === '/api/threads') return Response.json({data:[thread('a')], next_cursor:null});
    if (path.endsWith('/messages')) return Response.json({data:sent ? [saved] : []});
    return Response.json({data:{id:'existing', thread_id:'a', status:'completed'}});
  });
  await until(() => store.canSend());
  store.updateDraft(original);
  store.send(original);
  await until(() => store.getSnapshot().views.a.verified && store.getSnapshot().views.a.messages.length);
  const record = store.getSnapshot().submissions.a;
  assert.equal(record.status, 'unknown');
  assert.match(record.error, /500/);
  assert.equal(store.canSend(), false);
  assert.equal(store.getSnapshot().drafts.a, original);
  assert.equal(posts, 1);
  assert.equal(store.confirmSend(999, record.id), false);
  assert.equal(store.confirmSend(2, record.id), true);
  assert.equal(store.getSnapshot().drafts.a, '');
  assert.equal(store.canSend(), true);
  assert.equal(posts, 1);
  close();
});

test('空白禁发；运行/审批期间编辑草稿，终态不排队、不自动发送', async () => {
  let stream, posts = 0;
  const {store, close} = setup(memory(), async (url, init) => {
    if (init.method === 'POST') {
      posts++;
      return new Response(new ReadableStream({start:controller => stream = controller}), {headers:{'Content-Type':'text/event-stream'}});
    }
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => store.canSend());
  assert.equal(store.send(' \n\t '), false);
  assert.equal(posts, 0);
  store.updateDraft('第一条'); store.send('第一条');
  await until(() => stream);
  for (const status of ['running','interrupted','completed']) {
    stream.enqueue(encode('metadata', {thread_id:'a', run_id:'one', status}));
    await until(() => store.getSnapshot().views.a.run?.status === status);
    store.updateDraft('下一条仍须手动发送');
    assert.equal(store.getSnapshot().drafts.a, '下一条仍须手动发送');
    if (status !== 'completed') assert.equal(store.send('不准排队'), false);
  }
  assert.equal(store.canSend(), true);
  assert.equal(posts, 1);
  close();
});

test('接受前解析/网络/HTTP 200 空流均保留未知，GET 不清草稿', async t => {
  for (const [name, response] of [
    ['解析', () => new Response('event: metadata\ndata: {坏 JSON}\n\n', {headers:{'Content-Type':'text/event-stream'}})],
    ['网络', () => { throw new TypeError('网络已断开'); }],
    ['HTTP200空流', () => new Response('', {headers:{'Content-Type':'text/event-stream'}})],
  ]) await t.test(name, async () => {
    let posts = 0;
    const {store, close} = setup(memory(), async (url, init) => {
      if (init.method === 'POST') { posts++; return response(); }
      return new URL(url).pathname === '/api/threads'
        ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
    });
    await until(() => store.canSend());
    store.updateDraft('待核对原文'); store.send('待核对原文');
    await until(() => store.getSnapshot().submissions.a?.status === 'unknown' && store.getSnapshot().views.a.verified);
    assert.equal(store.getSnapshot().drafts.a, '待核对原文');
    assert.equal(store.canSend(), false);
    assert.equal(posts, 1);
    close();
  });
});

test('切换中止未确认 POST，迟到接受不能修改旧会话或新会话草稿', async () => {
  let reply;
  const {store, close} = setup(memory(), async (url, init) => {
    if (init.method === 'POST') return new Promise(resolve => reply = resolve);
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a'), thread('b')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => store.canSend());
  store.updateDraft('a 原文'); store.send('a 原文');
  await until(() => reply);
  store.select('b'); store.updateDraft('b 新草稿');
  reply(new Response(encode('metadata', {thread_id:'a', run_id:'late', status:'running'}), {headers:{'Content-Type':'text/event-stream'}}));
  await until(() => store.canSend());
  assert.equal(store.getSnapshot().drafts.a, 'a 原文');
  assert.equal(store.getSnapshot().drafts.b, 'b 新草稿');
  assert.equal(store.getSnapshot().submissions.a.status, 'unknown');
  close();
});

test('503 遵守 Retry-After，400/409/422 不自动重发且保留草稿', async t => {
  for (const status of [503,400,409,422]) await t.test(String(status), async () => {
    let posts = 0;
    const {store, close} = setup(memory(), async (url, init) => {
      if (init.method === 'POST') { posts++; return Response.json({detail:'原始错误'}, {status, headers:{'Retry-After':'300'}}); }
      return new URL(url).pathname === '/api/threads'
        ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
    });
    await until(() => store.canSend());
    store.updateDraft('请求正文'); store.send('请求正文');
    await until(() => !store.getSnapshot().views.a.sending && store.getSnapshot().views.a.verified);
    assert.equal(store.getSnapshot().drafts.a, '请求正文');
    if (status === 503) {
      assert.equal(store.getSnapshot().submissions.a.status, 'unknown');
      assert.equal(store.canSendAsNewTask(), false);
      assert.equal(store.sendAsNewTask(store.getSnapshot().submissions.a.id), false);
    } else assert.equal(store.canSend(), true);
    assert.equal(posts, 1);
    close();
  });
});

test('本地写入失败保留内存并提示，会话 404 可复制到新会话且保留源文字', async () => {
  const storage = {getItem:() => null, setItem:() => { throw new Error('quota exceeded'); }};
  let missing = false, creates = 0;
  const {store, close} = setup(storage, async (url, init) => {
    if (init.method === 'POST') { creates++; return Response.json({thread_id:'new'}); }
    if (new URL(url).pathname === '/api/threads') return Response.json({data:[thread('a'), ...(creates ? [thread('new')] : [])], next_cursor:null});
    if (missing && url.endsWith('/a/messages')) return Response.json({detail:'deleted'}, {status:404});
    return Response.json({data:[]});
  });
  await until(() => store.canSend());
  store.updateDraft('  可恢复的文字\n');
  assert.match(store.getSnapshot().storageIssue, /本地保存不可用/);
  missing = true; store.reload();
  await until(() => store.getSnapshot().views.a.missing);
  assert.equal(store.canSend(), false);
  await store.copyDraftToNewConversation();
  assert.equal(store.getSnapshot().drafts.new, '  可恢复的文字\n');
  assert.equal(store.getSnapshot().drafts.a, '  可恢复的文字\n');
  assert.equal(creates, 1);
  close();
});

test('接受 Run 快照 404 不误报会话删除，恢复线索和下一条草稿保留', async () => {
  const storage = memory();
  let stream;
  const first = setup(storage, async (url, init) => {
    if (init.method === 'POST') return new Response(new ReadableStream({start:c => stream = c}), {headers:{'Content-Type':'text/event-stream'}});
    return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread('a')], next_cursor:null}) : Response.json({data:[]});
  });
  await until(() => first.store.canSend());
  first.store.updateDraft('第一条'); first.store.send('第一条');
  await until(() => stream);
  stream.enqueue(encode('metadata', {thread_id:'a', run_id:'accepted', status:'running'}));
  await until(() => first.store.getSnapshot().submissions.a.status === 'accepted');
  first.store.updateDraft('保留下一条'); first.close();
  const second = setup(storage, async url => {
    if (url.endsWith('/messages')) return Response.json({data:[]});
    if (new URL(url).pathname === '/api/threads') return Response.json({data:[thread('a')], next_cursor:null});
    return Response.json({detail:'Run not found'}, {status:404});
  });
  await until(() => second.store.getSnapshot().views.a?.error);
  assert.equal(second.store.getSnapshot().views.a.missing, false);
  assert.match(second.store.getSnapshot().views.a.error, /运行不可读取/);
  assert.equal(second.store.getSnapshot().drafts.a, '保留下一条');
  assert.equal(second.store.canSend(), false);
  second.close();
});

test('本地存储 API 缺失或被禁用也提示内存保存，文字仍可编辑', async () => {
  const {store, close} = setup(null);
  await until(() => store.canSend());
  assert.match(store.getSnapshot().storageIssue, /本地保存不可用/);
  store.updateDraft('  内存仍保留\n');
  assert.equal(store.getSnapshot().drafts.a, '  内存仍保留\n');
  close();
});
