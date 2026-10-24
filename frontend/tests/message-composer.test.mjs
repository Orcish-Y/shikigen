import { selectConversationWhenListed } from './helpers/select-conversation.mjs';
import assert from 'node:assert/strict';
import test, { afterEach } from 'node:test';
import { JSDOM } from 'jsdom';

const browser = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLTextAreaElement',
  'Element', 'MutationObserver', 'Event', 'KeyboardEvent', 'CompositionEvent', 'MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true, value:name === 'window' ? browser.window : browser.window[name]});
}
// jsdom has no layout engine; resizing belongs to the real WebView acceptance.
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.getComputedStyle = browser.window.getComputedStyle.bind(browser.window);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import('react');
const {render, cleanup, screen, fireEvent, act} = await import('@testing-library/react');
const {default:userEvent} = await import('@testing-library/user-event');
const {Composer, Conversation} = await import('../src/components/Conversation.tsx');
const {BackendClient} = await import('../src/backend-client.ts');
const {ConversationStore, emptyConversation} = await import('../src/conversation-state.ts');
const {presentMessage} = await import('../src/message-presentation.ts');
afterEach(cleanup);

const baseProps = {backendReady:true, draft:'原文', onChange:() => {}, onCommands:() => {},
  shortcut:'Ctrl', canSend:true, onSend:() => {}};

test('消息草稿的辅助说明让用户识别发送结果待确认，并保持可编辑', () => {
  render(React.createElement(Composer, {...baseProps, canSend:false, sendUnknown:true}));
  const draft = screen.getByRole('textbox', {name:'消息草稿', description:/发送结果待确认/});
  assert.equal(draft.disabled, false);
  assert.equal(screen.getByRole('button', {name:'发送'}).disabled, true);
});

