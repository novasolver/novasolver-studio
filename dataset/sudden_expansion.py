"""Family 17: turbulent flow through a sudden expansion in a round pipe (OpenFOAM k-omega SST with wall functions,
through Studio's internal-flow solver; the whole pipe, flow cases have no symmetry role).

The loss coefficient K = (p1 - p2 + rho (U1^2 - U2^2) / 2) / (rho U1^2 / 2) on the mean speeds, between the inlet of a
small pipe d (3 d long) and the outlet of the big pipe D (8 D long), so it includes the friction of both lengths. Anchor:
Borda-Carnot (1 - beta^2)^2 for the expansion plus smooth-pipe friction (Petukhov) of the two lengths, beta = d / D. That
anchor is itself a textbook model (fully developed flow, mean-speed energy), so the ratio to it is a comparison, not a
check: the error bands here are the numerical (mesh) error of the turbulence model's equations; how far k-omega SST is
from a real pipe is not in them. The inlet profile is uniform (5 % turbulence), as Studio sets it."""
from __future__ import annotations

import math
from pathlib import Path

PHYSICS = "flow"
MODE = "final"
D1 = 20.0                     # mm, small pipe
LU_D = 3.0                    # small-pipe length / d
LD_D = 8.0                    # big-pipe length / D
NU = 1e-6
RHO = 998.0
F = 1.0
E = 1.0
LEVELS = {"coarser": "coarse", "standard": "normal", "finer": "fine"}
GCI_RATIO = 1.4               # cells across the small pipe 7 / 10 / 14 (snappyHexMesh core; the wall layer stays)
GCI_EVERY = 5
CALCULIX = False
TIMEOUT_S = 2 * 3600
PARAMS = {"beta": (0.4, 0.8), "Re": (1.0e4, 1.0e5)}               # d / D; Re on the small pipe
QUANTITIES = ("K",)
NORMALISED = {"K": "K_over_model"}
EXPECTED_DIRECTIONS = {"K": {"beta": -1}}
CHECK_EQUILIBRIUM = False


def dims(p, scale=1.0):
    d = D1 * scale
    D = d / p["beta"]
    return {"d": d, "D": D, "Lu": LU_D * d, "Ld": LD_D * D}


def speed(p, scale=1.0):
    return p["Re"] * NU / (dims(p, scale)["d"] * 1e-3)


def write_step(p, path: Path, scale=1.0):
    import gmsh
    g = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("expansion")
        occ = gmsh.model.occ
        a = occ.addCylinder(0, 0, 0, 0, 0, g["Lu"], g["d"] / 2)
        b = occ.addCylinder(0, 0, g["Lu"], 0, 0, g["Ld"], g["D"] / 2)
        occ.fuse([(3, a)], [(3, b)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces):
    return faces[0]["key"]                                          # levels are Studio's mesh sizes


def refine_length(p, scale=1.0):
    return dims(p, scale)["d"]


def boundary_changes(faces, p, scale=1.0, force=F):
    g = dims(p, scale)
    tol = 1e-3 * g["d"]
    inlet = [f["key"] for f in faces if f.get("normal") and f["normal"][2] < -0.99 and abs(f["centroid_mm"][2]) < tol]
    outlet = [f["key"] for f in faces if f.get("normal") and f["normal"][2] > 0.99
              and abs(f["centroid_mm"][2] - g["Lu"] - g["Ld"]) < tol]
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
    out = {k: m.get(k) for k in ("dp_pa", "dp_nodal_pa", "flow_rate_m3s", "mass_balance", "re", "turbulent", "iterations", "residual",
                                 "solver_cells")}
    out["yplus_avg"] = (m.get("wall_mesh") or {}).get("yplus_avg")
    return out


def nondim(s, p, scale=1.0, force=F):
    q = 0.5 * RHO * speed(p, scale) ** 2
    return {"K": s["dp_pa"] / q + 1 - p["beta"] ** 4}


def friction(re):
    """Darcy factor of a smooth pipe, Petukhov (good to a few % for Re 3e3 - 5e6)."""
    return (0.790 * math.log(re) - 1.64) ** -2


def model(p):
    b = p["beta"]
    return (1 - b * b) ** 2 + friction(p["Re"]) * LU_D + friction(p["Re"] * b) * LD_D * b ** 4


def references(p, s, nd):
    return {"K_over_model": nd["K"] / model(p), "borda_carnot": (1 - p["beta"] ** 2) ** 2}


def mirror_err(s):
    return 0.0
