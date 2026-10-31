// HTTP/WS client for the Studio backend. Falls back to a lazily-loaded mock (dev aid)
// only when GET /api/templates fails on startup.

import type {
  CasePayload,
  ExamplesPayload,
  UpdateInfo,
  UpdateJob,
  FieldPayload,
  GeometryPayload,
  Job,
  Lang,
  MeshStats,
  ResultsPayload,
  RunResponse,
  Sample,
  Template,
  WsMessage,
  SectionPlane,
  ProbeLine,
  ProbePoint,
} from "./types";

type MockModule = typeof import("./mock");
let mock: MockModule | null = null;

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

let currentLang: Lang = "ja";
export function setApiLang(l: Lang) {
  currentLang = l;
}
export function isMock() {
  return mock !== null;
}

function withLang(path: string): string {
  return path + (path.includes("?") ? "&" : "?") + "lang=" + currentLang;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const url = withLang(path);
  if (mock) {
    const r = await mock.request(method, url, body);
    if (r.status >= 400) throw new ApiError(r.status, r.body, errorText(r.body));
    return r.body as T;
  }
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, data, errorText(data) ?? `HTTP ${res.status}`);
  return data as T;
}

function errorText(b: unknown): string | undefined {
  if (b && typeof b === "object") {
    const o = b as Record<string, unknown>;
    const v = o.message ?? o.detail ?? o.error;
    if (typeof v === "string") return v;
  }
  return undefined;
}

/** Probe the backend; switch to the mock when it does not answer. */
export async function initApi(): Promise<"backend" | "mock"> {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 2500);
    const res = await fetch(withLang("/api/templates"), { signal: ctl.signal });
    clearTimeout(timer);
    if (res.ok) {
      const j = await res.json();
      if (j && Array.isArray(j.templates)) return "backend";
    }
  } catch {
    /* fall through */
  }
  mock = await import("./mock");
  return "mock";
}

/** PATCH path used to change a face's boundary role. Kept in one place on purpose. */
export function faceRolePath(faceKey: string): string {
  return `boundaries.${faceKey}.role`;
}

/** URL of the server-rendered PNG of a result (export image). */
export function renderUrl(caseId: string, quantity: string): string {
  return withLang(`/api/cases/${encodeURIComponent(caseId)}/render.png?quantity=${encodeURIComponent(quantity)}`);
}

export function exportUrl(caseId: string, format: string): string {
  return withLang(`/api/cases/${encodeURIComponent(caseId)}/export?format=${encodeURIComponent(format)}`);
}

export interface CaseSummary {
  case_id: string;
  title: unknown;
  template?: string;
  revision?: number;
  /** optional extras some backends include */
  gates?: { ran: boolean; converged: boolean; verified: boolean } | null;
  physics?: string;
  source_file?: string;
}

/** Upload a CAD file as the raw request body (no multipart). */
async function importCad(file: File, physics: "structural" | "thermal" | "flow" | "external" | "electrostatic" | "current"): Promise<CasePayload> {
  if (mock) throw new ApiError(501, null, "CAD import needs the Studio backend.");
  const url = withLang(`/api/import?physics=${physics}&filename=${encodeURIComponent(file.name)}`);
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, data, errorText(data) ?? `HTTP ${res.status}`);
  return data as CasePayload;
}

/** Download URL of a case archive (.nscase), with or without its latest result. */
export function archiveUrl(caseId: string, results: boolean): string {
  return withLang(`/api/cases/${encodeURIComponent(caseId)}/archive?results=${results}`);
}

