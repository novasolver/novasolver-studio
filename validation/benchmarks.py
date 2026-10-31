"""Standard benchmarks for the validation manual. Each case builds its own geometry, sets it up through the public
commands (the same ones the app and the MCP tools use), solves, and returns rows of computed vs reference values.
References come from the cited source or are computed here from the closed form, so this file is its own record."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import gmsh
import numpy as np

from novastudio import commands as C
from novastudio import results as R

GEOM = Path(tempfile.mkdtemp(prefix="nsval_"))
CASES: list[dict] = []


def case(id, physics, title, source, tests, slow=False):
    def deco(fn):
        CASES.append({"id": id, "physics": physics, "title": title, "source": source, "tests": tests, "run": fn,
                      "slow": slow})
        return fn
    return deco


def step(name, build):
    gmsh.initialize(["", "-nopopup"])
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)
    build(gmsh.model.occ)
    gmsh.model.occ.synchronize()
    p = GEOM / f"{name}.step"
    gmsh.write(str(p))
    gmsh.finalize()
    return p


def imported(physics, path):
    c = C.import_geometry(physics, path.name, path=str(path), lang="en")["case"]
    return c["case_id"], c


def where(c, pred):
    """Face keys whose centroid (mm) and area (mm2) satisfy pred."""
    return [f["key"] for f in c["geometry"]["faces"] if pred(np.array(f["centroid"]) * 1e3, f["area"] * 1e6)]


def near(c, pt, r=1.0):
    return where(c, lambda x, a: np.linalg.norm(x - np.array(pt, float)) <= r)


def update(cid, ch):
    C.update_case(cid, C.describe_case(cid)["revision"], ch, "en")


def solve(cid, study=True):
    """Mesh study (coarse / normal / fine with GCI) when study, else one run at the case's mesh size."""
    r = C.check_convergence(cid, wait_s=36000, lang="en") if study else C.run_simulation(cid, "preview", wait_s=36000, lang="en")
    res = r.get("results")
    if not res:
        raise RuntimeError(f"no results: {r.get('job')}")
    cards = {c["key"]: c.get("value") for c in res["cards"]}
    conv = res.get("convergence") or {}
    return {"gates": res["gates"], "elements": cards.get("elements") or cards.get("cells"), "study": bool(conv),
            "gci_pass": bool(conv.get("pass")), "gci_pct": conv.get("gci_pct")}


def probe(cid, pts, key):
    return [p["values"][key] for p in C.probe_results(cid, points=pts, lang="en")["points"]]


def row(quantity, computed, reference, unit, tol_pct=None, tol_abs=None):
    err = computed - reference
    rel = err / reference * 100 if reference else None
    ok = abs(err) <= tol_abs if tol_abs is not None else abs(rel) <= tol_pct
    return {"quantity": quantity, "computed": computed, "reference": reference, "unit": unit,
            "error_pct": rel, "error_abs": err, "tol_pct": tol_pct, "tol_abs": tol_abs, "pass": bool(ok)}


T = lambda ja, en, zh: {"ja": ja, "en": en, "zh": zh}


# ---------------------------------------------------------------- structural

@case("nafems-le1", "structural", T("NAFEMS LE1 楕円膜", "NAFEMS LE1 elliptic membrane", "NAFEMS LE1 椭圆膜"),
      "NAFEMS, The Standard NAFEMS Benchmarks, TNSB Rev. 3 (1990), LE1: σyy at D = 92.7 MPa",
      T("曲線境界・対称面・外向き圧力", "curved boundary, symmetry planes, outward pressure", "曲线边界、对称面、向外压力"))
