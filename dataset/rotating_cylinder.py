"""Family 20: a long hollow cylinder spinning about its axis, in plane strain (body load from physics.rotation).

Exact at every point, with k = b / a, x = r / a, C1 = (3 - 2 nu) / (8 (1 - nu)), C2 = (1 + 2 nu) / (8 (1 - nu)):
  sigma_t / (rho w^2 a^2) = C1 (1 + k^2 + k^2 / x^2) - C2 x^2
  sigma_r / (rho w^2 a^2) = C1 (1 + k^2 - k^2 / x^2 - x^2)
  u_r E / (rho w^2 a^3)   = x (1 + nu) ((1 - nu) sigma_t - nu sigma_r) / (rho w^2 a^2).
The geometry and the quarter-ring model are the pressure cylinder's (family 3)."""
from __future__ import annotations

import math

from thick_cylinder import E, F, PROBE_DEPTH, _hoop, dims, refine_face, refine_length, write_step  # noqa: F401

RHO = 7850.0
RPM = 3000.0                  # at the nominal "force" F: similarity scales the body load with force / F
CALCULIX = False
GCI_EVERY = 5
EXACT_NORMALISED = True
CHECK_EQUILIBRIUM = False
PARAMS = {"b_over_a": (1.1, 3.0), "nu": (0.2, 0.45)}
QUANTITIES = ("hoop_star", "ur_star")
NORMALISED = {"hoop_star": "hoop_over_exact", "ur_star": "ur_over_exact"}
EXPECTED_DIRECTIONS = {"hoop_star": {"b_over_a": 1}}


def rpm(force):
    return RPM * math.sqrt(force / F)


def boundary_changes(faces, p, scale=1.0, force=F):
    d = dims(p, scale)
    tol = 1e-3 * d["a"]
    def plane(axis, value, sign):
        return [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99
                and abs(f["centroid_mm"][axis] - value) < tol]
    sym = plane(0, 0, -1) + plane(1, 0, -1) + plane(2, 0, -1) + plane(2, d["Lz"], 1)
    assert len(sym) == 4, sym
    return {f"boundaries.{k}.role": "symmetry" for k in sym}


def extra_changes(p, scale, force):
    return {"physics.rotation.enabled": True, "physics.rotation.rpm": rpm(force), "physics.rotation.axis": "z",
            "physics.rotation.axis_point": [0.0, 0.0, 0.0], "materials.solid.rho": f"{RHO} kg/m3"}


def measure(C, cid, p, scale, refine_key):
    d = dims(p, scale)
    r = d["a"] + PROBE_DEPTH * (d["b"] - d["a"])
    angles = [math.radians(x) for x in (45, 20, 70)]
    pts = [[r * math.cos(t), r * math.sin(t), d["Lz"] / 2] for t in angles]
    v = [pt["values"] for pt in C.probe_results(cid, pts, None, None, None, "en", 1, None)["points"]]
    hoop = [_hoop(x, t) for x, t in zip(v, angles)]
    return {"hoop_mpa": hoop[0], "ur_mm": (v[0]["ux"] + v[0]["uy"]) / math.sqrt(2), "hoop_20_70_mpa": hoop[1:]}


def unit_mpa(p, scale, force):
    w = rpm(force) * 2 * math.pi / 60
    return RHO * w * w * (dims(p, scale)["a"] * 1e-3) ** 2 / 1e6


def nondim(s, p, scale=1.0, force=F):
    u = unit_mpa(p, scale, force)
    return {"hoop_star": s["hoop_mpa"] / u, "ur_star": s["ur_mm"] / dims(p, scale)["a"] * (E / 1e6) / u}


def exact(p, depth=PROBE_DEPTH):
    k, nu = p["b_over_a"], p["nu"]
    x = 1 + depth * (k - 1)
    c1, c2 = (3 - 2 * nu) / (8 * (1 - nu)), (1 + 2 * nu) / (8 * (1 - nu))
    st = c1 * (1 + k * k + k * k / (x * x)) - c2 * x * x
    sr = c1 * (1 + k * k - k * k / (x * x) - x * x)
    return {"hoop_star": st, "ur_star": x * (1 + nu) * ((1 - nu) * st - nu * sr)}


def references(p, s, nd):
    ex = exact(p)
    return {"hoop_over_exact": nd["hoop_star"] / ex["hoop_star"], "ur_over_exact": nd["ur_star"] / ex["ur_star"]}


def mirror_err(s):
    h = s["hoop_20_70_mpa"]
    return abs(h[0] - h[1]) / max(abs(h[0]), 1e-30)
