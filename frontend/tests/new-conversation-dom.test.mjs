import assert from 'node:assert/strict';
import test, {afterEach, beforeEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser=new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window','document','navigator','localStorage','HTMLElement','HTMLTextAreaElement','Element','MutationObserver','Event','KeyboardEvent','MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true, value:name==='window' ? browser.window : browser.window[name]});
}
globalThis.ResizeObserver=class {observe() {} disconnect() {}};
globalThis.getComputedStyle=browser.window.getComputedStyle.bind(browser.window);
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');
const {render, cleanup, screen, fireEvent, act}=await import('@testing-library/react');
const {default:userEvent}=await import('@testing-library/user-event');
const {useConversations}=await import('../src/useConversations.ts');
const {Composer, Conversation}=await import('../src/components/Conversation.tsx');
const {BackendClient}=await import('../src/backend-client.ts');

beforeEach(() => browser.window.localStorage.clear());
afterEach(cleanup);
const instant='2026-10-24T00:00:00Z';
const existing={id:'existing', title:'历史会话', user_id:null, created_at:instant, updated_at:instant, run_id:null, run_status:null};

function Workspace({session, visible=true}) {
  const conversations=useConversations(session, false, visible);
  return React.createElement(React.Fragment, null,
    React.createElement('button', {onClick:()=>void conversations.create(), disabled:!conversations.canCreate}, '新建'),
    conversations.sessions.map(conversation => React.createElement('button', {
      key:conversation.id, onClick:()=>conversations.select(conversation.id), 'aria-current':conversations.activeId===conversation.id,
    }, conversation.title)),
    React.createElement('output', {'aria-label':'当前会话'}, conversations.activeId),
    conversations.error && React.createElement('p', {role:'alert'}, conversations.error),
    React.createElement(Conversation, {session:conversations.active, readState:conversations.historyState,
      factsReady:conversations.readingFactsReady, visible, onView:()=>{},
      onSuggestion:text=>conversations.appendExample(conversations.activeId, text)}),
    React.createElement(Composer, {backendReady:Boolean(session), draft:conversations.draft,
      hasConversation:Boolean(conversations.activeId), canSend:conversations.canSend, sending:conversations.sending,
      onChange:conversations.updateDraft, onSend:()=>conversations.send(conversations.draft),
      onCommands:()=>{}, shortcut:'Ctrl', runStatus:conversations.run?.status}),
  );
}
async function until(predicate) {
  for (let attempt=0; attempt<200; attempt++) {
    if (predicate()) return;
    await act(async () => {await new Promise(resolve=>setImmediate(resolve));});
  }
  assert.fail('新会话页面未就绪');
}
function fixture(t, respond) {
  const requests=[];
  const client=new BackendClient(async (url, init) => {
    const path=new URL(url).pathname;
    requests.push({path, method:init.method ?? 'GET', body:init.body && JSON.parse(init.body)});
    const response=await respond?.(path, init);
    if (response) return response;
    return path==='/api/threads' ? Response.json({data:[existing], next_cursor:null}) : Response.json({data:[]});
  });
  client.update({revision:1, startup_id:'dom', base_url:'http://127.0.0.1:45200', state:'ready', can_retry:false, error:null});
  const workspace=render(React.createElement(Workspace, {session:client.session}));
  t.after(() => act(() => {workspace.unmount(); client.update(null);}));
  return {client, requests, workspace, user:userEvent.setup({document:browser.window.document, delay:null})};
}

test('带失效选中缓存启动仍展示欢迎页，示例只追加草稿且不发请求', async t => {
  localStorage.setItem('shikigen.message-drafts.v1', JSON.stringify({schema:1, selected:'deleted', drafts:[['deleted',{text:'历史草稿',version:1}]], submissions:[]}));
  const {requests, user}=fixture(t);
  assert.ok(screen.getByRole('heading', {name:'从一个想法开始'}));
  const draft=screen.getByRole('textbox', {name:'消息草稿'});
  assert.equal(draft.disabled, false);
  await until(() => screen.queryByRole('button', {name:'历史会话'}));
  await user.click(draft);
  await user.paste('  保留的欢迎页原文\n');
  await user.click(screen.getByRole('button', {name:'解释当前项目的目录结构'}));
  assert.equal(draft.value, '  保留的欢迎页原文\n\n\n解释当前项目的目录结构');
  assert.equal(screen.getByLabelText('当前会话').textContent, '');
  assert.deepEqual(requests.map(request=>request.path), ['/api/threads']);
  assert.equal(screen.queryByRole('alert'), null);
});

