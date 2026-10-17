import assert from 'node:assert/strict';
import test, {afterEach} from 'node:test';
import {JSDOM} from 'jsdom';

const browser = new JSDOM('<!doctype html><html><body></body></html>', {url:'http://localhost/'});
for (const name of ['window','document','navigator','Window','HTMLElement','Element','Node','Text','MutationObserver','Event','KeyboardEvent','MouseEvent']) {
  Object.defineProperty(globalThis, name, {configurable:true, value:name === 'window' ? browser.window : browser.window[name]});
}
globalThis.getComputedStyle = browser.window.getComputedStyle.bind(browser.window);
globalThis.ResizeObserver = class {observe() {} disconnect() {} unobserve() {}};
browser.window.requestAnimationFrame = callback => setTimeout(callback, 0);
browser.window.cancelAnimationFrame = clearTimeout;
globalThis.requestAnimationFrame = browser.window.requestAnimationFrame;
globalThis.cancelAnimationFrame = clearTimeout;
browser.window.Range.prototype.getClientRects = () => [];
browser.window.Range.prototype.getBoundingClientRect = () => new browser.window.DOMRect();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
browser.window.HTMLDialogElement.prototype.showModal = function () {this.setAttribute('open','');};
browser.window.HTMLDialogElement.prototype.close = function () {this.removeAttribute('open');};
const React = await import('react');
const {render, cleanup, screen, waitFor, within, act, fireEvent} = await import('@testing-library/react');
const {default:userEvent} = await import('@testing-library/user-event');
const {ToolDefinitionForm} = await import('../src/components/tools/ToolDefinitionForm.tsx');
const {ToolInputForm} = await import('../src/components/tools/ToolInputForm.tsx');
const {ToolTestResult} = await import('../src/components/tools/ToolTestResult.tsx');
const {ToolsWorkspace} = await import('../src/components/tools/ToolsWorkspace.tsx');
const {BackendSession} = await import('../src/backend-client.ts');
const {EditorView} = await import('@codemirror/view');
const {EditorState} = await import('@codemirror/state');
const {forEachDiagnostic} = await import('@codemirror/lint');
const {undo,redo,indentMore} = await import('@codemirror/commands');
const {PythonSourceEditor} = await import('../src/components/tools/PythonSourceEditor.tsx');

function replacePythonSource(source) {
  const view=EditorView.findFromDOM(screen.getByRole('textbox',{name:'Python 源码'}));
  assert.ok(view);
  act(() => view.dispatch({changes:{from:0,to:view.state.doc.length,insert:source}}));
  return view;
}
afterEach(cleanup);

test('Python 本地预览不改写草稿，源码错误立即清除旧结构，默认值不注入实际输入', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const inputSchema={type:'object',properties:{quantity:{type:'integer'},price:{type:'number',default:2.5}},required:['quantity'],additionalProperties:false};
  const pythonSchema={type:'object',required:['display_name','name','source'],properties:{
    display_name:{type:'string',title:'页面名称'},name:{type:'string',title:'调用名称'},
    source:{type:'string',title:'Python 源码'},input_schema:{type:'object'},
  }};
  const edited=[],states=[],submittedDrafts=[];
  const source='def main(quantity: int, price: float = 2.5):\n  return quantity * price\n';
  render(React.createElement(ToolDefinitionForm,{schema:pythonSchema,initial:{kind:'python',display_name:'计算',name:'calculate',source,input_schema:inputSchema},
    onSave:value => submittedDrafts.push(value),onEdited:value => edited.push(value),onSourceAnalysis:analysis => states.push(analysis)}));
  await waitFor(() => assert.ok(states.at(-1)?.input_schema));
  assert.equal(edited.length,0);
  assert.equal(document.querySelector('.tool-field-source textarea'),null);
  const preview=screen.getByRole('region',{name:'源码参数预览'});
  assert.match(preview.textContent,/quantity/);
  assert.match(preview.textContent,/可省略/);
  assert.equal(preview.querySelectorAll('input,textarea,select').length,0);
  replacePythonSource('def main(:');
  assert.equal(states.at(-1).input_schema,null);
  assert.match(preview.textContent,/python_syntax/);
  assert.doesNotMatch(preview.textContent,/quantity/);
  assert.equal(edited.at(-1).source,'def main(:');
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  replacePythonSource(source);
  assert.ok(states.at(-1).input_schema);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submittedDrafts[0].source,source);
  assert.equal(Object.hasOwn(submittedDrafts[0],'input_schema'),false);
  cleanup();
  const submitted=[];
  render(React.createElement(ToolInputForm,{schema:inputSchema,disabled:false,onTest:value => submitted.push(value)}));
  assert.equal(screen.getByLabelText('price').value,'');
  fireEvent.change(screen.getByLabelText(/quantity/),{target:{value:'3'}});
  await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
  assert.deepEqual(JSON.parse(JSON.stringify(submitted)),[{quantity:3}]);
});

