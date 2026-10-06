import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient } from '../src/backend-client.ts';
import { WorkspaceImages } from '../src/workspace-images.ts';

const workspace = {workspace_id:'directory-1', root:'C:\\work'};
const resource = {workspace_id:'directory-1', resource_id:'image-1', absolute_path:'C:\\work\\one.png',
  relative_path:'one.png', name:'one.png', kind:'file', mime_type:'image/png', size:3,
  modified_at:'2026-10-06T00:00:00Z', version:'version-1', can_preview:true};
function client(fetcher) {
  const backend = new BackendClient(fetcher);
  backend.update({state:'ready', startup_id:'lease-1', base_url:'http://localhost:1234'});
  return backend;
}

test('BackendSession only obtains current resource facts and binary through its lease', async () => {
  const requests = [];
  const backend = client(async (url, options) => {
    requests.push([url, options]);
    return url.endsWith('/image') ? new Response(new Uint8Array([1,2,3]), {headers:{'content-type':'image/png'}})
      : Response.json({data:url.endsWith('/workspace') ? workspace : resource});
  });
  assert.deepEqual(await backend.session.getWorkspace(), workspace);
  assert.deepEqual(await backend.session.resolveResource('one.png'), resource);
  const blob = await backend.session.readResourceImage(resource.resource_id);
  assert.equal(blob.type, 'image/png');
  assert.deepEqual([...new Uint8Array(await blob.arrayBuffer())], [1,2,3]);
  assert.ok(requests.every(([, options]) => options.cache === 'no-store' && options.signal instanceof AbortSignal));
  const oldSession = backend.session;
  backend.update(null);
  await assert.rejects(oldSession.getWorkspace(), {name:'AbortError'});
});

const tick = () => new Promise(resolve => setImmediate(resolve));
test('same resource previews share one Blob URL and release it only after the last reader', async () => {
  const requests = []; const revoked = []; let created = 0;
  const backend = client(async url => {
    requests.push(url);
    return url.endsWith('/image') ? new Response('png', {headers:{'content-type':'image/png'}})
      : Response.json({data:url.endsWith('/workspace') ? workspace : resource});
  });
  const images = new WorkspaceImages(backend.session, {createObjectUrl:() => `blob:owned-${++created}`, revokeObjectUrl:url => revoked.push(url)});
  const first = []; const second = [];
  const reader1 = images.watchImage('one.png', state => first.push(state));
  const reader2 = images.watchImage('C:\\work\\one.png', state => second.push(state));
  await tick(); await tick();
  assert.equal(first.at(-1).phase, 'ready');
  assert.equal(second.at(-1).url, first.at(-1).url);
  assert.equal(requests.filter(url => url.endsWith('/image')).length, 1);
  assert.equal(created, 1);
  reader1.releaseImageReader(); assert.deepEqual(revoked, []);
  reader2.releaseImageReader(); assert.deepEqual(revoked, ['blob:owned-1']);
  images.disposeImages(); assert.equal(revoked.length, 1);
});

test('hide/switch disposal cancels unfinished binary reads and filters an ignored-abort late response', async () => {
  let finishImage; let imageSignal; const urls = [];
  const backend = client(async (url, options) => {
    if (url.endsWith('/image')) {
      imageSignal = options.signal;
      return new Promise(resolve => finishImage = resolve);
    }
    return Response.json({data:url.endsWith('/workspace') ? workspace : resource});
  });
  const images = new WorkspaceImages(backend.session, {createObjectUrl:() => {urls.push('created'); return 'blob:late';}, revokeObjectUrl:() => urls.push('revoked')});
  const states = [];
  images.watchImage('one.png', state => states.push(state));
  await tick(); assert.ok(finishImage);
  images.disposeImages(); assert.equal(imageSignal.aborted, true);
  finishImage(new Response('late', {headers:{'content-type':'image/png'}}));
  await tick(); await tick();
  assert.deepEqual(urls, []);
  assert.equal(states.at(-1).phase, 'loading');
  assert.ok(!states.some(state => state.phase === 'ready'));
});

