"""Thin-plate spline (what NovaSolver Flash uses) against Gaussian processes on one solved family. Measurement only.

    python dataset/compare_surrogates.py l_bracket

Every hyperparameter is learned from the training split alone, and the spline also gets a tuned version, so the GP does
not win by being the only model that was tuned. Each fit is scored twice: on answer / hand formula, and on the raw
answer, because a surrogate built from a user's own case has no hand formula to divide out.

Experiments: repeated 10-fold CV, learning curve (few solves), block hold-out (a slab at each end of each range, the
nearest thing to extrapolating inside the box). Writes dataset/out/<family>/surrogate_compare.json and prints tables."""
from __future__ import annotations

import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from novastudio.estimate import DATA, SHAPES  # noqa: E402

MODELS = ("tps", "tps_ard", "gp_m52_ard", "gp_rbf_ard")   # first run also had tps_tuned (same as tps) and gp_m52_iso (worse)
TARGETS = ("norm", "raw")
CURVE_N = (30, 60, 100, 150, 225)
CURVE_REPEATS = 10
CV_REPEATS, CV_FOLDS = 3, 10
BLOCK_FRACTION = 0.15
NOISE_FLOOR = 3e-5              # the data keep 5 significant figures: rounding alone is about this much in log units
EDGE = 0.10                     # a point counts as near the edge when any ratio is within 10 % of its range end


def load(family: str) -> dict:
    d = json.loads((DATA / f"{family}.json").read_text(encoding="utf-8"))
    names = [p[0] for p in d["params"]]
    lo, hi = np.array([p[1] for p in d["params"]], float), np.array([p[2] for p in d["params"]], float)
    pts, p = d["points"], len(names)
    X = np.array([r[1:1 + p] for r in pts], float)
    out = []
    for i, (name, _sym, _unit, ref, _dim) in enumerate(SHAPES[family]["out"]):
        y = np.array([r[1 + p + 2 * i] for r in pts], float)
        band = np.array([r[2 + p + 2 * i] for r in pts], float)
        norm = np.array([ref(dict(zip(names, row))) for row in X]) if ref else np.ones(len(X))
        out.append({"name": name, "has_ref": ref is not None, "y": {"norm": np.log(y / norm), "raw": np.log(y)}, "band": band})
    return {"names": names, "U": (X - lo) / (hi - lo), "q": out}


# ---- spline, as in novastudio/estimate.py
def tps_kernel(r2):
    return 0.5 * r2 * np.log(np.where(r2 > 0, r2, 1.0))


class TPS:
    def __init__(self, tuned: bool):
        self.tuned = tuned

    def _solve(self, U, y, lam):
        n, dim = U.shape
        M = np.zeros((n + dim + 1, n + dim + 1))
        M[:n, :n] = tps_kernel(((U[:, None, :] - U[None, :, :]) ** 2).sum(-1)) + lam * np.eye(n)
        M[:n, n] = M[n, :n] = 1
        M[:n, n + 1:] = U
        M[n + 1:, :n] = U.T
        Mi = np.linalg.inv(M)
        c = Mi[:, :n] @ y
        return c, np.abs(c[:n] / np.diag(Mi)[:n])      # Rippa: left-out residuals

    def fit(self, U, y):
        grid = 10.0 ** np.arange(-8, 0) if self.tuned else [1e-6]
        best = None
        for lam in grid:
            c, loo = self._solve(U, y, lam)
            score = float(np.sqrt((loo ** 2).mean()))
            if best is None or score < best[0]:
                best = (score, lam, c, loo)
        _, self.lam, self.c, loo = best
        self.U = U
        self.half = float(np.sort(loo)[min(len(y) - 1, int(0.95 * len(y)))])
        return self

    def predict(self, Us):
        n, dim = self.U.shape
        r2 = ((Us[:, None, :] - self.U[None, :, :]) ** 2).sum(-1)
        m = tps_kernel(r2) @ self.c[:n] + self.c[n] + Us @ self.c[n + 1:n + 1 + dim]
        return m, np.full(len(Us), self.half), np.full(len(Us), self.half), np.full(len(Us), self.half)

    def info(self):
        return {"lam": float(self.lam), "loo_p95": self.half}