test('CodeMirror 保持光标和撤销历史，外部重读不触发编辑，禁用与只读可更新', () => {
  const changes=[],focus=[],blur=[];
  const props={id:'source-editor',label:'Python 源码',value:'def main(): pass',schema:{type:'string'},
    registry:{formContext:{}},onChange:value => changes.push(value),onFocus:(...args) => focus.push(args),onBlur:(...args) => blur.push(args)};
  const form=render(React.createElement(PythonSourceEditor,props));
  const content=screen.getByRole('textbox',{name:'Python 源码'});
  const view=EditorView.findFromDOM(content);
  act(() => {view.focus();view.dispatch({changes:{from:view.state.doc.length,insert:' # 中文'},selection:{anchor:5}});});
  assert.deepEqual(changes,['def main(): pass # 中文']);
  form.rerender(React.createElement(PythonSourceEditor,{...props,value:changes.at(-1)}));
  assert.equal(EditorView.findFromDOM(content),view);
  assert.equal(view.state.selection.main.anchor,5);
  act(() => {assert.equal(undo(view),true);assert.equal(redo(view),true);});
  assert.equal(view.state.doc.toString(),'def main(): pass # 中文');
  const count=changes.length;
  form.rerender(React.createElement(PythonSourceEditor,{...props,value:'def main(): return 1',readonly:true}));
  assert.equal(view.state.doc.toString(),'def main(): return 1');
  assert.equal(changes.length,count);
  assert.equal(view.state.facet(EditorState.readOnly),true);
  assert.equal(indentMore(view),false);
  assert.equal(content.getAttribute('aria-readonly'),'true');
  form.rerender(React.createElement(PythonSourceEditor,{...props,disabled:true}));
  assert.equal(view.state.facet(EditorView.editable),false);
  assert.equal(content.getAttribute('aria-disabled'),'true');
  assert.equal(content.getAttribute('tabindex'),'-1');
  assert.equal(changes.length,count);
  form.rerender(React.createElement(PythonSourceEditor,props));
  assert.equal(EditorView.findFromDOM(content),view);
  assert.equal(view.state.facet(EditorState.readOnly),false);
  act(() => view.focus());
  fireEvent.blur(content);
  assert.ok(focus.length);
  assert.equal(blur.at(-1)[0],'source-editor');
  assert.ok(content.getAttribute('aria-describedby').includes('source-editor__help'));
  const multiline='def helper(): pass\r\nbroken\r\n';
  const from=multiline.indexOf('broken');
  form.rerender(React.createElement(PythonSourceEditor,{...props,value:multiline,registry:{formContext:{pythonAnalysis:{
    diagnostics:[{from,to:from+6,severity:'warning',code:'python_syntax',message:'测试诊断'}],
  }}}}));
  const marked=[];
  forEachDiagnostic(view.state,(_diagnostic,start,end) => marked.push(view.state.doc.sliceString(start,end)));
  assert.deepEqual(marked,['broken']);
  assert.equal(changes.length,count);
});

test('本地不能识别的源码可显式交给后端，不复用旧 schema，也不修改草稿', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const states=[],edited=[],submitted=[];
  const source="def main(a: '\\x69nt'): return a\n";
  render(React.createElement(ToolDefinitionForm,{schema:{type:'object',properties:{source:{type:'string',title:'Python 源码'},input_schema:{type:'object'}}},
    initial:{kind:'python',source},onSourceAnalysis:value => states.push(value),onEdited:value => edited.push(value),onSave:value => submitted.push(value)}));
  assert.equal(states.at(-1).input_schema,null);
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'交给后端校验'}));
  assert.deepEqual(states.at(-1).input_schema,{});
  assert.equal(edited.length,0);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted[0].source,source);
  assert.equal(Object.hasOwn(submitted[0],'input_schema'),false);
  replacePythonSource(source+'# changed');
  assert.equal(states.at(-1).input_schema,null);
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
});

test('真实 rjsf 测试表单不注入业务值，JSON 与表单切换保留实际 inputs 和无效原文', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const submitted = [];
  const inputSchema = {type:'object',properties:{body:{type:'object',required:['flag'],properties:{
    flag:{type:'boolean'}, value:{type:'string',default:'injected'}, choice:{type:'string',enum:['first','second']},
    items:{type:'array',minItems:2,items:{type:'string'}}, email:{type:'string',format:'email'},
  }}}};
  const form = render(React.createElement(ToolInputForm,{schema:inputSchema,disabled:false,onTest:value => submitted.push(value)}));
  await user.click(screen.getByRole('button',{name:'JSON 参数'}));
  const editor = screen.getByLabelText('测试参数 JSON');
  assert.deepEqual(JSON.parse(editor.value), {});
  const inputs = {body:{flag:false,value:'',choice:'second',items:[],email:'not-an-email',nested:[null,0,{},[]]},extra:7};
  fireEvent.change(editor,{target:{value:JSON.stringify(inputs)}});
  await user.click(screen.getByRole('button',{name:'参数表单'}));
  await user.click(screen.getByRole('button',{name:'JSON 参数'}));
  assert.deepEqual(JSON.parse(screen.getByLabelText('测试参数 JSON').value),inputs);
  await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
  assert.deepEqual(submitted,[inputs]);
  fireEvent.change(screen.getByLabelText('测试参数 JSON'),{target:{value:'{"body":'}});
  assert.match(screen.getByRole('alert').textContent,/JSON/);
  assert.equal(screen.getByRole('button',{name:'测试已保存工具'}).disabled,true);
  form.rerender(React.createElement(ToolInputForm,{schema:{type:'object',properties:{}},disabled:false,onTest:value => submitted.push(value)}));
  assert.equal(screen.getByLabelText('测试参数 JSON').value,'{"body":');
  fireEvent.change(screen.getByLabelText('测试参数 JSON'),{target:{value:JSON.stringify(inputs)}});
  await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
  assert.deepEqual(submitted.at(-1),inputs);
});

test('两种方言的真实 rjsf 保持未回答布尔和枚举，format 不增加阻断且提交真实类型', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  for (const dialect of ['http://json-schema.org/draft-07/schema#','https://json-schema.org/draft/2020-12/schema']) {
    const submitted=[];
    const schema={$schema:dialect,type:'object',required:['body'],properties:{body:{type:'object',required:['flag','count','mail','date'],properties:{
      flag:{type:'boolean',title:'明确布尔'}, count:{type:'integer',title:'数量',minimum:0},
      mail:{type:'string',title:'邮箱注解',format:'email'}, date:{type:'string',title:'日期注解',format:'date'},
      choice:{type:'string',title:'枚举',enum:['first','second']},
      defaulted:{type:'string',default:'generated'}, list:{type:'array',minItems:2,items:{type:'integer'}},
    }}}};
    const form=render(React.createElement(ToolInputForm,{schema,disabled:false,onTest:value => submitted.push(value)}));
    assert.equal(screen.getByLabelText(/明确布尔/).value,'');
    assert.equal(screen.getByLabelText(/枚举/).value,'');
    await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
    assert.equal(submitted.length,0);
    await user.click(screen.getByRole('button',{name:'JSON 参数'}));
    assert.deepEqual(JSON.parse(screen.getByLabelText('测试参数 JSON').value),{});
    await user.click(screen.getByRole('button',{name:'参数表单'}));
    await user.selectOptions(screen.getByLabelText(/明确布尔/),'false');
    await user.type(screen.getByLabelText(/数量/),'0');
    assert.equal(screen.getByLabelText(/邮箱注解/).type,'text');
    assert.equal(screen.getByLabelText(/日期注解/).type,'text');
    await user.type(screen.getByLabelText(/邮箱注解/),'not-an-email');
    await user.type(screen.getByLabelText(/日期注解/),'not-a-date');
    await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
    assert.deepEqual(JSON.parse(JSON.stringify(submitted)),[{body:{flag:false,count:0,mail:'not-an-email',date:'not-a-date'}}]);
    form.unmount();
  }
});

