import test from 'node:test';
import assert from 'node:assert/strict';
import { ChatReadingPositions, readingHistoryReady, sameTimelineLayout, movedBeyondLayoutClamp } from '../src/chat-reading-position.ts';

// 浏览器布局边界：已测量的锚点/滚动尺寸，不伪造应用内部模块。
const frame = (scrollTop = 0, anchors = [{id:'a', top:20}, {id:'b', top:400}, {id:'c', top:800}]) =>
  ({scrollTop, height:200, total:1100, anchors});
const content = new Map([['a', '甲'], ['b', '乙'], ['c', '丙']]);

test('首次最新，切回按会话锚点恢复；新的应用内存不恢复旧像素', () => {
  const reading = new ChatReadingPositions();
  assert.equal(reading.reconcile('one', frame(), content, true).scrollTop, 900);
  reading.userScroll('one', frame(450), 'up');
  assert.equal(reading.reconcile('two', frame(), content, true).scrollTop, 900);
  const changed = frame(0, [{id:'a', top:20}, {id:'b', top:600}, {id:'c', top:1000}]);
  assert.equal(reading.reconcile('one', changed, content, true).scrollTop, 650);
  assert.equal(reading.reconcile('one', changed, content, true).following, false);
  assert.equal(new ChatReadingPositions().reconcile('one', changed, content, true).scrollTop, 900);
});

test('暂缺锚点等待事实恢复，确认失效后选择同会话最近内容，隐藏不覆盖记录', () => {
  const reading = new ChatReadingPositions();
  reading.reconcile('one', frame(), content, true);
  reading.userScroll('one', frame(450), 'up');
  const partial = {...frame(0, [{id:'a', top:20}, {id:'c', top:700}]), total:1000};
  assert.equal(reading.reconcile('one', partial, content, false).scrollTop, null);
  assert.equal(reading.reconcile('one', {...partial, height:0}, content, true).scrollTop, null);
  assert.equal(reading.reconcile('one', frame(), content, true).scrollTop, 450);
  assert.equal(reading.reconcile('one', partial, content, true).scrollTop, 70);
  // 即使不同会话共享同一消息 ID，也不继承 one 的阅读模式或位置。
  assert.equal(reading.reconcile('other', partial, content, true).scrollTop, 800);
});

test('上翻即停，即使离底部很近；真实内容变化只提示一次，重复事实和布局不造数量', () => {
  const reading = new ChatReadingPositions();
  reading.reconcile('one', frame(), content, true);
  reading.userScroll('one', frame(899), 'up');
  const next = new Map(content); next.set('c', '丙\n继续生成');
  const growing = {...frame(899), total:1400};
  assert.deepEqual(reading.reconcile('one', growing, next, true),
    {scrollTop:899, following:false, hasNewContent:true});
  assert.equal(reading.reconcile('one', growing, new Map(next), true).scrollTop, 899);
  assert.equal(reading.latest('one', growing).scrollTop, 1200);
  assert.equal(reading.reconcile('one', growing, next, true).hasNewContent, false);
  reading.userScroll('one', frame(450), 'up');
  const layout = {...frame(450, [{id:'a', top:100}, {id:'b', top:600}, {id:'c', top:1100}]), total:1600};
  assert.deepEqual(reading.reconcile('one', layout, next, true),
    {scrollTop:650, following:false, hasNewContent:false});
  reading.userScroll('one', {...layout, scrollTop:1400}, 'down');
  assert.equal(reading.reconcile('one', {...layout, total:1700}, next, true).scrollTop, 1500);
});

test('仅新的本次发送接受恢复跟随；已经处理的接受信息重入不抢阅读位置', () => {
  const reading = new ChatReadingPositions();
  reading.reconcile('one', frame(), content, true);
  reading.userScroll('one', frame(450), 'up');
  assert.equal(reading.reconcile('one', frame(450), content, true, 'send-one').scrollTop, 900);
  reading.userScroll('one', frame(450), 'up');
  assert.equal(reading.reconcile('one', frame(), content, true, 'send-one').scrollTop, 450);
  assert.equal(reading.reconcile('one', frame(), content, true, 'send-two').scrollTop, 900);
});

test('同一完整事实的对象键顺序变化不提示新内容，数组内容变化仍提示', () => {
  const reading = new ChatReadingPositions();
  reading.reconcile('one', frame(), new Map([['a', {text:'原文', fields:[0, false]}]]), true);
  reading.userScroll('one', frame(450), 'up');
  const replay = new Map([['a', {fields:[0, false], text:'原文'}]]);
  assert.equal(reading.reconcile('one', frame(450), replay, true).hasNewContent, false);
  const changed = new Map([['a', {fields:[false, 0], text:'原文'}]]);
  assert.equal(reading.reconcile('one', frame(450), changed, true).hasNewContent, true);
});

test('切换前记住已发生但尚未递送 scroll 事件的真实位置，保留原暂停模式', () => {
  const reading = new ChatReadingPositions();
  reading.reconcile('one', frame(), content, true);
  reading.userScroll('one', frame(0), 'up');
  reading.remember('one', frame(450));
  assert.equal(reading.reconcile('one', frame(), content, true).scrollTop, 450);
  assert.equal(reading.reconcile('one', frame(), content, true).following, false);
});

test('metadata 核实身份不表示消息已重建；连接或重试时等待缺锚点，读取结束后才失效落点', () => {
  const view = {history:'ready', verified:true, observation:'open'};
  assert.equal(readingHistoryReady(view), false);
  for (const observation of ['connecting','retry_wait','paused','failed'])
    assert.equal(readingHistoryReady({...view, observation}), false);
  for (const observation of ['idle','closed'])
    assert.equal(readingHistoryReady({...view, observation}), true);
  assert.equal(readingHistoryReady({...view, history:'loading', observation:'closed'}), false);
  assert.equal(readingHistoryReady({...view, verified:false, observation:'closed'}), false);
});

test('布局变化与用户滚动分开：纯滚动尺寸不变，宽高、内容增高及锚点移动都需先恢复偏移', () => {
  assert.equal(sameTimelineLayout(frame(0), frame(450)), true);
  assert.equal(sameTimelineLayout(frame(), {...frame(), height:400}), false);
  assert.equal(sameTimelineLayout(frame(), {...frame(), total:1400}), false);
  assert.equal(sameTimelineLayout(frame(), frame(0, [{id:'a',top:20},{id:'b',top:410},{id:'c',top:800}])), false);
  assert.equal(sameTimelineLayout(frame(), frame(0, [{id:'a',top:20},{id:'new',top:400},{id:'c',top:800}])), false);
});

test('有输入意图时先采集迟到滚动，浏览器布局夹紧仍保留旧阅读锚点', () => {
  assert.equal(movedBeyondLayoutClamp(frame(450), frame(449)), true);
  assert.equal(movedBeyondLayoutClamp(frame(450), frame(450)), false);
  assert.equal(movedBeyondLayoutClamp(frame(900), {...frame(600), total:800}), false);
  assert.equal(movedBeyondLayoutClamp(frame(900), {...frame(700), height:400}), false);
  assert.equal(movedBeyondLayoutClamp(frame(0), {...frame(450), total:1101}), true);
});
