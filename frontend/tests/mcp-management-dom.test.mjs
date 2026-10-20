import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'});
for (const name of ['window','document','navigator','Window','HTMLElement','Element','Node','Text','MutationObserver','Event','KeyboardEvent','MouseEvent'])
  Object.defineProperty(globalThis,name,{configurable:true,value:name === 'window' ? browser.window : browser.window[name]});
globalThis.getComputedStyle=browser.window.getComputedStyle.bind(browser.window);
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
browser.window.HTMLDialogElement.prototype.showModal=function () {this.setAttribute('open','');};
browser.window.HTMLDialogElement.prototype.close=function () {this.removeAttribute('open');};
const React=await import('react');
const {render,cleanup,screen,waitFor,fireEvent}=await import('@testing-library/react');
const {default:userEvent}=await import('@testing-library/user-event');
const {McpWorkspace}=await import('../src/components/tools/McpWorkspace.tsx');
const {BackendSession}=await import('../src/backend-client.ts');
afterEach(cleanup);

const schema={type:'object',required:['display_name','command'],properties:{
  display_name:{type:'string',minLength:1,title:'连接名称'},command:{type:'string',minLength:1,title:'启动命令'},
  transport:{type:'string',const:'stdio'},args:{type:'array',items:{type:'string'},title:'启动参数'},
  env:{type:'object',additionalProperties:{type:'string'},title:'环境变量'},
  cwd:{type:['string','null'],title:'工作目录（可选）'},
  test_timeout_seconds:{type:'number',title:'连接测试预算（秒）'},discovery_timeout_seconds:{type:'number',title:'工具发现预算（秒）'},
}};
const connection={id:'server-1',display_name:'本地服务',command:'python',transport:'stdio',args:[],env:{},cwd:null,
  test_timeout_seconds:30,discovery_timeout_seconds:30,created_at:'2026-10-18T00:00:00Z',updated_at:'2026-10-18T00:00:00Z'};
const source={name:'search',description:'查找',inputSchema:{type:'object',properties:{query:{type:'string'}},required:['query']}};
const json=(data,status=200) => new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const httpSchema={type:'object',required:['display_name','url'],properties:{
  display_name:{type:'string',minLength:1,title:'连接名称'},
  transport:{type:'string',const:'streamable_http'},url:{type:'string',minLength:1,title:'远程 MCP URL'},
  headers:{type:'object',additionalProperties:{type:'string'},title:'请求头'},
  test_timeout_seconds:{type:'number',title:'连接测试预算（秒）'},discovery_timeout_seconds:{type:'number',title:'工具发现预算（秒）'},
}};

test('重新发现预览来源变化和未发现项，只应用勾选更新并展示所属工具',async () => {
  const opened=[],requests=[];
  const saved={id:'tool-search',kind:'mcp',connection_id:connection.id,remote_name:'search',name:'local_search',display_name:'本地搜索',source_tool:source};
  const missing={...saved,id:'tool-gone',remote_name:'gone',name:'local_gone',display_name:'保留工具'};
  const changed={...source,inputSchema:{type:'object',properties:{term:{type:'string'}}}};
  const changes=[{remote_name:'search',status:'changed',tool_id:saved.id,local_name:saved.name,source_tool:changed,previous_source_tool:source},
    {remote_name:'added',status:'new',tool_id:null,local_name:null,source_tool:{...source,name:'added'},previous_source_tool:null},
    {remote_name:'gone',status:'missing',tool_id:missing.id,local_name:missing.name,source_tool:null,previous_source_tool:source}];
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;requests.push({path,...init});
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[saved,missing],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections') return json({data:[connection],version:'v1'});
    if (path === '/api/mcp/connections/server-1') return json({data:connection,version:'v1'});
    if (path.endsWith('/discover')) return json({data:{status:'success',connection_id:connection.id,duration_ms:3,error:null,discovery_id:'d1',version:'v1',tools:[changed,{...source,name:'added'}],changes}});
    if (path.endsWith('/imports')) return json({data:[{id:saved.id,remote_name:'search',existing:true}]});
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:id => opened.push(id),initialConnectionId:connection.id}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'发现工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'发现工具'}));
  await screen.findByText('来源变化');
  assert.equal(screen.getAllByText('本次未发现').length,2);
  assert.ok(screen.getByText('新增'));
  assert.equal(screen.queryByRole('checkbox',{name:'选择 gone'}),null);
  assert.equal(screen.getByLabelText('search 本地调用名称').value,'local_search');
  assert.equal(screen.getByLabelText('search 本地调用名称').disabled,true);
  await user.click(screen.getByRole('checkbox',{name:'选择 search'}));
  await user.click(screen.getByRole('button',{name:'应用所选变更'}));
  await screen.findByText('所选工具已入库');
  assert.deepEqual(JSON.parse(requests.find(item => item.path.endsWith('/imports')).body),
    {discovery_id:'d1',tools:[{remote_name:'search',name:'local_search'}]});
  await user.click(screen.getByRole('button',{name:'查看工具 保留工具'}));
  assert.deepEqual(opened,[missing.id]);
});

