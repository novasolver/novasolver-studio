import { useEffect, useRef, useState, type ReactNode } from "react";
import { Copy, Film, Image, MessagesSquare, Share2 } from "lucide-react";
import { communityUrl } from "./StartScreen";
import { caseTitle, getState, getViewer, setState, toast, t as tr, useStore, useT } from "../state/store";
import { splitCards } from "../lib/resultCards";
import { copyImage, download, shareImage, turntableVideo, videoSupported, type ShareInfo, type ShareLayout } from "../lib/share";
import { fmt, fmtGci, fmtSignedPct, unitLabel } from "../lib/units";
import { Tooltip } from "./ui/Tooltip";
import { cn } from "./ui/cn";

const withUnit = (v: number, u: string, digits = 4) => {
  const s = unitLabel(u);
  return fmt(v, digits) + (s ? ` ${s}` : "");
};

/** Figures for the share frame, the same choice the results strip makes. */
function shareInfo(): ShareInfo {
  const s = getState();
  const r = s.results;
  const f = s.field;
  const split = r ? splitCards(r) : null;
  const v = r?.verification;
  const lead = split?.lead ?? null;
  const [lo, hi] = s.range ?? f?.range ?? [0, 1];
  return {
    title: caseTitle(s.payload),
    lead: lead ? { label: lead.label, value: withUnit(lead.value, lead.unit) } : null,
    check:
      split?.compared && v
        ? {
            pass: v.pass,
            text:
              v.kind === "convergence"
                ? tr("strip.gci", { g: fmtGci(v.error_pct) })
                : tr("strip.vsRef", { ref: v.reference_label ?? tr("verify.reference"), d: fmtSignedPct(v.error_pct) }),
          }
        : null,
    outputs: (split?.outputs ?? []).slice(0, 2).map((c) => ({ label: c.label, value: withUnit(c.value, c.unit) })),
    legend: f
      ? { label: f.label + (unitLabel(f.unit) ? ` [${unitLabel(f.unit)}]` : ""), lo: fmt(lo, 3), hi: fmt(hi, 3), colormap: s.colormap }
      : null,
  };
}

function fileName(ext: string) {
  const s = getState();
  const id = (s.payload?.case.case_id ?? "case").replace(/[^\w-]/g, "");
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `novasolver-studio-${id}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.${ext}`;
}

let abort: AbortController | null = null;

export async function exportImage(layout: ShareLayout, copy: boolean) {
  const viewer = getViewer();
  if (!viewer) return;
  try {
    const blob = await shareImage(viewer, shareInfo(), layout);
    if (copy) {
      const ok = await copyImage(blob);
      toast(tr(ok ? "share.copied" : "share.copyFailed"), ok ? "info" : "error");
      return;
    }
    const name = fileName("png");
    download(blob, name);
    toast(tr("share.saved", { name }));
  } catch (e) {
    toast(tr("share.failed", { message: e instanceof Error ? e.message : String(e) }), "error");
  }
}

async function exportVideo(layout: ShareLayout) {
  const viewer = getViewer();
  if (!viewer || getState().shareProgress != null) return;
  if (!videoSupported()) {
    toast(tr("share.noVideo"), "error");
    return;
  }
  abort = new AbortController();
  setState({ shareProgress: 0 });
  try {
    const blob = await turntableVideo(viewer, shareInfo(), layout, (u) => setState({ shareProgress: u }), abort.signal);
    const name = fileName("mp4");
    download(blob, name);
    toast(tr("share.saved", { name }));
  } catch (e) {
    if (!(e instanceof DOMException && e.name === "AbortError"))
      toast(tr("share.failed", { message: e instanceof Error ? e.message : String(e) }), "error");
  } finally {
    abort = null;
    setState({ shareProgress: null });
  }
}

