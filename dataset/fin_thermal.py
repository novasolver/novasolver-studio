"""Family 10: a straight rectangular fin, base held hot, every other face cooled by convection.

Exact anchor: the one-dimensional fin with a convecting tip, q = sqrt(h P k A) theta_b (sinh mL + (h/mk) cosh mL) /
(cosh mL + (h/mk) sinh mL), m^2 = h P / (k A). It holds while the fin is thin to the heat (small Biot number h t / 2k);
a stubby or strongly cooled fin falls below it, which is what the data shows. Answers: the heat flow over the 1D answer,
and the fin efficiency q / (h A_surface theta_b). Both depend only on the shape and on mL."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "thermal"
L0 = 100.0                    # mm
K = 200.0                     # W/mK
T_BASE, T_AIR = 100.0, 20.0   # degC
F = 1.0                       # no force in this family; similarity keeps mL fixed
E = 1.0
LEVELS = {"coarser": 1.0, "standard": 0.5, "finer": 0.25}       # element size / fin thickness
PARAMS = {"mL": (0.2, 3.0), "t_over_L": (0.05, 0.25), "w_over_t": (1.0, 5.0)}
QUANTITIES = ("q_star", "eta")
NORMALISED = {"q_star": "q_star", "eta": "eta_over_1d"}
EXPECTED_DIRECTIONS = {"eta": {"mL": -1}}
CHECK_EQUILIBRIUM = False
CALCULIX = False
GCI_EVERY = 5


def dims(p, scale=1.0):
    L = L0 * scale
    t = p["t_over_L"] * L
    return {"L": L, "t": t, "w": p["w_over_t"] * t}


def film(p, scale=1.0):
    """h in W/m2K for this mL: m^2 = h P / (k A)."""
    d = dims(p, scale)
    P, A = 2 * (d["w"] + d["t"]) * 1e-3, d["w"] * d["t"] * 1e-6
    return (p["mL"] / (d["L"] * 1e-3)) ** 2 * K * A / P


def write_step(p, path: Path, scale=1.0):
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("fin")
        gmsh.model.occ.addBox(0, 0, 0, d["L"], d["w"], d["t"])
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces):
    hit = [f["key"] for f in faces if f.get("normal") and f["normal"][2] > 0.99]
    assert len(hit) == 1, hit
    return hit[0]


def refine_length(p, scale=1.0):
    return dims(p, scale)["t"]


def boundary_changes(faces, p, scale=1.0, force=F):
    base = [f["key"] for f in faces if f.get("normal") and f["normal"][0] < -0.99]
    assert len(base) == 1 and len(faces) == 6, base
    ch = {f"boundaries.{base[0]}.role": "temperature", f"boundaries.{base[0]}.temperature": f"{T_BASE} degC"}
    h = film(p, scale)
    for f in faces:
        if f["key"] != base[0]:
            ch.update({f"boundaries.{f['key']}.role": "convection", f"boundaries.{f['key']}.h": f"{h:.8g} W/m2K",
                       f"boundaries.{f['key']}.tinf": f"{T_AIR} degC"})
    return ch


def extra_changes(p, scale, force):
    return {"materials.solid.preset": "custom", "materials.solid.k": f"{K} W/mK"}


def measure(C, cid, p, scale, refine_key):
    import core
    return {"q_w": core.metrics(cid)["q_in_w"]}


def q_1d(p, scale=1.0):
    d = dims(p, scale)
    h = film(p, scale)
    L, w, t = d["L"] * 1e-3, d["w"] * 1e-3, d["t"] * 1e-3
    P, A = 2 * (w + t), w * t
    m = (h * P / (K * A)) ** 0.5
    r = h / (m * K)
    return (h * P * K * A) ** 0.5 * (T_BASE - T_AIR) * (math.sinh(m * L) + r * math.cosh(m * L)) / (math.cosh(m * L) + r * math.sinh(m * L))


def nondim(s, p, scale=1.0, force=F):
    d = dims(p, scale)
    area = (2 * (d["w"] + d["t"]) * d["L"] + d["w"] * d["t"]) * 1e-6
    return {"q_star": abs(s["q_w"]) / q_1d(p, scale), "eta": abs(s["q_w"]) / (film(p, scale) * area * (T_BASE - T_AIR))}


def references(p, s, nd):
    d = dims(p)
    return {"biot": film(p) * d["t"] * 1e-3 / (2 * K), "eta_over_1d": nd["q_star"]}


def mirror_err(s):
    return 0.0
