import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight,
  ChartSpline,
  Check,
  Circle,
  CircleAlert,
  Crosshair,
  ExternalLink,
  FileBox,
  Hourglass,
  ImageDown,
  Info,
  Lock,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  Square,
  TriangleAlert,
  X,
  EyeOff,
  Pencil,
  Trash2,
} from "lucide-react";
import {
  caseTitle,
  change,
  checkConvergence,
  focusPeak,
  generateMesh,
  getState,
  goStep,
  isActive,
  loadField,
  runCase,
  selectFace,
  selectFaces,
  setHoverFace,
  setState,
  stopJob,
  STEPS,
  useStore,
  useT,
  EMPTY,
  renameFaceGroup,
  deleteFaceGroup,
} from "../state/store";
import type { ConvergenceStudy, StepId, UiFace, UiParam } from "../api/types";
import { exportImage } from "./ShareMenu";
import { groupColor, roleGroup } from "../viewer";
import { Button } from "./ui/Button";
import { NumberInput } from "./ui/Input";
import { Select } from "./ui/Select";
import { Slider } from "./ui/Slider";
import { Tabs } from "./ui/Tabs";
import { Tooltip } from "./ui/Tooltip";
import { Field, Kbd, SectionLabel, Spinner } from "./ui/misc";
import { cn } from "./ui/cn";
import { fmt, fmtDuration, fmtGci, fmtInt, fmtSignedPct, unitLabel } from "../lib/units";
import { STEP_ICONS } from "./stepIcons";
import { cadPhysicsOf, pickCadFile } from "./ImportCad";
import { SelectionActions } from './SelectionActions';
import { StructuralSettings, VectorInput } from './StructuralSettings';
import { ResultsTools } from './ResultsTools';

// ------------------------------------------------------------------ shared bits

function ParamField({ p }: { p: UiParam }) {
  const err = useStore((s) => s.fieldErrors[p.path]);
  const unitless = !p.unit || p.unit === "-";
  const units = unitless ? [] : (p.units ?? []).filter((u) => u !== "-");
  return (
    <Field label={p.label}>
      <NumberInput
        ariaLabel={p.label}
        value={Number(p.value)}
        unit={unitless ? undefined : p.unit}
        units={units}
        // Bounds from the server are not in a fixed unit, so only enforce the sign here;
        // the server validates the range and its 400 message is shown below.
        min={p.path.startsWith("geometry.") ? Number.MIN_VALUE : p.min_si != null && p.min_si >= 0 ? 0 : undefined}
        onCommit={(v, u) => change(p.path, { value: v, unit: u ?? (unitless ? "-" : p.unit) })}
        className={err ? "border-red" : undefined}
      />
      {err && <FieldError text={err} />}
    </Field>
  );
}

function FieldError({ text }: { text: string }) {
  return (
    <div className="prose-ui mt-1.5 flex items-start gap-1.5 text-label text-red">
      <CircleAlert size={14} className="mt-[1px] shrink-0" />
      <span>{text}</span>
    </div>
  );
}

function ParamList({ params }: { params: UiParam[] }) {
  return (
    <div className="flex flex-col gap-4">
      {params.map((p) => (
        <ParamField key={p.path} p={p} />
      ))}
    </div>
  );
}

/** Sections are separated by space (24 px), not by rules. */
function Section({ title, right, children, className }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("px-4 pt-6 first:pt-4", className)}>
      {title && <SectionLabel right={right}>{title}</SectionLabel>}
      {children}
    </section>
  );
}

/** Callout: tint + 1 px border, no side bar. Title line in text, body in text-2. */
function Callout({
  tone,
  title,
  children,
  icon,
}: {
  tone: "warn" | "error" | "info";
  title?: ReactNode;
  children?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "anim-in rounded-[8px] border p-3",
        tone === "warn" && "border-orange-line bg-orange-soft",
        tone === "error" && "border-red-line bg-red-soft",
        tone === "info" && "border-line bg-raised",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-[2px] shrink-0">
          {icon ??
            (tone === "warn" ? (
              <TriangleAlert size={16} className="text-orange" />
            ) : tone === "error" ? (
              <CircleAlert size={16} className="text-red" />
            ) : (
              <Info size={16} className="text-fg-3" />
            ))}
        </span>
        <div className="min-w-0 flex-1">
          {title && <div className="text-body font-semibold text-fg">{title}</div>}
          {children && <div className={cn("text-callout text-fg-2", !!title && "mt-1")}>{children}</div>}
        </div>
      </div>
    </div>
  );
}

function Well({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex h-8 items-center gap-2 rounded-[6px] bg-raised px-2.5 text-body text-fg", className)}>{children}</div>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-micro text-fg-2">{label}</dt>
      <dd className="tnum mt-0.5 truncate text-em font-medium text-fg">{value}</dd>
    </div>
  );
}

function fmtArea(m2: number | null | undefined): string {
  if (m2 == null || !Number.isFinite(m2)) return "";
  return m2 < 1e-2 ? `${fmt(m2 * 1e6, 3)} mm²` : `${fmt(m2, 3)} m²`;
}

// ------------------------------------------------------------------ steps

function GeometryStep() {
  const t = useT();
  const p = useStore((s) => s.payload);
  const params = p?.ui.params ?? EMPTY;
  if (!p) return null;
  const geo = params.filter((q) => q.path.startsWith("geometry."));
  const physics = p.ui.physics;
  const bbox = (p.case.geometry as { bbox?: number[][] } | undefined)?.bbox;
  const dims = bbox ? [0, 1, 2].map((i) => (bbox[1][i] - bbox[0][i]) * 1000) : null;
  return (
    <>
      {p.ui.imported ? (
        <Section title={t("geometry.source")}>
          <div className="rounded-[8px] border border-line bg-surface p-3">
            <div className="flex items-center gap-2.5">
              <FileBox size={16} className="shrink-0 text-fg-2" />
              <span className="min-w-0 flex-1 truncate text-body font-medium text-fg" title={p.ui.source_file ?? undefined}>
                {p.ui.source_file ?? caseTitle(p)}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
              <Stat label={t("geometry.faces")} value={fmtInt(p.ui.faces.length)} />
              {dims && <Stat label={t("geometry.bbox")} value={dims.map((d) => fmt(d, 3)).join(" × ") + " mm"} />}
            </dl>
          </div>
          <p className="prose-ui mt-2 text-label text-fg-3">{t("geometry.importedHint")}</p>
        </Section>
      ) : (
        <Section title={t("geometry.dimensions")}>
          <ParamList params={geo} />
          <div className="mt-4 flex items-center justify-between text-body">
            <span className="text-fg-2">{t("geometry.faces")}</span>
            <span className="tnum text-fg">{t("geometry.facesCount", { n: p.ui.faces.length })}</span>
          </div>
        </Section>
      )}
      {physics && (
        <Section>
          <Button variant="ghost" size="sm" className="-ml-2.5" onClick={() => pickCadFile(cadPhysicsOf(physics === "electric" ? p.case.physics?.kind ?? physics : physics))}>
            <FileBox size={14} />
            {t(p.ui.imported ? "geometry.importOther" : "geometry.importInstead")}
          </Button>
        </Section>
      )}
    </>
  );
}

