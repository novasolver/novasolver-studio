"""Blind test of the surrogates on one family: predictions are frozen and hashed first, then the points are solved.

    python dataset/blind_check.py <family> plan                 write predictions.json (refuses to overwrite)
    python dataset/blind_check.py <family> solve --workers 3    solve every planned point (append-only log, safe to resume)
    python dataset/blind_check.py <family> score                compare, write score.json
    --round 2 on all three: after a change that the earlier points showed was needed, a fresh set in out/<family>_blind_r2

Points: the next points of the dataset's own Sobol sequence, hard points near the ends of several ranges at once,
reruns of two dataset points (does this Studio version still give the same answer?) and twins moved a tiny step from a
Sobol point (how much mesh noise sits under any surrogate?). Same mesh level as the dataset."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MODELS = ("tps", "tps_ard", "gp_m52_ard", "gp_rbf_ard")
N_SOBOL, N_HARD, N_TWIN = 20, 12, 4
TWIN_STEP = 0.002              # of each range
HARD = {"l_bracket": ("t_over_L", "w_over_L", "r_over_t")}     # the ranges pushed to their ends; default: all but nu


ROUND = 0                      # a later round after a change: fresh points, its own folder (--round)


def out_dir(family: str) -> Path:
    return HERE / "out" / (f"{family}_blind" + (f"_r{ROUND}" if ROUND else ""))


def solved_rows(family: str) -> dict:
    rows = {}
    for line in (HERE / "out" / family / "points.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("status") == "ok":
            rows[r["id"]] = r
    return rows


def plan_points(family: str, fam) -> list[dict]:
    import build
    rows = solved_rows(family)
    design = max(i for i in rows if i < build.REFINE_ID) + 1 + ROUND * N_SOBOL     # REFINE points sit apart
    names = list(fam.PARAMS)
    lo = np.array([fam.PARAMS[k][0] for k in names])
    hi = np.array([fam.PARAMS[k][1] for k in names])
    to_p = lambda u: {k: round(float(v), 6) for k, v in zip(names, lo + np.clip(u, 0, 1) * (hi - lo))}
    pts = [{"key": f"sobol{i}", "kind": "sobol", "params": p} for i, p in enumerate(build.sobol_points(fam, design + N_SOBOL)[design:])]
    rng = np.random.default_rng(20261104 + ROUND)
    free = [names.index(k) for k in HARD.get(family, [k for k in names if k != "nu"])]
    if len(free) < 2:
        free = list(range(len(names)))
    for i in range(N_HARD):
        u = rng.random(len(names))
        for d in rng.choice(free, size=min(int(rng.integers(2, 4)), len(free)), replace=False):
            u[d] = rng.uniform(0, 0.05) if rng.random() < 0.5 else rng.uniform(0.95, 1)
        pts.append({"key": f"hard{i}", "kind": "hard", "params": to_p(u)})
    for i in range(N_TWIN):
        base = pts[i]["params"]
        u = (np.array([base[k] for k in names]) - lo) / (hi - lo) + TWIN_STEP * rng.choice([-1, 1], len(names))
        pts.append({"key": f"twin{i}", "kind": "twin", "base": pts[i]["key"], "params": to_p(u)})
    for i in sorted(rows)[1:3]:
        pts.append({"key": f"rerun{i}", "kind": "rerun", "id": i, "params": rows[i]["params"]})
    return pts


def plan(family: str):
    import compare_surrogates as cs
    fam = importlib.import_module(family)
    out_dir(family).mkdir(parents=True, exist_ok=True)
    f = out_dir(family) / "predictions.json"
    if f.exists():
        sys.exit(f"{f} exists: predictions are frozen once written")
    D = cs.load(family)
    names = D["names"]
    d = json.loads((cs.DATA / f"{family}.json").read_text(encoding="utf-8"))
    lo, hi = np.array([p[1] for p in d["params"]], float), np.array([p[2] for p in d["params"]], float)
    pts = plan_points(family, fam)
    Us = (np.array([[p["params"][k] for k in names] for p in pts]) - lo) / (hi - lo)
    assert names == list(fam.PARAMS)
    out = {"family": family, "points": pts, "pred": {}}
    for qi, q in enumerate(D["q"]):
        out["pred"][q["name"]] = {}
        for t in ("norm", "raw"):
            out["pred"][q["name"]][t] = {}
            for mo in MODELS:
                m = cs.make(mo).fit(D["U"], q["y"][t])
                mean, bar, bar2, bar3 = m.predict(Us)
                out["pred"][q["name"]][t][mo] = {"mean": mean.tolist(), "sigma_bar": bar2.tolist(), "const_bar": bar3.tolist()}
                print(q["name"], t, mo, "fitted", flush=True)
    # nearest-point mesh band, as estimate.py gives it
    d2 = ((D["U"][None, :, :] - Us[:, None, :]) ** 2).sum(-1)
    near = np.argsort(d2, 1)[:, :4]
    for q in D["q"]:
        w = 1 / (np.take_along_axis(d2, near, 1) + 1e-6)
        out["pred"][q["name"]]["mesh_band"] = ((w * q["band"][near]).sum(1) / w.sum(1)).tolist()
    # the answer a user gets today, from Studio's own code
    from novastudio import estimate as E
    flash = [E.estimate(family, p["params"]) for p in pts]
    out["flash"] = [[r["dimensionless_value"] for r in x["results"]] for x in flash]
    out["flash_error_pct"] = [[r["error_pct"] for r in x["results"]] for x in flash]
    b = json.dumps(out, sort_keys=True).encode("utf-8")
    f.write_bytes(b)
    print("frozen", len(pts), "points, sha256", hashlib.sha256(b).hexdigest())


def job(family: str, key: str, p: dict) -> dict:
    os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
    import build
    import core
    fam = importlib.import_module(family)
    lv = getattr(fam, "LEVELS", build.LEVELS)
    try:
        s = core.solve(fam, p, lv["standard"])
        return {"key": key, "status": "ok", "standard": s, "nd": fam.nondim(s, p)}
    except Exception as e:
        return {"key": key, "status": "failed", "error": f"{type(e).__name__}: {e}"[:400]}


def solve(family: str, workers: int):
    OUT = out_dir(family)
    from novastudio import __version__
    pred = json.loads((OUT / "predictions.json").read_text(encoding="utf-8"))
    os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(OUT / "_work"))
    os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", str(workers))
    log = OUT / "solved.jsonl"
    done = {json.loads(x)["key"] for x in log.read_text(encoding="utf-8").splitlines()} if log.exists() else set()
    todo = [p for p in pred["points"] if p["key"] not in done]
    print(f"studio {__version__}: {len(todo)} to solve", flush=True)
    with ProcessPoolExecutor(workers) as ex, log.open("a", encoding="utf-8") as f:
        futs = [ex.submit(job, family, p["key"], p["params"]) for p in todo]
        for k, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(f"[{k}/{len(todo)}] {r['key']} {r['status']} {r.get('standard', {}).get('wall_s', r.get('error'))}", flush=True)


def score(family: str):
    import compare_surrogates as cs
    OUT = out_dir(family)
    fam = importlib.import_module(family)
    pred = json.loads((OUT / "predictions.json").read_text(encoding="utf-8"))
    print("predictions sha256", hashlib.sha256((OUT / "predictions.json").read_bytes()).hexdigest())
    got = {}
    for line in (OUT / "solved.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        got[r["key"]] = r
    pts = pred["points"]
    failed = [p["key"] for p in pts if got.get(p["key"], {}).get("status") != "ok"]
    print("failed or missing:", failed)
    D = cs.load(family)
    res = {"failed": failed, "q": {}}
    rows = solved_rows(family)
    print("--- reruns of dataset points: relative change against the stored answer")
    for p in pts:
        if p["kind"] == "rerun" and p["key"] not in failed:
            old, new = fam.nondim(rows[p["id"]]["standard"], p["params"]), got[p["key"]]["nd"]
            print(" ", p["key"], {k: f"{new[k] / old[k] - 1:+.2e}" for k in old}, "elements", rows[p["id"]]["standard"]["elements"], got[p["key"]]["standard"]["elements"])
    kinds = {k: np.array([i for i, p in enumerate(pts) if p["kind"] == k and p["key"] not in failed]) for k in ("sobol", "hard", "twin")}
    names = D["names"]
    for qi, q in enumerate(D["q"]):
        name, nd_key = q["name"], fam.QUANTITIES[qi]
        ref = cs.SHAPES[family]["out"][qi][3] or (lambda x: 1.0)
        ly = np.array([np.log(got[p["key"]]["nd"][nd_key]) if p["key"] not in failed else np.nan for p in pts])
        lnorm = np.array([np.log(ref(dict(zip(names, [p["params"][k] for k in names])))) for p in pts])
        band = np.array(pred["pred"][name]["mesh_band"])
        res["q"][name] = {}
        print(f"\n=== {name}  (error %, log-based); mesh band at these points median {100 * np.median(band):.3f} %")
        for t in ("norm", "raw"):
            target = ly - lnorm if t == "norm" else ly
            for kind, idx in kinds.items():
                if kind == "twin" or not len(idx):
                    continue
                print(f"--- {t} / {kind} ({len(idx)} points): rmse median p95 max | const bar cover, sigma bar cover, max-of-both cover (mean half width)")
                for mo in MODELS:
                    P = pred["pred"][name][t][mo]
                    e = np.array(P["mean"])[idx] - target[idx]
                    a = np.abs(e)
                    c, s = np.array(P["const_bar"])[idx], np.array(P["sigma_bar"])[idx]
                    m = np.maximum(c, s)
                    row = {**cs.summary(e), "cover_const": float((a <= c).mean()), "cover_sigma": float((a <= s).mean()), "cover_max": float((a <= m).mean()),
                           "width_const": float(cs.pct(c.mean())), "width_max": float(cs.pct(m.mean())), "cover_with_mesh": float((a <= m + band[idx]).mean()), "bias": float(cs.pct(np.abs(e.mean())))}
                    res["q"][name].setdefault(t, {}).setdefault(kind, {})[mo] = row
                    print(f"{mo:11s} {row['rmse']:6.3f} {row['median']:6.3f} {row['p95']:6.3f} {row['max']:6.3f} | {row['cover_const']:.2f} {row['cover_sigma']:.2f} {row['cover_max']:.2f} (±{row['width_max']:.3f}) with mesh {row['cover_with_mesh']:.2f} | signed mean {100 * e.mean():+.3f}")
        # twins: what moved beyond what the smooth GP says should move is noise
        tn = []
        by = {p["key"]: i for i, p in enumerate(pts)}
        P = pred["pred"][name]["norm"]["gp_m52_ard"]
        for p in pts:
            if p["kind"] == "twin" and p["key"] not in failed and p["base"] not in failed:
                i, b = by[p["key"]], by[p["base"]]
                tn.append(((ly[i] - lnorm[i]) - (ly[b] - lnorm[b])) - (P["mean"][i] - P["mean"][b]))
        res["q"][name]["twin_noise_pct"] = [float(100 * v) for v in tn]
        print("twin noise %:", [round(100 * v, 3) for v in tn], "(geometry moved", TWIN_STEP, "of each range; expected change removed)")
        # the answer a user gets today, end to end
        idx = np.r_[kinds["sobol"], kinds["hard"]]
        fl = np.log(np.array([r[qi] for r in pred["flash"]]))
        err = 100 * (np.exp(np.abs(fl[idx] - ly[idx])) - 1)
        bar = np.array([r[qi] for r in pred["flash_error_pct"]])[idx]
        res["q"][name]["flash"] = {"max_err": float(err.max()), "within_bar": float((err <= bar).mean()), "mean_bar": float(bar.mean())}
        print(f"Flash today: max error {err.max():.3f} %, inside its stated bar on {(err <= bar).mean():.3f} of {len(idx)} points (mean bar {bar.mean():.2f} %)")
    (OUT / "score.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("family")
    ap.add_argument("cmd", choices=("plan", "solve", "score"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--round", type=int, default=0)
    a = ap.parse_args()
    ROUND = a.round
    {"plan": lambda: plan(a.family), "solve": lambda: solve(a.family, a.workers), "score": lambda: score(a.family)}[a.cmd]()