class ScaledTPS(TPS):
    """The same spline on coordinates stretched by a GP's learned length scales: is direction all the GP adds?"""

    def __init__(self):
        super().__init__(True)

    def fit(self, U, y):
        self.ell = GP("m52", True, starts=(0.7,)).fit(U, y).ell
        return super().fit(U / self.ell, y)

    def predict(self, Us):
        return super().predict(Us / self.ell)

    def info(self):
        return {**super().info(), "lengthscales": [float(v) for v in self.ell]}


# ---- Gaussian process: linear trend (the spline has one too), then a stationary kernel with a learned nugget
class GP:
    def __init__(self, kernel: str, ard: bool, starts=(0.7, 2.5)):
        self.kernel, self.ard, self.starts = kernel, ard, starts

    def _shape(self, r2):
        """k(r), and the factor f with dk/dlog(l_d) = f * (delta_d / l_d)^2."""
        if self.kernel == "rbf":
            k = np.exp(-0.5 * r2)
            return k, k
        r = np.sqrt(r2)
        e = np.exp(-np.sqrt(5) * r)
        return (1 + np.sqrt(5) * r + 5 * r2 / 3) * e, (5 / 3) * (1 + np.sqrt(5) * r) * e

    def _unpack(self, th, dim):
        return (np.exp(th[:dim]) if self.ard else np.full(dim, np.exp(th[0]))), np.exp(th[-2]), np.exp(th[-1])

    def _nll(self, th, D2, y):
        n, dim = len(y), D2.shape[-1]
        ell, sf, sn = self._unpack(th, dim)
        S = D2 / ell ** 2
        k, f = self._shape(S.sum(-1))
        K = sf ** 2 * k + sn ** 2 * np.eye(n)
        try:
            cf = cho_factor(K, lower=True, check_finite=False)
        except np.linalg.LinAlgError:
            return 1e25, np.zeros_like(th)
        a = cho_solve(cf, y, check_finite=False)
        nll = 0.5 * y @ a + np.log(np.diag(cf[0])).sum() + 0.5 * n * np.log(2 * np.pi)
        W = cho_solve(cf, np.eye(n), check_finite=False) - np.outer(a, a)
        g = np.zeros_like(th)
        fS = sf ** 2 * f
        if self.ard:
            for d in range(dim):
                g[d] = 0.5 * (W * (fS * S[..., d])).sum()
        else:
            g[0] = 0.5 * (W * (fS * S.sum(-1))).sum()
        g[-2] = (W * (sf ** 2 * k)).sum()
        g[-1] = sn ** 2 * np.trace(W)
        return nll, g

    def fit(self, U, y):
        n, dim = U.shape
        A = np.c_[np.ones(n), U]
        self.beta = np.linalg.lstsq(A, y, rcond=None)[0]
        res = y - A @ self.beta
        self.scale = float(res.std()) or 1.0
        z = res / self.scale
        D2 = (U[:, None, :] - U[None, :, :]) ** 2
        nl = dim if self.ard else 1
        bounds = [(np.log(0.03), np.log(30))] * nl + [(np.log(1e-2), np.log(30)), (min(np.log(NOISE_FLOOR / self.scale), np.log(0.5)), np.log(1.0))]
        best = None
        for s in self.starts:
            r = minimize(self._nll, np.r_[np.full(nl, np.log(s)), 0.0, np.log(0.05)], args=(D2, z), jac=True,
                         method="L-BFGS-B", bounds=bounds, options={"maxiter": 200})
            if best is None or r.fun < best.fun:
                best = r
        self.th = best.x
        self.ell, self.sf, self.sn = self._unpack(self.th, dim)
        k, _ = self._shape((D2 / self.ell ** 2).sum(-1))
        K = self.sf ** 2 * k + self.sn ** 2 * np.eye(n)
        self.cf = cho_factor(K, lower=True, check_finite=False)
        self.Ki = cho_solve(self.cf, np.eye(n), check_finite=False)
        self.a = cho_solve(self.cf, z, check_finite=False)
        # the GP's own left-out residuals in units of its predicted sigma: how far to stretch the bar to reach 95 %
        d = np.diag(self.Ki)
        rat = np.abs(self.a / d) * np.sqrt(d)
        self.stretch = float(np.sort(rat)[min(n - 1, int(0.95 * n))])
        loo = self.scale * np.abs(self.a / d)
        self.loo_rmse = float(np.sqrt((loo ** 2).mean()))
        self.half = float(np.sort(loo)[min(n - 1, int(0.95 * n))])   # Flash's own rule: one bar from left-out residuals
        self.U = U
        return self

    def predict(self, Us):
        r2 = (((Us[:, None, :] - self.U[None, :, :]) / self.ell) ** 2).sum(-1)
        ks = self.sf ** 2 * self._shape(r2)[0]
        m = ks @ self.a * self.scale + np.c_[np.ones(len(Us)), Us] @ self.beta
        v = self.sf ** 2 + self.sn ** 2 - (ks * cho_solve(self.cf, ks.T, check_finite=False).T).sum(1)
        s = self.scale * np.sqrt(np.maximum(v, self.sn ** 2))
        return m, 1.96 * s, self.stretch * s, np.full(len(Us), self.half)

    def info(self):
        return {"lengthscales": [float(v) for v in self.ell], "signal": float(self.sf * self.scale),
                "noise": float(self.sn * self.scale), "stretch_95": self.stretch, "loo_rmse": self.loo_rmse, "loo_p95": self.half}