test('schema 更新或输入不匹配枚举时保留原参数，使用 JSON 诊断而不让控件修正值', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const schema={type:'object',properties:{query:{type:'object',properties:{choice:{type:'string',enum:['before']}}}}};
  const form=render(React.createElement(ToolInputForm,{schema,disabled:false,onTest:() => {}}));
  await user.click(screen.getByRole('button',{name:'JSON 参数'}));
  fireEvent.change(screen.getByLabelText('测试参数 JSON'),{target:{value:'{"query":{"choice":"before","extra":0}}'}});
  await user.click(screen.getByRole('button',{name:'参数表单'}));
  form.rerender(React.createElement(ToolInputForm,{schema:{...schema,properties:{query:{type:'object',properties:{choice:{type:'string',enum:['after']}}}}},disabled:false,onTest:() => {}}));
  await user.click(screen.getByRole('button',{name:'JSON 参数'}));
  assert.deepEqual(JSON.parse(screen.getByLabelText('测试参数 JSON').value),{query:{choice:'before',extra:0}});
  assert.ok(screen.getByText(/原输入.*JSON/));
  form.rerender(React.createElement(ToolInputForm,{schema:{type:'object',properties:{}},disabled:false,onTest:() => {}}));
  await user.click(screen.getByRole('button',{name:'参数表单'}));
  assert.deepEqual(JSON.parse(screen.getByLabelText('实际测试参数').textContent),{query:{choice:'before',extra:0}});
});

test('JSON 超范围数字保留原文并拒绝测试，日期时间等 format 控件不转换字符串', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const submitted=[];
  const schema={type:'object',properties:{body:{type:'object',properties:{
    dateTime:{type:'string',format:'date-time'}, time:{type:'string',format:'time'},
    dataUrl:{type:'string',format:'data-url'}, hostname:{type:'string',format:'hostname'},
    number:{type:['number','null']},
  }}}};
  const numeric=render(React.createElement(ToolInputForm,{schema,disabled:false,onTest:value => submitted.push(value)}));
  fireEvent.change(screen.getByLabelText('测试参数 JSON'),{target:{value:'{"body":{"number":1e999}}'}});
  assert.equal(screen.getByRole('button',{name:'测试已保存工具'}).disabled,true);
  assert.equal(screen.getByLabelText('测试参数 JSON').value,'{"body":{"number":1e999}}');
  assert.match(screen.getByRole('alert').textContent,/数字|number/);
  assert.equal(submitted.length,0);
  numeric.unmount();
  const formSchema={...schema,properties:{body:{...schema.properties.body,properties:{...schema.properties.body.properties,number:{type:'number'}}}}};
  render(React.createElement(ToolInputForm,{schema:formSchema,disabled:false,onTest:value => submitted.push(value)}));
  fireEvent.change(screen.getByLabelText('number'),{target:{value:'1e999'}});
  assert.equal(screen.getByRole('button',{name:'测试已保存工具'}).disabled,true);
  assert.match(screen.getByRole('alert').textContent,/数字|数值/);
  assert.equal(screen.getByRole('button',{name:'JSON 参数'}).disabled,true);
  await user.clear(screen.getByLabelText('number'));
  for (const label of ['dateTime','time','dataUrl','hostname']) await user.type(screen.getByLabelText(label),'not-a-format');
  await user.click(screen.getByRole('button',{name:'测试已保存工具'}));
  assert.deepEqual(JSON.parse(JSON.stringify(submitted)),[{body:{dateTime:'not-a-format',time:'not-a-format',dataUrl:'not-a-format',hostname:'not-a-format'}}]);
});

const schema = {type:'object', required:['display_name','name','url'], properties:{
  display_name:{type:'string', title:'页面名称', minLength:1},
  name:{type:'string', title:'调用名称', minLength:1, maxLength:64, pattern:'^[A-Za-z_][A-Za-z0-9_]*$'},
  url:{type:'string', title:'请求地址', minLength:1},
  timeout_seconds:{type:'number', title:'超时（秒）', minimum:1, maximum:300},
  input_schema:{type:'object', title:'输入结构'},
  output_schema:{type:['object','null'], title:'输出结构'},
  enabled:{type:'boolean', title:'启用'},
}};
const initial = {display_name:'',name:'tool',url:'',enabled:true,timeout_seconds:30,
  input_schema:{type:'object',properties:{},additionalProperties:false},output_schema:null};
const authManagementSchema={...schema,properties:{...schema.properties,auth:{type:'array',title:'认证',items:{type:'object',properties:{
  id:{type:'string'},kind:{type:'string'},location:{type:'string'},name:{type:'string'},value:{type:'string'},
}}}}};

test('认证表单直接回填和编辑密钥，清空提交空字符串且不改变业务输入', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const submitted=[];
  render(React.createElement(ToolDefinitionForm,{schema:authManagementSchema,initial:{...initial,display_name:'认证',url:'http://localhost/',auth:[{id:'bearer',kind:'bearer',location:'headers',name:'Authorization',value:'saved-token'}]},onSave:value => submitted.push(value)}));
  const password=screen.getByLabelText('认证密钥');
  assert.equal(password.type,'password');
  assert.equal(password.value,'saved-token');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted[0].auth[0].value,'saved-token');
  await user.clear(password);
  await user.type(password,'replacement-token');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted.at(-1).auth[0].value,'replacement-token');
  assert.ok(!('credential' in submitted.at(-1).auth[0]));
  assert.equal(screen.queryByRole('button',{name:'清空已保存密钥'}),null);
  await user.clear(password);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted.at(-1).auth[0].value,'');
  assert.deepEqual(submitted.at(-1).input_schema,initial.input_schema);
  assert.doesNotMatch(JSON.stringify({...browser.window.localStorage}),/saved-token|replacement-token/);
  await user.selectOptions(screen.getByLabelText('认证方式'),'api_key_query');
  assert.equal(screen.getByLabelText('凭据参数名').value,'api_key');
  await user.click(screen.getByRole('button',{name:'添加认证凭据'}));
  assert.equal(screen.getAllByLabelText(/认证密钥/).length,2);
  await user.selectOptions(screen.getByLabelText('认证方式'),'none');
  assert.equal(screen.queryByLabelText('认证密钥'),null);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.deepEqual(submitted.at(-1).auth,[]);
});

