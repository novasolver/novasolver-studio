"""Turn a family's points.jsonl into the published, lightweight tables and the certificate summary.

    python dataset/analyze.py [--family l_bracket] [--out dataset/out/l_bracket]

Writes (all small, plain CSV/JSON so any tool reads them):
  points.csv            one row per point: parameters, nondimensional answers, their error bands and every check
  checks_gci.csv        three-mesh studies (Roache GCI, Richardson extrapolation)
  checks_similarity.csv lengths x2 and force x4: nondimensional answers must not move
  checks_calculix.csv   the same mesh solved by CalculiX
  summary.json          counts, pass rates, error bands, direction checks, file sizes
The answers are the family's QUANTITIES (nondimensional, so one row holds for any size, stiffness and load of the
same shape in linear elasticity)."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FS = 1.25                     # Roache's safety factor for a three-mesh study with a confirmed order
P_MIN, P_MAX = 1.0, 2.0       # tet10: stress converges at order 2 at best; below 1 the extrapolation runs away


def gci3(f1: float, f2: float, f3: float, r: float = 2.0) -> dict:
    """f1 finest, f3 coarsest, constant ratio r. Returns the observed order, the extrapolated value and the error band
    of the *standard* (middle) mesh: FS x |f2 - extrapolated| / |extrapolated|.

    When the observed order is in [P_MIN, 1.25 P_MAX] it is used (held to [P_MIN, P_MAX]). Otherwise it is not
    confirmed: the three values oscillate, or the order is implausible, mostly because a peak read from an
    unstructured mesh carries ~0.5 % of noise that the small fine-pair difference cannot outvote. Then the slowest
    plausible order for tet10 stresses, p = 1, is assumed on the fine pair alone, which doubles the fine-pair
    difference: conservative without letting the coarsest mesh's scatter decide the band (v1 used 3 x the spread of
    all three and reported +-20 % for answers that a 4x finer mesh moved by under 1 %)."""
    e21, e32 = f2 - f1, f3 - f2
    p = math.log(abs(e32 / e21)) / math.log(r) if e21 != 0 and e32 != 0 and e21 * e32 > 0 else None
    confirmed = p is not None and P_MIN <= p <= P_MAX * 1.25
    pu = min(max(p, P_MIN), P_MAX) if confirmed else 1.0
    ext = f1 + (f1 - f2) / (r ** pu - 1)
    return {"order": p, "extrapolated": ext, "err_standard": FS * abs(f2 - ext) / abs(ext),
            "monotone": p is not None, "order_confirmed": confirmed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="l_bracket")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    fam = importlib.import_module(a.family)
    out = Path(a.out or HERE / "out" / a.family)
    rows = [json.loads(l) for l in (out / "points.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = {}
    for r in rows:                                            # a resumed run may have retried a point
        if r["status"] == "ok" or r["id"] not in latest:
            latest[r["id"]] = r
    ok = [r for r in sorted(latest.values(), key=lambda r: r["id"]) if r["status"] == "ok"]
    failed = [r for r in latest.values() if r["status"] != "ok"]
    names = list(fam.PARAMS)
    Q = list(fam.QUANTITIES)
    nd = lambda r, s, scale=1.0, force=None: fam.nondim(s, r["params"], scale, fam.F if force is None else force)

    # ---- three-mesh studies on the nondimensional answers
    gci_rows = []
    for r in ok:
        g = r.get("gci")
        if not g:
            continue
        lv = [nd(r, g["finer"]), nd(r, r["standard"]), nd(r, g["coarser"])]
        row = {"id": r["id"], **r["params"]}
        for q in Q:
            vals = [abs(v[q]) for v in lv]
            st = gci3(*vals, r=getattr(fam, "GCI_RATIO", 2.0))
            row.update({f"{q}_coarser": vals[2], f"{q}_standard": vals[1], f"{q}_finer": vals[0],
                        f"{q}_order": st["order"], f"{q}_extrapolated": st["extrapolated"],
                        f"{q}_monotone": st["monotone"], f"{q}_order_confirmed": st["order_confirmed"],
                        f"{q}_err_standard": st["err_standard"]})
        gci_rows.append(row)

    # ---- error band for every point: the largest standard-mesh error among the 3 nearest studied points (in the
    # unit parameter cube), times 1.25. Conservative and easy to explain; refined when more studies exist.
    lo = np.array([fam.PARAMS[k][0] for k in names])
    hi = np.array([fam.PARAMS[k][1] for k in names])
    unit = lambda p: (np.array([p[k] for k in names]) - lo) / (hi - lo)
    G = np.array([unit(g) for g in gci_rows]) if gci_rows else np.zeros((0, len(names)))

    def band(p: dict, q: str) -> float | None:
        if not len(G):
            return None
        near = np.argsort(np.linalg.norm(G - unit(p), axis=1))[:3]
        return 1.25 * max(gci_rows[i][f"{q}_err_standard"] for i in near)

    # ---- per-point table
    table = []
    for r in ok:
        s = r["standard"]
        v = nd(r, s)
        bands = {f"{q}_band": band(r["params"], q) for q in Q}
        # where the family's own symmetry check measures the same answer twice (e.g. two meridian planes of an
        # axisymmetric part), their disagreement is a direct, per-point measure of the discretisation error
        for q in getattr(fam, "MIRROR_BOUNDS", ()):
            bands[f"{q}_band"] = max(bands[f"{q}_band"] or 0.0, fam.mirror_err(s))
        row = {"id": r["id"], **r["params"], **v, **bands,
               **fam.references(r["params"], s, v),
               "equilibrium_err": (abs(s["reaction_n"] - fam.F) / fam.F
                                   if getattr(fam, "CHECK_EQUILIBRIUM", False) and s.get("reaction_n") is not None else None),
               "mirror_err": fam.mirror_err(s),
               "has_gci": "gci" in r, "has_similarity": "similarity" in r, "has_calculix": "calculix" in r,
               "nodes": s["nodes"], "solve_s": s["wall_s"], "studio": r["studio"]}
        table.append(row)

    # ---- neighbour consistency: leave-one-out prediction from a smooth fit of the other points, made on what is
    # left after the known theory is divided out (fam.NORMALISED: e.g. Kt = stress / nominal stress, deflection /
    # beam theory). The raw answers swing as 1/t^2 or 1/t^3, which a fit cannot follow at the thin edge and would
    # flag good points there. A point far from what its neighbours imply is flagged for a re-solve.
    if len(table) >= 30:
        from scipy.interpolate import RBFInterpolator
        X = np.array([unit(t) for t in table])
        for q in Q:
            y = np.log(np.abs(np.array([t[fam.NORMALISED[q]] for t in table])))
            pred = np.empty_like(y)
            for i in range(len(y)):
                m = np.arange(len(y)) != i
                pred[i] = RBFInterpolator(X[m], y[m], kernel="thin_plate_spline", degree=1, smoothing=1e-6)(X[i:i + 1])[0]
            res = y - pred
            mad = np.median(np.abs(res - np.median(res))) * 1.4826
            for t, e in zip(table, res):
                t[f"{q}_loo_err"] = float(math.expm1(abs(e)))
                t[f"{q}_neighbour_flag"] = bool(abs(e) > max(4 * mad, 0.02))

    # ---- flags followed up by a finer re-solve (recheck.py): resolved when the finer answer is within the band
    rechecks = {}
    if (out / "rechecks.jsonl").exists():
        for line in (out / "rechecks.jsonl").read_text(encoding="utf-8").splitlines():
            x = json.loads(line)
            if "finer" in x:
                rechecks[x["id"]] = x["finer"]
        by_id = {r["id"]: r for r in ok}
        for t in table:
            if t["id"] in rechecks:
                v = nd(by_id[t["id"]], rechecks[t["id"]])
                for q in Q:
                    t[f"{q}_recheck_diff"] = t[q] / v[q] - 1
                    band_q = t[f"{q}_band"] or 0.0
                    t[f"{q}_flag_resolved"] = bool(abs(t[f"{q}_recheck_diff"]) <= band_q)
                    # the stated error can't be smaller than what the finer solve just showed at this very point
                    t[f"{q}_band"] = max(band_q, 1.25 * abs(t[f"{q}_recheck_diff"]))

    # ---- where the exact answer is known at every point, the stated error can't be smaller than the difference from it
    if getattr(fam, "EXACT_NORMALISED", False):
        for t in table:
            for q in Q:
                t[f"{q}_band"] = max(t[f"{q}_band"] or 0.0, 1.25 * abs(t[fam.NORMALISED[q]] - 1))

    # ---- direction checks (the operator's idea: the response must move the physically right way). Judged on the
    # partial slope, the others held: a smooth fit of all points (log space) is differentiated in one parameter at
    # every point. A marginal correlation over the sample is not enough: where the parameters are coupled (a fillet
    # must fit its step) it can come out with the wrong sign for a correct answer. ok = at least 95 % of the points
    # slope the expected way; for "should hardly matter" (0) the median |d ln q / d unit| must be below 0.05.
    directions = {}
    if len(table) >= 30:
        from scipy.interpolate import RBFInterpolator
        from scipy.stats import spearmanr
        X = np.array([unit(t) for t in table])
        for q, signs in getattr(fam, "EXPECTED_DIRECTIONS", {}).items():
            y = np.log(np.abs(np.array([t[q] for t in table])))
            fit = RBFInterpolator(X, y, kernel="thin_plate_spline", degree=1, smoothing=1e-4)
            for k, sign in signs.items():
                j = names.index(k)
                hi_, lo_ = X.copy(), X.copy()
                hi_[:, j] = np.minimum(X[:, j] + 0.05, 1.0)
                lo_[:, j] = np.maximum(X[:, j] - 0.05, 0.0)
                slope = (fit(hi_) - fit(lo_)) / (hi_[:, j] - lo_[:, j])
                # a change across the probe smaller than what the fit misses at left-out points says nothing about the sign
                # (a tall block's height hardly matters: the fit then wiggles either way by 0.2 %, far above the mesh error)
                loo = [t[f"{q}_loo_err"] for t in table if f"{q}_loo_err" in t]
                seen = np.abs(slope) * (hi_[:, j] - lo_[:, j]) > (float(np.percentile(loo, 95)) if loo else 0.0)
                share = float(np.mean(np.sign(slope[seen]) == sign)) if sign and seen.any() else (1.0 if sign else None)
                rho =float(spearmanr([t[k] for t in table], [t[q] for t in table]).statistic)
                directions[f"{q} vs {k}"] = {
                    "expected": sign, "share_expected_sign": None if share is None else round(share, 3),
                    "median_abs_slope": round(float(np.median(np.abs(slope))), 4), "spearman": round(rho, 3),
                    "ok": bool(share >= 0.95) if sign else bool(np.median(np.abs(slope)) < 0.05)}

    # ---- similarity and CalculiX
    sim_rows, ccx_rows = [], []
    for r in ok:
        s0 = nd(r, r["standard"])
        if "similarity" in r:
            s1 = nd(r, r["similarity"], 2.0, fam.F * 4)
            sim_rows.append({"id": r["id"], **{f"{q}{sfx}": val for q in Q for sfx, val in
                             (("", s0[q]), ("_scaled", s1[q]), ("_diff", s1[q] / s0[q] - 1))}})
        c = r.get("calculix")
        if c and "error" not in c:
            s1 = nd(r, c)
            ccx_rows.append({"id": r["id"], **{f"{q}{sfx}": val for q in Q for sfx, val in
                             (("_builtin", s0[q]), ("_calculix", s1[q]), ("_diff", s1[q] / s0[q] - 1))}})

    def write(name, data):
        if not data:
            return
        keys = list(dict.fromkeys(k for d in data for k in d))
        with (out / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for d in data:
                w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in d.items()})

    write("points.csv", table)
    write("checks_gci.csv", gci_rows)
    write("checks_similarity.csv", sim_rows)
    write("checks_calculix.csv", ccx_rows)

    stat = lambda xs: {"median": float(np.median(xs)), "p95": float(np.percentile(xs, 95)), "max": float(np.max(xs))} if len(xs) else None
    ref_keys = [k for k in fam.references(ok[0]["params"], ok[0]["standard"], nd(ok[0], ok[0]["standard"]))] if ok else []
    summary = {
        "family": a.family, "points_ok": len(ok), "points_failed": len(failed),
        "failures": [{"id": r["id"], "error": r.get("error")} for r in failed][:20],
        "params": fam.PARAMS, "quantities": Q,
        "error_band": {q: stat([t[f"{q}_band"] for t in table if t[f"{q}_band"] is not None]) for q in Q},
        "gci_studies": len(gci_rows),
        "gci_order": {q: stat([g[f"{q}_order"] for g in gci_rows if g[f"{q}_order"] is not None]) for q in Q},
        "gci_non_monotone": {q: sum(not g[f"{q}_monotone"] for g in gci_rows) for q in Q},
        "equilibrium_err": stat([t["equilibrium_err"] for t in table if t["equilibrium_err"] is not None]),
        "mirror_err": stat([t["mirror_err"] for t in table]),
        "similarity": {q: stat([abs(s[f"{q}_diff"]) for s in sim_rows]) for q in Q},
        "calculix": {q: stat([abs(s[f"{q}_diff"]) for s in ccx_rows]) for q in Q},
        "references": {k: stat([t[k] for t in table]) for k in ref_keys},
        "neighbour_flags": {q: [t["id"] for t in table if t.get(f"{q}_neighbour_flag")] for q in Q},
        "neighbour_flags_unresolved": {q: [t["id"] for t in table if t.get(f"{q}_neighbour_flag")
                                           and not t.get(f"{q}_flag_resolved")] for q in Q},
        "rechecked": len(rechecks),
        "directions": directions,
        "solve_s": stat([t["solve_s"] for t in table]),
        "studio": sorted({t["studio"] for t in table}),
    }
    summary["files_kb"] = {}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    summary["files_kb"] = {p.name: round(p.stat().st_size / 1024, 1) for p in sorted(out.glob("*.csv"))}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("points_ok", "points_failed", "error_band", "similarity", "calculix",
                                               "references", "neighbour_flags", "directions", "files_kb")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
