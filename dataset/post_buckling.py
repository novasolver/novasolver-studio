"""Family 9: a clamped-free column pushed past its Euler load, where it keeps carrying load while bending far sideways.

Exact anchor: the elastica of the buckled column (Timoshenko): the tip moves sideways delta/L = 0.22 at P/P_cr = 1.015,
0.59 at 1.15 and about 0.81 at 1.52. A straight column under exact load would stay straight in a solver, so the long
face also carries a small sideways load (IMPERFECTION of the axial load, spread along the length), which is the only
departure from the exact problem. Answers are read at P/P_cr = 1.06, 1.2 and 1.5 on one load curve."""
from __future__ import annotations

import math

from beam_common import E, LEVELS, at, column, dims, face, refine_face, refine_length, second_moment, tip_rows, write_step  # noqa: F401

F = 1.0                       # scaled out: the load is set by the shape through P_cr
RATIOS = (1.06, 1.2, 1.5)
RATIO_MAX = 1.6
IMPERFECTION = 0.002
STEPS = 32
CALCULIX = False
GCI_EVERY = 5
PARAMS = {"t_over_L": (0.01, 0.03), "w_over_t": (1.2, 4.0), "nu": (0.25, 0.35)}
QUANTITIES = tuple(f"delta_{int(r * 100)}" for r in RATIOS)
NORMALISED = {q: f"{q}_over_elastica" for q in QUANTITIES}
EXPECTED_DIRECTIONS = {}
CHECK_EQUILIBRIUM = False


def euler(p, scale=1.0):
    return (math.pi / 2) ** 2 * (E / 1e6) * second_moment(p, scale) / dims(p, scale)["L"] ** 2   # N


def boundary_changes(faces, p, scale=1.0, force=F):
    root, tip, top = face(faces, 0, -1), face(faces, 0, 1), face(faces, 2, 1)
    P = RATIO_MAX * euler(p, scale)
    return {f"boundaries.{root}.role": "beam-clamp", f"boundaries.{tip}.role": "load",
            f"boundaries.{tip}.force": f"{P:.8g} N", f"boundaries.{tip}.direction": "-x",
            f"boundaries.{top}.role": "load", f"boundaries.{top}.force": f"{IMPERFECTION * P:.8g} N",
            f"boundaries.{top}.direction": "-z"}


def extra_changes(p, scale, force):
    return {"physics.analysis": "nonlinear",
            "physics.nonlinear": {"large_deformation": True, "steps": STEPS, "max_iterations": 40}}


def measure(C, cid, p, scale, refine_key):
    return {"curve": tip_rows(C, cid, p, scale, refine_key)}


def nondim(s, p, scale=1.0, force=F):
    L = dims(p, scale)["L"]
    return {f"delta_{int(r * 100)}": abs(at(s["curve"], r / RATIO_MAX, "uz_mm")) / L for r in RATIOS}


def references(p, s, nd):
    return {f"delta_{int(r * 100)}_over_elastica": nd[f"delta_{int(r * 100)}"] / column(r)[0] for r in RATIOS}


def mirror_err(s):
    return 0.0
