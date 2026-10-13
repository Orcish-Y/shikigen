import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'MutationObserver',
  'Event', 'KeyboardEvent', 'MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true,
    value:name === 'window' ? browser.window : browser.window[name]});
}
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.getComputedStyle = browser.window.getComputedStyle.bind(browser.window);
globalThis.requestAnimationFrame = callback => setTimeout(callback, 0);
globalThis.cancelAnimationFrame = clearTimeout;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import('react');
const {render, cleanup, screen, within, act} = await import('@testing-library/react');
const {default:userEvent} = await import('@testing-library/user-event');
const {MessageBody} = await import('../src/components/MessageBody.tsx');
const {Conversation} = await import('../src/components/Conversation.tsx');
const {BackendClient} = await import('../src/backend-client.ts');
const {ConversationStore, emptyConversation} = await import('../src/conversation-state.ts');
const {presentMessage} = await import('../src/message-presentation.ts');
afterEach(cleanup);

const createUser = () => userEvent.setup({document:browser.window.document, delay:null});
const bodyProps = {role:'assistant', identity:'reasoning-message', onView:() => {}};
const createThinkingBlock = text => ({type:'thinking', thinking:text, signature:'原始签名'});
const renderBody = props => React.createElement(MessageBody, {...bodyProps, ...props});

test('推理默认展开；用户折叠后状态变化与内容更新不覆盖选择，子控件继续挂载', async () => {
  const user = createUser();
  const initial = '  **思考原文**\n\n段落一  \n';
  const workspace = render(renderBody({content:[createThinkingBlock(initial)], preview:true, generating:true}));
  const panel = screen.getByRole('region', {name:'思考链路'});
  const toggle = within(panel).getByRole('button', {name:/思考链路.*生成中/});
  const body = document.getElementById(toggle.getAttribute('aria-controls'));
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(body.hidden, false);
  const rawToggle = within(panel).getByText('查看原始思考块');
  await user.click(rawToggle);
  assert.equal(rawToggle.parentElement.open, true);
  await user.click(within(panel).getByRole('button', {name:'复制当前思考片段'}));
  assert.equal(await navigator.clipboard.readText(), initial);
  await user.click(toggle);
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(body.hidden, true);
  assert.equal(rawToggle.isConnected, true);
  workspace.rerender(renderBody({content:[createThinkingBlock(initial + '\n持续新增原文')], preview:true, generating:false}));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(body.hidden, true);
  workspace.rerender(renderBody({content:[createThinkingBlock(initial + '\n持续新增原文')], preview:true, generating:true}));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement, toggle);
  workspace.rerender(renderBody({content:[createThinkingBlock(initial + '\n持续新增原文')]}));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  await user.keyboard('{Enter}');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(body.hidden, false);
  assert.equal(within(panel).getByText('查看原始思考块'), rawToggle);
  assert.equal(rawToggle.parentElement.open, true);
  assert.match(body.textContent, /持续新增原文/);
  assert.equal(within(panel).getByRole('button', {name:'复制思考内容'}).textContent, '已复制');
  // Upstream's delayed auto-close must not undo an explicit user expansion.
  await act(async () => {await new Promise(resolve => setTimeout(resolve, 1100));});
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
});