def le1():
    def build(o):
        ring, _ = o.cut([(2, o.addDisk(0, 0, 0, 3250, 2750))], [(2, o.addDisk(0, 0, 0, 2000, 1000))])
        q, _ = o.intersect(ring, [(2, o.addRectangle(0, 0, 0, 4000, 4000))])
        o.extrude(q, 0, 0, 50)                     # half of the 100 mm thickness, z = 0 is a symmetry plane
    cid, c = imported("structural", step("le1", build))
    ch = {"materials.solid.E": "210 GPa", "materials.solid.nu": 0.3}
    for k in near(c, [2625, 0, 25]) + near(c, [0, 1875, 25]) + near(c, [1532, 1381, 0]):
        ch[f"boundaries.{k}.role"] = "symmetry"
    for k in near(c, [2012, 1799, 25], 5):
        ch.update({f"boundaries.{k}.role": "pressure", f"boundaries.{k}.pressure": "-10 MPa"})
    for k in near(c, [1140, 706, 25], 5):
        ch[f"mesh.refine.{k}"] = "20 mm"
    update(cid, ch)
    info = solve(cid)
    v = probe(cid, [[2000.01, 0.01, 0.01]], "syy")[0]
    return info, [row("σyy at D", v, 92.7, "MPa", tol_pct=2)]


@case("nafems-le10", "structural", T("NAFEMS LE10 厚板の曲げ", "NAFEMS LE10 thick plate", "NAFEMS LE10 厚板弯曲"),
      "NAFEMS TNSB Rev. 3, LE10: σyy at D = −5.38 MPa",
      T("3次元の曲げ・成分拘束・対称面", "3D bending, component supports, symmetry planes", "三维弯曲、分量约束、对称面"))
def le10():
    band = 10.0

    def build(o):
        ring, _ = o.cut([(2, o.addDisk(0, 0, 0, 3250, 2750))], [(2, o.addDisk(0, 0, 0, 2000, 1000))])
        q, _ = o.intersect(ring, [(2, o.addRectangle(0, 0, 0, 4000, 4000))])
        o.translate(q, 0, 0, -300)
        h, layers = band / 2, []
        for z0, dz in ((-300, 300 - h), (-h, band), (h, 300 - h)):
            cp = o.copy(q)
            o.translate(cp, 0, 0, z0 + 300)
            layers += [e for e in o.extrude(cp, 0, 0, dz) if e[0] == 3]
        o.remove(q, recursive=True)
        o.fragment(layers[:1], layers[1:])
    cid, c = imported("structural", step("le10", build))
    ch = {"materials.solid.E": "210 GPa", "materials.solid.nu": 0.3}
    for b in C.describe_case(cid).get("body_materials", {}):
        ch.update({f"body_props.{b}.E": "210 GPa", f"body_props.{b}.nu": 0.3})
    for f in c["geometry"]["faces"]:
        if f.get("interface"):
            continue
        x, y, z = (v * 1e3 for v in f["centroid"])
        k = f["key"]
        if abs(x) < 1e-3 or abs(y) < 1e-3:
            ch[f"boundaries.{k}.role"] = "symmetry"
        elif abs(x - 2011.9) < 1 and abs(y - 1799.4) < 1:           # outer face; the middle band also holds z
            ch.update({f"boundaries.{k}.role": "constraint", f"boundaries.{k}.components": "xyz" if abs(z) < 1e-3 else "xy"})
        elif abs(z - 300) < 1e-3:
            ch.update({f"boundaries.{k}.role": "pressure", f"boundaries.{k}.pressure": "1 MPa"})
    update(cid, ch)
    info = solve(cid, study=False)                 # the fine mesh needs more than 16 GB
    v = probe(cid, [[2000.01, 0.01, 299.99]], "syy")[0]
    return info, [row("σyy at D", v, -5.38, "MPa", tol_pct=2)]


@case("lame-cylinder", "structural", T("閉じた厚肉円筒の内圧（Lamé）", "Closed thick cylinder under pressure (Lamé)", "封闭厚壁圆筒内压（Lamé）"),
      "Lamé solution, e.g. Timoshenko & Goodier, Theory of Elasticity, §28",
      T("曲面への圧力・2次要素の曲面追従・1/8対称", "pressure on curved faces, curved quadratic elements, 1/8 symmetry", "曲面压力、二次单元贴合曲面、1/8 对称"))
