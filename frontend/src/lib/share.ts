// Share image (PNG) and turntable video (MP4) of the shown result, drawn from the 3D viewer on this machine.
// Every frame carries the product name and URL in the bottom-right corner; nothing is uploaded anywhere.
import { ArrayBufferTarget, Muxer } from "mp4-muxer";
import { sample, type ColormapName } from "../viewer/colormaps";
import type { Viewer } from "../viewer";

export const SHARE_URL = "novasolver.jp/studio";

export interface ShareInfo {
  title: string;
  lead: { label: string; value: string } | null;
  check: { text: string; pass: boolean } | null;
  outputs: { label: string; value: string }[];
  legend: { label: string; lo: string; hi: string; colormap: ColormapName } | null;
}

export type ShareLayout = "wide" | "tall";
export const LAYOUT_SIZE: Record<ShareLayout, [number, number]> = { wide: [1600, 900], tall: [1080, 1920] };

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

const FONT = getComputedStyle(document.documentElement).getPropertyValue("--font-sans").trim() || "system-ui, sans-serif";

function font(px: number, weight = 400) {
  return `${weight} ${Math.round(px)}px ${FONT}`;
}

/** Shrink text to maxW by cutting it with an ellipsis. */
function fit(ctx: CanvasRenderingContext2D, s: string, maxW: number): string {
  if (ctx.measureText(s).width <= maxW) return s;
  let t = s;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
  return t + "…";
}

/** The product mark (same diamond as the top bar) at (x, y) with size d. */
function mark(ctx: CanvasRenderingContext2D, x: number, y: number, d: number) {
  const k = d / 24;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k, k);
  ctx.fillStyle = css("--accent-fill");
  ctx.fill(new Path2D("M12 1.5 22.5 12 12 22.5 1.5 12Z"));
  ctx.fillStyle = css("--vp-bottom");
  ctx.fill(new Path2D("M12 7.2 16.8 12 12 16.8 7.2 12Z"));
  ctx.restore();
}

/** One finished frame: viewport background, the rendered model, result figures, colour legend and brand. */
export function composeFrame(out: HTMLCanvasElement, view: CanvasImageSource, info: ShareInfo) {
  const W = out.width;
  const H = out.height;
  const ctx = out.getContext("2d")!;
  const s = Math.min(W, H) / 900;
  const pad = 44 * s;
  const fg = css("--text");
  const fg2 = css("--text-2");

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, css("--vp-top"));
  bg.addColorStop(1, css("--vp-bottom"));
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  ctx.drawImage(view, 0, 0, W, H);
  ctx.textBaseline = "alphabetic";

  // figures, top left
  let y = pad + 26 * s;
  ctx.fillStyle = fg;
  ctx.font = font(26 * s, 600);
  ctx.fillText(fit(ctx, info.title, W - 2 * pad), pad, y);
  if (info.lead) {
    y += 46 * s;
    ctx.fillStyle = fg2;
    ctx.font = font(19 * s, 500);
    ctx.fillText(fit(ctx, info.lead.label, W - 2 * pad), pad, y);
    y += 52 * s;
    ctx.fillStyle = fg;
    ctx.font = font(46 * s, 600);
    ctx.fillText(info.lead.value, pad, y);
  }
  if (info.check) {
    y += 36 * s;
    ctx.fillStyle = css(info.check.pass ? "--green" : "--red");
    ctx.font = font(19 * s, 500);
    ctx.fillText(fit(ctx, (info.check.pass ? "✓ " : "✕ ") + info.check.text, W - 2 * pad), pad, y);
  }
  y += 18 * s;
  for (const o of info.outputs) {
    y += 32 * s;
    ctx.font = font(19 * s, 400);
    ctx.fillStyle = fg2;
    ctx.fillText(o.label, pad, y);
    const lw = ctx.measureText(o.label + "  ").width;
    ctx.font = font(19 * s, 600);
    ctx.fillStyle = fg;
    ctx.fillText(o.value, pad + lw, y);
  }

  // colour legend, bottom left
  if (info.legend) {
    const bw = Math.min(380 * s, W * 0.42);
    const bh = 14 * s;
    const by = H - pad - 30 * s;
    ctx.fillStyle = fg;
    ctx.font = font(18 * s, 500);
    ctx.fillText(fit(ctx, info.legend.label, bw), pad, by - 14 * s);
    const n = 96;
    for (let i = 0; i < n; i++) {
      const [r, g, b] = sample(info.legend.colormap, i / (n - 1));
      ctx.fillStyle = `rgb(${(r * 255) | 0},${(g * 255) | 0},${(b * 255) | 0})`;
      ctx.fillRect(pad + (bw * i) / n, by, bw / n + 1, bh);
    }
    ctx.fillStyle = fg2;
    ctx.font = font(16 * s, 400);
    ctx.fillText(info.legend.lo, pad, by + bh + 22 * s);
    const hw = ctx.measureText(info.legend.hi).width;
    ctx.fillText(info.legend.hi, pad + bw - hw, by + bh + 22 * s);
  }

  // brand, bottom right
  ctx.font = font(22 * s, 600);
  const name = "NovaSolver Studio";
  const nw = ctx.measureText(name).width;
  ctx.font = font(16 * s, 400);
  const uw = ctx.measureText(SHARE_URL).width;
  const tw = Math.max(nw, uw);
  const d = 34 * s;
  const right = W - pad;
  const base = H - pad;
  mark(ctx, right - tw - d - 12 * s, base - 40 * s, d);
  ctx.fillStyle = fg;
  ctx.font = font(22 * s, 600);
  ctx.fillText(name, right - tw, base - 20 * s);
  ctx.fillStyle = fg2;
  ctx.font = font(16 * s, 400);
  ctx.fillText(SHARE_URL, right - tw, base);
}

