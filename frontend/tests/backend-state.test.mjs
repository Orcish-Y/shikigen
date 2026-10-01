import test from 'node:test';
import assert from 'node:assert/strict';
import { subscribeBackendState } from '../src/backend-state.ts';
const snapshot = (revision, state = 'starting') => ({revision, state, startup_id:'one', base_url:null, can_retry:false, error:null});

test('subscribe before querying and ignore an older query result', async () => {
  const seen = []; let receive; let resolveQuery; let stopped = 0;
  const cancel = subscribeBackendState({
    listen: async (callback) => { receive = callback; return () => stopped++; },
    query: () => { assert.ok(receive); return new Promise(resolve => resolveQuery = resolve); },
  }, value => seen.push(value.revision), error => assert.fail(String(error)));
  await new Promise(resolve => setImmediate(resolve));
  receive(snapshot(3, 'ready')); resolveQuery(snapshot(2));
  await new Promise(resolve => setImmediate(resolve));
  receive(snapshot(3)); receive(snapshot(1)); receive(snapshot(4, 'failed'));
  assert.deepEqual(seen, [3,4]);
  cancel.dispose(); receive(snapshot(5)); assert.deepEqual(seen, [3,4]); assert.equal(stopped, 1);
});
test('unmount during subscription releases the late listener and does not query', async () => {
  let resolveListen; let stopped = 0;
  const cancel = subscribeBackendState({listen: () => new Promise(resolve => resolveListen = resolve), query: () => assert.fail('query after unmount')}, () => assert.fail('late update'), () => {});
  cancel.dispose(); resolveListen(() => stopped++);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stopped, 1);
});

test('retry results, old events and an outstanding query cannot overwrite the new attempt', async () => {
  const seen = []; let receive; let queryDone; let retryDone;
  const subscription = subscribeBackendState({
    listen: async callback => { receive = callback; return () => {}; },
    query: () => new Promise(resolve => queryDone = resolve),
    retry: () => new Promise(resolve => retryDone = resolve),
  }, value => seen.push([value.revision, value.startup_id]), error => assert.fail(String(error)));
  await new Promise(resolve => setImmediate(resolve));
  receive({...snapshot(4, 'failed'), can_retry:true});
  const pending = subscription.retry();
  receive({...snapshot(6, 'ready'), startup_id:'two', base_url:'http://127.0.0.1:45230'});
  retryDone({accepted:true, reason:null, snapshot:{...snapshot(5), startup_id:'two'}});
  assert.equal(await pending, null); // Stale command feedback is also ignored.
  queryDone(snapshot(2));
  receive(snapshot(4, 'failed'));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(seen, [[4, 'one'], [6, 'two']]);
  subscription.dispose();
});

test('a refused retry applies the manager snapshot and exposes its reason', async () => {
  const seen = [];
  const subscription = subscribeBackendState({
    listen: async () => () => {},
    query: async () => ({...snapshot(4, 'failed'), can_retry:true}),
    retry: async () => ({accepted:false, reason:'应用正在退出，不能重试', snapshot:snapshot(5, 'stopped')}),
  }, value => seen.push(value), error => assert.fail(String(error)));
  await new Promise(resolve => setImmediate(resolve));
  const reply = await subscription.retry();
  assert.equal(reply.accepted, false);
  assert.match(reply.reason, /退出/);
  assert.equal(seen.at(-1).can_retry, false);
  assert.equal(seen.at(-1).state, 'stopped');
  subscription.dispose();
});

test('unmount while retry is pending suppresses the reply and later commands', async () => {
  let done;
  const subscription = subscribeBackendState({
    listen: async () => () => {},
    query: async () => snapshot(4, 'failed'),
    retry: () => new Promise(resolve => done = resolve),
  }, () => {}, error => assert.fail(String(error)));
  await new Promise(resolve => setImmediate(resolve));
  const reply = subscription.retry();
  subscription.dispose();
  done({accepted:true, reason:null, snapshot:snapshot(5)});
  assert.equal(await reply, null);
  assert.equal(await subscription.retry(), null);
});
