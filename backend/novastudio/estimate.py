"""Instant answers for standard shapes, looked up from solved points instead of solved anew (milliseconds, no mesh).

Every point in estimate_data/ was solved by Studio and checked (three-mesh study, CalculiX, similarity on subsets; see
dataset/ in the source tree). Between points the answer comes from a Gaussian process on the log of answer / hand formula
(surrogate.Fit, settings learned ahead of time by dataset/flash_hyper.py). Its bar is the larger of the left-out 95th
percentile and the process's own sigma stretched to reach 95 % on left-out points, so it widens where the points are far,
and is added to the mesh error bar of the nearest points. Same method as novasolver.jp/studio/verified/ (explore.js).
Outside the solved ranges it refuses: there is no data there to say how wrong a guess would be."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from .store import StudioError
from .surrogate import NOISE_FLOOR, Fit

DATA = Path(__file__).parent / "estimate_data"
PAGE = "https://novasolver.jp/en/studio/verified/"
DEFAULT_NU = 0.3
CHECKS = ("three-mesh study", "CalculiX comparison", "similarity scaling")


def _lb_stress(x):
    t = x["t_over_L"]
    return 6 * ((t + x["r_over_t"] * t + 1) / 2 - t) / (x["w_over_L"] * t * t)


def _lb_deflection(x):
    t, a, b = x["t_over_L"], x["r_over_t"] * x["t_over_L"], 1 - x["t_over_L"]
    return (b * (b ** 3 - a ** 3) - (b ** 4 - a ** 4) / 4) / (6 * (b - a)) * 12 / (x["w_over_L"] * t ** 3)


def _lame_hoop(x):
    k2 = x["b_over_a"] ** 2
    return (1 + k2) / (k2 - 1)


def _lame_u(x):
    k2 = x["b_over_a"] ** 2
    return (1 + x["nu"]) * ((1 - 2 * x["nu"]) + k2) / (k2 - 1)


def _square_fit(x):
    """The textbook square-section fit 2 pi / ln(1.08 W/d), scaled for a taller block by the walls each side of the hole:
    a hole near a wall conducts like 1/acosh(1 + gap/radius), so moving the top and bottom walls away removes their
    share. Only the normalisation the fit divides out (it bends fast near a square with a big hole)."""
    d, a = x["d_over_W"], x["d_over_W"] / 2
    side, top = math.acosh(1 + (1 - d) / 2 / a), math.acosh(1 + (x["H_over_W"] - d) / 2 / a)
    return 2 * math.pi / math.log(1.08 / d) * (0.5 + 0.5 * side / top)


def _maxwell(x):
    return math.pi * x["d_over_W"] ** 2 / 2


def _round_kt(key):
    return lambda q, I, x: q * 4 * I["F_N"] / (math.pi * I[key] ** 2)


# per shape: what is loaded, the size and load inputs, and per quantity: name, dimensionless symbol, unit, hand formula
# the fit divides out (None = 1), dimensional value from (q, inputs, ratios)
SHAPES = {
    "l_bracket": {
        "title": "L-bracket, back of the upright fixed, F spread evenly over the top of the flange beyond the fillet", "inputs": ("L_mm", "F_N", "E_GPa"),
        "out": (("peak_von_mises_at_fillet", "sigma*L^2/F", "MPa", _lb_stress, lambda q, I, x: q * I["F_N"] / I["L_mm"] ** 2),
                ("tip_deflection", "delta*E*L/F", "mm", _lb_deflection, lambda q, I, x: q * I["F_N"] / (I["E_GPa"] * 1000 * I["L_mm"])))},
    "plate_hole": {
        "title": "Plate with a central hole, tension", "inputs": ("W_mm", "F_N"),
        "out": (("peak_stress_at_hole_midplane", "Kt_net", "MPa", None,
                 lambda q, I, x: q * I["F_N"] / (I["W_mm"] ** 2 * (1 - x["d_over_W"]) * x["t_over_W"])),)},
    "stepped_shaft": {
        "title": "Stepped round shaft, tension", "inputs": ("d_mm", "F_N"),
        "out": (("peak_principal_at_fillet", "Kt", "MPa", None, _round_kt("d_mm")),)},
    "grooved_shaft": {
        "title": "Round bar with a U-groove, tension", "inputs": ("d_mm", "F_N"),
        "out": (("peak_principal_in_groove", "Kt", "MPa", None, _round_kt("d_mm")),)},
    "flat_shoulder": {
        "title": "Flat bar with opposite shoulder fillets, tension", "inputs": ("d_mm", "F_N"),
        "out": (("peak_principal_at_fillet_midthickness", "Kt", "MPa", None,
                 lambda q, I, x: q * I["F_N"] / (I["d_mm"] ** 2 * x["t_over_d"])),)},
    "thick_cylinder": {
        "title": "Thick cylinder, internal pressure, plane strain (ends held axially; open or capped ends differ)", "inputs": ("p_MPa", "a_mm", "E_GPa"),
        "out": (("hoop_stress_at_bore", "sigma_hoop/p", "MPa", _lame_hoop, lambda q, I, x: q * I["p_MPa"]),
                ("radial_displacement_at_bore", "u*E/(p*a)", "mm", _lame_u, lambda q, I, x: q * I["p_MPa"] * I["a_mm"] / (I["E_GPa"] * 1000)))},
    "sphere_cavity": {
        "title": "Round bar with a central spherical cavity, tension", "inputs": ("D_mm", "F_N"),
        "out": (("peak_principal_on_cavity", "Kt", "MPa", None, _round_kt("D_mm")),)},
    "square_hole_thermal": {
        "title": "Heat from a round hole through a long rectangular block (H/W tall) to its outside, steady conduction",
        "inputs": ("length_m", "k_W_mK", "dT_K"),
        "out": (("heat_flow", "q/(k*length*dT)", "W", _square_fit,
                 lambda q, I, x: q * I["k_W_mK"] * I["length_m"] * I["dT_K"]),)},
    "strip_hole_current": {
        "title": "Direct current along a flat busbar with a round hole, possibly off the centre line",
        "inputs": ("W_mm", "t_mm", "sigma_MS_m", "I_A"),
        "out": (("extra_resistance", "dL/W", "uOhm", _maxwell,
                 lambda q, I, x: q * 1e3 / (I["sigma_MS_m"] * I["t_mm"])),
                ("peak_current_density_at_hole", "J_max/J_mean", "A/mm2", None,
                 lambda q, I, x: q * I["I_A"] / (I["W_mm"] * I["t_mm"]))),
    },
}


@lru_cache(maxsize=None)
def _space(shape: str) -> dict:
    d = json.loads((DATA / f"{shape}.json").read_text(encoding="utf-8"))
    names = [p[0] for p in d["params"]]
    lo = np.array([p[1] for p in d["params"]], float)
    hi = np.array([p[2] for p in d["params"]], float)
    pts = d["points"]
    np_ = len(names)
    X = np.array([r[1:1 + np_] for r in pts], float)
    U = (X - lo) / (hi - lo)
    n, dim = U.shape
    xs = [dict(zip(names, row)) for row in X]
    qs = []
    for i, (*_, ref, _f) in enumerate(SHAPES[shape]["out"]):
        y = np.array([r[1 + np_ + 2 * i] for r in pts], float)
        norm = np.array([ref(x) for x in xs]) if ref else np.ones(len(pts))
        qs.append({"y": y, "fit": Fit(U, np.log(y / norm), NOISE_FLOOR, d["gp"][i] if "gp" in d else None),
                   "band": np.array([r[2 + np_ + 2 * i] for r in pts], float)})
    return {"names": names, "lo": lo, "hi": hi, "U": U, "ids": [r[0] for r in pts], "X": X, "checks": [r[-1] for r in pts], "q": qs}


def _number(v, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise StudioError("err.estimate_value", name=name, value=v)
    return float(v)


def ranges(shape: str) -> dict:
    sp = _space(shape)
    return {k: [float(a), float(b)] for k, a, b in zip(sp["names"], sp["lo"], sp["hi"])}


def estimate(shape: str, ratios: dict, size: dict | None = None) -> dict:
    """ratios: the shape's dimensionless ratios (nu may be left out: 0.3). size: its size and load inputs; without them
    only the dimensionless answers come back."""
    if shape not in SHAPES:
        raise StudioError("err.estimate_shape", shape=shape, shapes=", ".join(SHAPES))
    sp, spec = _space(shape), SHAPES[shape]
    span = ", ".join(f"{k} {a:g} to {b:g}" for k, (a, b) in ranges(shape).items())
    unknown = sorted(set(ratios) - set(sp["names"]))
    missing = [k for k in sp["names"] if k not in ratios and k != "nu"]
    if unknown or missing:
        raise StudioError("err.estimate_ratios", shape=shape, names=", ".join(unknown + missing), ranges=span)
    x = {k: _number(ratios.get(k, DEFAULT_NU), k) for k in sp["names"]}
    for k, a, b in zip(sp["names"], sp["lo"], sp["hi"]):
        if not a <= x[k] <= b:
            raise StudioError("err.estimate_range", name=k, value=x[k], lo=float(a), hi=float(b))
    I = None
    if size:
        unknown = sorted(set(size) - set(spec["inputs"]))
        missing = [k for k in spec["inputs"] if k not in size]
        if unknown or missing:
            raise StudioError("err.estimate_size", shape=shape, names=", ".join(unknown + missing), needs=", ".join(spec["inputs"]))
        I = {k: _number(v, k) for k, v in size.items()}
        for k, v in I.items():
            if v <= 0:
                raise StudioError("err.estimate_value", name=k, value=v)
    u = (np.array([x[k] for k in sp["names"]]) - sp["lo"]) / (sp["hi"] - sp["lo"])
    d2 = ((sp["U"] - u) ** 2).sum(1)
    near = np.argsort(d2)[:4]
    w = 1 / (d2[near] + 1e-6)
    exact = float(np.abs(sp["U"][near[0]] - u).max()) < 1e-4
    out = []
    for (name, sym, unit, ref, dim), q in zip(spec["out"], sp["q"]):
        mesh = float(q["band"][near[0]]) if exact else float((w * q["band"][near]).sum() / w.sum())
        mean, bar = (float(q["y"][near[0]]), 0.0) if exact else (float(a[0]) for a in q["fit"].predict(u))
        interp = math.expm1(bar)
        v = mean if exact else math.exp(mean) * (ref(x) if ref else 1.0)
        row = {"name": name, "dimensionless": sym, "dimensionless_value": v, "error_pct": 100 * (mesh + interp),
               "mesh_error_pct": 100 * mesh, "interpolation_error_pct": 100 * interp}
        if I:
            row.update(value=dim(v, I, x), unit=unit)
        out.append(row)
    i = int(near[0])
    ck = sp["checks"][i]
    return {"shape": shape, "title": spec["title"], "ratios": x, "size": I, "results": out, "exact_point": exact,
            "solved_points": len(sp["ids"]),
            "nearest_point": {"id": sp["ids"][i], "ratios": dict(zip(sp["names"], map(float, sp["X"][i]))),
                              "checks": [c for j, c in enumerate(CHECKS) if ck & (1 << j)]},
            "data_page": PAGE}