function MeshStep() {
  const t = useT();
  const mesh = useStore((s) => s.payload?.ui.mesh);
  const busy = useStore((s) => s.meshBusy);
  const sizes = mesh?.sizes ?? ["coarse", "normal", "fine"];
  const size = mesh?.size ?? "normal";
  const idx = Math.max(0, sizes.indexOf(size));
  const st = mesh?.state;
  const stats = st?.stats;
  const needs = !st?.exists || st.stale;
  return (
    <>
      <Section title={t("mesh.size")}>
        <Slider
          ariaLabel={t("mesh.size")}
          min={0}
          max={sizes.length - 1}
          step={1}
          value={idx}
          onChange={(i) => change("mesh.size", sizes[i])}
          marks={sizes.map((s, i) => ({ value: i, label: t(`mesh.${s}`) }))}
        />
        <Button
          variant={needs ? "primary" : "secondary"}
          size="lg"
          className="mt-5 w-full justify-center"
          disabled={busy}
          onClick={() => void generateMesh()}
        >
          {busy ? <Spinner /> : <Play size={14} />}
          {busy ? t("mesh.generating") : st?.exists ? t("mesh.regenerate") : t("mesh.generate")}
        </Button>
      </Section>
      <Section title={t("mesh.stats")}>
        {st?.stale && (
          <div className="mb-3">
            <Callout tone="warn">{t("mesh.stale")}</Callout>
          </div>
        )}
        {stats ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
            <Stat label={t("mesh.nodes")} value={fmtInt(stats.nodes)} />
            <Stat label={t("mesh.elements")} value={fmtInt(stats.elements)} />
            {stats.quality_min != null && <Stat label={t("mesh.qualityMin")} value={fmt(stats.quality_min, 2)} />}
            {stats.quality_mean != null && <Stat label={t("mesh.qualityMean")} value={fmt(stats.quality_mean, 2)} />}
            {stats.element_type && <Stat label={t("mesh.elementType")} value={stats.element_type} />}
          </dl>
        ) : (
          <div className="text-body text-fg-3">{t("mesh.notYet")}</div>
        )}
      </Section>
    </>
  );
}

function PhysicsStep() {
  const t = useT();
  const p = useStore((s) => s.payload);
  if (!p) return null;
  const kind = p.ui.material_kind ?? (p.case.materials?.fluid ? "fluid" : "solid");
  const preset = String(p.case.materials?.[kind]?.preset ?? "");
  const mats = p.ui.params.filter((q) => q.path.startsWith("materials."));
  const physicsKind = p.case.physics?.kind ?? "";
  const kindLabel = t(`physics.kind.${physicsKind}`);
  return (
    <>
      <Section title={t("physics.kind")}>
        <Well>
          <Lock size={14} className="text-fg-3" />
          {kindLabel.startsWith("physics.") ? physicsKind : kindLabel}
        </Well>
      </Section>
      {p.ui.flow && <FlowSection />}
      <StructuralSettings />
      {physicsKind === "dc-current" && <Section>
        <label className="flex items-center gap-2 text-body text-fg">
          <input type="checkbox" checked={p.case.physics?.joule_heating !== false}
            onChange={(e) => change("physics.joule_heating", e.target.checked)} />
          {t("physics.jouleHeating")}
        </label>
      </Section>}
      <Section title={t("physics.material")}>
        <div className="flex flex-col gap-4">
          {p.ui.materials.length > 0 && (
            <Select
              value={preset}
              ariaLabel={t("physics.material")}
              options={p.ui.materials.map((m) => ({ value: m.id, label: m.label }))}
              onChange={(v) => change(`materials.${kind}.preset`, v)}
            />
          )}
          {mats.length > 0 && <ParamList params={mats} />}
        </div>
      </Section>
    </>
  );
}

/** "+x" -> "+X", "-x" -> "−X" (true minus sign). */
function axisLabel(id: string): string {
  return id.replace(/^-/, "−").toUpperCase();
}

const AXIS_ORDER = ["+x", "-x", "+y", "-y", "+z", "-z"];

