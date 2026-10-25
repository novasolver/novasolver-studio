import { cn } from "./cn";

interface Props {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  ariaLabel?: string;
  className?: string;
  /** optional labelled stops shown under the track (e.g. coarse / normal / fine) */
  marks?: { value: number; label: string }[];
}

export function Slider({ value, min, max, step = 1, onChange, ariaLabel, className, marks }: Props) {
  const fill = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return (
    <div className={cn("w-full", className)}>
      <input
        type="range"
        className="nss-range"
        aria-label={ariaLabel}
        min={min}
        max={max}
        step={step}
        value={value}
        style={{ ["--fill" as string]: `${fill}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {marks && (
        <div className="tnum relative mt-1 h-4 text-micro text-fg-3">
          {marks.map((m) => {
            const p = ((m.value - min) / (max - min)) * 100;
            const edge = p <= 0 ? "translate-x-0" : p >= 100 ? "-translate-x-full" : "-translate-x-1/2";
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => onChange(m.value)}
                style={{ left: `${p}%` }}
                className={cn(
                  "absolute top-0 whitespace-nowrap transition-colors duration-[var(--dur-2)] hover:text-fg",
                  edge,
                  m.value === value && "font-medium text-fg-2",
                )}
              >
                {m.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
