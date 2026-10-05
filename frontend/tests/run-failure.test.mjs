import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {Conversation} from '../src/components/Conversation.tsx';
import {presentMessage} from '../src/message-presentation.ts';
import {RunFailure} from '../src/components/RunFailure.tsx';
import {BackendClient} from '../src/backend-client.ts';
import {ConversationStore} from '../src/conversation-state.ts';

const body = '  保存正文\n    原始空白 ';
const message = (generation_status, preview=false) => ({run_id:'r', seq:3, preview,
  content:{type:'ai', message_id:'answer', content:body, tool_calls:[], generation_status}});
const render = record => renderToStaticMarkup(React.createElement(Conversation, {
  session:{id:'a', title:'会话', messages:[presentMessage(record)], runStatuses:{r:'error'}},
  onSuggestion:()=>{}, onView:()=>{},
}));

test('失败正文保持原文且正文外标记中止，预览与 complete 不伪造中止', ()=> {
  const html = render(message('error'));
  assert.match(html, /因失败中止/);
  assert.match(html, /class="badge generation-error"/);
  assert.ok(html.indexOf('因失败中止') < html.indexOf('message-content'));
  assert.doesNotMatch(html, /因取消中止|生成中/);
  for (const record of [message('complete'), message(undefined), message('error',true)]) {
    assert.doesNotMatch(render(record), /因失败中止/);
  }
  assert.match(render(message('cancelled')), /class="badge generation-cancelled"/);
});

test('真实失败原因完整且安全显示，非 Run error 不显示失败原因', ()=> {
  const reason = '  <script>broken()</script>\n' + '失败详情 '.repeat(400) + '\n末尾 ';
  const run = {thread_id:'a',run_id:'r',status:'error',error:reason,error_code:'execution_failed'};
  const html = renderToStaticMarkup(React.createElement(RunFailure, {run,onView:()=>{}}));
  assert.ok(html.includes('execution_failed'));
  assert.ok(html.includes('&lt;script&gt;broken()&lt;/script&gt;'));
  assert.ok(html.includes('失败详情 '.repeat(400)));
  assert.ok(html.includes('\n末尾 '));
  assert.match(html,/查看完整内容/);
  assert.doesNotMatch(html,/<script>/);
  for (const status of ['running','interrupted','completed','cancelled']) {
    assert.equal(renderToStaticMarkup(React.createElement(RunFailure, {run:{...run,status},onView:()=>{}})), '');
  }
});

const date = '2026-10-05T00:00:00Z';
const ready = {revision:1,startup_id:'lease',base_url:'http://127.0.0.1:45200',state:'ready',can_retry:false,error:null};
const stored = (seq,content) => ({id:seq,thread_id:'a',run_id:'r',run_status:'running',seq,
  category:'message',event_type:content.type+'_message',event_key:content.type+':'+content.message_id,
  content,metadata:{},created_at:date});
const human = stored(2,{type:'human',message_id:'entry',content:'原文'});
const saved = stored(3,message('error').content);
const encode = (event,data) => new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
async function until(probe) {
  for (let i=0;i<300;i++) {if(probe())return;await new Promise(resolve=>setImmediate(resolve));}
  assert.fail('状态未达到预期');
}
async function setup(messages) {
  let stream, reads=0, posts=0, status='running';
  const reason='真实模型错误\n  request-123 ';
  const client = new BackendClient(async (url,init)=> {
    const path=new URL(url).pathname;
    if (init?.method==='POST') posts++;
    if(path==='/api/threads')return Response.json({data:[{id:'a',title:null,user_id:null,created_at:date,updated_at:date,run_id:'r',run_status:status}],next_cursor:null});
    if(path.endsWith('/runs/r/messages')) {
      reads++;return messages?.(reads) ?? Response.json({data:[{...human,run_status:status},{...saved,run_status:status}]});
    }
    if(path.endsWith('/messages'))return Response.json({data:[human]});
    if(path.endsWith('/stream'))return new Response(new ReadableStream({start:controller=> {
      stream=controller;
      controller.enqueue(encode('metadata',{thread_id:'a',run_id:'r',status}));
      controller.enqueue(encode('delta',{message_id:'answer',seq:3,field:'content',value:'当前片段'}));
    }}),{headers:{'Content-Type':'text/event-stream'}});
    return Response.json({data:{id:'r',thread_id:'a',status,error:status==='error'?reason:null,error_code:status==='error'?'execution_failed':null}});
  });
  const store = new ConversationStore({storage:null});
  client.update(ready);store.setSession(client.session);
  await until(()=>store.getSnapshot().views.a?.verified && store.getSnapshot().views.a.messages.at(-1)?.preview);
  return {store,reason,reads:()=>reads,posts:()=>posts,
    frame:(event,data)=>stream.enqueue(encode(event,data)),
    fail:()=>{status='error';stream.enqueue(encode('metadata',{thread_id:'a',run_id:'r',status,error:reason,error_code:'execution_failed'}));},
    close:()=>{store.setSession(null);client.update(null);}};
}

