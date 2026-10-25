import { ChevronUp, Hourglass, Square } from "lucide-react";
import { isActive, stopJob, ui, useStore, useT } from "../state/store";
import { fmtDuration } from "../lib/units";
import { Tooltip } from "./ui/Tooltip";
import { Spinner } from "./ui/misc";
import { cn } from "./ui/cn";

const DOT: Record<string, string> = {
  info: "bg-fg-3",
  ok: "bg-green",
  warn: "bg-orange-fill",
  error: "bg-red",
};

/** One 28 px bar: connection · save state · last log line (opens the log) | job. */
export function StatusBar() {
  const t = useT();
  const mode = useStore((s) => s.mode);
  const ws = useStore((s) => s.wsConnected);
  const saving = useStore((s) => s.saving);
  const rev = useStore((s) => s.payload?.case.revision);
  const job = useStore((s) => s.job);
  const stopping = useStore((s) => s.stopping);
  const importing = useStore((s) => s.importing);
  const last = useStore((s) => s.logs[s.logs.length - 1]);
  const logOpen = useStore((s) => s.logOpen);
  const hasCase = useStore((s) => !!s.payload);
  const active = isActive(job);
  const queued = job?.state === "queued";
  const pct = Math.round((job?.progress ?? 0) * 100);

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-line bg-bg px-3 text-label text-fg-3">
      {mode === "mock" ? (
        <Tooltip content={t("statusbar.mockTip")} side="top">
          <span className="flex items-center gap-1.5 text-orange">
            <span className="h-1.5 w-1.5 rounded-full bg-orange-fill" />
            {t("statusbar.mock")}
          </span>
        </Tooltip>
      ) : (
        <span className="flex shrink-0 items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", ws ? "bg-green" : "bg-fg-3")} />
          {ws ? t("statusbar.connected") : t("statusbar.offline")}
        </span>
      )}
      {rev != null && (
        <span className="tnum shrink-0">
          {saving ? t("statusbar.saving") : t("statusbar.saved")}
          <span className="ml-2">{t("statusbar.rev", { rev })}</span>
        </span>
      )}
      {(hasCase || last) && (
        <button
          type="button"
          onClick={() => ui.log()}
          aria-expanded={logOpen}
          aria-label={t(logOpen ? "log.collapse" : "log.expand")}
          className="-mx-1.5 flex h-6 min-w-0 flex-1 items-center gap-2 rounded-[4px] px-1.5 text-left hover:bg-hover"
        >
          {last ? (
            <>
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[last.level])} />
              <span className={cn("truncate", last.level === "error" ? "text-red" : "text-fg-2")}>{last.text}</span>
            </>
          ) : (
            <span className="truncate">{t("log.empty")}</span>
          )}
          <ChevronUp size={12} className={cn("shrink-0 transition-transform duration-[var(--dur-2)]", !logOpen && "rotate-180")} />
        </button>
      )}
      {!hasCase && !last && <span className="flex-1" />}
      {importing && (
        <span className="flex shrink-0 items-center gap-2 text-fg-2">
          <Spinner size={12} />
          {t("import.busy", { name: importing })}
        </span>
      )}
      {job ? (
        <span className="flex shrink-0 items-center gap-2.5">
          {active ? (
            <>
              {queued ? (
                // waiting for the machine's single solver slot: calm, not an error
                <Tooltip content={t("job.waiting")} side="top">
                  <span className="flex items-center gap-1.5 text-fg-2">
                    <Hourglass size={12} className="text-fg-3" />
                    {t("statusbar.job")} {t("job.state.queued")}
                    <span className="hidden text-fg-3 xl:inline">· {t("job.waiting")}</span>
                  </span>
                </Tooltip>
              ) : (
                <>
                  <span className="anim-pulse h-1.5 w-1.5 rounded-full bg-accent-fill" />
                  <span className="text-fg-2">{job.study ? t("conv.running") : `${t("statusbar.job")} ${t(`job.state.${job.state}`)}`}</span>
                  <span className="h-1 w-24 overflow-hidden rounded-full bg-line">
                    <span
                      className="block h-full rounded-full bg-accent-fill transition-[width] duration-300 ease-[var(--ease-out)]"
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                  <span className="tnum w-8 text-right text-fg-2">{pct}%</span>
                  {job.eta_s != null && <span className="tnum">{t("job.eta", { t: fmtDuration(job.eta_s) })}</span>}
                </>
              )}
              <button
                type="button"
                onClick={() => void stopJob()}
                disabled={stopping}
                className="flex h-5 items-center gap-1 rounded-[4px] border border-line-strong px-1.5 text-micro font-medium text-red hover:bg-red-soft disabled:opacity-50"
              >
                <Square size={8} fill="currentColor" />
                {stopping ? t("job.stopping") : t("job.stop")}
              </button>
            </>
          ) : (
            <span className={cn(job.state === "failed" && "text-red", job.state === "done" && "text-fg-2")}>
              {t("statusbar.job")} {t(`job.state.${job.state}`)}
            </span>
          )}
        </span>
      ) : (
        <span className="shrink-0">{t("statusbar.idle")}</span>
      )}
    </footer>
  );
}
