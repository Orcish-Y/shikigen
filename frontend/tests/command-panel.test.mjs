import assert from 'node:assert/strict';
import test from 'node:test';
import { listCommands, moveCommandSelection, resolveSelectedCommand } from '../src/command-panel.ts';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const context = {
  conversations: [
    {id:'first', title:'第一条 中文任务', status:'运行中', summary:'刚刚'},
    {id:'second', title:'Report Alpha', status:'已完成', summary:'2 天前'},
    {id:'third', title:'Report Alpha', status:'等待审批', summary:'昨天'},
  ],
  isDesktop:true, isNavigationCollapsed:false,
  createUnavailableReason:null, detailsUnavailableReason:'尚未开始运行',
};

test('command projection uses only loaded display titles and preserves independent duplicate identities', () => {
  const choices = listCommands(context, '');
  assert.equal(choices.length, 7);
  assert.deepEqual(choices.slice(4).map(choice=>[choice.id,choice.label,choice.action.conversationId]), [
    ['conversation:first','第一条 中文任务','first'],
    ['conversation:second','Report Alpha','second'],
    ['conversation:third','Report Alpha','third'],
  ]);
  assert.equal(choices[4].description, '运行中 · 刚刚');
  assert.equal(choices[3].unavailableReason, '尚未开始运行');
  assert.equal(choices[0].shortcut, 'N');
  assert.equal(choices[1].shortcut, 'B');
});

test('search is case insensitive and matches only action names and titles, never ids or auxiliary facts', () => {
  assert.deepEqual(listCommands(context, '  ALPHA ').map(choice=>choice.id), ['conversation:second','conversation:third']);
  assert.equal(listCommands(context, '中文')[0].id, 'conversation:first');
  assert.equal(listCommands(context, '运行详情')[0].id, 'run-details');
  for (const query of ['first', '运行中', '刚刚', '2 天前', '不存在的标题']) {
    assert.deepEqual(listCommands(context, query), []);
    assert.equal(resolveSelectedCommand(listCommands(context, query), 'create-conversation'), null);
    assert.equal(moveCommandSelection(listCommands(context, query), null, 'next'), null);
  }
});

test('navigation name reflects the same desktop choice and uses an explicit narrow screen action', () => {
  assert.equal(listCommands(context, '')[1].label, '收起主导航');
  assert.equal(listCommands({...context,isNavigationCollapsed:true}, '')[1].label, '展开主导航');
  assert.equal(listCommands({...context,isDesktop:false}, '')[1].label, '打开主导航');
});

test('selection skips disabled options and recovers when a title, filter or availability changes', () => {
  const choices = listCommands({...context,createUnavailableReason:'正在创建会话，请稍候'}, '');
  assert.equal(resolveSelectedCommand(choices, null).id, 'toggle-navigation');
  assert.equal(resolveSelectedCommand(choices, 'create-conversation').id, 'toggle-navigation');
  assert.equal(resolveSelectedCommand(choices, 'conversation:second').id, 'conversation:second');
  assert.equal(resolveSelectedCommand(listCommands(context, '中文'), 'conversation:second').id, 'conversation:first');
  const disabledChoices = listCommands(context, '运行详情');
  assert.equal(disabledChoices.length, 1);
  assert.equal(resolveSelectedCommand(disabledChoices, null), null);
  assert.equal(moveCommandSelection(disabledChoices, null, 'previous'), null);
});

test('arrows wrap available choices and do not select disabled items in either direction', () => {
  const choices = listCommands(context, '');
  assert.equal(moveCommandSelection(choices, null, 'next'), 'create-conversation');
  assert.equal(moveCommandSelection(choices, null, 'previous'), 'conversation:third');
  assert.equal(moveCommandSelection(choices, 'find-conversation', 'next'), 'conversation:first');
  assert.equal(moveCommandSelection(choices, 'conversation:first', 'previous'), 'find-conversation');
  assert.equal(moveCommandSelection(choices, 'conversation:third', 'next'), 'create-conversation');
  assert.equal(moveCommandSelection(choices, 'create-conversation', 'previous'), 'conversation:third');
});

test('empty loaded list still shows action reasons and never invents a conversation', () => {
  const choices = listCommands({...context,conversations:[],createUnavailableReason:'后端未连接'}, '');
  assert.equal(choices.length, 4);
  assert.equal(choices[0].unavailableReason, '后端未连接');
  assert.deepEqual(choices.map(choice=>choice.group), ['actions','actions','actions','actions']);
});

test('shared creation qualification blocks no lease, hidden workspace, list reads and pending duplicate writes', async () => {
  let releaseList, releaseCreation;
  let postCount = 0;
  let listCount = 0;
  const client = new BackendClient(async (url, request) => {
    if (request.method === 'POST') {
      postCount++;
      return new Promise(resolve => { releaseCreation = resolve; });
    }
    if (url.endsWith('/messages')) return Response.json({data:[]});
    listCount++;
    if (listCount === 1) return new Promise(resolve => { releaseList = resolve; });
    return Response.json({data:[], next_cursor:null});
  });
  const store = new ConversationStore();
  const waitFor = async checkReadiness => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (checkReadiness()) return;
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.fail('creation state did not settle');
  };
  try {
    assert.equal(store.canCreate(), false);
    client.update({revision:1,startup_id:'commands',base_url:'http://127.0.0.1:4100',state:'ready',can_retry:false,error:null});
    store.setSession(client.session);
    await waitFor(() => releaseList);
    assert.equal(store.canCreate(), false);
    releaseList(Response.json({data:[],next_cursor:null}));
    await waitFor(() => !store.getSnapshot().listing);
    assert.equal(store.canCreate(), true);
    store.setVisible(false);
    assert.equal(store.canCreate(), false);
    await store.create();
    assert.equal(postCount, 0);
    store.setVisible(true);
    await waitFor(() => listCount >= 2 && !store.getSnapshot().listing);
    const creationRequest = store.create();
    await waitFor(() => releaseCreation);
    assert.equal(store.canCreate(), false);
    await store.create();
    assert.equal(postCount, 1);
    releaseCreation(Response.json({thread_id:'created-from-command'}));
    await creationRequest;
    assert.equal(store.canCreate(), true);
    client.update(null);
    assert.equal(store.canCreate(), false);
  } finally {
    store.setSession(null); client.update(null);
  }
});
