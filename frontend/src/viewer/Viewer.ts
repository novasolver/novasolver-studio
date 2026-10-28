// NovaSolver Studio 3D viewer — framework independent (DESIGN.md §7).
// Only dependency: three.js. No React imports here; the same module is meant to be
// reused by MCP Apps and novasolver.jp.
//
// Performance notes (Intel HD 630 / WebGL2):
//  - All geometry faces are merged into ONE mesh + ONE edge line set (2 draw calls).
//  - Field result is ONE mesh + ONE edge set (+ one dashed ghost outline).
//  - Ground grid and contact shadow are ONE transparent quad with an analytic shader
//    (no shadow maps, no post-processing).
//  - Selection / hover outlines are fat lines over the face boundary only (≤ 2 draw calls).
//  - Image-based lighting comes from a RoomEnvironment PMREM generated once at start-up.
//  - Rendering is on demand: we only draw when something changed or damping is active.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { getLut, type ColormapName } from "./colormaps";
import { VIEWER_PALETTES, type ViewerPalette, type ViewerTheme } from "./palette";

export type FaceId = number | string;
export type ViewName = "iso" | "front" | "top" | "fit";

export interface ViewerFace {
  id: FaceId;
  label?: string;
  positions: ArrayLike<number>;
  indices: ArrayLike<number>;
}

export interface ViewerGeometry {
  faces: ViewerFace[];
}

export interface ViewerField {
  positions: ArrayLike<number>;
  indices: ArrayLike<number>;
  scalars: ArrayLike<number>;
  range: [number, number];
  displacement?: ArrayLike<number> | null;
  unit?: string;
  label?: string;
}

export type FacePickHandler = (id: FaceId | null, info: { label?: string; shiftKey: boolean }) => void;
export type FaceHoverHandler = (id: FaceId | null, label?: string) => void;

const HOVER_LIGHTEN = 0.1;
const AXIS_COLORS = { x: "#e5566f", y: "#3fc07a", z: "#4f8ff7" } as const;

const GROUND_VERT = /* glsl */ `
varying vec2 vXY;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vXY = w.xy;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const GROUND_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uMinor;
uniform float uMinorA;
uniform float uMajorA;
uniform vec2 uCenter;
uniform vec2 uHalf;
uniform float uBlur;
uniform float uShadowA;
uniform float uFade;
uniform float uOpacity;
varying vec2 vXY;

float gridLine(vec2 p, float s) {
  vec2 q = p / s;
  vec2 w = fwidth(q);
  vec2 g = abs(fract(q - 0.5) - 0.5) / max(w, vec2(1e-6));
  return 1.0 - min(min(g.x, g.y), 1.0);
}

void main() {
  float r = length(vXY - uCenter);
  float fade = 1.0 - smoothstep(uFade * 0.3, uFade, r);
  vec2 w = fwidth(vXY / uMinor);
  float lod = clamp(1.0 - max(w.x, w.y) * 1.6, 0.0, 1.0);
  float minor = gridLine(vXY, uMinor) * uMinorA * lod;
  float major = gridLine(vXY, uMinor * 10.0) * uMajorA;
  float lineA = max(minor, major) * fade;
  vec2 q = abs(vXY - uCenter) - uHalf;
  float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
  float sh = (1.0 - smoothstep(-uBlur * 0.6, uBlur, d)) * uShadowA;
  float a = lineA + sh * (1.0 - lineA);
  vec3 col = uColor * lineA / max(a, 1e-4);
  gl_FragColor = vec4(col, a * uOpacity);
}`;

/** 1-2-5 rounding for grid spacing. */
function niceStep(x: number): number {
  if (!(x > 0)) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(x)));
  const m = x / e;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * e;
}

export class Viewer {
  private container: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private keyLight: THREE.DirectionalLight;
  private hemi: THREE.HemisphereLight;
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private resizeObserver: ResizeObserver;
  private frame = 0;
  private dirty = true;
  private disposed = false;
  private theme: ViewerTheme = "dark";
  private pal: ViewerPalette = VIEWER_PALETTES.dark;

  // ground (grid + contact shadow, one quad)
  private ground: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  private groundZ = 0;
  private groundOn = false;
  private groundAllowed = true;

  // geometry (pickable faces)
  private geoMesh: THREE.Mesh | null = null;
  private geoEdges: THREE.LineSegments | null = null;
  private ghost: THREE.LineSegments | null = null;
  private wire: THREE.LineSegments | null = null;
  private wireOn = false;
  private triFace: Int32Array = new Int32Array(0); // triangle -> face index
  private faceIds: FaceId[] = [];
  private faceLabels: (string | undefined)[] = [];
  private faceVertexRange: [number, number][] = []; // [start, count] in vertices
  private faceTriRange: [number, number][] = []; // [start, count] in triangles
  private faceIndexById = new Map<string, number>();
  private outlineCache = new Map<number, Float32Array>();
  private layers = new Map<string, { ids: Set<string>; color: THREE.Color }>();
  private hoverFace = -1;
  private externalHover = -1;
  private selected = new Set<number>();
  private hidden = new Set<string>();
  private through = false;
  private originalIndex = new Uint32Array(0);
  private boxHandlers = new Set<(ids: FaceId[], add: boolean) => void>();
  private boxStart: { x: number; y: number; add: boolean } | null = null;
  private boxElement: HTMLDivElement | null = null;
  private pickingEnabled = true;
  private selLine: LineSegments2 | null = null;
  private hoverLine: LineSegments2 | null = null;
  private selMat: LineMaterial;
  private hoverMat: LineMaterial;

  // free-stream guide (external flow): a few arrows upstream of the body, one fat-line draw call
  private flowDir: THREE.Vector3 | null = null;
  private flowLine: LineSegments2 | null = null;
  private flowBox: THREE.Box3 | null = null;
  private flowMat: LineMaterial;

  // field
  private fieldMesh: THREE.Mesh | null = null;
  private fieldEdges: THREE.LineSegments | null = null;
  private field: ViewerField | null = null;
  private basePositions: Float32Array | null = null;
  private colormap: ColormapName = "viridis";
  private range: [number, number] = [0, 1];
  private deformScale = 1;

  private pickHandlers = new Set<FacePickHandler>();
  private hoverHandlers = new Set<FaceHoverHandler>();
  private cameraHandlers = new Set<() => void>();
  private downAt: { x: number; y: number } | null = null;
  private pendingHover: { x: number; y: number } | null = null;

  private tween: {
    t0: number;
    dur: number;
    fromPos: THREE.Vector3;
    toPos: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
  } | null = null;

  private triad: SVGSVGElement;

  constructor(container: HTMLElement) {
    this.container = container;
    const w = Math.max(1, container.clientWidth);
    const h = Math.max(1, container.clientHeight);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h);
    this.renderer.setClearColor(0x000000, 0); // background is a CSS gradient behind the canvas
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.outline = "none";
    this.renderer.domElement.style.touchAction = "none";
    container.appendChild(this.renderer.domElement);

