import type { ReactNode } from "react";
import { Check, CircleAlert, TriangleAlert } from "lucide-react";
import type { StepStatus } from "../../api/types";
import { cn } from "./cn";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "tnum inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] border border-line bg-raised px-1 font-sans text-[11px] leading-none font-medium text-fg-3",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

/**
 * Step status mark. Done = quiet check in text-3; green only when the step's own
 * validation passed (`verified`); needs attention = 6 px warning dot; todo = nothing.
 */
export function StatusDot({ status, verified, className }: { status: StepStatus; verified?: boolean; className?: string }) {
  if (status === "ok")
    return (
      <span className={cn("inline-flex h-4 w-4 items-center justify-center", verified ? "text-green" : "text-fg-3", className)}>
        <Check size={14} />
      </span>
    );
  if (status === "warn")
    return (
      <span className={cn("inline-flex h-4 w-4 items-center justify-center", className)}>
        <span className="h-1.5 w-1.5 rounded-full bg-orange-fill" />
      </span>
    );
  return <span className={cn("inline-block h-4 w-4", className)} />;
}

export function LevelIcon({ level, size = 14 }: { level: "error" | "warn"; size?: number }) {
  return level === "error" ? (
    <CircleAlert size={size} className="shrink-0 text-red" />
  ) : (
    <TriangleAlert size={size} className="shrink-0 text-orange" />
  );
}

/** Section header: 12/500 text-2, sentence case, 8 px to content. */
export function SectionLabel({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-2 flex min-h-4 items-center justify-between gap-2", className)}>
      <span className="text-label font-medium text-fg-2">{children}</span>
      {right}
    </div>
  );
}

/** Field: label 12/500 text-2, 6 px above the control; helper 12 px below. */
export function Field({ label, children, hint, right }: { label: ReactNode; children: ReactNode; hint?: ReactNode; right?: ReactNode }) {
  return (
    <div className="block">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="truncate text-label font-medium text-fg-2">{label}</span>
        {right}
      </div>
      {children}
      {hint && <span className="mt-1.5 block text-label text-fg-3">{hint}</span>}
    </div>
  );
}

export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={cn("animate-spin", className)} aria-hidden>
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

/** Neutral chip (badges, counts). Status is shown by an icon colour, never a saturated fill. */
export function Chip({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center gap-1 whitespace-nowrap rounded-[4px] bg-raised px-1.5 text-label text-fg-2",
        className,
      )}
    >
      {children}
    </span>
  );
}
