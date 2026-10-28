// App state: a tiny external store (useSyncExternalStore) + async actions.
import { useCallback, useSyncExternalStore } from "react";
import { api, ApiError, connectEvents, faceRolePath, initApi, isMock, setApiLang, type CaseSummary } from "../api/client";
import type {
  CasePayload,
  FieldPayload,
  GeometryPayload,
  Job,
  Lang,
  ResultsPayload,
  Sample,
  StepId,
  Template,
  UiFace,
  WsMessage,
  SectionPlane,
} from "../api/types";
import { detectLang, pick, translate } from "../i18n";
import type { ColormapName, Viewer, ViewName } from "../viewer";

/** Stable empty array for selectors (a fresh [] would re-render forever). */
export const EMPTY: never[] = [];

export const STEPS: StepId[] = ["geometry", "mesh", "physics", "boundaries", "run", "results"];

export interface LogEntry {
  id: number;
  t: number;
  level: "info" | "ok" | "warn" | "error";
  text: string;
}

export interface Toast {
  action?: 'undo' | 'redo';
  id: number;
  text: string;
  kind: "ai" | "info" | "error";
}

export interface State {
  boot: "loading" | "ready";
  mode: "backend" | "mock";
  wsConnected: boolean;
  lang: Lang;
  theme: "light" | "dark";
  themeExplicit: boolean;
  templates: Template[];
  samples: Sample[];
  recent: CaseSummary[];
  importing: string | null; // file being imported
  payload: CasePayload | null;
  geometry: GeometryPayload | null;
  step: StepId;
  selectedFaces: string[]; // face keys, e.g. ["x1"] (multi-select with Shift/Ctrl)
  hiddenFaces: string[];
  seeThrough: boolean;
  faceFilter: string[] | null;
  historyBusy: boolean;
  resultsBeforeUndo: boolean;
  hoverFace: string | null; // face under the pointer (3D view or list)
  flashFaces: string[];
  fieldErrors: Record<string, string>; // PATCH path -> localized message (400)
  results: ResultsPayload | null;
  resultsLoading: boolean;
  field: FieldPayload | null;
  quantity: string | null;
  colormap: ColormapName;
  range: [number, number] | null; // user override; null = auto
  deformScale: number | null; // null = auto
  selectedMode: number;
  modeAnimation: boolean;
  section: SectionPlane | null;
  probeValue: { at: number[]; value: number; unit: string } | null;
  job: Job | null;
  stopping: boolean;
  saving: boolean;
  creating: string | null;
  meshBusy: boolean;
  runBusy: boolean;
  palette: boolean;
  ai: boolean;
  logOpen: boolean;
  logs: LogEntry[];
  toast: Toast | null;
  brandMark: boolean; // small "NovaSolver Studio" mark in the viewport corner (shows in screenshots)
  shareProgress: number | null; // turntable export 0..1 while running
}

