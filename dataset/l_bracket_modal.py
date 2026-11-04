"""Family 21: the first natural frequency of the shelf L-bracket of family 1 (the back of the vertical flange fixed).

Hand anchor: the horizontal flange as a clamped-free beam of length L - t. The vertical flange is held over its whole back,
so it moves little; the corner and a short wide flange are what the ratio to the beam shows. Studio's own mesh sizes set the
levels here: the mode lives in the whole flange, not at the fillet."""
from __future__ import annotations

import math

from l_bracket import E, PARAMS, dims, refine_face, refine_length, write_step  # noqa: F401

F = 1.0
RHO = 7850.0
LEVELS = {"coarser": "coarse", "standard": "normal", "finer": "fine"}
GCI_RATIO = 1.6
GCI_EVERY = 5
CALCULIX = False
CHECK_EQUILIBRIUM = False
QUANTITIES = ("f_star",)
NORMALISED = {"f_star": "f_over_beam"}
EXPECTED_DIRECTIONS = {"f_star": {"t_over_L": 1}}


def boundary_changes(faces, p, scale=1.0, force=F):
    d = dims(p, scale)
    fixed = [f["key"] for f in faces if f.get("normal") and f["normal"][0] < -0.99 and abs(f["centroid_mm"][0]) < 1e-3 * d["L"]]
    assert len(fixed) == 1, fixed
    return {f"boundaries.{fixed[0]}.role": "fixed"}


def extra_changes(p, scale, force):
    return {"physics.analysis": "modal", "physics.modes": 2, "materials.solid.rho": f"{RHO} kg/m3"}


def measure(C, cid, p, scale, refine_key):
    import core
    return {"f_hz": core.metrics(cid)["frequency_hz"]}


def nondim(s, p, scale=1.0, force=F):
    return {"f_star": s["f_hz"] * dims(p, scale)["L"] * 1e-3 * math.sqrt(RHO / E)}


def references(p, s, nd):
    d = dims(p)
    beam = 1.8751 ** 2 / (2 * math.pi) * d["t"] / math.sqrt(12) / (d["L"] - d["t"]) ** 2 * d["L"]
    return {"f_over_beam": nd["f_star"] / beam}


def mirror_err(s):
    return 0.0
