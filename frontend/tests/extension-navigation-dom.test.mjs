import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';
const browser = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window','document','navigator','Window','HTMLElement','Element','Node','Text','MutationObserver','Event','KeyboardEvent','MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true, value:name === 'window' ? browser.window : browser.window[name]});
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = browser.window.getComputedStyle.bind(browser.window);
browser.window.HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open','');};
browser.window.HTMLDialogElement.prototype.close = function () {this.removeAttribute('open');};
const React = await import('react');
const {render, cleanup, screen, fireEvent, within, waitFor} = await import('@testing-library/react');
const {Navigation} = await import('../src/components/Sidebar.tsx');
const {ExtensionsWorkspace} = await import('../src/components/tools/ExtensionsWorkspace.tsx');
const {ExtensionLibrarySidebar} = await import('../src/components/tools/ExtensionLibrarySidebar.tsx');
afterEach(cleanup);
const navProps = {backendReady:true, observationLabel:'观察已建立', isCollapsed:false,onToggle:()=>{}, onCommands:()=>{}};

test('对话和扩展共用主导航，扩展紧随对话，旧子入口和特殊导航移除', () => {
  const destinations = [];
  const props = {...navProps,onNavigate:page=>destinations.push(page)};
  const view = render(React.createElement(Navigation, props));
  assert.ok(screen.queryByText('会话与对话') === null);
  const navigation = screen.getByRole('navigation', {name:'核心工作台'});
  assert.deepEqual(within(navigation).getAllByRole('button').slice(0,2).map(button=>button.textContent), ['对话','扩展']);
  fireEvent.click(screen.getByRole('button', {name:'扩展'}));
  assert.deepEqual(destinations, ['extensions']);
  view.rerender(React.createElement(Navigation, {...props,page:'extensions'}));
  assert.equal(screen.getByRole('button', {name:'扩展'}).getAttribute('aria-current'), 'page');
  assert.ok(screen.queryByRole('button', {name:'工具'}) === null);
  assert.ok(screen.queryByRole('button', {name:'MCP 服务'}) === null);
  assert.equal(screen.getByRole('complementary', {name:'主导航'}).className, 'navigation');
  assert.ok(screen.getByText('Local Developer'));
  fireEvent.click(screen.getByRole('button', {name:'对话'}));
  assert.deepEqual(destinations, ['extensions','chat']);
});
test('折叠时保留相同导航和展开按钮，扩展直接进入页面', () => {
  let toggles=0;
  const destinations=[];
  render(React.createElement(Navigation,{...navProps,isCollapsed:true,page:'extensions',onToggle:()=>toggles++,onNavigate:page=>destinations.push(page)}));
  fireEvent.click(screen.getByRole('button',{name:'展开主导航'}));
  fireEvent.click(screen.getByRole('button',{name:'扩展'}));
  assert.equal(toggles,1);
  assert.deepEqual(destinations,['extensions']);
  assert.ok(screen.getByText('Local Developer'));
});
function tab(label) {return within(screen.getByRole('tablist',{name:'扩展分类'})).getByRole('tab',{name:name => name.startsWith((label === 'Skill' ? 'SKILL' : label) + ' (')});}
function workspace(props={}) {return render(React.createElement(ExtensionsWorkspace,{session:null,onView:()=>{},...props}));}
test('扩展库仅有一套新增、搜索、分类、开关和页脚，断连不可写', () => {
  workspace();
  assert.equal(screen.getAllByRole('complementary').length,1);
  assert.equal(screen.getAllByRole('searchbox').length,1);
  assert.equal(screen.getAllByRole('list').length,1);
  assert.equal(screen.getAllByRole('tablist').length,1);
  assert.deepEqual(within(screen.getByRole('tablist',{name:'扩展分类'})).getAllByRole('tab').map(button=>button.textContent),['全部 (0)','工具 (0)','MCP (0)','SKILL (0)']);
  assert.equal(screen.getByRole('button',{name:'新增扩展'}).disabled,true);
  assert.ok(screen.getByRole('switch',{name:'隐藏禁用工具'}));
  assert.ok(screen.getByText('0 / 0 项已启用'));
  assert.ok(screen.queryByText(/个连接/) === null);
  assert.ok(screen.queryByRole('complementary',{name:'工具库'}) === null);
  assert.ok(screen.queryByRole('complementary',{name:'MCP 连接列表'}) === null);
  fireEvent.click(tab('MCP'));
  assert.ok(screen.getByRole('region',{name:'MCP 服务详情'}));
  fireEvent.click(tab('工具'));
  assert.ok(screen.getByRole('region',{name:'工具详情'}));
  fireEvent.click(tab('Skill'));
  assert.ok(screen.getByRole('region',{name:'Skill'}));
  assert.ok(screen.getByText('技能管理暂未开放。'));
  assert.ok(screen.getByRole('searchbox',{name:'搜索扩展'}));
});
test('分类标签方向键和 Home/End 移动焦点，按钮激活分类', () => {
  workspace();tab('全部').focus();
  fireEvent.keyDown(tab('全部'),{key:'ArrowRight'});
  assert.ok(document.activeElement === tab('工具'));
  assert.equal(tab('全部').getAttribute('aria-selected'),'true');
  fireEvent.keyDown(tab('工具'),{key:'End'});
  assert.ok(document.activeElement === tab('Skill'));
  fireEvent.keyDown(tab('Skill'),{key:'Home'});
  assert.ok(document.activeElement === tab('全部'));
});
async function waitForCreation(label) {
  await waitFor(()=>assert.equal(screen.getByRole('button',{name:'新增扩展'}).disabled,false));
  fireEvent.click(screen.getByRole('button',{name:'新增扩展'}));
  await waitFor(()=>assert.equal(screen.getByRole('button',{name:label}).disabled,false));
  fireEvent.click(screen.getByRole('button',{name:'新增扩展'}));
}
const connection={id:'connection-1',display_name:'本地搜索',transport:'stdio',command:'python',args:[],env:{},cwd:null,test_timeout_seconds:30,discovery_timeout_seconds:30};
const schema={type:'object',required:['display_name','command'],properties:{display_name:{type:'string',title:'连接名称'},command:{type:'string',title:'启动命令'},transport:{type:'string'}}};
function sessionFixture() {
  return {
    getToolManagementSchema:async()=>({data:{type:'object',properties:{display_name:{type:'string',title:'工具名称'},name:{type:'string',title:'调用名称'},url:{type:'string',title:'URL'}}}}),
    listTools:async()=>({data:[],version:'v1',reserved_names:[]}),getMcpConnectionSchema:async()=>({data:schema}),
    listMcpConnections:async()=>({data:[connection],version:'v1'}),getMcpConnection:async()=>({data:connection,version:'v1'}),validateToolName:async()=>({data:{valid:true}}),
  };
}
test('全部内打开连接，草稿保护覆盖分类和外部导航，放弃后不再出现', async () => {
  const ref=React.createRef();workspace({session:sessionFixture(),ref});
  const entry=await screen.findByRole('button',{name:/本地搜索/});
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(entry);
  const command=await screen.findByLabelText(/启动命令/);
  assert.equal(tab('全部').getAttribute('aria-selected'),'true');
  fireEvent.change(command,{target:{value:'changed-python'}});
  fireEvent.click(tab('工具'));
  assert.ok(screen.getByRole('dialog',{name:'未保存的连接修改'}));
  assert.equal(tab('全部').getAttribute('aria-selected'),'true');
  fireEvent.click(screen.getByRole('button',{name:'继续编辑'}));
  assert.equal(screen.getByLabelText(/启动命令/).value,'changed-python');
  let departures=0;React.act(()=>ref.current.requestLeave(()=>departures++));assert.equal(departures,0);
  fireEvent.click(screen.getByRole('button',{name:'继续编辑'}));
  fireEvent.click(tab('工具'));fireEvent.click(screen.getByRole('button',{name:'放弃修改并离开'}));
  assert.equal(tab('工具').getAttribute('aria-selected'),'true');
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(tab('MCP'));
  const restoredEntry=await screen.findByRole('button',{name:/本地搜索/});
  await waitFor(()=>assert.equal(restoredEntry.disabled,false));
  fireEvent.click(restoredEntry);
  assert.equal((await screen.findByLabelText(/启动命令/)).value,'python');
});
test('从 MCP 详情经工具接入菜单跳转 MCP 不被工具激活覆盖', async () => {
  workspace({session:sessionFixture()});
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(await screen.findByRole('button',{name:/本地搜索/}));await screen.findByLabelText(/启动命令/);
  await waitForCreation('本地 stdio 服务');
  fireEvent.click(screen.getByRole('button',{name:'新增扩展'}));
  fireEvent.click(screen.getByRole('button',{name:'本地 stdio 服务'}));
  assert.ok(screen.getByRole('region',{name:'MCP 服务详情'}));
  assert.ok(screen.queryByRole('region',{name:'工具详情'}) === null);
  await waitForCreation('新建 HTTP 工具');
  await waitForCreation('本地 stdio 服务');
});

