import test from 'node:test';
import assert from 'node:assert/strict';
import { parseApproval, createApprovalDraft, updateApprovalChoice, buildApprovalResponses, createApprovalIdentity, collectApprovalRecords } from '../src/approval-decisions.ts';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const request = {
  status:'required', checkpoint:{configurable:{thread_id:'t', checkpoint_ns:'', checkpoint_id:'cp'}},
  interrupts:[
    {id:'i-a', namespace:'', value:{action_requests:[
      {name:'bash', args:{command:'first'}, description:'先审核'},
      {name:'bash', args:{command:'second'}},
    ], review_configs:[
      {action_name:'bash', allowed_decisions:['approve','reject']},
      {action_name:'bash', allowed_decisions:['reject']},
    ]}},
    {id:'i-b', namespace:'child:1', value:{action_requests:[{name:'write_file', args:{path:'report.md'}}],
      review_configs:[{action_name:'write_file', allowed_decisions:['approve','reject','edit']}]}},
  ],
};

test('多 Interrupt 默认未选，全选后按服务端动作顺序提交；批准不携带原因',()=> {
  const requestModel = parseApproval(request);
  assert.equal(requestModel.issue, null);
  assert.equal(requestModel.total, 3);
  assert.deepEqual(requestModel.interrupts.map(interrupt=>interrupt.namespace), ['', 'child:1']);
  let draft = createApprovalDraft('r', request);
  assert.equal(buildApprovalResponses(draft), null);
  draft = updateApprovalChoice(draft, 'i-b', 0, {type:'approve'});
  draft = updateApprovalChoice(draft, 'i-a', 1, {type:'reject', reason:'  保留原文\n'});
  draft = updateApprovalChoice(draft, 'i-a', 0, {type:'reject', reason:'暂时拒绝'});
  draft = updateApprovalChoice(draft, 'i-a', 0, {type:'approve'});
  assert.equal(draft.choices['i-a'][0].reason, '暂时拒绝');
  assert.deepEqual(buildApprovalResponses(draft), {
    'i-a':{decisions:[{type:'approve'}, {type:'reject', message:'  保留原文\n'}]},
    'i-b':{decisions:[{type:'approve'}]},
  });
  draft = updateApprovalChoice(draft, 'i-a', 1, {reason:' \n '});
  assert.deepEqual(buildApprovalResponses(draft)['i-a'].decisions[1], {type:'reject'});
});

