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
  cancel(); receive(snapshot(5)); assert.deepEqual(seen, [3,4]); assert.equal(stopped, 1);
});
test('unmount during subscription releases the late listener and does not query', async () => {
  let resolveListen; let stopped = 0;
  const cancel = subscribeBackendState({listen: () => new Promise(resolve => resolveListen = resolve), query: () => assert.fail('query after unmount')}, () => assert.fail('late update'), () => {});
  cancel(); resolveListen(() => stopped++);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stopped, 1);
});
