import { FileUp, FolderOpen, MessagesSquare, ShieldCheck, TriangleAlert } from "lucide-react";
import { createCase, createSample, openCase, useStore, useT } from "../state/store";
import { pick } from "../i18n";
import type { Lang, Sample, Template } from "../api/types";
import { Spinner, Kbd, Chip } from "./ui/misc";
import { Button } from "./ui/Button";
import { Tooltip } from "./ui/Tooltip";
import { cn } from "./ui/cn";
import { MOD, summaryTitle } from "./TopBar";
import { CAD_PHYSICS, PHYSICS_ICON, pickCadFile } from "./ImportCad";

// Line art: accent strokes + text-3 context lines, on the sunken well.
const S = "var(--accent-fill)";
const D = "var(--text-3)";

function Illustration({ id, physics }: { id: string; physics: string }) {
  const common = { viewBox: "0 0 240 110", className: "h-full w-full", "aria-hidden": true } as const;
  if (id === "sphere-drag" || physics === "external") {
    // body in a free stream: streamlines part around it, a dashed wake behind
    const lines = [
      { y: 19, o: -4 },
      { y: 34, o: -9 },
      { y: 76, o: 9 },
      { y: 91, o: 4 },
    ];
    return (
      <svg {...common}>
        {lines.map(({ y, o }) => (
          <g key={y}>
            <path d={`M22 ${y} C 88 ${y} 102 ${y + o} 128 ${y + o} C 154 ${y + o} 168 ${y} 226 ${y}`} fill="none" stroke={D} strokeWidth="1" />
            <path d={`M38 ${y - 3} 43 ${y} 38 ${y + 3}`} fill="none" stroke={D} strokeWidth="1" />
          </g>
        ))}
        <line x1="22" y1="55" x2="104" y2="55" stroke={D} strokeWidth="1" />
        <path d="M38 52 43 55 38 58" fill="none" stroke={D} strokeWidth="1" />
        <path d="M143 46 C 160 49 178 52 204 53 M143 64 C 160 61 178 58 204 57" fill="none" stroke={S} strokeWidth="1" strokeDasharray="3 3" opacity="0.6" />
        <circle cx="128" cy="55" r="16" fill="none" stroke={S} strokeWidth="1.4" />
      </svg>
    );
  }
  if (id === "plate-hole") {
    // plate in tension with a central hole (stress concentration)
    return (
      <svg {...common}>
        <rect x="58" y="32" width="124" height="46" rx="1" fill="none" stroke={S} strokeWidth="1.4" />
        <circle cx="120" cy="55" r="9" fill="none" stroke={S} strokeWidth="1.3" />
        <path d="M120 41 V37 M120 69 V73" stroke={S} strokeWidth="1" opacity="0.6" />
        {[40, 55, 70].map((y) => (
          <g key={y}>
            <line x1="54" y1={y} x2="32" y2={y} stroke={D} strokeWidth="1.2" />
            <path d={`M36 ${y - 3.5} 30 ${y} 36 ${y + 3.5}Z`} fill={D} />
            <line x1="186" y1={y} x2="208" y2={y} stroke={D} strokeWidth="1.2" />
            <path d={`M204 ${y - 3.5} 210 ${y} 204 ${y + 3.5}Z`} fill={D} />
          </g>
        ))}
      </svg>
    );
  }
  if (id === "fin") {
    // straight fin on a hot wall: conduction along the fin, convection off its surface
    return (
      <svg {...common}>
        <defs>
          <pattern id="hatch-fin" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke={D} strokeWidth="1.1" />
          </pattern>
        </defs>
        <rect x="34" y="22" width="12" height="66" fill="url(#hatch-fin)" />
        <line x1="46" y1="22" x2="46" y2="88" stroke={D} strokeWidth="1.2" />
        <rect x="46" y="48" width="144" height="14" rx="1" fill="none" stroke={S} strokeWidth="1.4" />
        <line x1="58" y1="55" x2="126" y2="55" stroke={S} strokeWidth="1" strokeDasharray="3 3" opacity="0.7" />
        <path d="M122 52 127 55 122 58" fill="none" stroke={S} strokeWidth="1" opacity="0.7" />
        {[84, 124, 164].map((x) => (
          <path key={x} d={`M${x} 43 q 4 -6 0 -12 q -4 -6 0 -12`} fill="none" stroke={D} strokeWidth="1.1" />
        ))}
        {[104, 144].map((x) => (
          <path key={x} d={`M${x} 67 q 4 6 0 12 q -4 6 0 12`} fill="none" stroke={D} strokeWidth="1.1" opacity="0.7" />
        ))}
        <text x="54" y="40" fill={D} fontSize="10" fontFamily="Inter">T₀</text>
      </svg>
    );
  }
  if (id === "cavity") {
    return (
      <svg {...common}>
        <rect x="80" y="18" width="80" height="80" fill="none" stroke={D} strokeWidth="1.2" />
        <line x1="80" y1="18" x2="160" y2="18" stroke={S} strokeWidth="2.2" />
        <line x1="96" y1="9" x2="140" y2="9" stroke={D} strokeWidth="1.2" />
        <path d="M136 5.5 143 9 136 12.5Z" fill={D} />
        <ellipse cx="124" cy="52" rx="24" ry="22" fill="none" stroke={S} strokeWidth="1.3" opacity="0.85" />
        <ellipse cx="124" cy="52" rx="13" ry="12" fill="none" stroke={S} strokeWidth="1.1" opacity="0.6" />
        <ellipse cx="94" cy="86" rx="7" ry="6" fill="none" stroke={S} strokeWidth="0.9" opacity="0.4" />
        <ellipse cx="150" cy="88" rx="5" ry="4.5" fill="none" stroke={S} strokeWidth="0.9" opacity="0.4" />
      </svg>
    );
  }
  if (id === "pipe_elbow") {
    return (
      <svg {...common}>
        <path d="M40 40 H120 A34 34 0 0 1 154 74 V100" fill="none" stroke={S} strokeWidth="1.4" />
        <path d="M40 64 H118 A12 12 0 0 1 130 76 V100" fill="none" stroke={S} strokeWidth="1.4" />
        <path d="M44 52 H112 A22 22 0 0 1 142 74 V96" fill="none" stroke={D} strokeWidth="1" strokeDasharray="3 3" />
        <path d="M24 46 34 52 24 58" fill="none" stroke={D} strokeWidth="1.2" />
        <line x1="14" y1="52" x2="33" y2="52" stroke={D} strokeWidth="1.2" />
      </svg>
    );
  }
  if (id === "channel" || physics === "cfd" || physics === "flow") {
    return (
      <svg {...common}>
        <line x1="30" y1="24" x2="210" y2="24" stroke={D} strokeWidth="1.6" />
        <line x1="30" y1="86" x2="210" y2="86" stroke={D} strokeWidth="1.6" />
        <path d="M120 24 Q 176 55 120 86" fill="none" stroke={S} strokeWidth="1.4" />
        {[33, 44, 55, 66, 77].map((y) => {
          const s = 1 - Math.pow((y - 55) / 31, 2);
          const x2 = 120 + 52 * s;
          return (
            <g key={y} opacity="0.8">
              <line x1="120" y1={y} x2={x2} y2={y} stroke={S} strokeWidth="1" />
              <path d={`M${x2 - 4} ${y - 2.5} ${x2} ${y} ${x2 - 4} ${y + 2.5}`} fill="none" stroke={S} strokeWidth="1" />
            </g>
          );
        })}
        <line x1="120" y1="24" x2="120" y2="86" stroke={D} strokeWidth="1" strokeDasharray="2 3" />
      </svg>
    );
  }
  if (id === "heatsink") {
    return (
      <svg {...common}>
        <rect x="64" y="74" width="112" height="12" fill="none" stroke={S} strokeWidth="1.3" />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect key={i} x={70 + i * 18} y="30" width="8" height="44" fill="none" stroke={S} strokeWidth="1.2" opacity="0.85" />
        ))}
        {[0, 1, 2].map((i) => (
          <path key={i} d={`M${96 + i * 24} 24 q 4 -6 0 -12 q -4 -6 0 -12`} fill="none" stroke={D} strokeWidth="1.1" />
        ))}
        <line x1="84" y1="98" x2="156" y2="98" stroke={D} strokeWidth="1.1" />
        {[96, 120, 144].map((x) => (
          <path key={x} d={`M${x} 104 ${x} 92 M${x - 3} 95 ${x} 91 ${x + 3} 95`} fill="none" stroke={D} strokeWidth="1.1" />
        ))}
      </svg>
    );
  }
  if (id === "l_bracket") {
    return (
      <svg {...common}>
        <path d="M70 88 H170 V76 H86 V22 H70 Z" fill="none" stroke={S} strokeWidth="1.4" />
        <circle cx="128" cy="82" r="3" fill="none" stroke={S} strokeWidth="1.1" />
        <pattern id="hatch-lb" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke={D} strokeWidth="1.1" />
        </pattern>
        <rect x="64" y="90" width="112" height="7" fill="url(#hatch-lb)" />
        <line x1="104" y1="34" x2="90" y2="34" stroke={D} strokeWidth="1.4" />
        <path d="M94 30.5 88 34 94 37.5Z" fill={D} />
        <text x="108" y="37" fill={D} fontSize="10" fontFamily="Inter">F</text>
      </svg>
    );
  }
  if (id === "thermal-block" || physics === "thermal") {
    return (
      <svg {...common}>
        <rect x="72" y="36" width="96" height="38" fill="none" stroke={S} strokeWidth="1.4" />
        <line x1="72" y1="30" x2="72" y2="80" stroke={D} strokeWidth="2.2" />
        <line x1="168" y1="30" x2="168" y2="80" stroke={D} strokeWidth="2.2" />
        {[46, 55, 64].map((y) => (
          <g key={y} opacity="0.8">
            <line x1="84" y1={y} x2="152" y2={y} stroke={S} strokeWidth="1" strokeDasharray="3 3" />
            <path d={`M148 ${y - 3} 153 ${y} 148 ${y + 3}`} fill="none" stroke={S} strokeWidth="1" />
          </g>
        ))}
        <text x="56" y="58" fill={D} fontSize="10" fontFamily="Inter" textAnchor="middle">T₁</text>
        <text x="184" y="58" fill={D} fontSize="10" fontFamily="Inter" textAnchor="middle">T₂</text>
      </svg>
    );
  }
  // cantilever / generic structural
  return (
    <svg {...common}>
      <defs>
        <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke={D} strokeWidth="1.1" />
        </pattern>
      </defs>
      <rect x="34" y="22" width="12" height="66" fill="url(#hatch)" />
      <line x1="46" y1="22" x2="46" y2="88" stroke={D} strokeWidth="1.2" />
      <rect x="46" y="44" width="148" height="16" rx="1" fill="none" stroke={S} strokeWidth="1.4" />
      <path d="M46 52 Q 130 56 194 72" fill="none" stroke={S} strokeWidth="1.1" strokeDasharray="3 3" opacity="0.7" />
      <line x1="194" y1="14" x2="194" y2="38" stroke={D} strokeWidth="1.4" />
      <path d="M190 33 194 40 198 33Z" fill={D} />
      <text x="202" y="26" fill={D} fontSize="10" fontFamily="Inter">F</text>
    </svg>
  );
}