function initialTheme(): { theme: "light" | "dark"; explicit: boolean } {
  try {
    const t = localStorage.getItem("nss.theme");
    if (t === "light" || t === "dark") return { theme: t, explicit: true };
  } catch {
    /* ignore */
  }
  return { theme: window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light", explicit: false };
}

const th = initialTheme();
let state: State = {
  boot: "loading",
  mode: "backend",
  wsConnected: false,
  lang: detectLang(),
  theme: th.theme,
  themeExplicit: th.explicit,
  templates: [],
  samples: [],
  recent: [],
  importing: null,
  payload: null,
  geometry: null,
  step: "geometry",
  selectedFaces: [],
  hiddenFaces: [],
  seeThrough: false,
  faceFilter: null,
  historyBusy: false,
  resultsBeforeUndo: false,
  hoverFace: null,
  flashFaces: [],
  fieldErrors: {},
  results: null,
  resultsLoading: false,
  field: null,
  quantity: null,
  colormap: "viridis",
  range: null,
  deformScale: null,
  selectedMode: 1, modeAnimation: false, section: null, probeValue: null,
  job: null,
  stopping: false,
  saving: false,
  creating: null,
  meshBusy: false,
  runBusy: false,
  palette: false,
  ai: false,
  logOpen: false,
  logs: [],
  toast: null,
  brandMark: initialBrandMark(),
  shareProgress: null,
};

function initialBrandMark(): boolean {
  try {
    return localStorage.getItem("nss.brandMark") !== "off";
  } catch {
    return true;
  }
}
export function toggleBrandMark() {
  const brandMark = !state.brandMark;
  setState({ brandMark });
  try {
    localStorage.setItem("nss.brandMark", brandMark ? "on" : "off");
  } catch {
    /* ignore */
  }
}

const subs = new Set<() => void>();
let fieldProbeGeneration = 0;
export function getState() {
  return state;
}
export function setState(p: Partial<State> | ((s: State) => Partial<State>)) {
  const patch = typeof p === "function" ? p(state) : p;
  if (('selectedMode' in patch && patch.selectedMode !== state.selectedMode) ||
      ('payload' in patch && patch.payload?.case.case_id !== state.payload?.case.case_id) ||
      ('results' in patch && patch.results?.run_id !== state.results?.run_id) ||
      ('field' in patch && patch.field !== state.field) || ('section' in patch && patch.section !== state.section)) fieldProbeGeneration++;
  state = { ...state, ...patch };
  subs.forEach((f) => f());
  scheduleGuiState();
}

let guiTimer = 0;
let guiSignature = '';   // latest state to publish
let guiSent = '';        // last state the server acknowledged
let guiInFlight = false;
let guiRetry = 0;
function scheduleGuiState() {
  const body = { case_id: state.payload?.case.case_id ?? null, revision: state.payload?.case.revision ?? 0,
    step: state.step, selected: state.selectedFaces, hidden: state.hiddenFaces };
  const signature = JSON.stringify(body);
  if (signature === guiSignature) return;
  guiSignature = signature;
  guiRetry = 0;
  window.clearTimeout(guiTimer);
  guiTimer = window.setTimeout(() => void sendGuiState(), 300);
}
async function sendGuiState() {
  if (guiInFlight || guiSent === guiSignature || state.mode === 'mock') return;
  guiInFlight = true;
  const signature = guiSignature;
  let failed = false;
  try { await api.guiState(JSON.parse(signature)); guiSent = signature; }
  catch { failed = true; }
  finally {
    guiInFlight = false;
    if (signature !== guiSignature) void sendGuiState();
    // a failed send must not leave the AI reading an older selection: retry the latest state with backoff
    // (0.6 s, 1.2 s ... capped at 10 s) until the server takes it or the state changes again
    else if (failed) {
      window.clearTimeout(guiTimer);
      guiTimer = window.setTimeout(() => void sendGuiState(), Math.min(10000, 600 * 2 ** guiRetry++));
    }
  }
}
function subscribe(f: () => void) {
  subs.add(f);
  return () => subs.delete(f);
}
export function useStore<T>(sel: (s: State) => T): T {
  return useSyncExternalStore(subscribe, () => sel(state));
}

export function t(key: string, vars?: Record<string, string | number>) {
  return translate(state.lang, key, vars);
}
/** Hook that re-renders on language change and returns a stable translator. */
export function useT() {
  const lang = useStore((s) => s.lang);
  return useCallback((key: string, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);
}

// ------------------------------------------------------------------ viewer handle
let viewer: Viewer | null = null;
export function registerViewer(v: Viewer | null) {
  viewer = v;
}
export function getViewer(): Viewer | null {
  return viewer;
}
export function viewCmd(name: ViewName) {
  viewer?.view(name);
}
/** Bring the largest value of the shown result into view (the place that decides failure). */
export function focusPeak() {
  viewer?.focusPeak();
}

// ------------------------------------------------------------------ log / toast
let seq = 0;
export function log(level: LogEntry["level"], text: string) {
  setState((s) => ({ logs: [...s.logs.slice(-199), { id: ++seq, t: Date.now(), level, text }] }));
}
let toastTimer = 0;
export function toast(text: string, kind: Toast["kind"] = "info", action?: 'undo' | 'redo') {
  window.clearTimeout(toastTimer);
  setState({ toast: { id: ++seq, text, kind, action } });
  toastTimer = window.setTimeout(() => setState({ toast: null }), 4200);
}
function errMsg(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  // keep the human part; drop Python tracebacks the server may append
  const first = raw.split(/\r?\n|\s+File "/)[0].trim().replace(/[:：]\s*$/, "");
  return first.length > 200 ? first.slice(0, 199) + "…" : first || raw.slice(0, 200);
}

// ------------------------------------------------------------------ boot
let unsubscribeEvents: (() => void) | null = null;

export async function boot() {
  applyTheme();
  applyLangAttr();
  setApiLang(state.lang);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!state.themeExplicit) {
      setState({ theme: e.matches ? "dark" : "light" });
      applyTheme();
    }
  });
  const mode = await initApi();
  setState({ mode });
  try {
    const [{ templates }, recent, samples] = await Promise.all([
      api.templates(),
      api.cases().catch(() => []),
      api.samples().catch(() => [] as Sample[]),
    ]);
    setState({ templates, recent, samples });
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
  }
  unsubscribeEvents?.();
  unsubscribeEvents = connectEvents(onEvent, (c) => setState({ wsConnected: c }));
  setState({ boot: "ready" });
  void openFromLink();
}

/** Revisions produced by this GUI's own PATCHes; a WS "case" event for them is not external. */
const ownRevisions = new Set<number>();

function onEvent(m: WsMessage) {
  if (m.type === "job") {
    if (m.job.case_id && m.job.case_id !== state.payload?.case.case_id) return;
    const cur = state.job;
    if (!cur || cur.job_id === m.job.job_id || isActive(m.job)) {
      // WS messages are English; keep the localized text obtained by polling instead.
      const j = { ...m.job };
      if (state.lang !== "en" && cur?.job_id === j.job_id) j.message = cur.message;
      updateJob(j);
    }
  } else if (m.type === "case") {
    const p = state.payload;
    if (!p || m.case_id !== p.case.case_id) return;
    if (m.revision <= p.case.revision || ownRevisions.has(m.revision) || state.saving || pendingFlush || state.historyBusy) return;
    log("info", t("log.external", { rev: m.revision }));
    toast(t("toast.external", { rev: m.revision }), "ai");
    void refreshCase(true);
  }
}

