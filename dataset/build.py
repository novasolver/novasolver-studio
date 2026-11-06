"""Build a certified parameter space for one family with NovaSolver Studio.

    python dataset/build.py --family l_bracket --n 300 --workers 4 [--out dataset/out/l_bracket]

Every point is solved once at the standard mesh and carries the cheap checks (equilibrium, symmetry, the family's
hand theory). Every 10th point also gets a three-mesh study (GCI) and a similarity check (lengths x2, force x4: the
nondimensional answers must not move); every 20th is solved again with CalculiX. Results go to an append-only log
(points.jsonl, safe to stop and resume); the case is deleted after its numbers are read, so the workspace stays small.
The mesher and the solver each use one core: run as many workers as there are physical cores, memory permitting.
analyze.py turns the log into the published tables. The family module's interface is described in core.py."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# element size on the family's critical face / its refine_length (coarse global mesh elsewhere). The L-bracket v1
# used 1/8 with a 1/4-1/8-1/16 study: not yet asymptotic (observed orders 0.2-6, standard 2-4 % low); 1/16 is within
# 0.9 % of 1/32 on the worst v1 cases. A family may override with LEVELS.
LEVELS = {"coarser": 1 / 8, "standard": 1 / 16, "finer": 1 / 32}
GCI_EVERY, SIM_EVERY, CCX_EVERY = 10, 10, 20


def point_job(family: str, idx: int, p: dict) -> dict:
    os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
    import core
    from novastudio import __version__
    fam = importlib.import_module(family)
    lv = getattr(fam, "LEVELS", LEVELS)
    row = {"id": idx, "params": p, "studio": __version__, "status": "ok", "refine_levels": lv}
    try:
        pics = os.environ.get("NSS_PICTURES")
        row["standard"] = core.solve(fam, p, lv["standard"], picture=Path(pics) / f"{idx}.webp" if pics else None)
        if idx % getattr(fam, "GCI_EVERY", GCI_EVERY) == 0:
            row["gci"] = {"coarser": core.solve(fam, p, lv["coarser"]), "finer": core.solve(fam, p, lv["finer"])}
        if idx % getattr(fam, "SIM_EVERY", SIM_EVERY) == 0:
            row["similarity"] = core.solve(fam, p, lv["standard"], scale=2.0, force=fam.F * 4)
        if idx % CCX_EVERY == 0 and getattr(fam, "CALCULIX", True):
            try:
                row["calculix"] = core.solve(fam, p, lv["standard"], mode="final")
            except Exception as e:
                row["calculix"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    except Exception as e:
        row["status"] = "failed"
        row["error"] = f"{type(e).__name__}: {e}"[:500]
        row["trace"] = traceback.format_exc()[-1500:]
    return row


def sobol_points(fam, n: int, seed: int = 20261101) -> list[dict]:
    from scipy.stats import qmc
    names = list(fam.PARAMS)
    lo = [fam.PARAMS[k][0] for k in names]
    hi = [fam.PARAMS[k][1] for k in names]
    u = qmc.Sobol(d=len(names), scramble=True, seed=seed).random(n)
    x = qmc.scale(u, lo, hi)
    return [{k: round(float(v), 6) for k, v in zip(names, row)} for row in x]


REFINE_ID = 10000


def refine_points(fam) -> list[tuple[int, dict]]:
    """Extra points in a family's REFINE boxes, [({name: (lo, hi)}, n), ...]: where the answer bends faster than the even
    spread can follow (found by blind_check.py). Ids from 10000 per box, so the main sequence can still grow."""
    out = []
    for b, (box, n) in enumerate(getattr(fam, "REFINE", ())):
        sub = type("Box", (), {"PARAMS": {k: box.get(k, v) for k, v in fam.PARAMS.items()}})
        out += [(REFINE_ID * (b + 1) + i, p) for i, p in enumerate(sobol_points(sub, n, seed=20261106 + b))]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="l_bracket")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    fam = importlib.import_module(a.family)
    out = Path(a.out or HERE / "out" / a.family)
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(out / "_work"))
    # Studio runs one solver job per machine unless told otherwise: without this the workers just queue
    os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", str(a.workers))
    os.environ.setdefault("NSS_PICTURES", str(out / "pictures"))   # one small stress picture per point (explorer)
    log = out / "points.jsonl"
    done = set()
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("status") == "ok":
                done.add(r["id"])
    pts = sobol_points(fam, a.n)
    todo = [(i, p) for i, p in list(enumerate(pts)) + refine_points(fam) if i not in done]
    print(f"{a.family}: {len(done)} done, {len(todo)} to solve with {a.workers} workers", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex, log.open("a", encoding="utf-8") as f:
        futs = {ex.submit(point_job, a.family, i, p): i for i, p in todo}
        for k, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            el = time.time() - t0
            print(f"[{k}/{len(todo)}] id {r['id']} {r['status']}"
                  + (f" {r['standard']['wall_s']} s" if r["status"] == "ok" else f" {r.get('error')}")
                  + f"  elapsed {el / 60:.1f} min, eta {el / k * (len(todo) - k) / 60:.0f} min", flush=True)


if __name__ == "__main__":
    main()