test('完整推理查看与复制保持精确原文和真实范围，复制失败可恢复', async () => {
  const user = createUser();
  const views = [];
  const original = '  **精确原文**\n\n```python\n  value = 0\n```\n尾部  \n';
  const source = {type:'reasoning', reasoning:original, extras:{values:[0, false, null]}};
  const workspace = render(renderBody({content:[source], preview:true, generating:false,
    onView:view => views.push(view)}));
  const panel = screen.getByRole('region', {name:'思考链路'});
  assert.ok(within(panel).getByText('预览'));
  await user.click(within(panel).getByRole('button', {name:'查看完整思考'}));
  assert.deepEqual(views.at(-1), {title:'完整思考内容', text:original, preview:true, generating:false});
  await user.click(within(panel).getByRole('button', {name:'复制当前思考片段'}));
  assert.equal(await navigator.clipboard.readText(), original);
  await user.click(within(panel).getByText('查看原始思考块'));
  assert.equal(within(panel).getByLabelText('原始思考块 JSON').textContent, JSON.stringify(source, null, 2));
  workspace.rerender(renderBody({content:[source], onView:view => views.push(view)}));
  Object.defineProperty(navigator.clipboard, 'writeText', {configurable:true, value:async () => {
    throw new Error('clipboard denied');
  }});
  await user.click(within(panel).getByRole('button', {name:'复制思考内容'}));
  assert.equal(within(panel).getByRole('status').textContent, '复制失败，可手动选择');
  let copiedText;
  Object.defineProperty(navigator.clipboard, 'writeText', {configurable:true, value:async text => {copiedText = text;}});
  await user.click(within(panel).getByRole('button', {name:'复制思考内容'}));
  assert.equal(copiedText, original);
  assert.equal(within(panel).queryByRole('status'), null);
  assert.equal(within(panel).getByRole('button', {name:'复制思考内容'}).textContent, '已复制');
  await user.click(within(panel).getByRole('button', {name:'查看完整思考'}));
  assert.deepEqual(views.at(-1), {title:'完整思考内容', text:original, preview:undefined, generating:undefined});
});

test('每个推理块独立键盘折叠，空与未知内容不伪造推理，正文策略继续生效', async () => {
  const user = createUser();
  const unknownReasoningBlock = {type:'reasoning', encrypted_content:'opaque', values:[0, false, null]};
  const workspace = render(renderBody({content:[createThinkingBlock('  '), unknownReasoningBlock,
    {type:'reasoning', summary:[{type:'summary_text', text:'摘要一'}, {type:'summary_text', text:'摘要二'}]},
    {type:'reasoning', reasoning:'<script>window.__injected=true</script>\n\n![远程](https://example.org/no-load.png)'}]}));
  const panels = screen.getAllByRole('region', {name:'思考链路'});
  assert.equal(panels.length, 3);
  const toggles = panels.map(panel => within(panel).getByRole('button', {name:/思考链路/}));
  assert.equal(new Set(toggles.map(toggle => toggle.getAttribute('aria-controls'))).size, 3);
  toggles[0].focus();
  await user.keyboard(' ');
  assert.equal(toggles[0].getAttribute('aria-expanded'), 'false');
  assert.equal(toggles[1].getAttribute('aria-expanded'), 'true');
  await user.keyboard('{Enter}');
  assert.ok(within(panels[0]).getByText('未提供思考文本。'));
  assert.ok(within(panels[1]).getByText('摘要一'));
  assert.ok(within(panels[1]).getByText('摘要二'));
  assert.equal(screen.getByLabelText('内容块 JSON').textContent, JSON.stringify(unknownReasoningBlock, null, 2));
  assert.ok(within(panels[2]).getByText('网页图片未自动加载'));
  assert.equal(document.querySelector('.message-content script,.message-content img'), null);
  assert.equal(browser.window.__injected, undefined);
  workspace.rerender(renderBody({role:'user', content:[unknownReasoningBlock]}));
  assert.equal(screen.queryByRole('region', {name:'思考链路'}), null);
});