test('从 MCP 切回工具重新读取工具库，发现入库后的新工具立即可见', async () => {
  const session=sessionFixture();
  let library=[];
  session.listTools=async()=>({data:library,version:'v2',reserved_names:[]});
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(tab('MCP'));
  await waitForCreation('本地 stdio 服务');
  library=[{id:'imported-1',kind:'mcp',name:'remote_search',display_name:'新入库工具',description:'搜索',enabled:true,connection_id:'connection-1',remote_name:'search'}];
  fireEvent.click(tab('工具'));
  assert.ok(await screen.findByRole('button',{name:/remote_search/}));
});

test('共用搜索、隐藏禁用开关与分类数量覆盖工具和 MCP，页脚固定统计工具启用状态', () => {
  const tools=[
    {id:'http-1',kind:'http',name:'lookup',display_name:'查询',description:'查询订单',enabled:true,url:'http://orders',method:'GET'},
    {id:'python-1',kind:'python',name:'calculate',display_name:'计算',description:'计算金额',enabled:false,code_path:'calculate.py'},
  ];
  const props={category:'all',onCategory:()=>{},activeEditor:'tools',connected:true,
    toolLibrary:{tools,recent:{},busy:false,verified:true,canCreate:true,canReload:true,error:null},
    mcpLibrary:{connections:[connection],busy:false,locked:false,canCreate:true,canReload:true,error:null},
    onCreateTool:()=>{},onImportOpenApi:()=>{},onCreateMcp:()=>{},onOpenTool:()=>{},onOpenMcp:()=>{},onReload:()=>{}};
  const view=render(React.createElement(ExtensionLibrarySidebar,props));
  assert.equal(tab('全部').textContent,'全部 (3)');
  assert.equal(tab('工具').textContent,'工具 (2)');
  assert.equal(tab('MCP').textContent,'MCP (1)');
  assert.equal(screen.getAllByRole('searchbox').length,1);
  assert.equal(screen.getAllByRole('list').length,1);
  assert.equal(screen.getAllByRole('switch').length,1);
  assert.ok(screen.getByText('1 / 2 项已启用'));
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:'本地搜索'}});
  assert.ok(screen.getByRole('button',{name:/本地搜索/}));
  assert.ok(screen.queryByRole('button',{name:/lookup/}) === null);
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:'查询订单'}});
  assert.ok(screen.getByRole('button',{name:/lookup/}));
  assert.ok(screen.queryByRole('button',{name:/本地搜索/}) === null);
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:''}});
  fireEvent.click(screen.getByRole('switch'));
  assert.ok(screen.queryByRole('button',{name:/calculate/}) === null);
  assert.ok(screen.getByRole('button',{name:/本地搜索/}));
  assert.equal(tab('全部').textContent,'全部 (2)');
  assert.equal(tab('工具').textContent,'工具 (1)');
  assert.ok(screen.getByText('1 / 2 项已启用'));
  view.rerender(React.createElement(ExtensionLibrarySidebar,{...props,category:'mcp'}));
  assert.ok(screen.queryByRole('button',{name:/lookup/}) === null);
  assert.ok(screen.getByRole('button',{name:/本地搜索/}));
  assert.ok(screen.queryByText(/个连接/) === null);
});

