import { useEffect, useRef, useState } from "react";
import { Box, FileUp, Thermometer, Waves, Wind } from "lucide-react";
import { CAD_EXTENSIONS, importFile, useStore, useT } from "../state/store";
import { cn } from "./ui/cn";

export type CadPhysics = "structural" | "thermal" | "flow" | "external";

/** The four import choices, in the order they are offered. */
export const CAD_PHYSICS: CadPhysics[] = ["structural", "thermal", "flow", "external"];

/** Internal flow (pipes, channels) = waves; flow around a body = wind. */
export const PHYSICS_ICON = { structural: Box, thermal: Thermometer, cfd: Waves, flow: Waves, external: Wind } as const;

/** Backend physics name -> the import choice that re-imports a file for the same analysis. */
export function cadPhysicsOf(physics: string): CadPhysics {
  return physics === "cfd" ? "flow" : (CAD_PHYSICS as string[]).includes(physics) ? (physics as CadPhysics) : "structural";
}

/** Open the OS file picker for a CAD file and import it for the given analysis. */
export function pickCadFile(physics: CadPhysics) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = CAD_EXTENSIONS.join(",");
  input.style.display = "none";
  input.addEventListener("change", () => {
    const f = input.files?.[0];
    if (f) void importFile(f, physics);
    input.remove();
  });
  document.body.appendChild(input);
  input.click();
}

function hasFiles(e: DragEvent) {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
}

/**
 * Drag a CAD file anywhere onto the window: two drop targets appear (Structural / Thermal).
 * Dropping onto one is the single decision; dropping elsewhere cancels.
 */
export function DropOverlay() {
  const t = useT();
  const [show, setShow] = useState(false);
  const [over, setOver] = useState<CadPhysics | null>(null);
  const timer = useRef(0);

  useEffect(() => {
    const onOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setShow(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        setShow(false);
        setOver(null);
      }, 220);
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); // never let the browser navigate to the file
      setShow(false);
      setOver(null);
    };
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  if (!show) return null;
  const target = (physics: CadPhysics) => {
    const Icon = PHYSICS_ICON[physics];
    return (
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(physics);
        }}
        onDragLeave={() => setOver(null)}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          const f = e.dataTransfer.files?.[0];
          setShow(false);
          setOver(null);
          if (f) void importFile(f, physics);
        }}
        className={cn(
          "flex h-40 min-w-0 flex-1 flex-col items-center justify-center gap-2 rounded-[8px] border border-dashed px-3 text-center transition-colors duration-[var(--dur-2)]",
          over === physics ? "border-[var(--focus)] bg-accent-soft text-fg" : "border-line-strong text-fg-2",
        )}
      >
        <Icon size={20} className={over === physics ? "text-accent-text" : "text-fg-3"} />
        <span className="text-em font-medium">{t(`physics.${physics}`)}</span>
        <span className="text-label text-fg-3">{t(`import.as.${physics}`)}</span>
      </div>
    );
  };
  return (
    <div className="anim-in fixed inset-0 z-[85] flex items-center justify-center bg-black/30 dark:bg-black/55">
      <div className="anim-rise w-[min(800px,calc(100vw-32px))] rounded-[8px] bg-overlay p-4 shadow-overlay">
        <div className="mb-3 flex items-center gap-2">
          <FileUp size={16} className="text-fg-2" />
          <span className="text-em font-semibold text-fg">{t("import.dropTitle")}</span>
        </div>
        <div className="flex gap-3">
          {CAD_PHYSICS.map((ph) => (
            <div key={ph} className="flex min-w-0 flex-1">
              {target(ph)}
            </div>
          ))}
        </div>
        <p className="mt-3 text-label text-fg-3">{t("import.formats")}</p>
      </div>
    </div>
  );
}

/** Small busy line used while an upload is in flight. */
export function useImporting() {
  return useStore((s) => s.importing);
}
