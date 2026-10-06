import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import Markdown from 'react-markdown';
import { renderToStaticMarkup } from 'react-dom/server';
import { captureConversationExport, collectExportRunOutcomes, serializeConversationExport, exportFilename, downloadConversationExport } from '../src/conversation-export.ts';

const createMessageRecord = (seq, type, content, contentFields = {}) => ({run_id:'run-1', seq,
  content:{type, message_id:`message-${seq}`, content, ...contentFields}});
const captureExportSnapshot = (messages, snapshotOptions = {}) => captureConversationExport({threadId:'thread-1', title:'导出测试',
  messages, capturedAt:new Date('2026-10-06T08:00:00Z'), ...snapshotOptions});

test('生命周期文案与执行错误保留各自字段，不把旧完成提示误标 error', () => {
  const events = {'run-old':[{seq:2,created_at:'2026-10-06T08:00:00Z',category:'lifecycle',event_type:'status_changed',
    payload:{status:'completed',message:'任务正常结束'}}], 'run-1':[
    {seq:6,created_at:'2026-10-06T08:00:00Z',category:'lifecycle',event_type:'status_changed',
      payload:{status:'error',message:'生命周期原文',error_code:'execution_failed'}},
    {seq:7,category:'approval',event_type:'resolved',payload:{status:'resolved',secret:'审批不要导出'}}]};
  const outcomes = collectExportRunOutcomes({'run-old':'completed'},events,
    {thread_id:'thread-1',run_id:'run-1',status:'error',error:'执行快照原因',error_code:'execution_failed'});
  assert.deepEqual(outcomes,[{run_id:'run-old',status:'completed',message:'任务正常结束'},
    {run_id:'run-1',status:'error',message:'生命周期原文',error_code:'execution_failed',error:'执行快照原因'}]);
  assert.doesNotMatch(JSON.stringify(outcomes),/审批不要导出|event_type|seq/);
});

test('点击快照仅含已提交消息，排序去重且后到和原对象变更不混入', () => {
  const messages = [createMessageRecord(3,'ai','**原回答**'), createMessageRecord(1,'human','  用户原文\n'),
    {...createMessageRecord(4,'ai','PREVIEW_EXCLUDED'), preview:true}];
  messages.push(structuredClone(messages[0]));
  const snapshot = captureExportSnapshot(messages);
  messages[0].content.content = '后来变更';
  messages.push(createMessageRecord(5,'ai','后到消息'));
  assert.deepEqual(snapshot.messages.map(message=>message.seq),[1,3]);
  const markdown = serializeConversationExport(snapshot);
  assert.match(markdown, /消息数：2/);
  assert.match(markdown, /已加载 seq：1, 3/);
  assert.match(markdown, /不代表服务端全部历史/);
  assert.ok(markdown.includes('  用户原文\n'));
  assert.ok(markdown.includes('**原回答**'));
  assert.doesNotMatch(markdown, /PREVIEW_EXCLUDED|后来变更|后到消息/);
});

