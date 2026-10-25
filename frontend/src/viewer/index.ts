// Public entry of the framework-independent viewer (DESIGN.md §7).
export { Viewer } from "./Viewer";
export type { FaceId, ViewName, ViewerFace, ViewerGeometry, ViewerField, FacePickHandler, FaceHoverHandler } from "./Viewer";
export { cssGradient, sample, getLut } from "./colormaps";
export type { ColormapName } from "./colormaps";
export { VIEWER_PALETTES, roleColor, roleGroup, groupColor } from "./palette";
export type { ViewerTheme, ViewerPalette, RoleGroup } from "./palette";

import { Viewer } from "./Viewer";

/** Convenience factory: `const viewer = createViewer(el)`. */
export function createViewer(container: HTMLElement): Viewer {
  return new Viewer(container);
}
