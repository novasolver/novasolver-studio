import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ui, useStore, useT } from "../state/store";
import { Tabs } from "./ui/Tabs";
import { Button } from "./ui/Button";
import { cn } from "./ui/cn";
import { VerificationLine } from "./PropertiesPanel";
import { fmt } from "../lib/units";

const DOT: Record<string, string> = {
  info: "bg-fg-3",
  ok: "bg-green",
  warn: "bg-orange-fill",
  error: "bg-red",
};

function time(ts: number) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

/** Log / verification drawer under the viewport. Opened from the status bar (one line). */
export function LogDrawer() {
  const t = useT();
  const open = useStore((s) => s.logOpen);
  const logs = useStore((s) => s.logs);
  const results = useStore((s) => s.results);
  const [tab, setTab] = useState<"log" | "verify">("log");
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open && list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [open, logs.length, tab]);

  if (!open) return null;
  return (
    <div className="anim-in shrink-0 overflow-hidden rounded-[8px] border border-line bg-surface dark:rounded-none dark:border-x-0 dark:border-b-0 dark:bg-bg">
      <div className="flex items-center justify-between border-b border-line pl-3 pr-1">
        <Tabs
          variant="underline"
          value={tab}
          onChange={setTab}
          items={[
            { value: "log", label: t("log.title") },
            { value: "verify", label: t("log.verify") },
          ]}
        />
        <Button variant="ghost" size="icon-sm" aria-label={t("log.collapse")} onClick={() => ui.log(false)}>
          <X size={14} />
        </Button>
      </div>
      <div ref={list} className="h-[168px] overflow-auto px-3 py-2 text-label">
        {tab === "log" ? (
          logs.length === 0 ? (
            <div className="text-fg-3">{t("log.empty")}</div>
          ) : (
            logs.map((l) => (
              <div key={l.id} className="flex gap-3 py-0.5">
                <span className="tnum shrink-0 text-fg-3">{time(l.t)}</span>
                <span className={cn("mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full", DOT[l.level])} />
                <span className={cn("min-w-0 break-words", l.level === "error" ? "text-red" : "text-fg-2")}>{l.text}</span>
              </div>
            ))
          )
        ) : results?.verification ? (
          <div className="text-body">
            <div className="mb-1 text-fg">{results.verification.label}</div>
            <VerificationLine />
            <div className="mt-2 text-label text-fg-3">
              {t("verify.tolerance", { t: fmt(results.verification.tolerance_pct, 3) })}
              {results.verification.metric ? `, ${results.verification.metric}` : ""}
            </div>
          </div>
        ) : (
          <div className="text-fg-3">{results?.gates_detail?.verified || t("verify.none")}</div>
        )}
      </div>
    </div>
  );
}