const date = '2026-10-06T00:00:00Z';
const approvalRequestEvent = {category:'approval', event_type:'required', seq:5, created_at:date, payload:request};
const encodeRunFrame = (event, framePayload)=>new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(framePayload)}\n\n`);
async function waitForState(readStateFn) {
  for (let index=0;index<200;index++) {if (readStateFn()) return; await new Promise(resolve=>setImmediate(resolve));}
  assert.fail('公开状态未达到预期');
}
async function createWorkbench(respondToPost, options={}) {
  let postStream, status='interrupted', reads=0, snapshots=0;
  const posts=[];
  const client = new BackendClient(async (url, init)=> {
    const path = new URL(url).pathname;
    if (path === '/api/threads') return Response.json({data:[{id:'t', title:null, user_id:null,
      created_at:date, updated_at:date, run_id:'r', run_status:status},
      {id:'u', title:null, user_id:null, created_at:date, updated_at:date, run_id:null, run_status:null}], next_cursor:null});
    if (path.endsWith('/approval-decisions')) {
      posts.push({path, body:JSON.parse(init.body)});
      return respondToPost?.({setStatus:value=>status=value}) ?? new Response(new ReadableStream({start(controller) {postStream=controller;}}),
        {headers:{'content-type':'text/event-stream'}});
    }
    if (path.endsWith('/messages')) return Response.json({data:path.includes('/u/') ? [] : [{id:2, seq:2, thread_id:'t', run_id:'r', run_status:status,
      category:'message', event_type:'human_message', event_key:'human:entry', metadata:{}, created_at:date,
      content:{type:'human', message_id:'entry', content:'请执行'}}]});
    if (path.endsWith('/stream')) {
      reads++;
      return new Response(new ReadableStream({start(controller) {
        controller.enqueue(encodeRunFrame('metadata', {thread_id:'t', run_id:'r', status}));
        for (const event of options.replayEventsFn?.(reads) ?? [approvalRequestEvent]) controller.enqueue(encodeRunFrame('event', event));
        controller.close();
      }}), {headers:{'content-type':'text/event-stream'}});
    }
    return options.readSnapshotFn?.(++snapshots) ?? Response.json({data:{id:'r', thread_id:'t', status}});
  });
  client.update({state:'ready', startup_id:'lease', base_url:'http://127.0.0.1:45200'});
  const store = new ConversationStore({storage:null}); store.setSession(client.session);
  await waitForState(()=>store.getSnapshot().views.t?.approval?.verified);
  return {store, posts, readPostStream:()=>postStream, readObservationCount:()=>reads, setStatus:value=>status=value,
    readView:()=>store.getSnapshot().views.t, closeWorkbench:()=>{store.setSession(null); client.update(null);}};
}

function chooseAll(app) {
  const identity=app.readView().approvalDraft.identity;
  app.store.chooseApproval(identity, 'i-a', 0, {type:'approve'});
  app.store.chooseApproval(identity, 'i-a', 1, {type:'reject', reason:'  请保留\n'});
  app.store.chooseApproval(identity, 'i-b', 0, {type:'approve'});
  return identity;
}

test('全部选完一次 POST；pending 锁编辑／取消，本次有效 metadata 即解锁而不等 EOF', async()=> {
  const app = await createWorkbench();
  try {
    const identity = app.readView().approvalDraft.identity;
    assert.equal(app.store.canSubmitApproval(identity), false);
    app.store.chooseApproval(identity, 'i-a', 0, {type:'approve'});
    assert.equal(app.store.submitApproval(identity), false);
    app.store.chooseApproval(identity, 'i-a', 1, {type:'reject', reason:'  不覆盖\n'});
    app.store.chooseApproval(identity, 'i-b', 0, {type:'approve'});
    assert.equal(app.store.submitApproval(identity), true);
    await waitForState(()=>app.posts.length === 1);
    assert.equal(app.store.submitApproval(identity), false);
    assert.equal(app.store.canCancel(), false);
    assert.equal(app.store.chooseApproval(identity, 'i-a', 0, {type:'reject'}), false);
    assert.deepEqual(app.posts[0].body, {responses:{
      'i-a':{decisions:[{type:'approve'}, {type:'reject', message:'  不覆盖\n'}]},
      'i-b':{decisions:[{type:'approve'}]},
    }});
    assert.equal(app.readView().write.phase, 'pending');
    app.readPostStream().enqueue(encodeRunFrame('metadata', {thread_id:'t', run_id:'r', status:'running'}));
    await waitForState(()=>app.readView().write === null);
    assert.equal(app.store.canCancel(), true);
    assert.equal(app.store.canSubmitApproval(identity), false);
    assert.equal(app.readView().events.r.filter(event=>event.event_type === 'resolved').length, 0);
    app.readPostStream().enqueue(encodeRunFrame('event', {category:'approval', event_type:'resolved', seq:7, created_at:date,
      payload:{status:'resolved', checkpoint:request.checkpoint, responses:app.posts[0].body.responses}}));
    await waitForState(()=>app.readView().events.r.some(event=>event.event_type === 'resolved'));
    assert.equal(app.readView().run.status, 'running', '拒绝动作不把运行变成 cancelled');
  } finally {app.closeWorkbench();}
});

test('同一 Run 新 checkpoint 的全部动作重新选择；POST 暂停后自动 GET 才开放', async()=> {
  let replayEvents=[approvalRequestEvent];
  const app=await createWorkbench(undefined, {replayEventsFn:()=>replayEvents});
  try {
    const oldIdentity=chooseAll(app); app.store.submitApproval(oldIdentity);
    await waitForState(()=>app.posts.length===1);
    const nextRequest=structuredClone(request);
    nextRequest.checkpoint.configurable.checkpoint_id='next-cp';
    const resolution={category:'approval',event_type:'resolved',seq:7,created_at:date,
      payload:{status:'resolved',checkpoint:request.checkpoint,responses:app.posts[0].body.responses}};
    const nextApprovalRequestEvent={...approvalRequestEvent,seq:9,payload:nextRequest};
    replayEvents=[approvalRequestEvent,resolution,nextApprovalRequestEvent];
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'r',status:'running'}));
    app.readPostStream().enqueue(encodeRunFrame('event',resolution));
    app.readPostStream().enqueue(encodeRunFrame('event',nextApprovalRequestEvent));
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'r',status:'interrupted'}));
    await waitForState(()=>app.readView().approvalDraft?.request.checkpoint.configurable.checkpoint_id==='next-cp');
    const identity=app.readView().approvalDraft.identity;
    assert.notEqual(identity,oldIdentity);
    assert.equal(app.store.canEditApproval(identity),false,'POST 回放不是 GET 身份校验');
    app.readPostStream().close();
    await waitForState(()=>app.store.canEditApproval(identity));
    assert.deepEqual(Object.values(app.readView().approvalDraft.choices).flat().map(choice=>choice.type),[null,null,null]);
    assert.equal(app.store.canSubmitApproval(identity),false);
    assert.equal(app.store.canSubmitApproval(oldIdentity),false);
    assert.equal(app.posts.length,1); assert.equal(app.readObservationCount(),2);
  } finally {app.closeWorkbench();}
});

test('错误 Run metadata 不能确认接受，先 GET 核实才开放原请求', async()=> {
  const app=await createWorkbench();
  try {
    const identity=chooseAll(app); app.store.submitApproval(identity);
    await waitForState(()=>app.posts.length===1);
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'foreign',status:'running'}));
    await waitForState(()=>app.readView().write?.verified);
    assert.equal(app.readView().acceptedApproval,null);
    assert.equal(app.readView().run.run_id,'r');
    assert.equal(app.readView().write.phase,'unknown');
    assert.ok(app.readView().protocolIssue);
    assert.equal(app.store.canSubmitApproval(identity),true);
    assert.equal(app.posts.length,1); assert.equal(app.readObservationCount(),2);
  } finally {app.closeWorkbench();}
});

test('未知提交经正常全量 GET 已核实，后续快照失败不撤销这次审批资格', async()=> {
  const app=await createWorkbench(()=>new Response('校验未通过',{status:422}), {
    readSnapshotFn:count=>count > 1 ? new Response('补充快照读取失败',{status:500}) : undefined,
  });
  try {
    const identity=chooseAll(app); app.store.submitApproval(identity);
    await waitForState(()=>app.readView().queryFailure);
    assert.equal(app.readView().approval.verified,true);
    assert.equal(app.store.canSubmitApproval(identity),true);
    assert.equal(app.store.canCancel(),true);
    assert.equal(app.posts.length,1); assert.equal(app.readObservationCount(),2);
  } finally {app.closeWorkbench();}
});

test('不支持或不可解析的动作使整组只读，原始内容保留且仍可取消', async()=> {
  for (const updateRequestFn of [
    payload=>payload.interrupts[1].value.review_configs[0].allowed_decisions=['edit'],
    payload=>delete payload.interrupts[1].value.action_requests[0].args,
    payload=>payload.interrupts[1].value.review_configs=[],
    payload=>payload.interrupts[1].value='未知审批格式',
  ]) {
    const payload=structuredClone(request); updateRequestFn(payload);
    const app=await createWorkbench(undefined, {replayEventsFn:()=>[{...approvalRequestEvent,payload}]});
    try {
      const identity=app.readView().approvalDraft.identity;
      assert.ok(parseApproval(payload).issue);
      assert.deepEqual(app.readView().approval.request.payload, payload);
      assert.equal(app.store.chooseApproval(identity, 'i-a', 0, {type:'approve'}), false);
      assert.equal(app.store.submitApproval(identity), false);
      assert.equal(app.store.canCancel(), true);
      assert.equal(app.posts.length, 0);
    } finally {app.closeWorkbench();}
  }
});

test('请求内容键次序不改变身份，参数／namespace／checkpoint／动作顺序改变身份',()=> {
  const reorderedRequest=structuredClone(request);
  reorderedRequest.interrupts[0].value.action_requests[0]={description:'先审核', args:{command:'first'}, name:'bash'};
  assert.equal(createApprovalIdentity('r',reorderedRequest),createApprovalIdentity('r',request));
  for (const updateRequestFn of [
    payload=>payload.interrupts[0].namespace='child',
    payload=>payload.checkpoint.configurable.checkpoint_id='next',
    payload=>payload.interrupts[0].value.action_requests.reverse(),
    payload=>payload.interrupts[0].value.action_requests[0].args.command='changed',
  ]) {
    const payload=structuredClone(request); updateRequestFn(payload);
    assert.notEqual(createApprovalIdentity('r',payload),createApprovalIdentity('r',request));
  }
});

test('422 和未确认的 500 均保留选择，完整 GET 核实后才能手动重提，不造 resolved', async()=> {
  for (const status of [422,500]) {
    const app=await createWorkbench(()=>new Response('服务端原始校验详情', {status}));
    try {
      const identity=chooseAll(app), choicesBeforeSubmission=structuredClone(app.readView().approvalDraft.choices);
      assert.equal(app.store.submitApproval(identity),true);
      await waitForState(()=>app.readView().write?.verified);
      assert.equal(app.readObservationCount(),2); assert.equal(app.posts.length,1);
      assert.equal(app.readView().write.phase,'unknown');
      assert.equal(app.readView().write.failure.status,status);
      assert.deepEqual(app.readView().approvalDraft.choices,choicesBeforeSubmission);
      assert.equal(app.store.canSubmitApproval(identity),true);
      assert.equal(app.store.canCancel(),true);
      assert.equal(app.readView().events.r.length,1);
    } finally {app.closeWorkbench();}
  }
});

test('旧 GET metadata 不确认 POST；隐藏结束 pending，旧 POST 响应不影响新选择', async()=> {
  const app=await createWorkbench();
  try {
    const identity=chooseAll(app);
    app.store.submitApproval(identity); await waitForState(()=>app.posts.length === 1);
    await app.store.queryStatus();
    assert.equal(app.readView().write.phase,'pending'); assert.equal(app.readObservationCount(),1);
    app.store.select('u'); await waitForState(()=>app.store.getSnapshot().views.u?.verified);
    assert.equal(app.readView().write.phase,'unknown');
    assert.equal(app.store.getSnapshot().views.u.run,null);
    assert.equal(app.posts.length,1);
    app.store.select('t'); await waitForState(()=>app.readView().approval?.verified);
    await waitForState(()=>app.readView().write?.verified);
    assert.equal(app.readView().acceptedApproval,null);
    assert.equal(app.store.canSubmitApproval(identity),true);
    assert.equal(app.posts.length,1);
  } finally {app.closeWorkbench();}
});

test('503 的 Retry-After 同时限制核实和重提；确认结果前互斥', async t=> {
  t.mock.timers.enable({apis:['Date','setTimeout'],now:Date.parse(date)});
  const app=await createWorkbench(()=>new Response('稍后再试',{status:503,headers:{'Retry-After':'10'}}));
  try {
    const identity=chooseAll(app); app.store.submitApproval(identity);
    await waitForState(()=>app.readView().write?.phase === 'unknown');
    assert.equal(app.readObservationCount(),1); assert.equal(app.store.canSubmitApproval(identity),false);
    assert.equal(app.store.canCancel(),false);
    t.mock.timers.tick(9999); await new Promise(resolve=>setImmediate(resolve)); assert.equal(app.readObservationCount(),1);
    t.mock.timers.tick(1); await waitForState(()=>app.readView().write?.verified);
    assert.equal(app.readObservationCount(),2); assert.equal(app.posts.length,1);
    assert.equal(app.store.canSubmitApproval(identity),true);
  } finally {app.closeWorkbench();}
});

test('resolved 显示服务端真实决策；终态和迟到 running 永不重新开放旧审批', async()=> {
  const app=await createWorkbench();
  try {
    const identity=chooseAll(app); app.store.submitApproval(identity); await waitForState(()=>app.posts.length === 1);
    const actualResponses={'i-a':{decisions:[{type:'reject', message:'另一客户端实际拒绝'},{type:'reject'}]}, 'i-b':{decisions:[{type:'approve'}]}};
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'r',status:'cancelled'}));
    await waitForState(()=>app.readView().run.status === 'cancelled');
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'r',status:'running'}));
    app.readPostStream().enqueue(encodeRunFrame('event',{category:'approval',event_type:'resolved',seq:7,created_at:date,
      payload:{status:'resolved',checkpoint:request.checkpoint,responses:actualResponses}}));
    await waitForState(()=>app.readView().events.r.length===2);
    assert.equal(app.readView().run.status,'cancelled'); assert.equal(app.readView().write,null);
    assert.equal(app.store.canSubmitApproval(identity),false);
    assert.equal(app.store.canCancel(),false);
    assert.deepEqual(collectApprovalRecords(app.readView().events)[0].resolution.responses,actualResponses);
  } finally {app.closeWorkbench();}
});

test('终态只有状态时保持只读，手动 GET 读取真实失效记录，不重发决策', async()=> {
  const invalidationEvent={category:'approval',event_type:'invalidated',seq:8,created_at:date,
    payload:{status:'invalidated',checkpoint:request.checkpoint,interrupt_ids:['i-a','i-b'],reason:'run_cancelled'}};
  const app=await createWorkbench(undefined, {replayEventsFn:readCount=>readCount === 1
    ? [approvalRequestEvent] : [approvalRequestEvent,invalidationEvent]});
  try {
    const identity=chooseAll(app); app.store.submitApproval(identity);
    await waitForState(()=>app.posts.length === 1);
    assert.equal(app.store.canReconnect(),false);
    app.setStatus('cancelled');
    app.readPostStream().enqueue(encodeRunFrame('metadata',{thread_id:'t',run_id:'r',status:'cancelled'}));
    app.readPostStream().close();
    await waitForState(()=>app.store.canReconnect());
    assert.equal(collectApprovalRecords(app.readView().events)[0].resolution,null);
    assert.equal(app.store.canSubmitApproval(identity),false);
    app.store.reconnect();
    await waitForState(()=>collectApprovalRecords(app.readView().events)[0].resolution?.status === 'invalidated');
    assert.equal(app.posts.length,1);
    assert.equal(app.readObservationCount(),2);
    assert.equal(app.readView().run.status,'cancelled');
    assert.equal(app.store.canCancel(),false);
  } finally {app.closeWorkbench();}
});
