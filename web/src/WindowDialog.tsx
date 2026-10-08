import { useEffect, useRef } from "react";
import { X } from "lucide-react";
export default function WindowDialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    dialog.showModal();
    const cancel = (event: Event) => {
      event.preventDefault();
      close.current();
    };
    dialog.addEventListener("cancel", cancel);
    return () => {
      dialog.removeEventListener("cancel", cancel);
      dialog.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog className="window-dialog" ref={ref} aria-label={title}>
      <header>
        <h2>{title}</h2>
        <button aria-label={`Close ${title}`} onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      <div className="window-dialog-content">{children}</div>
    </dialog>
  );
}
