import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';
import { collectApprovalRecords } from '../src/approval-decisions.ts';

const date='2026-10-06T00:00:00Z';
const request={status:'required',checkpoint:{configurable:{thread_id:'t',checkpoint_ns:'',checkpoint_id:'cp'}},
  interrupts:[{id:'i',namespace:'child:1',value:{action_requests:[{name:'bash',args:{command:'echo approved',tags:['first','second']},description:'完整说明'}],
    review_configs:[{action_name:'bash',allowed_decisions:['approve','reject']}]}}]};
const approvalRequestEvent={category:'approval',event_type:'required',seq:3,created_at:date,payload:request};
const encodeFrame=(event,payload)=>new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`);
const createMemoryStorage=()=> {
  const values=new Map();
  return {getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
};
async function waitForState(readStateFn) {
  for(let index=0;index<300;index++) {if(readStateFn())return;await new Promise(resolve=>setImmediate(resolve));}
  assert.fail('公开状态未达到预期');
}
function openWorkbench(storage,options={}) {
  const requests=[];
  let replayController;
  const client=new BackendClient(async(url,init)=> {
    const path=new URL(url).pathname;
    requests.push({path,method:init?.method??'GET',body:init?.body?JSON.parse(init.body):null});
    const status=options.status??'interrupted';
    if(path==='/api/threads') return Response.json({data:[{id:'t',title:null,user_id:null,created_at:date,updated_at:date,run_id:'r',run_status:status},
      {id:'u',title:null,user_id:null,created_at:date,updated_at:date,run_id:null,run_status:null}],next_cursor:null});
    if(path.endsWith('/approval-decisions'))return options.respondToPost?.(requests.at(-1))??new Response('未知提交',{status:500});
    if(path.endsWith('/messages')) return options.respondToHistory?.()??Response.json({data:path.includes('/u/')?[]:[{
      id:1,seq:1,thread_id:'t',run_id:'r',run_status:status,category:'message',event_type:'human_message',event_key:'entry',metadata:{},created_at:date,
      content:{type:'human',message_id:'entry',content:'请执行'}}]});
    if(path.endsWith('/stream'))return options.respondToReplay?.()??new Response(new ReadableStream({start(controller){
      replayController=controller;
      controller.enqueue(encodeFrame('metadata',{thread_id:'t',run_id:'r',status}));
      for(const event of options.events??[approvalRequestEvent])controller.enqueue(encodeFrame('event',event));
      if(!options.holdReplay)controller.close();
    }}),{headers:{'content-type':'text/event-stream'}});
    return options.respondToSnapshot?.()??Response.json({data:{id:'r',thread_id:'t',status}});
  });
  client.update({state:'ready',startup_id:'lease',base_url:'http://127.0.0.1:45200'});
  const store=new ConversationStore({storage});store.setSession(client.session);
  return {store,client,requests,readView:()=>store.getSnapshot().views.t,
    finishReplay:()=>replayController.close(),closeWorkbench:()=>{store.setSession(null);client.update(null);}};
}
const readPosts=workbench=>workbench.requests.filter(request=>request.method==='POST');

test('审批选择与原始原因跨重启保留，全量 GET 正常结束前只读，核实后从不自动 POST',async()=> {
  const storage=createMemoryStorage();
  const originalWorkbench=openWorkbench(storage);
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;
  originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'  完整原因\n'});
  originalWorkbench.closeWorkbench();
  const reopenedWorkbench=openWorkbench(storage,{holdReplay:true});
  try {
    await waitForState(()=>reopenedWorkbench.readView()?.approvalDraft);
    assert.equal(reopenedWorkbench.store.canEditApproval(identity),false);
    reopenedWorkbench.finishReplay();
    await waitForState(()=>reopenedWorkbench.store.canEditApproval(identity));
    assert.deepEqual(reopenedWorkbench.readView().approvalDraft.choices.i,[{type:'reject',reason:'  完整原因\n'}]);
    assert.equal(readPosts(reopenedWorkbench).length,0);
  } finally {reopenedWorkbench.closeWorkbench();}
});

test('旧 pending 重启转未知并保留提交内容；全量核实后只允许人工再提交',async()=> {
  const storage=createMemoryStorage();
  const originalWorkbench=openWorkbench(storage,{respondToPost:()=>new Response(new ReadableStream({start(){}}),{headers:{'content-type':'text/event-stream'}})});
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;
  originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'  捕获提交原文\n'});
  originalWorkbench.store.submitApproval(identity);
  await waitForState(()=>readPosts(originalWorkbench).length===1);
  // 第二个所有者模拟进程消失，不能依赖第一个所有者的中止回调来补保存。
  const reopenedWorkbench=openWorkbench(storage,{holdReplay:true});
  try{
    await waitForState(()=>reopenedWorkbench.readView()?.approvalDraft);
    assert.equal(reopenedWorkbench.readView().write?.phase,'unknown');
    assert.equal(reopenedWorkbench.store.canSubmitApproval(identity),false);
    assert.deepEqual(reopenedWorkbench.store.getSnapshot().approvalBackups[0].submission.responses,{i:{decisions:[{type:'reject',message:'  捕获提交原文\n'}]}});
    reopenedWorkbench.finishReplay();
    await waitForState(()=>reopenedWorkbench.store.canSubmitApproval(identity));
    assert.equal(readPosts(reopenedWorkbench).length,0);
    assert.equal(reopenedWorkbench.readView().write.verified,true);
    assert.equal(reopenedWorkbench.readView().events.r.some(event=>event.event_type==='resolved'),false);
  }finally{originalWorkbench.closeWorkbench();reopenedWorkbench.closeWorkbench();}
});

test('核实失败或目标 404 保留本地选择只读，不造审批历史；恢复后可继续',async()=> {
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage);
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;
  originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'不能丢失'});originalWorkbench.closeWorkbench();
  for(const options of [
    {respondToHistory:()=>new Response('会话不存在',{status:404})},
    {respondToReplay:()=>new Response('运行不存在',{status:404})},
    {respondToReplay:()=>new Response('坏 JSON',{status:200,headers:{'content-type':'text/event-stream'}})},
  ]){
    const workbench=openWorkbench(storage,options);
    try{
      await waitForState(()=>workbench.readView()?.error);
      const backup=workbench.store.getSnapshot().approvalBackups.find(record=>record.draft.identity===identity);
      assert.deepEqual(backup.draft.choices.i,[{type:'reject',reason:'不能丢失'}]);
      assert.equal(workbench.store.canSubmitApproval(identity),false);
      assert.equal(readPosts(workbench).length,0);
    }finally{workbench.closeWorkbench();}
  }
  const finalWorkbench=openWorkbench(storage);
  try{await waitForState(()=>finalWorkbench.store.canEditApproval(identity));assert.equal(finalWorkbench.readView().approvalDraft.choices.i[0].reason,'不能丢失');}
  finally{finalWorkbench.closeWorkbench();}
});

test('对象键顺序等价；checkpoint、namespace、说明、参数数组和 review_configs 改变均不复用选择',async()=> {
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage);
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;
  originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'原请求'});originalWorkbench.closeWorkbench();
  const requestWithReorderedKeys=structuredClone(request);
  requestWithReorderedKeys.interrupts[0].value.action_requests[0].args={tags:['first','second'],command:'echo approved'};
  const equivalentWorkbench=openWorkbench(storage,{events:[{...approvalRequestEvent,payload:requestWithReorderedKeys}]});
  await waitForState(()=>equivalentWorkbench.store.canEditApproval(identity));
  assert.equal(equivalentWorkbench.readView().approvalDraft.choices.i[0].reason,'原请求');equivalentWorkbench.closeWorkbench();
  for(const changeRequest of [
    payload=>payload.checkpoint.configurable.checkpoint_id='different',
    payload=>payload.interrupts[0].id='new-i',
    payload=>payload.interrupts[0].namespace='child:2',
    payload=>payload.interrupts[0].value.action_requests[0].description='修改说明',
    payload=>payload.interrupts[0].value.action_requests[0].args.tags.reverse(),
    payload=>payload.interrupts[0].value.review_configs[0].allowed_decisions.reverse(),
  ]){
    const changedRequest=structuredClone(request);changeRequest(changedRequest);
    const workbench=openWorkbench(storage,{events:[{...approvalRequestEvent,payload:changedRequest}]});
    try{
      await waitForState(()=>workbench.readView()?.approval?.verified);
      assert.notEqual(workbench.readView().approvalDraft.identity,identity);
      assert.deepEqual(Object.values(workbench.readView().approvalDraft.choices).flat(),[{type:null,reason:''}]);
      assert.ok(workbench.store.getSnapshot().approvalBackups.some(record=>record.draft.identity===identity));
      assert.equal(readPosts(workbench).length,0);
    }finally{workbench.closeWorkbench();}
  }
});

test('旧处理记录只清匹配草稿，新 checkpoint 已编辑草稿保留；历史显示实际服务端决策',async()=> {
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage);
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const oldIdentity=originalWorkbench.readView().approvalDraft.identity;
  originalWorkbench.store.chooseApproval(oldIdentity,'i',0,{type:'approve'});originalWorkbench.closeWorkbench();
  const nextRequest=structuredClone(request);nextRequest.checkpoint.configurable.checkpoint_id='next';
  const nextEvent={...approvalRequestEvent,seq:6,payload:nextRequest};
  const reopenedWorkbench=openWorkbench(storage,{events:[nextEvent]});
  await waitForState(()=>reopenedWorkbench.readView()?.approval?.verified);
  const nextIdentity=reopenedWorkbench.readView().approvalDraft.identity;
  reopenedWorkbench.store.chooseApproval(nextIdentity,'i',0,{type:'reject',reason:'新请求输入'});reopenedWorkbench.closeWorkbench();
  const serverResponses={i:{decisions:[{type:'reject',message:'实际被另一客户端拒绝'}]}};
  const resolution={category:'approval',event_type:'resolved',seq:5,created_at:date,
    payload:{status:'resolved',checkpoint:request.checkpoint,responses:serverResponses}};
  const finalWorkbench=openWorkbench(storage,{events:[approvalRequestEvent,resolution,nextEvent]});
  try{
    await waitForState(()=>finalWorkbench.store.canEditApproval(nextIdentity));
    assert.equal(finalWorkbench.readView().approvalDraft.choices.i[0].reason,'新请求输入');
    assert.equal(finalWorkbench.store.getSnapshot().approvalBackups.some(record=>record.draft.identity===oldIdentity),false);
    assert.deepEqual(collectApprovalRecords(finalWorkbench.readView().events)[0].resolution.responses,serverResponses);
    assert.equal(readPosts(finalWorkbench).length,0);
  }finally{finalWorkbench.closeWorkbench();}
});

test('存储写入失败回退内存且输入保留；切换与租约换代仍能核实恢复',async()=> {
  const storage=createMemoryStorage(),workbench=openWorkbench(storage);
  try{
    await waitForState(()=>workbench.readView()?.approval?.verified);
    const identity=workbench.readView().approvalDraft.identity;
    storage.setItem=()=>{throw new Error('磁盘失败');};
    workbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'内存原文'});
    assert.match(workbench.store.getSnapshot().storageIssue,/本地保存不可用/);
    workbench.store.select('u');await waitForState(()=>workbench.store.getSnapshot().views.u?.verified);
    workbench.store.select('t');await waitForState(()=>workbench.store.canEditApproval(identity));
    assert.equal(workbench.readView().approvalDraft.choices.i[0].reason,'内存原文');
    workbench.client.update({state:'ready',startup_id:'next-lease',base_url:'http://127.0.0.1:45201'});
    workbench.store.setSession(workbench.client.session);await waitForState(()=>workbench.store.canEditApproval(identity));
    assert.equal(workbench.readView().approvalDraft.choices.i[0].reason,'内存原文');assert.equal(readPosts(workbench).length,0);
  }finally{workbench.closeWorkbench();}
});

test('接受前网络／500／解析异常保留捕获内容，409／422 详情真实，手动再提交 409 收敛实际处理事实',async()=> {
  for(const createFailureResponse of [
    ()=>{throw new TypeError('网络中断');},
    ()=>new Response('服务端错误',{status:500}),
    ()=>new Response('event: metadata\ndata: broken\n\n',{headers:{'content-type':'text/event-stream'}}),
    ()=>new Response(JSON.stringify({detail:[{loc:['body','responses','i'],msg:'实际校验错误'}]}),{status:422}),
    ()=>new Response('原请求仍在处理中',{status:409}),
  ]){
    const storage=createMemoryStorage();let replayEvents=[approvalRequestEvent],postCount=0;
    const workbench=openWorkbench(storage,{respondToReplay:()=>new Response(replayEvents.map(event=>`event: event\ndata: ${JSON.stringify(event)}\n\n`).join('')
      .replace(/^/,'event: metadata\ndata: {"thread_id":"t","run_id":"r","status":"interrupted"}\n\n'),{headers:{'content-type':'text/event-stream'}}),
      respondToPost:()=>{if(++postCount===1)return createFailureResponse();
        replayEvents=[approvalRequestEvent,{category:'approval',event_type:'resolved',seq:4,created_at:date,
          payload:{status:'resolved',checkpoint:request.checkpoint,responses:{i:{decisions:[{type:'approve'}]}}}}];
        return new Response('迟到原请求已经接受',{status:409});}});
    try{
      await waitForState(()=>workbench.readView()?.approval?.verified);
      const identity=workbench.readView().approvalDraft.identity;workbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'实际提交'});
      workbench.store.submitApproval(identity);await waitForState(()=>workbench.readView().write?.verified);
      assert.equal(readPosts(workbench).length,1);
      assert.equal(workbench.readView().approvalDraft.choices.i[0].reason,'实际提交');
      assert.ok(workbench.readView().write.failure.message);
      if(workbench.readView().write.failure.status===422)assert.match(workbench.readView().write.failure.detail,/实际校验错误/);
      workbench.store.chooseApproval(identity,'i',0,{reason:'新的人工输入'});
      assert.equal(workbench.store.getSnapshot().approvalBackups[0].submission.responses.i.decisions[0].message,'实际提交');
      assert.equal(workbench.store.submitApproval(identity),true);
      await waitForState(()=>collectApprovalRecords(workbench.readView().events)[0]?.resolution);
      assert.equal(workbench.store.canSubmitApproval(identity),false);
      assert.equal(workbench.store.getSnapshot().approvalBackups.length,0);
      assert.equal(readPosts(workbench).length,2);
      assert.equal(collectApprovalRecords(workbench.readView().events)[0].resolution.responses.i.decisions[0].type,'approve');
    }finally{workbench.closeWorkbench();}
  }
});

test('已接受但还未读到 resolved 的旧决策跨重启保持锁定，断流后只 GET',async()=> {
  const storage=createMemoryStorage();let postController;
  const originalWorkbench=openWorkbench(storage,{respondToPost:()=>new Response(new ReadableStream({start(controller){postController=controller;}}),
    {headers:{'content-type':'text/event-stream'}})});
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;originalWorkbench.store.chooseApproval(identity,'i',0,{type:'approve'});originalWorkbench.store.submitApproval(identity);
  await waitForState(()=>postController);
  postController.enqueue(encodeFrame('metadata',{thread_id:'t',run_id:'r',status:'running'}));
  await waitForState(()=>originalWorkbench.readView().acceptedApproval===identity);
  const reopenedWorkbench=openWorkbench(storage);
  try{
    await waitForState(()=>reopenedWorkbench.readView()?.approval?.verified);
    assert.equal(reopenedWorkbench.readView().acceptedApproval,identity);
    assert.equal(reopenedWorkbench.store.canEditApproval(identity),false);
    assert.equal(reopenedWorkbench.store.canSubmitApproval(identity),false);
    assert.equal(readPosts(reopenedWorkbench).length,0);
  }finally{originalWorkbench.closeWorkbench();reopenedWorkbench.closeWorkbench();}
});

test('503 Retry-After 跨重启保留，不能用切换／手动核实绕过等待',async t=> {
  t.mock.timers.enable({apis:['Date','setTimeout'],now:Date.parse(date)});
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage,{respondToPost:()=>new Response('稍后再试',{status:503,headers:{'Retry-After':'10'}})});
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;originalWorkbench.store.chooseApproval(identity,'i',0,{type:'approve'});originalWorkbench.store.submitApproval(identity);
  await waitForState(()=>originalWorkbench.readView().write?.phase==='unknown');originalWorkbench.closeWorkbench();
  const reopenedWorkbench=openWorkbench(storage);
  try{
    await waitForState(()=>reopenedWorkbench.readView()?.history==='ready');
    assert.equal(reopenedWorkbench.requests.filter(request=>request.path.endsWith('/stream')).length,0);
    reopenedWorkbench.store.queryStatus();
    t.mock.timers.tick(9999);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(reopenedWorkbench.requests.filter(request=>request.path.endsWith('/stream')).length,0);
    t.mock.timers.tick(1);await waitForState(()=>reopenedWorkbench.store.canSubmitApproval(identity));
    assert.equal(readPosts(reopenedWorkbench).length,0);
  }finally{reopenedWorkbench.closeWorkbench();}
});

test('已核实后编辑保留捕获版本，422 原始校验详情跨退出和重开不被连接停止提示覆盖',async()=> {
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage,{respondToPost:()=>new Response('实际字段 responses.i 错误',{status:422})});
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'提交时原因'});
  originalWorkbench.store.submitApproval(identity);await waitForState(()=>originalWorkbench.readView().write?.verified);
  const submissionRecord=originalWorkbench.store.getSnapshot().approvalBackups[0].submission;
  originalWorkbench.store.chooseApproval(identity,'i',0,{reason:'核实后继续编辑'});originalWorkbench.closeWorkbench();
  const reopenedWorkbench=openWorkbench(storage);
  try{
    await waitForState(()=>reopenedWorkbench.store.canSubmitApproval(identity));
    const backup=reopenedWorkbench.store.getSnapshot().approvalBackups[0];
    assert.equal(backup.draft.choices.i[0].reason,'核实后继续编辑');
    assert.ok(backup.draft.version>submissionRecord.draftVersion);
    assert.deepEqual(backup.submission.responses,{i:{decisions:[{type:'reject',message:'提交时原因'}]}});
    assert.equal(reopenedWorkbench.readView().write.failure.status,422);
    assert.match(reopenedWorkbench.readView().write.failure.detail,/实际字段 responses.i 错误/);
    assert.equal(readPosts(reopenedWorkbench).length,0);
  }finally{reopenedWorkbench.closeWorkbench();}
});

test('隐藏只停旧请求；旧 POST 迟到不能确认人工新提交或清掉新版本选择',async()=> {
  const storage=createMemoryStorage();let releaseOldPost,newPostController,postCount=0;
  const workbench=openWorkbench(storage,{respondToPost:()=>++postCount===1?new Promise(resolve=>releaseOldPost=resolve)
    :new Response(new ReadableStream({start(controller){newPostController=controller;}}),{headers:{'content-type':'text/event-stream'}})});
  try{
    await waitForState(()=>workbench.readView()?.approval?.verified);
    const identity=workbench.readView().approvalDraft.identity;workbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'旧提交'});
    workbench.store.submitApproval(identity);await waitForState(()=>releaseOldPost);
    workbench.store.setVisible(false);
    assert.equal(workbench.store.getSnapshot().approvalBackups[0].submission.status,'unknown');
    workbench.store.setVisible(true);await waitForState(()=>workbench.store.canSubmitApproval(identity));
    workbench.store.chooseApproval(identity,'i',0,{reason:'新人工决策'});workbench.store.submitApproval(identity);await waitForState(()=>newPostController);
    const currentSubmission=workbench.store.getSnapshot().approvalBackups[0].submission;
    releaseOldPost(new Response('event: metadata\ndata: {"thread_id":"t","run_id":"r","status":"running"}\n\n',
      {headers:{'content-type':'text/event-stream'}}));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(workbench.readView().acceptedApproval,null);
    assert.equal(workbench.readView().write.phase,'pending');
    assert.equal(workbench.store.getSnapshot().approvalBackups[0].submission.id,currentSubmission.id);
    assert.equal(workbench.readView().approvalDraft.choices.i[0].reason,'新人工决策');
    assert.equal(readPosts(workbench).length,2);
    newPostController.enqueue(encodeFrame('metadata',{thread_id:'t',run_id:'r',status:'running'}));
    await waitForState(()=>workbench.readView().acceptedApproval===identity);
  }finally{workbench.closeWorkbench();}
});

test('全量 GET 核实后快照报告 Run 404，当前输入立即转只读保留，不能沿用旧提交资格',async()=> {
  const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage);
  await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
  const identity=originalWorkbench.readView().approvalDraft.identity;originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'目标失效仍保留'});originalWorkbench.closeWorkbench();
  const reopenedWorkbench=openWorkbench(storage,{respondToSnapshot:()=>new Response('运行已不可读取',{status:404})});
  try{
    await waitForState(()=>reopenedWorkbench.readView()?.queryFailure?.status===404);
    assert.equal(reopenedWorkbench.store.canSubmitApproval(identity),false);
    assert.equal(reopenedWorkbench.store.canCancel(),false);
    assert.equal(reopenedWorkbench.readView().approvalDraft.choices.i[0].reason,'目标失效仍保留');
    assert.equal(readPosts(reopenedWorkbench).length,0);
  }finally{reopenedWorkbench.closeWorkbench();}
});

test('处理事件缺少完整 required 身份时保留本地输入只读，不能仅凭 checkpoint 清理',async()=> {
  for(const status of ['resolved','invalidated']){
    const storage=createMemoryStorage(),originalWorkbench=openWorkbench(storage);
    await waitForState(()=>originalWorkbench.readView()?.approval?.verified);
    const identity=originalWorkbench.readView().approvalDraft.identity;
    originalWorkbench.store.chooseApproval(identity,'i',0,{type:'reject',reason:'缺少原请求仍保留'});originalWorkbench.closeWorkbench();
    const resolution={category:'approval',event_type:status,seq:5,created_at:date,payload:status==='resolved'
      ?{status,checkpoint:request.checkpoint,responses:{i:{decisions:[{type:'approve'}]}}}
      :{status,checkpoint:request.checkpoint,interrupt_ids:['i'],reason:'run_cancelled'}};
    const reopenedWorkbench=openWorkbench(storage,{events:[resolution]});
    try{
      await waitForState(()=>reopenedWorkbench.readView()?.observation==='closed');
      const backup=reopenedWorkbench.store.getSnapshot().approvalBackups.find(record=>record.draft.identity===identity);
      assert.equal(backup?.draft.choices.i[0].reason,'缺少原请求仍保留');
      assert.equal(reopenedWorkbench.store.canSubmitApproval(identity),false);
      assert.equal(readPosts(reopenedWorkbench).length,0);
    }finally{reopenedWorkbench.closeWorkbench();}
  }
});
