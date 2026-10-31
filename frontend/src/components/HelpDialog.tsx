import { useState } from "react";
import { ArrowUpCircle, ExternalLink, RefreshCw, X } from "lucide-react";
import { Dialog } from "./ui/Dialog";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/misc";
import { applyUpdate, checkUpdate, setUpdateAuto, startUpdate, ui, useStore, useT } from "../state/store";
import { communityUrl } from "./StartScreen";
import type { Lang, UpdateInfo } from "../api/types";

const SITE: Record<Lang, string> = { ja: "https://novasolver.jp/studio/", en: "https://novasolver.jp/en/studio/", zh: "https://novasolver.jp/zh/studio/" };
const GITHUB = "https://github.com/novasolver/novasolver-studio";

function Link({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="flex h-8 items-center gap-2 text-body text-accent-text hover:underline">
      <ExternalLink size={14} strokeWidth={1.5} />
      {children}
    </a>
  );
}

/** What to do about an available update, per kind of installation. */
function UpdateAction({ u }: { u: UpdateInfo }) {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const job = useStore((s) => s.updateJob);
  const [applying, setApplying] = useState(false);       // one click starts one swap
  if (u.kind === "mcpb") return <p className="prose-ui text-body text-fg-2">{t("update.mcpb")}</p>;
  if (u.kind === "dev") return <p className="prose-ui text-body text-fg-2">{t("update.dev")}</p>;
  if (u.kind !== "portable")
    return (
      <div className="space-y-1.5">
        <p className="text-body text-fg-2">{t("update.python")}</p>
        {u.pip && <code className="block break-all rounded-[6px] bg-sunken px-2 py-1.5 text-label text-fg">{u.pip}</code>}
        <Link href={u.page?.[lang] ?? SITE[lang]}>{t("update.page")}</Link>
      </div>
    );
  if (job?.state === "downloading") {
    const frac = job.total ? (job.bytes ?? 0) / job.total : 0;
    return (
      <div className="space-y-1.5" aria-live="polite">
        <div className="flex justify-between text-label text-fg-2">
          <span>{t("update.downloading")}</span>
          <span className="tnum">{((job.bytes ?? 0) / 1e6).toFixed(0)} / {((job.total ?? 0) / 1e6).toFixed(0)} MB</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-raised">
          <div className="h-full rounded-full bg-accent-fill transition-[width] duration-300 ease-[var(--ease-out)]" style={{ width: `${frac * 100}%` }} />
        </div>
      </div>
    );
  }
  if (job?.state === "ready")
    return (
      <Button disabled={applying} onClick={() => { setApplying(true); void applyUpdate().finally(() => setApplying(false)); }}>
        <RefreshCw size={14} strokeWidth={1.5} />
        {t("update.restart")}
      </Button>
    );
  if (job?.state === "applying") return <p className="prose-ui text-body text-fg-2">{t("update.restarting")}</p>;
  return (
    <div className="space-y-1.5">
      {job?.state === "error" && <p className="text-body text-red">{t("update.failed", { error: job.error ?? "" })}</p>}
      <Button onClick={() => void startUpdate()}>
        <ArrowUpCircle size={14} strokeWidth={1.5} />
        {t("update.now")}
        {u.size ? <span className="tnum text-label opacity-70">({(u.size / 1e6).toFixed(0)} MB)</span> : null}
      </Button>
    </div>
  );
}

export function HelpDialog() {
  const t = useT();
  const open = useStore((s) => s.help);
  const lang = useStore((s) => s.lang);
  const u = useStore((s) => s.update);
  const checking = useStore((s) => s.updateChecking);
  const [notesOpen, setNotesOpen] = useState(true);
  return (
    <Dialog open={open} onClose={() => ui.help(false)} ariaLabel={t("help.title")}>
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="text-em font-semibold text-fg">{t("help.title")}</h2>
        <Button variant="ghost" size="icon" aria-label="Close" onClick={() => ui.help(false)}>
          <X size={16} />
        </Button>
      </div>
      <div className="space-y-6 px-5 py-4">
        <section className="space-y-1">
          <div className="flex items-baseline gap-2">
            <span className="text-label text-fg-3">{t("help.version")}</span>
            <span className="tnum text-em font-semibold text-fg">{u?.current ?? "…"}</span>
          </div>
          <Link href={SITE[lang]}>{t("help.site")}</Link>
          <Link href={GITHUB}>{t("help.github")}</Link>
          <Link href={communityUrl(lang, "help")}>{t("help.community")}</Link>
        </section>
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-label font-medium text-fg-2">{t("update.title")}</h3>
            <Button variant="secondary" disabled={checking} onClick={() => void checkUpdate(true)}>
              {checking ? <Spinner /> : <RefreshCw size={14} strokeWidth={1.5} />}
              {checking ? t("update.checking") : t("update.check")}
            </Button>
          </div>
          {u?.offline ? (
            <p className="prose-ui text-body text-fg-2">{u.offline_mode ? t("update.offlineMode") : u.message ?? t("update.offline")}</p>
          ) : u?.available && u.latest ? (
            <div className="space-y-3 rounded-[8px] border border-line bg-surface p-3">
              <p className="text-body font-medium text-fg">{t("update.available", { version: u.latest })}</p>
              {u.notes?.[lang] && (
                <div>
                  <button type="button" className="text-label text-fg-3 hover:text-fg" onClick={() => setNotesOpen(!notesOpen)}>
                    {notesOpen ? "▾" : "▸"} {t("update.details")}
                  </button>
                  {notesOpen && <p className="prose-ui mt-1 whitespace-pre-line text-body text-fg-2">{u.notes[lang]}</p>}
                </div>
              )}
              <UpdateAction u={u} />
            </div>
          ) : u?.latest ? (
            <p className="text-body text-fg-2">{t("update.latest", { version: u.current })}</p>
          ) : null}
          <label className="flex items-center gap-2 text-body text-fg-2">
            <input type="checkbox" checked={u?.auto ?? true} onChange={(e) => void setUpdateAuto(e.target.checked)} />
            {t("update.auto")}
          </label>
          <p className="prose-ui text-label text-fg-3">{t("update.privacy")}</p>
        </section>
      </div>
    </Dialog>
  );
}

/** A quiet notice in the corner once per new version; "Details" opens the help dialog. */
export function UpdateNotice() {
  const t = useT();
  const u = useStore((s) => s.update);
  const open = useStore((s) => s.help);
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem("nss.updateDismissed") ?? ""; } catch { return ""; }
  });
  if (!u?.available || !u.latest || open || hidden === u.latest) return null;
  const dismiss = () => {
    try { localStorage.setItem("nss.updateDismissed", u.latest!); } catch { /* ignore */ }
    setHidden(u.latest!);
  };
  return (
    <div role="status" className="anim-rise fixed bottom-10 right-4 z-[70] flex items-center gap-3 rounded-[8px] bg-overlay px-3.5 py-2.5 shadow-overlay">
      <ArrowUpCircle size={16} strokeWidth={1.5} className="text-accent-text" />
      <span className="text-body text-fg">{t("update.toast", { version: u.latest })}</span>
      <Button variant="secondary" onClick={() => ui.help(true)}>{t("update.details")}</Button>
      <Button variant="ghost" size="icon" aria-label="Close" onClick={dismiss}>
        <X size={14} />
      </Button>
    </div>
  );
}