def lame():
    def build(o):
        shell, _ = o.cut([(3, o.addCylinder(0, 0, 0, 0, 0, 160, 52.5))], [(3, o.addCylinder(0, 0, -1, 0, 0, 151, 50.0))])
        o.intersect(shell, [(3, o.addBox(0, 0, -1, 60, 60, 170))])
    cid, c = imported("structural", step("can8", build))
    ch = {"materials.solid.preset": "steel"}
    for k in near(c, [0, 36.67, 121.67]) + near(c, [36.67, 0, 121.67]) + near(c, [32.63, 32.63, 0]):
        ch[f"boundaries.{k}.role"] = "symmetry"
    for k in near(c, [31.83, 31.83, 75]) + near(c, [21.22, 21.22, 150]):
        ch.update({f"boundaries.{k}.role": "pressure", f"boundaries.{k}.pressure": "1 MPa"})
    update(cid, ch)
    info = solve(cid)
    p, ri, ro, r = 1.0, 50.0, 52.5, 51.25
    A = p * ri ** 2 / (ro ** 2 - ri ** 2)
    hoop, axial = A + A * ro ** 2 / r ** 2, A
    pr = C.probe_results(cid, points=[[r, 0.01, 40]], lang="en")["points"][0]["values"]
    return info, [row("hoop stress, mid wall", pr["syy"], hoop, "MPa", tol_pct=1),
                  row("axial stress, mid wall", pr["szz"], axial, "MPa", tol_pct=1)]


@case("curved-beam", "structural", T("曲がり梁（Winkler–Bach）", "Curved beam (Winkler–Bach)", "曲梁（Winkler–Bach）"),
      "Winkler–Bach curved-beam formula, e.g. Roark's Formulas for Stress and Strain, 8th ed., §9.1",
      T("曲げと軸力の組合せ・曲率による応力の偏り", "combined bending and tension, curvature shifts the stress", "弯曲与轴力组合、曲率导致应力偏移"))
def ring():
    def build(o):
        ann, _ = o.cut([(3, o.addCylinder(0, 0, -10, 0, 0, 20, 40))], [(3, o.addCylinder(0, 0, -10, 0, 0, 20, 20))])
        half, _ = o.cut(ann, [(3, o.addBox(-50, 0, -20, 100, 60, 40))])
        o.fuse(half, [(3, o.addBox(20, 0, -10, 20, 60, 20)), (3, o.addBox(-40, 0, -10, 20, 60, 20))])
    cid, c = imported("structural", step("ring", build))
    fix = min(c["geometry"]["faces"], key=lambda f: np.linalg.norm(np.array(f["centroid"]) * 1e3 - [-30, 60, 0]))["key"]
    load = min(c["geometry"]["faces"], key=lambda f: np.linalg.norm(np.array(f["centroid"]) * 1e3 - [30, 60, 0]))["key"]
    update(cid, {"materials.solid.preset": "steel", f"boundaries.{fix}.role": "fixed", f"boundaries.{load}.role": "load",
                 f"boundaries.{load}.force": "1 kN", f"boundaries.{load}.direction": "+x"})
    info = solve(cid)
    P, ri, ro, b = 1000.0, 20.0, 40.0, 20.0
    h, Rc = ro - ri, (ri + ro) / 2
    Ar, rn = b * h, h / math.log(ro / ri)
    e, M = Rc - rn, P * 90.0
    s_in = P / Ar + M * (rn - ri) / (Ar * e * ri)
    s_out = P / Ar - M * (ro - rn) / (Ar * e * ro)
    v = probe(cid, [[0, -20.05, 0], [0, -39.95, 0]], "sxx")
    return info, [row("inner fibre", v[0], s_in, "MPa", tol_pct=2), row("outer fibre", v[1], s_out, "MPa", tol_pct=2)]