// ------------------------------------------------------------------ theme / lang
function applyTheme() {
  document.documentElement.classList.toggle("dark", state.theme === "dark");
  document.documentElement.style.colorScheme = state.theme;
}
export function toggleTheme() {
  const theme = state.theme === "dark" ? "light" : "dark";
  setState({ theme, themeExplicit: true });
  try {
    localStorage.setItem("nss.theme", theme);
  } catch {
    /* ignore */
  }
  applyTheme();
}
function applyLangAttr() {
  document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : state.lang;
}
export async function setLang(lang: Lang) {
  if (lang === state.lang) return;
  setState({ lang });
  setApiLang(lang);
  applyLangAttr();
  try {
    localStorage.setItem("nss.lang", lang);
  } catch {
    /* ignore */
  }
  // backend-localized text (labels, check messages) must be refetched
  api
    .templates()
    .then(({ templates }) => setState({ templates }))
    .catch(() => {});
  api
    .samples()
    .then((samples) => setState({ samples }))
    .catch(() => {});
  if (state.payload) {
    await refreshCase(false);
    void loadGeometry();
    if (state.results) void loadResults(false, true);
  }
}

// ------------------------------------------------------------------ case lifecycle
export async function refreshRecent() {
  try {
    setState({ recent: await api.cases() });
  } catch {
    /* ignore */
  }
}

export function closeCase() {
  setState({
    payload: null,
    geometry: null,
    results: null,
    field: null,
    selectedFaces: [],
    hiddenFaces: [], seeThrough: false, faceFilter: null, resultsBeforeUndo: false,
    hoverFace: null,
    flashFaces: [],
    fieldErrors: {},
    step: "geometry",
    job: null,
  });
  void refreshRecent();
}

export async function createCase(template: string) {
  if (state.creating) return;
  setState({ creating: template });
  try {
    const p = await api.createCase(template);
    openPayload(p);
    log("ok", t("log.caseCreated", { title: pick(state.lang, p.case.title) }));
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  } finally {
    setState({ creating: null });
  }
}

/**
 * "Solve this in 3D" links from novasolver.jp open http://127.0.0.1:<port>/?template=<id>&set.<path>=<value>…
 * Only a template id and a few value overrides under known sections are read; the case is created, never run.
 */
const LINK_PREFIXES = ["geometry.params.", "materials.", "boundaries.", "physics."];
async function openFromLink() {
  const q = new URLSearchParams(location.search);
  const caseId = q.get("case");
  if (caseId && /^c_\d{8}_\d{6}_[0-9a-f]{4}$/.test(caseId)) {
    history.replaceState(null, "", location.pathname);
    await openCase(caseId);                 // a saved case with its results (recordings, tutorials)
    return;
  }
  const template = q.get("template");
  if (!template) return;
  history.replaceState(null, "", location.pathname);
  if (!state.templates.some((x) => x.id === template)) {
    toast(t("open.failed", { message: template }), "error");
    return;
  }
  const params: Record<string, string> = {};
  for (const [k, v] of q) {
    if (!k.startsWith("set.")) continue;
    const path = k.slice(4);
    if (Object.keys(params).length >= 24 || v.length > 64 || !/^[\w.-]+$/.test(path)) continue;
    if (LINK_PREFIXES.some((p) => path.startsWith(p))) params[path] = v;
  }
  setState({ creating: template });
  try {
    const p = await api.createCase(template, Object.keys(params).length ? params : undefined);
    openPayload(p);
    log("ok", t("log.caseCreated", { title: pick(state.lang, p.case.title) }));
    toast(t("open.created"));
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
    toast(t("open.failed", { message: errMsg(e) }), "error");
  } finally {
    setState({ creating: null });
  }
}

/** Open one of the bundled sample CAD models (the backend copies it into a new case). */
export async function createSample(id: string, physics: string) {
  if (state.creating || state.importing) return;
  setState({ creating: `sample:${id}` });
  try {
    const p = await api.createSample(id, physics);
    openPayload(p);
    log("ok", t("log.caseCreated", { title: caseTitle(p) }));
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  } finally {
    setState({ creating: null });
  }
}

export const CAD_EXTENSIONS = [".step", ".stp", ".iges", ".igs", ".brep", ".stl"];

/** Import a CAD file (raw body upload) as a new case. */
export async function importFile(file: File, physics: "structural" | "thermal" | "flow" | "external" | "electrostatic" | "current") {
  if (state.importing) return;
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!CAD_EXTENSIONS.includes(ext)) {
    toast(t("import.badType", { ext: CAD_EXTENSIONS.join(" ") }), "error");
    return;
  }
  setState({ importing: file.name });
  log("info", t("import.started", { name: file.name }));
  try {
    const p = await api.importCad(file, physics);
    openPayload(p);
    log("ok", t("import.done", { name: file.name, n: p.ui.faces.length }));
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  } finally {
    setState({ importing: null });
  }
}

/** Display title; imported cases fall back to the file name. */
export function caseTitle(p: CasePayload | null): string {
  if (!p) return "";
  const s = pick(state.lang, p.case.title);
  if (s && !s.startsWith("template.")) return s;
  return p.ui.source_file || (p.case.geometry as { name?: string } | undefined)?.name || p.case.case_id;
}

