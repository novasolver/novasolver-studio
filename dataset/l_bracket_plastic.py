"""Family 1P: the L-bracket of family 1 in elastic-perfectly-plastic steel (J2, no hardening, small strain).

The plastic correction on top of the linear space. Loads are measured in units of the first-yield load F_y of the
same shape, taken from the certified linear answer (F_y = sy L^2 / sigma*, sigma* = von Mises peak of family 1):
  lam_limit  the collapse load / F_y  (the plastic reserve beyond first yield; the solver stops at collapse)
  amp_15     tip deflection at 1.5 F_y / the linear deflection at the same load (how much plasticity adds)
For an elastic-perfectly-plastic material at small strain both depend only on the shape and nu (not on sy or E), so
one row again holds for any steel grade, size and stiffness. Hand anchor: a rectangular section collapses at 1.5 x its
first-yield moment; with the fillet's concentration the bracket yields earlier, so lam_limit should exceed about 1.5
for slender brackets (beam reference = plastic hinge at the flange root)."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from l_bracket import L, E, F, PARAMS, dims, refine_face, refine_length   # noqa: F401

SY = 250e6                    # Pa (scaled out)
LAM_MAX = 3.2                 # load ramp up to this many first-yield loads; collapse normally ends it earlier
STEPS = 16                    # 0.2 F_y per step
# Elastic-plastic solves factorise the tangent at every iteration: the cost grows much faster than the node count
# (a full bracket at R/8, ~90k unknowns: ~5 min per load step). Hence half the bracket (mirror plane y = W/2) and a
# coarser fillet mesh: a plastic zone smooths the peak, and the collapse load depends on the yielded section, not on
# the elastic peak.
LEVELS = {"coarser": 1 / 2, "standard": 1 / 4, "finer": 1 / 8}
TIMEOUT_S = 4 * 3600          # one load curve at R/8 can take hours next to other solves


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    """Half of family 1's bracket: y in [0, W/2]."""
    import gmsh
    d = dims(p, scale)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("bracket_half")
        occ = gmsh.model.occ
        base = occ.addBox(0, 0, 0, d["L"], d["W"] / 2, d["t"])
        wall = occ.addBox(0, 0, 0, d["t"], d["W"] / 2, d["H"])
        out, _ = occ.fuse([(3, base)], [(3, wall)])
        occ.synchronize()
        tol = 1e-4 * d["L"]
        inner = [e for _, e in gmsh.model.getEntitiesInBoundingBox(d["t"] - tol, -tol, d["t"] - tol,
                                                                     d["t"] + tol, d["W"] / 2 + tol, d["t"] + tol, 1)]
        assert len(inner) == 1, f"inner corner edge not found ({len(inner)})"
        occ.fillet([out[0][1]], inner, [d["R"]])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
QUANTITIES = ("lam_limit", "amp_15")
NORMALISED = {"lam_limit": "lam_over_hinge", "amp_15": "amp_15"}
EXPECTED_DIRECTIONS = {"lam_limit": {"r_over_t": -1}}            # a larger fillet concentrates less: less reserve
CHECK_EQUILIBRIUM = False
# F_y is fixed to the v2 linear answers (fillet stress read 0.5 % of R inside), so later linear rebuilds cannot shift
# the load scale of points already solved; the surface-extrapolated sigma* is about 1 % higher
LINEAR = Path(__file__).resolve().parent / "out" / "l_bracket_v2_probe" / "points.csv"


@lru_cache(maxsize=1)
def _linear() -> list:
    with LINEAR.open(encoding="utf-8") as f:
        return [([float(r[k]) for k in PARAMS], float(r["sigma_star"])) for r in csv.DictReader(f)]


def sigma_star(p: dict) -> float:
    """The linear answer at the same point (the CSV holds 6 significant digits, so match the nearest row)."""
    x = [p[k] for k in PARAMS]
    q, s = min(_linear(), key=lambda row: max(abs(a - b) / abs(b) for a, b in zip(row[0], x)))
    assert max(abs(a - b) / abs(b) for a, b in zip(q, x)) < 1e-4, (x, q)
    return s


def first_yield(p: dict, scale: float = 1.0, force: float = F) -> float:
    """F_y in N for this shape and size (force only rescales the reference used by similarity: F_y is independent)."""
    Lmm = L * scale
    return (SY / 1e6) * Lmm ** 2 / sigma_star(p)


