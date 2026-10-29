import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { cssGradient } from "../viewer";
import { setState, useStore, useT } from "../state/store";
import { fmt, unitLabel } from "../lib/units";
import { Tooltip } from "./ui/Tooltip";
import { cn } from "./ui/cn";

const WIDTH = 200;

/** Tick labels. A narrow range far from zero (20.00 … 20.08 °C) needs fixed decimals from the tick step: three or
 * four significant digits would print every tick as "20". */
function tickFormat(lo: number, hi: number): (v: number, sig: number) => string {
  const step = (hi - lo) / 4;
  const mag = Math.max(Math.abs(lo), Math.abs(hi));
  // A uniform field (a bar in pure tension) differs only by rounding noise: fixed decimals would print 283.14000000.
  if (step > 0 && step / mag < 1e-6) return (v) => fmt(v, 4);   // every tick the same value, not 283 / 280
  if (!(step > 0) || mag >= 1e6 || step / mag > 0.01) return (v, sig) => fmt(v, sig);
  const dec = Math.min(8, Math.max(0, Math.ceil(-Math.log10(step))));
  return (v) => (v === 0 ? "0" : v.toFixed(dec).replace(/^-/, "−"));
}

function EditableValue({ value, onCommit, className, format = fmt }: {
  value: number; onCommit: (v: number) => void; className?: string; format?: (v: number, sig: number) => string;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  if (editing)
    return (
      <input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const v = Number(text.replace(/−/g, "-").replace(",", "."));
          if (Number.isFinite(v)) onCommit(v);
          setEditing(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setEditing(false);
          e.stopPropagation();
        }}
        className={cn("tnum h-5 w-[72px] rounded-[4px] border border-line-strong bg-field px-1 text-micro text-fg", className)}
      />
    );
  return (
    <button
      type="button"
      title={t("colorbar.dragHint")}
      onClick={() => {
        setText(String(Number(value.toPrecision(6))));
        setEditing(true);
      }}
      className={cn("tnum h-5 rounded-[4px] px-0.5 text-micro text-fg-2 hover:bg-hover hover:text-fg", className)}
    >
      {format(value, 3)}
    </button>
  );
}

/** Legend: 200 × 8 bar, five ticks (explicit 0 for diverging maps), drag notches on hover. */
export function ColorBar() {
  const t = useT();
  const field = useStore((s) => s.field);
  const colormap = useStore((s) => s.colormap);
  const range = useStore((s) => s.range);
  if (!field) return null;
  const auto = field.range;
  const [lo, hi] = range ?? auto;
  const span = auto[1] - auto[0] || Math.abs(auto[1]) || 1;

  const set = (a: number, b: number) => {
    if (b <= a) return;
    setState({ range: [a, b] });
  };

  const startDrag = (end: "lo" | "hi") => (e: React.PointerEvent) => {
    e.preventDefault();
    const x0 = e.clientX;
    const start = [lo, hi];
    const move = (ev: PointerEvent) => {
      const dv = ((ev.clientX - x0) / WIDTH) * (start[1] - start[0] || span);
      if (end === "lo") set(Math.min(start[0] + dv, start[1] - span * 0.01), start[1]);
      else set(start[0], Math.max(start[1] + dv, start[0] + span * 0.01));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // inner ticks at 1/4, 1/2, 3/4; a diverging map gets its 0 instead of the middle tick
  const inner = [0.25, 0.5, 0.75].map((u) => ({ u, v: lo + (hi - lo) * u }));
  if (colormap === "coolwarm" && lo < 0 && hi > 0) {
    inner[1] = { u: -lo / (hi - lo), v: 0 };
  }
  const unit = unitLabel(field.unit);
  const tf = tickFormat(lo, hi);
  // drop an inner label that would collide with the editable end values
  const w = (s: string) => s.length * 6.4 + 6;
  const loW = w(tf(lo, 3));
  const hiW = w(tf(hi, 3));
  const visible = inner.map((x) => {
    const c = x.u * WIDTH;
    const half = w(tf(x.v, 2)) / 2;
    return c - half > loW + 2 && c + half < WIDTH - hiW - 2;
  });

  return (
    <div className="hud anim-in group absolute bottom-3 left-3 rounded-[8px] px-3 pb-1.5 pt-2" style={{ width: WIDTH + 24 }}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="truncate text-label font-medium text-fg">
          {field.label}
          {unit && <span className="ml-1 font-normal text-fg-3">[{unit}]</span>}
        </span>
        {range && (
          <Tooltip content={t("colorbar.reset")} side="top">
            <button
              type="button"
              aria-label={t("colorbar.reset")}
              onClick={() => setState({ range: null })}
              className="flex h-5 items-center gap-1 rounded-[4px] px-1 text-micro text-fg-2 hover:bg-hover hover:text-fg"
            >
              <RotateCcw size={11} />
              {t("results.auto")}
            </button>
          </Tooltip>
        )}
      </div>
      <div className="relative h-2 rounded-[2px]" style={{ width: WIDTH, background: cssGradient(colormap) }}>
        {(["lo", "hi"] as const).map((end) => (
          <span
            key={end}
            onPointerDown={startDrag(end)}
            title={t("colorbar.dragHint")}
            className="absolute -top-[3px] h-[14px] w-[6px] cursor-ew-resize opacity-0 transition-opacity duration-[var(--dur-2)] group-hover:opacity-100"
            style={end === "lo" ? { left: -3 } : { right: -3 }}
          >
            <span className="mx-auto block h-full w-[2px] rounded-full bg-fg" />
          </span>
        ))}
      </div>
      <div className="relative mt-0.5 h-5" style={{ width: WIDTH }}>
        {[0, ...inner.map((x) => x.u), 1].map((u, i) => (
          <span key={i} className="absolute top-0 h-1 w-px bg-hud-line" style={{ left: `calc(${u * 100}% - ${u === 1 ? 1 : 0}px)` }} />
        ))}
        <EditableValue value={lo} format={tf} onCommit={(v) => set(v, hi)} className="absolute left-[-2px] top-1" />
        {inner.map((x, i) => visible[i] && (
          <span
            key={i}
            className="tnum absolute top-1 -translate-x-1/2 text-micro text-fg-2"
            style={{ left: `${x.u * 100}%` }}
          >
            {tf(x.v, 2)}
          </span>
        ))}
        <EditableValue value={hi} format={tf} onCommit={(v) => set(lo, v)} className="absolute right-[-2px] top-1" />
      </div>
    </div>
  );
}
