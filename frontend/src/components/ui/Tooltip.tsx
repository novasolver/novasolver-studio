import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "./cn";

interface Props {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  shortcut?: string;
  className?: string;
  delay?: number;
}

/** Lightweight tooltip: hover/focus, portal-rendered, auto-flips inside the viewport. */
export function Tooltip({ content, children, side = "bottom", shortcut, className, delay = 800 }: Props) {
  const anchor = useRef<HTMLSpanElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const timer = useRef(0);

  const show = (immediate = false) => {
    window.clearTimeout(timer.current);
    if (immediate) setOpen(true);
    else timer.current = window.setTimeout(() => setOpen(true), delay);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
    setPos(null);
  };

  useLayoutEffect(() => {
    if (!open || !anchor.current || !tip.current) return;
    const a = anchor.current.getBoundingClientRect();
    const t = tip.current.getBoundingClientRect();
    const gap = 6;
    let x = 0;
    let y = 0;
    if (side === "bottom" || side === "top") {
      x = a.left + a.width / 2 - t.width / 2;
      y = side === "bottom" ? a.bottom + gap : a.top - t.height - gap;
      if (y + t.height > window.innerHeight - 4) y = a.top - t.height - gap;
      if (y < 4) y = a.bottom + gap;
    } else {
      y = a.top + a.height / 2 - t.height / 2;
      x = side === "right" ? a.right + gap : a.left - t.width - gap;
    }
    x = Math.max(6, Math.min(x, window.innerWidth - t.width - 6));
    setPos({ x, y });
  }, [open, side]);

  return (
    <span
      ref={anchor}
      className={cn("inline-flex", className)}
      onPointerEnter={() => show()}
      onPointerLeave={hide}
      onFocus={(e) => (e.target as HTMLElement).matches?.(":focus-visible") && show(true)}
      onBlur={hide}
      onPointerDown={hide}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={tip}
            role="tooltip"
            style={{ left: pos?.x ?? -9999, top: pos?.y ?? -9999 }}
            className="anim-in pointer-events-none fixed z-[100] flex max-w-[280px] items-center gap-2 rounded-[6px] bg-overlay px-2 py-1 text-label text-fg shadow-overlay"
          >
            <span>{content}</span>
            {shortcut && (
              <kbd className="rounded-[4px] border border-line bg-raised px-1 font-sans text-[11px] leading-[16px] text-fg-3">
                {shortcut}
              </kbd>
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