/** Share button for the viewport HUD (results step): images, a turntable video, copy to clipboard. */
export function ShareButton() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const busy = useStore((s) => s.shareProgress != null);
  const lang = useStore((s) => s.lang);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);
  const items: { id: string; icon: ReactNode; label: string; run: () => void }[] = [
    { id: "img-wide", icon: <Image size={15} />, label: t("share.imageWide"), run: () => void exportImage("wide", false) },
    { id: "img-tall", icon: <Image size={15} />, label: t("share.imageTall"), run: () => void exportImage("tall", false) },
    { id: "vid-tall", icon: <Film size={15} />, label: t("share.videoTall"), run: () => void exportVideo("tall") },
    { id: "vid-wide", icon: <Film size={15} />, label: t("share.videoWide"), run: () => void exportVideo("wide") },
    { id: "copy", icon: <Copy size={15} />, label: t("share.copy"), run: () => void exportImage("wide", true) },
  ];
  return (
    <div ref={box} className="relative">
      <Tooltip content={t("share.button")} side="top">
        <button
          type="button"
          aria-label={t("share.button")}
          aria-expanded={open}
          disabled={busy}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-[6px] text-fg-2 transition-colors duration-[var(--dur-1)] hover:bg-hover hover:text-fg disabled:opacity-50",
            open && "bg-active text-fg",
          )}
        >
          <Share2 size={16} />
        </button>
      </Tooltip>
      {open && (
        <div role="menu" className="anim-in absolute bottom-10 right-0 z-[90] w-[264px] rounded-[8px] bg-overlay p-1 shadow-overlay">
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                it.run();
              }}
              className="flex min-h-8 w-full items-center gap-2 rounded-[4px] px-2 py-1 text-left text-body text-fg hover:bg-hover"
            >
              <span className="text-fg-3">{it.icon}</span>
              {it.label}
            </button>
          ))}
          <p className="prose-ui mt-1 border-t border-line px-2 pb-1 pt-2 text-micro text-fg-3">{t("share.hint")}</p>
          <a
            href={communityUrl(lang, "share_menu")}
            target="_blank"
            rel="noreferrer"
            className="flex min-h-8 items-center gap-2 rounded-[4px] px-2 py-1 text-label text-accent-text hover:bg-hover"
          >
            <MessagesSquare size={14} className="shrink-0" />
            {t("share.community")}
          </a>
        </div>
      )}
    </div>
  );
}

/** Progress while a turntable video is being encoded (covers the stretched canvas during capture). */
export function ShareProgress() {
  const t = useT();
  const p = useStore((s) => s.shareProgress);
  if (p == null) return null;
  return (
    <div className="viewer-bg absolute inset-0 z-[80] flex items-center justify-center">
      <div className="hud flex w-[300px] flex-col gap-2.5 rounded-[8px] px-4 py-3">
        <div className="flex items-center justify-between gap-3 text-body text-fg">
          <span className="tnum">{t("share.recording", { p: Math.round(p * 100) })}</span>
          <button
            type="button"
            onClick={() => abort?.abort()}
            className="h-7 rounded-[6px] border border-line-strong px-2.5 text-label font-medium text-fg hover:bg-hover"
          >
            {t("share.cancel")}
          </button>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-raised">
          <div className="h-full bg-accent-fill" style={{ width: `${p * 100}%` }} />
        </div>
      </div>
    </div>
  );
}

/** Small product mark in the viewport corner, so screenshots carry the name (can be turned off from the palette). */
export function BrandMark() {
  const on = useStore((s) => s.brandMark);
  if (!on) return null;
  return (
    // hidden in narrow windows: next to the view buttons it would run into the colour bar on the left
    <div className="pointer-events-none flex select-none items-center gap-1.5 text-micro text-fg-3 max-xl:hidden">
      <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden>
        <path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" fill="var(--accent-fill)" />
        <path d="M12 7.2 16.8 12 12 16.8 7.2 12Z" fill="var(--vp-bottom)" />
      </svg>
      <span className="font-medium">NovaSolver Studio</span>
      <span>novasolver.jp/studio</span>
    </div>
  );
}