const readJsonBlocks = markdown => [...markdown.matchAll(/^(`{3,})json\n([\s\S]*?)\n\1(?=\n|$)/gm)]
  .map(match=>JSON.parse(match[2]));

test('完整公开工具字段、未知字段、空 artifact 和正文数组保留，UI 合并不重复结果', () => {
  const calls = [{id:'call-1',name:'检查',args:{path:'C:\\报告', nested:{lines:[1,2]}}, future:'未知调用字段'}];
  const agent = createMessageRecord(2,'ai','检查中',{tool_calls:calls, generation_status:'complete', future:{source:false}});
  agent.metadata = {reason:'记录级原因'}; agent.extra = {kept:null};
  const tool = createMessageRecord(4,'tool',[{type:'text',text:'  结果\n',extra:true},{type:'unknown',raw:['```',null]}],
    {tool_call_id:'call-1', name:'检查',status:'error',artifact:{content:0,empty:[],nil:null}});
  const emptyTools = [false,0,'',[],{},null].map((artifact,index)=>createMessageRecord(5+index,'tool','',{artifact,status:'success'}));
  const markdown = serializeConversationExport(captureExportSnapshot([tool,agent,...emptyTools,structuredClone(tool)]));
  const fields = readJsonBlocks(markdown);
  assert.deepEqual(fields.find(message=>message.seq===2).content.tool_calls,calls);
  assert.deepEqual(fields.find(message=>message.seq===2).metadata,agent.metadata);
  assert.deepEqual(fields.find(message=>message.seq===2).extra,agent.extra);
  assert.deepEqual(fields.find(message=>message.seq===4).content.artifact,tool.content.artifact);
  assert.deepEqual(fields.find(Array.isArray),tool.content.content);
  assert.deepEqual(emptyTools.map(message=>fields.find(field=>field.seq===message.seq).content.artifact),[false,0,'',[],{},null]);
  assert.equal(markdown.match(/^## seq 4 · 工具结果$/gm).length,1);
  assert.match(markdown,/工具真实状态：error/);
});

test('正常 Agent Markdown 可读，中止／未闭合／HTML 原文隔离且长围栏不能吞后续记录', () => {
  const unsafeBodies = ['   开头\n``````````\n# 不闭合  \n', '<div>未闭合 HTML', '> ```\n引用内代码',
    '[ref]: https://example.com/\n', '  取消正文\n~~~~~~~~~~~~\n```  \n', '```lang`invalid\n正文\n```'];
  const messages = [createMessageRecord(1,'ai','## 正常标题\n\n**完整回答**\n\n```js\nconst x = 1;\n```')];
  for (const [index,body] of unsafeBodies.entries()) messages.push(createMessageRecord(index+2,'ai',body,
    {generation_status:index===4?'cancelled':'complete'}));
  messages.push(createMessageRecord(8,'ai','失败原文\n```',{generation_status:'error'}),createMessageRecord(9,'human','  最后一条\n'));
  const markdown = serializeConversationExport(captureExportSnapshot(messages,{runOutcomes:[{run_id:'run-1',status:'error',error:'真实原因\n不是正文',error_code:'execution_failed'}]}));
  for (const body of unsafeBodies) assert.ok(markdown.includes(body));
  assert.match(markdown,/```````````markdown\n/);
  assert.match(markdown,/因取消中止/); assert.match(markdown,/因失败中止/);
  assert.ok(markdown.includes('## 正常标题\n\n**完整回答**'));
  assert.equal(readJsonBlocks(markdown)[0][0].error,'真实原因\n不是正文');
  const html = renderToStaticMarkup(React.createElement(Markdown,{children:markdown}));
  for (const message of messages) assert.ok(html.includes(`<h2>seq ${message.seq} ·`));
  assert.match(html,/<strong>完整回答<\/strong>/);
  assert.doesNotMatch(html,/<div>未闭合 HTML/);
});

test('标题和身份不能注入结构，文件名安全且空标题用会话', () => {
  const snapshot = captureExportSnapshot([createMessageRecord(1,'ai','[报告](reports/a.pdf)\n\n![图](images/a.png)')],
    {title:'# 名字\n## 注入 <script> ``` :/\\?*',threadId:'id\n## 伪造'});
  const markdown = serializeConversationExport(snapshot);
  assert.doesNotMatch(markdown,/^## 注入|^## 伪造|<script>/m);
  assert.ok(markdown.includes('[报告](reports/a.pdf)\n\n![图](images/a.png)'));
  assert.doesNotMatch(exportFilename(snapshot),/[<>:"/\\|?*\u0000-\u001f]/);
  assert.match(exportFilename(captureExportSnapshot([], {title:null})),/^会话-2026-10-06T08-00-00-000Z\.md$/);
  assert.ok(exportFilename(captureExportSnapshot([],{title:'图'.repeat(150)})).length < 120);
});

test('空记录／仅预览不下载，冲突身份拒绝而不丢事实', () => {
  assert.throws(()=>serializeConversationExport(captureExportSnapshot([])),/暂无已提交内容/);
  assert.throws(()=>serializeConversationExport(captureExportSnapshot([{...createMessageRecord(1,'ai','预览'),preview:true}])),/暂无已提交内容/);
  assert.throws(()=>captureExportSnapshot([createMessageRecord(1,'ai','a'),createMessageRecord(1,'ai','b')]),/冲突/);
  assert.throws(()=>captureExportSnapshot([{...createMessageRecord(1,'ai','a'),thread_id:'其他会话'}]),/身份/);
});

test('Blob UTF-8 来源是捕获原文，取消／派发失败不改事实并释放 URL', async context => {
  const message = createMessageRecord(1,'human','  中文 🐈\n原文  \n');
  const snapshot = captureExportSnapshot([message]);
  let capturedBlob; const urlReleases = []; const timers = [];
  context.mock.method(URL,'createObjectURL',blob=>{capturedBlob=blob;return 'blob:export-1';});
  context.mock.method(URL,'revokeObjectURL',url=>urlReleases.push(url));
  context.mock.method(globalThis,'setTimeout',(performRevoke,delay)=>{timers.push({performRevoke,delay});});
  const link = {click(){},remove(){this.isRemoved=true;}};
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis,'document');
  Object.defineProperty(globalThis,'document',{configurable:true,value:{body:{append(){}},createElement(){return link;}}});
  context.after(()=>{if(originalDocument)Object.defineProperty(globalThis,'document',originalDocument);else delete globalThis.document;});
  assert.equal(downloadConversationExport(snapshot),exportFilename(snapshot));
  assert.equal(capturedBlob.type,'text/markdown;charset=utf-8');
  assert.equal(await capturedBlob.text(),serializeConversationExport(snapshot));
  assert.equal(link.isRemoved,true); assert.equal(timers.length,1);
  timers[0].performRevoke(); assert.deepEqual(urlReleases,['blob:export-1']);
  link.click = ()=>{throw new Error('下载不可用');};
  assert.throws(()=>downloadConversationExport(snapshot),/下载不可用/);
  assert.deepEqual(message,createMessageRecord(1,'human','  中文 🐈\n原文  \n'));
  assert.equal(urlReleases.length,2);
});
