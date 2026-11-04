"""Family 8: a slender cantilever bent far beyond small deflection by a dead load at its tip.

Exact anchor: the inextensible elastica (Bisshopp and Drucker, 1945). With the load parameter a = F L^2 / (E I), the tip
travels delta/L = 0.3017 down and 0.0566 in at a = 1 (small-deflection theory says 1/3 and 0). One load curve gives every
level at once, so the answers are read at a = 1, 3 and 6. Elastic to any strain here (Green strain, second Piola stress):
a real metal yields first once the surface strain a t / (2 L) passes its yield strain."""
from __future__ import annotations

from beam_common import E, LEVELS, at, cantilever, dims, face, refine_face, refine_length, second_moment, tip_rows, write_step  # noqa: F401

F = 1.0                       # scaled out: the load is set by the shape through a
ALPHAS = (1.0, 3.0, 6.0)
ALPHA_MAX = 6.0
STEPS = 18
CALCULIX = False              # CalculiX is checked on the plastic family; here the exact elastica is the independent answer
GCI_EVERY = 5
PARAMS = {"t_over_L": (0.01, 0.03), "w_over_t": (1.0, 4.0), "nu": (0.25, 0.35)}
QUANTITIES = tuple(f"{k}_{int(a)}" for a in ALPHAS for k in ("delta", "short"))
NORMALISED = {q: f"{q}_over_elastica" for q in QUANTITIES}
EXPECTED_DIRECTIONS = {"delta_1": {"t_over_L": 0}, "delta_6": {"t_over_L": 0}}
CHECK_EQUILIBRIUM = False


def boundary_changes(faces, p, scale=1.0, force=F):
    root, tip = face(faces, 0, -1), face(faces, 0, 1)
    load = ALPHA_MAX * (E / 1e6) * second_moment(p, scale) / dims(p, scale)["L"] ** 2     # N (MPa x mm^4 / mm^2)
    return {f"boundaries.{root}.role": "beam-clamp", f"boundaries.{tip}.role": "load",
            f"boundaries.{tip}.force": f"{load:.8g} N", f"boundaries.{tip}.direction": "-z"}


def extra_changes(p, scale, force):
    return {"physics.analysis": "nonlinear",
            "physics.nonlinear": {"large_deformation": True, "steps": STEPS, "max_iterations": 25}}


def measure(C, cid, p, scale, refine_key):
    return {"curve": tip_rows(C, cid, p, scale, refine_key)}


def nondim(s, p, scale=1.0, force=F):
    L = dims(p, scale)["L"]
    out = {}
    for a in ALPHAS:
        out[f"delta_{int(a)}"] = abs(at(s["curve"], a / ALPHA_MAX, "uz_mm")) / L
        out[f"short_{int(a)}"] = abs(at(s["curve"], a / ALPHA_MAX, "ux_mm")) / L
    return out


def references(p, s, nd):
    out = {}
    for a in ALPHAS:
        delta, short = cantilever(a)
        out[f"delta_{int(a)}_over_elastica"] = nd[f"delta_{int(a)}"] / delta
        out[f"short_{int(a)}_over_elastica"] = nd[f"short_{int(a)}"] / short
    return out


def mirror_err(s):
    return 0.0