test('删除连接先读取完整影响，确认后发送带版本的删除请求',async () => {
  const owned={id:'tool-1',kind:'mcp',connection_id:connection.id,remote_name:'search',name:'local_search',display_name:'所属搜索'};
  let deleted=false;const writes=[];
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:deleted ? [] : [owned],reserved_names:[],version:'impact-v2'});
    if (path === '/api/mcp/connections') return json({data:deleted ? [] : [connection],version:'v1'});
    if (path === '/api/mcp/connections/server-1' && init.method === 'DELETE') {
      writes.push(JSON.parse(init.body));deleted=true;return new Response(null,{status:204});
    }
    if (path === '/api/mcp/connections/server-1') return json({data:connection,version:'v1'});
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {},initialConnectionId:connection.id}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'删除连接'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'删除连接'}));
  const dialog=await screen.findByRole('dialog',{name:'删除 MCP 连接'});
  assert.match(dialog.textContent,/1 个工具/);assert.match(dialog.textContent,/所属搜索/);
  assert.equal(writes.length,0);
  await user.click(screen.getByRole('button',{name:'取消'}));
  assert.equal(writes.length,0);
  await user.click(screen.getByRole('button',{name:'删除连接'}));
  await user.click(await screen.findByRole('button',{name:'确认删除连接及工具'}));
  await screen.findByText('连接及所属工具已删除');
  assert.deepEqual(writes,[{version:'impact-v2'}]);
  assert.equal(screen.queryByRole('button',{name:'查看工具 所属搜索'}),null);
});

test('连接脏草稿保存失败保留内容，保存并离开成功后才导航',async () => {
  let saves=0,left=0,current=connection;
  const ref=React.createRef();
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections') return json({data:[connection],version:'v1'});
    if (path === '/api/mcp/connections/server-1' && init.method === 'PUT') {
      saves++;
      if (saves === 1) return json({detail:{code:'connection_invalid',message:'fixture rejected'}},422);
      current={...connection,...JSON.parse(init.body).definition};return new Response(null,{status:204});
    }
    if (path === '/api/mcp/connections/server-1') return json({data:current,version:'v1'});
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,ref,onOpenTool:() => {},initialConnectionId:connection.id}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'保存连接'}).disabled,false));
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'修改后的连接'}});
  await React.act(async () => ref.current.requestLeave(() => left++));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  await screen.findAllByText(/保存失败/);
  assert.equal(left,0);assert.equal(screen.getByLabelText(/^连接名称/).value,'修改后的连接');
  await user.click(screen.getByRole('button',{name:'继续编辑'}));
  await React.act(async () => ref.current.requestLeave(() => left++));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  await waitFor(() => assert.equal(left,1));
  assert.equal(saves,2);
  assert.ok(screen.getByText(/请重新发现核对来源结构/));
});