def make(model: str):
    return {"tps": lambda: TPS(False), "tps_tuned": lambda: TPS(True), "tps_ard": ScaledTPS, "gp_m52_ard": lambda: GP("m52", True),
            "gp_m52_iso": lambda: GP("m52", False), "gp_rbf_ard": lambda: GP("rbf", True)}[model]()


_D = None


def _task(a):
    global _D
    family, model, qi, target, exp, key, tr, te = a
    if _D is None:
        _D = load(family)
    U, y = _D["U"], _D["q"][qi]["y"][target]
    t0 = time.perf_counter()
    m = make(model).fit(U[tr], y[tr])
    t1 = time.perf_counter()
    p, bar, bar2, bar3 = m.predict(U[te])
    return {"model": model, "qi": qi, "target": target, "exp": exp, "key": key, "te": te, "err": p - y[te], "bar": bar,
            "bar2": bar2, "bar3": bar3, "fit_s": t1 - t0}


def pct(v):
    return 100 * np.expm1(v)


def summary(e):
    a = np.abs(e)
    return {"rmse": float(pct(np.sqrt((a ** 2).mean()))), "median": float(pct(np.median(a))),
            "p95": float(pct(np.percentile(a, 95))), "max": float(pct(a.max()))}


def main(family: str):
    D = load(family)
    n = len(D["U"])
    rng = np.random.default_rng(20261103)
    splits = []
    for rep in range(CV_REPEATS):
        perm = rng.permutation(n)
        for f in range(CV_FOLDS):
            te = np.sort(perm[f::CV_FOLDS])
            splits.append(("cv", rep, np.setdiff1d(np.arange(n), te), te))
    curve_n = [m for m in CURVE_N if m <= 0.8 * n]
    for m in curve_n:
        for rep in range(CURVE_REPEATS):
            perm = rng.permutation(n)
            splits.append(("curve", m, np.sort(perm[:m]), np.sort(perm[m:])))
    for d, name in enumerate(D["names"]):
        for side, mask in (("low", D["U"][:, d] < BLOCK_FRACTION), ("high", D["U"][:, d] > 1 - BLOCK_FRACTION)):
            splits.append(("block", f"{name}:{side}", np.where(~mask)[0], np.where(mask)[0]))
    tasks = [(family, mo, qi, t, *s) for qi, q in enumerate(D["q"]) for t in TARGETS if t == "norm" or q["has_ref"]
             for mo in MODELS for s in splits]
    print(f"{family}: {n} points, {len(D['names'])} ratios, {len(tasks)} fits", flush=True)
    t0 = time.time()
    with Pool(max(1, (os.cpu_count() or 2) - 2)) as pool:
        rows = []
        for i, r in enumerate(pool.imap_unordered(_task, tasks, chunksize=4)):
            rows.append(r)
            if (i + 1) % 400 == 0:
                print(f"  {i + 1}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
    print(f"done in {time.time() - t0:.0f}s", flush=True)

    edge = (D["U"] < EDGE).any(1) | (D["U"] > 1 - EDGE).any(1)
    res = {"family": family, "points": n, "edge_points": int(edge.sum()), "settings": {"cv": [CV_REPEATS, CV_FOLDS], "curve": curve_n,
           "curve_repeats": CURVE_REPEATS, "block_fraction": BLOCK_FRACTION, "edge": EDGE}, "q": []}
    boot = np.random.default_rng(7)
    for qi, q in enumerate(D["q"]):
        qr = {"name": q["name"], "mesh_band_median_pct": float(100 * np.median(q["band"])), "targets": {}}
        print(f"\n=== {q['name']}  mesh band median {100 * np.median(q['band']):.3f} %, p95 {100 * np.percentile(q['band'], 95):.3f} %")
        for t in TARGETS:
            if t == "raw" and not q["has_ref"]:
                continue
            tr = {"cv": {}, "curve": {}, "block": {}}
            print(f"--- target {t}: 10-fold CV, error % (rmse / median / p95 / max); bar coverage and mean half width; p95 near edge / interior")
            per = {}
            for mo in MODELS:
                rs = [r for r in rows if r["model"] == mo and r["qi"] == qi and r["target"] == t and r["exp"] == "cv"]
                err = np.zeros((CV_REPEATS, n))
                bar, bar2, bar3 = np.zeros((CV_REPEATS, n)), np.zeros((CV_REPEATS, n)), np.zeros((CV_REPEATS, n))
                for r in rs:
                    err[r["key"], r["te"]] = r["err"]
                    bar[r["key"], r["te"]] = r["bar"]
                    bar2[r["key"], r["te"]] = r["bar2"]
                    bar3[r["key"], r["te"]] = r["bar3"]
                per[mo] = np.abs(err).mean(0)
                s = summary(err.ravel())
                s.update(cover=float((np.abs(err) <= bar).mean()), width=float(pct(bar.mean())), cover_cal=float((np.abs(err) <= bar2).mean()),
                         width_cal=float(pct(bar2.mean())), cover_const=float((np.abs(err) <= bar3).mean()), width_const=float(pct(bar3.mean())),
                         cover_max=float((np.abs(err) <= np.maximum(bar2, bar3)).mean()), width_max=float(pct(np.maximum(bar2, bar3).mean())),
                         cover_const_edge=float((np.abs(err[:, edge]) <= bar3[:, edge]).mean()), p95_edge=float(pct(np.percentile(np.abs(err[:, edge]), 95))),
                         p95_inner=float(pct(np.percentile(np.abs(err[:, ~edge]), 95))) if (~edge).any() else None,
                         cover_edge=float((np.abs(err[:, edge]) <= bar2[:, edge]).mean()), fit_s=float(np.mean([r["fit_s"] for r in rs])))
                tr["cv"][mo] = s
                print(f"{mo:11s} {s['rmse']:6.2f} {s['median']:6.2f} {s['p95']:6.2f} {s['max']:7.2f} | raw {s['cover']:.3f} ±{s['width']:5.2f} cal {s['cover_cal']:.3f} ±{s['width_cal']:5.2f} const {s['cover_const']:.3f} ±{s['width_const']:5.2f} (edge {s['cover_const_edge']:.3f}) max {s['cover_max']:.3f} ±{s['width_max']:5.2f} "
                      f"| edge {s['p95_edge']:6.2f} (cover {s['cover_edge']:.3f}) inner {s['p95_inner'] if s['p95_inner'] is None else round(s['p95_inner'], 2)} | fit {s['fit_s']:.2f}s")
            # paired: same points, same folds, so resample points and compare with the spline in production
            base = per["tps"]
            for mo in MODELS[1:]:
                ratios, p95s = [], []
                for _ in range(4000):
                    i = boot.integers(0, n, n)
                    ratios.append(np.sqrt((per[mo][i] ** 2).mean() / (base[i] ** 2).mean()))
                    p95s.append(np.percentile(per[mo][i], 95) / np.percentile(base[i], 95))
                tr["cv"][mo]["vs_tps"] = {"rmse_ratio": float(np.sqrt((per[mo] ** 2).mean() / (base ** 2).mean())),
                                          "rmse_ci": [float(v) for v in np.percentile(ratios, [2.5, 97.5])],
                                          "p95_ci": [float(v) for v in np.percentile(p95s, [2.5, 97.5])],
                                          "better_share": float((per[mo] < base).mean())}
                v = tr["cv"][mo]["vs_tps"]
                print(f"  {mo:11s} vs tps: rmse x{v['rmse_ratio']:.3f} CI [{v['rmse_ci'][0]:.3f}, {v['rmse_ci'][1]:.3f}], p95 CI [{v['p95_ci'][0]:.3f}, {v['p95_ci'][1]:.3f}], better on {100 * v['better_share']:.0f} % of points")
            print(f"--- target {t}: learning curve, rmse % (spread over {CURVE_REPEATS} draws); p95 % ; calibrated-bar coverage")
            for m_ in curve_n:
                line = [f"n={m_:<4d}"]
                tr["curve"][str(m_)] = {}
                for mo in MODELS:
                    rs = [r for r in rows if r["model"] == mo and r["qi"] == qi and r["target"] == t and r["exp"] == "curve" and r["key"] == m_]
                    rm = [summary(r["err"])["rmse"] for r in rs]
                    al = np.concatenate([r["err"] for r in rs])
                    b2 = np.concatenate([r["bar2"] for r in rs])
                    b3 = np.concatenate([r["bar3"] for r in rs])
                    x = {"rmse": float(np.median(rm)), "rmse_lo": float(min(rm)), "rmse_hi": float(max(rm)), "p95": summary(al)["p95"], "cover": float((np.abs(al) <= b2).mean()), "cover_const": float((np.abs(al) <= b3).mean()), "cover_max": float((np.abs(al) <= np.maximum(b2, b3)).mean())}
                    tr["curve"][str(m_)][mo] = x
                    line.append(f"{mo} {x['rmse']:6.2f} [{x['rmse_lo']:5.2f},{x['rmse_hi']:6.2f}] p95 {x['p95']:6.2f} c{x['cover']:.2f}/{x['cover_const']:.2f}/{x['cover_max']:.2f}")
                print(" ".join(line))
            print(f"--- target {t}: block hold-out, rmse % / max % per slab; calibrated-bar coverage")
            for mo in MODELS:
                rs = sorted([r for r in rows if r["model"] == mo and r["qi"] == qi and r["target"] == t and r["exp"] == "block"], key=lambda r: r["key"])
                al = np.concatenate([r["err"] for r in rs])
                b2 = np.concatenate([r["bar2"] for r in rs])
                b3 = np.concatenate([r["bar3"] for r in rs])
                tr["block"][mo] = {"all": summary(al), "cover": float((np.abs(al) <= b2).mean()), "cover_const": float((np.abs(al) <= b3).mean()), "cover_max": float((np.abs(al) <= np.maximum(b2, b3)).mean()), "slabs": {r["key"]: summary(r["err"])["rmse"] for r in rs}}
                print(f"{mo:11s} all rmse {tr['block'][mo]['all']['rmse']:6.2f} p95 {tr['block'][mo]['all']['p95']:6.2f} max {tr['block'][mo]['all']['max']:7.2f} cover {tr['block'][mo]['cover']:.3f}/{tr['block'][mo]['cover_const']:.3f}/{tr['block'][mo]['cover_max']:.3f} | worst slab "
                      f"{max(tr['block'][mo]['slabs'], key=tr['block'][mo]['slabs'].get)} {max(tr['block'][mo]['slabs'].values()):.2f}")
            full = {}
            for mo in MODELS:
                t1 = time.perf_counter()
                m = make(mo).fit(D["U"], q["y"][t])
                t2 = time.perf_counter()
                m.predict(D["U"][:1])
                t3 = time.perf_counter()
                full[mo] = {**m.info(), "fit_s": t2 - t1, "predict_ms": 1000 * (t3 - t2)}
            tr["full"] = full
            print("full fit:", json.dumps(full, indent=None))
            qr["targets"][t] = tr
        res["q"].append(qr)
    out = ROOT / "dataset" / "out" / family / "surrogate_compare.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("\nwrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "l_bracket")
