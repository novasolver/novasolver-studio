import { useEffect, useState } from "react";
import { Check, Copy, Sparkles, X } from "lucide-react";
import { ui, useStore, useT } from "../state/store";
import { api } from "../api/client";
import { Button } from "./ui/Button";

/** AI assistant panel (placeholder): explains how to connect an MCP client. */
export function AiPanel() {
  const t = useT();
  const open = useStore((s) => s.ai);
  const [root, setRoot] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open || root) return;
    api
      .env()
      .then((env) => {
        const ws = typeof env.workspace === "string" ? env.workspace : null;
        if (ws) setRoot(ws.replace(/[\\/]workspace[\\/]?$/, ""));
      })
      .catch(() => {});
  }, [open, root]);

  if (!open) return null;
  const path = root ?? "<path>";
  const py = `${path}\\.venv\\Scripts\\python.exe`;
  const snippet = JSON.stringify(
    { mcpServers: { "novasolver-studio": { command: py, args: ["-m", "novastudio.mcp_server"] } } },
    null,
    2,
  );
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = snippet;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <aside className="anim-slide absolute bottom-0 right-0 top-0 z-30 flex w-[380px] flex-col bg-overlay shadow-overlay">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
        <h2 className="flex items-center gap-2 text-em font-semibold text-fg">
          <Sparkles size={16} className="text-accent-text" />
          {t("ai.title")}
        </h2>
        <Button variant="ghost" size="icon-sm" aria-label={t("common.close")} onClick={() => ui.ai(false)}>
          <X size={15} />
        </Button>
      </header>
      <div className="prose-ui min-h-0 flex-1 overflow-y-auto p-4 text-body text-fg-2">
        <p className="text-fg">{t("ai.lead")}</p>
        <ol className="mt-4 flex flex-col gap-3">
          {["ai.step1", "ai.step2", "ai.step3"].map((k, i) => (
            <li key={k} className="flex gap-2.5">
              <span className="tnum flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-raised text-micro font-medium text-fg-2">
                {i + 1}
              </span>
              <span>{root && k === "ai.step2" ? t("ai.step2filled") : t(k)}</span>
            </li>
          ))}
        </ol>
        <div className="mt-4 overflow-hidden rounded-[8px] border border-line bg-raised">
          <div className="flex h-8 items-center justify-between border-b border-line pl-3 pr-1">
            <span className="font-mono text-micro text-fg-3">mcp.json</span>
            <Button variant="ghost" size="sm" onClick={() => void copy()}>
              {copied ? <Check size={13} className="text-green" /> : <Copy size={13} />}
              {copied ? t("ai.copied") : t("ai.copy")}
            </Button>
          </div>
          <pre className="whitespace-pre-wrap break-all p-3 font-mono text-micro text-fg">{snippet}</pre>
        </div>
        <p className="mt-4 flex gap-2 text-label text-fg-2">{t("ai.note")}</p>
      </div>
    </aside>
  );
}
