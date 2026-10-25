// Development-only, offline fallback for the Studio backend (DESIGN.md §6).
// Loaded lazily by client.ts ONLY when GET /api/templates fails on startup, so it never
// sits on the production path. Shapes mirror the real backend (2026-10-25): faces are
// identified by keys ("x0".."z1"), checks carry face keys, results can be stale, etc.

import type {
  CasePayload,
  CaseSchema,
  Check,
  FieldPayload,
  GeometryFace,
  Job,
  Lang,
  ResultsPayload,
  StepId,
  StepStatus,
  Template,
  UiParam,
  WsMessage,
} from "./types";
import { parseWithUnit, toSI } from "../lib/units";

type L3 = { ja: string; en: string; zh: string };
const l3 = (ja: string, en: string, zh: string): L3 => ({ ja, en, zh });

export interface MockResponse {
  status: number;
  body: unknown;
}

const TEMPLATES: Template[] = [
  {
    id: "cantilever",
    physics: "structural",
    title: l3("片持ち梁", "Cantilever beam", "悬臂梁"),
    description: l3(
      "一端を固定した角棒の先端に荷重をかけ、たわみと応力を求めます。梁理論の手計算と自動で比較します。",
      "A bar fixed at one end and loaded at the tip. Deflection and stress are checked against beam theory.",
      "一端固定的方截面梁在端部受载，求挠度与应力，并自动与梁理论手算对比。",
    ),
    has_reference: true,
    engines: [{ id: "builtin-fem", available: true }, { id: "calculix", available: false }],
    runnable_now: true,
  },
  {
    id: "cavity",
    physics: "cfd",
    title: l3("キャビティ流れ", "Lid-driven cavity", "顶盖驱动方腔流"),
    description: l3(
      "ふたが動く正方形の箱の中の流れ。CFDの標準問題で、Ghia らの参照値（Re=100）と比較します。",
      "Flow in a square box with a moving lid — the classic CFD benchmark, compared with Ghia et al. (Re = 100).",
      "顶盖移动的方腔内流动，CFD 标准算例，与 Ghia 等人的参考值（Re=100）对比。",
    ),
    has_reference: true,
    engines: [{ id: "builtin-cavity", available: true }, { id: "openfoam", available: false }],
    runnable_now: true,
  },
  {
    id: "channel",
    physics: "cfd",
    title: l3("平行平板の流れ", "Plane channel flow", "平行平板流动"),
    description: l3(
      "2枚の板の間を流れる層流。十分発達した速度分布が放物線（ポアズイユ流れ）になるかを確かめます。",
      "Laminar flow between two plates. Checks that the developed profile is the Poiseuille parabola.",
      "两平板间的层流。验证充分发展的速度分布是否为抛物线（泊肃叶流）。",
    ),
    has_reference: true,
    engines: [{ id: "openfoam", available: false }],
    runnable_now: false,
  },
];

type Q = { value: number; unit: string };
const KEYS = ["x0", "x1", "y0", "y1", "z0", "z1"] as const;
type Key = (typeof KEYS)[number];

interface MockCase {
  schema: CaseSchema;
  physics: "structural" | "cfd";
  dims: { length: Q; width: Q; height: Q };
  material: { preset: string; E: Q; nu: number };
  fluid: { preset: string; nu: Q };
  roles: Record<Key, string>;
  locked: Key[];
  values: Partial<Record<Key, Q>>;
  meshSize: "coarse" | "normal" | "fine";
  meshStats: { nodes: number; elements: number; element_type: string; quality_min: number; quality_mean: number } | null;
  meshKey: string | null;
  mode: "preview" | "final";
  results: { inputKey: string; revision: number; mode: string } | null;
  updated: number;
}

const MATERIALS: Record<string, { label: L3; E: number; nu: number }> = {
  steel: { label: l3("鋼", "Steel", "钢"), E: 205, nu: 0.3 },
  aluminium: { label: l3("アルミニウム", "Aluminium", "铝"), E: 70, nu: 0.33 },
  titanium: { label: l3("チタン", "Titanium", "钛"), E: 114, nu: 0.34 },
};

const ROLES_STRUCT = ["free", "fixed", "load", "pressure"];
const ROLES_CFD = ["wall", "moving-wall", "inlet", "outlet", "symmetry"];
const ROLE_LABEL: Record<string, L3> = {
  free: l3("自由", "Free", "自由"),
  fixed: l3("固定", "Fixed", "固定"),
  load: l3("荷重", "Load", "载荷"),
  pressure: l3("圧力", "Pressure", "压力"),
  symmetry: l3("対称", "Symmetry", "对称"),
  inlet: l3("入口", "Inlet", "入口"),
  outlet: l3("出口", "Outlet", "出口"),
  wall: l3("壁", "Wall", "壁面"),
  "moving-wall": l3("移動壁", "Moving wall", "移动壁面"),
  plane2d: l3("2次元平面", "2D plane", "二维平面"),
};