test('参数表格修改单字段保留约束和说明，高级 JSON 错误保留原文并阻止保存', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const submitted=[];
  const inputSchema={type:'object',additionalProperties:false,description:'root',properties:{query:{type:'object',description:'group',properties:{
    limit:{type:'integer',minimum:0,maximum:100,description:'old',examples:[0],default:10},
    other:{type:'string',pattern:'^[a-z]+$',description:'untouched',examples:['abc']},
  }},body:{type:'object',properties:{nested:{type:'array',items:{type:'object',properties:{flag:{type:'boolean'}}}}}}}};
  render(React.createElement(ToolDefinitionForm,{schema,initial:{...initial,display_name:'table',url:'http://localhost/',input_schema:inputSchema},onSave:value => submitted.push(value)}));
  fireEvent.change(screen.getByLabelText('query.limit 说明'),{target:{value:'changed'}});
  await user.click(screen.getByRole('button',{name:'高级输入 JSON'}));
  const editor=screen.getByLabelText('输入结构');
  const updated=JSON.parse(editor.value);
  assert.deepEqual(updated,{...inputSchema,properties:{...inputSchema.properties,query:{...inputSchema.properties.query,properties:{...inputSchema.properties.query.properties,limit:{...inputSchema.properties.query.properties.limit,description:'changed'}}}}});
  assert.match(screen.getByText(/复杂结构.*高级/).textContent,/body/);
  fireEvent.change(editor,{target:{value:'{invalid'}});
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted.length,0);
  assert.equal(screen.getByLabelText('输入结构').value,'{invalid');
  assert.match(screen.getAllByRole('alert').map(item => item.textContent).join(' '),/JSON/);
  fireEvent.change(screen.getByLabelText('输入结构'),{target:{value:JSON.stringify(updated)}});
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.deepEqual(submitted[0].input_schema,updated);
  assert.equal(submitted[0].output_schema,null);
  assert.ok(screen.getByText(/未声明输出结构/));
});

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

test('Python 工作区本地更新表单，提交不带派生 schema，保存与重读失败状态分别保留', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const source='def main(quantity: int, price: float = 2.5):\n    return quantity * price\n';
  const management={type:'object',required:['display_name','name','source'],properties:{
    display_name:{type:'string',title:'页面名称'},name:{type:'string',title:'调用名称'},
    kind:{type:'string',const:'python'},source:{type:'string',title:'Python 源码'},
    enabled:{type:'boolean'},input_schema:{type:'object'},output_schema:{type:['object','null']},
  }};
  let saved={kind:'python',id:'local-python',display_name:'本地 Python',name:'local_python',description:'',enabled:true,timeout_seconds:30,
    source,code_path:'tools/code.py',created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z',output_schema:null,
    input_schema:{type:'object',properties:{quantity:{type:'integer'},price:{type:'number',default:2.5}},required:['quantity'],additionalProperties:false}};
  const requests=[],writes=[],tests=[];
  let failDetail=false;
  const session=toolSession(async (url,init) => {
    requests.push(url);
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.endsWith('/schema/python')) return response({data:management});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (url.endsWith('/api/tools/tests')) {
      tests.push(JSON.parse(init.body));
      return response({data:{test_id:'local-test',tool_id:saved.id,status:'success',created_at:saved.created_at,
        result:{status:'success',data:14,error:null,duration_ms:1,details:{}}}});
    }
    if (init?.method === 'PUT') {
      const payload=JSON.parse(init.body);
      writes.push(payload);
      if (payload.definition.source.startsWith('return '))
        return new Response(JSON.stringify({detail:{code:'python_syntax',message:'return outside function'}}),{status:422});
      saved={...saved,...payload.definition};failDetail=true;
      return new Response(null,{status:204});
    }
    if (url.endsWith('/api/tools')) return response({data:[saved],version:'read-version'});
    assert.ok(url.endsWith('/api/tools/local-python'),url);
    if (failDetail) {failDetail=false;throw new Error('details unavailable');}
    return response({data:saved,version:'saved-version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('tab',{name:'Python (1)'}));
  await user.click(screen.getByRole('button',{name:/local_python.*本地 Python/}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'测试当前草稿'}).disabled,false));
  assert.equal(screen.queryByText('未保存修改'),null);
  assert.equal(screen.getByLabelText('price').value,'');
  fireEvent.change(screen.getByLabelText(/quantity/),{target:{value:'4'}});
  replacePythonSource('def main(:');
  assert.equal(screen.getByRole('button',{name:'测试当前草稿'}).disabled,true);
  assert.equal(screen.queryByLabelText(/quantity/),null);
  replacePythonSource(source.replace('2.5','3.5'));
  assert.equal(screen.getByLabelText(/quantity/).value,'4');
  await user.click(screen.getByRole('button',{name:'测试当前草稿'}));
  await screen.findAllByText('测试成功');
  assert.deepEqual(tests[0].inputs,{quantity:4});
  assert.equal(Object.hasOwn(tests[0].definition,'input_schema'),false);
  replacePythonSource('return 1\n'+source);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/保存失败/);
  assert.match(EditorView.findFromDOM(screen.getByRole('textbox',{name:'Python 源码'})).state.doc.toString(),/^return 1/);
  replacePythonSource(source.replace('2.5','3.5'));
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/工具已保存，详情读取失败/);
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  assert.equal(screen.queryByText(/保存结果不确定/),null);
  await user.click(screen.getByRole('button',{name:'重新读取工具详情'}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,false));
  assert.equal(screen.queryByText('未保存修改'),null);
  assert.equal(screen.queryByText('修改前的测试结果'),null);
  assert.equal(screen.getByLabelText('price').value,'');
  assert.equal(screen.getByLabelText(/quantity/).value,'4');
  assert.equal(writes.length,2);
  assert.ok(writes.every(payload => !Object.hasOwn(payload.definition,'input_schema')));
  assert.ok(requests.every(url => !url.includes('/python/parse')));
});