export async function openCase(id: string) {
  try {
    openPayload(await api.getCase(id));
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
  }
}

function openPayload(p: CasePayload) {
  const running = p.jobs?.find(isActive) ?? null;
  ownRevisions.clear();
  setState({
    payload: p,
    geometry: null,
    step: "geometry",
    selectedFaces: [],
    hiddenFaces: [], seeThrough: false, faceFilter: null, resultsBeforeUndo: false,
    hoverFace: null,
    flashFaces: [],
    fieldErrors: {},
    results: null,
    field: null,
    quantity: null,
    selectedMode: 1, modeAnimation: false, section: null, probeValue: null,
    range: null,
    deformScale: null,
    job: running,
  });
  if (running) startPolling(running.job_id);
  void loadGeometry();
  void refreshRecent();
  if (p.steps.run !== "todo" || p.latest_run) void loadResults(false);
}

async function refreshCase(reloadGeometry: boolean) {
  const p = state.payload;
  if (!p) return;
  try {
    const np = await api.getCase(p.case.case_id);
    if (state.payload?.case.case_id !== np.case.case_id) return;
    setState({ payload: np });
    if (reloadGeometry) void loadGeometry();
    if (state.results || state.step === "results") void loadResults(false);
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
  }
}

export async function loadGeometry() {
  const p = state.payload;
  if (!p) return;
  try {
    const g = await api.geometry(p.case.case_id);
    if (state.payload?.case.case_id === p.case.case_id) setState({ geometry: g });
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
  }
}

// ------------------------------------------------------------------ steps / selection
export function canOpenStep(step: StepId): boolean {
  const p = state.payload;
  if (!p) return false;
  return step !== "results" || !!state.results || p.steps.run !== "todo";
}
export function goStep(step: StepId) {
  if (!canOpenStep(step)) return;
  setState({ step, flashFaces: step === state.step ? state.flashFaces : [] });
  if (step === "results" && !state.results) void loadResults(false);
}
/** Select a face. mode "toggle" adds/removes (Shift/Ctrl-click), "set" replaces. */
export function selectFace(key: string | null, mode: "set" | "toggle" = "set") {
  if (key == null) {
    setState({ selectedFaces: [] });
    return;
  }
  if (mode === "toggle") {
    const cur = state.selectedFaces;
    setState({ selectedFaces: cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key] });
  } else setState({ selectedFaces: [key] });
}
export function selectFaces(keys: string[]) {
  setState({ selectedFaces: [...new Set(keys)] });
}

