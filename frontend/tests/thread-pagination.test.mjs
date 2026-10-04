import assert from 'node:assert/strict';
import test from 'node:test';
import { BackendClient } from '../src/backend-client.ts';
import { ConversationStore } from '../src/conversation-state.ts';

const instant = '2026-10-04T00:00:00.000Z';
const later = '2026-10-04T00:01:00.000Z';
const ready = { revision: 1, startup_id: 'pagination-test', base_url: 'http://127.0.0.1:8123',
  state: 'ready', can_retry: false, error: null };
const summary = (id, overrides = {}) => ({ id, user_id: 'user-1', title: id,
  created_at: instant, updated_at: instant, run_id: null, run_status: null, ...overrides });
const page = (data, next_cursor = null) => ({ data, next_cursor });
const encode = value => new TextEncoder().encode(value);

function makeStore(fetcher) {
  const client = new BackendClient(fetcher);
  client.update(ready);
  const store = new ConversationStore();
  store.setSession(client.session);
  return { client, store };
}

async function waitFor(predicate, message = 'condition was not reached') {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail(message);
}

function listUrl(input) { return new URL(input).pathname === '/api/threads'; }
function json(response) { return Response.json(response); }
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('requested page size controls the query and response limit', async () => {
  const urls = [];
  const client = new BackendClient(async input => {
    urls.push(new URL(input));
    return json(page(Array.from({ length: 21 }, (_, index) => summary(String(index)))));
  });
  client.update(ready);
  const result = await client.session.threads(25, undefined, 'cursor /?&');
  assert.equal(result.data.length, 21, 'responses larger than 20 are valid when requested');
  assert.equal(urls[0].searchParams.get('limit'), '25');
  assert.equal(urls[0].searchParams.get('cursor'), 'cursor /?&');
  await assert.rejects(client.session.threads(3), /格式无效/);
  const requested = urls.length;
  for (const invalid of [undefined, 0, -1, 1.5, NaN, Infinity, true, '20']) {
    await assert.rejects(client.session.threads(invalid), /正整数/);
  }
  assert.equal(urls.length, requested, 'invalid page sizes do not send requests');
  client.update(null);
});

test('thread pages encode cursors and reject malformed or oversized responses', async () => {
  const urls = [];
  const client = new BackendClient(async (input, init) => {
    urls.push({ url: new URL(input), init });
    return json(page([summary('same-time')], 'opaque-token'));
  });
  client.update(ready);
  await client.session.threads(20, undefined, 'cursor /?&');
  assert.equal(urls[0].url.searchParams.get('cursor'), 'cursor /?&');
  assert.equal(urls[0].init.cache, 'no-store');

  for (const invalid of [
    { data: [], next_cursor: undefined },
    { data: [], next_cursor: 4 },
    { data: Array.from({ length: 21 }, (_, index) => summary(String(index))), next_cursor: null },
    { data: [summary('missing-time', { updated_at: 'not a date' })], next_cursor: null },
    { data: [summary('partial-run', { run_id: 'run-1', run_status: null })], next_cursor: null },
    { data: [summary('unknown-run', { run_id: 'run-1', run_status: 'queued' })], next_cursor: null },
  ]) {
    const malformed = new BackendClient(async () => json(invalid));
    malformed.update(ready);
    await assert.rejects(malformed.session.threads(20), /格式无效|字段或运行状态无效/);
  }
});