const date = '2026-10-13T00:00:00Z';
const thread = {id:'a', title:null, user_id:null, created_at:date, updated_at:date, run_id:null, run_status:null};
const backendSnapshot = {revision:1, startup_id:'reasoning', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null};
const encodeSseFrame = (event, payload) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`);
async function waitForExpectation(isExpectedStateFn) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (isExpectedStateFn()) return;
    await act(async () => {await new Promise(resolve => setImmediate(resolve));});
  }
  assert.fail('公开会话或消息 DOM 未达到预期');
}
function StoreConversation({store}) {
  const snapshot = React.useSyncExternalStore(store.subscribe, store.getSnapshot);
  const conversation = snapshot.views[snapshot.activeId] ?? emptyConversation;
  return React.createElement(Conversation, {session:{id:snapshot.activeId, title:'推理验收', group:'今天',
    summary:'', messages:conversation.messages.map(presentMessage), runStatuses:conversation.runStatuses},
  onSuggestion:() => {}, onView:() => {}, readState:conversation.history});
}

test('真实会话投影通过HTTP/SSE接收已保存推理，随后正文增量与终态不抢走折叠和焦点', async t => {
  let stream;
  const requests = [];
  const client = new BackendClient(async (url, init) => {
    if (init.method !== 'POST') return new URL(url).pathname === '/api/threads'
      ? Response.json({data:[thread], next_cursor:null}) : Response.json({data:[]});
    requests.push(JSON.parse(init.body));
    return new Response(new ReadableStream({start:controller => {stream = controller;}}),
      {headers:{'content-type':'text/event-stream'}});
  });
  const store = new ConversationStore({storage:{getItem:() => null, setItem:() => {}}});
  client.update(backendSnapshot);
  store.setSession(client.session);
  render(React.createElement(StoreConversation, {store}));
  t.after(() => act(() => {store.setSession(null); client.update(null);}));
  await waitForExpectation(() => store.canSend());
  act(() => {store.send('公开消息链路');});
  await waitForExpectation(() => stream);
  const reasoning = createThinkingBlock('已保存的**真实推理**\n\n后续正文仍在生成。');
  await act(async () => {
    stream.enqueue(encodeSseFrame('metadata', {thread_id:'a', run_id:'run-reasoning', status:'running'}));
    stream.enqueue(encodeSseFrame('event', {seq:1, created_at:date, category:'message', event_type:'created',
      payload:{type:'ai', message_id:'reasoning-saved', content:[reasoning], tool_calls:[], generation_status:'complete'}}));
    stream.enqueue(encodeSseFrame('delta', {seq:2, message_id:'answer', field:'content', value:'正文流开始'}));
  });
  await waitForExpectation(() => screen.queryByRole('region', {name:'思考链路'}) && screen.queryByText('正文流开始'));
  const panel = screen.getByRole('region', {name:'思考链路'});
  const toggle = within(panel).getByRole('button', {name:/思考链路/});
  await createUser().click(toggle);
  assert.equal(document.activeElement, toggle);
  await act(async () => {stream.enqueue(encodeSseFrame('delta', {seq:2, message_id:'answer', field:'content', value:'，正文持续更新'}));});
  await waitForExpectation(() => screen.queryByText('正文流开始，正文持续更新'));
  assert.ok(screen.getByText('生成中 · 尚未保存'));
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement, toggle);
  assert.equal(within(panel).queryByText('生成中'), null, '已保存推理不是后端推理增量预览');
  await act(async () => {
    stream.enqueue(encodeSseFrame('event', {seq:2, created_at:date, category:'message', event_type:'created',
      payload:{type:'ai', message_id:'answer', content:'正文流开始，正文持续更新', tool_calls:[], generation_status:'complete'}}));
    stream.enqueue(encodeSseFrame('metadata', {thread_id:'a', run_id:'run-reasoning', status:'completed'}));
    stream.close();
  });
  await waitForExpectation(() => store.canSend());
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement, toggle);
  assert.equal(screen.queryByText('生成中 · 尚未保存'), null);
  assert.deepEqual(store.getSnapshot().views.a.messages[0].content.content, [reasoning]);
  assert.deepEqual(requests, [{message:'公开消息链路'}]);
});

for (const [status, badge] of [['cancelled', '因取消中止'], ['error', '因失败中止']]) {
  test(`已保存${status}推理保留中止事实和原文入口`, async () => {
    const views = [];
    render(React.createElement(Conversation, {session:{id:'aborted', title:'中止推理', group:'今天', summary:'',
      runStatuses:{'aborted-run':status}, messages:[presentMessage({run_id:'aborted-run', seq:1,
        content:{type:'ai', message_id:'aborted-reasoning', content:[createThinkingBlock('已保存原文')],
          tool_calls:[], generation_status:status}})]}, onSuggestion:() => {}, onView:view => views.push(view)}));
    assert.ok(screen.getByText(badge));
    assert.equal(screen.queryByText('生成中 · 尚未保存'), null);
    const panel = screen.getByRole('region', {name:'思考链路'});
    await createUser().click(within(panel).getByRole('button', {name:'查看完整思考'}));
    assert.equal(views.at(-1).text, '已保存原文');
    assert.equal(Boolean(views.at(-1).preview), false);
    assert.equal(views.at(-1).generating, false);
  });
}
