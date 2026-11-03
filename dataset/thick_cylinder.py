"""Family 3: a thick-walled cylinder (bore radius a, outer radius b) under internal pressure, in plane strain.

Lame's solution is exact, so every point of this family is checked against theory, not only a subset: it is the
anchor that proves the solver across the whole range before the families without a closed form are trusted.
  hoop stress at the bore     sigma_t(a) / p = (b^2 + a^2) / (b^2 - a^2)
  radial displacement at a    u(a) E / (p a) = (1 + nu) ((1 - 2 nu) a^2 + b^2) / (b^2 - a^2)
A quarter of a ring of length 0.5 a is solved: symmetry on x = 0 and y = 0, and on both ends (plane strain)."""
from __future__ import annotations

import math
from pathlib import Path

A = 20.0                      # mm, bore radius used in every solve
LZ_OVER_A = 0.5
P0 = 100.0                    # MPa at the nominal "force" F (similarity scales the pressure with force / F)
F = 1000.0
E = 200e9

PARAMS = {
    "b_over_a": (1.1, 3.0),
    "nu": (0.2, 0.45),
}
EXPECTED_DIRECTIONS = {"hoop_star": {"b_over_a": -1, "nu": 0}, "ur_star": {"b_over_a": -1}}
QUANTITIES = ("hoop_star", "ur_star")
NORMALISED = {"hoop_star": "hoop_over_lame", "ur_star": "ur_over_lame"}
EXACT_NORMALISED = True       # NORMALISED divides by the exact answer: every point's difference from it is known
CHECK_EQUILIBRIUM = False      # pressure against symmetry planes: no single reaction to compare with the load


def dims(p: dict, scale: float = 1.0) -> dict:
    a = A * scale
    return {"a": a, "b": p["b_over_a"] * a, "Lz": LZ_OVER_A * a}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("ring")
        occ = gmsh.model.occ
        outer = occ.addCylinder(0, 0, 0, 0, 0, d["Lz"], d["b"])
        inner = occ.addCylinder(0, 0, -d["Lz"], 0, 0, 3 * d["Lz"], d["a"])
        ring, _ = occ.cut([(3, outer)], [(3, inner)])
        box = occ.addBox(0, 0, -d["Lz"], 2 * d["b"], 2 * d["b"], 3 * d["Lz"])
        occ.intersect(ring, [(3, box)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def _radius(f: dict) -> float:
    return math.hypot(f["centroid_mm"][0], f["centroid_mm"][1])


def refine_face(faces: list[dict]) -> str:
    cyl = [f for f in faces if f.get("type") == "Cylinder"]
    assert len(cyl) == 2, [f["key"] for f in cyl]
    return min(cyl, key=_radius)["key"]


def refine_length(p: dict, scale: float = 1.0) -> float:
    d = dims(p, scale)
    return d["b"] - d["a"]                                          # the wall: the stress gradient lives across it


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    d = dims(p, scale)
    tol = 1e-3 * d["a"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sym = plane(0, 0, -1) + plane(1, 0, -1) + plane(2, 0, -1) + plane(2, d["Lz"], 1)
    assert len(sym) == 4, sym
    bore = refine_face(faces)
    ch = {f"boundaries.{k}.role": "symmetry" for k in sym}
    ch.update({f"boundaries.{bore}.role": "pressure", f"boundaries.{bore}.pressure": f"{P0 * force / F:.6g} MPa"})
    return ch


def _hoop(v: dict, phi: float) -> float:
    s, c = math.sin(phi), math.cos(phi)
    return v["sxx"] * s * s + v["syy"] * c * c - 2 * v["sxy"] * s * c


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    """Bore hoop stress and radial displacement at 45 deg (mid-length, 0.2 % of the wall inside), and the bore hoop
    stress at 20 deg and 70 deg: equal in an axisymmetric answer (the 'mirror' check of this family)."""
    d = dims(p, scale)
    r = d["a"] + PROBE_DEPTH * (d["b"] - d["a"])
    angles = [math.radians(x) for x in (45, 20, 70)]
    pts = [[r * math.cos(t), r * math.sin(t), d["Lz"] / 2] for t in angles]
    pr = C.probe_results(cid, pts, None, [refine_key], None, "en", 1, None)
    v = [pt["values"] for pt in pr["points"]]
    hoop = [_hoop(x, t) for x, t in zip(v, angles)]
    return {"bore_hoop_mpa": hoop[0], "bore_ur_mm": (v[0]["ux"] + v[0]["uy"]) / math.sqrt(2),
            "hoop_20_70_mpa": hoop[1:], "bore_inside": sum(pt["inside"] for pt in pr["points"]) / len(pts),
            "bore_face_max_vm_mpa": pr["faces"][0]["max"]["vm"]}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    d = dims(p, scale)
    pr = P0 * force / F
    return {"hoop_star": s["bore_hoop_mpa"] / pr, "ur_star": s["bore_ur_mm"] * (E / 1e6) / (pr * d["a"])}


PROBE_DEPTH = 0.002           # the probe sits this fraction of the wall inside the bore


def lame(p: dict, depth: float = PROBE_DEPTH) -> dict:
    """Exact plane-strain values at r = a + depth (b - a), in the dataset's nondimensional form (at the bore itself
    with depth 0). The probe is a little inside the material, where sigma_t is already ~0.3 % lower at b/a = 2."""
    k, nu = p["b_over_a"], p["nu"]
    x = 1 + depth * (k - 1)                                         # r / a
    c = 1 / (k * k - 1)
    return {"hoop_star": c * (1 + k * k / (x * x)), "ur_star": x * (1 + nu) * c * ((1 - 2 * nu) + k * k / (x * x))}


def references(p: dict, s: dict, nd: dict) -> dict:
    ex = lame(p)
    return {"hoop_over_lame": nd["hoop_star"] / ex["hoop_star"], "ur_over_lame": nd["ur_star"] / ex["ur_star"]}


def mirror_err(s: dict) -> float:
    h = s["hoop_20_70_mpa"]
    return abs(h[0] - h[1]) / max(abs(h[0]), 1e-30)
