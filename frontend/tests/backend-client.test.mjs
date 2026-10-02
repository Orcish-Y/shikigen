import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { BackendClient } from '../src/backend-client.ts';
import { subscribeBackendState } from '../src/backend-state.ts';

const ready = (revision, startup_id, base_url) => ({revision, startup_id, base_url, state:'ready', can_retry:false, error:null});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function server(t, handler) {
  const http = createServer(handler).listen(0, '127.0.0.1');
  await once(http, 'listening');
  t.after(() => { http.closeAllConnections(); http.close(); });
  return `http://127.0.0.1:${http.address().port}`;
}

test('host query races cannot restore an old address; leaving ready closes SSE and rejects old sessions', async t => {
  let closed; const disconnected = new Promise(resolve => closed = resolve);
  const oldUrl = await server(t, (req, res) => {
    if (req.url.endsWith('/stream')) {
      res.writeHead(200, {'content-type':'text/event-stream'});
      res.write('event: metadata\ndata: {"thread_id":"t","run_id":"r","status":"running"}\n\n');
      res.on('close', closed);
    } else res.end(JSON.stringify([{id:'old-thread'}]));
  });
  const newUrl = await server(t, (req, res) => res.end(JSON.stringify([{id:'persisted-thread'}])));
  const client = new BackendClient();
  let receive, queryDone;
  const subscription = subscribeBackendState({
    listen: async callback => { receive = callback; return () => {}; },
    query: () => new Promise(resolve => queryDone = resolve),
  }, state => client.update(state), error => assert.fail(String(error)));
  t.after(() => { subscription.dispose(); client.update(null); });
  await tick();
  assert.equal(client.session, null);
  receive(ready(2, 'old', oldUrl));
  const old = client.session;
  assert.equal((await old.threads())[0].id, 'old-thread');
  let first; const received = new Promise(resolve => first = resolve);
  const stream = old.observe('t', 'r', first).catch(error => error);
  await received;
  receive({...ready(3, 'old', null), state:'failed'});
  assert.equal(client.session, null);
  assert.equal(old.signal.aborted, true);
  await assert.rejects(old.threads(), {name:'AbortError'});
  await disconnected;
  assert.equal((await stream).name, 'AbortError');
  receive(ready(5, 'new', newUrl));
  queryDone(ready(2, 'old', oldUrl));
  await tick();
  assert.equal((await client.session.threads())[0].id, 'persisted-thread');
});

test('delayed JSON and SSE headers from a revoked startup are discarded and released', async () => {
  let jsonDone, headersDone, cancelled = false;
  const client = new BackendClient(async url => {
    if (url.endsWith('/messages')) return {
      ok:true, json: () => new Promise(resolve => jsonDone = resolve),
    };
    return new Promise(resolve => headersDone = resolve);
  });
  client.update(ready(1, 'old', 'http://127.0.0.1:1'));
  const old = client.session;
  const messages = old.messages('t').catch(error => error);
  const events = [];
  const stream = old.observe('t', 'r', frame => events.push(frame)).catch(error => error);
  await tick();
  client.update(ready(3, 'new', 'http://127.0.0.1:2'));
  jsonDone({data:[{content:{content:'stale history'}}]});
  headersDone(new Response(new ReadableStream({cancel() { cancelled = true; }}), {
    headers:{'content-type':'text/event-stream'},
  }));
  assert.equal((await messages).name, 'AbortError');
  assert.equal((await stream).name, 'AbortError');
  assert.deepEqual(events, []);
  assert.equal(cancelled, true);
  client.update(null);
});

test('queued SSE frames cannot publish after revocation, even within the same network chunk', async () => {
  const bytes = new TextEncoder().encode(
    'event: metadata\r\ndata: {"status":"running"}\r\n\r\n' +
    'event: delta\ndata: {"value":"旧启动迟到事件"}\n\n');
  let cancelled = false;
  const client = new BackendClient(async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(bytes); },
    cancel() { cancelled = true; },
  }), {headers:{'content-type':'text/event-stream'}}));
  client.update(ready(1, 'old', 'http://127.0.0.1:1'));
  const seen = [];
  await assert.rejects(client.session.observe('t', 'r', frame => {
    seen.push(frame.event);
    client.update(ready(3, 'new', 'http://127.0.0.1:2'));
  }), {name:'AbortError'});
  assert.deepEqual(seen, ['metadata']);
  assert.equal(cancelled, true);
  client.update(null);
});