test('revoked lease releases completed URLs, and visible reentry resolves current disk facts afresh', async () => {
  const requests = []; const revoked = [];
  const backend = client(async url => {
    requests.push(url);
    return url.endsWith('/image') ? new Response('png', {headers:{'content-type':'image/png'}})
      : Response.json({data:url.endsWith('/workspace') ? workspace : resource});
  });
  const first = new WorkspaceImages(backend.session, {createObjectUrl:() => 'blob:first', revokeObjectUrl:url => revoked.push(url)});
  first.watchImage('one.png', () => {}); await tick(); await tick();
  backend.update(null); assert.deepEqual(revoked, ['blob:first']);
  backend.update({state:'ready', startup_id:'lease-2', base_url:'http://localhost:1235'});
  const second = new WorkspaceImages(backend.session, {createObjectUrl:() => 'blob:second', revokeObjectUrl:url => revoked.push(url)});
  const states = []; const watcher = second.watchImage('one.png', state => states.push(state));
  await tick(); await tick();
  assert.equal(states.at(-1).url, 'blob:second');
  assert.equal(requests.filter(url => url.endsWith('/workspace')).length, 2);
  assert.ok(requests.at(-1).startsWith('http://localhost:1235/'));
  watcher.releaseImageReader(); assert.deepEqual(revoked, ['blob:first','blob:second']);
  second.disposeImages();
});

test('404/403/409/413/415 failures stay local and manual retry resolves a new version', async () => {
  for (const status of [404,403,409,413,415]) {
    let attempts = 0; const requests = [];
    const backend = client(async url => {
      requests.push(url);
      if (url.endsWith('/image')) return ++attempts === 1 ? new Response('实际读取原因', {status})
        : new Response('png', {headers:{'content-type':'image/png'}});
      return Response.json({data:url.endsWith('/workspace') ? workspace : {...resource, version:attempts ? 'version-2' : 'version-1'}});
    });
    const images = new WorkspaceImages(backend.session);
    const states = []; const watcher = images.watchImage('one.png', state => states.push(state));
    await tick(); await tick();
    assert.equal(states.at(-1).phase, 'error');
    assert.match(states.at(-1).error, new RegExp(`HTTP ${status}`));
    assert.match(states.at(-1).error, /实际读取原因/);
    assert.equal(attempts, 1);
    watcher.retryImageLoad(); await tick(); await tick();
    assert.equal(states.at(-1).phase, 'ready');
    assert.equal(states.at(-1).resource.version, 'version-2');
    assert.ok(requests.every(url => url.includes('/api/workspace')));
    images.disposeImages();
  }
});

test('workspace mismatch and bad metadata never acquire a URL; binary format and size are constrained', async () => {
  for (const override of [{workspace_id:'other'}, {size:-1}, {version:null}, {can_preview:'yes'}]) {
    let imageReads = 0;
    const backend = client(async url => {
      if (url.endsWith('/image')) {imageReads++; return new Response('png', {headers:{'content-type':'image/png'}});}
      return Response.json({data:url.endsWith('/workspace') ? workspace : {...resource, ...override}});
    });
    const images = new WorkspaceImages(backend.session);
    const states = []; images.watchImage('one.png', state => states.push(state));
    await tick(); await tick();
    assert.equal(states.at(-1).phase, 'error'); assert.equal(imageReads, 0);
    images.disposeImages();
  }
  for (const response of [new Response('<html>', {headers:{'content-type':'text/html'}}),
    new Response(new Uint8Array(20 * 1024 * 1024 + 1), {headers:{'content-type':'image/png'}})]) {
    const backend = client(async () => response);
    await assert.rejects(backend.session.readResourceImage('image-1'));
  }
});

test('releasing the last reader during resolve cancels that reference without aborting another image', async () => {
  let finishResolve; let resolveSignal;
  const backend = client(async (url, options) => {
    if (url.includes('path=slow')) {
      resolveSignal = options.signal;
      return new Promise(resolve => finishResolve = resolve);
    }
    return url.endsWith('/image') ? new Response('png', {headers:{'content-type':'image/png'}})
      : Response.json({data:url.endsWith('/workspace') ? workspace : resource});
  });
  const images = new WorkspaceImages(backend.session);
  const slow = []; const fast = [];
  const first = images.watchImage('slow.png', state => slow.push(state));
  images.watchImage('one.png', state => fast.push(state));
  await tick(); await tick();
  first.releaseImageReader(); assert.equal(resolveSignal.aborted, true);
  finishResolve(Response.json({data:resource})); await tick();
  assert.equal(slow.at(-1).phase, 'loading');
  assert.equal(fast.at(-1).phase, 'ready');
  images.disposeImages();
});