@case("bar-two-materials", "structural", T("鋼とアルミの直列棒", "Steel and aluminium bar in series", "钢铝串联杆"),
      "Hand calculation: u = F/A (L1/E1 + L2/E2)",
      T("部品ごとの材料・成分拘束・部品間の接合面", "per-part materials, component supports, bonded interface", "分部件材料、分量约束、粘接界面"))
def bar2():
    p = step("bar2", lambda o: o.fragment([(3, o.addBox(0, 0, 0, 100, 10, 10))], [(3, o.addBox(100, 0, 0, 100, 10, 10))]))
    cid, c = imported("structural", p)
    ch = {}
    for b, v in C.describe_case(cid)["body_materials"].items():
        ch[f"body_materials.{b}"] = "steel" if v["centroid_mm"][0] < 100 else "aluminium"
    for ax, comp in ((0, "x"), (1, "y"), (2, "z")):
        for k in where(c, lambda x, a, ax=ax: abs(x[ax]) < 1e-6):
            ch.update({f"boundaries.{k}.role": "constraint", f"boundaries.{k}.components": comp})
    for k in where(c, lambda x, a: abs(x[0] - 200) < 1e-6):
        ch.update({f"boundaries.{k}.role": "load", f"boundaries.{k}.force": "10 kN", f"boundaries.{k}.direction": "+x"})
    update(cid, ch)
    info = solve(cid)
    ref = 1e4 / 1e-4 * (0.1 / 205e9 + 0.1 / 69e9) * 1e3
    return info, [row("tip displacement", probe(cid, [[199.99, 5, 5]], "ux")[0], ref, "mm", tol_pct=1)]


@case("thick-sphere", "structural", T("厚肉球の内圧", "Thick sphere under internal pressure", "厚壁球内压"),
      "Lamé solution for a thick sphere, Timoshenko & Goodier §141",
      T("3方向の対称面・曲面の内圧", "three symmetry planes, pressure on a curved inner face", "三个对称面、曲面内压"))
def sphere():
    def build(o):
        sh, _ = o.cut([(3, o.addSphere(0, 0, 0, 100))], [(3, o.addSphere(0, 0, 0, 50))])
        o.intersect(sh, [(3, o.addBox(0, 0, 0, 100, 100, 100))])
    cid, c = imported("structural", step("sphere8", build))
    ch = {"materials.solid.preset": "steel"}
    for ax in range(3):
        for k in where(c, lambda x, a, ax=ax: abs(x[ax]) < 1e-6):
            ch[f"boundaries.{k}.role"] = "symmetry"
    inner = where(c, lambda x, a: abs(a - math.pi * 50 ** 2 / 2) < 0.02 * math.pi * 50 ** 2 / 2)
    ch.update({f"boundaries.{inner[0]}.role": "pressure", f"boundaries.{inner[0]}.pressure": "10 MPa"})
    update(cid, ch)
    info = solve(cid)
    p, a, b, E, nu = 10e6, 0.05, 0.1, 205e9, 0.30
    k = p * a ** 3 / (b ** 3 - a ** 3)
    r = 50.02 / math.sqrt(3)
    pr = C.probe_results(cid, points=[[r, r, r]], lang="en")["points"][0]["values"]
    return info, [row("inner displacement", pr["disp"], k / E * ((1 - 2 * nu) * a + (1 + nu) * b ** 3 / (2 * a ** 2)) * 1e3, "mm", tol_pct=1),
                  row("hoop stress at the bore", pr["s1"], k * (1 + b ** 3 / (2 * a ** 3)) / 1e6, "MPa", tol_pct=3)]


# ---------------------------------------------------------------- thermal

@case("nafems-t4", "thermal", T("NAFEMS T4 対流つき2次元伝熱", "NAFEMS T4 2D conduction with convection", "NAFEMS T4 带对流的二维导热"),
      "NAFEMS TNSB Rev. 3, T4: T at E = 18.3 °C",
      T("温度固定と対流の組合せ", "fixed temperature with convection", "定温与对流组合"))
