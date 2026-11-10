import { useState } from "react";
import { Download, Sparkles } from "lucide-react";
import { genesisStlUrl } from "../api/client";
import type { GenesisSettings } from "../api/types";
import { isActive, runGenesis, setState, useStore, useT } from "../state/store";
import { Button } from "./ui/Button";
import { Select } from "./ui/Select";
import { Slider } from "./ui/Slider";
import { Field, SectionLabel, Spinner } from "./ui/misc";
import { fmt } from "../lib/units";

type Making = "none" | "print" | "mill";
const AXES = ["x", "y", "z"] as const;
const RESOLUTION: Record<string, number> = { coarse: 40000, normal: 120000, fine: 400000 };

/** Genesis: topology optimisation of the part. The part is the design space, its face conditions the loads and
 * supports; the result is a closed shape (STL) to analyse again. Lives in the run step next to the solver. */
export function GenesisPanel() {
  const t = useT();
  const p = useStore((s) => s.payload);
  const job = useStore((s) => s.job);
  const busy = useStore((s) => s.genesisBusy);
  const g = useStore((s) => s.genesis);
  const view = useStore((s) => s.genesisView);
  const offline = useStore((s) => s.mode === "mock");
  const [volume, setVolume] = useState(30);
  const [res, setRes] = useState("normal");
  const [minMember, setMinMember] = useState("");
  const [making, setMaking] = useState<Making>("none");
  const [build, setBuild] = useState("+z");
  const [extrude, setExtrude] = useState<"x" | "y" | "z">("z");
  const [sym, setSym] = useState<string[]>([]);
  if (!p || offline || !["structural", "thermal"].includes(p.ui.physics ?? "")) return null;
  const mm = Number(minMember);
  const minOk = !minMember.trim() || (Number.isFinite(mm) && mm > 0);
  const settings = (): GenesisSettings => ({
    volume_fraction: volume / 100,
    cells: RESOLUTION[res],
    symmetry: sym as ("x" | "y" | "z")[],
    extrusion: making === "mill" ? extrude : null,
    overhang: making === "print" ? build : null,
    ...(minMember.trim() && minOk ? { min_member: { value: mm, unit: "mm" } } : {}),
  });
  const active = isActive(job);
  const ready = (p.ready ?? !p.checks.some((c) => c.level === "error")) && minOk;
  return (
    <section className="px-4 pt-6">
      <SectionLabel>{t("genesis.title")}</SectionLabel>
      <p className="prose-ui text-label text-fg-2">{t("genesis.lead")}</p>
      <div className="mt-3 flex flex-col gap-4">
        <Field label={t("genesis.volume")} right={<span className="tnum text-label text-fg">{volume}<span className="ml-0.5 text-fg-3">%</span></span>}>
          <Slider ariaLabel={t("genesis.volume")} min={5} max={90} step={1} value={volume} onChange={setVolume} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("genesis.resolution")}>
            <Select ariaLabel={t("genesis.resolution")} value={res} onChange={setRes}
              options={Object.keys(RESOLUTION).map((k) => ({ value: k, label: t(`genesis.res.${k}`) }))} />
          </Field>
          <Field label={t("genesis.minMember")}>
            <div className="flex h-8 items-center rounded-[6px] border border-line-strong bg-field pr-2 focus-within:border-accent">
              <input className="h-full w-full min-w-0 bg-transparent px-2 text-right text-body text-fg tnum outline-none" inputMode="decimal"
                placeholder={t("genesis.auto")} value={minMember} aria-label={t("genesis.minMember")} aria-invalid={!minOk}
                onChange={(e) => setMinMember(e.target.value)} />
              <span className="text-label text-fg-3">mm</span>
            </div>
          </Field>
        </div>
        <Field label={t("genesis.making")}>
          <Select ariaLabel={t("genesis.making")} value={making} onChange={(v) => setMaking(v as Making)}
            options={(["none", "print", "mill"] as Making[]).map((k) => ({ value: k, label: t(`genesis.make.${k}`), hint: t(`genesis.make.${k}.hint`) }))} />
        </Field>
        {making === "print" && (
          <Field label={t("genesis.buildDir")}>
            <Select ariaLabel={t("genesis.buildDir")} value={build} onChange={setBuild}
              options={["+z", "-z", "+y", "-y", "+x", "-x"].map((d) => ({ value: d, label: d.toUpperCase() }))} />
          </Field>
        )}
        {making === "mill" && (
          <Field label={t("genesis.extrusionAxis")}>
            <Select ariaLabel={t("genesis.extrusionAxis")} value={extrude} onChange={(v) => setExtrude(v as "x" | "y" | "z")}
              options={AXES.map((a) => ({ value: a, label: a.toUpperCase() }))} />
          </Field>
        )}
        <Field label={t("genesis.symmetry")}>
          <div className="flex h-8 items-center gap-4">
            {AXES.map((a) => (
              <label key={a} className="flex items-center gap-1.5 text-body text-fg">
                <input type="checkbox" checked={sym.includes(a)}
                  onChange={(e) => setSym(e.target.checked ? [...sym, a] : sym.filter((x) => x !== a))} />
                {a.toUpperCase()}
              </label>
            ))}
          </div>
        </Field>
        {!active && (
          <Button variant="secondary" className="w-full justify-center" disabled={!ready || busy} onClick={() => void runGenesis(settings())}>
            {busy ? <Spinner /> : <Sparkles size={14} strokeWidth={1.5} />}
            {busy ? t("genesis.starting") : t("genesis.run")}
          </Button>
        )}
      </div>
      {g && <GenesisResultView />}
      {g && (
        <label className="mt-3 flex h-8 items-center gap-2 text-body text-fg">
          <input type="checkbox" checked={view} onChange={(e) => setState({ genesisView: e.target.checked })} />
          {t("genesis.show")}
        </label>
      )}
    </section>
  );
}