test('新增扩展菜单保留 HTTP、Python、OpenAPI、本地与远程 MCP 入口，刷新共用一个按钮', () => {
  const actions=[];
  const props={category:'all',onCategory:()=>{},activeEditor:'tools',connected:true,
    toolLibrary:{tools:[],recent:{},busy:false,verified:true,canCreate:true,canReload:true,error:null},
    mcpLibrary:{connections:[],busy:false,locked:false,canCreate:true,canReload:true,error:null},
    onCreateTool:kind=>actions.push(kind),onImportOpenApi:()=>actions.push('openapi'),onCreateMcp:transport=>actions.push(transport),
    onOpenTool:()=>{},onOpenMcp:()=>{},onReload:()=>actions.push('reload')};
  render(React.createElement(ExtensionLibrarySidebar,props));
  for (const label of ['新建 HTTP 工具','新建 Python 工具','导入 OpenAPI 文档','本地 stdio 服务','远程 Streamable HTTP 服务']) {
    fireEvent.click(screen.getByRole('button',{name:'新增扩展'}));
    assert.equal(screen.getByRole('button',{name:'SKILL · 暂未开放'}).disabled,true);
    fireEvent.click(screen.getByRole('button',{name:label}));
    assert.equal(screen.getByRole('button',{name:'新增扩展'}).getAttribute('aria-expanded'),'false');
  }
  fireEvent.click(screen.getByRole('button',{name:'刷新扩展列表'}));
  assert.deepEqual(actions,['http','python','openapi','stdio','streamable_http','reload']);
});

