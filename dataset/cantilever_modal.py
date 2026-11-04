"""Family 17: the first natural frequency of a clamped-free box beam (built-in eigenvalue solver).

Anchor: Euler-Bernoulli, f1 = 1.8751^2 / (2 pi L^2) sqrt(E I / (rho A)), with the root simply built in. A stubby beam falls
below it through shear and rotary inertia (Timoshenko) and the fixed root adds a little stiffness: that departure is what
the data adds. The bending is about the weak axis (w > t) so that the first mode stays the same one over the whole space."""
from __future__ import annotations

import math

from beam_common import E, LEVELS, dims, face, refine_face, refine_length, write_step  # noqa: F401

F = 1.0                       # no load in an eigenvalue problem
RHO = 7850.0
CALCULIX = False
GCI_EVERY = 5
PARAMS = {"t_over_L": (0.02, 0.15), "w_over_t": (1.2, 4.0), "nu": (0.2, 0.4)}
QUANTITIES = ("f_star",)
NORMALISED = {"f_star": "f_over_beam"}
EXPECTED_DIRECTIONS = {"f_star": {"t_over_L": 1}}
CHECK_EQUILIBRIUM = False


def boundary_changes(faces, p, scale=1.0, force=F):
    return {f"boundaries.{face(faces, 0, -1)}.role": "fixed"}


def extra_changes(p, scale, force):
    return {"physics.analysis": "modal", "physics.modes": 2, "materials.solid.rho": f"{RHO} kg/m3"}


def measure(C, cid, p, scale, refine_key):
    import core
    return {"f_hz": core.metrics(cid)["frequency_hz"]}


def nondim(s, p, scale=1.0, force=F):
    return {"f_star": s["f_hz"] * dims(p, scale)["L"] * 1e-3 * math.sqrt(RHO / E)}


def references(p, s, nd):
    return {"f_over_beam": nd["f_star"] / (1.8751 ** 2 / (2 * math.pi) * p["t_over_L"] / math.sqrt(12))}


def mirror_err(s):
    return 0.0
