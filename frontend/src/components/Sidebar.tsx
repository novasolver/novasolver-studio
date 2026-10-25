import { useState } from "react";
import { ChevronDown, CircleCheck } from "lucide-react";
import { canOpenStep, EMPTY, focusCheck, goStep, STEPS, useStore, useT } from "../state/store";
import { cn } from "./ui/cn";
import { Kbd, LevelIcon, StatusDot } from "./ui/misc";
import { Tooltip } from "./ui/Tooltip";

function StepList() {
  const t = useT();
  const steps = useStore((s) => s.payload?.steps);
  const current = useStore((s) => s.step);
  const verified = useStore((s) => !!s.results?.gates.verified && !s.results?.stale);
  useStore((s) => s.results); // re-evaluate canOpenStep when results arrive
  if (!steps) return null;
  return (
    <nav className="flex flex-col gap-0.5 p-2" aria-label="steps">
      {STEPS.map((s, i) => {
        const active = s === current;
        const enabled = canOpenStep(s);
        const status = steps[s];
        const row = (
          <button
            key={s}
            type="button"
            disabled={!enabled}
            onClick={() => goStep(s)}
            aria-current={active ? "step" : undefined}
            className={cn(
              "flex h-8 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left text-body transition-colors duration-[var(--dur-1)]",
              active ? "bg-active font-medium text-fg" : status === "todo" ? "text-fg-3 hover:bg-hover hover:text-fg-2" : "text-fg-2 hover:bg-hover hover:text-fg",
              !enabled && "cursor-not-allowed opacity-50 hover:bg-transparent",
            )}
          >
            <span className={cn("tnum w-3 text-label font-medium", active ? "text-accent-text" : "text-fg-3")}>{i + 1}</span>
            <span className="flex-1 truncate">{t(`step.${s}.title`)}</span>
            <StatusDot status={status} verified={s === "results" && verified} />
          </button>
        );
        return enabled ? (
          row
        ) : (
          <Tooltip key={s} content={t("step.locked")} side="right" className="w-full">
            {row}
          </Tooltip>
        );
      })}
    </nav>
  );
}

function Checks() {
  const t = useT();
  const checks = useStore((s) => s.payload?.checks ?? EMPTY);
  const [open, setOpen] = useState(true);
  const errors = checks.filter((c) => c.level === "error");
  const warns = checks.filter((c) => c.level === "warn");
  const sorted = [...errors, ...warns];
  return (
    <section className="flex min-h-0 flex-1 flex-col px-2 pb-2 pt-5">
      <div className="px-2.5 pb-2 text-label font-medium text-fg-3">{t("checks.title")}</div>
      {sorted.length === 0 ? (
        <div className="flex items-center gap-2 px-2.5 text-body text-fg-2">
          <CircleCheck size={16} className="shrink-0 text-green" />
          {t("checks.ready")}
        </div>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="flex h-8 w-full items-center gap-2 rounded-[6px] px-2.5 text-left text-body text-fg hover:bg-hover"
          >
            <LevelIcon level={errors.length ? "error" : "warn"} size={16} />
            <span className="flex-1 truncate">{t("checks.attention", { n: sorted.length })}</span>
            <ChevronDown size={14} className={cn("text-fg-3 transition-transform duration-[var(--dur-2)]", !open && "-rotate-90")} />
          </button>
          {open && (
            <ul className="mt-0.5 min-h-0 flex-1 overflow-auto">
              {sorted.map((c, i) => (
                <li key={`${c.code}-${i}`}>
                  <button
                    type="button"
                    onClick={() => focusCheck(c.step, c.faces)}
                    className="flex w-full items-start gap-2 rounded-[6px] py-1.5 pl-[34px] pr-2.5 text-left hover:bg-hover"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="prose-ui line-clamp-3 text-label text-fg-2">{c.message}</span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-label text-fg-3">
                        <span className={cn("h-1.5 w-1.5 rounded-full", c.level === "error" ? "bg-red" : "bg-orange-fill")} />
                        {t(`step.${c.step}.title`)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function Sidebar() {
  const t = useT();
  return (
    <aside className="flex w-[240px] shrink-0 flex-col border-r border-line bg-bg">
      <StepList />
      <Checks />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-label text-fg-3">
        <span className="flex items-center gap-1">
          <Kbd>1</Kbd>
          <span>–</span>
          <Kbd>6</Kbd>
          <span className="ml-0.5">{t("kbd.steps").replace(/^1–6\s*/, "")}</span>
        </span>
        <span className="flex items-center gap-1">
          <Kbd>F</Kbd>
          <span className="ml-0.5">{t("kbd.fit").replace(/^F\s*/, "")}</span>
        </span>
      </div>
    </aside>
  );
}
