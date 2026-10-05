import { useLayoutEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";

export function Overlay({
  title,
  drawer = false,
  onClose,
  children,
}: {
  title: string;
  drawer?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
      const valid = previous?.isConnected && previous !== document.body
        && previous !== document.documentElement && !previous.closest('[inert]');
      if (valid) previous.focus();
      if (!valid || document.activeElement !== previous)
        document.querySelector<HTMLElement>('.chat-workspace')?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={drawer ? "overlay drawer" : "overlay command-dialog"}
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
