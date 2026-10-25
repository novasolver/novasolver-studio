import { Activity, Atom, Box, Grid3x3, Pin, Play, type LucideIcon } from "lucide-react";
import type { StepId } from "../api/types";

export const STEP_ICONS: Record<StepId, LucideIcon> = {
  geometry: Box,
  mesh: Grid3x3,
  physics: Atom,
  boundaries: Pin,
  run: Play,
  results: Activity,
};