export async function shareImage(viewer: Viewer, info: ShareInfo, layout: ShareLayout): Promise<Blob> {
  await document.fonts.ready;
  const [W, H] = LAYOUT_SIZE[layout];
  const view = viewer.snapshot(W, H);
  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  composeFrame(out, view, info);
  return new Promise((res, rej) => out.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));
}

export function videoSupported(): boolean {
  return typeof VideoEncoder !== "undefined" && typeof VideoFrame !== "undefined";
}

/**
 * One full turn of the model in `seconds` at 30 fps, H.264 in MP4 (plays on X, YouTube Shorts, TikTok, Instagram).
 * Frames are encoded with explicit timestamps, so a slow GPU makes the export slower, never the video choppier.
 */
export async function turntableVideo(
  viewer: Viewer,
  info: ShareInfo,
  layout: ShareLayout,
  onProgress: (u: number) => void,
  signal?: AbortSignal,
  seconds = 8,
): Promise<Blob> {
  await document.fonts.ready;
  const [W, H] = LAYOUT_SIZE[layout];
  const fps = 30;
  const n = seconds * fps;
  const muxer = new Muxer({ target: new ArrayBufferTarget(), video: { codec: "avc", width: W, height: H }, fastStart: "in-memory" });
  let failure: unknown = null;
  const enc = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => (failure = e),
  });
  const config: VideoEncoderConfig = { codec: "avc1.640028", width: W, height: H, bitrate: 8_000_000, framerate: fps };
  if (!(await VideoEncoder.isConfigSupported(config)).supported) config.codec = "avc1.42003e";
  enc.configure(config);
  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  viewer.beginCapture(W, H);
  try {
    for (let i = 0; i < n; i++) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      if (failure) throw failure;
      // ease in and out of the turn so the loop starts and ends calmly on the user's view
      const u = i / n;
      const angle = 2 * Math.PI * (u - Math.sin(2 * Math.PI * u) / (2 * Math.PI));
      composeFrame(out, viewer.captureFrame(angle), info);
      const frame = new VideoFrame(out, { timestamp: Math.round((i * 1e6) / fps), duration: Math.round(1e6 / fps) });
      enc.encode(frame, { keyFrame: i % (fps * 2) === 0 });
      frame.close();
      while (enc.encodeQueueSize > 4) await new Promise((r) => setTimeout(r, 4));
      if (i % 6 === 0) {
        onProgress(u);
        await new Promise((r) => setTimeout(r, 0)); // let the progress paint (rAF would stall in a background tab)
      }
    }
    await enc.flush();
    if (failure) throw failure;
  } finally {
    viewer.endCapture();
    if (enc.state !== "closed") enc.close();
  }
  muxer.finalize();
  onProgress(1);
  return new Blob([muxer.target.buffer], { type: "video/mp4" });
}

export function download(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

export async function copyImage(blob: Blob): Promise<boolean> {
  try {
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch {
    return false;
  }
}