test('读取失败显示明确错误并允许刷新，不把未知数量显示成空库', () => {
  let reloads=0;
  render(React.createElement(ExtensionLibrarySidebar,{category:'all',onCategory:()=>{},activeEditor:'tools',connected:true,
    toolLibrary:{tools:null,recent:{},busy:false,verified:false,canCreate:false,canReload:true,error:'工具读取失败'},
    mcpLibrary:{connections:null,busy:false,locked:false,canCreate:false,canReload:true,error:'MCP 读取失败'},
    onCreateTool:()=>{},onImportOpenApi:()=>{},onCreateMcp:()=>{},onOpenTool:()=>{},onOpenMcp:()=>{},onReload:()=>reloads++}));
  assert.equal(screen.getAllByRole('alert').length,2);
  assert.ok(screen.getByText('启用数量待确认'));
  assert.ok(screen.queryByText('扩展库为空。点击新增扩展开始接入。') === null);
  assert.equal(tab('全部').textContent,'全部 (…)');
  fireEvent.click(screen.getByRole('button',{name:'刷新扩展列表'}));
  assert.equal(reloads,1);
});

for (const [creationLabel,categoryLabel,detailLabel] of [
  ['新建 HTTP 工具','工具','工具详情'], ['本地 stdio 服务','MCP','MCP 服务详情'],
]) {
  test(`从 SKILL 新增 ${creationLabel} 会切换对应分类并显示编辑器`,async () => {
    workspace({session:sessionFixture()});
    await waitForCreation('新建 HTTP 工具');
    fireEvent.click(tab('Skill'));
    assert.equal(tab('Skill').getAttribute('aria-selected'),'true');
    await waitForCreation(creationLabel);
    fireEvent.click(screen.getByRole('button',{name:'新增扩展'}));
    fireEvent.click(screen.getByRole('button',{name:creationLabel}));
    assert.equal(tab(categoryLabel).getAttribute('aria-selected'),'true');
    assert.ok(screen.getByRole('region',{name:detailLabel}));
    assert.ok(screen.queryByRole('region',{name:'Skill'}) === null);
    await waitForCreation(creationLabel);
  });
}

test('切换扩展分类时保留已加载数量和列表，不重新显示加载占位',async () => {
  const session=sessionFixture();
  const readTools=session.listTools;
  const readConnections=session.listMcpConnections;
  let shouldDelayReads=false;
  const pendingLibraryReads=new Promise(()=>{});
  session.listTools=()=>shouldDelayReads ? pendingLibraryReads : readTools();
  session.listMcpConnections=()=>shouldDelayReads ? pendingLibraryReads : readConnections();
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  await waitForCreation('本地 stdio 服务');
  const countsBefore=screen.getByRole('tablist',{name:'扩展分类'}).textContent;
  const enabledCountBefore=screen.getByTitle('已注册工具的启用数量').textContent;
  shouldDelayReads=true;
  fireEvent.click(tab('MCP'));
  assert.equal(tab('MCP').getAttribute('aria-selected'),'true');
  assert.equal(screen.getByRole('tablist',{name:'扩展分类'}).textContent,countsBefore,
    '分类切换不能将已加载数字替换为省略号，引起标签宽度跳变');
  assert.equal(screen.getByTitle('已注册工具的启用数量').textContent,enabledCountBefore);
  assert.ok(screen.getByRole('button',{name:/本地搜索/}));
  assert.ok(screen.queryByText('正在读取扩展库…') === null);
  assert.ok(screen.queryByText('读取中…') === null, '后台刷新不应在详情中插入再移除加载提示');
});

