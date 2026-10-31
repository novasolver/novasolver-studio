// Browser demo: Pyodide runs Studio's own FEM (py/novastudio/fem_tet10.py, box_mesh.py) on this device; three.js draws it.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const T = {
  ja: { title: "片持ち梁をブラウザで解く", lead: "NovaSolver Studio と同じ有限要素ソルバ（2次四面体）が、インストールなしでこのページの中で動きます。結果は梁理論と照合します。",
    L: "長さ L [mm]", b: "幅 b [mm]", h: "高さ h [mm]", F: "先端の荷重 F [N]", mat: "材料", steel: "鋼（E 205 GPa）", aluminium: "アルミニウム（E 70 GPa）", pla: "PLA 3Dプリント（E 3.5 GPa）",
    run: "計算する", loading: "ソルバを読み込み中（初回は約 30 MB、1 分ほど）…", ready: "準備完了", solving: "計算中…", done: (s) => `計算完了（${s} 秒）`,
    fem: "FEM", theory: "梁理論", diff: "差", tip: "先端たわみ", mid: "中央の曲げ応力", peak: "最大ミーゼス応力",
    peakok: (sf) => `降伏まで余裕 ${sf} 倍`, peakbad: "降伏応力を超えています（線形の結果は成り立ちません）",
    mesh: (n, e) => `メッシュ: 節点 ${n}・要素 ${e}（2次四面体）。固定端の角は応力集中のため梁理論より高くなります。`,
    ratio: "長さ L は高さ h の 5 倍以上にしてください（短い梁には梁理論が合いません）。",
    privacy: "計算はすべてこの端末の中で行われ、入力も結果もどこにも送信されません。", legend: "ミーゼス応力 [MPa]（変形は強調表示）",
    cta1: "自分の CAD・STL で解析するには", cta2: "Windows 版 NovaSolver Studio（無料・オープンソース）。STEP/STL 読込、熱・流れ・接触・座屈、AI から操作（MCP）。" },
  en: { title: "Solve a cantilever in your browser", lead: "The same finite-element solver as NovaSolver Studio (quadratic tetrahedra) runs inside this page, with nothing to install. Results are checked against beam theory.",
    L: "Length L [mm]", b: "Width b [mm]", h: "Height h [mm]", F: "Tip load F [N]", mat: "Material", steel: "Steel (E 205 GPa)", aluminium: "Aluminium (E 70 GPa)", pla: "PLA, 3D printed (E 3.5 GPa)",
    run: "Solve", loading: "Loading the solver (about 30 MB the first time, a minute or so)…", ready: "Ready", solving: "Solving…", done: (s) => `Solved in ${s} s`,
    fem: "FEM", theory: "Beam theory", diff: "Diff.", tip: "Tip deflection", mid: "Bending stress at mid-span", peak: "Peak von Mises stress",
    peakok: (sf) => `${sf}× below yield`, peakbad: "Above the yield stress (the linear result no longer holds)",
    mesh: (n, e) => `Mesh: ${n} nodes, ${e} quadratic tetrahedra. The clamped corners carry a stress concentration that beam theory does not have.`,
    ratio: "Make the length at least 5 times the height (beam theory does not fit short beams).",
    privacy: "Everything is computed on this device; no input or result is sent anywhere.", legend: "von Mises stress [MPa] (deformation exaggerated)",
    cta1: "Analyse your own CAD or STL", cta2: "NovaSolver Studio for Windows (free, open source): STEP/STL import, heat, flow, contact, buckling, driven by AI over MCP." },
  zh: { title: "在浏览器中求解悬臂梁", lead: "与 NovaSolver Studio 相同的有限元求解器（二次四面体）直接在本页面中运行，无需安装。结果与梁理论对照。",
    L: "长度 L [mm]", b: "宽度 b [mm]", h: "高度 h [mm]", F: "端部载荷 F [N]", mat: "材料", steel: "钢（E 205 GPa）", aluminium: "铝（E 70 GPa）", pla: "PLA 3D 打印（E 3.5 GPa）",
    run: "计算", loading: "正在加载求解器（首次约 30 MB，约一分钟）…", ready: "准备就绪", solving: "计算中…", done: (s) => `计算完成（${s} 秒）`,
    fem: "FEM", theory: "梁理论", diff: "差", tip: "端部挠度", mid: "跨中弯曲应力", peak: "最大米塞斯应力",
    peakok: (sf) => `距屈服还有 ${sf} 倍余量`, peakbad: "超过屈服应力（线性结果不再成立）",
    mesh: (n, e) => `网格：节点 ${n}，二次四面体单元 ${e}。固定端角部存在应力集中，高于梁理论。`,
    ratio: "请使长度至少为高度的 5 倍（短梁不适用梁理论）。",
    privacy: "全部计算都在本设备上完成，输入和结果不会发送到任何地方。", legend: "米塞斯应力 [MPa]（变形已放大）",
    cta1: "用您自己的 CAD 或 STL 进行分析", cta2: "Windows 版 NovaSolver Studio（免费、开源）：STEP/STL 导入，热、流动、接触、屈曲，可由 AI 通过 MCP 操作。" },
};
const qs = new URLSearchParams(location.search);
let lang = qs.get("lang") || (navigator.language || "ja").slice(0, 2);
if (!T[lang]) lang = "en";
const t = (k) => T[lang][k];
const $ = (id) => document.getElementById(id);

function applyLang() {
  document.documentElement.lang = lang === "zh" ? "zh-Hans" : lang;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
  $("lang").value = lang;
}
$("lang").addEventListener("change", (e) => { lang = e.target.value; applyLang(); if (last) show(last); });
applyLang();

