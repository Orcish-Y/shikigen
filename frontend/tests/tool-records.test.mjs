import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Conversation } from '../src/components/Conversation.tsx';
import { presentMessage } from '../src/message-presentation.ts';
import { ToolCardPreferences } from '../src/tool-card-preferences.ts';
import { RunProjection } from '../src/run-projection.ts';

const saved = (seq, content, run = 'run', thread = 'thread') => ({
  id:seq, seq, run_id:run, thread_id:thread, run_status:'completed',
  category:'message', event_type:'created', event_key:null, metadata:{},
  created_at:'2026-10-05T01:00:00Z', content,
});
const ai = (seq, calls, run = 'run', thread = 'thread') => saved(seq,
  {type:'ai', message_id:`ai-${seq}`, content:'', tool_calls:calls}, run, thread);
const tool = (seq, id, content, extra = {}, run = 'run', thread = 'thread') => saved(seq,
  {type:'tool', message_id:`tool-${seq}`, tool_call_id:id, status:'success', content, ...extra}, run, thread);
const call = id => ({id, name:'read_file', args:{path:`${id}.txt`}});
const render = (records, extra = {}) => renderToStaticMarkup(React.createElement(Conversation, {
  session:{id:'thread', title:'测试会话', group:'今天', summary:'', messages:records.map(presentMessage)},
  onSuggestion:() => {}, onView:() => {}, ...extra,
}));

test('工具结果只关联唯一身份，按调用顺序，保留两条完整事实和 seq', () => {
  const records = [ai(1, [call('a'), call('b')]), tool(2, 'b', '结果 B'), tool(3, 'a', '结果 A')];
  const html = render(records);
  assert.equal((html.match(/class="tool-block/g) ?? []).length, 2);
  assert.equal((html.match(/class="message assistant"/g) ?? []).length, 1);
  assert.ok(html.indexOf('a.txt') < html.indexOf('b.txt'));
  assert.ok(html.indexOf('结果 A') < html.indexOf('结果 B'));
  assert.match(html, /调用 seq：1/);
  assert.match(html, /结果 seq：3/);
  assert.match(html, /结果 seq：2/);
  assert.match(html, /已返回/);
  assert.doesNotMatch(html, /未找到对应调用/);
});

test('同名不猜配、跨运行或会话不串入，重复调用及重复结果独立保留', () => {
  for (const records of [
    [ai(1, [call('a')]), tool(2, 'b', '未匹配结果')],
    [ai(1, [call('a')]), tool(2, 'a', '另一次运行', {}, 'other')],
    [ai(1, [call('a')]), tool(2, 'a', '另一个会话', {}, 'run', 'other')],
    [ai(1, [call('a'), call('a')]), tool(2, 'a', '重复调用')],
    [ai(1, [call('a')]), tool(2, 'a', '重复结果1'), tool(3, 'a', '重复结果2')],
  ]) {
    const html = render(records);
    assert.match(html, /未找到对应调用/);
    assert.match(html, /等待结果/);
    assert.match(html, /所属运行已结束/);
  }
  const earlier = render([tool(1, 'a', '先到结果'), ai(2, [call('a')])]);
  assert.doesNotMatch(earlier, /未找到对应调用/);
  assert.match(earlier, /结果 seq：1/);
});

test('标题状态只看真实工具 status；空正文已返回，记录名称和所有额外字段可读', () => {
  const html = render([ai(1, [call('a'), call('b')]),
    tool(2, 'a', 'Error: 仍然是成功返回', {name:'returned_name', custom:{keep:false}}),
    tool(3, 'b', '', {status:'error', name:null}),
  ]);
  assert.equal((html.match(/>工具失败</g) ?? []).length, 1);
  assert.equal((html.match(/>已返回</g) ?? []).length, 1);
  assert.match(html, /已返回，正文为空/);
  assert.match(html, /returned_name/);
  assert.match(html, /&quot;keep&quot;: false/);
  assert.match(html, /class="tool-status tool-error"/);
  assert.match(render([tool(1, 'orphan', [])]), /已返回，正文为空/);
});

test('附加数据包括所有非 null 空值，省略和 null 不创建附加区', () => {
  for (const artifact of ['', 0, false, [], {}, {file:'image.png', values:[null, 0, false]}]) {
    const html = render([tool(1, 'a', '', {artifact})]);
    assert.match(html, /附加数据/);
    assert.match(html, /附加数据 JSON|附加数据原文/);
    assert.doesNotMatch(html.slice(html.indexOf('<div class="tool-block"')), /<img| href=| src=|批准|拒绝/);
  }
  for (const extra of [{}, {artifact:null}]) assert.doesNotMatch(render([tool(1, 'a', '', extra)]), />附加数据</);
});

test('默认折叠，失败首次只展开卡片和结果；手动收起和再次进入均保留选择', () => {
  const preferences = new ToolCardPreferences();
  const id = 'thread/run/seq/call';
  assert.equal(preferences.read(id, false).card, false);
  preferences.observeFailure(id, true);
  assert.equal(preferences.read(id, true).card, true);
  assert.equal(preferences.read(id, true).result, true);
  assert.equal(preferences.read(id, true).parameters, false);
  assert.equal(preferences.read(id, true).artifact, false);
  preferences.toggle(id, 'card', true);
  preferences.toggle(id, 'result', true);
  preferences.observeFailure(id, true);
  preferences.observeFailure(id, true);
  assert.equal(preferences.read(id, true).card, false);
  assert.equal(preferences.read(id, true).result, false);
  const records = [ai(1, [call('a')]), tool(2, 'a', '失败内容', {status:'error'})];
  const initial = render(records);
  assert.match(initial, /class="tool-summary" aria-expanded="true"/);
  assert.match(initial, /aria-expanded="true"[^>]*>结果正文/);
  assert.match(initial, /aria-expanded="false"[^>]*>参数/);
  assert.equal(new ToolCardPreferences().read(id, true).card, true, '重启使用新的应用内偏好');
  const manual = new ToolCardPreferences();
  manual.toggle(id, 'card', false); // 打开等待卡片
  manual.toggle(id, 'card', false); // 用户主动收起
  manual.observeFailure(id, true);
  assert.equal(manual.read(id, true).card, false);
});

test('当前及历史运行已结束仍等待结果，metadata 不改写原消息 seq 和 content', () => {
  const projection = new RunProjection();
  const record = ai(1, [call('a')]);
  record.run_status = 'running';
  const original = structuredClone(record);
  projection.mergeHistory([record]);
  projection.metadata({thread_id:'thread', run_id:'run', status:'cancelled'});
  projection.metadata({thread_id:'thread', run_id:'new', status:'running'});
  const snapshot = projection.snapshot();
  const html = render(snapshot.messages, {session:{id:'thread', title:'测试', group:'今天', summary:'',
    messages:snapshot.messages.map(presentMessage), runStatuses:snapshot.runStatuses}});
  assert.match(html, /等待结果/);
  assert.match(html, /所属运行已结束（已取消）/);
  assert.doesNotMatch(html, />工具失败</);
  assert.deepEqual(record, original);
  assert.deepEqual(snapshot.messages, [original]);
});