    // Z-up, like most CAE tools. Orbit = turntable around Z: no roll, stable.
    this.camera = new THREE.PerspectiveCamera(32, w / h, 0.001, 1000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(1, -1.4, 0.9);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.14;
    this.controls.rotateSpeed = 0.85;
    this.controls.zoomSpeed = 0.9;
    this.controls.panSpeed = 0.9;
    this.controls.screenSpacePanning = true;
    this.controls.zoomToCursor = true;
    this.controls.minPolarAngle = 0.001;
    this.controls.maxPolarAngle = Math.PI - 0.001;
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.addEventListener("change", () => {
      this.dirty = true;
    });
    this.controls.addEventListener("start", () => {
      this.tween = null;
    });

    // Lighting: sky/ground fill + a camera-relative key light from the upper left +
    // soft image-based speculars (generated once; no per-frame cost).
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1.1);
    this.scene.add(this.hemi);
    this.keyLight = new THREE.DirectionalLight(0xffffff, 1.7);
    this.keyLight.position.set(-0.7, 0.8, 1);
    this.camera.add(this.keyLight);
    this.scene.add(this.camera);
    try {
      const pmrem = new THREE.PMREMGenerator(this.renderer);
      const room = new RoomEnvironment();
      this.scene.environment = pmrem.fromScene(room, 0.04).texture;
      this.scene.environmentIntensity = 0.45;
      room.dispose();
      pmrem.dispose();
    } catch {
      /* IBL is optional */
    }

