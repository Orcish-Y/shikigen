import { useEffect, useRef } from 'react';
import { resolveWorkspaceShortcut, detectShortcutPlatform, type CompositionState,
  type ShortcutForeground, type WorkspaceShortcut } from './workspace-shortcuts';

export function useWorkspaceShortcuts(foreground: ShortcutForeground,
  onShortcut: (action: WorkspaceShortcut) => void) {
  const shortcutRouting = useRef({foreground, onShortcut});
  shortcutRouting.current = {foreground, onShortcut};
  useEffect(() => {
    const composition: CompositionState = {isActive: false, endedAt: -Infinity};
    const platform = detectShortcutPlatform(navigator.platform);
    function startComposition() { composition.isActive = true; }
    function endComposition(event: CompositionEvent) {
      composition.isActive = false; composition.endedAt = event.timeStamp;
    }
    function clearComposition() { composition.isActive = false; composition.endedAt = -Infinity; }
    function routeShortcut(event: KeyboardEvent) {
      // Include any native dialog, even one not represented in this workspace's state.
      const currentForeground = shortcutRouting.current.foreground === 'none' && document.querySelector('dialog[open]')
        ? 'other' : shortcutRouting.current.foreground;
      const decision = resolveWorkspaceShortcut(event, platform, currentForeground, composition);
      if (decision.shouldPreventDefault) event.preventDefault();
      if (decision.action) shortcutRouting.current.onShortcut(decision.action);
    }
    window.addEventListener('compositionstart', startComposition, true);
    window.addEventListener('compositionend', endComposition, true);
    window.addEventListener('blur', clearComposition);
    window.addEventListener('keydown', routeShortcut);
    return () => {
      window.removeEventListener('compositionstart', startComposition, true);
      window.removeEventListener('compositionend', endComposition, true);
      window.removeEventListener('blur', clearComposition);
      window.removeEventListener('keydown', routeShortcut);
    };
  }, []);
}
