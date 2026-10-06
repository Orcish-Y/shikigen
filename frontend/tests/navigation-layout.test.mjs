import assert from 'node:assert/strict';
import test from 'node:test';
import { NavigationLayout, NAVIGATION_PREFERENCE_KEY, calculateNavigationBreakpoint } from '../src/navigation-layout.ts';

function createStorage(cachedPreference = null) {
  const writes = [];
  return {writes, getItem: key => {
    assert.equal(key, NAVIGATION_PREFERENCE_KEY);
    return cachedPreference;
  }, setItem: (key, serializedPreference) => {
    writes.push([key, serializedPreference]); cachedPreference = serializedPreference;
  }};
}

test('CSS viewport boundaries select all four layouts exactly', () => {
  for (const [width, expected] of [[390, 'phone'], [767.9, 'phone'], [768, 'tablet'],
    [1279.9, 'tablet'], [1280, 'compact-desktop'], [1439.9, 'compact-desktop'], [1440, 'wide-desktop'], [1920, 'wide-desktop']]) {
    assert.equal(calculateNavigationBreakpoint(width), expected);
  }
});

test('initial defaults never create a desktop preference', () => {
  const storage = createStorage();
  for (const [width, expected] of [[1440, false], [1280, true], [1024, true], [390, true]]) {
    const layout = new NavigationLayout(width, storage);
    assert.equal(layout.readView().isCollapsed, expected);
    assert.equal(layout.readView().isDesktop, width >= 1280);
  }
  assert.deepEqual(storage.writes, []);
});

test('the template auto-saved key cannot masquerade as an intentional desktop preference', () => {
  const reads = [];
  const writes = [];
  const layout = new NavigationLayout(1440, {
    getItem: key => { reads.push(key); return key === 'shikigen.navigation-collapsed' ? 'true' : null; },
    setItem: (key, serializedPreference) => writes.push([key, serializedPreference]),
  });
  assert.equal(layout.readView().isCollapsed, false);
  assert.deepEqual(reads, [NAVIGATION_PREFERENCE_KEY]);
  assert.deepEqual(writes, []);
});

test('resize recomputes defaults without storing them, including a narrow initial window', () => {
  const storage = createStorage();
  const layout = new NavigationLayout(390, storage);
  for (const width of [1024, 1280, 1440, 1280, 390, 1440]) {
    assert.equal(layout.resizeViewport(width).isCollapsed, width < 1440);
  }
  assert.deepEqual(storage.writes, []);
});

test('only a deliberate desktop toggle writes, and preference returns after narrow layouts', () => {
  const storage = createStorage();
  const layout = new NavigationLayout(1280, storage);
  assert.equal(layout.toggleDesktopNavigation().isCollapsed, false);
  assert.deepEqual(storage.writes, [[NAVIGATION_PREFERENCE_KEY, 'false']]);
  for (const width of [767, 768, 1279]) {
    assert.equal(layout.resizeViewport(width).isCollapsed, true);
    layout.toggleDesktopNavigation();
  }
  assert.equal(storage.writes.length, 1);
  assert.equal(layout.resizeViewport(1440).isCollapsed, false);
  assert.equal(layout.toggleDesktopNavigation().isCollapsed, true);
  assert.equal(layout.resizeViewport(1280).isCollapsed, true);
  assert.equal(new NavigationLayout(1440, storage).readView().isCollapsed, true);
});

test('both stored desktop choices win at either desktop width', () => {
  for (const preference of ['true', 'false']) {
    const storage = createStorage(preference);
    for (const width of [1280, 1440]) {
      assert.equal(new NavigationLayout(width, storage).readView().isCollapsed, preference === 'true');
    }
    assert.equal(new NavigationLayout(390, storage).readView().isCollapsed, true);
    assert.deepEqual(storage.writes, []);
  }
});

test('invalid cached values are ignored without overwriting user storage', () => {
  for (const value of ['TRUE', '', '{}', '0', 'null']) {
    const storage = createStorage(value);
    assert.equal(new NavigationLayout(1440, storage).readView().isCollapsed, false);
    assert.equal(new NavigationLayout(1280, storage).readView().isCollapsed, true);
    assert.deepEqual(storage.writes, []);
  }
});

test('storage read or write errors retain defaults and the in-memory active choice', () => {
  const layout = new NavigationLayout(1440, {
    getItem: () => { throw new Error('disabled'); },
    setItem: () => { throw new Error('quota'); },
  });
  assert.equal(layout.readView().isCollapsed, false);
  assert.equal(layout.toggleDesktopNavigation().isCollapsed, true);
  layout.resizeViewport(390);
  assert.equal(layout.resizeViewport(1440).isCollapsed, true);
  assert.equal(layout.toggleDesktopNavigation().isCollapsed, false);
  assert.equal(layout.resizeViewport(1280).isCollapsed, false);
});

test('without storage desktop choices still persist within this session', () => {
  const layout = new NavigationLayout(1280);
  layout.toggleDesktopNavigation();
  layout.resizeViewport(390);
  assert.equal(layout.resizeViewport(1280).isCollapsed, false);
});
