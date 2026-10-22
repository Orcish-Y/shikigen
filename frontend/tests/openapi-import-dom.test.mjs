import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'});
for (const name of ['window','document','navigator','Window','HTMLElement','Element','Node','Text','MutationObserver','Event','KeyboardEvent','MouseEvent','File','FileReader'])
  Object.defineProperty(globalThis,name,{configurable:true,value:name === 'window' ? browser.window : browser.window[name]});
globalThis.getComputedStyle=browser.window.getComputedStyle.bind(browser.window);
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
browser.window.HTMLDialogElement.prototype.showModal=function () {this.setAttribute('open','');};
browser.window.HTMLDialogElement.prototype.close=function () {this.removeAttribute('open');};
const React=await import('react');
const {render,cleanup,screen,waitFor,fireEvent}=await import('@testing-library/react');
const {default:userEvent}=await import('@testing-library/user-event');
const {ToolsWorkspace}=await import('../src/components/tools/ToolsWorkspace.tsx');
const {BackendSession}=await import('../src/backend-client.ts');
afterEach(cleanup);
const schema={type:'object',required:['display_name','name','url'],properties:{
  kind:{type:'string'},method:{type:'string',title:'请求方法'},url:{type:'string',title:'请求地址'},
  display_name:{type:'string',minLength:1,title:'页面名称'},name:{type:'string',title:'调用名称'},description:{type:'string',title:'说明'},
  input_schema:{type:'object',title:'输入结构'},output_schema:{type:['object','null'],title:'输出结构'},
}};
const definition={kind:'http',method:'GET',url:'/items',display_name:'商品',name:'',description:'商品查询',headers:{},parameters:[],auth:[],
  enabled:true,timeout_seconds:30,input_schema:{type:'object',properties:{},additionalProperties:false},output_schema:null};
const operation={key:'GET /items',method:'GET',path:'/items',name_hint:'list-items',definition,servers:[{url:'/relative'},{url:'https://api.test/v1'}],
  errors:[],warnings:['输出结构未声明'],configuration_errors:['请补充地址']};
const json=(data,status=200) => new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});

test('粘贴文档、补齐所选接口，保存失败保留草稿，保存后读取失败不重复导入',async () => {
  const writes=[];let failSave=true,failRead=false,tools=[];
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path.endsWith('/schema/http')) return json({data:schema});
    if (path.endsWith('/validate-name')) return json({data:{valid:true}});
    if (path === '/api/tools') {
      if (failRead) throw new Error('read lost');
      return json({data:tools,version:'v1',reserved_names:['list_items']});
    }
    if (path.endsWith('/openapi/preview')) return json({data:{openapi:'3.1.0',title:'Store',operations:[operation,{...operation,key:'GET /other',path:'/other',name_hint:'other'}]}});
    if (path.endsWith('/openapi/imports')) {
      const payload=JSON.parse(init.body);writes.push(payload);
      if (failSave) return json({detail:{code:'definition_invalid',message:'fixture rejection'}},422);
      tools=[{...payload.tools[0].definition,id:'import-1',created_at:'2026-10-20T00:00:00Z',updated_at:'2026-10-20T00:00:00Z'}];
      failRead=true;return json({data:[{id:'import-1'}]},201);
    }
    if (path === '/api/tools/import-1') return json({data:tools[0],version:'v1'});
    throw new Error(path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'选择接入类型'}).disabled,false));
  await user.click(await screen.findByRole('button',{name:'选择接入类型'}));
  await user.click(screen.getByRole('button',{name:'导入 OpenAPI 文档'}));
  fireEvent.change(screen.getByLabelText('OpenAPI 文档'),{target:{value:'openapi: 3.1.0\npaths: {}'}});
  await user.click(screen.getByRole('button',{name:'解析文档'}));
  await user.click(await screen.findByRole('checkbox',{name:'选择 GET /items'}));
  assert.equal(screen.getByLabelText(/^调用名称/).value,'list_items_2');
  await user.selectOptions(screen.getByLabelText('服务器候选'),'1');
  assert.equal(screen.getByLabelText(/^请求地址/).value,'https://api.test/v1/items');
  await user.click(screen.getByRole('button',{name:'保存所选工具'}));
  await screen.findByText(/保存失败.*fixture rejection/);
  assert.equal(screen.getByLabelText(/^请求地址/).value,'https://api.test/v1/items');
  failSave=false;
  await user.click(screen.getByRole('button',{name:'保存所选工具'}));
  await screen.findByText(/工具已保存，.*读取失败/);
  assert.equal(screen.getByRole('button',{name:'保存所选工具'}).disabled,true);
  assert.equal(writes.length,2);
  assert.equal(writes[1].tools.length,1);
  assert.equal(writes[1].tools[0].operation_key,'GET /items');
  failRead=false;
  await user.click(screen.getByRole('button',{name:'重新读取已保存工具'}));
  await user.click(await screen.findByRole('button',{name:'编辑工具 商品'}));
  await screen.findByRole('button',{name:'保存工具'});
  assert.equal(writes.length,2);
});