const COS2 = Math.cos(2 * Math.PI / 180);
const dot = (a: number[], b: number[]) => a.reduce((s, v, i) => s + v * b[i], 0);
let coaxialLast: string[] | null = null;
let coaxialSeeds: string[] = [];
export function selectConnected() {
  const faces = state.payload?.ui.faces ?? [];
  const valid = new Set(faces.filter(f => !f.locked).map(f => f.key));
  const found = new Set(state.selectedFaces);
  const queue = [...found];
  while (queue.length) {
    const key = queue.shift();
    const f = faces.find(f => f.key === key);
    for (const k of f?.descriptor?.smooth_neighbors ?? []) if (valid.has(k) && !found.has(k)) { found.add(k); queue.push(k); }
  }
  selectFaces([...found]);
}
export function selectSameDirection() {
  const faces = state.payload?.ui.faces ?? [];
  // planes only: a curved face has no single direction (cases saved before 0.4 may still carry one)
  const planar = (f: UiFace) => !!f.descriptor?.normal && (!f.descriptor.type || f.descriptor.type === 'Plane');
  const normals = faces.filter(f => state.selectedFaces.includes(f.key) && planar(f)).map(f => f.descriptor!.normal!);
  selectFaces(faces.filter(f => !f.locked && planar(f) && normals.some(n => dot(n, f.descriptor!.normal!) >= COS2)).map(f => f.key));
}
/** Faces painted the same colour in the CAD file (designers mark seats and sealing faces that way). */
export function selectSameColor() {
  const faces = state.payload?.ui.faces ?? [];
  const cols = new Set(faces.filter(f => state.selectedFaces.includes(f.key)).flatMap(f => f.descriptor?.color ? [f.descriptor.color] : []));
  selectFaces(faces.filter(f => !f.locked && f.descriptor?.color && cols.has(f.descriptor.color)).map(f => f.key));
}
export function selectCoaxial() {
  const faces = state.payload?.ui.faces ?? [];
  const sameRadius = coaxialLast === state.selectedFaces;
  if (!sameRadius) coaxialSeeds = [...state.selectedFaces];
  const seeds = faces.filter(f => coaxialSeeds.includes(f.key)).map(f => f.descriptor).filter(d => d?.axis && d.axis_point && d.radius);
  const bbox = state.geometry?.bbox;
  const tolerance = bbox ? Math.hypot(...bbox[0].map((v, i) => bbox[1][i] - v)) * .01 : 0;
  selectFaces(faces.filter(f => {
    const d = f.descriptor;
    return !f.locked && d?.axis && d.axis_point && d.radius && seeds.some(s => {
      if (Math.abs(dot(s!.axis!, d.axis!)) < COS2) return false;
      const v = d.axis_point!.map((x, i) => x - s!.axis_point![i]);
      const along = dot(v, s!.axis!);
      return Math.hypot(...v.map((x, i) => x - along * s!.axis![i])) <= tolerance &&
        (!sameRadius || Math.abs(d.radius! - s!.radius!) <= s!.radius! * .01);
    });
  }).map(f => f.key));
  coaxialLast = sameRadius ? null : state.selectedFaces;
}
export function selectSimilar() {
  const faces = state.payload?.ui.faces ?? [];
  const seeds = faces.filter(f => state.selectedFaces.includes(f.key));
  selectFaces(faces.filter(f => !f.locked && seeds.some(s => {
    const sameType = s.descriptor?.type && f.descriptor?.type ? s.descriptor.type === f.descriptor.type :
      s.label.split('·')[1]?.trim() === f.label.split('·')[1]?.trim();
    return sameType && s.area_m2 && f.area_m2 && Math.abs(f.area_m2 - s.area_m2) <= s.area_m2 * .02;
  })).map(f => f.key));
}
export function invertSelection() {
  selectFaces((state.payload?.ui.faces ?? []).filter(f => !f.locked && !state.selectedFaces.includes(f.key) &&
    (!state.faceFilter || state.faceFilter.includes(f.key))).map(f => f.key));
}
export function hideSelected() {
  setState({ hiddenFaces: [...new Set([...state.hiddenFaces, ...state.selectedFaces])], selectedFaces: [] });
}
export function showAllFaces() { setState({ hiddenFaces: [] }); }
export function toggleSeeThrough() { setState({ seeThrough: !state.seeThrough }); }
export function selectBox(x0: number, y0: number, x1: number, y1: number, add = false) {
  viewer?.selectBox(x0, y0, x1, y1, add);
}
export function deleteFaceGroup(name: string) { change(`face_groups.${name}`, null); }
export function renameFaceGroup(name: string, next: string) {
  const keys = state.payload?.case.face_groups?.[name];
  if (!keys || !next.trim() || next.trim() === name) return;
  deleteFaceGroup(name);
  change(`face_groups.${next.trim()}`, keys);
}
export function saveFaceGroup(name?: string) {
  const p = state.payload;
  if (!p || !state.selectedFaces.length) return;
  const cadName = p.ui.faces.find(f => state.selectedFaces.includes(f.key) && f.descriptor?.name)?.descriptor?.name;
  const groups = p.case.face_groups ?? {};
  let n = 1;
  while (groups[t('bc.groupDefault', { n })]) n++;
  const value = name ?? window.prompt(t('bc.groupName'), cadName ?? t('bc.groupDefault', { n }));
  if (value?.trim()) change(`face_groups.${value.trim()}`, [...state.selectedFaces]);
}
export function setHoverFace(key: string | null) {
  if (state.hoverFace !== key) setState({ hoverFace: key });
}
export function focusCheck(stepId: StepId, faces?: (string | number)[]) {
  goStep(stepId);
  const ids = (faces ?? []).map(String);
  setState({ flashFaces: ids, selectedFaces: ids.length === 1 ? [ids[0]] : state.selectedFaces });
  if (ids.length) viewer?.view("fit");
}

// ------------------------------------------------------------------ PATCH (debounced, no Apply button)
let pending: Record<string, unknown> = {};
/** the case the queued edits belong to: a case switch inside the debounce must not send them to the next case */
let pendingCase: string | null = null;
let pendingFlush = false;
let flushTimer = 0;
let inFlight: Promise<void> | null = null;
/** edits taken off `pending` with their case, sent one batch at a time in order */
const batches: { caseId: string; changes: Record<string, unknown> }[] = [];

function applyOptimistic(p: CasePayload, path: string, value: unknown): CasePayload {
  const np: CasePayload = { ...p, case: { ...p.case }, ui: { ...p.ui } };
  const fm = path.match(/^boundaries\.([^.]+)\.role$/);
  if (fm) {
    const label = p.ui.roles.find((r) => r.id === value)?.label;
    np.ui.faces = p.ui.faces.map((f) => (f.key === fm[1] ? { ...f, role: (value as string) || null, role_label: label } : f));
    return np;
  }
  const ft = path.match(/^boundaries\.([^.]+)\.thermal\.([^.]+)$/);
  if (ft) {
    np.ui.faces = p.ui.faces.map((f) => f.key === ft[1] ? { ...f, thermal: { role: "insulated", ...f.thermal, [ft[2]]: value as { value: number; unit: string } | string } } : f);
    return np;
  }
  if (path === "physics.joule_heating") np.case.physics = { kind: p.case.physics?.kind ?? "dc-current", ...p.case.physics, joule_heating: Boolean(value) };
  if (path.startsWith('physics.')) {
    const physics = structuredClone(np.case.physics ?? { kind: 'linear-static' });
    const parts = path.split('.').slice(1);
    let parent = physics as Record<string, unknown>;
    for (const key of parts.slice(0,-1)) {
      if (!parent[key] || typeof parent[key] !== 'object') parent[key] = {};
      parent = parent[key] as Record<string,unknown>;
    }
    parent[parts.at(-1)!] = value;
    np.case.physics = physics;
  }
  const fv = path.match(/^boundaries\.([^.]+)\.([^.]+)$/);
  if (fv && p.ui.faces.some((f) => f.key === fv[1])) {
    np.ui.faces = p.ui.faces.map((f) =>
      f.key === fv[1] ? { ...f, values: { ...(f.values ?? {}), [fv[2]]: value as { value: number; unit: string } | string } } : f,
    );
  }
  if (path === "mesh.size") {
    np.case.mesh = { ...(p.case.mesh ?? {}), size: String(value) };
    if (p.ui.mesh) np.ui.mesh = { ...p.ui.mesh, size: String(value) };
  } else if (path === "run.mode") np.case.run = { ...(p.case.run ?? {}), mode: String(value) };
  else if (path === "flow.direction" && p.ui.flow) np.ui.flow = { ...p.ui.flow, direction: String(value) };
  else if (path.startsWith("materials.") && path.endsWith(".preset")) {
    const kind = path.split(".")[1];
    const mats = { ...(p.case.materials ?? {}) };
    mats[kind] = { ...(mats[kind] ?? {}), preset: String(value) };
    np.case.materials = mats;
  }
  np.ui.params = p.ui.params.map((q) => {
    if (q.path !== path) return q;
    if (value && typeof value === "object" && "value" in (value as object)) {
      const v = value as { value: number; unit?: string };
      return { ...q, value: v.value, unit: v.unit ?? q.unit };
    }
    return { ...q, value: value as number };
  });
  return np;
}

