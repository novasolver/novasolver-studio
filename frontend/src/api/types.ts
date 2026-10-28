// Shapes returned by the NovaSolver Studio backend (DESIGN.md §3, §6; verified against
// the running backend's /api/openapi.json on 2026-10-25).

export type Lang = "ja" | "en" | "zh";
export type StepId = "geometry" | "mesh" | "physics" | "boundaries" | "run" | "results";
export type StepStatus = "todo" | "warn" | "ok";
export type Localized = string | Partial<Record<Lang, string>>;

export interface EngineInfo {
  id: string;
  available: boolean;
}

/** Analysis family as the backend names it (templates use "cfd", imports use "flow"). */
export type Physics = "structural" | "thermal" | "cfd" | "flow" | "external" | "electric" | "electrostatic" | "current";

export interface Template {
  id: string;
  physics: Physics;
  title: Localized;
  description: Localized;
  has_reference: boolean;
  engines: (EngineInfo | string)[];
  runnable_now?: boolean;
}

export interface Quantity {
  value: number | number[];
  unit: string;
}

export interface CaseSchema {
  face_groups?: Record<string, string[]>;
  schema_version: string;
  case_id: string;
  revision: number;
  title: Localized;
  template: string;
  engine?: { kind: string; version?: string };
  geometry?: { kind: string; params?: Record<string, Quantity> };
  physics?: { kind: string; joule_heating?: boolean };
  materials?: Record<string, { preset?: string; [k: string]: unknown }>;
  boundaries?: Record<string, { role: string; [k: string]: unknown }>;
  mesh?: { method?: string; size?: string; order?: number };
  run?: { mode?: string; max_wall_s?: number };
  reference?: { kind: string; id: string; quantity: string; tolerance_pct?: number };
  [k: string]: unknown;
}

export interface Check {
  level: "error" | "warn";
  code: string;
  message: string;
  step: StepId;
  faces?: string[]; // face keys, e.g. "x0"
  fix?: unknown;
}

export interface UiParam {
  path: string;
  label: string;
  value: number | string;
  unit?: string;
  units?: string[];
  min_si?: number;
  max_si?: number;
}

export interface UiFace {
  descriptor?: FaceDescriptor;
  key: string;
  region?: string | null;
  label: string;
  role: string | null;
  role_label?: string;
  locked?: boolean;
  value?: { value: number; unit: string } | null;
  /** per-field values for the current role, e.g. {force:{value,unit}, direction:"-z"} */
  values?: Record<string, { value: number; unit: string } | string>;
  thermal?: { role: string; [key: string]: { value: number; unit: string } | string } | null;
  area_m2?: number | null;
}

export interface FaceDescriptor {
  key: string;
  name?: string;
  type?: string;
  normal?: number[];
  axis?: number[];
  axis_point?: number[];
  radius?: number;
  area?: number;
  bbox?: number[][];
  neighbors?: string[];
  smooth_neighbors?: string[];
}

export interface Sample {
  id: string;
  physics: Physics;
  title: Localized;
  description: Localized;
  file: string;
}

export interface MeshStats {
  nodes: number;
  elements: number;
  element_type?: string;
  quality_min?: number;
  quality_mean?: number;
}

export interface CaseUi {
  params: UiParam[];
  materials: { id: string; label: string }[];
  material_kind?: "solid" | "fluid";
  roles: { id: string; label: string }[];
  thermal_roles?: { id: string; label: string }[];
  faces: UiFace[];
  mesh?: { size: string; sizes: string[]; state: { exists: boolean; stale: boolean; stats: MeshStats | null } };
  modes?: { id: "preview" | "final"; engine: string | null }[];
  physics?: Physics;
  imported?: boolean;
  /** benchmark templates whose boundary pattern is built by the solver: roles cannot change */
  fixed_roles?: boolean;
  source_file?: string | null;
  role_fields?: Record<string, string[]>;
  field_labels?: Record<string, string>;
  field_units?: Record<string, string[]>;
  directions?: { id: string; label: string }[];
  /** external flow: free-stream direction (edit with PATCH {"flow.direction": "+x"}) */
  flow?: { direction: string; directions: { id: string; label: string }[] };
}

export interface Job {
  job_id: string;
  case_id?: string;
  state: "queued" | "running" | "done" | "failed" | "stopped";
  progress: number;
  eta_s?: number | null;
  message?: string;
  engine?: string;
  mode?: string;
  gates?: { ran: boolean; converged: boolean; verified: boolean };
  first_error?: string | null;
  /** set by this GUI when the job is a mesh convergence study (the backend does not echo it) */
  study?: "convergence";
}

export interface CasePayload {
  history?: { undo: { rev: number; source: string; summary: string; ts: number }[]; redo_count: number };
  undone?: { source: string; paths: string[]; summary: string };
  case: CaseSchema;
  steps: Record<StepId, StepStatus>;
  checks: Check[];
  ready?: boolean;
  engine?: string;
  ui: CaseUi;
  jobs: Job[];
  latest_run?: Job | null;
  diff?: unknown;
}

export interface GeometryFace {
  id: number | string;
  key?: string;
  region?: string;
  label: string;
  role?: string | null;
  positions: number[];
  indices: number[];
}

export interface GeometryPayload {
  faces: GeometryFace[];
  bbox?: [[number, number, number], [number, number, number]];
}

export interface ResultCard {
  key: string;
  label: string;
  value: number;
  unit: string;
}

export interface Verification {
  label: string;
  reference: number;
  computed: number;
  unit: string;
  error_pct: number;
  tolerance_pct: number;
  pass: boolean;
  metric?: string;
  reference_label?: string;
  /** "convergence": the mesh study is the verification (computed = fine mesh, reference = extrapolated, error = GCI) */
  kind?: "reference" | "convergence";
}

export interface ConvergenceLevel {
  size: "coarse" | "normal" | "fine";
  elements: number;
  value: number;
}

export interface ConvergenceStudy {
  quantity: string;
  label: string;
  unit: string;
  levels: ConvergenceLevel[];
  extrapolated: number;
  gci_pct: number;
  observed_order: number;
  monotone: boolean;
  rel_change_pct: number;
  tolerance_pct: number;
  pass: boolean;
}

export interface ResultQuantity {
  id: string;
  label: string;
  unit: string;
  kind: "sequential" | "diverging";
}

export interface ResultsPayload {
  kind?: string;
  run_id?: string;
  engine?: string;
  mode?: string;
  revision?: number;
  stale?: boolean;
  wall_s?: number;
  gates: { ran: boolean; converged: boolean; verified: boolean };
  gates_detail?: { converged?: unknown; verified?: string | null } | null;
  cards: ResultCard[];
  verification?: Verification | null;
  quantities: ResultQuantity[];
  nova_tool?: string | null;
  /** mesh convergence study (coarse / normal / fine), present after POST /convergence */
  convergence?: ConvergenceStudy | null;
  /** physics warnings on the result itself, e.g. code "yield" (linear result does not hold) */
  warnings?: { code: string; message: string }[];
}

export interface FieldPayload {
  quantity?: string;
  positions: number[];
  indices: number[];
  scalars: number[];
  range: [number, number];
  displacement?: number[];
  auto_deform_scale?: number;
  unit: string;
  label: string;
}

export interface RunResponse {
  job_id: string;
  job?: Job;
}

export type WsMessage =
  | { type: "job"; job: Job }
  | { type: "case"; case_id: string; revision: number };
