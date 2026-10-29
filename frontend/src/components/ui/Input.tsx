import { forwardRef, useEffect, useRef, useState, type InputHTMLAttributes } from "react";
import { cn } from "./cn";
import { Select } from "./Select";
import { convert, parseWithUnit, unitLabel } from "../../lib/units";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-8 w-full rounded-[6px] border border-line-strong bg-field px-2.5 text-body text-fg placeholder:text-fg-3",
        "transition-[border-color] duration-[var(--dur-2)] hover:border-[var(--field-hover)]",
        className,
      )}
      {...rest}
    />
  );
});

interface NumberInputProps {
  value: number;
  unit?: string;
  units?: string[];
  min?: number;
  max?: number;
  onCommit: (value: number, unit?: string) => void;
  ariaLabel?: string;
  className?: string;
}

function canonical(v: number) {
  if (!Number.isFinite(v)) return "";
  return String(Number(v.toPrecision(6)));
}

/**
 * Unit-aware numeric input. Typing commits immediately (the store debounces the PATCH).
 * "5 mm" is accepted; switching the unit converts the value so the physical quantity stays.
 * ↑/↓ nudge by ~1 % of magnitude (Shift = 10 %).
 */
export function NumberInput({ value, unit, units, min, max, onCommit, ariaLabel, className }: NumberInputProps) {
  const [text, setText] = useState(canonical(value));
  const [invalid, setInvalid] = useState(false);
  const focused = useRef(false);
  const unitList = units && units.length ? units : unit ? [unit] : [];

  useEffect(() => {
    if (!focused.current) {
      setText(canonical(value));
      setInvalid(false);
    }
  }, [value, unit]);

  const inRange = (v: number) => (min == null || v >= min) && (max == null || v <= max);

  const handle = (s: string) => {
    setText(s);
    const p = parseWithUnit(s, unitList);
    if (!p || !inRange(p.value)) {
      setInvalid(s.trim() !== "");
      return;
    }
    if (p.unit && p.unit !== unit && (!unit || convert(p.value, p.unit, unit) == null)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (p.unit && p.unit !== unit) {
      setText(canonical(p.value));
      onCommit(p.value, p.unit);
    } else if (p.value !== value) onCommit(p.value, unit);
  };

  const nudge = (dir: 1 | -1, big: boolean) => {
    const base = Math.abs(value) > 0 ? Math.pow(10, Math.floor(Math.log10(Math.abs(value)))) : 1;
    const step = (big ? 1 : 0.1) * base;
    let v = Number((value + dir * step).toPrecision(10));
    if (min != null) v = Math.max(min, v);
    if (max != null) v = Math.min(max, v);
    setText(canonical(v));
    onCommit(v, unit);
  };

  return (
    <div
      className={cn(
        "flex h-8 w-full items-stretch overflow-hidden rounded-[6px] border bg-field transition-[border-color] duration-[var(--dur-2)]",
        "focus-within:outline-2 focus-within:-outline-offset-1 focus-within:outline-[var(--focus)]",
        invalid ? "border-red" : "border-line-strong hover:border-[var(--field-hover)]",
        className,
      )}
    >
      <input
        aria-label={ariaLabel}
        aria-invalid={invalid}
        inputMode="decimal"
        spellCheck={false}
        value={text}
        onChange={(e) => handle(e.target.value)}
        onFocus={(e) => {
          focused.current = true;
          e.target.select();
        }}
        onBlur={() => {
          focused.current = false;
          setText(canonical(value));
          setInvalid(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            nudge(e.key === "ArrowUp" ? 1 : -1, e.shiftKey);
          } else if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          else if (e.key === "Escape") {
            setText(canonical(value));
            setInvalid(false);
            (e.target as HTMLInputElement).blur();
          }
        }}
        className="tnum min-w-0 flex-1 bg-transparent px-2.5 text-right text-body text-fg outline-none focus-visible:outline-none"
      />
      {unitList.length > 1 ? (
        <Select
          variant="unit"
          value={unit ?? unitList[0]}
          align="end"
          ariaLabel="unit"
          options={unitList.map((u) => ({ value: u, label: unitLabel(u) }))}
          onChange={(u) => {
            const conv = unit ? convert(value, unit, u) : null;
            if (conv == null || !Number.isFinite(conv)) {
              setInvalid(true);
              return;
            }
            const v = Number(conv.toPrecision(10));
            setText(canonical(v));
            onCommit(v, u);
          }}
          className="min-w-[60px] shrink-0 justify-between"
        />
      ) : unitList.length === 1 ? (
        <span className="flex min-w-[44px] shrink-0 items-center justify-center border-l border-line px-2 text-label text-fg-3">
          {unitLabel(unitList[0])}
        </span>
      ) : null}
    </div>
  );
}
