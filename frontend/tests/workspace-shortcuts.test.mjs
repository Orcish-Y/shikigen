import assert from 'node:assert/strict';
import test from 'node:test';
import { isCompositionKey, resolveWorkspaceShortcut, detectShortcutPlatform } from '../src/workspace-shortcuts.ts';

const composition = {isActive:false, endedAt:-Infinity};
const createKeyEvent = (key, overrides={}) => ({key, ctrlKey:true, metaKey:false, altKey:false, shiftKey:false,
  repeat:false, isComposing:false, keyCode:0, timeStamp:1000, defaultPrevented:false, ...overrides});
const noShortcutDecision = {action:null,shouldPreventDefault:false};

test('platform is explicit and only its ordinary modifier combination executes K, N and B', () => {
  assert.equal(detectShortcutPlatform('MacIntel'), 'mac');
  assert.equal(detectShortcutPlatform('iPad'), 'mac');
  assert.equal(detectShortcutPlatform('Win32'), 'other');
  assert.equal(detectShortcutPlatform('Linux x86_64'), 'other');
  for (const [key, action] of [['k','open-commands'],['n','create-conversation'],['b','toggle-navigation']]) {
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key), 'other', 'none', composition), {action,shouldPreventDefault:true});
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key.toUpperCase(),{ctrlKey:false,metaKey:true}), 'mac', 'none', composition), {action,shouldPreventDefault:true});
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key), 'mac', 'none', composition), noShortcutDecision);
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key,{ctrlKey:false,metaKey:true}), 'other', 'none', composition), noShortcutDecision);
  }
});

test('ordinary editing, shifted, alternate and mixed modifiers stay untouched', () => {
  for (const key of ['c','v','a','z','Enter','Escape','ArrowDown']) {
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key), 'other', 'none', composition), noShortcutDecision);
  }
  for (const overrides of [{ctrlKey:false},{shiftKey:true},{altKey:true},{metaKey:true},{defaultPrevented:true}]) {
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent('n',overrides), 'other', 'none', composition), noShortcutDecision);
  }
});

test('held combinations are consumed but never repeat creation, toggle or modal closure', () => {
  for (const foreground of ['none','commands','navigation','other']) {
    for (const key of ['k','n','b']) {
      assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key,{repeat:true}), 'other', foreground, composition),
        {action:null,shouldPreventDefault:true});
    }
  }
});

test('a modal blocks every workspace action except the matching panel close', () => {
  for (const [foreground,key,action] of [
    ['commands','k','close-commands'],['commands','n',null],['commands','b',null],
    ['navigation','k',null],['navigation','n',null],['navigation','b','close-navigation'],
    ['other','k',null],['other','n',null],['other','b',null],
  ]) {
    assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key), 'other', foreground, composition), {action,shouldPreventDefault:true});
  }
});

test('IME events, legacy key 229 and tracked composition cannot execute or close a panel', () => {
  for (const foreground of ['none','commands','navigation','other']) {
    for (const key of ['k','n','b']) {
      for (const overrides of [{isComposing:true},{keyCode:229}]) {
        assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key,overrides), 'other', foreground, composition), noShortcutDecision);
      }
      assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent(key), 'other', foreground, {...composition,isActive:true}), noShortcutDecision);
    }
  }
});

test('candidate confirmation after compositionend has a strict 50ms guard and then recovers', () => {
  const endedComposition = {isActive:false, endedAt:1000};
  assert.equal(isCompositionKey(createKeyEvent('Enter',{timeStamp:1049.99}),endedComposition), true);
  assert.equal(isCompositionKey(createKeyEvent('Enter',{timeStamp:1050}),endedComposition), false);
  assert.deepEqual(resolveWorkspaceShortcut(createKeyEvent('n',{timeStamp:1049}), 'other', 'none', endedComposition), noShortcutDecision);
  assert.equal(resolveWorkspaceShortcut(createKeyEvent('n',{timeStamp:1050}), 'other', 'none', endedComposition).action, 'create-conversation');
});
