import { useEffect, useMemo, useRef, useState } from "react";
import { Box, Check, CircleAlert, Frame, Maximize, PanelTop, Play, Sparkles, TriangleAlert, X } from "lucide-react";
import { Viewer, roleGroup, groupColor, VIEWER_PALETTES } from "../viewer";
import {
  generateMesh,
  goStep,
  isActive,
  loadResults,
  registerViewer,
  runCase,
  selectFace,
  setHoverFace,
  useStore,
  useT,
  viewCmd,
} from "../state/store";
import type { ResultCard, ResultsPayload } from "../api/types";
import { ColorBar } from "./ColorBar";
import { Tooltip } from "./ui/Tooltip";
import { Spinner } from "./ui/misc";
import { cn } from "./ui/cn";
import { fmt, fmtGci, fmtSignedPct, unitLabel } from "../lib/units";

/** "+x" -> [1, 0, 0] */
function flowVector(id: string | null): [number, number, number] | null {
  const m = id?.match(/^([+-])([xyz])$/);
  if (!m) return null;
  const v: [number, number, number] = [0, 0, 0];
  v["xyz".indexOf(m[2])] = m[1] === "-" ? -1 : 1;
  return v;
}

function ViewButtons() {
  const t = useT();
  const items = [
    { id: "iso" as const, icon: <Box size={16} />, label: t("view.iso") },
    { id: "front" as const, icon: <Frame size={16} />, label: t("view.front") },
    { id: "top" as const, icon: <PanelTop size={16} />, label: t("view.top") },
    { id: "fit" as const, icon: <Maximize size={16} />, label: t("view.fit"), key: "F" },
  ];
  return (
    <div className="hud absolute bottom-3 right-3 flex items-center gap-0.5 rounded-[8px] p-1">
      {items.map((it) => (
        <Tooltip key={it.id} content={it.label} shortcut={it.key} side="top">
          <button
            type="button"
            aria-label={it.label}
            onClick={() => viewCmd(it.id)}
            className="flex h-8 w-8 items-center justify-center rounded-[6px] text-fg-2 transition-colors duration-[var(--dur-1)] hover:bg-hover hover:text-fg"
          >
            {it.icon}
          </button>
        </Tooltip>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ results strip

/** Inputs echoed back as cards (not results). */
const INPUT_KEYS = new Set(["re"]);
/** Bookkeeping numbers (quiet group at the end). */
const META_KEYS = new Set(["nodes", "elements", "iterations"]);
/** Near-duplicates of the colour-bar maximum. */
const DUP_KEYS = new Set(["max_disp"]);

function splitCards(r: ResultsPayload) {
  const v = r.verification;
  const close = (a: number, b: number) => Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * 2e-3;
  const inputs = r.cards.filter((c) => INPUT_KEYS.has(c.key));
  const meta = r.cards.filter((c) => META_KEYS.has(c.key));
  let outputs = r.cards.filter((c) => !INPUT_KEYS.has(c.key) && !META_KEYS.has(c.key) && !DUP_KEYS.has(c.key));
  const lead = (v && outputs.find((c) => close(c.value, v.computed))) || outputs[0] || null;
  outputs = outputs.filter((c) => c !== lead);
  return { inputs, lead, outputs: outputs.slice(0, 3), meta: meta.slice(0, 1), compared: !!(v && lead && close(lead.value, v.computed)) };
}

function Unit({ u }: { u: string }) {
  const s = unitLabel(u);
  return s ? <span className="ml-[0.2em] text-[0.8em] font-normal text-fg-3">{s}</span> : null;
}

function Cell({ c, quiet }: { c: ResultCard; quiet?: boolean }) {
  return (
    <div className="min-w-0 px-3.5">
      <div className="truncate text-micro text-fg-2">{c.label}</div>
      <div className={cn("tnum mt-0.5 whitespace-nowrap", quiet ? "text-body font-medium text-fg-2" : "text-kpi font-medium text-fg")}>
        {fmt(c.value, 4)}
        <Unit u={c.unit} />
      </div>
    </div>
  );
}

const Divider = () => <span className="h-6 w-px shrink-0 self-center bg-hud-line" />;

function ResultsStrip() {
  const t = useT();
  const results = useStore((s) => s.results);
  if (!results || !results.cards.length) return null;
  const { inputs, lead, outputs, meta, compared } = splitCards(results);
  const v = results.verification;
  return (
    <div className="pointer-events-none absolute left-3 right-[88px] top-3 flex flex-wrap items-start gap-2">
      <div className="hud hud-blur anim-in pointer-events-auto flex max-w-full items-stretch rounded-[8px] px-3.5 py-2.5">
        {lead && (
          <div className="min-w-0 pr-3.5">
            <div className="truncate text-micro text-fg-2">{lead.label}</div>
            <div className="tnum mt-0.5 whitespace-nowrap text-lead font-semibold text-fg">
              {fmt(lead.value, 4)}
              <Unit u={lead.unit} />
            </div>
            {compared && v && (
              <div className={cn("tnum mt-0.5 flex items-center gap-1 text-micro", v.pass ? "text-green" : "text-red")}>
                {v.pass ? <Check size={12} /> : <X size={12} />}
                <span>
                  {v.kind === "convergence"
                    ? t("strip.gci", { g: fmtGci(v.error_pct) })
                    : t("strip.vsRef", { ref: v.reference_label ?? t("verify.reference"), d: fmtSignedPct(v.error_pct) })}
                </span>
              </div>
            )}
          </div>
        )}
        {outputs.map((c) => (
          <div key={c.key} className="flex items-stretch">
            <Divider />
            <div className="self-center">
              <Cell c={c} />
            </div>
          </div>
        ))}
        {meta.map((c) => (
          <div key={c.key} className="flex items-stretch">
            <Divider />
            <div className="self-center">
              <Cell c={c} quiet />
            </div>
          </div>
        ))}
      </div>
      {inputs.length > 0 && (
        <div className="hud anim-in pointer-events-auto flex h-8 items-center gap-3 rounded-[8px] px-3 text-label text-fg-2">
          <span className="text-fg-3">{t("strip.inputs")}</span>
          {inputs.map((c) => (
            <span key={c.key} className="tnum whitespace-nowrap">
              {c.label} <span className="font-medium text-fg">{fmt(c.value, 4)}</span>
              <Unit u={c.unit} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** While a job runs: the strip shows grey bars the size of the final values. */
function StripSkeleton() {
  return (
    <div className="pointer-events-none absolute left-3 top-3">
      <div className="hud anim-in flex items-stretch rounded-[8px] px-3.5 py-2.5">
        <div className="pr-3.5">
          <div className="skeleton anim-shimmer h-3 w-20" />
          <div className="skeleton anim-shimmer mt-1.5 h-5 w-24" />
        </div>
        {[0, 1].map((i) => (
          <div key={i} className="flex items-stretch">
            <Divider />
            <div className="self-center px-3.5">
              <div className="skeleton anim-shimmer h-3 w-16" />
              <div className="skeleton anim-shimmer mt-1.5 h-4 w-14" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StaleBanner() {
  const t = useT();
  const stale = useStore((s) => !!s.results?.stale);
  if (!stale) return null;
  return (
    <div className="hud anim-in absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2.5 rounded-[8px] py-1 pl-3 pr-1 text-body">
      <TriangleAlert size={14} className="text-orange" />
      <span className="text-fg">{t("results.stale")}</span>
      <button
        type="button"
        onClick={() => void runCase()}
        className="h-7 rounded-[6px] bg-primary px-2.5 text-label font-medium text-primary-ink hover:opacity-90"
      >
        {t("results.rerun")}
      </button>
    </div>
  );
}

function ToastView() {
  const toast = useStore((s) => s.toast);
  if (!toast) return null;
  return (
    <div
      key={toast.id}
      role="status"
      className="hud anim-rise absolute bottom-16 left-1/2 flex max-w-[min(520px,80%)] -translate-x-1/2 items-center gap-2 rounded-[8px] px-3 py-2 text-body text-fg"
    >
      {toast.kind === "ai" ? (
        <Sparkles size={14} className="shrink-0 text-accent-text" />
      ) : toast.kind === "error" ? (
        <CircleAlert size={14} className="shrink-0 text-red" />
      ) : null}
      <span className="line-clamp-2">{toast.text}</span>
    </div>
  );
}

function MeshEmpty() {
  const t = useT();
  const busy = useStore((s) => s.meshBusy);
  return (
    <div className="hud anim-in absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-[8px] py-1 pl-3.5 pr-1 text-body text-fg-2">
      {t("mesh.emptyViewport")}
      <button
        type="button"
        disabled={busy}
        onClick={() => void generateMesh()}
        className="flex h-7 items-center gap-1.5 rounded-[6px] border border-line-strong px-2.5 text-label font-medium text-fg hover:bg-hover disabled:opacity-50"
      >
        {busy ? <Spinner size={12} /> : <Play size={12} />}
        {busy ? t("mesh.generating") : t("mesh.generate")}
      </button>
    </div>
  );
}

export function ViewerPane() {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const [viewer, setViewer] = useState<Viewer | null>(null);
  const [hover, setHover] = useState<{ key: string; label?: string } | null>(null);

  const theme = useStore((s) => s.theme);
  const caseId = useStore((s) => s.payload?.case.case_id);
  const geometry = useStore((s) => s.geometry);
  const faces = useStore((s) => s.payload?.ui.faces);
  const roles = useStore((s) => s.payload?.ui.roles);
  const step = useStore((s) => s.step);
  const selected = useStore((s) => s.selectedFaces);
  const listHover = useStore((s) => s.hoverFace);
  const flash = useStore((s) => s.flashFaces);
  const field = useStore((s) => s.field);
  const colormap = useStore((s) => s.colormap);
  const range = useStore((s) => s.range);
  const deform = useStore((s) => s.deformScale);
  const resultsLoading = useStore((s) => s.resultsLoading);
  const meshExists = useStore((s) => !!s.payload?.ui.mesh?.state.exists);
  const running = useStore((s) => isActive(s.job));

  const showField = step === "results" && !!field;

  useEffect(() => {
    if (!host.current) return;
    const v = new Viewer(host.current);
    setViewer(v);
    registerViewer(v);
    return () => {
      registerViewer(null);
      v.dispose();
    };
  }, []);

  useEffect(() => {
    viewer?.setTheme(theme);
  }, [viewer, theme]);

  // external flow: free-stream arrows (before the geometry effect so the first fit frames them)
  const flowDir = useStore((s) => (s.payload?.ui.physics === "external" ? (s.payload.ui.flow?.direction ?? null) : null));
  const showFlow = !!flowDir && step !== "results";
  const lastFlow = useRef<string | null>(null);
  useEffect(() => {
    if (!viewer) return;
    viewer.setFlowDirection(showFlow ? flowVector(flowDir) : null);
    if (showFlow && lastFlow.current && lastFlow.current !== flowDir) viewer.view("fit");
    if (showFlow) lastFlow.current = flowDir;
  }, [viewer, showFlow, flowDir]);
  const external = !!flowDir;

  // id -> key mapping (viewer works with keys)
  const viewerGeometry = useMemo(
    () =>
      geometry
        ? {
            faces: geometry.faces.map((f) => ({
              id: f.key ?? String(f.id),
              label: f.label,
              positions: f.positions,
              indices: f.indices,
            })),
          }
        : null,
    [geometry],
  );

  const firstFitFor = useRef<string | null>(null);
  const lastBbox = useRef<string>("");
  useEffect(() => {
    if (!viewer) return;
    viewer.setGeometry(viewerGeometry);
    if (!viewerGeometry || !caseId) return;
    const bbox = JSON.stringify(geometry?.bbox ?? null);
    if (firstFitFor.current !== caseId) {
      firstFitFor.current = caseId;
      viewer.view("iso", false);
    } else if (bbox !== lastBbox.current) {
      viewer.view("fit"); // dimensions changed (by the user or an AI): keep the angle, refit
    }
    lastBbox.current = bbox;
  }, [viewer, viewerGeometry, caseId, geometry]);

  useEffect(() => {
    viewer?.setWireframe(step === "mesh" && meshExists);
  }, [viewer, step, meshExists, viewerGeometry]);

  const planar = useStore((s) => !!s.payload?.ui.faces.some((f) => f.locked));
  useEffect(() => {
    viewer?.setGround(!planar);
  }, [viewer, planar]);
  const topViewFor = useRef<string | null>(null);
  useEffect(() => {
    if (!viewer) return;
    viewer.setField(showField ? field : null);
    // 2D flow cases show a slice plane: look straight at it the first time
    if (showField && planar && caseId && topViewFor.current !== caseId) {
      topViewFor.current = caseId;
      viewer.view("top");
    } else if (showField && external) {
      viewer.view("fit"); // the flow slice reaches well beyond the body: frame it
    }
  }, [viewer, field, showField, planar, caseId, external]);

  useEffect(() => {
    viewer?.setColormap(colormap);
  }, [viewer, colormap, field]);

  useEffect(() => {
    if (!viewer || !field) return;
    const r = range ?? field.range;
    viewer.setRange(r[0], r[1]);
  }, [viewer, range, field]);

  useEffect(() => {
    if (!viewer || !field) return;
    viewer.setDeformScale(deform ?? field.auto_deform_scale ?? 1);
  }, [viewer, deform, field]);

  // face colouring layers (role colours shown on the boundaries step only)
  useEffect(() => {
    if (!viewer || !faces) return;
    const pal = VIEWER_PALETTES[theme];
    viewer.highlightFaces(
      faces.filter((f) => f.locked).map((f) => f.key),
      pal.roles.locked,
      "locked",
    );
    const bc = step === "boundaries";
    for (const g of ["fixed", "loaded", "exchange", "unassigned"] as const) {
      viewer.highlightFaces(
        bc ? faces.filter((f) => !f.locked && roleGroup(f.role) === g).map((f) => f.key) : [],
        groupColor(theme, g),
        g,
      );
    }
    viewer.highlightFaces(flash, pal.roles.flash, "flash");
  }, [viewer, faces, step, flash, viewerGeometry, theme]);

  useEffect(() => {
    viewer?.setSelection(step === "boundaries" ? selected : []);
  }, [viewer, selected, viewerGeometry, step]);

  useEffect(() => {
    viewer?.setHoverFace(listHover && listHover !== hover?.key ? listHover : null);
  }, [viewer, listHover, hover, viewerGeometry]);

  // picking (Shift / Ctrl adds to the selection)
  useEffect(() => {
    if (!viewer) return;
    // external flow: every body face is a wall, nothing to pick
    viewer.setPickingEnabled(step !== "results" && !external);
    const offPick = viewer.onFacePick((id, info) => {
      const key = id == null ? null : String(id);
      const f = faces?.find((x) => x.key === key);
      if (key && f?.locked) return;
      if (!key) {
        if (!info.shiftKey) selectFace(null);
        return;
      }
      selectFace(key, info.shiftKey ? "toggle" : "set");
      if (step !== "boundaries") goStep("boundaries");
    });
    const offHover = viewer.onFaceHover((id, label) => {
      setHover(id == null ? null : { key: String(id), label });
      setHoverFace(id == null ? null : String(id));
    });
    return () => {
      offPick();
      offHover();
    };
  }, [viewer, step, faces, external]);

  const hoverFace = hover ? faces?.find((f) => f.key === hover.key) : null;
  const hoverRole = hoverFace?.locked
    ? t("bc.locked")
    : (hoverFace?.role_label ?? roles?.find((r) => r.id === hoverFace?.role)?.label ?? t("bc.unassigned"));

  return (
    <div
      className={cn(
        "viewer-bg relative min-h-0 flex-1 overflow-hidden rounded-[8px] ring-1 ring-line dark:rounded-none dark:ring-0",
      )}
    >
      <div ref={host} className="absolute inset-0" />

      {!geometry && caseId && (
        <div className="absolute inset-0 flex items-center justify-center text-fg-3">
          <Spinner size={20} />
        </div>
      )}

      {hover && step !== "results" ? (
        <div className="hud pointer-events-none absolute left-1/2 top-3 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-1 text-label">
          <span className="font-medium text-fg">{hover.label ?? hover.key}</span>
          <span className="h-3 w-px bg-hud-line" />
          <span className={cn(hoverFace && !hoverFace.role && !hoverFace.locked ? "text-orange" : "text-fg-2")}>{hoverRole}</span>
        </div>
      ) : (
        selected.length > 1 &&
        step === "boundaries" && (
          <div className="hud pointer-events-none absolute left-1/2 top-3 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-1 text-label text-fg-2">
            <span className="tnum font-medium text-fg">{t("bc.nSelected", { n: selected.length })}</span>
            <span className="h-3 w-px bg-hud-line" />
            {t("bc.escClears")}
          </div>
        )
      )}

      {running && step !== "results" && <StripSkeleton />}

      {step === "mesh" && !meshExists && geometry && <MeshEmpty />}

      {step === "results" && (
        <>
          {running ? <StripSkeleton /> : <ResultsStrip />}
          <StaleBanner />
          {field && <ColorBar />}
          {resultsLoading && !field && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-body text-fg-2">
              <Spinner /> {t("results.loading")}
            </div>
          )}
          {!resultsLoading && !field && <NoResults />}
        </>
      )}

      <ViewButtons />
      <ToastView />
    </div>
  );
}

function NoResults() {
  const t = useT();
  const results = useStore((s) => s.results);
  if (results) return null;
  return (
    <div className="hud absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center gap-3 rounded-[8px] py-1 pl-3.5 pr-1 text-body text-fg-2">
      {t("results.none")}
      <button
        type="button"
        onClick={() => {
          goStep("run");
          void loadResults(false);
        }}
        className="h-7 rounded-[6px] bg-primary px-2.5 text-label font-medium text-primary-ink hover:opacity-90"
      >
        {t("results.goRun")}
      </button>
    </div>
  );
}
