import { useEffect } from "react";
import { TopBar } from "./components/TopBar";
import { Sidebar } from "./components/Sidebar";
import { ViewerPane } from "./components/ViewerPane";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { LogDrawer } from "./components/LogStrip";
import { StatusBar } from "./components/StatusBar";
import { StartScreen } from "./components/StartScreen";
import { CommandPalette } from "./components/CommandPalette";
import { AiPanel } from "./components/AiPanel";
import { DropOverlay } from "./components/ImportCad";
import { getState, goStep, selectFace, setState, STEPS, ui, useStore, viewCmd } from "./state/store";

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.palette();
        return;
      }
      const s = getState();
      if (s.palette || e.ctrlKey || e.metaKey || e.altKey || isTyping(e)) return;
      if (e.key === "Escape") {
        if (s.ai) ui.ai(false);
        else if (s.logOpen) ui.log(false);
        else if (s.selectedFaces.length || s.flashFaces.length) {
          selectFace(null);
          setState({ flashFaces: [] });
        }
        return;
      }
      if (!s.payload) return;
      if (/^[1-6]$/.test(e.key)) {
        e.preventDefault();
        goStep(STEPS[Number(e.key) - 1]);
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        viewCmd("fit");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export default function App() {
  useShortcuts();
  const hasCase = useStore((s) => !!s.payload);
  return (
    <div className="flex h-full flex-col bg-bg">
      <TopBar />
      <div className="relative flex min-h-0 flex-1">
        {hasCase ? (
          <>
            <Sidebar />
            {/* the viewport is the "sheet" inside one chrome ground (inverted L) */}
            <div className="flex min-w-0 flex-1 flex-col gap-1.5 p-1.5 dark:gap-0 dark:p-0">
              <ViewerPane />
              <LogDrawer />
            </div>
            <PropertiesPanel />
          </>
        ) : (
          <StartScreen />
        )}
        <AiPanel />
      </div>
      <StatusBar />
      <CommandPalette />
      <DropOverlay />
    </div>
  );
}
