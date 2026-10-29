import { FolderOpen, Languages, Moon, Plus, Search, Sparkles, Sun, Undo2, Redo2 } from "lucide-react";
import { Button } from "./ui/Button";
import { Select } from "./ui/Select";
import { Tooltip } from "./ui/Tooltip";
import { Kbd } from "./ui/misc";
import { cn } from "./ui/cn";
import { caseTitle, closeCase, openCase, setLang, toggleTheme, ui, useStore, useT, undoCase, redoCase } from "../state/store";
import { pick } from "../i18n";
import type { Lang, Localized } from "../api/types";

export const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex shrink-0 items-center gap-2 whitespace-nowrap select-none", className)}>
      <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden>
        <path d="M12 1.5 22.5 12 12 22.5 1.5 12Z" fill="var(--accent-fill)" />
        <path d="M12 7.2 16.8 12 12 16.8 7.2 12Z" fill="var(--bg)" />
      </svg>
      <span className="text-body font-semibold text-fg">
        {/* below 960 px the word gives way to the case title next to it */}
        NovaSolver <span className="font-normal text-fg-2 max-[959px]:hidden">Studio</span>
      </span>
    </span>
  );
}

/** Title for a recent-case row (imported cases fall back to their template id). */
export function summaryTitle(lang: Lang, title: unknown, fallback: string): string {
  const s = pick(lang, title as Localized);
  return s && !s.startsWith("template.") ? s : fallback;
}

function CaseSwitcher() {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const payload = useStore((s) => s.payload);
  const recent = useStore((s) => s.recent);
  if (!payload) return null;
  const currentId = payload.case.case_id;
  const options = [
    ...recent.slice(0, 8).map((c) => ({
      value: c.case_id,
      label: summaryTitle(lang, c.title, t("start.importedCase")),
      hint: c.case_id,
      icon: <FolderOpen size={14} className="text-fg-3" />,
    })),
    { value: "__new", label: t("top.case.new"), icon: <Plus size={14} className="text-fg-3" /> },
  ];
  if (!options.some((o) => o.value === currentId))
    options.unshift({
      value: currentId,
      label: caseTitle(payload),
      hint: currentId,
      icon: <FolderOpen size={14} className="text-fg-3" />,
    });
  return (
    <Select
      variant="ghost"
      value={currentId}
      ariaLabel={t("top.case.switch")}
      options={options}
      minMenuWidth={280}
      onChange={(v) => (v === "__new" ? closeCase() : void openCase(v))}
      renderValue={() => <span className="max-w-[240px] truncate font-medium text-fg">{caseTitle(payload)}</span>}
    />
  );
}

export function TopBar() {
  const t = useT();
  const lang = useStore((s) => s.lang);
  const theme = useStore((s) => s.theme);
  const aiOpen = useStore((s) => s.ai);
  const hasCase = useStore((s) => !!s.payload);
  const history = useStore(s => s.payload?.history);
  const busy = useStore(s => s.historyBusy);
  const saving = useStore(s => s.saving);
  return (
    <header className="relative z-20 grid h-12 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-line bg-bg px-3">
      <div className="flex min-w-0 items-center gap-1">
        <Tooltip content={t("top.home")}>
          <button type="button" onClick={() => closeCase()} className="shrink-0 rounded-[6px] px-1.5 py-1 hover:bg-hover">
            <Logo />
          </button>
        </Tooltip>
        {hasCase && (
          <>
            <span className="mx-1 h-4 w-px bg-line-strong" />
            <CaseSwitcher />
            <Tooltip content={history?.undo[0] ? t('undo.tooltip', { summary: history.undo[0].summary }) : t('undo.label')}>
              <Button variant="ghost" size="icon" disabled={busy || (!saving && !history?.undo.length)} aria-label={t('undo.label')} onClick={() => void undoCase()}><Undo2 size={16} strokeWidth={1.5} /></Button>
            </Tooltip>
            <Tooltip content={t('redo.label')}>
              <Button variant="ghost" size="icon" disabled={busy || !history?.redo_count} aria-label={t('redo.label')} onClick={() => void redoCase()}><Redo2 size={16} strokeWidth={1.5} /></Button>
            </Tooltip>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => ui.palette(true)}
        className="flex h-8 w-[min(480px,34vw)] max-[959px]:w-[200px] items-center gap-2 rounded-[6px] border border-line bg-raised px-2.5 text-body text-fg-3 transition-colors duration-[var(--dur-2)] hover:border-line-strong"
      >
        <Search size={14} />
        <span className="flex-1 truncate text-left">{t("top.search")}</span>
        <span className="flex gap-0.5">
          <Kbd>{MOD}</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <div className="flex items-center justify-end gap-1">
        <Tooltip content={t("top.language")}>
          <Select<Lang>
            variant="ghost"
            value={lang}
            align="end"
            ariaLabel={t("top.language")}
            onChange={(l) => void setLang(l)}
            minMenuWidth={140}
            options={(["ja", "en", "zh"] as Lang[]).map((l) => ({ value: l, label: t(`lang.${l}`) }))}
            renderValue={() => (
              <span className="flex items-center gap-1.5">
                <Languages size={16} />
                <span className="text-label font-medium uppercase">{lang}</span>
              </span>
            )}
          />
        </Tooltip>
        <Tooltip content={t(theme === "dark" ? "top.theme.toLight" : "top.theme.toDark")}>
          <Button variant="ghost" size="icon" aria-label={t(theme === "dark" ? "top.theme.toLight" : "top.theme.toDark")} onClick={toggleTheme}>
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </Button>
        </Tooltip>
        <Tooltip content={t("top.ai.tooltip")}>
          <Button variant="secondary" onClick={() => ui.ai()} aria-pressed={aiOpen} className={cn("ml-1", aiOpen && "bg-active")}>
            <Sparkles size={14} className="text-accent-text" />
            {t("top.ai")}
          </Button>
        </Tooltip>
      </div>
    </header>
  );
}