def t4():
    cid, c = imported("thermal", step("t4", lambda o: o.addBox(0, 0, 0, 600, 1000, 100)))
    ch = {"materials.solid.k": "52 W/mK"}
    for k in near(c, [300, 0, 50]):
        ch.update({f"boundaries.{k}.role": "temperature", f"boundaries.{k}.temperature": "100 degC"})
    for k in near(c, [600, 500, 50]) + near(c, [300, 1000, 50]):
        ch.update({f"boundaries.{k}.role": "convection", f"boundaries.{k}.h": "750 W/m2K", f"boundaries.{k}.tinf": "0 degC"})
    update(cid, ch)
    info = solve(cid)
    return info, [row("T at E", probe(cid, [[599.99, 200, 50]], "temp")[0], 18.3, "°C", tol_pct=1)]


@case("iso10211-1", "thermal", T("ISO 10211 附属書A ケース1", "ISO 10211 Annex A, case 1", "ISO 10211 附录A 案例1"),
      "ISO 10211:2017 Annex A, case 1 (28 grid points; exact series solution)",
      T("建築熱橋計算法の検証（許容 0.1 K）", "thermal-bridge software validation (tolerance 0.1 K)", "建筑热桥计算验证（容差 0.1 K）"))
def iso1():
    cid, c = imported("thermal", step("iso1", lambda o: o.addBox(0, 0, 0, 4000, 8000, 100)))
    ch = {"materials.solid.k": "1 W/mK"}
    for pt, t in (([2000, 8000, 50], "20 degC"), ([0, 4000, 50], "0 degC"), ([2000, 0, 50], "0 degC")):
        for k in near(c, pt):
            ch.update({f"boundaries.{k}.role": "temperature", f"boundaries.{k}.temperature": t})
    update(cid, ch)
    info = solve(cid)

    def exact(x, y, terms=2001):        # full 8 m square, 20 on top, 0 elsewhere; x = 4 is the symmetry line
        s = 0.0
        for n in range(1, terms, 2):
            k = n * math.pi / 8
            s += 80 / (n * math.pi) * math.sin(k * x) * math.exp(k * (y - 8)) * (1 - math.exp(-2 * k * y)) / (1 - math.exp(-16 * k))
        return s
    pts = [(x, y) for y in range(1, 8) for x in range(1, 5)]
    vals = probe(cid, [[x * 1000, y * 1000, 50] for x, y in pts], "temp")
    worst = max(zip(pts, vals), key=lambda t: abs(t[1] - exact(*t[0])))
    return info, [row(f"largest deviation of 28 points (at x {worst[0][0]} m, y {worst[0][1]} m)", worst[1],
                      exact(*worst[0]), "°C", tol_abs=0.1)]


@case("iso10211-2", "thermal", T("ISO 10211 附属書A ケース2（4材料の熱橋）", "ISO 10211 Annex A, case 2 (four materials)", "ISO 10211 附录A 案例2（四种材料热桥）"),
      "ISO 10211:2017 Annex A, case 2: nine temperatures (±0.1 K) and 9.5 W/m (±0.1 W/m)",
      T("複数材料・薄いアルミ部材・表面熱抵抗", "several materials, a thin aluminium profile, surface resistances", "多材料、薄铝型材、表面热阻"))