test('上传 YAML、阻止未支持接口，离开时保留草稿；保存响应丢失后禁止重复导入',async () => {
  let previews=0,saves=0,left=0;
  const ref=React.createRef();
  const documentText='openapi: 3.0.3\ninfo: {title: Uploaded, version: "1"}\npaths: {}';
  const valid={...operation,definition:{...definition,url:'https://api.test/items'},configuration_errors:[]};
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path.endsWith('/schema/http')) return json({data:schema});
    if (path.endsWith('/validate-name')) return json({data:{valid:true}});
    if (path === '/api/tools') return json({data:[],version:'v1',reserved_names:[]});
    if (path.endsWith('/openapi/preview')) {
      previews++;assert.equal(JSON.parse(init.body).document,documentText);
      return json({data:{openapi:'3.0.3',title:'Uploaded',operations:[valid,{...valid,key:'GET /blocked',path:'/blocked',errors:['引用尚未支持']}]}});
    }
    if (path.endsWith('/openapi/imports')) {saves++;throw new TypeError('lost response');}
    throw new Error(path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(ToolsWorkspace,{session,ref,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'选择接入类型'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'选择接入类型'}));
  await user.click(screen.getByRole('button',{name:'导入 OpenAPI 文档'}));
  await user.upload(screen.getByLabelText('上传 OpenAPI 文档'),new File([documentText],'api.yaml',{type:'application/yaml'}));
  await waitFor(() => assert.equal(screen.getByLabelText('OpenAPI 文档').value,documentText));
  assert.equal(previews,0);
  await user.click(screen.getByRole('button',{name:'解析文档'}));
  assert.equal((await screen.findByRole('checkbox',{name:'选择 GET /blocked'})).disabled,true);
  await user.click(screen.getByRole('checkbox',{name:'选择 GET /items'}));
  await React.act(async () => ref.current.requestLeave(() => left++));
  await screen.findByRole('dialog',{name:'未保存的导入草稿'});
  await user.click(screen.getByRole('button',{name:'继续编辑'}));
  assert.equal(left,0);
  assert.equal(screen.getByLabelText('OpenAPI 文档').value,documentText);
  await user.click(screen.getByRole('button',{name:'保存所选工具'}));
  await screen.findByText(/保存结果不确定/);
  assert.equal(screen.getByRole('button',{name:'保存所选工具'}).disabled,true);
  assert.equal(saves,1);
  await React.act(async () => ref.current.requestLeave(() => left++));
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读工具库'}));
  await waitFor(() => assert.equal(left,1));
  assert.equal(saves,1);
});

