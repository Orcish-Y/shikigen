import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window','document','navigator','HTMLElement','Element','MutationObserver','Event','KeyboardEvent','MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true, value:name === 'window' ? browser.window : browser.window[name]});
}
globalThis.getComputedStyle = browser.window.getComputedStyle.bind(browser.window);
globalThis.ResizeObserver = class {observe() {} disconnect() {} unobserve() {}};
browser.window.requestAnimationFrame = callback => setTimeout(callback, 0);
browser.window.cancelAnimationFrame = clearTimeout;
globalThis.requestAnimationFrame = browser.window.requestAnimationFrame;
globalThis.cancelAnimationFrame = clearTimeout;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import('react');
const {render, cleanup, screen, waitFor, within} = await import('@testing-library/react');
const {default:userEvent} = await import('@testing-library/user-event');
const {ToolDefinitionForm} = await import('../src/components/tools/ToolDefinitionForm.tsx');
const {ToolTestResult} = await import('../src/components/tools/ToolTestResult.tsx');
const {ToolsWorkspace} = await import('../src/components/tools/ToolsWorkspace.tsx');
const {BackendSession} = await import('../src/backend-client.ts');
afterEach(cleanup);

const schema = {type:'object', required:['display_name','url'], properties:{
  display_name:{type:'string', title:'页面名称', minLength:1},
  name:{type:'string', title:'调用名称'},
  url:{type:'string', title:'请求地址', minLength:1},
  timeout_seconds:{type:'number', title:'超时（秒）', minimum:1, maximum:300},
  input_schema:{type:'object', title:'输入结构'},
  output_schema:{type:['object','null'], title:'输出结构'},
  enabled:{type:'boolean', title:'启用'},
}};
const initial = {display_name:'',url:'',enabled:true,timeout_seconds:30,
  input_schema:{type:'object',properties:{},additionalProperties:false},output_schema:null};

test('真实业务 Form 按管理 schema 提交配置，使用本地控件并保留 schema 的实际结构', async () => {
  const user = userEvent.setup({document:browser.window.document, delay:null});
  const submitted = [];
  render(React.createElement(ToolDefinitionForm, {schema, initial, onSave:value => submitted.push(value)}));
  await user.type(screen.getByLabelText(/页面名称/), '天气查询');
  const address = screen.getByLabelText(/请求地址/);
  assert.equal(address.dataset.slot, 'input');
  await user.type(address, 'http://127.0.0.1/weather');
  await user.click(screen.getByRole('button', {name:'保存工具'}));
  assert.equal(submitted.length, 1);
  assert.equal(submitted[0].display_name, '天气查询');
  assert.equal(submitted[0].enabled, true);
  assert.equal(submitted[0].timeout_seconds, 30);
  assert.deepEqual(submitted[0].input_schema, initial.input_schema);
  assert.equal(submitted[0].output_schema, null);
});

test('真实 Tool 展示并复制所有空值和假值，完整结果保持结构', async () => {
  const user = userEvent.setup({document:browser.window.document, delay:null});
  const views = [];
  for (const data of [null,false,0,'',[],{}]) {
    const result = {status:'success', data, error:null, duration_ms:12,
      details:{status_code:200}};
    const rendered = render(React.createElement(ToolTestResult, {result, inputs:{}, onView:view => views.push(view)}));
    const output = screen.getByLabelText('工具返回 data');
    assert.equal(output.textContent, JSON.stringify(data, null, 2));
    await user.click(screen.getByRole('button', {name:'复制完整结果'}));
    assert.deepEqual(JSON.parse(await navigator.clipboard.readText()), result);
    await user.click(screen.getByRole('button', {name:'查看完整结果'}));
    assert.deepEqual(JSON.parse(views.at(-1).text), result);
    assert.deepEqual(result.data, data);
    rendered.unmount();
  }
});

function toolSession(fetcher, id='tool-session') {
  return new BackendSession(id, 'http://test', new AbortController().signal, fetcher);
}
const response = data => new Response(JSON.stringify(data), {headers:{'Content-Type':'application/json'}});

