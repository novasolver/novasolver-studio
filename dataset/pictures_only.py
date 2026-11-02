"""Pictures for a family built before picture.py: solve each good point again at the standard mesh, keep only the picture.

    python dataset/pictures_only.py --family sphere_cavity [--workers 2]"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def job(family: str, idx: int, p: dict, level: float, path: str) -> tuple:
    import core
    fam = importlib.import_module(family)
    try:
        return idx, core.solve(fam, p, level, picture=Path(path)).get("picture")
    except Exception as e:
        return idx, {"error": f"{type(e).__name__}: {e}"[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    import build
    fam = importlib.import_module(a.family)
    out = HERE / "out" / a.family
    os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(out / "_work"))
    os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", str(a.workers))
    level = getattr(fam, "LEVELS", build.LEVELS)["standard"]
    rows = [json.loads(x) for x in (out / "points.jsonl").read_text(encoding="utf-8").splitlines()]
    todo = [r for r in rows if r.get("status") == "ok" and not (out / "pictures" / f"{r['id']}.webp").exists()]
    print(a.family, "pictures to make:", len(todo), flush=True)
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(job, a.family, r["id"], r["params"], level, str(out / "pictures" / f"{r['id']}.webp")) for r in todo]
        bad = 0
        for fut in as_completed(futs):
            idx, meta = fut.result()
            if not meta or "error" in meta:
                bad += 1
                print(idx, meta, flush=True)
    print(a.family, "done, failed", bad, flush=True)


if __name__ == "__main__":
    main()