test('认证保存响应丢失保留不确定状态，明确放弃后只重读工具库', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const writes=[];let tool;let reloads=0;
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:authManagementSchema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'POST') {
      writes.push(JSON.parse(init.body));
      assert.deepEqual(init.headers,{'Content-Type':'application/json'});
      tool={...writes.at(-1),id:'auth-tool',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
      throw new TypeError('write response lost');
    }
    if (tool && url.endsWith('/api/tools') && ++reloads === 1) throw new TypeError('read failed');
    return response({data:url.endsWith('/api/tools') ? (tool ? [tool] : []) : tool,version:'version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(screen.getByLabelText(/页面名称/),'认证保存');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.selectOptions(screen.getByLabelText('认证方式'),'bearer');
  await user.type(screen.getByLabelText('认证密钥'),'ticket04-uncertain-secret');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/保存结果不确定/);
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  assert.equal(screen.queryByText('工具已保存'),null);
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读工具库'}));
  await screen.findByText(/工具库重读失败/);
  assert.equal(screen.getByLabelText('认证密钥').value,'ticket04-uncertain-secret');
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  assert.equal(writes.length,1);
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读工具库'}));
  await screen.findByText(/此前保存结果仍不确定/);
  assert.equal(screen.queryByLabelText('认证密钥'),null);
  assert.equal(screen.queryByText('工具已保存'),null);
  await user.click(screen.getByRole('button',{name:/认证保存/}));
  assert.equal(screen.getByLabelText('认证密钥').value,'ticket04-uncertain-secret');
  assert.equal(writes.length,1);
  assert.equal(screen.queryByRole('alert'),null);
  assert.doesNotMatch(document.body.textContent,/ticket04-uncertain-secret/);
});

test('创建成功后详情读取失败明确已保存，重读恢复编辑且不重复创建', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const writes=[];let saved;let reads=0;
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'POST') {
      writes.push(JSON.parse(init.body));
      saved={...writes[0],id:'created-id',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
      return response({data:{id:saved.id}});
    }
    if (url.endsWith('/api/tools/created-id')) {
      if (++reads <= 2) return new Response(JSON.stringify({detail:{code:'config_read',message:'暂时无法读取'}}),{status:503});
      return response({data:saved,version:'new-version'});
    }
    return response({data:[],version:'version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(screen.getByLabelText(/页面名称/),'已提交');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/已保存，详情读取失败/);
  assert.equal(screen.queryByText(/保存结果不确定/),null);
  assert.equal(screen.getByLabelText(/页面名称/).value,'已提交');
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'重新读取工具详情'}));
  await screen.findByText(/已保存，详情读取失败/);
  assert.equal(writes.length,1);
  await user.click(screen.getByRole('button',{name:'重新读取工具详情'}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,false));
  assert.equal(screen.queryByRole('alert'),null);
  assert.ok(screen.getByText('created-id'));
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,false);
  assert.equal(writes.length,1);
});

test('更新 204 后详情读取失败保留已保存状态，重读后完成离开并使用新版本', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  let tool={...initial,kind:'http',method:'GET',headers:{},parameters:[],description:'',id:'updated-id',name:'updated_tool',display_name:'更新工具',url:'http://localhost/',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  const writes=[];let reads=0;let version='old-version';
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'PUT') {
      writes.push(JSON.parse(init.body));tool={...tool,...writes.at(-1).definition};version=`version-${writes.length}`;
      return new Response(null,{status:204});
    }
    if (url.endsWith('/api/tools/updated-id') && ++reads === 2) throw new TypeError('details temporarily unavailable');
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/updated_tool.*更新工具/}));
  await user.type(screen.getByLabelText(/请求地址/),'changed');
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  const dialog=await screen.findByRole('dialog',{name:'工具已保存'});
  await within(dialog).findByText(/已保存，详情读取失败/);
  assert.equal(writes.length,1);
  assert.equal(within(dialog).getByRole('button',{name:'保存并离开'}).disabled,true);
  assert.equal(screen.queryByText(/保存结果不确定/),null);
  await user.click(within(dialog).getByRole('button',{name:'重新读取工具详情'}));
  await waitFor(() => assert.equal(screen.queryByLabelText(/请求地址/),null));
  await user.click(screen.getByRole('button',{name:/updated_tool.*更新工具/}));
  await waitFor(() => assert.equal(screen.getByLabelText(/请求地址/).value,'http://localhost/changed'));
  await user.type(screen.getByLabelText(/请求地址/),'-second');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText('工具已保存');
  assert.equal(writes.length,2);
  assert.equal(writes[0].version,'old-version');
  assert.equal(writes[1].version,'version-1');
});

test('未保存草稿可测试，修改后标记旧结果，离开保存失败保留草稿', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const writes=[];const tests=[];
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (url.endsWith('/api/tools/tests')) {
      tests.push(JSON.parse(init.body));
      return response({data:{test_id:'draft-test',tool_id:null,status:'success',created_at:'2026-10-14T00:00:00Z',result:{status:'success',data:0,error:null,duration_ms:1,details:{}}}});
    }
    if (init?.method === 'POST') {
      writes.push(JSON.parse(init.body));
      return new Response(JSON.stringify({detail:{code:'config_write',message:'磁盘不可写'}}),{status:503});
    }
    return response({data:[],version:'version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(screen.getByLabelText(/页面名称/),'草稿');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/draft');
  await user.click(screen.getByRole('button',{name:'测试当前草稿'}));
  await screen.findAllByText('测试成功');
  assert.equal(tests[0].definition.url,'http://localhost/draft');
  assert.deepEqual(tests[0].inputs,{});
  assert.equal(writes.length,0);
  await user.type(screen.getByLabelText(/请求地址/),'-changed');
  assert.ok(screen.getByText('修改前的测试结果'));
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  const dialog=screen.getByRole('dialog',{name:'未保存的工具修改'});
  await user.click(within(dialog).getByRole('button',{name:'保存并离开'}));
  await within(dialog).findByText(/保存失败/);
  assert.equal(screen.getByLabelText(/请求地址/).value,'http://localhost/draft-changed');
  await user.click(within(dialog).getByRole('button',{name:'继续编辑'}));
  assert.equal(screen.queryByRole('dialog'),null);
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  await user.click(screen.getByRole('button',{name:'放弃修改'}));
  assert.equal(screen.queryByLabelText(/请求地址/),null);
});

