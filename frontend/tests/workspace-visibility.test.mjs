import test from 'node:test';
import assert from 'node:assert/strict';
import { subscribeWorkspaceVisibility } from '../src/workspace-visibility.ts';

const tick = () => new Promise(resolve => setImmediate(resolve));
test('subscribe before querying; newer visibility events win over a late query', async () => {
  let receive, resolveQuery, stopped = 0;
  const seen = [];
  const subscription = subscribeWorkspaceVisibility({
    listen: async callback => {receive = callback; return () => stopped++;},
    query: () => {assert.ok(receive); return new Promise(resolve => resolveQuery = resolve);},
  }, value => seen.push(value), error => assert.fail(String(error)));
  await tick();
  receive({revision:2, visible:false});
  resolveQuery({revision:1, visible:true});
  await tick();
  receive({revision:2, visible:true});
  receive({revision:3, visible:true});
  assert.deepEqual(seen, [{revision:2, visible:false}, {revision:3, visible:true}]);
  subscription.dispose();
  receive({revision:4, visible:false});
  assert.equal(seen.length, 2);
  assert.equal(stopped, 1);
});

test('query failure retains the known event; first failure leaves the visible fallback unchanged', async () => {
  for (const event of [null, {revision:1, visible:false}]) {
    let value = true, errors=0, receive;
    const subscription = subscribeWorkspaceVisibility({
      listen:async callback => {receive=callback; if(event) callback(event); return () => {};},
      query:async () => {throw new Error('原生查询失败');},
    }, snapshot => value=snapshot.visible, () => errors++);
    await tick();
    assert.equal(value, event ? false : true);
    assert.equal(errors, 1);
    receive({revision:2, visible:true});
    assert.equal(value, true, '查询失败不撤销已订阅事件');
    subscription.dispose();
  }
});

test('disposal during subscription removes the late listener without querying', async () => {
  let resolveListen, stopped=0;
  const subscription = subscribeWorkspaceVisibility({
    listen:() => new Promise(resolve => resolveListen=resolve),
    query:() => assert.fail('卸载后不可查询'),
  }, () => assert.fail('卸载后不可更新'), () => {});
  subscription.dispose();
  resolveListen(() => stopped++);
  await tick();
  assert.equal(stopped, 1);
});