test('删除响应丢失时锁定重复删除，通过重读核实已保存连接',async () => {
  let deletes=0;
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections') return json({data:deletes ? [] : [connection],version:'v1'});
    if (path === '/api/mcp/connections/server-1' && init.method === 'DELETE') {
      deletes++;throw new TypeError('connection lost');
    }
    if (path === '/api/mcp/connections/server-1') return json({data:connection,version:'v1'});
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {},initialConnectionId:connection.id}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'删除连接'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'删除连接'}));
  await user.click(await screen.findByRole('button',{name:'确认删除连接及工具'}));
  await screen.findByText(/删除结果不确定，请重读列表核实/);
  assert.equal(screen.getByRole('button',{name:'删除连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'重新读取连接列表核实删除'}));
  await screen.findByText(/此前删除结果仍不确定/);
  assert.equal(deletes,1);
  assert.ok(screen.getByText('暂无 MCP 连接'));
});

test('远程 MCP 连接使用专属动态表单，保存后重读，修改时禁止测试旧配置',async () => {
  const requests=[];
  const remote={id:'remote-1',display_name:'远程服务',transport:'streamable_http',url:'http://localhost:9000/mcp',
    headers:{Authorization:'Bearer local-test'},test_timeout_seconds:30,discovery_timeout_seconds:30,
    created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'};
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;requests.push({path,...init});
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections' && init.method !== 'POST') return json({data:[connection],version:'v1'});
    if (path === '/api/mcp/connections') return json({data:{id:'remote-1'}},201);
    if (path === '/api/mcp/connections/remote-1') return json({data:remote,version:'v2'});
    if (path.endsWith('/test')) return json({data:{status:'success',duration_ms:4,error:null,connection_id:'remote-1'}});
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'接入 MCP 服务'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'接入 MCP 服务'}));
  await user.click(screen.getByRole('button',{name:'新建 Streamable HTTP 连接'}));
  assert.equal(screen.queryByLabelText(/^启动命令/),null);
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'远程服务'}});
  fireEvent.change(screen.getByLabelText(/^远程 MCP URL/),{target:{value:remote.url}});
  fireEvent.change(screen.getByLabelText('请求头'),{target:{value:JSON.stringify(remote.headers)}});
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  await screen.findByText('连接已保存');
  const created=JSON.parse(requests.find(request => request.path === '/api/mcp/connections' && request.method === 'POST').body);
  assert.equal(created.transport,'streamable_http');assert.deepEqual(created.headers,remote.headers);
  assert.equal(created.command,undefined);
  assert.equal(screen.getByLabelText('请求头').value.includes('Bearer local-test'),true);
  await user.click(screen.getByRole('button',{name:'测试连接'}));
  await screen.findByText(/连接测试成功/);
  fireEvent.change(screen.getByLabelText(/^远程 MCP URL/),{target:{value:remote.url+'-changed'}});
  assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,true);
  assert.equal(screen.getByRole('button',{name:'发现工具'}).disabled,true);
  assert.equal(screen.getByLabelText('请求头').value.includes('Bearer local-test'),true);
});