test('离开保存成功后才切换工具，未保存内容不会进入浏览器存储', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const a={...initial,kind:'http',method:'GET',headers:{},parameters:[],description:'',id:'a',display_name:'工具甲',name:'tool_a',url:'http://localhost/a',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  const b={...a,id:'b',name:'tool_b',display_name:'工具乙'};
  let resolveSave;let update;let currentA=a;let version='read-version';
  const storage=browser.window.localStorage.length;
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'PUT') {update=JSON.parse(init.body);return new Promise(resolve => {resolveSave=resolve;});}
    return response({data:url.endsWith('/api/tools') ? [currentA,b] : url.endsWith('/a') ? currentA : b,version});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/tool_a.*工具甲/}));
  await user.type(screen.getByLabelText(/页面名称/),'修改');
  await user.click(screen.getByRole('button',{name:/tool_b.*工具乙/}));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  assert.equal(update.version,'read-version');
  assert.equal(screen.getByLabelText(/页面名称/).value,'工具甲修改');
  assert.equal(screen.getByRole('button',{name:'放弃修改'}).disabled,true);
  await act(async () => {currentA={...a,...update.definition};version='new-version';resolveSave(new Response(null,{status:204}));});
  await waitFor(() => assert.equal(screen.getByLabelText(/页面名称/).value,'工具乙'));
  assert.equal(screen.queryByRole('dialog'),null);
  assert.equal(browser.window.localStorage.length,storage);
});

test('工具删除要求确认和读取版本，失败保留编辑，成功移除列表及详情', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const tool={...initial,kind:'http',method:'GET',headers:{},parameters:[],description:'',id:'delete-id',display_name:'待删工具',name:'delete_tool',url:'http://localhost/',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  const deletes=[];
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'DELETE') {
      deletes.push(JSON.parse(init.body));
      if (deletes.length === 1) return new Response(JSON.stringify({detail:{code:'config_write',message:'不可写'}}),{status:503});
      return new Response(null,{status:204});
    }
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version:'read-version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/delete_tool.*待删工具/}));
  await user.click(screen.getByRole('button',{name:'删除工具'}));
  assert.equal(deletes.length,0);
  assert.ok(screen.getByText(/未来引用此 ID.*工具不存在/));
  await user.click(screen.getByRole('button',{name:'确认删除'}));
  await screen.findByText(/删除失败/);
  assert.equal(screen.getByLabelText(/页面名称/).value,'待删工具');
  await user.click(screen.getByRole('button',{name:'确认删除'}));
  await screen.findByText('工具已删除');
  assert.deepEqual(deletes,[{version:'read-version'},{version:'read-version'}]);
  assert.equal(screen.queryByLabelText(/页面名称/),null);
  assert.equal(screen.queryByRole('button',{name:/delete_tool.*待删工具/}),null);
  assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false);
});

test('保存相同草稿保留有效测试，修改保存后列表和详情标记旧结果', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  let tool={...initial,kind:'http',method:'GET',headers:{},parameters:[{location:'query',input_name:'q',name:'q'}],input_schema:{type:'object',properties:{query:{type:'object',properties:{q:{type:'string'}}}}},description:'',id:'tested',display_name:'测试记录工具',name:'tested_tool',url:'http://localhost/before',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  let version='version';
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (url.endsWith('/api/tools/tests')) return response({data:{test_id:'recent-test',tool_id:tool.id,status:'success',created_at:tool.created_at,result:{status:'success',data:0,error:null,duration_ms:1,details:{}}}});
    if (init?.method === 'PUT') {
      const definition=JSON.parse(init.body).definition;
      tool={...tool,...definition,parameters:definition.parameters.map(mapping => ({...mapping,style:null,explode:null}))};version='saved-version';return new Response(null,{status:204});
    }
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/tested_tool.*测试记录工具/}));
  await user.click(screen.getByRole('button',{name:'测试当前草稿'}));
  await screen.findAllByText('测试成功');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText('工具已保存');
  assert.equal(screen.queryByText('修改前的测试结果'),null);
  await user.type(screen.getByLabelText(/请求地址/),'-after');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText('工具已保存');
  const sidebar=screen.getByRole('complementary',{name:'工具库'});
  assert.ok(within(sidebar).getByText('修改前的测试结果'));
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  await user.click(within(sidebar).getByRole('button',{name:/tested_tool.*测试记录工具/}));
  await waitFor(() => assert.ok(within(screen.getByRole('region',{name:'快速测试调试'})).getByText('修改前的测试结果')));
});