test('raw 20-item duplicate pages keep the cursor moving; short raw pages end pagination', async () => {
  const first = Array.from({ length: 20 }, (_, index) => summary(`t-${String(index).padStart(2, '0')}`));
  let olderReads = 0;
  const requests = [];
  const { client, store } = makeStore(async (input) => {
    const url = new URL(input);
    requests.push(url.searchParams.get('cursor'));
    if (listUrl(input)) {
      assert.equal(url.searchParams.get('limit'), '20', 'the frontend chooses its page size');
      if (!url.searchParams.has('cursor')) return json(page(first, 'older/0'));
      olderReads++;
      if (url.searchParams.get('cursor') === 'older/0') {
        return json(page(Array.from({ length: 20 }, () => first[0]), 'older/1'));
      }
      return json(page([first[0]], 'server-sent-but-short'));
    }
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  store.select('t-01');
  await waitFor(() => store.getSnapshot().views['t-01']?.history === 'ready');
  store.updateDraft('草稿要保留');

  await store.loadMore();
  assert.equal(store.getSnapshot().threads.length, 20, 'duplicate IDs should be merged');
  assert.equal(store.getSnapshot().nextCursor, 'older/1', 'raw page size controls continuation');
  assert.equal(store.getSnapshot().activeId, 't-01');
  assert.equal(store.getSnapshot().drafts['t-01'], '草稿要保留');

  await store.loadMore();
  assert.equal(olderReads, 2);
  assert.equal(requests.at(-1), 'older/1', 'a zero-new-item page must still permit the next request');
  assert.equal(store.getSnapshot().threads.length, 20);
  assert.equal(store.getSnapshot().nextCursor, null, 'a short raw page ends pagination despite a supplied cursor');
  assert.equal(store.getSnapshot().activeId, 't-01');
  assert.equal(store.getSnapshot().drafts['t-01'], '草稿要保留');
  client.update(null);
});

test('first-page refresh merges without deleting older rows, resetting cursor, or regressing timestamps', async () => {
  const initial = Array.from({ length: 20 }, (_, index) => summary(`t-${String(index).padStart(2, '0')}`));
  initial[10] = summary('t-10', { title: 'current title', updated_at: later });
  const older = Array.from({ length: 20 }, (_, index) => summary(`old-${String(index).padStart(2, '0')}`));
  let firstReads = 0;
  const { client, store } = makeStore(async input => {
    if (listUrl(input)) {
      const url = new URL(input);
      if (url.searchParams.has('cursor')) return json(page(older, 'cursor-after-older'));
      firstReads++;
      if (firstReads === 1) return json(page(initial, 'cursor-before-older'));
      return json(page([
        summary('new-first-row', { updated_at: later }),
        summary('t-10', { title: 'stale title', updated_at: instant }),
      ], 'new-first-cursor'));
    }
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  store.select('t-10');
  await waitFor(() => store.getSnapshot().views['t-10']?.history === 'ready');
  store.updateDraft('keep this draft');
  await store.loadMore();
  assert.equal(store.getSnapshot().threads.length, 40);
  const cursorBeforeRefresh = store.getSnapshot().nextCursor;

  await store.refreshThreads();
  const state = store.getSnapshot();
  assert.equal(state.nextCursor, cursorBeforeRefresh, 'a first-page poll must preserve established progress');
  assert.ok(state.threads.some(item => item.id === 'old-19'), 'older loaded rows remain when absent from page one');
  assert.ok(state.threads.some(item => item.id === 'new-first-row'), 'new IDs from page one are inserted');
  const retained = state.threads.find(item => item.id === 't-10');
  assert.equal(retained.title, 'current title');
  assert.equal(retained.updated_at, later);
  assert.equal(state.activeId, 't-10');
  assert.equal(state.drafts['t-10'], 'keep this draft');
  client.update(null);
});

test('equal timestamps use descending ID order after merges', async () => {
  const { client, store } = makeStore(async input => {
    if (listUrl(input)) return json(page([summary('a'), summary('c'), summary('b')], null));
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  assert.deepEqual(store.getSnapshot().threads.map(item => item.id), ['c', 'b', 'a']);
  client.update(null);
});

test('current same-run metadata wins over an older list projection that completes later', async () => {
  let pushFrame;
  let refresh;
  const { client, store } = makeStore(async input => {
    const url = new URL(input);
    if (url.pathname === '/api/threads') {
      if (url.searchParams.has('cursor')) return json(page([], null));
      if (!refresh) return json(page([summary('t', { run_id: 'run-1', run_status: 'running' })], null));
      return refresh.promise;
    }
    if (url.pathname.endsWith('/messages')) {
      return json({ data: [{ id: 1, thread_id: 't', run_id: 'run-1', run_status: 'running', seq: 1 }] });
    }
    if (url.pathname.endsWith('/runs/run-1/stream')) {
      return new Response(new ReadableStream({ start(controller) {
        pushFrame = frame => controller.enqueue(encode(`event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`));
      } }), { headers: { 'content-type': 'text/event-stream' } });
    }
    assert.fail(`unexpected request ${url}`);
  });
  await waitFor(() => typeof pushFrame === 'function');
  pushFrame({ event: 'metadata', data: { thread_id: 't', run_id: 'run-1', status: 'running' } });
  await waitFor(() => store.getSnapshot().threads[0]?.run_status === 'running');

  refresh = deferred();
  const refreshResult = store.refreshThreads();
  await waitFor(() => store.getSnapshot().listing);
  pushFrame({ event: 'metadata', data: { thread_id: 't', run_id: 'run-1', status: 'completed' } });
  await waitFor(() => store.getSnapshot().threads[0]?.run_status === 'completed');
  refresh.resolve(json(page([summary('t', { run_id: 'run-1', run_status: 'running', updated_at: later })], null)));
  await refreshResult;
  assert.equal(store.getSnapshot().threads[0].run_id, 'run-1');
  assert.equal(store.getSnapshot().threads[0].run_status, 'completed');
  client.update(null);
});

test('new-run metadata is not replaced by a list request already in flight', async () => {
  let pushFrame;
  const refresh = deferred();
  let firstPage = true;
  const { client, store } = makeStore(async (input, init) => {
    const url = new URL(input);
    if (url.pathname === '/api/threads') {
      if (url.searchParams.has('cursor')) return json(page([], null));
      if (firstPage) { firstPage = false; return json(page([summary('t')], null)); }
      return refresh.promise;
    }
    if (url.pathname.endsWith('/messages')) return json({ data: [] });
    if (url.pathname === '/api/threads/t/stream' && init.method === 'POST') {
      return new Response(new ReadableStream({ start(controller) {
        pushFrame = frame => controller.enqueue(encode(`event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`));
      } }), { headers: { 'content-type': 'text/event-stream' } });
    }
    assert.fail(`unexpected request ${url}`);
  });
  await waitFor(() => store.getSnapshot().views.t?.verified);
  const refreshResult = store.refreshThreads();
  await waitFor(() => store.getSnapshot().listing);
  assert.equal(store.send('新任务'), true);
  await waitFor(() => typeof pushFrame === 'function');
  pushFrame({ event: 'metadata', data: { thread_id: 't', run_id: 'new-run', status: 'running' } });
  await waitFor(() => store.getSnapshot().threads[0]?.run_id === 'new-run');
  refresh.resolve(json(page([summary('t', { updated_at: later })], null)));
  await refreshResult;
  assert.equal(store.getSnapshot().threads[0].run_id, 'new-run');
  assert.equal(store.getSnapshot().threads[0].run_status, 'running');
  client.update(null);
});

test('page failures are explicit, honor both Retry-After forms, and do not auto-retry', async () => {
  let pageRequests = 0;
  const retryDate = new Date(Date.now() + 60_000).toUTCString();
  const { client, store } = makeStore(async input => {
    const url = new URL(input);
    if (listUrl(input) && !url.searchParams.has('cursor')) return json(page(Array.from({ length: 20 }, (_, index) => summary(`t-${index}`)), 'cursor'));
    if (url.searchParams.get('cursor') === 'cursor') {
      pageRequests++;
      if (pageRequests === 1) return new Response('busy', { status: 503, headers: { 'Retry-After': '2' } });
      return new Response('still busy', { status: 503, headers: { 'Retry-After': retryDate } });
    }
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  const beforeSeconds = Date.now();
  await store.loadMore();
  const secondsError = store.getSnapshot().pageError;
  assert.equal(pageRequests, 1);
  assert.ok(secondsError.retryAt >= beforeSeconds + 1900 && secondsError.retryAt <= beforeSeconds + 2500);
  await store.loadMore(true);
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(pageRequests, 1, 'a failed sentinel must not retry by itself or before the deadline');

  const originalNow = Date.now;
  try {
    const fakeNow = secondsError.retryAt + 1;
    Date.now = () => fakeNow;
    await store.loadMore(true);
    assert.equal(pageRequests, 2);
    assert.ok(store.getSnapshot().pageError.retryAt >= Date.parse(retryDate) - 1000,
      'HTTP-date Retry-After should be retained as an absolute deadline');
    await store.loadMore(true);
    assert.equal(pageRequests, 2, 'HTTP-date cooldown blocks an early retry');
  } finally {
    Date.now = originalNow;
    client.update(null);
  }
});

test('422 pagination errors stop cursor retries until an explicit first-page reload', async () => {
  let firstReads = 0;
  let pageReads = 0;
  const { client, store } = makeStore(async input => {
    const url = new URL(input);
    if (url.pathname === '/api/threads') {
      if (!url.searchParams.has('cursor')) {
        firstReads++;
        return json(page(Array.from({ length: 20 }, (_, index) => summary(`t-${index}`)), `cursor-${firstReads}`));
      }
      pageReads++;
      return new Response('expired cursor', { status: 422 });
    }
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  await store.loadMore();
  assert.equal(store.getSnapshot().pageError.invalidCursor, true);
  await store.loadMore(true);
  assert.equal(pageReads, 1);
  await store.reloadThreads();
  assert.equal(firstReads, 2);
  assert.equal(store.getSnapshot().pageError, null);
  assert.equal(store.getSnapshot().nextCursor, 'cursor-2');
  client.update(null);
});

test('failed first-page reload keeps rows, selected conversation, and its draft', async () => {
  let firstReads = 0;
  const { client, store } = makeStore(async input => {
    if (listUrl(input)) {
      if (new URL(input).searchParams.has('cursor')) return json(page([], null));
      firstReads++;
      if (firstReads === 1) return json(page([summary('t')], null));
      return new Response('offline', { status: 503, headers: { 'Retry-After': '1' } });
    }
    return json({ data: [] });
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  await waitFor(() => store.getSnapshot().views.t?.history === 'ready');
  store.updateDraft('draft');
  const before = store.getSnapshot().threads;
  await store.reloadThreads();
  const state = store.getSnapshot();
  assert.deepEqual(state.threads, before);
  assert.equal(state.activeId, 't');
  assert.equal(state.drafts.t, 'draft');
  assert.match(state.listError.message, /读取会话列表失败/);
  assert.equal(state.listError.retryAt > Date.now(), true);
  client.update(null);
});

test('a non-reset first-page refresh and an older-page request can finish in either order', async () => {
  const olderResponse = deferred();
  const refreshResponse = deferred();
  const older = Array.from({ length: 20 }, (_, index) => summary(`older-${index}`));
  let firstReads = 0;
  const { client, store } = makeStore(async input => {
    const url = new URL(input);
    if (url.pathname !== '/api/threads') return json({ data: [] });
    if (url.searchParams.has('cursor')) return olderResponse.promise;
    firstReads++;
    if (firstReads === 1) return json(page(Array.from({ length: 20 }, (_, index) => summary(`first-${index}`)), 'cursor-0'));
    return refreshResponse.promise;
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  const moreRequest = store.loadMore();
  await waitFor(() => store.getSnapshot().loadingMore);
  const firstPageRequest = store.refreshThreads();
  await waitFor(() => store.getSnapshot().listing);

  olderResponse.resolve(json(page(older, 'cursor-1')));
  await moreRequest;
  assert.equal(store.getSnapshot().nextCursor, 'cursor-1');
  refreshResponse.resolve(json(page([summary('new-first-row', { updated_at: later })], 'ignored-refresh-cursor')));
  await firstPageRequest;

  const state = store.getSnapshot();
  assert.equal(state.nextCursor, 'cursor-1');
  assert.ok(state.threads.some(item => item.id === 'new-first-row'));
  assert.ok(state.threads.some(item => item.id === 'older-19'));
  client.update(null);
});

test('resetting while an older page is in flight ignores the revoked page response', async () => {
  const older = deferred();
  let firstReads = 0;
  const { client, store } = makeStore(async input => {
    const url = new URL(input);
    if (url.pathname !== '/api/threads') return json({ data: [] });
    if (url.searchParams.has('cursor')) return older.promise;
    firstReads++;
    if (firstReads === 1) return json(page(Array.from({ length: 20 }, (_, index) => summary(`t-${index}`)), 'old-cursor'));
    return json(page(Array.from({ length: 20 }, (_, index) => summary(`fresh-${index}`)), 'fresh-cursor'));
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  const oldRequest = store.loadMore();
  await waitFor(() => store.getSnapshot().loadingMore);
  await store.reloadThreads();
  assert.equal(store.getSnapshot().nextCursor, 'fresh-cursor');
  older.resolve(json(page([summary('stale-older-row')], 'stale-cursor')));
  await oldRequest;
  assert.equal(store.getSnapshot().threads.some(item => item.id === 'stale-older-row'), false);
  assert.equal(store.getSnapshot().nextCursor, 'fresh-cursor');
  client.update(null);
});

test('a lease revoked during a refresh cannot publish its late page', async () => {
  const latePage = deferred();
  let firstReads = 0;
  const { client, store } = makeStore(async input => {
    if (!listUrl(input)) return json({ data: [] });
    firstReads++;
    if (firstReads === 1) return json(page([summary('kept')], null));
    return latePage.promise;
  });
  await waitFor(() => store.getSnapshot().listLoaded && !store.getSnapshot().listing);
  const before = store.getSnapshot().threads;
  const refresh = store.refreshThreads();
  await waitFor(() => store.getSnapshot().listing);
  client.update(null);
  latePage.resolve(json(page([summary('late-from-old-lease')], null)));
  await refresh;
  assert.deepEqual(store.getSnapshot().threads, before);
  assert.equal(store.getSnapshot().listing, false);
});