def iso2():
    D = 2.0

    def build(o):
        o.addBox(0, 0, 41.5, 500, D, 6)
        o.addBox(0, 0, 36.5, 15, D, 5)
        o.fuse([(3, o.addBox(0, 0, 0, 1.5, D, 36.5))], [(3, o.addBox(1.5, 0, 35, 13.5, D, 1.5)), (3, o.addBox(1.5, 0, 0, 498.5, D, 1.5))])
        o.cut([(3, o.addBox(1.5, 0, 1.5, 498.5, D, 40))], [(3, o.addBox(1.5, 0, 35, 13.5, D, 1.5)), (3, o.addBox(0, 0, 36.5, 15, D, 5))])
    cid, c = imported("thermal", step("iso2", build))
    bm = C.describe_case(cid)["body_materials"]
    cen = {b: v["centroid_mm"] for b, v in bm.items()}
    vol = {b: v["volume_mm3"] for b, v in bm.items()}
    at = lambda x, z: min(cen, key=lambda b: (cen[b][0] - x) ** 2 + (cen[b][2] - z) ** 2)
    mats = {at(250, 44.5): ("concrete", "1.15 W/mK"), at(7.5, 39): ("wood", "0.12 W/mK")}
    rest = [b for b in vol if b not in mats]
    mats[max(rest, key=vol.get)] = ("insulation", "0.029 W/mK")
    mats[min(rest, key=vol.get)] = ("aluminium", "230 W/mK")
    ch = {"mesh.size": "fine"}
    for b, (m, k) in mats.items():
        ch.update({f"body_materials.{b}": m, f"body_props.{b}.k": k})
    top = where(c, lambda x, a: abs(x[2] - 47.5) < 1e-6)
    bottom = where(c, lambda x, a: abs(x[2]) < 1e-6)
    for k in top:
        ch.update({f"boundaries.{k}.role": "convection", f"boundaries.{k}.h": "16.6667 W/m2K", f"boundaries.{k}.tinf": "0 degC"})
    for k in bottom:
        ch.update({f"boundaries.{k}.role": "convection", f"boundaries.{k}.h": "9.0909 W/m2K", f"boundaries.{k}.tinf": "20 degC"})
    update(cid, ch)
    info = solve(cid, study=False)                # thin profile: one fine mesh, as ISO allows
    pts = {"A": (0, 47.5, 7.1), "B": (500, 47.5, 0.8), "C": (0, 41.5, 7.9), "D": (15, 41.5, 6.3), "E": (500, 41.5, 0.8),
           "F": (0, 36.5, 16.4), "G": (15, 36.5, 16.3), "H": (0, 0, 16.8), "I": (500, 0, 18.3)}
    eps = 1e-4
    vals = probe(cid, [[min(max(x, eps), 500 - eps), D / 2, min(max(z, eps), 47.5 - eps)] for x, z, _ in pts.values()], "temp")
    rows = [row(f"T at {n}", v, ref, "°C", tol_abs=0.1) for (n, (_, _, ref)), v in zip(pts.items(), vals)]
    m = R.load(cid)[1]["metrics"]
    q = -sum(m["face_flows_w"][k] for k in top) / (D * 1e-3)
    return info, rows + [row("heat flow", q, 9.5, "W/m", tol_abs=0.1)]


@case("layered-wall", "thermal", T("3層の壁", "Three-layer wall", "三层墙"),
      "Hand calculation: series thermal resistances",
      T("部品ごとの熱伝導率・接合面での温度の連続", "per-part conductivity, temperature continuity at interfaces", "分部件导热系数、界面温度连续"))
def wall3():
    def build(o):
        o.fragment([(3, o.addBox(0, 0, 0, 10, 100, 100))], [(3, o.addBox(10, 0, 0, 50, 100, 100)), (3, o.addBox(60, 0, 0, 10, 100, 100))])
    cid, c = imported("thermal", step("wall3", build))
    ch = {}
    for b, v in C.describe_case(cid)["body_materials"].items():
        x = v["centroid_mm"][0]
        m, k = ("concrete", "1.0 W/mK") if x < 10 else ("insulation", "0.04 W/mK") if x < 60 else ("wood", "0.2 W/mK")
        ch.update({f"body_materials.{b}": m, f"body_props.{b}.k": k})
    for k in where(c, lambda x, a: abs(x[0]) < 1e-6):
        ch.update({f"boundaries.{k}.role": "temperature", f"boundaries.{k}.temperature": "20 degC"})
    for k in where(c, lambda x, a: abs(x[0] - 70) < 1e-6):
        ch.update({f"boundaries.{k}.role": "temperature", f"boundaries.{k}.temperature": "0 degC"})
    update(cid, ch)
    info = solve(cid)
    A, Rsum = 0.01, 0.01 / 1.0 + 0.05 / 0.04 + 0.01 / 0.2
    q = 20 * A / Rsum
    v = probe(cid, [[10, 50, 50], [60, 50, 50]], "temp")
    return info, [row("T, first interface", v[0], 20 - q / A * 0.01, "°C", tol_abs=0.05),
                  row("T, second interface", v[1], q / A * 0.01 / 0.2, "°C", tol_abs=0.05),
                  row("heat flow", R.load(cid)[1]["metrics"]["q_in_w"], q, "W", tol_pct=1)]