test('无效映射 JSON 保留原文并阻止测试，离开校验失败后仍可继续编辑', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const management={...schema,properties:{...schema.properties,parameters:{
    type:'array',title:'请求映射',items:{type:'object',required:['location','input_name','name'],
      properties:{location:{type:'string'},input_name:{type:'string'},name:{type:'string'}}},
  }}};
  const session=toolSession(async (url,init) => {
    assert.ok(!init?.method || init.method === 'GET','invalid draft must not start tests or save');
    if (url.endsWith('/schema/http')) return response({data:management});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    return response({data:[],version:'version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(screen.getByLabelText(/页面名称/),'无效草稿');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  fireEvent.change(screen.getByLabelText('请求映射'),{target:{value:'[null]'}});
  assert.deepEqual(JSON.parse(screen.getByLabelText('请求映射').value),[null]);
  assert.equal(screen.getByRole('button',{name:'测试当前草稿'}).disabled,true);
  await user.type(screen.getByLabelText('新参数名称'),'q');
  await user.click(screen.getByRole('button',{name:'添加参数'}));
  assert.deepEqual(JSON.parse(screen.getByLabelText('请求映射').value),[null]);
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  await screen.findByText(/保存前校验失败/);
  await user.click(screen.getByRole('button',{name:'继续编辑'}));
  assert.deepEqual(JSON.parse(screen.getByLabelText('请求映射').value),[null]);
});

test('保存响应丢失后锁定重复创建，明确放弃草稿后重读工具库', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  let saved = null;
  let posts = 0;
  const session = toolSession(async (url, init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'POST') {
      posts++;
      saved = {...JSON.parse(init.body), id:'saved-id',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
      throw new TypeError('response lost after commit');
    }
    return response({data:url.endsWith('/api/tools') ? (saved ? [saved] : []) : saved,version:'saved-version'});
  });
  render(React.createElement(ToolsWorkspace, {session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(await screen.findByLabelText(/页面名称/),'响应丢失');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText(/保存结果不确定/);
  assert.equal(screen.getByLabelText(/页面名称/).value,'响应丢失');
  assert.equal(screen.getByRole('button',{name:'保存工具'}).disabled,true);
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(posts,1);
  await user.click(screen.getByRole('button',{name:'放弃草稿并重读工具库'}));
  await screen.findByText(/此前保存结果仍不确定/);
  assert.equal(screen.queryByLabelText(/页面名称/),null);
  assert.equal(screen.queryByText('工具已保存'),null);
  await user.click(screen.getByRole('button',{name:/响应丢失/}));
  assert.ok(screen.getByText('saved-id'));
  assert.equal(posts,1);
});

test('保存并离开响应丢失后，明确放弃草稿并重读才继续原操作', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  let posts=0;
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    if (init?.method === 'POST') {posts++;throw new TypeError('write response unavailable');}
    return response({data:[],version:'read-version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  await user.type(screen.getByLabelText(/页面名称/),'离开草稿');
  await user.type(screen.getByLabelText(/请求地址/),'http://localhost/');
  await user.click(screen.getByRole('button',{name:'返回工具列表'}));
  await user.click(screen.getByRole('button',{name:'保存并离开'}));
  const dialog=await screen.findByRole('dialog',{name:'保存结果不确定'});
  assert.equal(screen.getByLabelText(/页面名称/).value,'离开草稿');
  assert.equal(within(dialog).getByRole('button',{name:'保存并离开'}).disabled,true);
  assert.equal(within(dialog).getByRole('button',{name:'放弃修改'}).disabled,true);
  await user.click(within(dialog).getByRole('button',{name:'放弃草稿并重读工具库'}));
  await waitFor(() => assert.equal(screen.queryByRole('dialog'),null));
  assert.equal(screen.queryByLabelText(/页面名称/),null);
  assert.equal(posts,1);
  assert.equal(screen.queryByText('工具已保存'),null);
  assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false);
});

test('旧宿主的迟到保存错误不会覆盖新宿主已读取的工具页面', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  let rejectSave;
  const oldSession = toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
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
  await user.click(await screen.findByRole('button',{name:'测试当前草稿'}));
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
  await user.click(within(sidebar).getByRole('switch',{name:'隐藏禁用工具'}));
  assert.ok(within(sidebar).getByRole('button',{name:/天气查询/}));
  assert.equal(within(sidebar).queryByRole('button',{name:/库存查询/}),null);
  assert.equal(screen.getByLabelText(/页面名称/).value,'天气查询');
  await user.click(within(sidebar).getByRole('switch',{name:'隐藏禁用工具'}));
  assert.ok(within(sidebar).getByRole('button',{name:/库存查询/}));
  assert.equal(screen.queryByText(/HITL|Rust Sandbox|1,429|近 24 小时调用历史/),null);
});

test('工具类型 tab 支持数量、键盘切换，并与搜索和隐藏禁用工具组合', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  const http={...initial,kind:'http',method:'GET',description:'读取天气',id:'http',display_name:'HTTP 查询',name:'http_query',url:'http://localhost/weather',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  const python={...http,id:'python',kind:'python',display_name:'Python 计算',name:'python_calc',code_path:'tools/calc.py',enabled:false};
  const mcp={...http,id:'mcp',kind:'mcp',display_name:'MCP 搜索',name:'mcp_search',server_id:'local-server',remote_name:'search'};
  const session=toolSession(async url => response(url.endsWith('/schema/http') ? {data:schema} : {data:[http,python,mcp],version:'version'}));
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  const sidebar=await screen.findByRole('complementary',{name:'工具库'});
  await within(sidebar).findByRole('button',{name:/HTTP 查询/});
  assert.equal(screen.getByRole('tab',{name:'全部 (3)'}).getAttribute('aria-selected'),'true');
  await user.click(screen.getByRole('tab',{name:'Python (1)'}));
  assert.ok(within(sidebar).getByRole('button',{name:/Python 计算.*tools\/calc.py/}));
  assert.equal(within(sidebar).queryByRole('button',{name:/HTTP 查询/}),null);
  await user.keyboard('{ArrowRight}');
  assert.equal(screen.getByRole('tab',{name:'MCP (1)'}),document.activeElement);
  assert.ok(within(sidebar).getByRole('button',{name:/MCP 搜索.*local-server \/ search/}));
  assert.equal(within(sidebar).queryByText(/在线/),null);
  await user.keyboard('{Home}');
  assert.equal(screen.getByRole('tab',{name:'全部 (3)'}),document.activeElement);
  await user.click(screen.getByRole('switch',{name:'隐藏禁用工具'}));
  assert.equal(screen.getByRole('tab',{name:'全部 (2)'}).getAttribute('aria-selected'),'true');
  assert.ok(screen.getByRole('tab',{name:'Python (0)'}));
  assert.equal(within(sidebar).queryByRole('button',{name:/Python 计算/}),null);
  await user.type(screen.getByRole('searchbox',{name:'搜索工具'}),'mcp_search');
  assert.ok(within(sidebar).getByRole('button',{name:/MCP 搜索/}));
  assert.equal(within(sidebar).queryByRole('button',{name:/HTTP 查询/}),null);
  await user.click(screen.getByRole('tab',{name:'HTTP (1)'}));
  assert.ok(within(sidebar).getByText('没有匹配的工具。已隐藏禁用工具。'));
  await user.clear(screen.getByRole('searchbox',{name:'搜索工具'}));
  assert.ok(within(sidebar).getByRole('button',{name:/HTTP 查询/}));
});

test('操作栏启用开关同步配置草稿，保存后隐藏禁用工具且保留详情', async () => {
  const user=userEvent.setup({document:browser.window.document,delay:null});
  let tool={...initial,kind:'http',method:'GET',id:'toggle-id',display_name:'启用切换',name:'toggle_tool',description:'',url:'http://localhost/',created_at:'2026-10-14T00:00:00Z',updated_at:'2026-10-14T00:00:00Z'};
  const writes=[];
  const session=toolSession(async (url,init) => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true}});
    if (init?.method === 'PUT') {
      const payload=JSON.parse(init.body);writes.push(payload);tool={...tool,...payload.definition};
      return new Response(null,{status:204});
    }
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version:writes.length ? 'new-version' : 'version'});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  const sidebar=screen.getByRole('complementary',{name:'工具库'});
  await user.click(await within(sidebar).findByRole('button',{name:/启用切换/}));
  await user.click(screen.getByRole('switch',{name:'隐藏禁用工具'}));
  await user.click(screen.getByRole('button',{name:'禁用此工具'}));
  assert.equal(screen.getByLabelText(/^启用/).value,'false');
  assert.equal(writes.length,0);
  assert.ok(within(sidebar).getByRole('button',{name:/启用切换/}));
  await user.type(screen.getByLabelText(/页面名称/),'改名');
  assert.equal(screen.getByLabelText(/^启用/).value,'false');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  await screen.findByText('工具已保存');
  assert.equal(writes.length,1);assert.equal(writes[0].definition.enabled,false);
  assert.equal(tool.display_name,'启用切换改名');
  assert.equal(within(sidebar).queryByRole('button',{name:/启用切换/}),null);
  assert.equal(screen.getByLabelText(/页面名称/).value,'启用切换改名');
  await user.click(screen.getByRole('button',{name:'启用此工具'}));
  assert.equal(screen.getByLabelText(/^启用/).value,'true');
});