export function change(path: string, value: unknown) {
  const p = state.payload;
  if (!p) return;
  if (pendingCase && pendingCase !== p.case.case_id) void flush(); // edits of the previous case go out first
  pending[path] = value;
  pendingCase = p.case.case_id;
  pendingFlush = true;
  const fe = { ...state.fieldErrors };
  delete fe[path];
  setState({ payload: applyOptimistic(p, path, value), saving: true, fieldErrors: fe });
  window.clearTimeout(flushTimer);
  flushTimer = window.setTimeout(() => void flush(), 300);
}

export function setFaceRole(faceKey: string, role: string) {
  change(faceRolePath(faceKey), role);
}

async function flush(): Promise<void> {
  // take the queued edits off with their case right now: awaiting first would let the next case's edits join them
  if (pendingCase && Object.keys(pending).length) batches.push({ caseId: pendingCase, changes: pending });
  pending = {};
  pendingCase = null;
  if (!inFlight) {
    inFlight = (async () => {
      while (batches.length) await send(batches.shift()!);
    })().finally(() => {
      inFlight = null;
    });
  }
  await inFlight;
  if (batches.length) return flush();        // queued after the loop had already finished
  if (Object.keys(pending).length) {
    window.clearTimeout(flushTimer);
    flushTimer = window.setTimeout(() => void flush(), 50);
  } else {
    pendingFlush = false;
    setState({ saving: false });
  }
}

/** One batch: never throws, so a failed batch cannot block the ones after it (or later edits). */
async function send({ caseId, changes }: { caseId: string; changes: Record<string, unknown> }): Promise<void> {
  if (historyBarrier) await historyBarrier;
  try {
    // the revision of the case the edits were made in, also when another case is open by now
    let rev = state.payload?.case.case_id === caseId ? state.payload.case.revision : (await api.getCase(caseId)).case.revision;
    let np: CasePayload;
    try {
      np = await api.patchCase(caseId, rev, changes);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        log("warn", t("log.conflict"));
        const b = e.body as { current_revision?: number; current?: number } | null;
        rev = b?.current_revision ?? b?.current ?? (await api.getCase(caseId)).case.revision;
        np = await api.patchCase(caseId, rev, changes);
      } else throw e;
    }
    ownRevisions.add(np.case.revision);
    if (state.payload?.case.case_id !== caseId) return;
    // keep optimistic values for changes queued while this request was in flight
    let merged = np;
    if (pendingCase === caseId) for (const [k, v] of Object.entries(pending)) merged = applyOptimistic(merged, k, v);
    setState({ payload: merged });
    log("info", t("log.saved", { rev: np.case.revision }));
    if (Object.keys(changes).some((k) => k.startsWith("geometry.") || k === "mesh.size" || k.endsWith(".role")))
      void loadGeometry();
    if (state.results) void loadResults(false);
  } catch (e) {
    const here = state.payload?.case.case_id === caseId;
    if (e instanceof ApiError && e.status === 400) {
      // validation error: show the (already localized) message next to the field
      if (here) {
        const fe = { ...state.fieldErrors };
        for (const k of Object.keys(changes)) fe[k] = e.message;
        setState({ fieldErrors: fe });
      }
      log("warn", `${Object.keys(changes).join(", ")}: ${e.message}`);
    } else log("error", t("log.error", { message: errMsg(e) }));
    if (here) await refreshCase(false).catch(() => undefined);
  }
}

async function settle() {
  do {
    window.clearTimeout(flushTimer);
    if (pendingFlush || batches.length || Object.keys(pending).length) await flush();
    if (inFlight) await inFlight;
  } while (inFlight || batches.length || Object.keys(pending).length);
}

