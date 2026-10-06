export interface WorkspaceKey {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  repeat: boolean;
  isComposing: boolean;
  keyCode: number;
  timeStamp: number;
  defaultPrevented: boolean;
}

export interface CompositionState {isActive: boolean; endedAt: number}
export type ShortcutPlatform = 'mac' | 'other';
export type ShortcutForeground = 'none' | 'commands' | 'navigation' | 'other';
export type WorkspaceShortcut = 'open-commands' | 'create-conversation' | 'toggle-navigation'
  | 'close-commands' | 'close-navigation';

export function detectShortcutPlatform(platform: string): ShortcutPlatform {
  return /Mac|iPhone|iPad/.test(platform) ? 'mac' : 'other';
}

export function isCompositionKey(event: WorkspaceKey, composition: CompositionState): boolean {
  return event.isComposing || event.keyCode === 229 || composition.isActive
    || event.timeStamp - composition.endedAt < 50;
}

/** Recognized but blocked combinations are consumed without a workspace action. */
export function resolveWorkspaceShortcut(event: WorkspaceKey, platform: ShortcutPlatform,
  foreground: ShortcutForeground, composition: CompositionState): {
    action: WorkspaceShortcut | null; shouldPreventDefault: boolean;
  } {
  const noShortcutDecision = {action: null, shouldPreventDefault: false};
  if (event.defaultPrevented || event.altKey || event.shiftKey || isCompositionKey(event, composition)) return noShortcutDecision;
  if (platform === 'mac' ? !event.metaKey || event.ctrlKey : !event.ctrlKey || event.metaKey) return noShortcutDecision;
  const key = event.key.toLowerCase();
  if (!['k', 'n', 'b'].includes(key)) return noShortcutDecision;
  if (event.repeat) return {action: null, shouldPreventDefault: true};
  if (foreground !== 'none') return {shouldPreventDefault: true, action:
    foreground === 'commands' && key === 'k' ? 'close-commands'
      : foreground === 'navigation' && key === 'b' ? 'close-navigation' : null};
  return {shouldPreventDefault: true, action: key === 'k' ? 'open-commands'
    : key === 'n' ? 'create-conversation' : 'toggle-navigation'};
}
