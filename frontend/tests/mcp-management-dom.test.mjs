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

test('MCP 动态表单保存后分别测试和发现，只导入勾选工具并可跳转到工具页',async () => {
  const requests=[],opened=[];
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;requests.push({path,...init});
    if (path === '/api/mcp/schema/stdio') return json({data:schema});
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
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'新建 stdio 连接'}).disabled,false));
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
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'新建 stdio 连接'}).disabled,false));
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
    if (path === '/api/tools') return json({data:[],reserved_names:[],version:'v1'});
    if (path === '/api/mcp/connections' && init.method !== 'POST') return json({data:creates ? [connection] : [],version:'v2'});
    if (path === '/api/mcp/connections') {creates++;return json({detail:'proxy unavailable'},503);}
    throw new Error('unexpected '+path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(McpWorkspace,{session,onOpenTool:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'新建 stdio 连接'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'新建 stdio 连接'}));
  fireEvent.change(screen.getByLabelText(/^连接名称/),{target:{value:'本地服务'}});
  fireEvent.change(screen.getByLabelText(/^启动命令/),{target:{value:'python'}});
  await user.click(screen.getByRole('button',{name:'保存连接'}));
  await screen.findByText(/保存结果不确定，请勿重复保存/);
  assert.equal(screen.getByRole('button',{name:'保存连接'}).disabled,true);
  assert.equal(screen.getByRole('button',{name:'测试连接'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读连接列表'}));
  await screen.findByText(/此前保存结果仍不确定/);
  assert.equal(screen.getByRole('button',{name:'新建 stdio 连接'}).disabled,false);
  assert.equal(creates,1);
});