test('在 MCP、工具和 SKILL 间切换不重复加载 schema，也不清空分类数量',async () => {
  const session=sessionFixture();
  const readToolSchema=session.getToolManagementSchema;
  const readConnectionSchema=session.getMcpConnectionSchema;
  let toolSchemaReads=0,connectionSchemaReads=0;
  session.getToolManagementSchema=()=>{toolSchemaReads++;return readToolSchema();};
  session.getMcpConnectionSchema=()=>{connectionSchemaReads++;return readConnectionSchema();};
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  await waitForCreation('本地 stdio 服务');
  const countsBefore=screen.getByRole('tablist',{name:'扩展分类'}).textContent;
  for (const label of ['MCP','工具','Skill','全部']) {
    fireEvent.click(tab(label));
    assert.equal(screen.getByRole('tablist',{name:'扩展分类'}).textContent,countsBefore);
    await waitForCreation('新建 HTTP 工具');
    await waitForCreation('本地 stdio 服务');
  }
  assert.equal(toolSchemaReads,1);
  assert.equal(connectionSchemaReads,2);
});

test('切回工具时静默更新列表，不插入加载提示',async () => {
  const session=sessionFixture();
  const readTools=session.listTools;
  let shouldDelayReads=false;
  const pendingLibraryReads=new Promise(()=>{});
  session.listTools=()=>shouldDelayReads ? pendingLibraryReads : readTools();
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(tab('MCP'));
  await waitForCreation('本地 stdio 服务');
  const countsBefore=screen.getByRole('tablist',{name:'扩展分类'}).textContent;
  shouldDelayReads=true;
  fireEvent.click(tab('工具'));
  assert.equal(tab('工具').getAttribute('aria-selected'),'true');
  assert.equal(screen.getByRole('tablist',{name:'扩展分类'}).textContent,countsBefore);
  assert.ok(screen.queryByText('正在读取工具库…') === null);
  assert.ok(screen.queryByText('正在读取扩展库…') === null);
});

test('首次 MCP schema 尚未读取完成时切换分类，不中断初始读取',async () => {
  const session=sessionFixture();
  const readConnectionSchema=session.getMcpConnectionSchema;
  let completeSchemaRead;
  const pendingSchemaRead=new Promise(resolve=>{completeSchemaRead=resolve;});
  session.getMcpConnectionSchema=async()=>{await pendingSchemaRead;return readConnectionSchema();};
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  fireEvent.click(tab('MCP'));
  assert.equal(tab('MCP').getAttribute('aria-selected'),'true');
  await React.act(async()=>{completeSchemaRead();});
  await waitForCreation('本地 stdio 服务');
  assert.equal(tab('MCP').textContent,'MCP (1)');
  assert.ok(screen.getByRole('button',{name:/本地搜索/}));
});

test('手动刷新保留分类数量并继续显示明确读取反馈',async () => {
  const session=sessionFixture();
  const readTools=session.listTools;
  const readConnections=session.listMcpConnections;
  let shouldDelayReads=false;
  const pendingLibraryReads=new Promise(()=>{});
  session.listTools=()=>shouldDelayReads ? pendingLibraryReads : readTools();
  session.listMcpConnections=()=>shouldDelayReads ? pendingLibraryReads : readConnections();
  workspace({session});
  await waitForCreation('新建 HTTP 工具');
  await waitForCreation('本地 stdio 服务');
  const countsBefore=screen.getByRole('tablist',{name:'扩展分类'}).textContent;
  shouldDelayReads=true;
  fireEvent.click(screen.getByRole('button',{name:'刷新扩展列表'}));
  assert.equal(screen.getByRole('tablist',{name:'扩展分类'}).textContent,countsBefore);
  assert.ok(screen.getByText('正在读取工具库…'));
});