const FACE_LABELS: Record<Key, L3> = {
  x0: l3("左端面 (x=0)", "Left end (x = 0)", "左端面 (x=0)"),
  x1: l3("右端面 (x=L)", "Right end (x = L)", "右端面 (x=L)"),
  y0: l3("手前の側面", "Front side", "前侧面"),
  y1: l3("奥の側面", "Back side", "后侧面"),
  z0: l3("下面", "Bottom", "底面"),
  z1: l3("上面", "Top", "顶面"),
};

const cases = new Map<string, MockCase>();
const jobs = new Map<string, Job & { t0: number; dur: number; timer?: number }>();
const listeners = new Set<(m: WsMessage) => void>();

export function subscribe(cb: (m: WsMessage) => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
const emit = (m: WsMessage) => listeners.forEach((l) => l(m));

function newId(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `c_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}_${Math.random().toString(16).slice(2, 6)}`;
}

function createCase(templateId: string): MockCase {
  const tpl = TEMPLATES.find((t) => t.id === templateId) ?? TEMPLATES[0];
  const structural = tpl.physics === "structural";
  const dims =
    tpl.id === "cantilever"
      ? { length: { value: 200, unit: "mm" }, width: { value: 20, unit: "mm" }, height: { value: 20, unit: "mm" } }
      : tpl.id === "cavity"
        ? { length: { value: 100, unit: "mm" }, width: { value: 100, unit: "mm" }, height: { value: 10, unit: "mm" } }
        : { length: { value: 400, unit: "mm" }, width: { value: 10, unit: "mm" }, height: { value: 40, unit: "mm" } };
  const roles: Record<Key, string> = structural
    ? { x0: "fixed", x1: "load", y0: "free", y1: "free", z0: "free", z1: "free" }
    : tpl.id === "cavity"
      ? { x0: "wall", x1: "wall", y0: "wall", y1: "moving-wall", z0: "plane2d", z1: "plane2d" }
      : { x0: "inlet", x1: "outlet", y0: "wall", y1: "wall", z0: "plane2d", z1: "plane2d" };
  const values: Partial<Record<Key, Q>> = structural
    ? { x1: { value: 1000, unit: "N" } }
    : tpl.id === "cavity"
      ? { y1: { value: 0.01, unit: "m/s" } }
      : { x0: { value: 0.01, unit: "m/s" } };
  const id = newId();
  const mc: MockCase = {
    physics: tpl.physics === "cfd" ? "cfd" : "structural",
    dims,
    material: { preset: "steel", E: { value: 205, unit: "GPa" }, nu: 0.3 },
    fluid: { preset: "custom", nu: { value: 1e-5, unit: "m2/s" } },
    roles,
    locked: structural ? [] : ["z0", "z1"],
    values,
    meshSize: "normal",
    meshStats: null,
    meshKey: null,
    mode: "preview",
    results: null,
    updated: Date.now(),
    schema: {
      schema_version: "0.1",
      case_id: id,
      revision: 1,
      title: tpl.title,
      template: tpl.id,
      physics: { kind: structural ? "linear-static" : "incompressible-steady" },
    },
  };
  cases.set(id, mc);
  return mc;
}

const si = (q: Q) => toSI(q.value, q.unit);
const geomKey = (c: MockCase) => JSON.stringify([c.dims, c.meshSize]);
const inputKey = (c: MockCase) => JSON.stringify([c.dims, c.material, c.fluid, c.roles, c.values, c.meshSize]);

function beam(c: MockCase) {
  const L = si(c.dims.length);
  const b = si(c.dims.width);
  const h = si(c.dims.height);
  const E = toSI(c.material.E.value, c.material.E.unit);
  const I = (b * h ** 3) / 12;
  const lk = KEYS.find((k) => c.roles[k] === "load");
  const P = lk && c.values[lk] ? si(c.values[lk]!) : 0;
  const ref = (P * L ** 3) / (3 * E * I);
  const err = { coarse: -0.031, normal: -0.0085, fine: -0.0021 }[c.meshSize];
  return { L, b, h, E, I, P, ref, computed: ref * (1 + err), err };
}

function cfd(c: MockCase) {
  const L = si(c.dims.length);
  const H = si(c.dims.width);
  const nu = si(c.fluid.nu);
  const uk = KEYS.find((k) => c.roles[k] === "moving-wall" || c.roles[k] === "inlet");
  const U = uk && c.values[uk] ? si(c.values[uk]!) : 0;
  return { L, H, nu, U, Re: (U * (c.schema.template === "cavity" ? L : H)) / nu };
}

function grid(o: number[], u: number[], v: number[], nu: number, nv: number) {
  const positions: number[] = [];
  const indices: number[] = [];
  for (let j = 0; j <= nv; j++)
    for (let i = 0; i <= nu; i++) {
      const a = i / nu;
      const b = j / nv;
      positions.push(o[0] + u[0] * a + v[0] * b, o[1] + u[1] * a + v[1] * b, o[2] + u[2] * a + v[2] * b);
    }
  for (let j = 0; j < nv; j++)
    for (let i = 0; i < nu; i++) {
      const p = j * (nu + 1) + i;
      indices.push(p, p + 1, p + nu + 2, p, p + nu + 2, p + nu + 1);
    }
  return { positions, indices };
}

function boxFaces(Lx: number, Ly: number, Lz: number, n: [number, number, number]) {
  const [nx, ny, nz] = n;
  return [
    grid([0, 0, 0], [0, Ly, 0], [0, 0, Lz], ny, nz),
    grid([Lx, 0, 0], [0, Ly, 0], [0, 0, Lz], ny, nz),
    grid([0, 0, 0], [Lx, 0, 0], [0, 0, Lz], nx, nz),
    grid([0, Ly, 0], [Lx, 0, 0], [0, 0, Lz], nx, nz),
    grid([0, 0, 0], [Lx, 0, 0], [0, Ly, 0], nx, ny),
    grid([0, 0, Lz], [Lx, 0, 0], [0, Ly, 0], nx, ny),
  ];
}

function geometry(c: MockCase, lang: Lang) {
  const Lx = si(c.dims.length);
  const Ly = si(c.dims.width);
  const Lz = si(c.dims.height);
  const meshed = !!c.meshStats && c.meshKey === geomKey(c);
  const n: [number, number, number] = meshed ? [24, 4, 4] : [1, 1, 1];
  const faces: GeometryFace[] = boxFaces(Lx, Ly, Lz, n).map((f, i) => ({
    id: i + 1,
    key: KEYS[i],
    region: KEYS[i],
    label: FACE_LABELS[KEYS[i]][lang],
    role: c.roles[KEYS[i]],
    positions: f.positions,
    indices: f.indices,
  }));
  return { faces, bbox: [[0, 0, 0], [Lx, Ly, Lz]] };
}

function params(c: MockCase, lang: Lang): UiParam[] {
  const LEN = ["m", "cm", "mm", "um"];
  const p: UiParam[] = [
    { path: "geometry.params.length", label: l3("長さ", "Length", "长度")[lang], ...c.dims.length, units: LEN },
    { path: "geometry.params.width", label: l3(c.physics === "cfd" ? "高さ" : "幅", c.physics === "cfd" ? "Height" : "Width", c.physics === "cfd" ? "高度" : "宽度")[lang], ...c.dims.width, units: LEN },
    { path: "geometry.params.height", label: l3(c.physics === "cfd" ? "奥行き" : "高さ", c.physics === "cfd" ? "Depth" : "Height", c.physics === "cfd" ? "厚度" : "高度")[lang], ...c.dims.height, units: LEN },
  ];
  for (const k of KEYS) {
    const r = c.roles[k];
    const q = c.values[k];
    if (r === "load") p.push({ path: `boundaries.${k}.force`, label: l3("先端荷重（下向き）", "Tip load (downward)", "端部载荷（向下）")[lang], ...(q ?? { value: 1000, unit: "N" }), units: ["N", "kN"] });
    if (r === "pressure") p.push({ path: `boundaries.${k}.pressure`, label: l3("圧力", "Pressure", "压力")[lang], ...(q ?? { value: 1, unit: "MPa" }), units: ["Pa", "kPa", "MPa"] });
    if (r === "moving-wall" || r === "inlet") p.push({ path: `boundaries.${k}.speed`, label: l3("速度", "Speed", "速度")[lang], ...(q ?? { value: 0.01, unit: "m/s" }), units: ["m/s", "mm/s"] });
  }
  if (c.physics === "structural")
    p.push(
      { path: "materials.solid.E", label: l3("ヤング率", "Young's modulus", "杨氏模量")[lang], ...c.material.E, units: ["Pa", "kPa", "MPa", "GPa"] },
      { path: "materials.solid.nu", label: l3("ポアソン比", "Poisson's ratio", "泊松比")[lang], value: c.material.nu, unit: "-", units: ["-"] },
    );
  else p.push({ path: "materials.fluid.nu", label: l3("動粘度", "Kinematic viscosity", "运动黏度")[lang], ...c.fluid.nu, units: ["m2/s", "mm2/s"] });
  return p;
}

function checks(c: MockCase, lang: Lang): Check[] {
  const out: Check[] = [];
  const roles = Object.values(c.roles);
  if (c.physics === "structural") {
    if (!roles.includes("fixed"))
      out.push({ level: "error", code: "no_fixed", step: "boundaries", message: l3("固定面がありません（剛体運動）", "No fixed face (rigid-body motion)", "没有固定面（刚体运动）")[lang] });
    if (!roles.includes("load") && !roles.includes("pressure"))
      out.push({
        level: "error",
        code: "no_load",
        step: "boundaries",
        faces: ["x1"],
        message: l3("荷重がありません", "No load applied", "没有施加载荷")[lang],
      });
    const b = beam(c);
    if (b.L / b.h < 10)
      out.push({
        level: "warn",
        code: "low_slenderness",
        step: "geometry",
        message: l3(`細長比 L/H = ${(b.L / b.h).toFixed(1)}：梁理論との比較は目安です`, `Slenderness L/H = ${(b.L / b.h).toFixed(1)}: beam theory is only indicative`, `长细比 L/H = ${(b.L / b.h).toFixed(1)}：梁理论对比仅供参考`)[lang],
      });
  } else {
    if (!roles.includes("inlet") && !roles.includes("moving-wall"))
      out.push({ level: "error", code: "no_driver", step: "boundaries", message: l3("流れを起こす境界（入口・移動壁）がありません", "Nothing drives the flow (inlet or moving wall)", "没有驱动流动的边界（入口或移动壁面）")[lang] });
    const { Re } = cfd(c);
    if (Re > 2000)
      out.push({ level: "warn", code: "re_high", step: "physics", message: l3(`レイノルズ数 ${Re.toFixed(0)}：層流の範囲外です`, `Reynolds number ${Re.toFixed(0)} is outside the laminar range`, `雷诺数 ${Re.toFixed(0)}：超出层流范围`)[lang] });
    if (c.schema.template === "channel")
      out.push({ level: "warn", code: "engine_missing", step: "run", message: l3("OpenFOAM が見つかりません。設定はできますが実行できません", "OpenFOAM not found — you can set up but not run", "未找到 OpenFOAM，可以设置但无法运行")[lang] });
  }
  if (c.meshStats && c.meshKey !== geomKey(c))
    out.push({ level: "warn", code: "mesh_stale", step: "mesh", message: l3("形状が変わりました。メッシュを作り直してください", "Geometry changed — regenerate the mesh", "几何已更改，请重新生成网格")[lang] });
  return out;
}

function steps(c: MockCase, ch: Check[]): Record<StepId, StepStatus> {
  const has = (s: StepId, level?: "error" | "warn") => ch.some((x) => x.step === s && (!level || x.level === level));
  const meshOk = !!c.meshStats && c.meshKey === geomKey(c);
  const res = c.results ? resultsPayload(c, "en") : null;
  return {
    geometry: has("geometry") ? "warn" : "ok",
    mesh: !c.meshStats ? "todo" : meshOk ? "ok" : "warn",
    physics: has("physics") ? "warn" : "ok",
    boundaries: has("boundaries") ? "warn" : "ok",
    run: !c.results ? "todo" : res?.stale ? "warn" : "ok",
    results: !res ? "todo" : res.gates.verified && !res.stale ? "ok" : "warn",
  };
}

function payload(c: MockCase, lang: Lang): CasePayload {
  const ch = checks(c, lang);
  const structural = c.physics === "structural";
  const roleIds = structural ? ROLES_STRUCT : ROLES_CFD;
  c.schema.mesh = { method: "gmsh", size: c.meshSize, order: 2 };
  c.schema.run = { mode: c.mode, max_wall_s: 900 };
  return {
    case: structuredClone(c.schema),
    steps: steps(c, ch),
    checks: ch,
    ready: !ch.some((x) => x.level === "error"),
    engine: structural ? "builtin-fem" : c.schema.template === "cavity" ? "builtin-cavity" : "openfoam",
    ui: {
      params: params(c, lang),
      materials: structural
        ? [...Object.entries(MATERIALS).map(([id, m]) => ({ id, label: m.label[lang] })), { id: "custom", label: l3("カスタム", "Custom", "自定义")[lang] }]
        : [{ id: "custom", label: l3("カスタム", "Custom", "自定义")[lang] }],
      material_kind: structural ? "solid" : "fluid",
      roles: roleIds.map((id) => ({ id, label: ROLE_LABEL[id][lang] })),
      faces: KEYS.map((k) => ({
        key: k,
        region: k,
        label: FACE_LABELS[k][lang],
        role: c.roles[k],
        role_label: ROLE_LABEL[c.roles[k]]?.[lang] ?? c.roles[k],
        locked: c.locked.includes(k),
        value: c.values[k] ?? null,
      })),
      mesh: {
        size: c.meshSize,
        sizes: ["coarse", "normal", "fine"],
        state: { exists: !!c.meshStats, stale: !!c.meshStats && c.meshKey !== geomKey(c), stats: c.meshStats },
      },
      modes: [
        { id: "preview", engine: structural ? "builtin-fem" : c.schema.template === "cavity" ? "builtin-cavity" : null },
        { id: "final", engine: structural ? "calculix" : "openfoam" },
      ],
    },
    jobs: [...jobs.values()].filter((j) => j.case_id === c.schema.case_id && (j.state === "running" || j.state === "queued")).map(publicJob),
    latest_run: null,
  };
}

function resultsPayload(c: MockCase, lang: Lang): ResultsPayload {
  const stale = !!c.results && c.results.inputKey !== inputKey(c);
  if (c.physics === "structural") {
    const b = beam(c);
    const sigma = (b.P * b.L * (b.h / 2)) / b.I / 1e6;
    const errPct = b.err * 100;
    return {
      run_id: "r_mock",
      engine: "builtin-fem",
      mode: c.results?.mode ?? "preview",
      revision: c.results?.revision,
      stale,
      wall_s: 3.8,
      gates: { ran: true, converged: true, verified: Math.abs(errPct) <= 3 },
      cards: [
        { key: "max_disp", label: l3("最大変位", "Max displacement", "最大位移")[lang], value: b.computed * 1e3, unit: "mm" },
        { key: "max_vm", label: l3("最大ミーゼス応力", "Max von Mises stress", "最大米塞斯应力")[lang], value: sigma * 1.02, unit: "MPa" },
        { key: "reaction", label: l3("反力の合計", "Reaction sum", "反力合计")[lang], value: b.P * 0.9999, unit: "N" },
      ],
      verification: {
        label: l3("先端たわみ", "Tip deflection", "端部挠度")[lang],
        reference: b.ref * 1e3,
        computed: b.computed * 1e3,
        unit: "mm",
        error_pct: errPct,
        tolerance_pct: 3,
        pass: Math.abs(errPct) <= 3,
        metric: "tip_disp",
      },
      quantities: [
        { id: "disp_mag", label: l3("変位の大きさ", "Displacement magnitude", "位移大小")[lang], unit: "mm", kind: "sequential" },
        { id: "von_mises", label: l3("ミーゼス応力", "von Mises stress", "米塞斯应力")[lang], unit: "MPa", kind: "sequential" },
        { id: "sigma_xx", label: l3("曲げ応力 σxx", "Bending stress σxx", "弯曲应力 σxx")[lang], unit: "MPa", kind: "diverging" },
      ],
      nova_tool: "https://novasolver.jp/tools/beam-deflection.html",
      warnings:
        sigma * 1.02 > (c.material.preset === "aluminium" ? 95 : c.material.preset === "titanium" ? 880 : 245)
          ? [
              {
                code: "yield",
                message: l3(
                  "最大ミーゼス応力が材料の降伏応力を超えています。線形解析の結果は成り立ちません",
                  "Max von Mises stress exceeds the material's yield strength — the linear result does not hold",
                  "最大米塞斯应力超过材料屈服强度，线性分析结果不成立",
                )[lang],
              },
            ]
          : [],
    };
  }
  const f = cfd(c);
  const ref = -0.20581 * f.U;
  const err = 0.0012;
  return {
    run_id: "r_mock",
    engine: "builtin-cavity",
    mode: "preview",
    stale,
    wall_s: 4.1,
    gates: { ran: true, converged: true, verified: true },
    cards: [
      { key: "u_max", label: l3("最大流速", "Max velocity", "最大流速")[lang], value: f.U, unit: "m/s" },
      { key: "re", label: l3("レイノルズ数", "Reynolds number", "雷诺数")[lang], value: f.Re, unit: "" },
      { key: "u_min", label: l3("中心線の最小 u", "Min. u on centreline", "中心线最小 u")[lang], value: ref * (1 + err), unit: "m/s" },
    ],
    verification: {
      label: l3("中心線の最小 u（Ghia）", "Min. u on centreline (Ghia)", "中心线最小 u（Ghia）")[lang],
      reference: ref,
      computed: ref * (1 + err),
      unit: "m/s",
      error_pct: err * 100,
      tolerance_pct: 3,
      pass: true,
    },
    quantities: [
      { id: "speed", label: l3("流速の大きさ", "Velocity magnitude", "速度大小")[lang], unit: "m/s", kind: "sequential" },
      { id: "p", label: l3("圧力", "Pressure", "压力")[lang], unit: "Pa", kind: "diverging" },
    ],
    nova_tool: "https://novasolver.jp/",
  };
}

function fieldPayload(c: MockCase, quantity: string, lang: Lang): FieldPayload {
  const Lx = si(c.dims.length);
  const Ly = si(c.dims.width);
  const Lz = si(c.dims.height);
  const res = resultsPayload(c, lang);
  const q = res.quantities.find((x) => x.id === quantity) ?? res.quantities[0];
  const positions: number[] = [];
  const indices: number[] = [];
  const scalars: number[] = [];
  const displacement: number[] = [];
  let auto: number | undefined;

  if (c.physics === "structural") {
    const b = beam(c);
    const k = 1 + b.err;
    const nx = { coarse: 30, normal: 60, fine: 96 }[c.meshSize];
    const nyz = { coarse: 4, normal: 8, fine: 12 }[c.meshSize];
    for (const f of boxFaces(Lx, Ly, Lz, [nx, nyz, nyz])) {
      const off = positions.length / 3;
      for (let i = 0; i < f.positions.length; i += 3) {
        const x = f.positions[i];
        const zc = f.positions[i + 2] - Lz / 2;
        const w = ((b.P * x * x * (3 * b.L - x)) / (6 * b.E * b.I)) * k;
        const slope = ((b.P * x * (2 * b.L - x)) / (2 * b.E * b.I)) * k;
        const ux = zc * slope;
        const sxx = (b.P * (b.L - x) * zc) / b.I / 1e6;
        displacement.push(ux, 0, -w);
        positions.push(f.positions[i], f.positions[i + 1], f.positions[i + 2]);
        scalars.push(q.id === "disp_mag" ? Math.hypot(ux, w) * 1e3 : q.id === "sigma_xx" ? sxx : Math.abs(sxx));
      }
      for (const ix of f.indices) indices.push(ix + off);
    }
    auto = b.computed > 0 ? (0.1 * b.L) / b.computed : 1;
  } else {
    const f = cfd(c);
    const n = { coarse: 30, normal: 60, fine: 90 }[c.meshSize];
    const g = grid([0, 0, Lz * 1.002], [Lx, 0, 0], [0, Ly, 0], n, n);
    for (let i = 0; i < g.positions.length; i += 3) {
      const x = g.positions[i] / Lx;
      const y = g.positions[i + 1] / Ly;
      positions.push(g.positions[i], g.positions[i + 1], g.positions[i + 2]);
      const dpsidy = Math.sin(Math.PI * x) ** 2 * (2 * y - 3 * y * y) * 2.2;
      const dpsidx = 2 * Math.PI * Math.sin(Math.PI * x) * Math.cos(Math.PI * x) * (y * y - y ** 3) * 2.2;
      const lid = Math.exp(-(1 - y) * 14);
      const speed = f.U * Math.min(1, Math.hypot(dpsidy * 0.35 + lid, dpsidx * 0.35));
      const p = 0.5 * 1000 * f.U * f.U * (x - 0.5) * Math.exp(-(1 - y) * 4) * 0.8;
      scalars.push(q.id === "p" ? p : speed);
    }
    indices.push(...g.indices);
  }
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of scalars) {
    if (s < lo) lo = s;
    if (s > hi) hi = s;
  }
  if (q.kind === "diverging") {
    const m = Math.max(Math.abs(lo), Math.abs(hi));
    lo = -m;
    hi = m;
  }
  return {
    quantity: q.id,
    positions,
    indices,
    scalars,
    range: [lo, hi],
    ...(c.physics === "structural" ? { displacement, auto_deform_scale: auto } : {}),
    unit: q.unit,
    label: q.label,
  };
}