test('侧栏列表慢或失败时欢迎页和草稿仍可使用', async t => {
  let releaseList;
  const {user}=fixture(t, path=>path==='/api/threads' ? new Promise(resolve=>{releaseList=resolve;}) : undefined);
  const draft=screen.getByRole('textbox', {name:'消息草稿'});
  await user.click(draft);
  await user.paste('列表加载时编辑');
  assert.ok(screen.getByRole('heading', {name:'从一个想法开始'}));
  assert.equal(screen.queryByText('正在读取会话历史…'), null);
  await act(async () => {releaseList(Response.json({detail:'列表暂不可用'}, {status:503}));});
  assert.equal(draft.value, '列表加载时编辑');
  assert.ok(screen.getByRole('heading', {name:'从一个想法开始'}));
  assert.equal(screen.queryByText(/会话历史读取失败/), null);
});

test('欢迎页 Enter 首发创建并发送一次，历史点击与新建入口按需切换', async t => {
  let releaseCreation;
  const {requests, user}=fixture(t, (path, init) => {
    if (path==='/api/threads' && init.method==='POST') return new Promise(resolve=>{releaseCreation=resolve;});
    if (path.endsWith('/stream')) return new Response(new ReadableStream({start(controller) {
      controller.enqueue(new TextEncoder().encode('event: metadata\ndata: {"thread_id":"created","run_id":"first","status":"running"}\n\n'));
    }}), {headers:{'content-type':'text/event-stream'}});
  });
  await until(() => !screen.getByRole('button', {name:'新建'}).disabled);
  const draft=screen.getByRole('textbox', {name:'消息草稿'});
  await user.click(draft);
  await user.paste('  首发原文\n    中文  ');
  await user.keyboard('{Enter}');
  await until(() => releaseCreation);
  assert.equal(screen.getByRole('button', {name:'确认发送中…'}).disabled, true);
  fireEvent.keyDown(draft, {key:'Enter', keyCode:13});
  await act(async () => {releaseCreation(Response.json({thread_id:'created'}));});
  await until(() => screen.getByLabelText('当前会话').textContent==='created' && draft.value==='');
  assert.deepEqual(requests.filter(request=>request.method==='POST').map(({path,body})=>({path,body})), [
    {path:'/api/threads',body:undefined}, {path:'/api/threads/created/stream',body:{message:'  首发原文\n    中文  '}},
  ]);
  await user.click(screen.getByRole('button', {name:'历史会话'}));
  await until(() => requests.some(request=>request.path==='/api/threads/existing/messages'));
  await user.click(screen.getByRole('button', {name:'新建'}));
  assert.equal(screen.getByLabelText('当前会话').textContent, '');
  assert.equal(requests.filter(request=>request.method==='POST').length, 2);
});

test('托盘隐藏后显示保留已选历史会话和原文草稿', async t => {
  const {client, workspace, user}=fixture(t);
  await until(() => screen.queryByRole('button', {name:'历史会话'}));
  await user.click(screen.getByRole('button', {name:'历史会话'}));
  await until(() => !screen.queryByText('正在读取会话历史…'));
  const draft=screen.getByRole('textbox', {name:'消息草稿'});
  await user.click(draft);
  await user.paste('隐藏后继续编辑');
  workspace.rerender(React.createElement(Workspace, {session:client.session, visible:false}));
  workspace.rerender(React.createElement(Workspace, {session:client.session, visible:true}));
  await until(() => screen.getByRole('button', {name:'历史会话'}).getAttribute('aria-current')==='true');
  assert.equal(draft.value, '隐藏后继续编辑');
});
