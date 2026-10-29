// Display-side unit helpers. The backend stores {value, unit}; SI conversion of record is
// done by the backend (units.py). These factors are only used to keep the physical
// quantity unchanged when the user switches the unit in an input.

const FACTORS: Record<string, [dim: string, toSI: number]> = {
  'N-m':['TORQUE',1], 'N-mm':['TORQUE',1e-3], '1/K':['ALPHA',1], 'm/s2':['ACC',1],
  // length
  m: ["L", 1],
  cm: ["L", 1e-2],
  mm: ["L", 1e-3],
  "µm": ["L", 1e-6],
  um: ["L", 1e-6],
  in: ["L", 0.0254],
  ft: ["L", 0.3048],
  // force
  N: ["F", 1],
  kN: ["F", 1e3],
  mN: ["F", 1e-3],
  lbf: ["F", 4.4482216],
  "N/m": ["STIFFNESS", 1],
  "N/mm": ["STIFFNESS", 1000],
  // pressure / stress / modulus
  Pa: ["P", 1],
  kPa: ["P", 1e3],
  MPa: ["P", 1e6],
  GPa: ["P", 1e9],
  bar: ["P", 1e5],
  psi: ["P", 6894.757],
  // density
  "kg/m³": ["D", 1],
  "kg/m3": ["D", 1],
  "g/cm³": ["D", 1e3],
  "g/cm3": ["D", 1e3],
  // velocity
  "m/s": ["V", 1],
  "mm/s": ["V", 1e-3],
  "cm/s": ["V", 1e-2],
  "km/h": ["V", 1 / 3.6],
  // kinematic viscosity
  "m²/s": ["NU", 1],
  "m2/s": ["NU", 1],
  "mm²/s": ["NU", 1e-6],
  "mm2/s": ["NU", 1e-6],
  cSt: ["NU", 1e-6],
  // dynamic viscosity
  "Pa·s": ["MU", 1],
  "mPa·s": ["MU", 1e-3],
  // time
  s: ["T", 1],
  ms: ["T", 1e-3],
  min: ["T", 60],
  // heat flux / heat transfer / conductivity
  "W/m2": ["Q", 1],
  "kW/m2": ["Q", 1e3],
  "W/m2K": ["H", 1],
  "W/mK": ["K", 1],
  W: ["P_W", 1],
  kW: ["P_W", 1e3],
  V: ["VOLT", 1], kV: ["VOLT", 1e3], mV: ["VOLT", 1e-3],
  A: ["AMP", 1], mA: ["AMP", 1e-3],
  "C/m2": ["CHARGE_AREA", 1], "S/m": ["SIGMA", 1],
  F: ["CAP", 1], pF: ["CAP", 1e-12], nF: ["CAP", 1e-9], uF: ["CAP", 1e-6],
  ohm: ["RES", 1], mohm: ["RES", 1e-3],
  // temperature is affine: handled in convert()
};

/** How a backend unit id is shown: "degC" -> "°C", "W/m2" -> "W/m²". */
export function unitLabel(u: string | undefined | null): string {
  if (!u || u === "-") return "";
  const map: Record<string, string> = {
    degC: "°C",
    'N-m':'N·m', 'N-mm':'N·mm', 'm/s2':'m/s²',
    "C/m2": "C/m²", "A/mm2": "A/mm²", "W/cm3": "W/cm³",
    ohm: "Ω", mohm: "mΩ", uF: "µF",
    "W/m2": "W/m²",
    "kW/m2": "kW/m²",
    "W/m2K": "W/(m²·K)",
    "W/mK": "W/(m·K)",
    "kg/m3": "kg/m³",
    "m2/s": "m²/s",
    "mm2/s": "mm²/s",
  };
  return map[u] ?? u;
}

export function convert(value: number, from: string, to: string): number | null {
  if (from === to) return value;
  if ((from === "degC" && to === "K") || (from === "K" && to === "degC")) return from === "degC" ? value + 273.15 : value - 273.15;
  const a = FACTORS[from];
  const b = FACTORS[to];
  if (!a || !b || a[0] !== b[0]) return null;
  return (value * a[1]) / b[1];
}

export function toSI(value: number, unit: string | undefined): number {
  if (!unit) return value;
  const f = FACTORS[unit];
  return f ? value * f[1] : value;
}

/** Parse "5 mm", "5mm", "1e3", "2,5" (comma decimal). Returns unit only if it is one of `units`. */
export function parseWithUnit(text: string, units: string[] = []): { value: number; unit?: string } | null {
  let s = text.trim().replace(/−/g, "-");
  // "1,000" / "12,500.5" are thousands separators; a lone "2,5" is a decimal comma
  s = /^[-+]?\d{1,3}(,\d{3})+(\.\d+)?(\s|$|[a-zA-Zµ])/.test(s) ? s.replace(/,/g, "") : s.replace(/,/g, ".");
  const m = s.match(/^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*)$/);
  if (!m) return null;
  const value = Number(m[1]);
  if (!Number.isFinite(value)) return null;
  const rest = m[2].trim();
  if (!rest) return { value };
  const norm = (u: string) =>
    u.toLowerCase().replace("°c", "degc").replace("℃", "degc").replace(/[()·]/g, "").replace("³", "3").replace(/²/g, "2").replace("μ", "µ");
  const unit = units.find((u) => norm(u) === norm(rest) || norm(unitLabel(u)) === norm(rest));
  return unit ? { value, unit } : null;
}

/** Format a number for display: up to `sig` significant digits, no trailing zeros. */
export function fmt(v: number | null | undefined, sig = 4): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (Number.isInteger(v) && a >= 1000 && a < 1e9) return v.toLocaleString("en-US").replace(/^-/, "−");
  let s: string;
  if (a >= 1e6 || a < 1e-3) s = v.toExponential(Math.max(0, sig - 1)).replace(/\.?0+e/, "e");
  else {
    s = Number(v.toPrecision(sig)).toString();
  }
  return s.replace(/^-/, "−");
}

/** Format with thousands separators (integers such as node counts). */
export function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

export function fmtSignedPct(v: number): string {
  const s = Math.abs(v) < 0.05 ? "0.0" : Math.abs(v).toFixed(1);
  if (s === "0.0") return "±0.0%";
  return `${v < 0 ? "−" : "+"}${s}%`;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "—";
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** GCI as a percentage: one decimal, two below 1 % ("3.0", "0.14"). */
export function fmtGci(p: number): string {
  return Math.abs(p) < 1 ? p.toFixed(2) : p.toFixed(1);
}
