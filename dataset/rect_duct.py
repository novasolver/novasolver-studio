"""Family 16: laminar flow in a straight rectangular duct (OpenFOAM, the whole duct: flow cases have no symmetry role).

The pressure-drop coefficient f Re (Fanning), read from the drop between the two ends. Exact anchor at every point: the
series solution, fitted by Shah and London to 0.05 %: f Re = 24 (1 - 1.3553 a + 1.9467 a^2 - 1.7012 a^3 + 0.9564 a^4 -
0.2537 a^5) with a = short side / long side. The uniform inlet adds an entry drop of about 1.4 q; it is small in a duct
30 hydraulic diameters long at these Reynolds numbers, and it is left in (so the answer rises slightly with Re)."""
from __future__ import annotations

from pathlib import Path

PHYSICS = "flow"
MODE = "final"
H0 = 5.0                      # mm, short side
L_DH = 30.0
NU = 1e-6
RHO = 998.0
F = 1.0
E = 1.0
LEVELS = {"coarser": "coarse", "standard": "normal", "finer": "fine"}
GCI_RATIO = 1.5
GCI_EVERY = 5
CALCULIX = False
EXACT_NORMALISED = True
TIMEOUT_S = 2 * 3600
PARAMS = {"aspect": (1.0, 5.0), "Re": (1.0, 20.0)}                  # long side / short side; on the hydraulic diameter
QUANTITIES = ("fRe",)
NORMALISED = {"fRe": "fRe_over_exact"}
EXPECTED_DIRECTIONS = {"fRe": {"aspect": 1}}
CHECK_EQUILIBRIUM = False


def dims(p, scale=1.0):
    h = H0 * scale
    w = p["aspect"] * h
    dh = 2 * w * h / (w + h)
    return {"h": h, "w": w, "dh": dh, "L": L_DH * dh}


def speed(p, scale=1.0):
    return p["Re"] * NU / (dims(p, scale)["dh"] * 1e-3)


def write_step(p, path: Path, scale=1.0):
    import gmsh
    g = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("duct")
        gmsh.model.occ.addBox(0, 0, 0, g["w"], g["h"], g["L"])
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces):
    return faces[0]["key"]                                          # levels are Studio's mesh sizes


def refine_length(p, scale=1.0):
    return dims(p, scale)["h"]


def boundary_changes(faces, p, scale=1.0, force=F):
    inlet = [f["key"] for f in faces if f.get("normal") and f["normal"][2] < -0.99]
    outlet = [f["key"] for f in faces if f.get("normal") and f["normal"][2] > 0.99]
    assert len(inlet) == 1 and len(outlet) == 1, (inlet, outlet)
    ch = {f"boundaries.{inlet[0]}.role": "inlet", f"boundaries.{inlet[0]}.speed": f"{speed(p, scale):.8g} m/s",
          f"boundaries.{outlet[0]}.role": "outlet"}
    for f in faces:
        if f["key"] not in (inlet[0], outlet[0]):
            ch[f"boundaries.{f['key']}.role"] = "wall"
    return ch


def extra_changes(p, scale, force):
    return {"materials.fluid.preset": "water"}


def measure(C, cid, p, scale, refine_key):
    import core
    m = core.metrics(cid)
    return {k: m.get(k) for k in ("dp_pa", "flow_rate_m3s", "re", "iterations", "max_speed")}


def nondim(s, p, scale=1.0, force=F):
    U = speed(p, scale)
    return {"fRe": abs(s["dp_pa"]) / (0.5 * RHO * U * U) / (4 * L_DH) * p["Re"]}


def exact(p):
    a = 1 / p["aspect"]
    return 24 * (1 - 1.3553 * a + 1.9467 * a ** 2 - 1.7012 * a ** 3 + 0.9564 * a ** 4 - 0.2537 * a ** 5)


def references(p, s, nd):
    return {"fRe_over_exact": nd["fRe"] / exact(p)}


def mirror_err(s):
    return 0.0
