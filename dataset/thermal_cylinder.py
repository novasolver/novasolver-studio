"""Family 19: thermal stress in a thick cylinder whose bore is hotter than its outside, in plane strain (temperature solved
first, then the stress: thermal_load mode "solve").

Exact at every point (Timoshenko and Goodier), with k = b / a, x = r / a and K = 1 / (2 (1 - nu) ln k):
  sigma_t / (E alpha dT) = K (1 - ln(k / x) - (1 + k^2 / x^2) ln k / (k^2 - 1))
  sigma_r / (E alpha dT) = K (  - ln(k / x) - (1 - k^2 / x^2) ln k / (k^2 - 1))
  sigma_z / (E alpha dT) = nu (sigma_r + sigma_t) / (E alpha dT) - T / dT,  T = dT ln(k / x) / ln k above the outside.
The geometry and the quarter-ring model are the pressure cylinder's (family 3)."""
from __future__ import annotations

import math

from thick_cylinder import E, F, PROBE_DEPTH, _hoop, _radius, dims, refine_face, refine_length, write_step  # noqa: F401

ALPHA = 12e-6                 # 1/K
DT = 100.0                    # K, bore above the outside
CALCULIX = False
GCI_EVERY = 5
EXACT_NORMALISED = True
CHECK_EQUILIBRIUM = False
PARAMS = {"b_over_a": (1.1, 3.0), "nu": (0.2, 0.45)}
QUANTITIES = ("hoop_star", "axial_star")
NORMALISED = {"hoop_star": "hoop_over_exact", "axial_star": "axial_over_exact"}
EXPECTED_DIRECTIONS = {}


def boundary_changes(faces, p, scale=1.0, force=F):
    d = dims(p, scale)
    tol = 1e-3 * d["a"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sym = plane(0, 0, -1) + plane(1, 0, -1) + plane(2, 0, -1) + plane(2, d["Lz"], 1)
    assert len(sym) == 4, sym
    cyl = sorted((f for f in faces if f.get("type") == "Cylinder"), key=_radius)
    assert len(cyl) == 2
    ch = {f"boundaries.{k}.role": "symmetry" for k in sym}
    ch.update({f"boundaries.{cyl[0]['key']}.thermal.role": "temperature",
               f"boundaries.{cyl[0]['key']}.thermal.temperature": f"{DT} degC",
               f"boundaries.{cyl[1]['key']}.thermal.role": "temperature",
               f"boundaries.{cyl[1]['key']}.thermal.temperature": "0 degC"})
    return ch


def extra_changes(p, scale, force):
    return {"physics.T_ref": "0 degC", "physics.thermal_load.mode": "solve", "materials.solid.alpha": f"{ALPHA} 1/K"}


def measure(C, cid, p, scale, refine_key):
    d = dims(p, scale)
    r = d["a"] + PROBE_DEPTH * (d["b"] - d["a"])
    angles = [math.radians(x) for x in (45, 20, 70)]
    pts = [[r * math.cos(t), r * math.sin(t), d["Lz"] / 2] for t in angles]
    v = [pt["values"] for pt in C.probe_results(cid, pts, None, None, None, "en", 1, None)["points"]]
    hoop = [_hoop(x, t) for x, t in zip(v, angles)]
    return {"hoop_mpa": hoop[0], "axial_mpa": v[0]["szz"], "hoop_20_70_mpa": hoop[1:]}


def nondim(s, p, scale=1.0, force=F):
    unit = (E / 1e6) * ALPHA * DT
    return {"hoop_star": s["hoop_mpa"] / unit, "axial_star": s["axial_mpa"] / unit}


def exact(p, depth=PROBE_DEPTH):
    k, nu = p["b_over_a"], p["nu"]
    x = 1 + depth * (k - 1)
    K = 1 / (2 * (1 - nu) * math.log(k))
    c = math.log(k) / (k * k - 1)
    st = K * (1 - math.log(k / x) - (1 + k * k / (x * x)) * c)
    sr = K * (-math.log(k / x) - (1 - k * k / (x * x)) * c)
    return {"hoop_star": st, "axial_star": nu * (sr + st) - math.log(k / x) / math.log(k)}


def references(p, s, nd):
    ex = exact(p)
    return {"hoop_over_exact": nd["hoop_star"] / ex["hoop_star"], "axial_over_exact": nd["axial_star"] / ex["axial_star"]}


def mirror_err(s):
    h = s["hoop_20_70_mpa"]
    return abs(h[0] - h[1]) / max(abs(h[0]), 1e-30)