@case("hollow-cylinder", "thermal", T("円管の半径方向伝熱", "Radial conduction through a tube", "圆管径向导热"),
      "Hand calculation: Q = 2πkLΔT / ln(b/a)",
      T("曲面の温度条件・対数分布", "temperatures on curved faces, logarithmic profile", "曲面温度条件、对数分布"))
def tube():
    p = step("tube", lambda o: o.cut([(3, o.addCylinder(0, 0, 0, 0, 0, 50, 20))], [(3, o.addCylinder(0, 0, -1, 0, 0, 52, 10))]))
    cid, c = imported("thermal", p)
    curved = [f for f in c["geometry"]["faces"] if abs(f["centroid"][2] * 1e3 - 25) < 1e-3]
    inner, outer = min(curved, key=lambda f: f["area"])["key"], max(curved, key=lambda f: f["area"])["key"]
    update(cid, {f"boundaries.{inner}.role": "temperature", f"boundaries.{inner}.temperature": "100 degC",
                 f"boundaries.{outer}.role": "temperature", f"boundaries.{outer}.temperature": "20 degC",
                 "materials.solid.k": "50 W/mK"})
    info = solve(cid)
    Q = 2 * math.pi * 50 * 0.05 * 80 / math.log(2)
    return info, [row("T at r = 15 mm", probe(cid, [[15.0, 0, 25]], "temp")[0], 100 - 80 * math.log(1.5) / math.log(2), "°C", tol_abs=0.05),
                  row("heat flow", R.load(cid)[1]["metrics"]["q_in_w"], Q, "W", tol_pct=1)]


# ---------------------------------------------------------------- flow

def _axis_gradient(cid, z0, z1, length):
    s = C.probe_results(cid, line={"from": [0, 0, 0.01], "to": [0, 0, length - 0.01], "n": 61}, lang="en")["line"]["samples"]
    z = np.array([x["at_mm"][2] for x in s if x["inside"]])
    p = np.array([x["values"]["p"] for x in s if x["inside"]])
    m = (z > z0) & (z < z1)
    return z, p, -np.polyfit(z[m] * 1e-3, p[m], 1)[0]


@case("hagen-poiseuille", "flow", T("円管の層流（Hagen–Poiseuille）", "Laminar pipe flow (Hagen–Poiseuille)", "圆管层流（Hagen–Poiseuille）"),
      "Hagen–Poiseuille: dp/dx = 32 μ U / d²",
      T("内部流れの壁摩擦・圧力勾配", "wall friction and pressure gradient in internal flow", "内部流动的壁面摩擦与压力梯度"), slow=True)
def poiseuille():
    cid, c = imported("flow", step("straw5", lambda o: o.addCylinder(0, 0, 0, 0, 0, 150, 2.5)))
    ch = {}
    for k in near(c, [0, 0, 0]):
        ch.update({f"boundaries.{k}.role": "inlet", f"boundaries.{k}.speed": "0.004 m/s"})
    for k in near(c, [0, 0, 150]):
        ch[f"boundaries.{k}.role"] = "outlet"
    update(cid, ch)
    info = solve(cid)
    mu = 1.0e-6 * 998.0                          # water preset: nu 1.0e-6 m2/s, rho 998 kg/m3
    _, _, g = _axis_gradient(cid, 30, 120, 150)
    return info, [row("pressure gradient, developed flow", g, 32 * mu * 0.004 / 0.005 ** 2, "Pa/m", tol_pct=2)]


