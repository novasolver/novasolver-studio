// Colormaps shared by the 3D viewer and the colour bar. No framework imports.

export type ColormapName = "viridis" | "coolwarm";

type Stop = [number, string];

const STOPS: Record<ColormapName, Stop[]> = {
  // perceptually uniform, colour-vision friendly (sequential)
  viridis: [
    [0.0, "#440154"],
    [0.125, "#472d7b"],
    [0.25, "#3b528b"],
    [0.375, "#2c728e"],
    [0.5, "#21918c"],
    [0.625, "#28ae80"],
    [0.75, "#5ec962"],
    [0.875, "#addc30"],
    [1.0, "#fde725"],
  ],
  // Moreland diverging (signed quantities)
  coolwarm: [
    [0.0, "#3b4cc0"],
    [0.125, "#5d7ce6"],
    [0.25, "#82a6fb"],
    [0.375, "#aac7fd"],
    [0.5, "#dddddd"],
    [0.625, "#f7b89c"],
    [0.75, "#ee8468"],
    [0.875, "#d65244"],
    [1.0, "#b40426"],
  ],
};

function hex(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

const LUT_SIZE = 256;
const luts = new Map<ColormapName, Float32Array>();

/** 256-entry sRGB lookup table (r,g,b in 0..1). */
export function getLut(name: ColormapName): Float32Array {
  let lut = luts.get(name);
  if (lut) return lut;
  const stops = STOPS[name].map(([t, c]) => [t, ...hex(c)] as [number, number, number, number]);
  lut = new Float32Array(LUT_SIZE * 3);
  for (let i = 0; i < LUT_SIZE; i++) {
    const t = i / (LUT_SIZE - 1);
    let k = 0;
    while (k < stops.length - 2 && t > stops[k + 1][0]) k++;
    const a = stops[k];
    const b = stops[k + 1];
    const u = Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0])));
    lut[i * 3] = a[1] + (b[1] - a[1]) * u;
    lut[i * 3 + 1] = a[2] + (b[2] - a[2]) * u;
    lut[i * 3 + 2] = a[3] + (b[3] - a[3]) * u;
  }
  luts.set(name, lut);
  return lut;
}

/** Sample a colormap at t in [0,1]; returns sRGB triple. */
export function sample(name: ColormapName, t: number): [number, number, number] {
  const lut = getLut(name);
  const i = Math.round(Math.min(1, Math.max(0, t)) * (LUT_SIZE - 1)) * 3;
  return [lut[i], lut[i + 1], lut[i + 2]];
}

/** CSS gradient for colour bars. */
export function cssGradient(name: ColormapName, direction = "to right"): string {
  const parts = STOPS[name].map(([t, c]) => `${c} ${(t * 100).toFixed(1)}%`);
  return `linear-gradient(${direction}, ${parts.join(", ")})`;
}
