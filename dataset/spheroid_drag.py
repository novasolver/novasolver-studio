"""Family 15: steady laminar drag of a spheroid aligned with the flow (OpenFOAM through Studio's external-flow solver).

Anchor: for the sphere (length / diameter = 1) the Schiller-Naumann correlation Cd = 24/Re (1 + 0.15 Re^0.687), good to
a few % below Re 800. Slender or flat spheroids have no simple formula over this range, which is the point of the
space. Cd uses the frontal area and Re the equatorial diameter D. Flow solves carry the velocity-field discretisation
error of Studio's mesh, so the bands here are wider than for the solid families."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "external"
MODE = "final"                # OpenFOAM at every level
D0 = 20.0                     # mm, equatorial diameter
NU = 1e-6                     # m2/s (water)
RHO = 998.0                   # kg/m3
F = 1.0
E = 1.0
LEVELS = {"coarser": "coarse", "standard": "normal", "finer": "fine"}   # Studio's external mesh ignores a face size
GCI_RATIO = 1.5               # measured from the cell counts of the three sizes (cube root of the ratio)
GCI_EVERY = 5
CALCULIX = False
TIMEOUT_S = 3 * 3600
PARAMS = {"aspect": (0.5, 2.0), "Re": (2.0, 150.0)}
QUANTITIES = ("cd",)
NORMALISED = {"cd": "cd_over_sn"}
EXPECTED_DIRECTIONS = {"cd": {"Re": -1}}
CHECK_EQUILIBRIUM = False


def dims(p, scale=1.0):
    D = D0 * scale
    return {"D": D, "len": p["aspect"] * D}


def speed(p, scale=1.0):
    return p["Re"] * NU / (dims(p, scale)["D"] * 1e-3)


def write_step(p, path: Path, scale=1.0):
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("spheroid")
        occ = gmsh.model.occ
        s = occ.addSphere(0, 0, 0, d["D"] / 2)
        if abs(p["aspect"] - 1) > 1e-6:
            occ.dilate([(3, s)], 0, 0, 0, p["aspect"], 1, 1)
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces):
    return faces[0]["key"]


def refine_length(p, scale=1.0):
    return dims(p, scale)["D"]


def boundary_changes(faces, p, scale=1.0, force=F):
    return {f"boundaries.{f['key']}.role": "wall" for f in faces}


def extra_changes(p, scale, force):
    return {"flow.speed": f"{speed(p, scale):.8g} m/s", "flow.direction": "+x",
            "materials.fluid.preset": "water"}


def measure(C, cid, p, scale, refine_key):
    import core
    m = core.metrics(cid)
    return {k: m.get(k) for k in ("cd", "drag_n", "re", "iterations", "residual", "converged_iter")}


def nondim(s, p, scale=1.0, force=F):
    d = dims(p, scale)
    U = speed(p, scale)
    area = math.pi * (d["D"] * 1e-3) ** 2 / 4
    return {"cd": abs(s["drag_n"]) / (0.5 * RHO * U * U * area)}


def schiller_naumann(Re):
    return 24 / Re * (1 + 0.15 * Re ** 0.687)


def references(p, s, nd):
    return {"cd_over_sn": nd["cd"] / schiller_naumann(p["Re"]), "cd_studio": s.get("cd")}


def mirror_err(s):
    return 0.0
