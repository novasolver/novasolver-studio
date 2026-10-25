import type { ReactNode } from "react";
import { cn } from "./cn";

export interface TabItem<V extends string> {
  value: V;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  title?: string;
}

interface Props<V extends string> {
  value: V;
  items: TabItem<V>[];
  onChange: (v: V) => void;
  className?: string;
  size?: "sm" | "md";
  variant?: "segmented" | "underline";
  ariaLabel?: string;
}

/** Segmented control (sliding thumb) or underline tabs. Arrow keys move between items. */
export function Tabs<V extends string>({ value, items, onChange, className, size = "md", variant = "segmented", ariaLabel }: Props<V>) {
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const enabled = items.filter((i) => !i.disabled);
    const idx = enabled.findIndex((i) => i.value === value);
    const next = enabled[(idx + (e.key === "ArrowRight" ? 1 : enabled.length - 1)) % enabled.length];
    if (next) onChange(next.value);
  };
  if (variant === "underline") {
    return (
      <div role="tablist" aria-label={ariaLabel} onKeyDown={onKey} className={cn("flex items-center gap-4", className)}>
        {items.map((it) => (
          <button
            key={it.value}
            role="tab"
            type="button"
            aria-selected={it.value === value}
            tabIndex={it.value === value ? 0 : -1}
            disabled={it.disabled}
            onClick={() => onChange(it.value)}
            className={cn(
              "relative inline-flex h-8 items-center gap-1.5 text-label font-medium transition-colors duration-[var(--dur-2)] disabled:opacity-50",
              it.value === value ? "text-fg" : "text-fg-3 hover:text-fg-2",
            )}
          >
            {it.icon}
            {it.label}
            {it.value === value && <span className="absolute inset-x-0 -bottom-px h-px bg-fg" />}
          </button>
        ))}
      </div>
    );
  }
  const idx = Math.max(0, items.findIndex((i) => i.value === value));
  const n = Math.max(1, items.length);
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKey}
      className={cn("relative flex w-full rounded-[6px] bg-raised p-[2px]", size === "sm" ? "h-7" : "h-8", className)}
    >
      <span
        aria-hidden
        className="absolute bottom-[2px] left-[2px] top-[2px] rounded-[5px] bg-thumb shadow-[0_1px_2px_rgba(0,0,0,0.2)] transition-transform duration-[var(--dur-2)] ease-[var(--ease-out)]"
        style={{ width: `calc((100% - 4px) / ${n})`, transform: `translateX(${idx * 100}%)` }}
      />
      {items.map((it) => {
        const on = it.value === value;
        return (
          <button
            key={it.value}
            role="tab"
            type="button"
            title={it.title}
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            disabled={it.disabled}
            onClick={() => onChange(it.value)}
            className={cn(
              "relative z-[1] inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 transition-colors duration-[var(--dur-2)] disabled:cursor-not-allowed disabled:opacity-50",
              size === "sm" ? "text-label" : "text-body",
              on ? "font-medium text-fg" : "text-fg-2 hover:text-fg",
            )}
          >
            {it.icon}
            <span className="truncate">{it.label}</span>
          </button>
        );
      })}
    </div>
  );
}
