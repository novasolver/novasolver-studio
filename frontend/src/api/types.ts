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
  contacts?: Record<string, ContactSettings>;
  /** contact between separate surfaces (no shared nodes): master/slave face keys */
  contact_pairs?: Record<string, { master: string[]; slave: string[]; type: ContactSettings["type"]; mu: number; search: Quantity }>;
  body_props?: Record<string, Record<string, unknown>>;
  body_materials?: Record<string, string>;
  face_groups?: Record<string, string[]>;
  schema_version: string;
  case_id: string;
  revision: number;
  title: Localized;
  template: string;
  engine?: { kind: string; version?: string };
  geometry?: { kind: string; params?: Record<string, Quantity> };
  physics?: { kind: string; joule_heating?: boolean; analysis?: string; modes?: number;
    fatigue?: { enabled?: boolean; ratio?: number; surface?: string; cycles?: number };
    nonlinear?: { large_deformation?: boolean; steps?: 'auto' | number; max_iterations?: number; path?: number[]; face?: string };
    T_ref?: Quantity; thermal_load?: { mode: string; temperature?: Quantity };
    gravity?: { enabled?: boolean; g?: Quantity; direction?: string };
    rotation?: { enabled?: boolean; rpm?: number; axis?: string; axis_point?: number[] } };
  materials?: Record<string, { preset?: string; [k: string]: unknown }>;
  boundaries?: Record<string, { role: string; [k: string]: unknown }>;
  mesh?: { method?: string; size?: string; order?: number };
  run?: { mode?: string; max_wall_s?: number };
  reference?: { kind: string; id: string; quantity: string; tolerance_pct?: number };
  [k: string]: unknown;
}

export interface Check {
  level: "error" | "warn" | 'info';
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
  values?: Record<string, Quantity | string>;
  thermal?: { role: string; [key: string]: { value: number; unit: string } | string } | null;
  area_m2?: number | null;
}

export interface FaceDescriptor {
  centroid?: number[];
  key: string;
  name?: string;
  /** face colour from the CAD file, "#rrggbb" */
  color?: string;
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

export interface UpdateInfo {
  current: string;
  latest?: string;
  available: boolean;
  /** portable: the Windows zip updates itself; mcpb, python, dev: show how to update instead */
  kind: "portable" | "mcpb" | "store" | "python" | "dev" | "other";
  notes?: Partial<Record<Lang, string>>;
  page?: Partial<Record<Lang, string>>;
  pip?: string;
  size?: number;
  auto?: boolean;
  offline?: boolean;
  /** offline mode (NOVASTUDIO_OFFLINE or an "offline" file): Studio never connects */
  offline_mode?: boolean;
  message?: string;
  last_result?: { ok: boolean; from: string; to: string; message: string; at: string } | null;
}

export interface UpdateJob {
  state: "idle" | "downloading" | "ready" | "applying" | "error";
  version?: string;
  bytes?: number;
  total?: number;
  error?: string;
}

/** A solved verification case published on GitHub (strings already in the request language). */
export interface Example {
  name: string;
  template: string;
  physics: string;
  title: string;
  description: string;
  size: number;
  error_pct: number;
  reference: { label: string; value: number; unit: string };
  result: { value: number; unit: string };
  cached: boolean;
}

export interface ExamplesPayload {
  examples: Example[];
  offline: boolean;
  release_page: string;
  /** neither the network nor a cached list: show `message` and the release page */
  unavailable?: boolean;
  message?: string;
}

export interface MeshStats {
  nodes: number;
  elements: number;
  element_type?: string;
  quality_min?: number;
  quality_mean?: number;
}

export interface CaseUi {
  material_models?: Record<string, { model?: string; sy?: Quantity; H?: Quantity }>;
  interfaces?: { key: string; label: string; bodies: string[]; area_m2?: number; contact: ContactSettings }[];
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
  interface?: boolean;
  contact?: ContactSettings;
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
  curve?: { step: number; load_fraction: number; max_disp_m: number; face_disp_m: number[]; iterations: number }[];
  interfaces?: Record<string, { force_n: number[]; normal_force_n: number; pressure_pa: number; status_counts: Record<string,number> }>;
  large_deformation?: boolean;
  modes?: { mode: number; frequency_hz?: number; effective_mass?: number[]; load_factor?: number; critical_load_n?: number }[];
  free_free?: boolean;
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
  step?: number;
  mode?: number;
  section?: SectionPlane;
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

export interface SectionPlane { normal: number[]; position: number }
export interface ContactSettings { type: string; mu: number; offset: Quantity }
export interface ProbeLine { quantities: Record<string,string>; line: { samples: { at_mm: number[]; distance_mm?: number; inside: boolean; values: Record<string,number> }[]; from_mm: number[]; to_mm: number[] } }
export interface ProbePoint { quantities: Record<string,string>; points: { inside: boolean; values: Record<string,number> }[] }

export interface RunResponse {
  job_id: string;
  job?: Job;
}

export type WsMessage =
  | { type: "job"; job: Job }
  | { type: "case"; case_id: string; revision: number };