for (const id of ["L", "b", "h", "F"]) {
  const upd = () => { $(id + "v").textContent = $(id).value; };
  $(id).addEventListener("input", upd); upd();
}

// ---------------------------------------------------------------- three.js view
const view = $("view");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);
const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 100);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.2); sun.position.set(1, -2, 3); scene.add(sun);
let mesh = null, ghost = null;
function resize() {
  const w = view.clientWidth, h = view.clientHeight || 400;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); render();
}
function render() { renderer.render(scene, camera); }
controls.addEventListener("change", render);
addEventListener("resize", resize);
resize();

const MAP = [[0x3b, 0x4c, 0xc0], [0x6f, 0x92, 0xf3], [0xaa, 0xc7, 0xfd], [0xdd, 0xdc, 0xdc], [0xf7, 0xb8, 0x9c], [0xe7, 0x74, 0x5b], [0xb4, 0x04, 0x26]];
function color(x) {
  const s = Math.min(Math.max(x, 0), 1) * (MAP.length - 1), i = Math.min(Math.floor(s), MAP.length - 2), f = s - i;
  return MAP[i].map((c, k) => (c + (MAP[i + 1][k] - c) * f) / 255);
}

function draw(r) {
  for (const m of [mesh, ghost]) if (m) { scene.remove(m); m.geometry.dispose(); }
  const p = r.positions, d = r.displacement, n = p.length / 3;
  const umax = Math.max(...d.map(Math.abs)) || 1;
  const k = 0.12 * r.L / umax;                       // exaggerate so the bend is visible at any load
  const pos = new Float32Array(p.length), col = new Float32Array(p.length);
  const vmax = Math.max(...r.vm) || 1;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < 3; j++) pos[3 * i + j] = p[3 * i + j] + k * d[3 * i + j];
    col.set(color(r.vm[i] / vmax), 3 * i);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.setIndex(r.indices); g.computeVertexNormals();
  mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide, roughness: 0.6 }));
  const g0 = new THREE.BufferGeometry();
  g0.setAttribute("position", new THREE.BufferAttribute(new Float32Array(p), 3)); g0.setIndex(r.indices);
  ghost = new THREE.Mesh(g0, new THREE.MeshBasicMaterial({ color: 0x8494aa, wireframe: true, transparent: true, opacity: 0.12 }));
  scene.add(ghost, mesh);
  const c = new THREE.Vector3(r.L / 2, r.b / 2, 0);
  controls.target.copy(c);
  camera.position.set(c.x + 0.25 * r.L, c.y - 1.25 * r.L, c.z + 0.55 * r.L);
  camera.up.set(0, 0, 1); controls.update();
  $("legend").hidden = false;
  $("lmid").textContent = (vmax / 2e6).toPrecision(3); $("lmax").textContent = (vmax / 1e6).toPrecision(3);
  render();
}

// ---------------------------------------------------------------- results table
let last = null;
const fmt = (x, digits = 3) => Number(x).toPrecision(digits);
function show(r) {
  last = r;
  $("res").hidden = false;
  $("tip").textContent = fmt(r.tip * 1e3) + " mm"; $("rtip").textContent = fmt(r.ref_tip * 1e3) + " mm";
  $("dtip").textContent = (100 * (r.tip / r.ref_tip - 1)).toFixed(1) + " %";
  $("mid").textContent = fmt(r.sigma_mid / 1e6) + " MPa"; $("rmid").textContent = fmt(r.ref_mid / 1e6) + " MPa";
  $("dmid").textContent = (100 * (r.sigma_mid / r.ref_mid - 1)).toFixed(1) + " %";
  $("peak").textContent = fmt(r.vm_max / 1e6) + " MPa";
  const sf = r.sy / r.vm_max;
  $("peaknote").textContent = sf >= 1 ? t("peakok")(sf.toFixed(1)) : t("peakbad");
  $("peaknote").className = sf >= 1 ? "ok" : "warn";
  $("meshnote").textContent = t("mesh")(r.nodes, r.elements);
}

// ---------------------------------------------------------------- Pyodide
let py = null;
async function boot() {
  $("status").textContent = t("loading");
  py = await loadPyodide();
  await py.loadPackage(["numpy", "scipy"]);
  py.FS.mkdirTree("/home/pyodide/novastudio");
  for (const f of ["novastudio/__init__.py", "novastudio/fem_tet10.py", "novastudio/box_mesh.py", "demo.py"]) {
    const src = await (await fetch("py/" + f)).text();
    py.FS.writeFile("/home/pyodide/" + f, src);
  }
  await py.runPythonAsync("import sys; sys.path.insert(0, '/home/pyodide'); import demo");
  $("status").textContent = t("ready");
  $("run").disabled = false;
  solve();
}

async function solve() {
  const L = +$("L").value, b = +$("b").value, h = +$("h").value, F = +$("F").value;
  if (L < 5 * h) { $("status").textContent = t("ratio"); return; }
  $("run").disabled = true; $("status").textContent = t("solving");
  await new Promise((r) => setTimeout(r, 30));          // let the status paint before the solve blocks
  const t0 = performance.now();
  try {
    const out = py.globals.get("demo").run(L, b, h, F, $("mat").value);
    const r = out.toJs({ dict_converter: Object.fromEntries }); out.destroy();
    draw(r); show(r);
    $("status").textContent = t("done")(((performance.now() - t0) / 1e3).toFixed(1));
  } catch (e) {
    $("status").textContent = String(e).split("\n").slice(-2).join(" ");
  } finally { $("run").disabled = false; }
}
$("run").addEventListener("click", solve);
boot();