def boundary_changes(faces, p, scale=1.0, force=F):
    """Wall face fixed, top of the horizontal flange loaded with half of LAM_MAX x F_y (half model), mirror plane
    y = W/2 symmetric. force is ignored: plastic answers are in units of F_y."""
    d = dims(p, scale)
    tol = 1e-3 * d["L"]
    fixed = [f["key"] for f in faces if f.get("normal") and f["normal"][0] < -0.99 and abs(f["centroid_mm"][0]) < tol]
    top = [f["key"] for f in faces if f.get("normal") and f["normal"][2] > 0.99
           and abs(f["centroid_mm"][2] - d["t"]) < tol and f["centroid_mm"][0] > d["t"] + d["R"]]
    mirror = [f["key"] for f in faces if f.get("normal") and f["normal"][1] > 0.99
              and abs(f["centroid_mm"][1] - d["W"] / 2) < tol]
    assert len(fixed) == len(top) == len(mirror) == 1, (fixed, top, mirror)
    return {f"boundaries.{fixed[0]}.role": "fixed", f"boundaries.{mirror[0]}.role": "symmetry",
            f"boundaries.{top[0]}.role": "load", f"boundaries.{top[0]}.force": f"{LAM_MAX * first_yield(p, scale) / 2:.6g} N",
            f"boundaries.{top[0]}.direction": "-z"}


def extra_changes(p: dict, scale: float, force: float) -> dict:
    return {"materials.solid.model": "elastoplastic", "materials.solid.sy": f"{SY / 1e6} MPa",
            "materials.solid.H": "0 Pa", "physics.analysis": "nonlinear",
            "physics.nonlinear": {"large_deformation": False, "steps": STEPS, "max_iterations": 25}}


def measure(C, cid: str, p: dict, scale: float, refine_key: str) -> dict:
    d = dims(p, scale)
    res = C.get_results(cid, None, "en")
    curve = res.get("curve") or []
    tip = [d["L"], d["W"] / 2 * 0.999, d["t"]]                    # on the mirror plane (the full bracket's middle)
    rows = []
    for i, row in enumerate(curve, 1):
        pr = C.probe_results(cid, [tip], None, [refine_key], None, "en", 1, i)
        v = pr["points"][0]["values"]
        rows.append({"lam": row["load_fraction"] * LAM_MAX, "tip_uz_mm": v["uz"],
                     "peeq_fillet_max": pr["faces"][0]["max"].get("peeq")})
    return {"curve": rows, "lam_reached": rows[-1]["lam"] if rows else 0.0,
            "collapsed": bool(rows) and rows[-1]["lam"] < LAM_MAX * 0.999}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    """lam_limit = last converged load before collapse (a lower bound within one load increment); amp_15 by linear
    interpolation of the tip deflection at 1.5 F_y over the linear deflection there."""
    rows = s["curve"]
    amp = None
    for a, b in zip(rows, rows[1:]):
        if a["lam"] <= 1.5 <= b["lam"]:
            w = (1.5 - a["lam"]) / (b["lam"] - a["lam"])
            uz = abs(a["tip_uz_mm"] + w * (b["tip_uz_mm"] - a["tip_uz_mm"]))
            # linear deflection at this load: the first step is elastic (lam < 1), scale it
            r0 = rows[0]
            amp = uz / (abs(r0["tip_uz_mm"]) * 1.5 / r0["lam"])
            break
    return {"lam_limit": s["lam_reached"] if s["collapsed"] else float("nan"), "amp_15": amp if amp else float("nan")}


def hinge_lambda(p: dict) -> float:
    """Plastic hinge where the fillet ends (x = t + R: the thinnest section nearest the wall), M_p = sy W t^2 / 4,
    raised by 2 / sqrt(3) for a wide flange (plane strain across the width), against the load centroid; in units of
    F_y. A hand reference (shear, narrow flanges and hinges elsewhere are not in it). The first trial point (id 0,
    W/t = 12) collapsed at 2.05 F_y; this gives 2.01, while a hinge at the root in plane stress gives 1.57."""
    d = dims(p)
    lever = (d["L"] - d["t"] - d["R"]) / 2
    Fp = (2 / 3 ** 0.5) * (SY / 1e6) * d["W"] * d["t"] ** 2 / 4 / lever
    return Fp / first_yield(p)


def references(p: dict, s: dict, nd: dict) -> dict:
    return {"lam_over_hinge": nd["lam_limit"] / hinge_lambda(p), "hinge_lambda": hinge_lambda(p),
            "steps": len(s["curve"])}


def mirror_err(s: dict) -> float:
    return 0.0                                                      # mirror points are not probed per step
