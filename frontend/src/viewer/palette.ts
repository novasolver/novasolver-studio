// Viewport colours per theme. Shared by the 3D viewer and by the host UI (face-list
// swatches use these exact values so the list doubles as a legend). No framework imports.

export type ViewerTheme = "dark" | "light";

export interface ViewerPalette {
  /** resting part colour */
  base: string;
  /** feature edges on geometry */
  edge: string;
  edgeAlpha: number;
  /** feature edges on result fields */
  fieldEdge: string;
  fieldEdgeAlpha: number;
  /** undeformed outline (dashed) shown with deformed results */
  ghost: string;
  ghostAlpha: number;
  /** mesh wireframe (mesh step) */
  wire: string;
  wireAlpha: number;
  /** ground grid + contact shadow */
  grid: string;
  gridMinorAlpha: number;
  gridMajorAlpha: number;
  shadowAlpha: number;
  /** selection / hover (accent) */
  selection: string;
  selectionTint: number;
  hoverAlpha: number;
  /** free-stream arrows in front of a body (external flow) */
  flow: string;
  flowAlpha: number;
  /** face roles on the boundaries step */
  roles: {
    fixed: string;
    loaded: string;
    exchange: string;
    unassigned: string;
    flash: string;
    locked: string;
  };
}

export const VIEWER_PALETTES: Record<ViewerTheme, ViewerPalette> = {
  dark: {
    base: "#a4a8b0",
    edge: "#0b0c0e",
    edgeAlpha: 0.5,
    fieldEdge: "#000000",
    fieldEdgeAlpha: 0.35,
    ghost: "#c9ccd3",
    ghostAlpha: 0.3,
    wire: "#0b0c0e",
    wireAlpha: 0.3,
    grid: "#ffffff",
    gridMinorAlpha: 0.035,
    gridMajorAlpha: 0.07,
    shadowAlpha: 0.32,
    selection: "#22d3ee",
    selectionTint: 0.3,
    hoverAlpha: 0.6,
    flow: "#c9ccd3",
    flowAlpha: 0.85,
    roles: {
      fixed: "#5a5f68",
      loaded: "#dde0e5",
      exchange: "#7f93ad",
      unassigned: "#f5a524",
      flash: "#fb923c",
      locked: "#34373d",
    },
  },
  light: {
    base: "#b3b7be",
    edge: "#18181b",
    edgeAlpha: 0.45,
    fieldEdge: "#000000",
    fieldEdgeAlpha: 0.3,
    ghost: "#18181b",
    ghostAlpha: 0.28,
    wire: "#18181b",
    wireAlpha: 0.22,
    grid: "#18181b",
    gridMinorAlpha: 0.045,
    gridMajorAlpha: 0.09,
    shadowAlpha: 0.1,
    selection: "#0891b2",
    selectionTint: 0.3,
    hoverAlpha: 0.7,
    flow: "#3f4249",
    flowAlpha: 0.8,
    roles: {
      fixed: "#4d525a",
      loaded: "#f1f2f4",
      exchange: "#8597b0",
      unassigned: "#f59e0b",
      flash: "#fb923c",
      locked: "#d3d6db",
    },
  },
};

/** Viewport colour for a face role (null = resting colour). */
export function roleColor(theme: ViewerTheme, role: string | null | undefined, locked?: boolean): string {
  const p = VIEWER_PALETTES[theme];
  if (locked) return p.roles.locked;
  if (!role) return p.roles.unassigned;
  return groupColor(theme, roleGroup(role));
}

/** Roles that hold a value fixed (displacement, temperature; symmetry holds the normal displacement). */
export const FIXED_ROLES = new Set(["fixed", 'beam-clamp', "symmetry", "constraint", 'displacement', 'spring', "temperature", "voltage"]);
/** Roles that drive the problem (force, pressure, heat input, inflow, moving wall). */
export const LOADED_ROLES = new Set(["load", "pressure", "heat-flux", "inlet", "moving-wall", "surface-charge", "current", 'moment', 'bearing', 'remote-force']);
/** Roles that exchange with the surroundings (convection, outflow). */
export const EXCHANGE_ROLES = new Set(["convection", "outlet", 'contact']);

export type RoleGroup = "fixed" | "loaded" | "exchange" | "unassigned" | "base";

export function roleGroup(role: string | null | undefined): RoleGroup {
  if (!role) return "unassigned";
  if (FIXED_ROLES.has(role)) return "fixed";
  if (LOADED_ROLES.has(role)) return "loaded";
  if (EXCHANGE_ROLES.has(role)) return "exchange";
  return "base";
}

/** Colour for a role group (base = resting part colour). */
export function groupColor(theme: ViewerTheme, g: RoleGroup): string {
  const p = VIEWER_PALETTES[theme];
  return g === "base" ? p.base : p.roles[g];
}