function publicJob(j: Job & { t0: number; dur: number }): Job {
  const { job_id, case_id, state, progress, eta_s, message, engine, mode, gates, first_error } = j;
  return { job_id, case_id, state, progress, eta_s, message, engine, mode, gates, first_error };
}

class BadValue extends Error {}

function applyChange(c: MockCase, path: string, value: unknown, lang: Lang): void {
  const asQ = (v: unknown, fallback: Q): Q => {
    let q: Q;
    if (typeof v === "string") {
      const p = parseWithUnit(v, ["m", "cm", "mm", "um", "N", "kN", "Pa", "kPa", "MPa", "GPa", "m/s", "mm/s"]);
      if (!p) throw new BadValue(l3("数値として読めません", "Not a number", "无法识别为数值")[lang]);
      q = { value: p.value, unit: p.unit ?? fallback.unit };
    } else if (v && typeof v === "object" && "value" in (v as Q)) q = { value: Number((v as Q).value), unit: String((v as Q).unit ?? fallback.unit) };
    else q = { value: Number(v), unit: fallback.unit };
    if (!Number.isFinite(q.value) || q.value <= 0) throw new BadValue(l3("正の値を入力してください", "Enter a positive value", "请输入正值")[lang]);
    return q;
  };
  const bm = path.match(/^boundaries\.([xyz][01])\.(role|force|pressure|speed)$/);
  if (bm) {
    const k = bm[1] as Key;
    if (c.locked.includes(k)) throw new BadValue(l3("この面は変更できません", "This face is locked", "此面不可更改")[lang]);
    if (bm[2] === "role") c.roles[k] = String(value);
    else c.values[k] = asQ(value, c.values[k] ?? { value: 0, unit: bm[2] === "force" ? "N" : bm[2] === "pressure" ? "MPa" : "m/s" });
    return;
  }
  const gm = path.match(/^geometry\.params\.(length|width|height)$/);
  if (gm) {
    const k = gm[1] as "length" | "width" | "height";
    c.dims[k] = asQ(value, c.dims[k]);
    return;
  }
  switch (path) {
    case "materials.solid.preset": {
      const p = MATERIALS[String(value)];
      if (p) c.material = { preset: String(value), E: { value: p.E, unit: "GPa" }, nu: p.nu };
      else c.material.preset = "custom";
      return;
    }
    case "materials.solid.E":
      c.material = { ...c.material, E: asQ(value, c.material.E), preset: "custom" };
      return;
    case "materials.solid.nu": {
      const v = Number(typeof value === "object" && value ? (value as Q).value : value);
      if (!(v >= 0 && v < 0.5)) throw new BadValue(l3("0 以上 0.5 未満にしてください", "Must be in [0, 0.5)", "须在 0 到 0.5 之间")[lang]);
      c.material = { ...c.material, nu: v, preset: "custom" };
      return;
    }
    case "materials.fluid.nu":
      c.fluid = { ...c.fluid, nu: asQ(value, c.fluid.nu) };
      return;
    case "materials.fluid.preset":
      return;
    case "mesh.size":
      if (value === "coarse" || value === "normal" || value === "fine") c.meshSize = value;
      return;
    case "run.mode":
      c.mode = value === "final" ? "final" : "preview";
      return;
  }
  throw new BadValue(`unknown path ${path}`);
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function request(method: string, url: string, body: unknown): Promise<MockResponse> {
  const u = new URL(url, "http://mock");
  const lang = (u.searchParams.get("lang") as Lang) || "ja";
  const path = u.pathname;
  await delay(method === "GET" ? 50 : 110);
  const ok = (b: unknown): MockResponse => ({ status: 200, body: b });
  const notFound: MockResponse = { status: 404, body: { error: "err.not_found", message: "not found" } };

  if (path === "/api/env") return ok({ mock: true });
  if (path === "/api/templates" && method === "GET") return ok({ templates: TEMPLATES });
  if (path === "/api/cases" && method === "GET")
    return ok({
      cases: [...cases.values()]
        .sort((a, b) => b.updated - a.updated)
        .map((c) => ({ case_id: c.schema.case_id, title: c.schema.title, template: c.schema.template, revision: c.schema.revision })),
    });
  if (path === "/api/cases" && method === "POST") return ok(payload(createCase(String((body as { template?: string })?.template ?? "cantilever")), lang));

  let m = path.match(/^\/api\/cases\/([^/]+)(\/.*)?$/);
  if (m) {
    const c = cases.get(m[1]);
    if (!c) return notFound;
    const sub = m[2] ?? "";
    if (sub === "" && method === "GET") return ok(payload(c, lang));
    if (sub === "" && method === "PATCH") {
      const b = body as { expected_revision: number; changes: Record<string, unknown> };
      if (b.expected_revision !== c.schema.revision)
        return { status: 409, body: { error: "err.revision", message: "revision conflict", current: c.schema.revision, current_revision: c.schema.revision } };
      try {
        for (const [k, v] of Object.entries(b.changes ?? {})) applyChange(c, k, v, lang);
      } catch (e) {
        if (e instanceof BadValue) return { status: 400, body: { error: "err.value", message: e.message } };
        throw e;
      }
      c.schema.revision += 1;
      c.updated = Date.now();
      return ok({ ...payload(c, lang), diff: b.changes });
    }
    if (sub === "/geometry" && method === "GET") return ok(geometry(c, lang));
    if (sub === "/mesh" && method === "POST") {
      await delay(900);
      const base = { coarse: 1800, normal: 6200, fine: 21400 }[c.meshSize];
      c.meshStats = { nodes: Math.round(base * 1.37), elements: Math.round(base * 0.62), element_type: "tet10", quality_min: 0.31, quality_mean: 0.82 };
      c.meshKey = geomKey(c);
      return ok({ ok: true, stats: c.meshStats });
    }
    if (sub === "/run" && method === "POST") {
      const mode = ((body ?? {}) as { mode?: string }).mode ?? c.mode;
      const id = `j_${Math.random().toString(36).slice(2, 8)}`;
      const dur = mode === "final" ? 7000 : 3800;
      const job = { job_id: id, case_id: c.schema.case_id, state: "queued" as Job["state"], progress: 0, eta_s: dur / 1000, message: "", mode, engine: "builtin-fem", t0: Date.now(), dur, timer: undefined as number | undefined };
      jobs.set(id, job);
      const blocked = checks(c, lang).some((x) => x.level === "error") || c.schema.template === "channel";
      const tick = () => {
        const j = jobs.get(id);
        if (!j || (j.state !== "running" && j.state !== "queued")) return;
        if (blocked) {
          j.state = "failed";
          j.first_error = l3("実行できません：準備チェックを確認してください", "Cannot run: see readiness checks", "无法运行：请查看准备检查")[lang];
          j.message = j.first_error;
          emit({ type: "job", job: publicJob(j) });
          return;
        }
        j.state = "running";
        const p = Math.min(1, (Date.now() - j.t0) / j.dur);
        j.progress = p;
        j.eta_s = Math.max(0, (j.dur * (1 - p)) / 1000);
        j.message = p < 0.2 ? l3("メッシュ準備中", "Preparing mesh", "准备网格")[lang] : p < 0.85 ? l3("求解中", "Solving", "求解中")[lang] : l3("後処理中", "Post-processing", "后处理")[lang];
        if (p >= 1) {
          if (!c.meshStats || c.meshKey !== geomKey(c)) {
            c.meshStats = { nodes: 8494, elements: 3844, element_type: "tet10", quality_min: 0.31, quality_mean: 0.82 };
            c.meshKey = geomKey(c);
          }
          c.results = { inputKey: inputKey(c), revision: c.schema.revision, mode };
          j.state = "done";
          j.gates = resultsPayload(c, "en").gates;
          emit({ type: "job", job: publicJob(j) });
          return;
        }
        emit({ type: "job", job: publicJob(j) });
        j.timer = window.setTimeout(tick, 200);
      };
      job.timer = window.setTimeout(tick, 150);
      return ok({ job_id: id, job: publicJob(job) });
    }
    if (sub === "/results" && method === "GET")
      return c.results ? ok(resultsPayload(c, lang)) : { status: 404, body: { error: "err.no_results", message: "No results yet." } };
    if (sub === "/field" && method === "GET")
      return c.results ? ok(fieldPayload(c, u.searchParams.get("quantity") ?? "", lang)) : { status: 404, body: { error: "err.no_results", message: "No results yet." } };
    return notFound;
  }

  m = path.match(/^\/api\/jobs\/([^/]+)(\/stop)?$/);
  if (m) {
    const j = jobs.get(m[1]);
    if (!j) return notFound;
    if (m[2] && method === "POST" && (j.state === "running" || j.state === "queued")) {
      j.state = "stopped";
      window.clearTimeout(j.timer);
      emit({ type: "job", job: publicJob(j) });
    }
    return ok(publicJob(j));
  }
  return notFound;
}