let historyBarrier: Promise<void> | null = null;
export async function undoCase(redo = false) {
  if (!state.payload || state.historyBusy) return;
  setState({ historyBusy: true });
  let release: (() => void) | undefined;
  try {
    const id = state.payload.case.case_id;
    await settle();
    if (state.payload?.case.case_id !== id) return;
    historyBarrier = new Promise<void>(resolve => { release = resolve; });
    const p = await api.undo(id, state.payload.case.revision, redo);
    ownRevisions.add(p.case.revision);
    if (state.payload?.case.case_id !== id) return;
    let merged = p;
    if (pendingCase === id) for (const [path, value] of Object.entries(pending)) merged = applyOptimistic(merged, path, value);
    setState({ payload: merged, resultsBeforeUndo: true });
    void loadGeometry();
    if (state.results) void loadResults(false);
    toast(t(redo ? 'redo.done' : p.undone?.source === 'ai' ? 'undo.ai' : 'undo.done', { summary: p.undone?.summary ?? '' }),
      p.undone?.source === 'ai' ? 'ai' : 'info', redo ? 'undo' : 'redo');
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) await refreshCase(true);
    toast(errMsg(e), 'error');
  } finally {
    historyBarrier = null;
    release?.();
    setState({ historyBusy: false });
  }
}
export function redoCase() { return undoCase(true); }

// ------------------------------------------------------------------ mesh
export async function generateMesh() {
  const p = state.payload;
  if (!p || state.meshBusy) return;
  setState({ meshBusy: true });
  try {
    await settle();
    const r = await api.mesh(p.case.case_id);
    log("ok", t("mesh.done", { nodes: r.stats.nodes.toLocaleString(), elements: r.stats.elements.toLocaleString() }));
    await refreshCase(true); // surface becomes the mesh surface
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  } finally {
    setState({ meshBusy: false });
  }
}

// ------------------------------------------------------------------ jobs
export function isActive(j: Job | null | undefined): boolean {
  return !!j && (j.state === "running" || j.state === "queued");
}

let pollTimer = 0;
function startPolling(jobId: string) {
  window.clearTimeout(pollTimer);
  const tick = async () => {
    if (!isActive(state.job) || state.job?.job_id !== jobId) return;
    try {
      updateJob(await api.job(jobId)); // localized message
    } catch {
      /* transient */
    }
    if (isActive(state.job) && state.job?.job_id === jobId) pollTimer = window.setTimeout(tick, state.wsConnected ? 1500 : 700);
  };
  pollTimer = window.setTimeout(tick, 500);
}

function updateJob(j: Job) {
  // stopped by the user (e.g. while queued) but reported as a failure: not an error
  if (j.state === "failed" && stopRequested.has(j.job_id)) j = { ...j, state: "stopped", first_error: null };
  const prev = state.job;
  const wasActive = isActive(prev) && prev?.job_id === j.job_id;
  setState({ job: { ...(prev?.job_id === j.job_id ? prev : {}), ...j } });
  if (!wasActive && isActive(j)) startPolling(j.job_id);
  if (wasActive && !isActive(j)) void onJobFinished(j);
}

async function onJobFinished(j: Job) {
  setState({ stopping: false, runBusy: false });
  log(j.state === "done" ? "ok" : j.state === "failed" ? "error" : "warn", t("log.jobFinished", { state: t(`job.state.${j.state}`) }));
  if (j.state === "failed") {
    const msg = j.first_error || j.message;
    if (msg) {
      log("error", msg);
      toast(msg, "error");
    }
  }
  await refreshCase(true);
  if (j.state === "done") {
    await loadResults(true);
    if (state.step === "run") setState({ step: "results" });
  }
}

export async function runCase(mode?: "preview" | "final") {
  const p = state.payload;
  if (!p || state.runBusy || isActive(state.job)) return;
  const m = mode ?? ((p.case.run?.mode as "preview" | "final") || "preview");
  setState({ runBusy: true });
  try {
    await settle();
    const r = await api.run(p.case.case_id, m);
    log("info", t("log.jobStarted", { mode: t(m === "final" ? "run.final" : "run.preview") }));
    const j: Job = r.job ?? { job_id: r.job_id, state: "queued", progress: 0, mode: m };
    if (state.job?.job_id === j.job_id && !isActive(state.job)) {
      // WS already delivered the completion before the POST returned
      setState({ runBusy: false });
    } else if (isActive(j)) {
      updateJob(j);
    } else {
      setState({ job: j });
      void onJobFinished(j);
    }
  } catch (e) {
    setState({ runBusy: false });
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  }
}

/**
 * Mesh convergence study: the backend solves on coarse, normal and fine meshes in one job
 * (about 3x a normal run) and the results then carry `convergence` (GCI, observed order).
 */
export async function checkConvergence() {
  const p = state.payload;
  if (!p || state.runBusy || isActive(state.job)) return;
  setState({ runBusy: true });
  try {
    await settle();
    const r = await api.convergence(p.case.case_id);
    log("info", t("conv.started"));
    const j: Job = { ...(r.job ?? { job_id: r.job_id, state: "queued", progress: 0 }), study: "convergence" };
    if (state.job?.job_id === j.job_id && !isActive(state.job)) {
      setState({ runBusy: false });
    } else if (isActive(j)) {
      updateJob(j);
    } else {
      setState({ job: j });
      void onJobFinished(j);
    }
  } catch (e) {
    setState({ runBusy: false });
    log("error", t("log.error", { message: errMsg(e) }));
    toast(errMsg(e), "error");
  }
}