test('新建工具在前端建议名称并避开列表和内置名称，手动修改后不再跟随页面名称', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const urls = [];
  const existing = {...initial,kind:'http',method:'GET',name:'read_status',id:'existing',display_name:'已有工具',url:'http://localhost/',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
  const session = toolSession(async url => {
    urls.push(url);
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) return response({data:{valid:true,code:null,message:null}});
    assert.ok(url.endsWith('/api/tools'), url);
    return response({data:[existing],version:'version',reserved_names:['tool','add']});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await waitFor(() => assert.equal(screen.getByRole('button',{name:'创建 HTTP 工具'}).disabled,false));
  await user.click(screen.getByRole('button',{name:'创建 HTTP 工具'}));
  assert.equal(screen.getByLabelText(/调用名称/).value, 'tool_2');
  await user.type(screen.getByLabelText(/页面名称/), 'read status');
  assert.equal(screen.getByLabelText(/调用名称/).value, 'read_status_2');
  await user.clear(screen.getByLabelText(/调用名称/));
  await user.type(screen.getByLabelText(/调用名称/), 'my_tool');
  await user.type(screen.getByLabelText(/页面名称/), ' changed');
  assert.equal(screen.getByLabelText(/调用名称/).value, 'my_tool');
  await waitFor(() => assert.ok(urls.some(url => url.includes('/validate-name?name=my_tool'))));
  assert.ok(urls.every(url => !url.includes('name-candidate')));
});

test('名称异步校验忽略迟到结果，当前重名错误显示在字段并阻止提交', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const checks = [];
  const submitted = [];
  render(React.createElement(ToolDefinitionForm, {
    schema, initial:{...initial,display_name:'测试',name:'old_name',url:'http://localhost/'},
    validateName:(name, signal) => new Promise(resolve => checks.push({name,signal,resolve})),
    onSave:value => submitted.push(value),
  }));
  await waitFor(() => assert.equal(checks.length, 1));
  await user.clear(screen.getByLabelText(/调用名称/));
  await user.type(screen.getByLabelText(/调用名称/), 'new_name');
  await waitFor(() => assert.equal(checks.at(-1).name, 'new_name'));
  assert.equal(checks[0].signal.aborted,true);
  await act(async () => {
    checks.at(-1).resolve({valid:true,code:null,message:null});
    checks[0].resolve({valid:false,code:'name_conflict',message:'旧名称已占用'});
  });
  assert.equal(screen.queryByText('旧名称已占用'),null);
  await user.clear(screen.getByLabelText(/调用名称/));
  await user.type(screen.getByLabelText(/调用名称/), 'taken');
  await waitFor(() => assert.equal(checks.at(-1).name, 'taken'));
  await act(async () => checks.at(-1).resolve({valid:false,code:'name_conflict',message:'调用名称已占用'}));
  assert.ok(screen.getAllByText('调用名称已占用').length);
  assert.equal(screen.getByLabelText(/调用名称/).getAttribute('aria-invalid'),'true');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted.length,0);
});

test('编辑工具的名称校验排除自身，修改页面名称保留调用名称', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const tool = {...initial,kind:'http',method:'GET',name:'stable_name',description:'',id:'id / 中文',display_name:'已有工具',url:'http://localhost/',created_at:'2026-10-13T00:00:00Z',updated_at:'2026-10-13T00:00:00Z'};
  const checks = [];
  const session = toolSession(async url => {
    if (url.endsWith('/schema/http')) return response({data:schema});
    if (url.includes('/validate-name?')) {
      checks.push(new URL(url).searchParams);
      return response({data:{valid:true,code:null,message:null}});
    }
    return response({data:url.endsWith('/api/tools') ? [tool] : tool,version:'version',reserved_names:[]});
  });
  render(React.createElement(ToolsWorkspace,{session,onView:() => {}}));
  await user.click(await screen.findByRole('button',{name:/已有工具/}));
  await waitFor(() => assert.equal(checks.length,1));
  assert.equal(checks[0].get('name'),tool.name);
  assert.equal(checks[0].get('tool_id'),tool.id);
  await user.type(screen.getByLabelText(/页面名称/),'改名');
  assert.equal(screen.getByLabelText(/调用名称/).value,tool.name);
});

test('名称预校验不可用时保留草稿并允许后端在保存时校验', async () => {
  const user = userEvent.setup({document:browser.window.document,delay:null});
  const submitted = [];
  render(React.createElement(ToolDefinitionForm, {
    schema, initial:{...initial,display_name:'测试',url:'http://localhost/'},
    validateName:async () => {throw new TypeError('offline');},
    onSave:value => submitted.push(value),
  }));
  await screen.findByText('调用名称校验暂不可用，保存时将再次校验。');
  await user.click(screen.getByRole('button',{name:'保存工具'}));
  assert.equal(submitted.length,1);
  assert.equal(submitted[0].name,'tool');
});
