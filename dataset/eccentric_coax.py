"""Family 12: the capacitance of a coaxial line whose inner conductor sits off centre.

Exact anchor everywhere in the space: C' = 2 pi eps / arccosh((a^2 + b^2 - e^2) / (2 a b)) for radii a, b and offset e.
The peak field on the inner conductor has an exact form too (bipolar coordinates), the number a designer actually needs:
how much closer to breakdown an off-centre conductor is. Half the section is solved as a slice; the mirror plane and the
ends carry no flux."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "electrostatic"
B0 = 20.0                     # mm, outer radius
SLICE = 4.0                   # mm
VOLT = 1000.0
EPS0 = 8.8541878128e-12
F = 1.0
E = 1.0
LEVELS = {"coarser": 1 / 8, "standard": 1 / 16, "finer": 1 / 32}   # element size on the inner conductor / its radius
MESH_SIZE = "normal"
GCI_EVERY = 5
CALCULIX = False
EXACT_NORMALISED = True
PARAMS = {"a_over_b": (0.1, 0.6), "e_over_gap": (0.0, 0.7)}        # offset / (b - a)
QUANTITIES = ("c_star", "emax_star")
NORMALISED = {"c_star": "c_over_exact", "emax_star": "emax_over_exact"}
EXPECTED_DIRECTIONS = {"c_star": {"a_over_b": 1, "e_over_gap": 1}, "emax_star": {"e_over_gap": 1}}
CHECK_EQUILIBRIUM = False


def dims(p, scale=1.0):
    b = B0 * scale
    a = p["a_over_b"] * b
    return {"a": a, "b": b, "e": p["e_over_gap"] * (b - a), "len": SLICE * scale}


def write_step(p, path: Path, scale=1.0):
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("coax")
        occ = gmsh.model.occ
        outer = occ.addCylinder(0, 0, 0, 0, 0, d["len"], d["b"])
        inner = occ.addCylinder(d["e"], 0, -d["len"], 0, 0, 3 * d["len"], d["a"])
        cut, _ = occ.cut([(3, outer)], [(3, inner)])
        half = occ.addBox(-2 * d["b"], 0, -d["len"], 4 * d["b"], 2 * d["b"], 3 * d["len"])
        occ.intersect(cut, [(3, half)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def cylinders(faces, p, scale):
    d = dims(p, scale)
    cyl = sorted((f for f in faces if f.get("type") == "Cylinder"), key=lambda f: f.get("area_mm2") or f.get("area") or 0)
    assert len(cyl) == 2, [(f["key"], f.get("type")) for f in faces]
    return cyl[0]["key"], cyl[1]["key"]


def refine_face(faces):
    cyl = sorted((f for f in faces if f.get("type") == "Cylinder"), key=lambda f: f.get("area_mm2") or f.get("area") or 0)
    assert len(cyl) == 2
    return cyl[0]["key"]


def refine_length(p, scale=1.0):
    return dims(p, scale)["a"]


def boundary_changes(faces, p, scale=1.0, force=F):
    inner, outer = cylinders(faces, p, scale)
    ch = {f"boundaries.{inner}.role": "voltage", f"boundaries.{inner}.voltage": f"{VOLT} V",
          f"boundaries.{outer}.role": "voltage", f"boundaries.{outer}.voltage": "0 V"}
    for f in faces:
        if f["key"] not in (inner, outer):
            ch[f"boundaries.{f['key']}.role"] = "open"
    return ch


def measure(C, cid, p, scale, refine_key):
    import core
    m = core.metrics(cid)
    return {"energy_j": m["energy_j"], "emax_kv_mm": m["e_max_v_m"] / 1e6}


def extra_changes(p, scale, force):
    return {"materials.solid.preset": "custom", "materials.solid.eps_r": 1.0}


def exact_c(p):
    x = p["a_over_b"]
    e = p["e_over_gap"] * (1 - x)
    return 2 * math.pi / math.acosh((x * x + 1 - e * e) / (2 * x))


def exact_emax(p):
    """Peak field on the inner conductor, at its point nearest the outer wall, over V / (b - a)."""
    x = p["a_over_b"]
    e = p["e_over_gap"] * (1 - x)
    if e < 1e-9:
        return (1 - x) / (x * math.log(1 / x))
    # the two conductors are circles of a bipolar family: the inverse points c1, c2 on the x axis (origin at the outer centre)
    s = (1 + e * e - x * x) / (2 * e)
    h = (s * s - 1) ** 0.5
    c1, c2 = s - h, s + h                                            # inside and outside the outer circle
    rho = lambda t: abs(t - c1) / abs(t - c2)
    outer = rho(1.0)
    inner = rho(e + x)                                               # the near side of the inner conductor
    near = e + x
    dudx = abs(1 / (near - c1) - 1 / (near - c2))                    # |d ln(rho) / dx| on the axis
    return dudx / abs(math.log(inner / outer)) * (1 - x)


def nondim(s, p, scale=1.0, force=F):
    d = dims(p, scale)
    c_per_m = 2 * s["energy_j"] / VOLT ** 2 / (d["len"] * 1e-3) * 2   # half of the section solved
    return {"c_star": c_per_m / EPS0,
            "emax_star": s["emax_kv_mm"] * 1e6 / (VOLT / ((d["b"] - d["a"]) * 1e-3))}


def references(p, s, nd):
    return {"c_over_exact": nd["c_star"] / exact_c(p), "emax_over_exact": nd["emax_star"] / exact_emax(p)}


def mirror_err(s):
    return 0.0
