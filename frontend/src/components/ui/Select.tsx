import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "./cn";

export interface SelectOption<V extends string = string> {
  value: V;
  label: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
}

interface Props<V extends string> {
  value: V | null;
  options: SelectOption<V>[];
  onChange: (v: V) => void;
  placeholder?: ReactNode;
  variant?: "default" | "ghost" | "unit";
  className?: string;
  menuClassName?: string;
  align?: "start" | "end";
  disabled?: boolean;
  ariaLabel?: string;
  renderValue?: (o: SelectOption<V> | undefined) => ReactNode;
  minMenuWidth?: number;
}

export function Select<V extends string>({
  value,
  options,
  onChange,
  placeholder,
  variant = "default",
  className,
  menuClassName,
  align = "start",
  disabled,
  ariaLabel,
  renderValue,
  minMenuWidth,
}: Props<V>) {
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ x: number; y: number; w: number; up: boolean } | null>(null);
  const current = options.find((o) => o.value === value);

  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const mh = menu.current?.offsetHeight ?? 200;
    const up = r.bottom + mh + 8 > window.innerHeight && r.top > mh + 8;
    const w = Math.max(r.width, minMenuWidth ?? 0);
    let x = align === "end" ? r.right - w : r.left;
    x = Math.max(6, Math.min(x, window.innerWidth - w - 6));
    setPos({ x, y: up ? r.top - mh - 4 : r.bottom + 4, w, up });
  }, [open, align, minMenuWidth, options.length]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (menu.current?.contains(e.target as Node) || btn.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onScroll = (e: Event) => {
      if (menu.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [open]);

  const openMenu = () => {
    if (disabled) return;
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };
  const choose = (o: SelectOption<V>) => {
    if (o.disabled) return;
    setOpen(false);
    btn.current?.focus();
    if (o.value !== value) onChange(o.value);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openMenu();
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(options.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const o = options[active];
      if (o) choose(o);
    } else if (e.key === "Tab") setOpen(false);
  };

  const trigger =
    variant === "unit"
      ? "h-full px-2 text-label text-fg-3 hover:text-fg hover:bg-hover border-l border-line gap-0.5"
      : variant === "ghost"
        ? "h-8 px-2 text-body text-fg-2 hover:bg-hover hover:text-fg rounded-[6px] gap-1.5"
        : "h-8 w-full px-2.5 text-body text-fg bg-field border border-line-strong rounded-[6px] hover:border-[var(--field-hover)] gap-2";

  return (
    <>
      <button
        ref={btn}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKey}
        className={cn(
          "inline-flex min-w-0 items-center justify-between text-left transition-[background-color,border-color,color] duration-[var(--dur-2)] disabled:opacity-50 disabled:cursor-not-allowed",
          trigger,
          open && variant === "default" && "outline-2 -outline-offset-1 outline-[var(--focus)]",
          className,
        )}
      >
        <span className="flex min-w-0 items-center gap-2 truncate">
          {renderValue ? renderValue(current) : current ? (
            <>
              {current.icon}
              <span className="truncate">{current.label}</span>
            </>
          ) : (
            <span className="text-fg-3">{placeholder}</span>
          )}
        </span>
        <ChevronDown size={variant === "unit" ? 12 : 14} className="shrink-0 text-fg-3" />
      </button>
      {open &&
        createPortal(
          <div
            ref={menu}
            role="listbox"
            onKeyDown={onKey}
            style={{ left: pos?.x ?? -9999, top: pos?.y ?? -9999, minWidth: pos?.w }}
            className={cn(
              "anim-in fixed z-[90] max-h-[320px] overflow-auto rounded-[8px] bg-overlay p-1 shadow-overlay",
              menuClassName,
            )}
          >
            {options.map((o, i) => (
              <div
                key={o.value}
                role="option"
                aria-selected={o.value === value}
                aria-disabled={o.disabled}
                onPointerEnter={() => setActive(i)}
                onClick={() => choose(o)}
                className={cn(
                  "flex min-h-8 cursor-default items-center gap-2 rounded-[4px] px-2 py-1 text-body text-fg",
                  i === active && !o.disabled && "bg-hover",
                  o.disabled && "opacity-50",
                )}
              >
                {o.icon}
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{o.label}</span>
                  {o.hint && <span className="block truncate text-micro text-fg-3">{o.hint}</span>}
                </span>
                {o.value === value && <Check size={14} className="shrink-0 text-accent-text" />}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