/** Upload a .nscase archive as the raw request body. */
async function importArchive(file: File): Promise<CasePayload> {
  if (mock) throw new ApiError(501, null, "Opening a case file needs the Studio backend.");
  const res = await fetch(withLang("/api/import-case"), { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, data, errorText(data) ?? `HTTP ${res.status}`);
  return data as CasePayload;
}

export const api = {
  update: (force = false, passive = false) =>
    mock ? Promise.resolve<UpdateInfo>({ current: "mock", available: false, kind: "dev" })
      : request<UpdateInfo>("GET", `/api/update?force=${force}&passive=${passive}`),
  updateSettings: (auto: boolean) => request("POST", "/api/update/settings", { auto }),
  updateDownload: () => request<UpdateJob>("POST", "/api/update/download"),
  updateStatus: () => request<UpdateJob>("GET", "/api/update/status"),
  updateApply: () => request<UpdateJob>("POST", "/api/update/apply"),
  examples: () => request<ExamplesPayload>("GET", "/api/examples"),
  openExample: (name: string) => request<CasePayload>("POST", `/api/examples/${encodeURIComponent(name)}`),
  exampleProgress: (name: string) =>
    request<{ bytes: number; total: number; active: boolean }>("GET", `/api/examples/${encodeURIComponent(name)}/progress`),
  importArchive,
  undo: (id: string, expected_revision: number, redo = false) =>
    request<CasePayload>('POST', `/api/cases/${encodeURIComponent(id)}/${redo ? 'redo' : 'undo'}`, { expected_revision }),
  guiState: (body: { case_id: string | null; revision: number; step: string; selected: string[]; hidden: string[] }) =>
    mock ? Promise.resolve() : request('PUT', '/api/gui-state', body),
  env: () => request<Record<string, unknown>>("GET", "/api/env"),
  templates: () => request<{ templates: Template[] }>("GET", "/api/templates"),
  samples: async (): Promise<Sample[]> => {
    if (mock) return [];
    const r = await request<{ samples?: Sample[] }>("GET", "/api/samples");
    return r.samples ?? [];
  },
  createSample: (id: string, physics: string) =>
    request<CasePayload>("POST", `/api/samples/${encodeURIComponent(id)}?physics=${encodeURIComponent(physics)}`),
  importCad,
  cases: async (): Promise<CaseSummary[]> => {
    const r = await request<{ cases?: CaseSummary[] } | CaseSummary[]>("GET", "/api/cases");
    return Array.isArray(r) ? r : (r.cases ?? []);
  },
  createCase: (template: string, params?: Record<string, string>) =>
    request<CasePayload>("POST", "/api/cases", params ? { template, params } : { template }),
  getCase: (id: string) => request<CasePayload>("GET", `/api/cases/${encodeURIComponent(id)}`),
  patchCase: (id: string, expected_revision: number, changes: Record<string, unknown>) =>
    request<CasePayload>("PATCH", `/api/cases/${encodeURIComponent(id)}`, { expected_revision, changes }),
  geometry: (id: string) => request<GeometryPayload>("GET", `/api/cases/${encodeURIComponent(id)}/geometry`),
  mesh: (id: string) => request<{ ok: boolean; stats: MeshStats }>("POST", `/api/cases/${encodeURIComponent(id)}/mesh`, {}),
  run: (id: string, mode: "preview" | "final") => request<RunResponse>("POST", `/api/cases/${encodeURIComponent(id)}/run`, { mode }),
  /** Mesh convergence study: one background job that solves on coarse, normal and fine meshes. */
  convergence: (id: string) => request<RunResponse>("POST", `/api/cases/${encodeURIComponent(id)}/convergence`),
  detectContacts: (id: string, apply: boolean) => request<{ pairs: { name: string; master: string[]; slave: string[]; gap_mm: number }[]; applied: boolean }>(
    "POST", `/api/cases/${encodeURIComponent(id)}/detect-contacts`, { apply }),
  job: (jobId: string) => request<Job>("GET", `/api/jobs/${encodeURIComponent(jobId)}`),
  stopJob: (jobId: string) => request<Job>("POST", `/api/jobs/${encodeURIComponent(jobId)}/stop`),
  results: (id: string) => request<ResultsPayload>("GET", `/api/cases/${encodeURIComponent(id)}/results`),
  field: (id: string, quantity: string, mode = 1, section: SectionPlane | null = null,step: number | null = null) =>
    request<FieldPayload>("GET", `/api/cases/${encodeURIComponent(id)}/field?quantity=${encodeURIComponent(quantity)}&mode=${mode}${step == null ? '':'&step='+step}${section ? '&section='+encodeURIComponent(JSON.stringify(section)) : ''}`),
  probe: (id: string, line: { from: number[]; to: number[]; n: number }, mode = 1, run_id?: string,step?: number | null) =>
    request<ProbeLine>('POST', `/api/cases/${encodeURIComponent(id)}/probe`, { line, mode, run_id,step }),
  probePoint: (id: string, at: number[], mode = 1, run_id?: string,step?: number | null) =>
    request<ProbePoint>('POST', `/api/cases/${encodeURIComponent(id)}/probe`, { points: [at], mode, run_id,step }),
};

/** Subscribe to server push (WS /ws). Reconnects with backoff. Returns an unsubscribe. */
export function connectEvents(onMessage: (m: WsMessage) => void, onState?: (connected: boolean) => void): () => void {
  if (mock) {
    onState?.(true);
    return mock.subscribe(onMessage);
  }
  let ws: WebSocket | null = null;
  let closed = false;
  let retry = 500;
  let timer = 0;
  const open = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onopen = () => {
      retry = 500;
      onState?.(true);
    };
    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(String(ev.data));
        if (m && (m.type === "job" || m.type === "case")) onMessage(m as WsMessage);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      onState?.(false);
      if (closed) return;
      timer = window.setTimeout(open, retry);
      retry = Math.min(retry * 2, 10_000);
    };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => {
    closed = true;
    window.clearTimeout(timer);
    ws?.close();
  };
}