test('MCP 动态表单保存后分别测试和发现，只导入勾选工具并可跳转到工具页',async () => {
  const requests=[],opened=[];
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;requests.push({path,...init});
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:['add'],version:'v1'});
    if (path === '/api/mcp/connections' && init.method !== 'POST') return json({data:[],version:'v1'});
    if (path === '/api/mcp/connections') return json({data:{id:'server-1'}},201);
    if (path === '/api/mcp/connections/server-1') return json({data:connection,version:'v2'});
    if (path.endsWith('/test')) return json({data:{status:'success',duration_ms:4,error:null,connection_id:'server-1'}});
    if (path.endsWith('/discover')) return json({data:{status:'success',duration_ms:8,error:null,connection_id:'server-1',discovery_id:'discovery-1',version:'v2',tools:[source,{...source,name:'other'}]}});
    if (path.endsWith('/imports')) return json({data:[{id:'tool-1',remote_name:'search',existing:false}]});
    throw new Error('Unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:id => opened.push(id)}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'接入 MCP 服务'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'接入 MCP 服务'}));
  await user.click(screen.getByRole('button',{name:'新建 stdio 连接'}));
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'本地服务'}});
  fireEvent.change(screen.getByLabelText(/^启动命令/),{target:{value:'python'}});
  assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  await screen.findByText('连接已保存');
  await user.click(screen.getByRole('button',{name:'测试连接'}));
  await screen.findByText(/连接测试成功/);
  assert.equal(requests.some(request => request.path.endsWith('/discover')),false);
  await user.click(screen.getByRole('button',{name:'发现工具'}));
  const checkbox=await screen.findByRole('checkbox',{name:'选择 search'});
  assert.equal(requests.some(request => request.path.endsWith('/imports')),false);
  assert.equal(screen.getByRole('button',{name:'导入所选工具'}).disabled,true);
  await user.click(checkbox);
  await user.click(screen.getByRole('button',{name:'导入所选工具'}));
  await waitFor(() => assert.equal(requests.filter(request => request.path.endsWith('/imports')).length,1));
  const body=JSON.parse(requests.find(request => request.path.endsWith('/imports')).body);
  assert.deepEqual(body,{discovery_id:'discovery-1',tools:[{remote_name:'search',name:'search'}]});
  await user.click(await screen.findByRole('button',{name:'打开工具 search'}));
  assert.deepEqual(opened,['tool-1']);
});

test('MCP 保存成功但详情读取失败时只重读，错误 JSON 原文保持且不能测试旧配置',async () => {
  let creates=0,reads=0;
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections' && init.method !== 'POST') return json({data:[],version:'v1'});
    if (path === '/api/mcp/connections') {creates++;return json({data:{id:'server-1'}},201);}
    if (path === '/api/mcp/connections/server-1') {
      if (++reads === 1) return json({detail:{code:'config_read',message:'temporary'}},503);
      return json({data:connection,version:'v2'});
    }
    throw new Error('unexpected request');
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'接入 MCP 服务'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'接入 MCP 服务'}));
  await user.click(screen.getByRole('button',{name:'新建 stdio 连接'}));
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'本地服务'}});
  fireEvent.change(screen.getByLabelText(/^启动命令/),{target:{value:'python'}});
  fireEvent.change(screen.getByLabelText('启动参数'),{target:{value:'[original broken'}});
  fireEvent.change(screen.getByLabelText(/^启动命令/),{target:{value:'python3'}});
  assert.equal(screen.getByLabelText('启动参数').value,'[original broken');
  assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  assert.equal(creates,0);
  fireEvent.change(screen.getByLabelText('启动参数'),{target:{value:'[]'}});
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  await screen.findByText(/连接已保存，详情读取失败/);
  assert.equal(screen.getByRole('button',{name:'保存连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'重新读取连接详情'}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,false));
  assert.equal(creates,1);
  assert.equal(reads,2);
});

test('MCP 未知 503 保存结果保持不确定，锁定重复提交并允许明确放弃后重读',async () => {
  let creates=0;
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
    if (path === '/api/mcp/schema/streamable_http') return json({data:httpSchema});
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections' && init.method !== 'POST') return json({data:creates ? [connection] : [],version:'v2'});
    if (path === '/api/mcp/connections') {creates++;return json({detail:'proxy unavailable'},503);}
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'接入 MCP 服务'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'接入 MCP 服务'}));
  await user.click(screen.getByRole('button',{name:'新建 stdio 连接'}));
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'本地服务'}});
  fireEvent.change(screen.getByLabelText(/^启动命令/),{target:{value:'python'}});
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  await screen.findByText(/保存结果不确定，请勿重复保存/);
  assert.equal(screen.getByRole('button',{name:'保存连接'}).disabled,true);
  assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读连接列表'}));
  await screen.findByText(/此前保存结果仍不确定/);
  assert.equal(screen.getByRole('button',{name:'接入 MCP 服务'}).disabled,false);
  assert.equal(creates,1);
});
