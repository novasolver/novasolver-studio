"""What the large-deflection and post-buckling families share: a slender box, its mesh levels and the elastica."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

L0 = 200.0                    # mm, beam length in the solves
E = 200e9                     # Pa
# element size on the loaded long face / the thickness: bending needs the size of the thickness along the beam
LEVELS = {"coarser": 2.0, "standard": 1.0, "finer": 0.5}


def dims(p: dict, scale: float = 1.0) -> dict:
    L = L0 * scale
    t = p["t_over_L"] * L
    return {"L": L, "t": t, "w": p["w_over_t"] * t}


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("beam")
        gmsh.model.occ.addBox(0, 0, 0, d["L"], d["w"], d["t"])
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def face(faces: list[dict], axis: int, sign: int) -> str:
    hit = [f["key"] for f in faces if f.get("normal") and sign * f["normal"][axis] > 0.99]
    assert len(hit) == 1, hit
    return hit[0]


def refine_face(faces: list[dict]) -> str:
    return face(faces, 2, 1)


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["t"]


def second_moment(p: dict, scale: float = 1.0) -> float:
    d = dims(p, scale)
    return d["w"] * d["t"] ** 3 / 12                                # mm^4, about the weak axis


def tip_rows(C, cid: str, p: dict, scale: float, refine_key: str) -> list[dict]:
    """Tip displacement at every converged load step, the middle of the end face."""
    d = dims(p, scale)
    tip = [d["L"], d["w"] / 2, d["t"] / 2]
    rows = []
    for i, row in enumerate(C.get_results(cid, None, "en").get("curve") or [], 1):
        v = C.probe_results(cid, [tip], None, None, None, "en", 1, i)["points"][0]["values"]
        rows.append({"frac": row["load_fraction"], "ux_mm": v["ux"], "uz_mm": v["uz"]})
    return rows


def at(rows: list[dict], frac: float, key: str) -> float:
    """A displacement interpolated at a load fraction; NaN when the run did not get there."""
    for a, b in zip([{"frac": 0.0, "ux_mm": 0.0, "uz_mm": 0.0}] + rows, rows):
        if a["frac"] <= frac <= b["frac"]:
            w = (frac - a["frac"]) / (b["frac"] - a["frac"])
            return a[key] + w * (b[key] - a[key])
    return float("nan")


def _integrate(alpha: float, slope0: float, axial: bool) -> tuple[float, float, float]:
    """theta along s in [0, 1] from a clamped root; returns the end curvature and the two tip displacements / L."""
    def f(_, y):
        th, k, _, _ = y
        return [k, -alpha * (np.sin(th) if axial else np.cos(th)), np.sin(th), np.cos(th)]
    # a transverse dead load acts as M' = -alpha cos(theta); an axial one as M' = -alpha sin(theta)
    y = solve_ivp(f, (0, 1), [0.0, slope0, 0.0, 0.0], rtol=1e-10, atol=1e-12).y[:, -1]
    return y[1], y[2], 1 - y[3]


@lru_cache(maxsize=64)
def cantilever(alpha: float) -> tuple[float, float]:
    """Exact inextensible elastica (Bisshopp and Drucker): F L^2 / E I = alpha -> vertical and horizontal tip travel / L."""
    root = brentq(lambda s: _integrate(alpha, s, False)[0], 1e-6, alpha * 1.01)
    _, delta, short = _integrate(alpha, root, False)
    return delta, short


@lru_cache(maxsize=64)
def column(load_ratio: float) -> tuple[float, float]:
    """Exact elastica of a clamped-free column above its Euler load: P / P_cr -> sideways and shortening / L."""
    assert load_ratio > 1
    alpha = load_ratio * (np.pi / 2) ** 2
    # the first buckled branch: the root curvature grows from 0, and the end curvature first crosses 0 there
    grid = np.linspace(1e-3, 2 * alpha ** 0.5, 400)
    ends = [_integrate(alpha, s, True)[0] for s in grid]
    i = next(j for j in range(len(grid) - 1) if ends[j] * ends[j + 1] < 0)
    root = brentq(lambda s: _integrate(alpha, s, True)[0], grid[i], grid[i + 1])
    _, delta, short = _integrate(alpha, root, True)
    return delta, short