/** Jobs the user asked to stop: their end is reported as "stopped", never as a solver error. */
const stopRequested = new Set<string>();

export async function stopJob() {
  const j = state.job;
  if (!j || !isActive(j)) return;
  setState({ stopping: true });
  stopRequested.add(j.job_id);
  try {
    let r: Job | { job: Job };
    try {
      r = (await api.stopJob(j.job_id)) as Job | { job: Job };
    } catch (e) {
      // a queued job rewrites its status file every second; one retry covers that race
      if (!(e instanceof ApiError) || e.status < 500) throw e;
      await new Promise((res) => setTimeout(res, 400));
      if (!isActive(state.job) || state.job?.job_id !== j.job_id) return;
      r = (await api.stopJob(j.job_id)) as Job | { job: Job };
    }
    const nj = "job" in r && r.job ? r.job : (r as Job);
    if (nj && nj.state) updateJob({ ...nj, job_id: nj.job_id ?? j.job_id });
  } catch (e) {
    log("error", t("log.error", { message: errMsg(e) }));
  } finally {
    setState({ stopping: false });
  }
}

// ------------------------------------------------------------------ results
/** `relabel`: the language changed, so the field (its label) is fetched again even for the same run */
export async function loadResults(resetView: boolean, relabel = false) {
  const p = state.payload;
  if (!p) return;
  setState({ resultsLoading: true });
  try {
    const r = await api.results(p.case.case_id);
    if (state.payload?.case.case_id !== p.case.case_id) return;
    const q = r.quantities.find((x) => x.id === state.quantity) ?? r.quantities[0];
    const sameRun = state.results?.run_id && state.results.run_id === r.run_id;
    if (r.modes && state.selectedMode > r.modes.length) setState({selectedMode:1});
    setState({ results: r, ...(r.stale ? {} : { resultsBeforeUndo: false }) });
    if (q && r.gates.ran && (!sameRun || !state.field || resetView || relabel))
      await loadField(q.id, resetView || state.quantity !== q.id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) setState({ results: null, field: null });
    else log("error", t("log.error", { message: errMsg(e) }));
  } finally {
    setState({ resultsLoading: false });
  }
}

let fieldGen = 0;
export async function loadField(quantity: string, reset = true) {
  const p = state.payload;
  if (!p) return;
  // only the latest request of the open case may land: a slow answer for another case or quantity is dropped
  const gen = ++fieldGen;
  const stale = () => gen !== fieldGen || state.payload?.case.case_id !== p.case.case_id;
  try {
    const f = await api.field(p.case.case_id, quantity, state.selectedMode, state.section);
    if (stale()) return;
    const kind = state.results?.quantities.find((x) => x.id === quantity)?.kind;
    setState({
      field: f,
      quantity,
      ...(reset ? { range: null, colormap: kind === "diverging" ? "coolwarm" : "viridis" } : {}),
    });
  } catch (e) {
    if (stale()) return;
    // keep the choice visible in the quantity menu even when the field could not be loaded
    setState({ quantity, field: null });
    log("error", t("log.error", { message: errMsg(e) }));
  }
}

export async function selectMode(mode: number) {
  setState({ selectedMode: mode, probeValue: null });
  await loadField('mode', false);
}

export async function probeFieldPoint(at: number[], value: number, unit: string) {
  const token = ++fieldProbeGeneration;
  const {field, payload, results, selectedMode} = state;
  const cid = payload?.case.case_id, quantity = field?.quantity;
  if (!field?.section || state.mode === 'mock') {
    setState({probeValue: {at, value, unit}});
    return;
  }
  if (!cid || !quantity) return;
  setState({probeValue: null});
  try {
    // The picked triangle supplies the original position; the element supplies the numerical value.
    const reply = await api.probePoint(cid, at.map(v => v*1000), selectedMode, results?.run_id);
    if (token !== fieldProbeGeneration) return;
    const sample = reply.points[0];
    if (sample?.inside && Number.isFinite(sample.values[quantity])) {
      const scale = ['emag','jmag','q'].includes(quantity) ? 1e-6 : 1;
      setState({probeValue: {at, value: sample.values[quantity]*scale, unit}});
    }
  } catch (e) {
    if (token === fieldProbeGeneration) toast(errMsg(e), 'error');
  }
}
let sectionTimer = 0;
export function setSection(section: SectionPlane | null) {
  setState({ section, probeValue: null });
  window.clearTimeout(sectionTimer);
  sectionTimer = window.setTimeout(() => { if (state.quantity) void loadField(state.quantity, false); }, 160);
}

export function usingMock() {
  return isMock();
}

// ------------------------------------------------------------------ ui toggles
export const ui = {
  palette: (v?: boolean) => setState((s) => ({ palette: v ?? !s.palette })),
  ai: (v?: boolean) => setState((s) => ({ ai: v ?? !s.ai })),
  log: (v?: boolean) => setState((s) => ({ logOpen: v ?? !s.logOpen })),
};
