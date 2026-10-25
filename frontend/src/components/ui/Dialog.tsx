import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";

interface Props {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  /** "center" for modal dialogs, "top" for the command palette */
  placement?: "center" | "top";
  ariaLabel?: string;
}

export function Dialog({ open, onClose, children, className, placement = "center", ariaLabel }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const last = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    last.current = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    requestAnimationFrame(() => {
      const el = panel.current?.querySelector<HTMLElement>("[data-autofocus], input, button");
      el?.focus();
    });
    return () => {
      window.removeEventListener("keydown", onKey, true);
      last.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div
      className={cn(
        "anim-in fixed inset-0 z-[80] flex justify-center bg-black/25 dark:bg-black/50",
        placement === "top" ? "items-start pt-[12vh]" : "items-center",
      )}
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        className={cn(
          "anim-rise w-[min(560px,calc(100vw-32px))] overflow-hidden rounded-[8px] bg-overlay shadow-overlay",
          className,
        )}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
