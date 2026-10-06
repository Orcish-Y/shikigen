import { useLayoutEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";

export function Overlay({
  title,
  variant = 'dialog',
  fallbackFocus = '.mobile-navigation, .history-toggle, .navigation-heading button',
  onClose,
  children,
  initialFocus,
}: {
  title: string;
  variant?: 'dialog' | 'drawer' | 'sidebar';
  fallbackFocus?: string;
  onClose: () => void;
  children: ReactNode;
  initialFocus?:string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    if (initialFocus) dialog.querySelector<HTMLElement>(initialFocus)?.focus();
    return () => {
      dialog.close();
      // The initiating message or whole workspace can be removed in this same
      // React commit. Restore after DOM mutations and do not steal a new modal's focus.
      queueMicrotask(() => {
        if (document.querySelector('dialog[open]')) return;
        const isPreviousValid = previousFocus?.isConnected && previousFocus !== document.body
          && previousFocus !== document.documentElement && !previousFocus.closest('[inert]')
          && previousFocus.getClientRects().length > 0;
        if (isPreviousValid) previousFocus.focus();
        if (!isPreviousValid || document.activeElement !== previousFocus) {
          const fallback = fallbackFocus && [...document.querySelectorAll<HTMLElement>(fallbackFocus)]
            .find(element => element.getClientRects().length > 0 && !element.matches(':disabled'));
          (fallback || document.querySelector<HTMLElement>('.chat-workspace, .backend-screen'))?.focus();
        }
      });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`overlay ${variant === 'sidebar' ? 'sidebar-dialog' : variant === 'drawer' ? 'drawer' : 'command-dialog'}`}
      aria-labelledby="overlay-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onKeyDown={event => {
        if (event.key !== 'Tab' || event.altKey || event.ctrlKey || event.metaKey) return;
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, summary, [tabindex]',
        )].filter(element => element.tabIndex >= 0 && !element.matches(':disabled')
          && !element.closest('[inert]') && element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls.at(-1);
        const active = document.activeElement;
        if (first && last && ((event.shiftKey && active === first)
          || (!event.shiftKey && active === last))) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const rect = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            onClose();
        }
      }}
    >
      <div className="overlay-heading">
        <h2 id="overlay-title">{title}</h2>
        <button className="icon-button" onClick={onClose} aria-label="关闭">
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