test('执行失败 metadata 自动补读一次完整事实，替换预览并保留草稿与原因',async()=> {
  const app=await setup();
  try {
    app.store.updateDraft('下一条草稿');app.fail();
    await until(()=>app.store.getSnapshot().views.a.savedContent==='ready');
    const view=app.store.getSnapshot().views.a;
    assert.equal(view.run.status,'error');assert.equal(view.run.error,app.reason);
    assert.equal(view.run.error_code,'execution_failed');
    assert.equal(view.messages.at(-1).content.generation_status,'error');
    assert.equal(view.messages.at(-1).content.content,body);
    assert.equal(view.messages.at(-1).preview,undefined);
    assert.equal(app.store.getSnapshot().drafts.a,'下一条草稿');
    assert.equal(app.store.canCancel(),false);assert.equal(app.store.canSend(),true);
    app.fail();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(app.reads(),1);assert.equal(app.posts(),0);
  } finally {app.close();}
});

test('终态正文读失败保留预览与真实 error，手动读取恢复，不自动导出预览',async()=> {
  const app=await setup(n=>n===1?new Response('content read failed',{status:500}):undefined);
  try {
    app.fail();await until(()=>app.store.getSnapshot().views.a.savedContent==='error');
    const view=app.store.getSnapshot().views.a;
    assert.equal(view.run.status,'error');assert.equal(view.run.error,app.reason);
    assert.equal(view.messages.at(-1).preview,true);
    assert.deepEqual(view.messages.filter(m=>!m.preview).map(m=>m.content.content),['原文']);
    app.fail();await new Promise(resolve=>setImmediate(resolve));assert.equal(app.reads(),1);
    await app.store.retrySavedContent();
    assert.equal(app.reads(),2);assert.equal(app.store.getSnapshot().views.a.savedContent,'ready');
  } finally {app.close();}
});

test('未知 generation_status 是协议问题，保存确认不猜测，原预览仍可读',async()=> {
  const unknown={...saved,content:{...saved.content,generation_status:'future'}};
  const app=await setup(()=>Response.json({data:[human,unknown]}));
  try {
    app.fail();await until(()=>app.store.getSnapshot().views.a.savedContent==='error');
    const view=app.store.getSnapshot().views.a;
    assert.equal(view.run.status,'error');assert.equal(view.messages.at(-1).preview,true);
    assert.equal(view.messages.at(-1).content.content,'当前片段');
    assert.equal(view.savedContentFailure.kind,'protocol');
    assert.deepEqual(view.savedContentFailure.raw,unknown.content);
    assert.equal(app.reads(),1);assert.equal(app.posts(),0);
  } finally {app.close();}
});

test('观察连接故障与工具 error 不标记真实 Run 失败或补读中止正文',async()=> {
  const app=await setup();
  try {
    app.frame('event',{seq:4,created_at:date,category:'message',event_type:'created',payload:{type:'tool',message_id:'tool',tool_call_id:'orphan',status:'error',content:'资源访问失败'}});
    await until(()=>app.store.getSnapshot().views.a.messages.length===3);
    assert.equal(app.store.getSnapshot().views.a.run.status,'running');assert.equal(app.reads(),0);
    app.frame('error',{code:'transport_failed',message:'连接失败',recoverable:false});
    await until(()=>app.store.getSnapshot().views.a.observation==='failed');
    assert.equal(app.store.getSnapshot().views.a.run.status,'running');
    assert.equal(app.reads(),0);assert.equal(app.posts(),0);
    assert.ok(app.store.getSnapshot().views.a.messages.some(m=>m.preview));
  } finally {app.close();}
});