test('预览配置在接口切换时保留，保存并离开等待成功读取',async () => {
  let left=0,written=[];
  const ref=React.createRef();
  const session=new BackendSession('test','http://backend',new AbortController().signal,async (url,init) => {
    const path=new URL(url).pathname;
    if (path.endsWith('/schema/http')) return json({data:schema});
    if (path.endsWith('/validate-name')) return json({data:{valid:true}});
    if (path === '/api/tools') return json({data:[],version:'v1',reserved_names:[]});
    if (path.endsWith('/openapi/preview')) return json({data:{openapi:'3.1.0',title:'Store',operations:[operation,{...operation,key:'GET /other',path:'/other',name_hint:'other'}]}});
    if (path.endsWith('/openapi/imports')) {written=JSON.parse(init.body).tools;return json({data:[{id:'saved'}]},201);}
    if (path === '/api/tools/saved') return json({data:{...written[0].definition,id:'saved'},version:'v1'});
    throw new Error(path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(ToolsWorkspace,{session,ref,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'选择接入类型'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'选择接入类型'}));
  await user.click(screen.getByRole('button',{name:'导入 OpenAPI 文档'}));
  fireEvent.change(screen.getByLabelText('OpenAPI 文档'),{target:{value:'doc'}});
  await user.click(screen.getByRole('button',{name:'解析文档'}));
  await user.click(await screen.findByRole('checkbox',{name:'选择 GET /items'}));
  fireEvent.change(screen.getByLabelText(/^请求地址/),{target:{value:'https://edited.test/items'}});
  fireEvent.change(screen.getByLabelText(/^调用名称/),{target:{value:'custom_name'}});
  await user.click(screen.getByRole('button',{name:'预览 GET /other'}));
  await user.click(screen.getByRole('button',{name:'预览 GET /items'}));
  assert.equal(screen.getByLabelText(/^请求地址/).value,'https://edited.test/items');
  assert.equal(screen.getByLabelText(/^调用名称/).value,'custom_name');
  await React.act(async () => ref.current.requestLeave(() => left++));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  await waitFor(() => assert.equal(left,1));
  assert.equal(written.length,1);assert.equal(written[0].definition.name,'custom_name');
});

test('服务器变量与业务路径参数同名时仍要求补齐服务器',async () => {
  const candidate={...operation,key:'GET /items/{id}',path:'/items/{id}',servers:[{url:'https://api.test/{id}'}],
    definition:{...definition,url:'https://api.test/{id}/items/{id}',parameters:[{location:'path',input_name:'id',name:'id'}],
      input_schema:{type:'object',properties:{path:{type:'object',properties:{id:{type:'string'}},required:['id']}},required:['path']}}};
  const session=new BackendSession('test','http://backend',new AbortController().signal,async url => {
    const path=new URL(url).pathname;
    if (path.endsWith('/schema/http')) return json({data:schema});
    if (path.endsWith('/validate-name')) return json({data:{valid:true}});
    if (path === '/api/tools') return json({data:[],version:'v1',reserved_names:[]});
    if (path.endsWith('/openapi/preview')) return json({data:{openapi:'3.1.0',title:'Variables',operations:[candidate]}});
    throw new Error(path);
  });
  const user=userEvent.setup({document:browser.window.document,delay:null});
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'选择接入类型'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'选择接入类型'}));
  await user.click(screen.getByRole('button',{name:'导入 OpenAPI 文档'}));
  fireEvent.change(screen.getByLabelText('OpenAPI 文档'),{target:{value:'doc'}});
  await user.click(screen.getByRole('button',{name:'解析文档'}));
  await user.click(await screen.findByRole('checkbox',{name:'选择 GET /items/{id}'}));
  assert.equal(screen.getByRole('button',{name:'保存所选工具'}).disabled,true);
  fireEvent.change(screen.getByLabelText(/^请求地址/),{target:{value:'https://api.test/resolved/items/{id}'}});
  assert.equal(screen.getByRole('button',{name:'保存所选工具'}).disabled,false);
});