/** External flow: free-stream direction (6 axes) and speed. */
function FlowSection() {
  const t = useT();
  const flow = useStore((s) => s.payload?.ui.flow);
  const params = useStore((s) => s.payload?.ui.params ?? EMPTY);
  const err = useStore((s) => s.fieldErrors["flow.direction"]);
  if (!flow) return null;
  const speed = params.find((q) => q.path === "flow.speed");
  const dirs = [...flow.directions].sort((a, b) => AXIS_ORDER.indexOf(a.id) - AXIS_ORDER.indexOf(b.id));
  const label = dirs.find((d) => d.id === flow.direction)?.label ?? axisLabel(flow.direction);
  return (
    <Section title={t("flow.direction")}>
      <Tabs
        size="sm"
        ariaLabel={t("flow.direction")}
        value={flow.direction}
        onChange={(v) => change("flow.direction", v)}
        items={dirs.map((d) => ({ value: d.id, label: <span className="tnum">{axisLabel(d.id)}</span>, title: d.label }))}
      />
      <p className="prose-ui mt-1.5 text-label text-fg-3">{t("flow.directionHint", { dir: label })}</p>
      {err && <FieldError text={err} />}
      {speed && (
        <div className="mt-4">
          <ParamField p={speed} />
        </div>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------ boundaries

function Swatch({ f, size = 10 }: { f: UiFace; size?: number }) {
  const theme = useStore((s) => s.theme);
  const g = f.locked ? null : roleGroup(f.role);
  return (
    <span
      className="shrink-0 rounded-[3px] ring-1 ring-inset ring-black/10 dark:ring-white/10"
      style={{
        width: size,
        height: size,
        background: f.locked ? "var(--line-strong)" : groupColor(theme, g ?? "base"),
      }}
    />
  );
}

function FaceRow({ f, selected, hovered }: { f: UiFace; selected: boolean; hovered: boolean }) {
  const t = useT();
  const roles = useStore((s) => s.payload?.ui.roles ?? EMPTY);
  const fixedRoles = useStore((s) => !!s.payload?.ui.fixed_roles);
  const flash = useStore((s) => s.flashFaces.includes(f.key));
  const hidden = useStore(s => s.hiddenFaces.includes(f.key));
  const ref = useRef<HTMLDivElement>(null);
  const single = useStore((s) => s.selectedFaces.length === 1);
  useEffect(() => {
    if (selected && single) ref.current?.scrollIntoView({ block: "nearest" });
  }, [selected, single]);
  const unassigned = !f.locked && !f.role;
  const toggle = (e: { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }) => {
    if (f.locked) return;
    if (e.shiftKey || e.ctrlKey || e.metaKey) selectFace(f.key, "toggle");
    else selectFace(selected && single ? null : f.key);
  };
  return (
    <div
      ref={ref}
      role="option"
      aria-selected={selected}
      tabIndex={f.locked ? -1 : 0}
      onClick={toggle}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) {
          e.preventDefault();
          toggle(e);
        }
      }}
      onPointerEnter={() => setHoverFace(f.key)}
      onPointerLeave={() => setHoverFace(null)}
      className={cn(
        "flex h-8 cursor-default items-center gap-2 rounded-[6px] pl-2 pr-1 transition-colors duration-[var(--dur-1)] [content-visibility:auto] [contain-intrinsic-size:auto_32px]",
        selected ? "bg-active" : flash ? "bg-orange-soft" : hovered ? "bg-hover" : "",
        f.locked && "opacity-50",
      )}
    >
      <Swatch f={f} />
      {hidden && <span title={t('bc.hidden')}><EyeOff size={12} className="text-fg-3" /></span>}
      {/* "面 1 · 平面 -X · 2,400 mm²": keep the name whole, let the description shrink (it was cut mid-number) */}
      <span className="flex min-w-0 flex-1 items-baseline gap-1.5" title={f.label}>
        <span className={cn("shrink-0 text-body", selected ? "text-fg" : "text-fg-2")}>{f.label.split(" · ")[0]}</span>
        <span className="min-w-0 truncate text-label text-fg-3">{f.label.split(" · ").slice(1).join(" · ")}</span>
      </span>
      {f.locked ? (
        <span className="flex shrink-0 items-center gap-1 pr-1.5 text-label text-fg-3">
          <Lock size={12} />
          {f.role_label ?? t("bc.locked")}
        </span>
      ) : (
        <span onClick={(e) => e.stopPropagation()} className="w-[118px] shrink-0">
          <Select
            variant="ghost"
            disabled={fixedRoles}
            value={f.role}
            placeholder={<span className="text-orange">{t("bc.unassigned")}</span>}
            ariaLabel={`${f.label} ${t("bc.role")}`}
            options={roles.map((r) => ({ value: r.id, label: r.label }))}
            onChange={(v) => {
              const keys = selected ? getState().selectedFaces : [f.key];
              for (const k of keys) change(`boundaries.${k}.role`, v);
              if (!selected) selectFace(f.key);
            }}
            renderValue={(o) => (
              <span className={cn("truncate", unassigned ? "text-orange" : "text-fg-2")}>{o?.label ?? t("bc.unassigned")}</span>
            )}
            className="h-7 w-full justify-between px-1.5 text-label"
            align="end"
            minMenuWidth={160}
          />
        </span>
      )}
    </div>
  );
}


/** Group key for the list (role id, or the unassigned / locked buckets). */
function bucket(f: UiFace) {
  return f.locked ? "__locked" : (f.role ?? "__unassigned");
}

function FaceList() {
  const t = useT();
  const faces = useStore((s) => s.payload?.ui.faces ?? EMPTY);
  const roles = useStore((s) => s.payload?.ui.roles ?? EMPTY);
  const selected = useStore((s) => s.selectedFaces);
  const hovered = useStore((s) => s.hoverFace);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const lastSelection = useRef(selected);
  const many = faces.length > 8;

  const roleLabel = (id: string) =>
    id === "__unassigned" ? t("bc.unassigned") : id === "__locked" ? t("bc.locked") : (roles.find((r) => r.id === id)?.label ?? id);

  const counts = useMemo(() => {
    const m = new Map<string, UiFace[]>();
    for (const f of faces) {
      const b = bucket(f);
      if (!m.has(b)) m.set(b, []);
      m.get(b)!.push(f);
    }
    // order: unassigned first, then the role order the backend gives, locked last
    const order = ["__unassigned", ...roles.map((r) => r.id), "__locked"];
    return [...m.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  }, [faces, roles]);

  const needle = q.trim().toLowerCase();
  const visible = faces.filter(
    (f) => (filter === "all" || bucket(f) === filter) && (!needle || f.label.toLowerCase().includes(needle) || f.key.toLowerCase() === needle),
  );
  const filterSignature = visible.map(f => f.key).join(',');
  useEffect(() => {
    setState({ faceFilter: filter !== 'all' || needle ? filterSignature.split(',').filter(Boolean) : null });
    return () => setState({ faceFilter: null });
  }, [filterSignature, filter, needle]);
  useEffect(() => {
    if (lastSelection.current !== selected && selected.length === 1 && !visible.some(f => f.key === selected[0])) {
      setQ(''); setFilter('all');
    }
    lastSelection.current = selected;
  }, [selected, filterSignature]);
  const grouped = faces.length > 12 && counts.length > 1 && filter === "all" && !needle;
  const selSet = new Set(selected);

  const rows = (list: UiFace[]) =>
    list.map((f) => <FaceRow key={f.key} f={f} selected={selSet.has(f.key)} hovered={hovered === f.key} />);

  return (
    <div>
      {many && (
        <div className="mb-2 flex h-8 items-center gap-2 rounded-[6px] border border-line-strong bg-field px-2.5 focus-within:outline-2 focus-within:-outline-offset-1 focus-within:outline-[var(--focus)]">
          <Search size={14} className="shrink-0 text-fg-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQ("")}
            placeholder={t("bc.search", { n: faces.length })}
            aria-label={t("bc.search", { n: faces.length })}
            className="min-w-0 flex-1 bg-transparent text-body text-fg outline-none placeholder:text-fg-3 focus-visible:outline-none"
          />
          {q && (
            <button type="button" aria-label={t("common.clear")} onClick={() => setQ("")} className="text-fg-3 hover:text-fg">
              <X size={14} />
            </button>
          )}
        </div>
      )}
      {/* role filter chips double as the viewport legend */}
      <div className="mb-2 flex flex-wrap gap-1">
        {counts.length > 1 && (
          <FilterChip on={filter === "all"} onClick={() => setFilter("all")}>
            {t("bc.all")}
            <span className="tnum text-fg-3">{faces.length}</span>
          </FilterChip>
        )}
        {counts.map(([id, list]) => (
          <FilterChip key={id} on={filter === id} onClick={() => setFilter(filter === id ? "all" : id)}>
            <Swatch f={list[0]} size={8} />
            <span className={id === "__unassigned" ? "text-orange" : undefined}>{roleLabel(id)}</span>
            <span className="tnum text-fg-3">{list.length}</span>
          </FilterChip>
        ))}
      </div>
      <div role="listbox" aria-multiselectable className={cn("-mx-1 flex flex-col gap-px px-1", many && "max-h-[min(34vh,300px)] overflow-y-auto")}>
        {grouped
          ? counts.map(([id, list]) => (
              <div key={id} className="pb-1.5">
                <div className="sticky top-0 z-[1] flex h-7 items-center gap-2 bg-bg px-2 text-label text-fg-3">
                  <span className="font-medium">{roleLabel(id)}</span>
                  <span className="tnum">{list.length}</span>
                </div>
                {rows(list)}
              </div>
            ))
          : rows(visible)}
        {visible.length === 0 && <div className="px-2 py-3 text-body text-fg-3">{t("bc.noMatch")}</div>}
      </div>
      {(filter !== "all" || needle) && visible.length > 1 && (
        <Button variant="ghost" size="sm" className="-ml-2.5 mt-1" onClick={() => selectFaces(visible.filter((f) => !f.locked).map((f) => f.key))}>
          {t("bc.selectShown", { n: visible.length })}
        </Button>
      )}
    </div>
  );
}

function FilterChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-[4px] border px-1.5 text-label transition-colors duration-[var(--dur-1)]",
        on ? "border-line-strong bg-active text-fg" : "border-transparent bg-raised text-fg-2 hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

type FaceValue = { value: number | number[]; unit: string } | string;

function sameValue(a: FaceValue | undefined, b: FaceValue | undefined) {
  if (typeof a === "string" || typeof b === "string") return a === b;
  return !!a && !!b && JSON.stringify(a.value) === JSON.stringify(b.value) && a.unit === b.unit;
}

/** Edits the role and values of every selected face at once (one PATCH). */
function SelectionEditor() {
  const t = useT();
  const p = useStore((s) => s.payload);
  const selected = useStore((s) => s.selectedFaces);
  const errors = useStore((s) => s.fieldErrors);
  if (!p) return null;
  const ui = p.ui;
  const sel = ui.faces.filter((f) => selected.includes(f.key) && !f.locked);

  if (sel.length === 0) {
    // summary of faces that carry values, so loads are visible without a selection
    const withValues = ui.faces.filter((f) => f.values && Object.keys(f.values).length > 0);
    const legacy = !ui.role_fields ? ui.params.filter((q) => q.path.startsWith("boundaries.")) : [];
    return (
      <>
        {withValues.length > 0 && (
          <Section title={t("bc.values")}>
            <details open={withValues.length <= 5}>
            <summary className="h-8 cursor-pointer text-label text-fg-2">{t('bc.values')} ({withValues.length})</summary>
            <ul className="-mx-2 flex flex-col">
              {withValues.map((f) => (
                <li key={f.key}>
                  <button
                    type="button"
                    onClick={() => selectFace(f.key)}
                    onPointerEnter={() => setHoverFace(f.key)}
                    onPointerLeave={() => setHoverFace(null)}
                    className="flex w-full items-start gap-2 rounded-[6px] px-2 py-1.5 text-left hover:bg-hover"
                  >
                    <span className="mt-[5px]">
                      <Swatch f={f} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body text-fg">{f.label}</span>
                      <span className="tnum block truncate text-label text-fg-2">
                        {f.role_label}
                        {"  "}
                        {describeValues(f, ui.directions)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            </details>
          </Section>
        )}
        {legacy.length > 0 && withValues.length === 0 && (
          <Section title={t("bc.values")}>
            <ParamList params={legacy} />
          </Section>
        )}
        <Section>
          <p className="prose-ui text-label text-fg-3">{t("bc.pickHint")}</p>
        </Section>
      </>
    );
  }

  const roles = ui.roles;
  const commonRole = sel.every((f) => f.role === sel[0].role) ? sel[0].role : null;
  const fields = commonRole ? (ui.role_fields?.[commonRole] ?? null) : null;
  const keys = sel.map((f) => f.key);
  const single = sel.length === 1 ? sel[0] : null;

  const legacyParams = !ui.role_fields && single ? ui.params.filter((q) => q.path.startsWith(`boundaries.${single.key}.`) && !q.path.endsWith(".role")) : [];

  return (
    <Section
      title={single ? t("bc.selected") : t("bc.nSelected", { n: sel.length })}
      right={
        <button type="button" onClick={() => selectFace(null)} className="flex h-6 items-center gap-1 rounded-[4px] px-1.5 text-label text-fg-3 hover:bg-hover hover:text-fg">
          {t("common.clear")}
          <Kbd className="ml-0.5">Esc</Kbd>
        </button>
      }
    >
      <div className="anim-in rounded-[8px] border border-line bg-surface p-3">
        {single ? (
          <div className="mb-3 flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate text-body font-medium text-fg">{single.label}</span>
            {single.area_m2 != null && <span className="tnum shrink-0 text-label text-fg-3">{fmtArea(single.area_m2)}</span>}
          </div>
        ) : (
          <div className="mb-3 flex flex-wrap gap-1">
            {sel.slice(0, 6).map((f) => (
              <span key={f.key} className="inline-flex h-6 max-w-[132px] items-center gap-1.5 rounded-[4px] bg-raised px-1.5 text-label text-fg-2">
                <Swatch f={f} size={8} />
                <span className="truncate">{f.label}</span>
              </span>
            ))}
            {sel.length > 6 && <span className="inline-flex h-6 items-center px-1 text-label text-fg-3">+{sel.length - 6}</span>}
          </div>
        )}
        <div className="flex flex-col gap-4">
          {p.case.physics?.analysis === 'modal' && commonRole && ['load','pressure','moment','bearing','remote-force'].includes(commonRole) && <p className="prose-ui text-label text-fg-2">{t('struct.loadsIgnored')}</p>}
          <Field label={t("bc.role")} hint={ui.fixed_roles ? t("bc.fixedRoles") : undefined}>
            <Select
              disabled={!!ui.fixed_roles}
              value={commonRole}
              placeholder={<span className={sel.some((f) => !f.role) ? "text-orange" : "text-fg-3"}>{sel.some((f) => !f.role) ? t("bc.unassigned") : t("bc.mixed")}</span>}
              ariaLabel={t("bc.role")}
              options={roles.map((r) => ({ value: r.id, label: r.label }))}
              onChange={(v) => {
                for (const k of keys) change(`boundaries.${k}.role`, v);
              }}
            />
          </Field>
          {fields === null && sel.length > 1 && <p className="text-label text-fg-3">{t("bc.mixedRoles")}</p>}
          {(fields ?? []).map((field) => {
            const label = ui.field_labels?.[field] ?? field;
            const vals = sel.map((f) => f.values?.[field]);
            const mixed = !vals.every((v) => sameValue(v, vals[0]));
            const err = keys.map((k) => errors[`boundaries.${k}.${field}`]).find(Boolean);
            if (field === "direction") {
              const cur = typeof vals[0] === "string" ? (vals[0] as string) : null;
              return (
                <Field key={field} label={label} hint={mixed ? t("bc.mixedValues") : undefined}>
                  <Select
                    value={mixed ? null : cur}
                    placeholder={<span className="text-fg-3">{t("bc.mixed")}</span>}
                    ariaLabel={label}
                    options={(ui.directions ?? []).map((d) => ({ value: d.id, label: d.label }))}
                    onChange={(v) => {
                      for (const k of keys) change(`boundaries.${k}.${field}`, v);
                    }}
                  />
                  {err && <FieldError text={err} />}
                </Field>
              );
            }
            if (field === "components") {
              // constraint: which displacement components are held, a non-empty subset of "xyz"
              const cur = mixed || typeof vals[0] !== "string" ? "" : (vals[0] as string);
              return (
                <Field key={field} label={label} hint={mixed ? t("bc.mixedValues") : undefined}>
                  <div className="flex gap-1" role="group" aria-label={label}>
                    {(["x", "y", "z"] as const).map((c) => {
                      const on = cur.includes(c);
                      return (
                        <button
                          key={c}
                          type="button"
                          aria-pressed={on}
                          onClick={() => {
                            const next = "xyz".split("").filter((d) => (d === c ? !on : cur.includes(d))).join("");
                            if (!next) return; // at least one component stays held
                            for (const k of keys) change(`boundaries.${k}.${field}`, next);
                          }}
                          className={cn(
                            "h-8 w-10 rounded-[6px] border text-body font-medium uppercase transition-colors duration-[var(--dur-1)]",
                            on ? "border-line-strong bg-active text-fg" : "border-line text-fg-3 hover:bg-hover hover:text-fg",
                          )}
                        >
                          {c}
                        </button>
                      );
                    })}
                  </div>
                  {err && <FieldError text={err} />}
                </Field>
              );
            }
            if (field === 'point') {
              const q = vals[0];
              const v = typeof q === 'object' && Array.isArray(q.value) ? q.value : [0,0,0];
              const unit = typeof q === 'object' ? q.unit : 'mm';
              return <Field key={field} label={label}><VectorInput label={label} value={v} unit={unit}
                onCommit={v => { for (const k of keys) change(`boundaries.${k}.point`,{value:v,unit}); }} />{err && <FieldError text={err} />}</Field>;
            }
            const v0 = vals.find((v) => v && typeof v !== "string") as { value: number; unit: string } | undefined;
            const units = ui.field_units?.[field] ?? (v0 ? [v0.unit] : []);
            return (
              <Field key={field} label={label} hint={mixed ? t("bc.mixedValues") : undefined}>
                <NumberInput
                  ariaLabel={label}
                  value={v0?.value ?? NaN}
                  unit={v0?.unit ?? units[0]}
                  units={units}
                  onCommit={(v, u) => {
                    for (const k of keys) change(`boundaries.${k}.${field}`, { value: v, unit: u ?? v0?.unit ?? units[0] });
                  }}
                  className={err ? "border-red" : undefined}
                />
                {err && <FieldError text={err} />}
              </Field>
            );
          })}
          {legacyParams.length > 0 && <ParamList params={legacyParams} />}
          {fields && fields.length === 0 && commonRole && <p className="text-label text-fg-3">{t("bc.noValues")}</p>}
          {((p.case.physics?.kind === "dc-current" && p.case.physics.joule_heating !== false) || p.case.physics?.thermal_load?.mode === 'solve') && <ThermalEditor faces={sel} />}
        </div>
        <div className="mt-3"><SelectionActions groups /></div>
      </div>
    </Section>
  );
}

function ThermalEditor({ faces }: { faces: UiFace[] }) {
  const t = useT();
  const ui = useStore((s) => s.payload!.ui);
  const errors = useStore((s) => s.fieldErrors);
  const role = faces.every((f) => f.thermal?.role === faces[0].thermal?.role) ? faces[0].thermal?.role ?? "insulated" : null;
  const fields = role ? ui.role_fields?.[role] ?? [] : [];
  return <div className="mt-2 flex flex-col gap-4">
    <SectionLabel>{t("bc.thermalCondition")}</SectionLabel>
    <Select value={role} ariaLabel={t("bc.thermalCondition")} placeholder={t("bc.mixed")}
      options={(ui.thermal_roles ?? []).map((r) => ({ value: r.id, label: r.label }))}
      onChange={(v) => { for (const f of faces) change(`boundaries.${f.key}.thermal.role`, v); }} />
    {fields.map((field) => {
      const values = faces.map((f) => f.thermal?.[field]);
      const mixed = !values.every((v) => sameValue(v, values[0]));
      const value = values.find((v) => v && typeof v !== "string") as { value: number; unit: string } | undefined;
      const units = ui.field_units?.[field] ?? [];
      const label = ui.field_labels?.[field] ?? field;
      const err = faces.map((f) => errors[`boundaries.${f.key}.thermal.${field}`]).find(Boolean);
      return <Field key={field} label={label} hint={mixed ? t("bc.mixedValues") : undefined}>
        <NumberInput ariaLabel={label} value={value?.value ?? NaN} unit={value?.unit ?? units[0]} units={units}
          onCommit={(v, u) => { for (const f of faces) change(`boundaries.${f.key}.thermal.${field}`, { value: v, unit: u ?? value?.unit ?? units[0] }); }} />
        {err && <FieldError text={err} />}
      </Field>;
    })}
  </div>;
}

function describeValues(f: UiFace, directions?: { id: string; label: string }[]): string {
  const v = f.values ?? {};
  return Object.entries(v)
    .map(([, x]) => (typeof x === "string" ? (directions?.find((d) => d.id === x)?.label ?? x) : `${Array.isArray(x.value) ? x.value.map(v => fmt(v,4)).join(', ') : fmt(x.value, 4)} ${unitLabel(x.unit)}`))
    .join("   ");
}

/** Conceptual (not to scale) side view of the tunnel the backend builds around the body. */
function TunnelDiagram() {
  const t = useT();
  const D = "var(--text-3)";
  const B = "var(--text-2)";
  return (
    <svg viewBox="0 0 288 124" className="block h-auto w-full" role="img" aria-label={t("bc.external.tunnel")}>
      <text x="144" y="13" textAnchor="middle" fontSize="12" fill={D}>
        {t("bc.external.sides")}
      </text>
      <rect x="10" y="22" width="268" height="88" rx="2" fill="none" stroke={D} strokeWidth="1" strokeDasharray="4 3" />
      <line x1="10" y1="22" x2="10" y2="110" stroke={B} strokeWidth="2" />
      <line x1="278" y1="22" x2="278" y2="110" stroke={B} strokeWidth="2" />
      {[46, 66, 86].map((y) => (
        <g key={y}>
          <line x1="20" y1={y} x2="46" y2={y} stroke={B} strokeWidth="1.2" />
          <path d={`M41 ${y - 3.5} 47 ${y} 41 ${y + 3.5}`} fill="none" stroke={B} strokeWidth="1.2" />
        </g>
      ))}
      <path d="M104 58 C 140 61 190 63 262 64 M104 74 C 140 71 190 69 262 68" fill="none" stroke={D} strokeWidth="1" strokeDasharray="3 3" />
      <circle cx="94" cy="66" r="11" fill="var(--raised)" stroke={B} strokeWidth="1.4" />
      <text x="94" y="96" textAnchor="middle" fontSize="12" fill={B}>
        {t("bc.external.body3d")}
      </text>
      <text x="18" y="38" fontSize="12" fill={B}>
        {t("bc.external.inlet")}
      </text>
      <text x="270" y="38" textAnchor="end" fontSize="12" fill={B}>
        {t("bc.external.outlet")}
      </text>
    </svg>
  );
}

/** External flow: the body is all wall; the tunnel is generated. Nothing to assign. */
function ExternalBoundaries() {
  const t = useT();
  const faces = useStore((s) => s.payload?.ui.faces ?? EMPTY);
  const flow = useStore((s) => s.payload?.ui.flow);
  const dirLabel = flow ? (flow.directions.find((d) => d.id === flow.direction)?.label ?? axisLabel(flow.direction)) : null;
  return (
    <>
      <Section
        title={t("bc.external.title")}
        right={<span className="tnum text-label text-fg-3">{t("bc.external.faces", { n: faces.length })}</span>}
      >
        <p className="prose-ui text-body text-fg-2">{t("bc.external.body")}</p>
      </Section>
      <Section
        title={t("bc.external.tunnel")}
        right={
          dirLabel && (
            <Tooltip content={t("flow.direction")} side="left">
              <button type="button" onClick={() => goStep("physics")} className="text-label text-accent-text underline-offset-2 hover:underline">
                {dirLabel}
              </button>
            </Tooltip>
          )
        }
      >
        <div className="rounded-[8px] bg-raised px-2 pb-2 pt-2.5">
          <TunnelDiagram />
        </div>
        <p className="prose-ui mt-2 text-label text-fg-3">{t("bc.external.size")}</p>
      </Section>
    </>
  );
}

function BoundariesStep() {
  const t = useT();
  const faces = useStore((s) => s.payload?.ui.faces ?? EMPTY);
  const external = useStore((s) => s.payload?.ui.physics === "external");
  const unassigned = faces.filter((f) => !f.locked && !f.role).length;
  if (external) return <ExternalBoundaries />;
  return (
    <>
      <FaceGroups />
      <Section
        title={t("bc.faces")}
        right={
          unassigned > 0 ? (
            <span className="tnum text-label text-orange">{t("bc.unassignedCount", { n: unassigned })}</span>
          ) : (
            <span className="tnum text-label text-fg-3">{t("geometry.facesCount", { n: faces.length })}</span>
          )
        }
      >
        <FaceList />
      </Section>
      <SelectionEditor />
    </>
  );
}

function FaceGroups() {
  const t = useT();
  const groups = useStore(s => s.payload?.case.face_groups);
  if (!groups || !Object.keys(groups).length) return null;
  return <Section title={t('bc.groups')}>
    {Object.entries(groups).map(([name, keys]) => <div key={name} className="flex h-8 items-center gap-1 text-body text-fg-2">
      <button className="min-w-0 flex-1 truncate text-left hover:text-fg" onClick={() => selectFaces(keys)}>{name} ({keys.length})</button>
      <button className="flex h-8 w-8 items-center justify-center rounded-[6px] hover:bg-hover" title={t('bc.renameGroup')} aria-label={t('bc.renameGroup')}
        onClick={() => { const next = window.prompt(t('bc.groupName'), name); if (next) renameFaceGroup(name, next); }}><Pencil size={14} strokeWidth={1.5} /></button>
      <button className="flex h-8 w-8 items-center justify-center rounded-[6px] hover:bg-hover" title={t('bc.deleteGroup')} aria-label={t('bc.deleteGroup')}
        onClick={() => deleteFaceGroup(name)}><Trash2 size={14} strokeWidth={1.5} /></button>
    </div>)}
  </Section>;
}

// ------------------------------------------------------------------ run

const STUDY_LEVELS = ["coarse", "normal", "fine"] as const;

/**
 * The active job: progress, message, Stop. A queued job (waiting for the machine's single
 * solver slot) reads as calm waiting, not as an error. A convergence study also shows which
 * of its three meshes is being solved.
 */
function JobCard() {
  const t = useT();
  const job = useStore((s) => s.job);
  const stopping = useStore((s) => s.stopping);
  if (!job || !isActive(job)) return null;
  const queued = job.state === "queued";
  const progress = job.progress ?? 0;
  const level = queued ? -1 : Math.min(2, Math.floor(progress * 3));
  return (
    <div className="anim-in rounded-[8px] border border-line bg-surface p-3">
      <div className="flex items-center justify-between gap-2 text-body">
        <span className="flex min-w-0 items-center gap-2 font-medium text-fg">
          {queued ? <Hourglass size={14} className="shrink-0 text-fg-3" /> : <Spinner className="shrink-0 text-accent-text" />}
          <span className="truncate">{queued ? t("job.state.queued") : job.study ? t("conv.running") : t(`job.state.${job.state}`)}</span>
        </span>
        {!queued && <span className="tnum shrink-0 text-fg-2">{Math.round(progress * 100)}%</span>}
      </div>
      {!queued && (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-line">
          <div
            className="h-full rounded-full bg-accent-fill transition-[width] duration-300 ease-[var(--ease-out)]"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      )}
      {job.study && (
        <ol className="mt-2.5 flex items-center gap-1 text-label">
          {STUDY_LEVELS.map((size, i) => (
            <li key={size} className="flex min-w-0 items-center gap-1">
              {i > 0 && <span className="mx-0.5 h-px w-3 shrink-0 bg-line-strong" />}
              {i < level ? (
                <Check size={12} className="shrink-0 text-green" />
              ) : i === level ? (
                <Spinner size={12} className="shrink-0 text-fg-2" />
              ) : (
                <Circle size={12} className="shrink-0 text-fg-3" />
              )}
              <span className={cn("truncate", i === level ? "text-fg" : "text-fg-3")}>{t(`mesh.${size}`)}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="mt-2 flex items-center justify-between gap-2 text-label text-fg-3">
        <span className="prose-ui min-w-0">{queued ? t("job.waiting") : job.message}</span>
        {!queued && job.eta_s != null && <span className="tnum shrink-0">{t("job.eta", { t: fmtDuration(job.eta_s) })}</span>}
      </div>
      <Button variant="danger" className="mt-3 w-full justify-center" onClick={() => void stopJob()} disabled={stopping}>
        <Square size={10} fill="currentColor" />
        {stopping ? t("job.stopping") : t("job.stop")}
      </Button>
    </div>
  );
}

function RunStep() {
  const t = useT();
  const p = useStore((s) => s.payload);
  const job = useStore((s) => s.job);
  const runBusy = useStore((s) => s.runBusy);
  if (!p) return null;
  const mode = (p.case.run?.mode as "preview" | "final") ?? "preview";
  const allModes = p.ui.modes ?? [
    { id: "preview" as const, engine: p.engine ?? null },
    { id: "final" as const, engine: null },
  ];
  // offer only modes that have an engine (imported flow runs only as "final")
  const withEngine = allModes.filter((m) => m.engine);
  const modes = withEngine.length ? withEngine : allModes;
  const engine = modes.find((m) => m.id === mode)?.engine ?? (modes.length === 1 ? modes[0].engine : null);
  const errors = p.checks.filter((c) => c.level === "error");
  const ready = p.ready ?? errors.length === 0;
  const active = isActive(job);
  const engineLabel = (e: string) => {
    const k = `engine.${e}`;
    const s = t(k);
    return s === k ? e : s;
  };
  return (
    <>
      <Section title={t("run.mode")}>
        {modes.length > 1 ? (
          <Tabs
            ariaLabel={t("run.mode")}
            value={mode}
            onChange={(v) => change("run.mode", v)}
            items={modes.map((m) => ({ value: m.id, label: t(m.id === "final" ? "run.final" : "run.preview") }))}
          />
        ) : (
          <Well>
            <Lock size={14} className="text-fg-3" />
            {t(modes[0]?.id === "preview" ? "run.preview" : "run.final")}
          </Well>
        )}
        <p className="prose-ui mt-2 text-label text-fg-3">
          {t(
            modes.length === 1 && p.ui.physics === "external"
              ? "run.externalOnlyFinal"
              : modes.length === 1 && (p.ui.physics === "cfd" || p.ui.physics === "flow")
                ? "run.flowOnlyFinal"
                : mode === "final"
                  ? "run.finalHint"
                  : "run.previewHint",
          )}
        </p>
      </Section>
      <Section title={t("run.engine")}>
        {engine ? (
          <Well className="justify-between">
            <span>{engineLabel(engine)}</span>
            {engine.startsWith("builtin") && <span className="text-label text-fg-3">{t("engine.builtin.hint")}</span>}
          </Well>
        ) : (
          <Callout tone="warn" title={t("run.engineMissingTitle")}>
            {t("run.engineMissing")}
          </Callout>
        )}
      </Section>
      <Section>
        {!ready && (
          <div className="mb-3">
            <Callout tone="error" title={t("run.blocked")}>
              <ul className="flex list-disc flex-col gap-1 pl-4">
                {errors.slice(0, 3).map((c, i) => (
                  <li key={i}>{c.message}</li>
                ))}
              </ul>
            </Callout>
          </div>
        )}
        {active && job ? (
          <JobCard />
        ) : (
          <Tooltip content={!ready ? t("run.blocked") : !engine ? t("run.engineMissing") : ""} className="w-full" side="top">
            <Button
              variant="primary"
              size="lg"
              className="w-full justify-center"
              disabled={!ready || !engine || runBusy}
              onClick={() => void runCase(mode)}
            >
              {runBusy ? <Spinner /> : <Play size={14} />}
              {runBusy ? t("run.starting") : t("run.start")}
            </Button>
          </Tooltip>
        )}
      </Section>
    </>
  );
}

// ------------------------------------------------------------------ results

/** ran → converged → verified as one quiet stepper. Only "verified" gets a tint. */
function GateStepper() {
  const t = useT();
  const gates = useStore((s) => s.results?.gates);
  const conv = useStore((s) => s.results?.verification?.kind === "convergence");
  if (!gates) return null;
  const items = [
    { k: "ran", on: gates.ran },
    { k: "converged", on: gates.converged },
    { k: "verified", on: gates.verified },
  ];
  return (
    <div className="flex items-center">
      {items.map((g, i) => (
        <div key={g.k} className="flex min-w-0 items-center">
          {i > 0 && <span className="mx-1 h-px w-3 shrink-0 bg-line-strong" />}
          <Tooltip content={t(g.k === "verified" && conv ? "gate.verified.tipConv" : `gate.${g.k}.tip`)}>
            <span
              className={cn(
                "inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-[11px] px-2 text-label font-medium",
                !g.on && "text-fg-3",
                g.on && g.k !== "verified" && "text-fg",
                g.on && g.k === "verified" && "bg-green-soft text-green",
              )}
            >
              {!g.on ? (
                <Circle size={12} className="text-fg-3" />
              ) : g.k === "verified" ? (
                <ShieldCheck size={12} />
              ) : (
                <Check size={12} className="text-green" />
              )}
              {t(`gate.${g.k}`)}
            </span>
          </Tooltip>
        </div>
      ))}
    </div>
  );
}

export function VerificationLine({ compact }: { compact?: boolean }) {
  const t = useT();
  const v = useStore((s) => s.results?.verification);
  if (!v) return null;
  const u = v.unit && v.unit !== "-" ? ` ${unitLabel(v.unit)}` : "";
  return (
    <span className={cn("tnum inline-flex flex-wrap items-baseline gap-x-1.5", compact ? "text-label" : "text-body")}>
      <span className="text-fg-3">{v.reference_label ?? t("verify.reference")}</span>
      <span className="text-fg">
        {fmt(v.reference, 4)}
        {u}
      </span>
      <span className="ml-2 text-fg-3">{t("verify.computed")}</span>
      <span className="text-fg">
        {fmt(v.computed, 4)}
        {u}
      </span>
      <span className="ml-2 text-fg-3">{t("verify.diff")}</span>
      <span className={cn("inline-flex items-center gap-0.5 font-medium", v.pass ? "text-green" : "text-red")}>
        {fmtSignedPct(v.error_pct)}
        {v.pass ? <Check size={12} /> : <X size={12} />}
      </span>
    </span>
  );
}

// ------------------------------------------------------------------ mesh convergence

/** Start (or show the progress of) a mesh convergence study. */
function ConvergenceAction({ variant }: { variant: "primary" | "secondary" | "again" }) {
  const t = useT();
  const job = useStore((s) => s.job);
  const runBusy = useStore((s) => s.runBusy);
  const stale = useStore((s) => !!s.results?.stale);
  const offline = useStore((s) => s.mode === "mock");
  if (isActive(job) && job?.study) {
    return (
      <div className="mt-3">
        <JobCard />
      </div>
    );
  }
  const disabled = isActive(job) || runBusy || stale || offline;
  const why = stale ? t("results.stale") : isActive(job) ? t("run.alreadyRunning") : "";
  if (variant === "again") {
    return (
      <Tooltip content={why}>
        <Button variant="ghost" size="sm" className="-ml-2.5 mt-2" disabled={disabled} onClick={() => void checkConvergence()}>
          <RotateCcw size={12} />
          {t("conv.recheck")}
        </Button>
      </Tooltip>
    );
  }
  const primary = variant === "primary";
  return (
    <div className={primary ? "mt-3" : "mt-2.5"}>
      <Tooltip content={why} className={primary ? "w-full" : undefined} side="top">
        <Button
          variant={primary ? "primary" : "secondary"}
          size={primary ? "lg" : "md"}
          className={primary ? "w-full justify-center" : undefined}
          disabled={disabled}
          onClick={() => void checkConvergence()}
        >
          {runBusy ? <Spinner /> : <ChartSpline size={14} />}
          {runBusy ? t("run.starting") : t("conv.check")}
        </Button>
      </Tooltip>
      <p className="prose-ui mt-2 text-label text-fg-3">{t("conv.checkHint")}</p>
    </div>
  );
}

/** Compact level label for element counts: 8 240 -> "8.2k". */
function fmtCount(n: number): string {
  if (n >= 1e6) return `${fmt(n / 1e6, 2)}M`;
  if (n >= 1e4) return `${fmt(n / 1e3, 3)}k`;
  return fmtInt(n);
}

/** Fewest significant digits (≥ min) that tell the values apart, so close levels do not read as equal. */
function distinctDigits(values: number[], min = 4, max = 7): number {
  for (let d = min; d <= max; d++) if (new Set(values.map((v) => fmt(v, d))).size === new Set(values).size) return d;
  return max;
}

/** Value against number of elements (log x), 3 points + the dashed extrapolated level. */
function ConvChart({ c }: { c: ConvergenceStudy }) {
  const t = useT();
  const W = 264;
  const H = 92;
  const R = 10;
  const T = 10;
  const B = 20;
  const xs = c.levels.map((l) => Math.log10(Math.max(1, l.elements)));
  const vals = [...c.levels.map((l) => l.value), c.extrapolated].filter(Number.isFinite);
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.18;
  lo -= pad;
  hi += pad;
  const ticks = [hi - pad, lo + pad];
  const td = distinctDigits(ticks, 3);
  const tickText = ticks.map((v) => fmt(v, td));
  // left gutter wide enough for the longest tick label (11 px tabular digits ≈ 6.6 px each)
  const L = Math.max(30, Math.ceil(Math.max(...tickText.map((s) => s.length)) * 6.6) + 12);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const X = (x: number) => L + ((x - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const pts = c.levels.map((l, i) => [X(xs[i]), Y(l.value)] as const);
  const ye = Y(c.extrapolated);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label={t("conv.chartLabel")}>
      <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="var(--line-strong)" strokeWidth="1" />
      {ticks.map((v, i) => (
        <text key={i} x={L - 6} y={Y(v) + 4} textAnchor="end" fontSize="11" fill="var(--text-3)" className="tnum">
          {tickText[i]}
        </text>
      ))}
      {Number.isFinite(ye) && <line x1={L} y1={ye} x2={W - R} y2={ye} stroke="var(--text-3)" strokeWidth="1" strokeDasharray="3 3" />}
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="var(--text-2)" strokeWidth="1.5" />
      {pts.map(([px, py], i) => (
        <g key={i}>
          <circle cx={px} cy={py} r={i === pts.length - 1 ? 3.5 : 3} fill={i === pts.length - 1 ? "var(--text)" : "var(--raised)"} stroke="var(--text)" strokeWidth="1.5" />
          <text x={px} y={H - 5} textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"} fontSize="11" fill="var(--text-3)" className="tnum">
            {fmtCount(c.levels[i].elements)}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Mesh study result: chart, the three levels, GCI against its tolerance and the observed order. */
function ConvergenceBlock({ c }: { c: ConvergenceStudy }) {
  const t = useT();
  const u = c.unit && c.unit !== "-" ? unitLabel(c.unit) : "";
  const vd = distinctDigits([...c.levels.map((l) => l.value), c.extrapolated]);
  return (
    <>
      <div className="anim-in rounded-[8px] bg-raised">
        <div className="px-3 pb-1 pt-3">
          <ConvChart c={c} />
        </div>
        <div className="tnum px-3 pb-1 text-body">
          <div className="grid h-7 grid-cols-[1fr_auto_88px] items-center gap-3 text-micro text-fg-2">
            <span className="truncate">{c.label}</span>
            <span className="text-right">{t("conv.elements")}</span>
            <span className="text-right">{u ? `${t("conv.value")} [${u}]` : t("conv.value")}</span>
          </div>
          {c.levels.map((l) => (
            <div key={l.size} className="grid h-7 grid-cols-[1fr_auto_88px] items-center gap-3 border-t border-line">
              <span className={cn("truncate", l.size === "fine" ? "text-fg" : "text-fg-2")}>{t(`mesh.${l.size}`)}</span>
              <span className="text-right text-fg-2">{fmtInt(l.elements)}</span>
              <span className={cn("text-right", l.size === "fine" ? "font-medium text-fg" : "text-fg")}>{fmt(l.value, vd)}</span>
            </div>
          ))}
          <div className="grid h-7 grid-cols-[1fr_auto_88px] items-center gap-3 border-t border-line">
            <span className="flex items-center gap-1.5 truncate text-fg-2">
              <svg width="14" height="2" aria-hidden className="shrink-0">
                <line x1="0" y1="1" x2="14" y2="1" stroke="var(--text-3)" strokeWidth="1.5" strokeDasharray="3 2" />
              </svg>
              {t("conv.extrapolated")}
            </span>
            <span className="text-right text-fg-3">—</span>
            <span className="text-right text-fg-2">{fmt(c.extrapolated, vd)}</span>
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-label">
        <span className={cn("tnum inline-flex items-center gap-1 whitespace-nowrap font-medium", c.pass ? "text-green" : "text-orange")}>
          {c.pass ? <Check size={14} /> : <TriangleAlert size={14} />}
          {t("conv.gci", { g: fmtGci(c.gci_pct), t: fmt(c.tolerance_pct, 3) })}
        </span>
        <span className="tnum whitespace-nowrap text-fg-2">{t("conv.order", { p: fmt(c.observed_order, 2) })}</span>
      </div>
      {c.pass ? (
        <p className="prose-ui mt-1.5 text-label text-fg-3">{t("conv.pass")}</p>
      ) : (
        <div className="mt-2.5">
          <Callout tone="warn" title={t("conv.notYet")}>
            {t("conv.notYetBody")}
          </Callout>
        </div>
      )}
      {!c.monotone && <p className="prose-ui mt-1.5 text-label text-fg-3">{t("conv.oscillating")}</p>}
    </>
  );
}

function ResultsStep() {
  const t = useT();
  const r = useStore((s) => s.results);
  const field = useStore((s) => s.field);
  const quantity = useStore((s) => s.quantity);
  const colormap = useStore((s) => s.colormap);
  const range = useStore((s) => s.range);
  const deform = useStore((s) => s.deformScale);
  const caseId = useStore((s) => s.payload?.case.case_id);
  const offline = useStore((s) => s.mode === "mock");
  if (!r) {
    return (
      <Section>
        <div className="text-body text-fg-3">{t("results.none")}</div>
        <Button className="mt-3" onClick={() => goStep("run")}>
          {t("results.goRun")} <ArrowRight size={14} />
        </Button>
      </Section>
    );
  }
  const v = r.verification;
  const conv = r.convergence ?? null;
  const warnings = r.warnings ?? [];
  const autoK = field?.auto_deform_scale ?? 1;
  const k = deform ?? autoK;
  const hasDisp = !!field?.displacement?.length;
  const noRefReason = !v ? (typeof r.gates_detail?.verified === "string" ? r.gates_detail.verified : null) : null;
  return (
    <>
      <Section
        title={t("results.gates")}
        right={
          <Tooltip content={t("results.verifiedNotSafe")} side="left">
            <button type="button" className="flex items-center gap-1 rounded-[4px] text-label text-accent-text hover:underline">
              <Info size={12} />
              {t("results.whatVerified")}
            </button>
          </Tooltip>
        }
      >
        <GateStepper />
        {warnings.length > 0 && (
          <div className="mt-3 flex flex-col gap-2">
            {warnings.map((w) => (
              <Callout key={w.code} tone="warn" title={t(`results.warning.${w.code}`) === `results.warning.${w.code}` ? t("results.warning.generic") : t(`results.warning.${w.code}`)}>
                <span className="tnum">{w.message}</span>
                {r.gates.verified && (
                  <span className="mt-2 flex items-start gap-1.5">
                    <Info size={14} className="mt-[2px] shrink-0 text-fg-3" />
                    <span>{t("results.verifiedNotSafe")}</span>
                  </span>
                )}
              </Callout>
            ))}
          </div>
        )}
        {r.stale && (
          <div className="mt-3">
            <Callout tone="info" icon={<RotateCcw size={16} className="text-fg-3" />}>
              {t("results.stale")}
            </Callout>
          </div>
        )}
      </Section>
      {v?.kind === "convergence" && conv ? (
        // no analytic reference: the mesh study IS the verification
        <Section title={v.label}>
          <ConvergenceBlock c={conv} />
          <ConvergenceAction variant="again" />
        </Section>
      ) : (
      <Section title={v ? v.label : t("verify.title")}>
        {v ? (
          <>
            <div className="tnum grid grid-cols-[auto_auto_1fr] gap-x-3 rounded-[8px] bg-raised px-3 py-2.5">
              {[
                { k: "verify.reference", label: v.reference_label, v: fmt(v.reference, 4) },
                { k: "verify.computed", label: undefined, v: fmt(v.computed, 4) },
              ].map((x) => (
                <div key={x.k} className="min-w-0">
                  <div className="truncate text-micro text-fg-2">{x.label ?? t(x.k)}</div>
                  <div className="mt-0.5 whitespace-nowrap text-kpi font-medium text-fg">
                    {x.v}
                    {v.unit && v.unit !== "-" && <span className="ml-[0.2em] text-[0.8em] font-normal text-fg-3">{unitLabel(v.unit)}</span>}
                  </div>
                </div>
              ))}
              <div className="min-w-0 text-right">
                <div className="text-micro text-fg-2">{t("verify.diff")}</div>
                <div className={cn("mt-0.5 inline-flex items-center gap-1 whitespace-nowrap text-em font-semibold", v.pass ? "text-green" : "text-red")}>
                  {v.pass ? <Check size={14} /> : <X size={14} />}
                  {fmtSignedPct(v.error_pct)}
                </div>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-label">
              <span className="tnum whitespace-nowrap text-fg-2">{t("verify.tolerance", { t: fmt(v.tolerance_pct, 3) })}</span>
              {r.nova_tool && (
                <a
                  href={r.nova_tool}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 whitespace-nowrap font-medium text-accent-text underline-offset-2 hover:underline"
                >
                  {t("verify.open")}
                  <ExternalLink size={12} />
                </a>
              )}
            </div>
          </>
        ) : (
          <>
            <Callout tone="info">
              {/* the backend reason is English-only: show the localized sentence, keep the raw one as a tooltip */}
              <span className="block" title={noRefReason ?? undefined}>
                {noRefReason ? t("conv.noRef") : t("verify.none")}
              </span>
            </Callout>
            <ConvergenceAction variant="primary" />
          </>
        )}
      </Section>
      )}
      {v && v.kind !== "convergence" && (
        // a template with an analytic reference: the mesh study is extra information
        <Section title={t("conv.title")}>
          {conv ? (
            <>
              <ConvergenceBlock c={conv} />
              <ConvergenceAction variant="again" />
            </>
          ) : (
            <>
              <p className="prose-ui text-label text-fg-3">{t("conv.extra")}</p>
              <ConvergenceAction variant="secondary" />
            </>
          )}
        </Section>
      )}
      <ResultsTools />
      <Section>
        <div className="flex flex-col gap-4">
          <Field label={t("results.quantity")}>
            <Select
              value={quantity}
              ariaLabel={t("results.quantity")}
              options={r.quantities.map((q) => ({
                value: q.id,
                label: (
                  <>
                    {q.label}
                    {q.unit && q.unit !== "-" && <span className="ml-1 text-fg-3">[{unitLabel(q.unit)}]</span>}
                  </>
                ),
              }))}
              onChange={(q) => void loadField(q, true)}
            />
            <Button variant="ghost" size="sm" className="mt-1.5 self-start" onClick={() => focusPeak()}>
              <Crosshair size={14} strokeWidth={1.5} />
              {t("results.focusPeak")}
            </Button>
          </Field>
          <Field label={t("results.colormap")}>
            <Tabs
              size="sm"
              value={colormap}
              onChange={(c) => setState({ colormap: c })}
              items={[
                { value: "viridis", label: t("results.viridis") },
                { value: "coolwarm", label: t("results.coolwarm") },
              ]}
            />
          </Field>
          {hasDisp && (
            <Field
              label={t("results.deform")}
              right={
                <span className="flex items-center gap-1">
                  {deform != null && (
                    <Tooltip content={t("results.auto")}>
                      <button
                        type="button"
                        aria-label={t("results.auto")}
                        onClick={() => setState({ deformScale: null })}
                        className="rounded-[4px] p-0.5 text-fg-3 hover:bg-hover hover:text-fg"
                      >
                        <RotateCcw size={12} />
                      </button>
                    </Tooltip>
                  )}
                  <span className="tnum text-body font-medium text-fg">×{fmt(k, 3)}</span>
                </span>
              }
            >
              <Slider
                ariaLabel={t("results.deform")}
                min={0}
                max={autoK * 3}
                step={autoK / 100}
                value={Math.min(k, autoK * 3)}
                onChange={(x) => setState({ deformScale: x })}
                marks={[
                  { value: 0, label: "0" },
                  { value: autoK, label: t("results.auto") },
                  { value: autoK * 3, label: `×${fmt(autoK * 3, 2)}` },
                ]}
              />
              <div className="mt-3 flex gap-2">
                <Button variant="secondary" onClick={() => setState({deformScale:null})}>{t('results.auto')}</Button>
                <Button variant="secondary" onClick={() => setState({deformScale:1})}>×1</Button>
                <NumberInput ariaLabel={t('results.customScale')} value={k} min={0} onCommit={v => setState({deformScale:v})} />
              </div>
            </Field>
          )}
          {range && (
            <Button size="sm" variant="ghost" className="-ml-2.5 self-start" onClick={() => setState({ range: null })}>
              <RotateCcw size={12} />
              {t("colorbar.reset")}
            </Button>
          )}
        </div>
      </Section>
      {caseId && quantity && !offline && (
        <Section className="pb-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void exportImage("wide", false)}
              className="inline-flex h-8 items-center gap-2 rounded-[6px] border border-line-strong px-3 text-body font-medium text-fg hover:bg-hover"
            >
              <ImageDown size={14} />
              {t("results.export")}
            </button>
            {r.wall_s != null && (
              <span className="tnum min-w-0 truncate text-label text-fg-3">
                {r.engine}
                <span className="ml-2">{fmt(r.wall_s, 3)} s</span>
              </span>
            )}
          </div>
        </Section>
      )}
    </>
  );
}

// ------------------------------------------------------------------ panel

const BODIES: Record<StepId, () => ReactNode> = {
  geometry: GeometryStep,
  mesh: MeshStep,
  physics: PhysicsStep,
  boundaries: BoundariesStep,
  run: RunStep,
  results: ResultsStep,
};

export function PropertiesPanel() {
  const t = useT();
  const step = useStore((s) => s.step);
  const saving = useStore((s) => s.saving);
  const external = useStore((s) => s.payload?.ui.physics === "external");
  const meshNeeds = useStore((s) => {
    const st = s.payload?.ui.mesh?.state;
    return !st?.exists || !!st.stale;
  });
  const idx = STEPS.indexOf(step);
  const next = idx < 4 ? STEPS[idx + 1] : null;
  const Body = BODIES[step];
  const Icon = STEP_ICONS[step];
  // one primary per view: the mesh step's own "Generate" wins while it is needed
  const nextPrimary = !(step === "mesh" && meshNeeds);
  return (
    <aside className="flex w-[320px] shrink-0 flex-col border-l border-line bg-bg">
      <header className="border-b border-line px-4 pb-3 pt-3.5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-em font-semibold text-fg">
            <Icon size={16} className="text-fg-2" />
            {t(`step.${step}.title`)}
          </h2>
          <span className="text-micro text-fg-3">{saving ? t("statusbar.saving") : t("props.saved")}</span>
        </div>
        <p className="prose-ui mt-1 text-label text-fg-2">{t(step === "boundaries" && external ? "step.boundaries.hintExternal" : `step.${step}.hint`)}</p>
      </header>
      <div key={step} className="anim-in min-h-0 flex-1 overflow-y-auto pb-6">
        <Body />
      </div>
      {next && (
        <footer className="border-t border-line p-3">
          <Button variant={nextPrimary ? "primary" : "secondary"} className="w-full justify-between" onClick={() => goStep(next)}>
            <span className="truncate">{t("props.next", { step: t(`step.${next}.title`) })}</span>
            <span className="flex items-center gap-1.5 opacity-70">
              <span className="tnum text-micro">{idx + 2}</span>
              <ArrowRight size={14} />
            </span>
          </Button>
        </footer>
      )}
    </aside>
  );
}