    // ground: grid + contact shadow
    this.ground = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.ShaderMaterial({
        vertexShader: GROUND_VERT,
        fragmentShader: GROUND_FRAG,
        transparent: true,
        depthWrite: false,
        uniforms: {
          uColor: { value: new THREE.Color(1, 1, 1) },
          uMinor: { value: 0.1 },
          uMinorA: { value: 0.05 },
          uMajorA: { value: 0.1 },
          uCenter: { value: new THREE.Vector2() },
          uHalf: { value: new THREE.Vector2(0.1, 0.1) },
          uBlur: { value: 0.05 },
          uShadowA: { value: 0.2 },
          uFade: { value: 3 },
          uOpacity: { value: 1 },
        },
      }),
    );
    this.ground.renderOrder = -1;
    this.ground.visible = false;
    this.scene.add(this.ground);

    this.selMat = new LineMaterial({ color: 0x22d3ee, linewidth: 2, transparent: true, depthWrite: false });
    this.hoverMat = new LineMaterial({ color: 0x22d3ee, linewidth: 1, transparent: true, opacity: 0.6, depthWrite: false });
    this.selMat.resolution.set(w, h);
    this.hoverMat.resolution.set(w, h);
    this.flowMat = new LineMaterial({ color: 0xc9ccd3, linewidth: 1.5, transparent: true, depthWrite: false });
    this.flowMat.resolution.set(w, h);

    this.triad = this.createTriad();
    container.appendChild(this.triad);

    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", this.onPointerDown, true);
    el.addEventListener("pointerup", this.onPointerUp);
    el.addEventListener("pointermove", this.onPointerMove);
    el.addEventListener("pointerleave", this.onPointerLeave);
    el.addEventListener('pointercancel', this.onPointerCancel);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);

    this.applyTheme();
    this.loop();
  }

  // ---------------------------------------------------------------- public API

  setGeometry(geo: ViewerGeometry | null): void {
    this.disposeObject(this.geoMesh);
    this.disposeObject(this.geoEdges);
    this.disposeObject(this.ghost);
    this.disposeObject(this.wire);
    this.geoMesh = null;
    this.geoEdges = null;
    this.ghost = null;
    this.wire = null;
    this.faceIds = [];
    this.faceLabels = [];
    this.faceVertexRange = [];
    this.faceTriRange = [];
    this.faceIndexById.clear();
    this.outlineCache.clear();
    this.hoverFace = -1;
    this.externalHover = -1;
    const prevSel = [...this.selected].map((i) => String(this.faceIds[i]));
    this.selected.clear();
    if (!geo || geo.faces.length === 0) {
      this.updateOutlines();
      this.updateGround();
      this.buildFlowGuide();
      this.dirty = true;
      return;
    }

    let nv = 0;
    let nt = 0;
    for (const f of geo.faces) {
      nv += f.positions.length / 3;
      nt += f.indices.length / 3;
    }
    const pos = new Float32Array(nv * 3);
    const col = new Float32Array(nv * 3);
    const idx = new Uint32Array(nt * 3);
    this.triFace = new Int32Array(nt);

    let vo = 0;
    let to = 0;
    geo.faces.forEach((f, fi) => {
      const fv = f.positions.length / 3;
      for (let i = 0; i < f.positions.length; i++) pos[vo * 3 + i] = f.positions[i];
      const ft = f.indices.length / 3;
      for (let i = 0; i < f.indices.length; i++) idx[to * 3 + i] = f.indices[i] + vo;
      for (let i = 0; i < ft; i++) this.triFace[to + i] = fi;
      this.faceIds.push(f.id);
      this.faceLabels.push(f.label);
      this.faceVertexRange.push([vo, fv]);
      this.faceTriRange.push([to, ft]);
      this.faceIndexById.set(String(f.id), fi);
      vo += fv;
      to += ft;
    });
    for (const k of prevSel) {
      const fi = this.faceIndexById.get(k);
      if (fi != null) this.selected.add(fi);
    }

    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.setAttribute('faceOpacity', new THREE.BufferAttribute(new Float32Array(nv).fill(1), 1));
    this.originalIndex = idx.slice();
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    // vertices are per face, so smooth normals stay crisp at face boundaries (CAD look)
    g.computeVertexNormals();
    g.computeBoundingSphere();
    g.computeBoundingBox();

    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.55,
      metalness: 0,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
    mat.onBeforeCompile = shader => {
      shader.vertexShader = 'attribute float faceOpacity; varying float vFaceOpacity;\n' + shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvFaceOpacity = faceOpacity;');
      shader.fragmentShader = 'varying float vFaceOpacity;\n' + shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.a *= vFaceOpacity;');
    };
    this.geoMesh = new THREE.Mesh(g, mat);
    this.scene.add(this.geoMesh);

    const eg = new THREE.EdgesGeometry(g, 30);
    this.geoEdges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ transparent: true, depthWrite: false }));
    this.scene.add(this.geoEdges);

    // undeformed outline used with deformed results: the same edges, dashed
    const dash = Math.max(1e-6, (g.boundingSphere?.radius ?? 1) * 0.012);
    this.ghost = new THREE.LineSegments(
      eg.clone(),
      new THREE.LineDashedMaterial({ dashSize: dash, gapSize: dash * 0.75, transparent: true, depthWrite: false }),
    );
    this.ghost.computeLineDistances();
    this.scene.add(this.ghost);

    this.applyLineColors();
    this.updateGeometryColors();
    if (this.wireOn) this.buildWire();
    this.syncVisibility();
    this.updateOutlines();
    this.updateGround();
    this.buildFlowGuide();
    const firstTime = !this.hasFitted;
    if (firstTime) this.view("iso", false);
    this.dirty = true;
  }

  setField(field: ViewerField | null): void {
    this.disposeObject(this.fieldMesh);
    this.disposeObject(this.fieldEdges);
    this.fieldMesh = null;
    this.fieldEdges = null;
    this.field = field;
    this.basePositions = null;
    if (field && field.positions.length > 0) {
      this.range = [field.range[0], field.range[1]];
      this.basePositions = Float32Array.from(field.positions);
      const n = this.basePositions.length / 3;
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.basePositions), 3));
      g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
      g.setIndex(new THREE.BufferAttribute(Uint32Array.from(field.indices), 1));
      const mat = new THREE.MeshStandardMaterial({
        vertexColors: true,
        flatShading: true,
        roughness: 0.85,
        metalness: 0,
        envMapIntensity: 0.35,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
      });
      this.fieldMesh = new THREE.Mesh(g, mat);
      this.scene.add(this.fieldMesh);
      this.applyDeform();
      this.updateFieldColors();
    }
    this.syncVisibility();
    this.updateGround();
    this.dirty = true;
  }

  /** Show every triangle edge of the geometry (useful to inspect a generated mesh). */
  setWireframe(on: boolean): void {
    this.wireOn = on;
    if (on && !this.wire) this.buildWire();
    this.syncVisibility();
    this.dirty = true;
  }

  /** Allow or suppress the ground grid + contact shadow (e.g. off for 2-D slice cases). */
  setGround(on: boolean): void {
    this.groundAllowed = on;
    this.updateGround();
  }

  /** Match the host theme: background is CSS; this sets lines, grid, shadow and accents. */
  setTheme(theme: ViewerTheme): void {
    if (theme === this.theme) return;
    this.theme = theme;
    this.applyTheme();
  }

  setColormap(name: ColormapName): void {
    this.colormap = name;
    this.updateFieldColors();
  }

  setRange(min: number, max: number): void {
    if (!Number.isFinite(min) || !Number.isFinite(max)) return;
    this.range = [min, max];
    this.updateFieldColors();
  }

  getRange(): [number, number] {
    return [this.range[0], this.range[1]];
  }

  setDeformScale(k: number): void {
    this.deformScale = Number.isFinite(k) ? k : 0;
    this.applyDeform();
    this.syncVisibility();
  }

  /**
   * Paint faces with a colour. Layers stack in insertion order (later wins), so the
   * host can keep e.g. "unassigned" (orange) and "flash" independently.
   * Pass an empty list or null colour to clear a layer.
   */
  highlightFaces(ids: FaceId[], color: string | null, layer = "default"): void {
    if (!color || ids.length === 0) {
      this.layers.delete(layer);
    } else {
      this.layers.delete(layer); // re-insert to move to top
      this.layers.set(layer, {
        ids: new Set(ids.map(String)),
        color: new THREE.Color().setStyle(color, THREE.SRGBColorSpace),
      });
    }
    this.updateGeometryColors();
  }

  /** Selected faces: accent tint over the shaded colour + a 2 px screen-space outline. */
  setSelection(ids: FaceId[]): void {
    this.selected.clear();
    for (const id of ids) {
      const fi = this.faceIndexById.get(String(id));
      if (fi != null) this.selected.add(fi);
    }
    this.updateGeometryColors();
    this.updateOutlines();
  }

  setHiddenFaces(ids: FaceId[]): void {
    this.hidden = new Set(ids.map(String));
    if (!this.geoMesh) return;
    const g = this.geoMesh.geometry;
    const idx = this.originalIndex.slice();
    this.triFace.forEach((fi, t) => {
      if (this.hidden.has(String(this.faceIds[fi]))) idx[t*3+1] = idx[t*3+2] = idx[t*3];
    });
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    if (this.geoEdges) {
      this.geoEdges.geometry.dispose();
      this.geoEdges.geometry = new THREE.EdgesGeometry(g, 30);
    }
    if (this.wire) { this.disposeObject(this.wire); this.wire = null; if (this.wireOn) this.buildWire(); }
    this.setHover(-1);
    this.updateOutlines();
    this.dirty = true;
  }

  setSeeThrough(on: boolean): void {
    this.through = on;
    this.syncVisibility();
    this.updateGeometryColors();
  }

  onBoxPick(cb: (ids: FaceId[], add: boolean) => void): () => void {
    this.boxHandlers.add(cb);
    return () => this.boxHandlers.delete(cb);
  }

  selectBox(x0: number, y0: number, x1: number, y1: number, add = false): void {
    this.boxHandlers.forEach(h => h(this.boxFaces(x0, y0, x1, y1), add));
  }

  /** Hover driven by the host (e.g. a list row): 1 px outline, no hover callbacks. */
  setHoverFace(id: FaceId | null): void {
    const fi = id == null ? -1 : (this.faceIndexById.get(String(id)) ?? -1);
    if (fi === this.externalHover) return;
    this.externalHover = fi;
    this.updateGeometryColors();
    this.updateOutlines();
  }

  onFacePick(cb: FacePickHandler): () => void {
    this.pickHandlers.add(cb);
    return () => this.pickHandlers.delete(cb);
  }

  onFaceHover(cb: FaceHoverHandler): () => void {
    this.hoverHandlers.add(cb);
    return () => this.hoverHandlers.delete(cb);
  }

  onCameraChange(cb: () => void): () => void {
    this.cameraHandlers.add(cb);
    return () => this.cameraHandlers.delete(cb);
  }

  setPickingEnabled(on: boolean): void {
    this.pickingEnabled = on;
    if (!on) this.setHover(-1);
  }

  view(name: ViewName, animate = true): void {
    let dir: THREE.Vector3;
    if (name === "fit") {
      dir = this.camera.position.clone().sub(this.controls.target);
      if (dir.lengthSq() < 1e-12) dir.set(1, -1.4, 0.9);
    } else if (name === "front") {
      dir = new THREE.Vector3(0, -1, 0.0001);
    } else if (name === "top") {
      dir = new THREE.Vector3(0, -0.0001, 1);
    } else {
      dir = new THREE.Vector3(1, -1.35, 0.85);
    }
    this.lookFrom(dir, animate);
  }

  /** Look at the model from a direction (e.g. [1,0,0] = from +X). */
  viewDirection(dir: [number, number, number], animate = true): void {
    const d = new THREE.Vector3(...dir);
    if (Math.abs(d.z) > 0.999) d.y -= 0.0001; // keep the turntable well-defined
    this.lookFrom(d, animate);
  }

  /**
   * Move the camera close to where the shown result is largest (e.g. peak stress at a tooth root hidden at the back).
   * Looks at it from outside the body, keeping some of the current angle. Returns false when no field is shown.
   */
  focusPeak(animate = true): boolean {
    const f = this.field;
    const base = this.basePositions;
    const sphere = this.boundingSphere();
    if (!f || !base || !sphere || f.scalars.length === 0) return false;
    const diverging = f.range[0] < 0 && f.range[1] > 0;
    let best = 0;
    let bestV = -Infinity;
    for (let i = 0; i < f.scalars.length; i++) {
      const v = diverging ? Math.abs(f.scalars[i]) : f.scalars[i];
      if (v > bestV) {
        bestV = v;
        best = i;
      }
    }
    const p = new THREE.Vector3(base[best * 3], base[best * 3 + 1], base[best * 3 + 2]);
    const out = p.clone().sub(sphere.center);
    if (out.lengthSq() < 1e-18) out.set(1, -1.35, 0.85);
    const cur = this.camera.position.clone().sub(this.controls.target).normalize();
    const dir = out.normalize().add(cur.multiplyScalar(0.6)).normalize();
    const toPos = p.clone().add(dir.multiplyScalar(sphere.radius * 0.9));
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!animate || reduce) {
      this.camera.position.copy(toPos);
      this.controls.target.copy(p);
      this.controls.update();
      this.tween = null;
      this.dirty = true;
      return true;
    }
    this.tween = { t0: performance.now(), dur: 450, fromPos: this.camera.position.clone(), toPos,
                   fromTarget: this.controls.target.clone(), toTarget: p };
    return true;
  }

  /** Force a resize (e.g. after the host layout changed). */
  resize(): void {
    const w = Math.max(1, this.container.clientWidth);
    const h = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.selMat.resolution.set(w, h);
    this.hoverMat.resolution.set(w, h);
    this.flowMat.resolution.set(w, h);
    this.dirty = true;
  }

  /**
   * Render the current view at w × h device pixels into a new 2D canvas (transparent background), for share images
   * and videos. The horizontal extent the user sees is kept when the aspect is narrower; `orbit` turns the camera
   * that many radians about the vertical (Z) axis through the orbit target. The on-screen view is left as it was.
   */
  snapshot(w: number, h: number, orbit = 0): HTMLCanvasElement {
    this.beginCapture(w, h);
    const out = document.createElement("canvas");
    out.width = w;
    out.height = h;
    out.getContext("2d")!.drawImage(this.captureFrame(orbit), 0, 0);
    this.endCapture();
    return out;
  }

  private capture: { size: THREE.Vector2; ratio: number; pos: THREE.Vector3; aspect: number; offset: THREE.Vector3 } | null =
    null;

  /** Start an off-screen capture at w × h (see snapshot); frames come from captureFrame, endCapture restores the view. */
  beginCapture(w: number, h: number): void {
    if (this.capture) this.endCapture();
    const half = THREE.MathUtils.degToRad(this.camera.fov) / 2;
    const hNow = Math.atan(Math.tan(half) * this.camera.aspect);
    const hNew = Math.atan(Math.tan(half) * (w / h));
    this.capture = {
      size: this.renderer.getSize(new THREE.Vector2()),
      ratio: this.renderer.getPixelRatio(),
      pos: this.camera.position.clone(),
      aspect: this.camera.aspect,
      offset: this.camera.position.clone().sub(this.controls.target).multiplyScalar(Math.max(1, Math.tan(hNow) / Math.tan(hNew))),
    };
    this.tween = null;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    for (const m of [this.selMat, this.hoverMat, this.flowMat]) m.resolution.set(w, h);
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(w, h, false);
  }

  /** Render one capture frame turned `orbit` radians about Z; the returned canvas is overwritten by the next frame. */
  captureFrame(orbit = 0): HTMLCanvasElement {
    const c = this.capture;
    if (!c) throw new Error("beginCapture first");
    const offset = c.offset.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), orbit);
    this.camera.position.copy(this.controls.target).add(offset);
    this.camera.lookAt(this.controls.target);
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement;
  }

  endCapture(): void {
    const c = this.capture;
    if (!c) return;
    this.capture = null;
    this.renderer.setPixelRatio(c.ratio);
    this.renderer.setSize(c.size.x, c.size.y, false);
    this.camera.position.copy(c.pos);
    this.camera.lookAt(this.controls.target);
    this.camera.aspect = c.aspect;
    this.camera.updateProjectionMatrix();
    for (const m of [this.selMat, this.hoverMat, this.flowMat]) m.resolution.set(c.size.x, c.size.y);
    this.dirty = true;
  }

  /**
   * External flow: draw the free-stream direction as arrows in front of the body
   * (e.g. [1,0,0] = flow toward +X). null hides it. Hidden while a result field is shown.
   */
  setFlowDirection(dir: [number, number, number] | null): void {
    const d = dir ? new THREE.Vector3(...dir) : null;
    if (d && d.lengthSq() > 0) d.normalize();
    const same = (!d && !this.flowDir) || (!!d && !!this.flowDir && d.distanceToSquared(this.flowDir) < 1e-9);
    this.flowDir = d && d.lengthSq() > 0 ? d : null;
    if (!same || !this.flowLine) this.buildFlowGuide();
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    const el = this.renderer.domElement;
    el.removeEventListener("pointerdown", this.onPointerDown, true);
    el.removeEventListener("pointerup", this.onPointerUp);
    el.removeEventListener("pointermove", this.onPointerMove);
    el.removeEventListener("pointerleave", this.onPointerLeave);
    el.removeEventListener('pointercancel', this.onPointerCancel);
    this.controls.dispose();
    this.disposeObject(this.geoMesh);
    this.disposeObject(this.geoEdges);
    this.disposeObject(this.ghost);
    this.disposeObject(this.wire);
    this.disposeObject(this.fieldMesh);
    this.disposeObject(this.fieldEdges);
    this.disposeObject(this.ground);
    this.disposeLine(this.selLine);
    this.disposeLine(this.hoverLine);
    this.disposeLine(this.flowLine);
    this.selMat.dispose();
    this.hoverMat.dispose();
    this.flowMat.dispose();
    this.scene.environment?.dispose();
    this.renderer.dispose();
    el.remove();
    this.triad.remove();
    this.pickHandlers.clear();
    this.boxHandlers.clear();
    this.boxElement?.remove();
    this.hoverHandlers.clear();
  }

  // --------------------------------------------------------------- internals

  private hasFitted = false;

  private lookFrom(direction: THREE.Vector3, animate: boolean): void {
    const sphere = this.boundingSphere();
    if (!sphere) return;
    this.hasFitted = true;
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const aspect = Math.max(0.3, this.camera.aspect);
    const fit = Math.max(sphere.radius / Math.sin(fov / 2), sphere.radius / Math.sin(Math.atan(Math.tan(fov / 2) * aspect)));
    const dist = fit * 1.08;
    const dir = direction.clone().normalize();
    const toTarget = sphere.center.clone();
    const toPos = toTarget.clone().add(dir.multiplyScalar(dist));
    this.camera.near = Math.max(dist / 1000, sphere.radius / 500);
    this.camera.far = dist + sphere.radius * 20;
    this.camera.updateProjectionMatrix();
    this.controls.minDistance = sphere.radius * 0.05;
    this.controls.maxDistance = sphere.radius * 60;

    if (!animate) {
      this.camera.position.copy(toPos);
      this.controls.target.copy(toTarget);
      this.controls.update();
      this.tween = null;
      this.dirty = true;
      return;
    }
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    this.tween = {
      t0: performance.now(),
      dur: reduce ? 1 : 450,
      fromPos: this.camera.position.clone(),
      toPos,
      fromTarget: this.controls.target.clone(),
      toTarget,
    };
  }

  private boundingSphere(): THREE.Sphere | null {
    const obj = this.geoMesh ?? this.fieldMesh;
    if (!obj) return null;
    obj.geometry.computeBoundingSphere();
    const base = obj.geometry.boundingSphere?.clone() ?? null;
    // a slice larger than the body (external flow) or the free-stream arrows: frame them too
    const slice = !!this.fieldMesh && this.fieldIsSlice();
    const arrows = !!this.flowLine?.visible && !!this.flowBox;
    if (!base || (!slice && !arrows)) return base;
    obj.geometry.computeBoundingBox();
    const box = obj.geometry.boundingBox!.clone();
    if (slice) {
      this.fieldMesh!.geometry.computeBoundingBox();
      box.union(this.fieldMesh!.geometry.boundingBox!);
    }
    if (arrows) box.union(this.flowBox!);
    return box.getBoundingSphere(new THREE.Sphere());
  }

  private buildFlowGuide(): void {
    this.disposeLine(this.flowLine);
    this.flowLine = null;
    this.flowBox = null;
    const d = this.flowDir;
    if (!d || !this.geoMesh) {
      this.dirty = true;
      return;
    }
    this.geoMesh.geometry.computeBoundingBox();
    const bb = this.geoMesh.geometry.boundingBox!;
    const c = bb.getCenter(new THREE.Vector3());
    const s = bb.getSize(new THREE.Vector3());
    const L = Math.max(s.x, s.y, s.z, 1e-9);
    const half = 0.5 * (Math.abs(d.x) * s.x + Math.abs(d.y) * s.y + Math.abs(d.z) * s.z);
    // spread the arrows vertically (Z) unless the flow itself is vertical
    const u = Math.abs(d.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
    u.addScaledVector(d, -u.dot(d)).normalize();
    const v = new THREE.Vector3().crossVectors(d, u).normalize();
    const pts: number[] = [];
    const push = (a: THREE.Vector3, b: THREE.Vector3) => pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
    const head = 0.14 * L;
    for (const [o, len] of [
      [-0.34, 0.9],
      [0, 1.25],
      [0.34, 0.9],
    ] as const) {
      const tip = c.clone().addScaledVector(d, -(half + 0.3 * L)).addScaledVector(u, o * L);
      const tail = tip.clone().addScaledVector(d, -len * L);
      push(tail, tip);
      const back = tip.clone().addScaledVector(d, -head);
      for (const w of [u, v]) {
        push(tip, back.clone().addScaledVector(w, head * 0.5));
        push(tip, back.clone().addScaledVector(w, -head * 0.5));
      }
    }
    const arr = new Float32Array(pts);
    const lg = new LineSegmentsGeometry();
    lg.setPositions(arr);
    this.flowLine = new LineSegments2(lg, this.flowMat);
    this.flowLine.renderOrder = 1;
    this.flowLine.visible = !this.fieldMesh;
    this.scene.add(this.flowLine);
    this.flowBox = new THREE.Box3().setFromArray(arr);
    this.dirty = true;
  }

  private applyTheme(): void {
    this.pal = VIEWER_PALETTES[this.theme];
    const u = this.ground.material.uniforms;
    u.uColor.value.setStyle(this.pal.grid, THREE.SRGBColorSpace);
    u.uMinorA.value = this.pal.gridMinorAlpha;
    u.uMajorA.value = this.pal.gridMajorAlpha;
    u.uShadowA.value = this.pal.shadowAlpha;
    this.selMat.color.setStyle(this.pal.selection, THREE.SRGBColorSpace);
    this.hoverMat.color.setStyle(this.pal.selection, THREE.SRGBColorSpace);
    this.hoverMat.opacity = this.pal.hoverAlpha;
    this.flowMat.color.setStyle(this.pal.flow, THREE.SRGBColorSpace);
    this.flowMat.opacity = this.pal.flowAlpha;
    this.hemi.groundColor.set(this.theme === "dark" ? 0x3a3c42 : 0x8a8d94);
    this.applyLineColors();
    this.updateGeometryColors();
    this.updateTriadStyle();
    this.dirty = true;
  }

  private applyLineColors(): void {
    const set = (obj: THREE.LineSegments | null, color: string, alpha: number) => {
      if (!obj) return;
      const m = obj.material as THREE.LineBasicMaterial;
      m.color.setStyle(color, THREE.SRGBColorSpace);
      m.opacity = alpha;
      m.needsUpdate = true;
    };
    set(this.geoEdges, this.pal.edge, this.pal.edgeAlpha);
    set(this.ghost, this.pal.ghost, this.pal.ghostAlpha);
    set(this.wire, this.pal.wire, this.pal.wireAlpha);
    set(this.fieldEdges, this.pal.fieldEdge, this.pal.fieldEdgeAlpha);
    this.dirty = true;
  }

  private updateGround(): void {
    const obj = this.geoMesh ?? this.fieldMesh;
    if (!obj) {
      this.ground.visible = this.groundOn = false;
      return;
    }
    obj.geometry.computeBoundingBox();
    const bb = obj.geometry.boundingBox!;
    const size = new THREE.Vector3();
    bb.getSize(size);
    const span = Math.max(size.x, size.y, size.z, 1e-9);
    // 2-D cases (a slice plane) and views of a flat field: no ground.
    const planar = size.z < span * 0.02;
    this.groundOn = !planar && this.groundAllowed;
    this.ground.visible = this.groundOn;
    if (!this.groundOn) {
      this.dirty = true;
      return;
    }
    const cx = (bb.min.x + bb.max.x) / 2;
    const cy = (bb.min.y + bb.max.y) / 2;
    const fade = span * 2.2;
    this.groundZ = bb.min.z - span * 0.0005;
    this.ground.position.set(cx, cy, this.groundZ);
    this.ground.scale.set(fade * 2, fade * 2, 1);
    const u = this.ground.material.uniforms;
    u.uCenter.value.set(cx, cy);
    u.uHalf.value.set(size.x / 2, size.y / 2);
    u.uBlur.value = Math.max(size.x, size.y) * 0.035 + size.z * 0.6;
    u.uFade.value = fade;
    u.uMinor.value = niceStep(span / 10);
    this.dirty = true;
  }

  /** A flat field inside a 3-D body (e.g. a CFD slice): the body is shown as a ghost around it. */
  private fieldIsSlice(): boolean {
    if (!this.fieldMesh || !this.geoMesh) return false;
    const ext = (o: THREE.Mesh) => {
      o.geometry.computeBoundingBox();
      const s = new THREE.Vector3();
      o.geometry.boundingBox!.getSize(s);
      return [s.x, s.y, s.z].sort((a, b) => a - b);
    };
    const f = ext(this.fieldMesh);
    const g = ext(this.geoMesh);
    return f[0] < f[2] * 0.01 && g[0] > g[2] * 0.05;
  }

  private syncVisibility(): void {
    const showField = !!this.fieldMesh;
    const slice = showField && this.fieldIsSlice();
    if (this.geoMesh) {
      this.geoMesh.visible = !showField || slice;
      const m = this.geoMesh.material as THREE.MeshStandardMaterial;
      const transparent = slice || this.through;
      m.opacity = slice ? 0.1 : 1;
      if (m.transparent !== transparent) {
        m.transparent = transparent;
        m.depthWrite = !transparent;
        m.needsUpdate = true;
      }
    }
    if (this.geoEdges) {
      this.geoEdges.visible = !showField || slice;
      (this.geoEdges.material as THREE.LineBasicMaterial).opacity = slice ? this.pal.edgeAlpha * 0.5 : this.pal.edgeAlpha;
    }
    if (this.wire) this.wire.visible = this.wireOn && !showField;
    const deformed = showField && !!this.field?.displacement?.length && this.deformScale !== 0;
    if (this.ghost) this.ghost.visible = deformed;
    if (this.flowLine) this.flowLine.visible = !showField;
    if (showField) this.setHover(-1);
    this.updateOutlines();
  }

  private buildWire(): void {
    if (!this.geoMesh) return;
    const wg = new THREE.WireframeGeometry(this.geoMesh.geometry);
    this.wire = new THREE.LineSegments(wg, new THREE.LineBasicMaterial({ transparent: true, depthWrite: false }));
    this.scene.add(this.wire);
    this.applyLineColors();
  }

  private updateGeometryColors(): void {
    if (!this.geoMesh) return;
    const attr = this.geoMesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const opacity = this.geoMesh.geometry.getAttribute('faceOpacity') as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const c = new THREE.Color();
    const base = new THREE.Color().setStyle(this.pal.base, THREE.SRGBColorSpace);
    const sel = new THREE.Color().setStyle(this.pal.selection, THREE.SRGBColorSpace);
    const white = new THREE.Color(1, 1, 1);
    for (let fi = 0; fi < this.faceIds.length; fi++) {
      const key = String(this.faceIds[fi]);
      c.copy(base);
      for (const layer of this.layers.values()) if (layer.ids.has(key)) c.copy(layer.color);
      if (this.selected.has(fi)) c.lerp(sel, this.pal.selectionTint);
      if (fi === this.hoverFace || fi === this.externalHover) c.lerp(white, HOVER_LIGHTEN);
      const [start, count] = this.faceVertexRange[fi];
      for (let v = start; v < start + count; v++) {
        opacity.setX(v, this.through && !this.selected.has(fi) ? .25 : 1);
        arr[v * 3] = c.r;
        arr[v * 3 + 1] = c.g;
        arr[v * 3 + 2] = c.b;
      }
    }
    attr.needsUpdate = true;
    opacity.needsUpdate = true;
    this.dirty = true;
  }

  /** Boundary edges of one face (edges used by exactly one of its triangles). */
  private faceOutline(fi: number): Float32Array {
    const cached = this.outlineCache.get(fi);
    if (cached) return cached;
    const g = this.geoMesh!.geometry;
    const pos = g.getAttribute("position") as THREE.BufferAttribute;
    const index = g.getIndex()!;
    const [t0, tn] = this.faceTriRange[fi];
    const q = (this.geoMesh!.geometry.boundingSphere?.radius ?? 1) * 1e-6;
    const key = (i: number) => `${Math.round(pos.getX(i) / q)},${Math.round(pos.getY(i) / q)},${Math.round(pos.getZ(i) / q)}`;
    const count = new Map<string, { n: number; a: number; b: number }>();
    for (let t = t0; t < t0 + tn; t++) {
      const v = [index.getX(t * 3), index.getX(t * 3 + 1), index.getX(t * 3 + 2)];
      for (let e = 0; e < 3; e++) {
        const a = v[e];
        const b = v[(e + 1) % 3];
        const ka = key(a);
        const kb = key(b);
        const k = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
        const hit = count.get(k);
        if (hit) hit.n++;
        else count.set(k, { n: 1, a, b });
      }
    }
    const out: number[] = [];
    for (const { n, a, b } of count.values()) {
      if (n !== 1) continue;
      out.push(pos.getX(a), pos.getY(a), pos.getZ(a), pos.getX(b), pos.getY(b), pos.getZ(b));
    }
    const arr = new Float32Array(out);
    this.outlineCache.set(fi, arr);
    return arr;
  }

  private updateOutlines(): void {
    this.disposeLine(this.selLine);
    this.disposeLine(this.hoverLine);
    this.selLine = null;
    this.hoverLine = null;
    if (!this.geoMesh || !this.geoMesh.visible) {
      this.dirty = true;
      return;
    }
    const build = (faces: number[], mat: LineMaterial) => {
      const parts = faces.filter(fi => !this.hidden.has(String(this.faceIds[fi]))).map((fi) => this.faceOutline(fi));
      const n = parts.reduce((s, p) => s + p.length, 0);
      if (!n) return null;
      const all = new Float32Array(n);
      let o = 0;
      for (const p of parts) {
        all.set(p, o);
        o += p.length;
      }
      const lg = new LineSegmentsGeometry();
      lg.setPositions(all);
      const line = new LineSegments2(lg, mat);
      line.renderOrder = 2;
      this.scene.add(line);
      return line;
    };
    const hover = [this.hoverFace, this.externalHover].filter((f) => f >= 0 && !this.selected.has(f));
    this.selLine = build([...this.selected], this.selMat);
    this.hoverLine = build([...new Set(hover)], this.hoverMat);
    this.dirty = true;
  }

  private updateFieldColors(): void {
    if (!this.fieldMesh || !this.field) return;
    const lut = getLut(this.colormap);
    const attr = this.fieldMesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const s = this.field.scalars;
    const [lo, hi] = this.range;
    const span = hi - lo || 1;
    const c = new THREE.Color();
    const n = Math.min(s.length, arr.length / 3);
    for (let i = 0; i < n; i++) {
      const t = Math.min(1, Math.max(0, (s[i] - lo) / span));
      const j = Math.round(t * 255) * 3;
      c.setRGB(lut[j], lut[j + 1], lut[j + 2], THREE.SRGBColorSpace);
      arr[i * 3] = c.r;
      arr[i * 3 + 1] = c.g;
      arr[i * 3 + 2] = c.b;
    }
    attr.needsUpdate = true;
    this.dirty = true;
  }

  private edgeTimer = 0;

  private applyDeform(): void {
    if (!this.fieldMesh || !this.basePositions || !this.field) return;
    const attr = this.fieldMesh.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const d = this.field.displacement;
    const k = this.deformScale;
    if (d && d.length === arr.length && k !== 0) {
      for (let i = 0; i < arr.length; i++) arr[i] = this.basePositions[i] + d[i] * k;
    } else {
      arr.set(this.basePositions);
    }
    attr.needsUpdate = true;
    this.fieldMesh.geometry.computeBoundingSphere();
    this.dirty = true;
    // feature edges are rebuilt lazily (cheap for typical result meshes)
    window.clearTimeout(this.edgeTimer);
    this.edgeTimer = window.setTimeout(() => this.rebuildFieldEdges(), this.fieldEdges ? 60 : 0);
  }

  private rebuildFieldEdges(): void {
    if (this.disposed || !this.fieldMesh) return;
    this.disposeObject(this.fieldEdges);
    this.fieldEdges = null;
    const tris = (this.fieldMesh.geometry.index?.count ?? 0) / 3;
    if (tris > 400_000) return; // too heavy for integrated GPUs; skip outline
    const eg = new THREE.EdgesGeometry(this.fieldMesh.geometry, 30);
    this.fieldEdges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ transparent: true, depthWrite: false }));
    this.scene.add(this.fieldEdges);
    this.applyLineColors();
    this.dirty = true;
  }

  private setHover(fi: number): void {
    if (fi === this.hoverFace) return;
    this.hoverFace = fi;
    this.renderer.domElement.style.cursor = fi >= 0 ? "pointer" : "";
    this.updateGeometryColors();
    this.updateOutlines();
    const id = fi >= 0 ? this.faceIds[fi] : null;
    const label = fi >= 0 ? this.faceLabels[fi] : undefined;
    this.hoverHandlers.forEach((h) => h(id, label));
  }

  private pickAt(clientX: number, clientY: number): number {
    if (!this.geoMesh || !this.geoMesh.visible) return -1;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObject(this.geoMesh, false).filter(hit =>
      hit.faceIndex != null && !this.hidden.has(String(this.faceIds[this.triFace[hit.faceIndex]])));
    // The first surface becomes a translucent shell; the next distinct face is available to pick.
    const first = hits[0];
    const hit = this.through && first ? hits.find(h => this.triFace[h.faceIndex!] !== this.triFace[first.faceIndex!]) ?? first : first;
    if (!hit || hit.faceIndex == null) return -1;
    return this.triFace[hit.faceIndex] ?? -1;
  }

  private onPointerDown = (e: PointerEvent) => {
    this.downAt = e.button === 0 ? { x: e.clientX, y: e.clientY } : null;
    if (e.button === 0 && e.ctrlKey && this.pickingEnabled) {
      e.stopImmediatePropagation();
      this.controls.enabled = false;
      this.renderer.domElement.setPointerCapture(e.pointerId);
      this.boxStart = { x: e.clientX, y: e.clientY, add: e.shiftKey };
      const el = document.createElement('div');
      Object.assign(el.style, { position: 'absolute', pointerEvents: 'none', border: '1px solid var(--focus)',
        background: 'var(--active)', opacity: '.5', zIndex: '3' });
      this.container.appendChild(el);
      this.boxElement = el;
    }
  };

  private onPointerUp = (e: PointerEvent) => {
    const d = this.downAt;
    this.downAt = null;
    const box = this.boxStart;
    if (box) {
      this.boxStart = null;
      this.boxElement?.remove(); this.boxElement = null;
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(e.pointerId)) this.renderer.domElement.releasePointerCapture(e.pointerId);
      if (Math.hypot(e.clientX-box.x, e.clientY-box.y) > 4) {
        this.selectBox(box.x, box.y, e.clientX, e.clientY, box.add);
        return;
      }
    }
    if (!d || e.button !== 0 || !this.pickingEnabled) return;
    if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) return; // it was a drag
    const fi = this.pickAt(e.clientX, e.clientY);
    const id = fi >= 0 ? this.faceIds[fi] : null;
    const label = fi >= 0 ? this.faceLabels[fi] : undefined;
    this.pickHandlers.forEach((h) => h(id, { label, shiftKey: e.shiftKey || e.ctrlKey || e.metaKey }));
  };

  private onPointerMove = (e: PointerEvent) => {
    if (this.boxStart && this.boxElement) {
      const rect = this.container.getBoundingClientRect();
      Object.assign(this.boxElement.style, { left: `${Math.min(e.clientX, this.boxStart.x)-rect.left}px`,
        top: `${Math.min(e.clientY, this.boxStart.y)-rect.top}px`, width: `${Math.abs(e.clientX-this.boxStart.x)}px`,
        height: `${Math.abs(e.clientY-this.boxStart.y)}px` });
      return;
    }
    if (e.buttons !== 0) return; // no hover updates while orbiting
    this.pendingHover = { x: e.clientX, y: e.clientY };
  };

  private boxFaces(x0: number, y0: number, x1: number, y1: number): FaceId[] {
    if (!this.geoMesh) return [];
    const rect = this.renderer.domElement.getBoundingClientRect();
    // Faces with any visible part inside the rectangle. A small depth buffer over the rectangle only (at most
    // 256 cells across) is filled once with every triangle, so the cost is one pass over the mesh. A raycast per
    // triangle was quadratic: 1.6 s for a hidden 6,400-triangle face.
    const pos = this.geoMesh.geometry.getAttribute('position');
    const nrm = this.geoMesh.geometry.getAttribute('normal');
    const mw = this.geoMesh.matrixWorld;
    const nm = new THREE.Matrix3().getNormalMatrix(mw);
    const eye = this.camera.position;
    const pw = new THREE.Vector3(), nw = new THREE.Vector3();
    // back faces out: at silhouettes their depth ties with the front faces and the bottom of a part got selected
    const facingAway = (i: number) => {
      if (!nrm) return false;
      nw.fromBufferAttribute(nrm, i).applyMatrix3(nm);
      pw.fromBufferAttribute(pos, i).applyMatrix4(mw);
      return nw.dot(pw.sub(eye)) > 0;
    };
    const n = pos.count;
    const sx = new Float32Array(n), sy = new Float32Array(n), sz = new Float32Array(n);
    const v = new THREE.Vector3();
    for (let i = 0; i < n; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(mw).project(this.camera);
      sx[i] = rect.left + (v.x + 1) * rect.width / 2;
      sy[i] = rect.top + (1 - v.y) * rect.height / 2;
      sz[i] = v.z;
    }
    const bx0 = Math.min(x0, x1), bx1 = Math.max(x0, x1), by0 = Math.min(y0, y1), by1 = Math.max(y0, y1);
    const cell = Math.max(1, Math.max(bx1 - bx0, by1 - by0) / 256);
    const W = Math.max(1, Math.ceil((bx1 - bx0) / cell)), H = Math.max(1, Math.ceil((by1 - by0) / cell));
    const depth = new Float32Array(W * H).fill(Infinity);
    const owner = new Int32Array(W * H).fill(-1);
    const skip = this.faceIds.map(id => this.hidden.has(String(id)));
    const put = (cx: number, cy: number, z: number, fi: number) => {
      const k = cy * W + cx;
      if (z < depth[k]) { depth[k] = z; owner[k] = fi; }
    };
    for (let t = 0; t < this.triFace.length; t++) {
      const fi = this.triFace[t];
      if (skip[fi]) continue;
      const a = this.originalIndex[t * 3], b = this.originalIndex[t * 3 + 1], c = this.originalIndex[t * 3 + 2];
      const za = sz[a], zb = sz[b], zc = sz[c];
      if (Math.abs(za) > 1 || Math.abs(zb) > 1 || Math.abs(zc) > 1) continue;      // clipped by the camera
      if (facingAway(a) && facingAway(b) && facingAway(c)) continue;
      const xa = sx[a], xb = sx[b], xc = sx[c], ya = sy[a], yb = sy[b], yc = sy[c];
      const cx0 = Math.max(0, Math.floor((Math.min(xa, xb, xc) - bx0) / cell));
      const cx1 = Math.min(W - 1, Math.floor((Math.max(xa, xb, xc) - bx0) / cell));
      const cy0 = Math.max(0, Math.floor((Math.min(ya, yb, yc) - by0) / cell));
      const cy1 = Math.min(H - 1, Math.floor((Math.max(ya, yb, yc) - by0) / cell));
      if (cx0 > cx1 || cy0 > cy1) continue;
      const den = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc);
      if (Math.abs(den) < 1e-12) continue;
      if (cx0 === cx1 && cy0 === cy1) {
        // smaller than a cell: sample its centroid, or tiny faces could never be box-selected
        put(cx0, cy0, (za + zb + zc) / 3, fi);
        continue;
      }
      for (let cy = cy0; cy <= cy1; cy++) {
        const py = by0 + (cy + 0.5) * cell;
        for (let cx = cx0; cx <= cx1; cx++) {
          const px = bx0 + (cx + 0.5) * cell;
          const u = ((yb - yc) * (px - xc) + (xc - xb) * (py - yc)) / den;
          const w = ((yc - ya) * (px - xc) + (xa - xc) * (py - yc)) / den;
          if (u < 0 || w < 0 || u + w > 1) continue;
          put(cx, cy, u * za + w * zb + (1 - u - w) * zc, fi);
        }
      }
    }
    const found = new Set<number>();
    for (const fi of owner) if (fi >= 0) found.add(fi);
    return [...found].map(fi => this.faceIds[fi]);
  }

  private onPointerLeave = () => {
    this.pendingHover = null;
    this.setHover(-1);
  };

  private onPointerCancel = () => {
    this.boxStart = null;
    this.downAt = null;
    this.boxElement?.remove(); this.boxElement = null;
    this.controls.enabled = true;
  };

  private loop = () => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.loop);

    if (this.tween) {
      const tw = this.tween;
      const u = Math.min(1, (performance.now() - tw.t0) / tw.dur);
      // ease-out (matches --ease-out)
      const e = 1 - Math.pow(1 - u, 3);
      this.camera.position.lerpVectors(tw.fromPos, tw.toPos, e);
      this.controls.target.lerpVectors(tw.fromTarget, tw.toTarget, e);
      if (u >= 1) this.tween = null;
      this.dirty = true;
    }
    if (this.capture) return; // a share capture owns the renderer and camera until endCapture
    if (this.controls.update()) this.dirty = true;

    if (this.pendingHover && this.pickingEnabled) {
      const p = this.pendingHover;
      this.pendingHover = null;
      this.setHover(this.pickAt(p.x, p.y));
    }

    if (this.dirty) {
      this.dirty = false;
      if (this.groundOn) {
        // fade the ground out when looking from below it
        const dz = this.camera.position.z - this.groundZ;
        const dist = this.camera.position.distanceTo(this.controls.target) || 1;
        this.ground.material.uniforms.uOpacity.value = THREE.MathUtils.smoothstep(dz / dist, -0.02, 0.15);
      }
      this.renderer.render(this.scene, this.camera);
      this.updateTriad();
      this.cameraHandlers.forEach((h) => h());
    }
  };

  // ---------------------------------------------------------------- triad

  private createTriad(): SVGSVGElement {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "-32 -32 64 64");
    svg.setAttribute("width", "64");
    svg.setAttribute("height", "64");
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "orientation");
    Object.assign(svg.style, {
      position: "absolute",
      top: "8px",
      right: "8px",
      pointerEvents: "none",
      overflow: "visible",
    });
    const dirs: Record<string, [number, number, number]> = {
      x: [1, 0, 0],
      y: [0, 1, 0],
      z: [0, 0, 1],
      "-x": [-1, 0, 0],
      "-y": [0, -1, 0],
      "-z": [0, 0, -1],
    };
    for (const key of ["x", "y", "z", "-x", "-y", "-z"]) {
      const axis = key.replace("-", "") as "x" | "y" | "z";
      const neg = key.startsWith("-");
      const g = document.createElementNS(ns, "g");
      g.dataset.axis = key;
      g.style.pointerEvents = "auto";
      g.style.cursor = "pointer";
      const title = document.createElementNS(ns, "title");
      title.textContent = `${neg ? "−" : "+"}${axis.toUpperCase()}`;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", "0");
      line.setAttribute("y1", "0");
      line.setAttribute("stroke", AXIS_COLORS[axis]);
      line.setAttribute("stroke-width", neg ? "0" : "1.5");
      line.setAttribute("stroke-linecap", "round");
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("r", neg ? "4" : "7.5");
      dot.setAttribute("fill", neg ? "transparent" : AXIS_COLORS[axis]);
      dot.setAttribute("stroke", AXIS_COLORS[axis]);
      dot.setAttribute("stroke-width", neg ? "1.25" : "0");
      g.append(title, line, dot);
      if (!neg) {
        const text = document.createElementNS(ns, "text");
        text.textContent = axis.toUpperCase();
        text.setAttribute("font-size", "10");
        text.setAttribute("font-weight", "600");
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("dominant-baseline", "central");
        text.setAttribute("font-family", "Inter, system-ui, sans-serif");
        text.setAttribute("fill", "#111214");
        text.style.pointerEvents = "none";
        g.append(text);
      }
      g.addEventListener("click", () => this.viewDirection(dirs[key]));
      g.addEventListener("pointerenter", () => dot.setAttribute("opacity", "0.75"));
      g.addEventListener("pointerleave", () => dot.setAttribute("opacity", "1"));
      svg.appendChild(g);
    }
    return svg;
  }

  private updateTriadStyle(): void {
    this.triad?.querySelectorAll("text").forEach((t) => t.setAttribute("fill", "#111214"));
  }

  private updateTriad(): void {
    const q = this.camera.quaternion.clone().invert();
    const items = (["x", "y", "z", "-x", "-y", "-z"] as const)
      .map((k) => {
        const s = k.startsWith("-") ? -1 : 1;
        const a = k.replace("-", "");
        const v = new THREE.Vector3(a === "x" ? s : 0, a === "y" ? s : 0, a === "z" ? s : 0).applyQuaternion(q);
        return [k, v] as const;
      })
      .sort((a, b) => a[1].z - b[1].z);
    for (const [k, v] of items) {
      const g = this.triad.querySelector(`g[data-axis="${k}"]`) as SVGGElement | null;
      if (!g) continue;
      this.triad.appendChild(g); // z-order: back to front
      const x = v.x * 21;
      const y = -v.y * 21;
      const facing = v.z > -0.2;
      const line = g.querySelector("line")!;
      line.setAttribute("x2", (v.x * 14).toFixed(2));
      line.setAttribute("y2", (-v.y * 14).toFixed(2));
      line.setAttribute("opacity", facing ? "1" : "0.5");
      const dot = g.querySelector("circle")!;
      dot.setAttribute("cx", x.toFixed(2));
      dot.setAttribute("cy", y.toFixed(2));
      g.setAttribute("opacity", facing ? "1" : "0.55");
      const text = g.querySelector("text");
      if (text) {
        text.setAttribute("x", x.toFixed(2));
        text.setAttribute("y", y.toFixed(2));
      }
    }
  }

  private disposeLine(obj: LineSegments2 | null): void {
    if (!obj) return;
    this.scene.remove(obj);
    obj.geometry.dispose();
  }

  private disposeObject(obj: THREE.Mesh | THREE.LineSegments | null): void {
    if (!obj) return;
    this.scene.remove(obj);
    obj.geometry.dispose();
    const m = obj.material;
    if (Array.isArray(m)) m.forEach((x) => x.dispose());
    else m.dispose();
  }
}
