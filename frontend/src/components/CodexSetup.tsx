import { useEffect, useState } from "react";
import { api, type CodexSetup as Preview } from "../api/client";
import { useT } from "../state/store";
import { Button } from "./ui/Button";

export function CodexSetup() {
  const t = useT();
  const [path, setPath] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(true);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    api.codexPreview().then(p => { if (active) { setPath(p.path); setPreview(p); } })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  const run = async (apply: boolean) => {
    setBusy(true); setFailed(false);
    try {
      const p = apply && preview?.revision
        ? await api.codexSetup(preview.path, preview.revision)
        : await api.codexPreview(path);
      setPreview(p);
    } catch { setPreview(null); setFailed(true); }
    finally { setBusy(false); }
  };
  return <section className="mt-4 rounded border border-line p-3">
    <h3>{t("codex.title")}</h3>
    <p>{t("codex.note")}</p>
    <label className="block mt-3">{t("codex.path")}
      <input className="w-full bg-raised p-2" value={path} disabled={busy}
        onChange={e => { setPath(e.target.value); setPreview(null); setFailed(false); }} />
    </label>
    <p role="status" aria-live="polite">{busy ? t("codex.busy") : failed ? t("codex.blocked") : preview ? t(`codex.${preview.status}`) : t("codex.previewRequired")}</p>
    {preview && <pre className="whitespace-pre-wrap break-all text-micro">{preview.table}</pre>}
    <div className="mt-3 flex gap-2">
      <Button disabled={busy || !path.trim()} onClick={() => void run(false)}>{t("codex.preview")}</Button>
      <Button disabled={busy || preview?.status !== "ready" || !preview.revision} onClick={() => void run(true)}>{t("codex.apply")}</Button>
    </div>
  </section>;
}