@case("sudden-expansion", "flow", T("急拡大管の損失（Borda–Carnot）", "Sudden expansion loss (Borda–Carnot)", "突扩管损失（Borda–Carnot）"),
      "Borda–Carnot: K = (1 − A1/A2)² = 0.5625; turbulent, Re 10,000, k-ω SST",
      T("乱流・はく離と再付着・壁の境界層メッシュ", "turbulence, separation and reattachment, wall layers", "湍流、分离与再附着、壁面边界层网格"), slow=True)
def expansion():
    cid, c = imported("flow", step("expansion", lambda o: o.fuse([(3, o.addCylinder(0, 0, 0, 0, 0, 150, 5))],
                                                                 [(3, o.addCylinder(0, 0, 150, 0, 0, 300, 10))])))
    ch = {}
    for k in near(c, [0, 0, 0]):
        ch.update({f"boundaries.{k}.role": "inlet", f"boundaries.{k}.speed": "1 m/s"})
    for k in near(c, [0, 0, 450]):
        ch[f"boundaries.{k}.role"] = "outlet"
    update(cid, ch)
    r = C.run_simulation(cid, "final", wait_s=36000, lang="en")["results"]
    info = {"gates": r["gates"], "elements": None, "study": False}
    s = C.probe_results(cid, line={"from": [0, 0, 0.01], "to": [0, 0, 449.99], "n": 91}, lang="en")["line"]["samples"]
    z = np.array([x["at_mm"][2] for x in s if x["inside"]])
    p = np.array([x["values"]["p"] for x in s if x["inside"]])
    up, dn = (z > 60) & (z < 140), (z > 330) & (z < 440)
    p1, p2 = np.polyval(np.polyfit(z[up], p[up], 1), 150), np.polyval(np.polyfit(z[dn], p[dn], 1), 150)
    rho = 998.0
    K = ((p1 - p2) + rho / 2 * (1 - 0.25 ** 2)) / (rho / 2)
    return info, [row("loss coefficient K", K, 0.5625, "-", tol_pct=5)]


@case("blasius-pipe", "flow", T("乱流の円管摩擦（Blasius）", "Turbulent pipe friction (Blasius)", "湍流圆管摩擦（Blasius）"),
      "Blasius: f = 0.316 Re^−0.25 (Re 20,000), dp/dx = f/d · ρU²/2",
      T("乱流の壁摩擦（壁関数・境界層メッシュ）", "turbulent wall friction (wall functions, wall layers)", "湍流壁面摩擦（壁函数、边界层网格）"), slow=True)
def blasius():
    cid, c = imported("flow", step("blasius", lambda o: o.addCylinder(0, 0, 0, 0, 0, 500, 5)))
    rho, nu, d = 998.0, 1.0e-6, 0.01              # water preset
    U = 20000 * nu / d
    ch = {}
    for k in near(c, [0, 0, 0]):
        ch.update({f"boundaries.{k}.role": "inlet", f"boundaries.{k}.speed": f"{U:.4f} m/s"})
    for k in near(c, [0, 0, 500]):
        ch[f"boundaries.{k}.role"] = "outlet"
    update(cid, ch)
    r = C.run_simulation(cid, "final", wait_s=36000, lang="en")["results"]
    info = {"gates": r["gates"], "elements": None, "study": False}
    _, _, g = _axis_gradient(cid, 250, 480, 500)
    f = 0.316 * 20000 ** -0.25
    return info, [row("pressure gradient, developed flow", g, f / d * rho * U ** 2 / 2, "Pa/m", tol_pct=10)]
