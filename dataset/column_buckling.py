"""Family 18: the linear buckling load of a clamped-free box column (built-in eigenvalue solver).

Anchors: Euler, P_cr = (pi / 2)^2 E I / L^2, and Engesser's shear correction, P = P_e / (1 + P_e / (5/6 G A)). The ratio to
Engesser's value is the part of the answer no formula gives (the fixed root, a stubby column). Buckling is about the weak
axis (w > t)."""
from __future__ import annotations

import math

from beam_common import E, LEVELS, dims, face, refine_face, refine_length, second_moment, write_step  # noqa: F401

F = 1000.0                    # N applied: the answer is the load factor x this, whatever it is
CALCULIX = False
GCI_EVERY = 5
PARAMS = {"t_over_L": (0.02, 0.15), "w_over_t": (1.2, 4.0), "nu": (0.2, 0.4)}
QUANTITIES = ("p_star",)
NORMALISED = {"p_star": "p_over_engesser"}
EXPECTED_DIRECTIONS = {"p_star": {"t_over_L": 1}}
CHECK_EQUILIBRIUM = False


def boundary_changes(faces, p, scale=1.0, force=F):
    tip = face(faces, 0, 1)
    return {f"boundaries.{face(faces, 0, -1)}.role": "fixed", f"boundaries.{tip}.role": "load",
            f"boundaries.{tip}.force": f"{force} N", f"boundaries.{tip}.direction": "-x"}


def extra_changes(p, scale, force):
    return {"physics.analysis": "buckling", "physics.modes": 2}


def measure(C, cid, p, scale, refine_key):
    import core
    return {"p_cr_n": core.metrics(cid)["critical_load_n"]}


def nondim(s, p, scale=1.0, force=F):
    """P_cr L^2 / (E I): pi^2 / 4 for a slender column of any size."""
    return {"p_star": s["p_cr_n"] * dims(p, scale)["L"] ** 2 / ((E / 1e6) * second_moment(p, scale))}


def references(p, s, nd):
    d = dims(p)
    euler = (math.pi / 2) ** 2 * (E / 1e6) * second_moment(p) / d["L"] ** 2
    shear = 5 / 6 * (E / 1e6) / (2 * (1 + p["nu"])) * d["w"] * d["t"]
    return {"p_over_euler": s["p_cr_n"] / euler, "p_over_engesser": s["p_cr_n"] * (1 + euler / shear) / euler}


def mirror_err(s):
    return 0.0