const date = '2026-10-13T00:00:00Z';
const thread = {id:'a', title:null, user_id:null, created_at:date, updated_at:date, run_id:null, run_status:null};
const backendSnapshot = {revision:1, startup_id:'composer', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null};
const createDraftStorage = () => {
  const drafts = new Map();
  return {getItem:key => drafts.get(key) ?? null, setItem:(key, value) => drafts.set(key, value)};
};
const encodeSseFrame = (event, payload) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`);
const readResponse = url => new URL(url).pathname === '/api/threads'
  ? Response.json({data:[thread], next_cursor:null}) : Response.json({data:[]});
async function waitForExpectation(isExpectedStateFn) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (isExpectedStateFn()) return;
    await act(async () => {await new Promise(resolve => setImmediate(resolve));});
  }
  assert.fail('公开会话状态或消息 DOM 未达到预期');
}

function StoreWorkspace({store}) {
  const snapshot = React.useSyncExternalStore(store.subscribe, store.getSnapshot);
  const conversation = snapshot.views[snapshot.activeId] ?? emptyConversation;
  const draft = snapshot.drafts[snapshot.activeId] ?? '';
  return React.createElement(React.Fragment, null,
    React.createElement(Conversation, {
      session:{id:snapshot.activeId, title:'测试会话', group:'今天', summary:'',
        messages:conversation.messages.map(presentMessage), runStatuses:conversation.runStatuses},
      onSuggestion:() => {}, onView:() => {}, readState:conversation.history,
      acceptedSendId:conversation.acceptedSendId,
    }),
    React.createElement(Composer, {...baseProps, draft,
      hasConversation:Boolean(snapshot.activeId), canSend:store.canSend(), sending:conversation.sending,
      runStatus:conversation.run?.status, sendUnknown:snapshot.submissions[snapshot.activeId]?.status === 'unknown',
      onChange:nextDraft => store.updateDraft(nextDraft), onSend:() => store.send(draft),
      canCancel:store.canCancel(),
    }),
  );
}

async function startWorkspace(t, sendRequestFn) {
  const client = new BackendClient(sendRequestFn);
  const store = new ConversationStore({storage:createDraftStorage()}); selectConversationWhenListed(store, 'a');
  client.update(backendSnapshot);
  store.setSession(client.session);
  render(React.createElement(StoreWorkspace, {store}));
  t.after(() => act(() => {store.setSession(null); client.update(null);}));
  await waitForExpectation(() => store.getSnapshot().activeId && store.canSend());
  const draft = screen.getByRole('textbox', {name:'消息草稿'});
  return {store, draft, user:userEvent.setup({document:browser.window.document, delay:null})};
}

test('真实输入原文只发送一次，pending 可编辑；接受不清新草稿，流式预览转为已保存消息', async t => {
  const requests = [];
  let stream;
  const {store, draft, user} = await startWorkspace(t, async (url, init) => {
    if (init.method !== 'POST') return readResponse(url);
    requests.push(JSON.parse(init.body));
    return new Response(new ReadableStream({start:controller => {stream = controller;}}),
      {headers:{'content-type':'text/event-stream'}});
  });
  const original = '  中文原文\n    缩进  \n';
  await user.click(draft);
  await user.paste(original);
  const sendButton = screen.getByRole('button', {name:'发送'});
  act(() => {
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);
    fireEvent.keyDown(draft, {key:'Enter', keyCode:13});
  });
  await waitForExpectation(() => requests.length === 1);
  assert.equal(requests[0].message, original);
  assert.equal(draft.value, original);
  assert.equal(screen.getByRole('button', {name:'确认发送中…'}).disabled, true);
  assert.equal(screen.getByRole('button', {name:'确认发送中…'}).getAttribute('aria-busy'), 'true');
  assert.equal(draft.disabled, false);
  await user.click(draft);
  await user.keyboard('{Control>}a{/Control}');
  await user.paste('下一条\n  新草稿');
  await act(async () => {stream.enqueue(encodeSseFrame('metadata', {thread_id:'a', run_id:'first', status:'running'}));});
  await waitForExpectation(() => screen.queryByRole('button', {name:'取消运行'}));
  assert.equal(draft.value, '下一条\n  新草稿');
  assert.equal(document.activeElement, draft, '确认接受不抢走输入焦点');
  await act(async () => {
    stream.enqueue(encodeSseFrame('event', {seq:1, created_at:date, category:'message', event_type:'created',
      payload:{type:'human', message_id:'human-1', content:original}}));
    stream.enqueue(encodeSseFrame('delta', {seq:2, message_id:'ai-1', field:'content', value:'流式回答'}));
  });
  await waitForExpectation(() => screen.queryByText('流式回答'));
  assert.ok(screen.getByText('生成中 · 尚未保存'));
  await act(async () => {
    stream.enqueue(encodeSseFrame('event', {seq:2, created_at:date, category:'message', event_type:'created',
      payload:{type:'ai', message_id:'ai-1', content:'已保存回答', tool_calls:[], generation_status:'complete'}}));
    stream.enqueue(encodeSseFrame('metadata', {thread_id:'a', run_id:'first', status:'completed'}));
    stream.close();
  });
  await waitForExpectation(() => screen.queryByText('已保存回答') && store.canSend());
  assert.equal(screen.queryByText('生成中 · 尚未保存'), null);
  assert.equal(store.getSnapshot().views.a.messages.find(message => message.content.type === 'human').content.content, original);
  assert.equal(draft.value, '下一条\n  新草稿');
  assert.equal(requests.length, 1, '运行终态不能自动发送下一条草稿');
});

test('本次 POST 接受后仅清空没有被改写的原草稿', async t => {
  let stream;
  const {store, draft, user} = await startWorkspace(t, async (url, init) => init.method === 'POST'
    ? new Response(new ReadableStream({start:controller => {stream = controller;}}), {headers:{'content-type':'text/event-stream'}})
    : readResponse(url));
  await user.click(draft);
  await user.paste('这条可以清空');
  await user.click(screen.getByRole('button', {name:'发送'}));
  await waitForExpectation(() => stream);
  assert.equal(draft.value, '这条可以清空');
  await act(async () => {stream.enqueue(encodeSseFrame('metadata', {thread_id:'a', run_id:'accepted', status:'running'}));});
  await waitForExpectation(() => store.getSnapshot().submissions.a.status === 'accepted');
  assert.equal(draft.value, '');
});

test('接受前 HTTP 500 保留原文与待确认反馈，核对和重复按键均不自动重发', async t => {
  let posts = 0;
  const {store, draft, user} = await startWorkspace(t, async (url, init) => {
    if (init.method !== 'POST') return readResponse(url);
    posts++;
    return Response.json({detail:'测试服务错误'}, {status:500});
  });
  const original = '  待核对原文\n';
  await user.click(draft);
  await user.paste(original);
  await user.click(screen.getByRole('button', {name:'发送'}));
  await waitForExpectation(() => store.getSnapshot().submissions.a?.status === 'unknown' && store.getSnapshot().views.a.verified);
  assert.equal(screen.getByRole('textbox', {name:'消息草稿', description:/发送结果待确认/}).value, original);
  const sendButton = screen.getByRole('button', {name:'发送'});
  assert.equal(sendButton.disabled, true);
  act(() => {
    fireEvent.click(sendButton);
    fireEvent.keyDown(draft, {key:'Enter', keyCode:13});
    store.reload();
  });
  await waitForExpectation(() => store.getSnapshot().views.a.verified);
  assert.equal(posts, 1);
  assert.equal(draft.value, original);
  await user.click(draft);
  await user.keyboard('{Control>}a{/Control}');
  await user.paste('核对期间仍可编辑');
  assert.equal(draft.value, '核对期间仍可编辑');
  assert.equal(posts, 1);
});

test('明确拒绝的 HTTP 422 保留草稿，重新取得发送资格后仍须手动发送', async t => {
  let posts = 0;
  const {store, draft, user} = await startWorkspace(t, async (url, init) => {
    if (init.method !== 'POST') return readResponse(url);
    posts++;
    return Response.json({detail:'消息被拒绝'}, {status:422});
  });
  await user.click(draft);
  await user.paste('  失败仍保留\n');
  await user.click(screen.getByRole('button', {name:'发送'}));
  await waitForExpectation(() => posts === 1 && store.canSend());
  assert.equal(draft.value, '  失败仍保留\n');
  assert.equal(screen.getByRole('button', {name:'发送'}).disabled, false);
  assert.match(store.getSnapshot().views.a.sendFailure.message, /422/);
  assert.equal(posts, 1);
});

test('IME 组合与候选确认不发送且不拦截，Shift+Enter 换行，长按 Enter 不重复提交', async () => {
  const submissions = [];
  function DraftEditor() {
    const [draft, setDraft] = React.useState('');
    return React.createElement(Composer, {...baseProps, draft, onChange:setDraft, onSend:() => submissions.push(draft)});
  }
  render(React.createElement(DraftEditor));
  const draft = screen.getByRole('textbox', {name:'消息草稿'});
  const user = userEvent.setup({document:browser.window.document, delay:null});
  await user.click(draft);
  await user.paste('中文');
  act(() => fireEvent.compositionStart(draft));
  assert.equal(fireEvent.keyDown(draft, {key:'Enter', keyCode:13}), true);
  assert.equal(fireEvent.keyDown(draft, {key:'Enter', keyCode:229, isComposing:true}), true);
  act(() => fireEvent.compositionEnd(draft));
  const candidate = new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true, cancelable:true});
  act(() => draft.dispatchEvent(candidate));
  assert.equal(candidate.defaultPrevented, false, 'compositionend 后的候选确认交给输入法');
  assert.deepEqual(submissions, []);
  // Match the existing 50ms native candidate-confirmation guard; its timing seam
  // is covered separately in message-drafts.test.mjs.
  await new Promise(resolve => setTimeout(resolve, 60));
  await user.keyboard('{Shift>}{Enter}{/Shift}');
  assert.equal(draft.value, '中文\n');
  assert.deepEqual(submissions, []);
  act(() => fireEvent.keyDown(draft, {key:'Enter', keyCode:13, repeat:true}));
  assert.deepEqual(submissions, []);
  await user.keyboard('{Enter}');
  assert.deepEqual(submissions, ['中文\n']);
});

test('运行和审批期间可编辑，普通 Enter 不转为取消或审批，主操作仍由明确按钮触发', async () => {
  const actions = [];
  function DraftEditor({runStatus}) {
    const [draft, setDraft] = React.useState('运行期间草稿');
    return React.createElement(Composer, {...baseProps, draft, onChange:setDraft, canSend:false, runStatus,
      canCancel:true, onSend:() => actions.push('发送'), onCancel:() => actions.push('取消'), onApproval:() => actions.push('审批')});
  }
  const {rerender} = render(React.createElement(DraftEditor, {runStatus:'running'}));
  const draft = screen.getByRole('textbox', {name:'消息草稿'});
  const user = userEvent.setup({document:browser.window.document, delay:null});
  await user.click(draft);
  await user.keyboard('{Enter}');
  assert.equal(draft.value, '运行期间草稿');
  await user.keyboard('{Shift>}{Enter}{/Shift}');
  assert.equal(draft.value, '运行期间草稿\n');
  assert.deepEqual(actions, []);
  await user.click(screen.getByRole('button', {name:'取消运行'}));
  assert.deepEqual(actions, ['取消']);
  rerender(React.createElement(DraftEditor, {runStatus:'interrupted'}));
  await user.click(draft);
  await user.keyboard('{Enter}');
  assert.deepEqual(actions, ['取消']);
  await user.click(screen.getByRole('button', {name:'处理审批'}));
  assert.deepEqual(actions, ['取消', '审批']);
  assert.equal(draft.value, '运行期间草稿\n');
  assert.equal(draft.disabled, false);
});

test('欢迎页可编辑，空白草稿禁发；命令面板按钮仍可键盘聚焦', async () => {
  const actions = [];
  const {rerender} = render(React.createElement(Composer, {...baseProps, hasConversation:false, canSend:false}));
  assert.equal(screen.getByRole('textbox', {name:'消息草稿'}).disabled, false, '新会话欢迎页允许编辑草稿');
  rerender(React.createElement(Composer, {...baseProps, draft:' \n\t ', onSend:() => actions.push('发送')}));
  assert.equal(screen.getByRole('button', {name:'发送'}).disabled, true);
  const user = userEvent.setup({document:browser.window.document, delay:null});
  await user.click(screen.getByRole('textbox', {name:'消息草稿'}));
  await user.keyboard('{Enter}');
  assert.deepEqual(actions, []);
  await user.tab();
  assert.equal(document.activeElement, screen.getByRole('button', {name:'Ctrl K 命令面板'}));
});
