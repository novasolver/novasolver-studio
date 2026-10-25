import { useMemo, useState, type ReactNode } from "react";
import {
  Bot,
  Box,
  ChartSpline,
  CornerDownLeft,
  FileUp,
  Frame,
  Languages,
  Maximize,
  MoonStar,
  Play,
  Plus,
  Rocket,
  Search,
  ScrollText,
} from "lucide-react";
import { Dialog } from "./ui/Dialog";
import { Kbd } from "./ui/misc";
import { cn } from "./ui/cn";
import { STEP_ICONS } from "./stepIcons";
import {
  checkConvergence,
  closeCase,
  generateMesh,
  goStep,
  runCase,
  setLang,
  STEPS,
  toggleTheme,
  ui,
  useStore,
  useT,
  viewCmd,
} from "../state/store";
import type { Lang } from "../api/types";
import { pickCadFile } from "./ImportCad";

interface Cmd {
  id: string;
  group: string;
  label: string;
  icon: ReactNode;
  hint?: string;
  run: () => void;
  disabled?: boolean;
}

export function CommandPalette() {
  const open = useStore((s) => s.palette);
  const hasCase = useStore((s) => !!s.payload);
  const lang = useStore((s) => s.lang);
  const t = useT();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);

  const cmds = useMemo<Cmd[]>(() => {
    const list: Cmd[] = [];
    if (hasCase) {
      STEPS.forEach((s, i) => {
        const Icon = STEP_ICONS[s];
        list.push({
          id: `step-${s}`,
          group: t("palette.group.steps"),
          label: t("cmd.goto", { step: t(`step.${s}.title`) }),
          icon: <Icon size={15} />,
          hint: String(i + 1),
          run: () => goStep(s),
        });
      });
      list.push(
        { id: "mesh", group: t("palette.group.run"), label: t("cmd.mesh"), icon: <Box size={15} />, run: () => void generateMesh() },
        { id: "run-preview", group: t("palette.group.run"), label: t("cmd.runPreview"), icon: <Play size={15} />, run: () => void runCase("preview") },
        { id: "run-final", group: t("palette.group.run"), label: t("cmd.runFinal"), icon: <Rocket size={15} />, run: () => void runCase("final") },
        {
          id: "convergence",
          group: t("palette.group.run"),
          label: t("cmd.convergence"),
          icon: <ChartSpline size={15} />,
          run: () => {
            goStep("results");
            void checkConvergence();
          },
        },
        { id: "view-iso", group: t("palette.group.view"), label: t("view.iso"), icon: <Box size={15} />, run: () => viewCmd("iso") },
        { id: "view-front", group: t("palette.group.view"), label: t("view.front"), icon: <Frame size={15} />, run: () => viewCmd("front") },
        { id: "view-top", group: t("palette.group.view"), label: t("view.top"), icon: <Frame size={15} />, run: () => viewCmd("top") },
        { id: "view-fit", group: t("palette.group.view"), label: t("view.fit"), icon: <Maximize size={15} />, hint: "F", run: () => viewCmd("fit") },
      );
    }
    list.push(
      { id: "import-structural", group: t("palette.group.app"), label: t("cmd.import", { physics: t("physics.structural") }), icon: <FileUp size={15} />, run: () => pickCadFile("structural") },
      { id: "import-thermal", group: t("palette.group.app"), label: t("cmd.import", { physics: t("physics.thermal") }), icon: <FileUp size={15} />, run: () => pickCadFile("thermal") },
      { id: "import-flow", group: t("palette.group.app"), label: t("cmd.import", { physics: t("physics.flow") }), icon: <FileUp size={15} />, run: () => pickCadFile("flow") },
      { id: "import-external", group: t("palette.group.app"), label: t("cmd.import", { physics: t("physics.external") }), icon: <FileUp size={15} />, run: () => pickCadFile("external") },
      { id: "new", group: t("palette.group.app"), label: t("cmd.newCase"), icon: <Plus size={15} />, run: () => closeCase() },
      { id: "theme", group: t("palette.group.app"), label: t("cmd.theme"), icon: <MoonStar size={15} />, run: () => toggleTheme() },
      ...(["ja", "en", "zh"] as Lang[])
        .filter((l) => l !== lang)
        .map((l) => ({
          id: `lang-${l}`,
          group: t("palette.group.app"),
          label: t("cmd.lang", { lang: t(`lang.${l}`) }),
          icon: <Languages size={15} />,
          run: () => void setLang(l),
        })),
      { id: "ai", group: t("palette.group.app"), label: t("cmd.ai"), icon: <Bot size={15} />, run: () => ui.ai(true) },
      { id: "log", group: t("palette.group.app"), label: t("cmd.log"), icon: <ScrollText size={15} />, run: () => ui.log() },
    );
    return list;
  }, [hasCase, lang, t]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return cmds;
    return cmds.filter((c) => (c.label + " " + c.group + " " + c.id).toLowerCase().includes(s));
  }, [cmds, q]);

  const close = () => {
    ui.palette(false);
    setQ("");
    setActive(0);
  };
  const exec = (c: Cmd | undefined) => {
    if (!c || c.disabled) return;
    close();
    c.run();
  };

  let lastGroup = "";
  return (
    <Dialog open={open} onClose={close} placement="top" ariaLabel={t("top.search")} className="w-[min(600px,calc(100vw-32px))]">
      <div className="flex h-12 items-center gap-2.5 border-b border-line px-4">
        <Search size={16} className="text-fg-3" />
        <input
          data-autofocus
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(filtered.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              exec(filtered[active]);
            }
          }}
          placeholder={t("palette.placeholder")}
          className="h-full flex-1 bg-transparent text-em text-fg outline-none placeholder:text-fg-3 focus-visible:outline-none"
        />
        <Kbd>Esc</Kbd>
      </div>
      <div className="max-h-[min(420px,60vh)] overflow-auto p-1.5">
        {filtered.length === 0 && <div className="px-3 py-8 text-center text-body text-fg-3">{t("palette.empty")}</div>}
        {filtered.map((c, i) => {
          const header = c.group !== lastGroup ? c.group : null;
          lastGroup = c.group;
          return (
            <div key={c.id}>
              {header && <div className="px-2.5 pb-1 pt-2.5 text-label font-medium text-fg-3">{header}</div>}
              <div
                role="option"
                aria-selected={i === active}
                onPointerMove={() => setActive(i)}
                onClick={() => exec(c)}
                className={cn(
                  "flex h-8 cursor-default items-center gap-3 rounded-[4px] px-2.5 text-body text-fg-2",
                  i === active && "bg-hover text-fg",
                )}
              >
                <span className={cn("text-fg-3", i === active && "text-fg")}>{c.icon}</span>
                <span className="flex-1 truncate">{c.label}</span>
                {c.hint && <Kbd>{c.hint}</Kbd>}
                {i === active && <CornerDownLeft size={13} className="text-fg-3" />}
              </div>
            </div>
          );
        })}
      </div>
    </Dialog>
  );
}
