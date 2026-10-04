export interface ComposerKey {
  key: string; shiftKey: boolean; repeat: boolean; isComposing: boolean;
  keyCode: number; timeStamp: number; preventDefault(): void;
}

/** IME 的候选确认优先；普通 Enter 从不成为运行控制操作。 */
export function composerEnter(event: ComposerKey, canSend: boolean, send: () => void,
  composing = false, compositionEndedAt = -Infinity) {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229 || composing
    || event.timeStamp - compositionEndedAt < 50 || event.shiftKey) return;
  event.preventDefault();
  if (!event.repeat && canSend) send();
}
