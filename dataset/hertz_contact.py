"""Family 14: a cylinder pressed on a block (frictionless line contact, plane strain, built-in contact solver).

Exact anchor for a shallow contact on a deep block: Hertz, p0 = sqrt(P' E* / (pi R)), a = sqrt(4 P' R / (pi E*)), with
1/E* = 2 (1 - nu^2) / E. The load is set through a/R. A block of finite depth (h/R, with h fixed at the template's 8 mm)
carries the contact a little differently, which is the part no formula gives. Both bodies share the elastic constants.
The mesh is Studio's own graded contact mesh at its three sizes (element size at the contact = a/5 x 1.6, 1, 0.625)."""
from __future__ import annotations

import math

H0 = 8.0                      # mm, block height of the template
SLAB = 0.5                    # mm, thickness of the plane-strain slab of the template
F = 1.0                       # scaled out: the load is set by a/R
E = 200e9
LEVELS = {"coarser": "coarse", "standard": "normal", "finer": "fine"}
GCI_RATIO = 1.6
GCI_EVERY = 4
SIM_EVERY = 10 ** 9           # sizes are fixed by the template: no similarity pair here, Hertz is the independent answer
CALCULIX = False
CHECK_EQUILIBRIUM = False
PARAMS = {"a_over_R": (0.005, 0.03), "h_over_R": (0.1, 0.4), "nu": (0.2, 0.35)}
QUANTITIES = ("p_over_hertz", "a_over_hertz")
NORMALISED = {"p_over_hertz": "p_over_hertz", "a_over_hertz": "a_over_hertz"}
EXPECTED_DIRECTIONS = {}


def geometry(p):
    R = H0 / p["h_over_R"]
    a = p["a_over_R"] * R
    es = E / 1e6 / (2 * (1 - p["nu"] ** 2))                         # MPa
    per_length = math.pi * es * a * a / (4 * R)                     # N/mm: a^2 = 4 P' R / (pi E*)
    return R, a, per_length, 2 * per_length / (math.pi * a)         # the last is p0 in MPa


def make_case(C, p, level, scale, force):
    R, _, per_length, _ = geometry(p)
    c = C.create_case("hertz-cylinder", None, "en")
    c = c.get("case", c)
    return c, {"geometry.params.radius": f"{R:.8g} mm", "boundaries.load.force": f"{per_length * SLAB / 2:.8g} N",
               "materials.solid.preset": "custom", "materials.solid.E": f"{E / 1e9} GPa", "materials.solid.nu": p["nu"],
               "mesh.size": level}


def measure(C, cid, p, scale, refine_key):
    """Pressure on the block's top nodes. The half-width comes from a fit of the Hertz shape, p^2 = p0^2 (1 - x^2 / a^2):
    the last loaded node alone moves in steps of one element (a/5)."""
    import numpy as np
    from novastudio import results
    jd, _ = results.load(cid, None)
    with np.load(jd / "results.npz") as r, np.load(jd / "mesh.npz") as mesh:
        top = np.unique(mesh["face_block_top"])
        pc, x = r["p_contact"][top], mesh["nodes"][top, 0]
    peak = float(pc.max())
    use = (pc > 0.3 * peak) & (pc < 0.97 * peak)
    slope, icpt = np.polyfit(x[use] ** 2, pc[use] ** 2, 1)
    return {"p0_mpa": peak / 1e6, "a_mm": float((-icpt / slope) ** 0.5) * 1e3, "p0_fit_mpa": float(icpt ** 0.5) / 1e6}


def nondim(s, p, scale=1.0, force=F):
    _, a, _, p0 = geometry(p)
    return {"p_over_hertz": s["p0_mpa"] / p0, "a_over_hertz": s["a_mm"] / a}


def references(p, s, nd):
    return {}


def mirror_err(s):
    return 0.0