function PhysicsChip({ physics }: { physics: string }) {
  const t = useT();
  const Icon = PHYSICS_ICON[physics as keyof typeof PHYSICS_ICON] ?? PHYSICS_ICON.structural;
  return (
    <Chip>
      <Icon size={12} className="text-fg-3" />
      {t(physics === "external" ? "physics.short.external" : `physics.${physics}`)}
    </Chip>
  );
}

/** "c_20261025_001824_7e91" -> Date (falls back to null). */
function caseDate(id: string): Date | null {
  const m = id.match(/^c_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})?/);
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0)) : null;
}

function relTime(d: Date, lang: Lang): string {
  const s = (d.getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(lang === "zh" ? "zh-Hans" : lang, { numeric: "auto" });
  const a = Math.abs(s);
  if (a < 60) return rtf.format(Math.round(s), "second");
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}

function TemplateCard({ tpl }: { tpl: Template }) {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const creating = useStore((s) => s.creating);
  const busy = creating === tpl.id;
  const engines = tpl.engines.map((e) => (typeof e === "string" ? { id: e, available: true } : e));
  const needsEngine = tpl.runnable_now === false;
  const missing = engines.filter((e) => !e.available).map((e) => e.id);
  return (
    <button
      type="button"
      onClick={() => void createCase(tpl.id)}
      disabled={!!creating}
      className={cn(
        "group flex flex-col overflow-hidden rounded-[10px] border border-line bg-surface text-left",
        "transition-[border-color] duration-[var(--dur-2)] hover:border-line-strong disabled:cursor-progress",
      )}
    >
      <div className="relative h-[100px] w-full overflow-hidden bg-sunken px-4">
        <div className="h-full transition-transform duration-[var(--dur-2)] ease-[var(--ease-out)] group-hover:-translate-y-[2px]">
          <Illustration id={tpl.id} physics={tpl.physics} />
        </div>
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-sunken/80 text-body text-fg">
            <Spinner /> {t("start.creating")}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h3 className="text-em font-semibold text-fg">{pick(lang, tpl.title)}</h3>
        <p className="prose-ui mt-1.5 line-clamp-3 text-body text-fg-2">{pick(lang, tpl.description)}</p>
        <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
          <PhysicsChip physics={tpl.physics} />
          {tpl.has_reference && (
            <Chip>
              <ShieldCheck size={12} className="text-green" />
              {t("start.reference")}
            </Chip>
          )}
          {needsEngine && (
            <Chip className="text-orange">
              <TriangleAlert size={12} />
              {t("start.requires", { engine: missing.map((m) => t(`engine.${m}`)).join(" / ") || "OpenFOAM" })}
            </Chip>
          )}
        </div>
      </div>
    </button>
  );
}

function SampleButton({ s }: { s: Sample }) {
  const t = useT();
  const lang = useStore((st) => st.lang);
  const creating = useStore((st) => st.creating);
  const busy = creating === `sample:${s.id}`;
  return (
    <button
      type="button"
      disabled={!!creating}
      onClick={() => void createSample(s.id, s.physics)}
      className="group flex min-w-0 items-center gap-3 rounded-[8px] p-1.5 pr-3 text-left transition-colors duration-[var(--dur-1)] hover:bg-hover disabled:cursor-progress"
    >
      <span className="relative h-12 w-[72px] shrink-0 overflow-hidden rounded-[6px] bg-sunken">
        <Illustration id={s.id} physics={s.physics} />
        {busy && (
          <span className="absolute inset-0 flex items-center justify-center bg-sunken/80">
            <Spinner />
          </span>
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body font-medium text-fg">{pick(lang, s.title)}</span>
        <span className="block truncate text-label text-fg-3">
          {t(`physics.${s.physics}`)}
          <span className="ml-2">{s.file}</span>
        </span>
      </span>
    </button>
  );
}

function ImportPanel() {
  const t = useT();
  const importing = useStore((s) => s.importing);
  const mock = useStore((s) => s.mode === "mock");
  const samples = useStore((s) => s.samples);
  return (
    <section className="mt-8 rounded-[10px] border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4 p-5">
        <div className="flex min-w-[280px] flex-1 items-start gap-3.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] bg-sunken text-fg-2">
            <FileUp size={18} />
          </span>
          <div className="min-w-0">
            <h2 className="text-em font-semibold text-fg">{t("import.title")}</h2>
            <p className="prose-ui mt-0.5 text-body text-fg-2">{t("import.subtitle")}</p>
          </div>
        </div>
        {importing ? (
          <div className="flex h-9 items-center gap-2 text-body text-fg-2">
            <Spinner /> {t("import.busy", { name: importing })}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="mr-1 text-label text-fg-3">{t("import.analyseAs")}</span>
            {CAD_PHYSICS.map((ph) => {
              const Icon = PHYSICS_ICON[ph];
              return (
                <Tooltip key={ph} content={mock ? t("import.needsBackend") : t(`import.as.${ph}`)} side="top">
                  <Button variant="secondary" size="lg" disabled={mock} onClick={() => pickCadFile(ph)}>
                    <Icon size={14} />
                    {t(`physics.${ph}`)}
                  </Button>
                </Tooltip>
              );
            })}

          </div>
        )}
      </div>
      {samples.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3.5 py-2.5">
          <span className="pl-1.5 text-label text-fg-3">{t("import.samples")}</span>
          {samples.map((s) => (
            <SampleButton key={s.id} s={s} />
          ))}
        </div>
      )}
    </section>
  );
}

export function StartScreen() {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const templates = useStore((s) => s.templates);
  const recent = useStore((s) => s.recent);
  const bootState = useStore((s) => s.boot);
  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1040px] px-8 pb-12 pt-[min(8vh,64px)]">
        <h1 className="text-page font-semibold text-fg">{t("start.title")}</h1>
        <p className="prose-ui mt-1 text-em text-fg-2">{t("start.subtitle")}</p>

        {bootState === "loading" ? (
          <div className="mt-10 flex items-center gap-2 text-fg-3">
            <Spinner /> {t("common.loading")}
          </div>
        ) : (
          <>
            <ImportPanel />
            <h2 className="mb-3 mt-10 text-label font-medium text-fg-2">{t("start.templates")}</h2>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
              {templates.map((tpl) => (
                <TemplateCard key={tpl.id} tpl={tpl} />
              ))}
            </div>
          </>
        )}

        {recent.length > 0 && (
          <section className="mt-10">
            <h2 className="mb-3 text-label font-medium text-fg-2">{t("start.recent")}</h2>
            <ul className="overflow-hidden rounded-[10px] border border-line bg-surface">
              {recent.slice(0, 6).map((c) => {
                const d = caseDate(c.case_id);
                const tpl = templates.find((x) => x.id === c.template);
                const title = summaryTitle(lang, c.title, c.source_file ?? t("start.importedCase"));
                const tid = c.template ?? "";
                const physics =
                  c.physics ??
                  tpl?.physics ??
                  (tid.includes("thermal") ? "thermal" : tid.includes("external") ? "external" : tid.includes("flow") || tid.includes("cfd") ? "cfd" : tid.startsWith("import") ? "structural" : null);
                return (
                  <li key={c.case_id} className="border-b border-line last:border-b-0">
                    <button
                      type="button"
                      onClick={() => void openCase(c.case_id)}
                      className="flex h-11 w-full items-center gap-3 px-4 text-left transition-colors duration-[var(--dur-1)] hover:bg-hover"
                    >
                      <FolderOpen size={16} className="shrink-0 text-fg-3" />
                      <span className="min-w-0 flex-1 truncate text-body font-medium text-fg">{title}</span>
                      {physics && <span className="hidden text-label text-fg-3 sm:block">{t(`physics.${physics}`)}</span>}
                      {c.gates && (
                        <Chip className={c.gates.verified ? "text-green" : undefined}>
                          {c.gates.verified ? <ShieldCheck size={12} /> : null}
                          {t(c.gates.verified ? "gate.verified" : c.gates.converged ? "gate.converged" : c.gates.ran ? "gate.ran" : "status.todo")}
                        </Chip>
                      )}
                      {d && (
                        <span className="tnum w-24 shrink-0 text-right text-label text-fg-3" title={d.toLocaleString(lang)}>
                          {relTime(d, lang)}
                        </span>
                      )}
                      {c.revision != null && <span className="tnum w-10 shrink-0 text-right text-label text-fg-3">rev {c.revision}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <p className="mt-8 flex items-center gap-1.5 text-label text-fg-3">
          {t("start.tip", { key: "§" })
            .split("§")
            .flatMap((part, i) =>
              i === 0
                ? [part]
                : [
                    <span key={i} className="inline-flex gap-0.5">
                      <Kbd>{MOD}</Kbd>
                      <Kbd>K</Kbd>
                    </span>,
                    part,
                  ],
            )}
        </p>
        <p className="prose-ui mt-2 flex flex-wrap items-center gap-x-1.5 text-label text-fg-3">
          <MessagesSquare size={14} className="shrink-0" />
          {t("start.community")}
          <a href={communityUrl(lang, "start")} target="_blank" rel="noreferrer" className="text-accent-text hover:underline">
            {t("start.communityLink")}
          </a>
        </p>
      </div>
    </main>
  );
}

/** The NovaSolver community page (Discord invite lives there, so an expired invite is fixed in one place). */
export function communityUrl(lang: string, from: string) {
  const prefix = lang === "en" ? "/en" : lang === "zh" ? "/zh" : "";
  return `https://novasolver.jp${prefix}/community/?utm_source=studio_app&utm_medium=${from}&utm_campaign=community`;
}