function GenesisResultView() {
  const t = useT();
  const g = useStore((s) => s.genesis)!;
  const cid = useStore((s) => s.payload?.case.case_id)!;
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between">
        <span className="text-body font-medium text-fg">{t("genesis.result")}</span>
        <span className="tnum text-label text-fg-3">{t("genesis.meta", { n: g.iterations, s: fmt(g.elapsed_s, 3) })}</span>
      </div>
      <dl className="tnum mt-2 grid grid-cols-2 overflow-hidden rounded-[8px] bg-raised">
        {g.cards.map((c, i) => (
          <div key={c.key} className={`min-w-0 px-3 py-2 ${i % 2 ? "border-l border-line" : ""} ${i > 1 ? "border-t border-line" : ""}`}>
            <dt className="truncate text-micro text-fg-2">{c.label}</dt>
            <dd className="mt-0.5 truncate text-em font-medium text-fg">{fmt(c.value, 4)}<span className="ml-1 text-[0.8em] text-fg-3">{c.unit}</span></dd>
          </div>
        ))}
      </dl>
      {g.kept != null && (
        <p className="prose-ui mt-2 text-label text-fg-2">{t(g.physics === "elastic" ? "genesis.kept" : "genesis.keptHeat", { pct: fmt(100 * g.kept, 3), vol: fmt(g.cards.find((c) => c.key === "volume_fraction")?.value ?? 0, 3) })}</p>
      )}
      {g.stale && <p className="prose-ui mt-1 text-label text-orange">{t("genesis.stale")}</p>}
      {g.warnings.map((w) => (
        <p key={w.key} className="prose-ui mt-1 text-label text-orange">{w.message}</p>
      ))}
      <a href={genesisStlUrl(cid, g.run_id)} className="mt-3 flex h-8 items-center justify-center gap-2 rounded-[6px] border border-line-strong px-3 text-body text-fg hover:bg-hover">
        <Download size={14} strokeWidth={1.5} />{t("genesis.download")}
      </a>
      <p className="prose-ui mt-2 text-label text-fg-3">{g.note}</p>
    </div>
  );
}