test('保存响应丢失后锁定重复创建，保留草稿并通过重读核实提交', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  let saved = null;
  let posts = 0;
  const session = toolSession(async (url, init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.endsWith('/name-candidate')) return response({data:'http_tool'});
    if (init?.method === 'POST') {
      posts++;
      saved = {...JSON.parse(init.body), id:'saved-id',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
      throw new TypeError('response lost after commit');
    }
    return response({data:saved ? [saved] : [],version:'saved-version'});
  });
  render(React.createElement(ToolsWorkspace, {session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(await screen.findByLabelText(/页面名称/),'响应丢失');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/保存结果待确认/);
  assert.equal(screen.getByLabelText(/页面名称/).value,'响应丢失');
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(posts,1);
  await user.click(screen.getByRole('button',{name:'核实保存结果'}));
  await screen.findByText('已核实工具保存结果');
  assert.ok(screen.getByText('saved-id'));
  assert.equal(posts,1);
});

test('旧宿主的迟到保存错误不会覆盖新宿主已读取的工具页面', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  let rejectSave;
  const oldSession = toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.endsWith('/name-candidate')) return response({data:'http_tool'});
    if (init?.method === 'POST') return new Promise((resolve,reject) => {rejectSave = reject;});
    return response({data:[],version:'old-version'});
  },'old');
  const workspace = render(React.createElement(ToolsWorkspace,{session:oldSession,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(await screen.findByLabelText(/页面名称/),'旧宿主');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  const newSession = toolSession(async url => response(url.endsWith('/schema/http') ? {data:schema} : {data:[],version:'new-version'}),'new');
  workspace.rerender(React.createElement(ToolsWorkspace,{session:newSession,onView:() => {}}));
  await screen.findByText(/工具库为空/);
  rejectSave(new TypeError('old backend stopped'));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  assert.equal(screen.queryByRole('alert'),null);
});

test('旧宿主手动查询的迟到错误不会覆盖新宿主页面', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const tool = {...initial,kind:'http',method:'GET',name:'http_tool',description:'',id:'old-id',display_name:'旧宿主工具',url:'http://localhost/',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
  let queries = 0;
  let rejectQuery;
  const oldSession = toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.endsWith('/tests')) return response({data:{test_id:'old-test',tool_id:tool.id,status:'running',created_at:tool.created_at,result:null}});
    if (url.includes('/tests/')) {
      if (++queries === 1) throw new TypeError('observation failed');
      return new Promise((resolve,reject) => {rejectQuery = reject;});
    }
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version:'version'});
  },'old-query');
  const workspace = render(React.createElement(ToolsWorkspace,{session:oldSession,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/旧宿主工具/}));
  await user.click(await screen.findByRole('button',{name:'测试已保存工具'}));
  await user.click(await screen.findByRole('button',{name:'重新查询测试'}));
  const newSession = toolSession(async url => response(url.endsWith('/schema/http') ? {data:schema} : {data:[],version:'new-version'}),'new-query');
  workspace.rerender(React.createElement(ToolsWorkspace,{session:newSession,onView:() => {}}));
  await screen.findByText(/工具库为空/);
  rejectQuery(new TypeError('old query cancelled'));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  assert.equal(screen.queryByRole('alert'),null);
});

test('工具侧栏在编辑时保留，并按真实工具名称和启用状态过滤', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const weather = {...initial,kind:'http',method:'GET',name:'weather',description:'读取天气',id:'weather-id',display_name:'天气查询',url:'http://localhost/weather',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
  const stock = {...weather,id:'stock-id',name:'stock',display_name:'库存查询',description:'读取库存',enabled:false};
  const session = toolSession(async url => response(url.endsWith('/schema/http')
    ? {data:schema} : {data:url.endsWith('/api/tools') ? [weather,stock] : weather,version:'version'}));
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  const sidebar = await screen.findByRole('complementary',{name:'工具库'});
  await user.click(await within(sidebar).findByRole('button',{name:/天气查询/}));
  assert.ok(within(sidebar).getByRole('button',{name:/库存查询/}));
  assert.ok(screen.getByRole('region',{name:'工具配置'}));
  assert.ok(screen.getByRole('region',{name:'快速测试调试'}));
  assert.ok(screen.getByRole('region',{name:'最近一次测试'}));
  assert.equal(screen.queryByRole('button',{name:'Submit'}),null);
  await user.type(within(sidebar).getByRole('searchbox',{name:'搜索工具'}),'库存');
  assert.equal(within(sidebar).queryByRole('button',{name:/天气查询/}),null);
  assert.ok(within(sidebar).getByRole('button',{name:/库存查询/}));
  await user.clear(within(sidebar).getByRole('searchbox',{name:'搜索工具'}));
  await user.click(within(sidebar).getByRole('button',{name:/已禁用.*1/}));
  assert.equal(within(sidebar).queryByRole('button',{name:/天气查询/}),null);
  assert.ok(within(sidebar).getByRole('button',{name:/库存查询/}));
  assert.equal(screen.queryByText(/HITL|Rust Sandbox|1,429|近 24 小时调用历史/),null);
});
