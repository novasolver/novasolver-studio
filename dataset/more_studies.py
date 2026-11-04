"""Add three-mesh studies to points that were solved without one, where the first sample proved too thin.

    python dataset/more_studies.py --family l_bracket_plastic --ids 5,15,25,26,29,8 --workers 2

Each finished point is appended to points.jsonl again with its "gci" added; analyze.py keeps the last good row of an id,
so the log stays append-only and the run can be stopped and resumed."""
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


def job(family: str, row: dict) -> dict:
    os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
    import build
    import core
    fam = importlib.import_module(family)
    lv = getattr(fam, "LEVELS", build.LEVELS)
    return {**row, "gci": {k: core.solve(fam, row["params"], lv[k]) for k in ("coarser", "finer")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    out = HERE / "out" / a.family
    os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(out / "_work"))
    os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", str(a.workers))
    log = out / "points.jsonl"
    latest = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("status") == "ok":
            latest[r["id"]] = r
    todo = [latest[int(i)] for i in a.ids.split(",") if "gci" not in latest[int(i)]]
    print(f"{a.family}: {len(todo)} mesh studies to run", flush=True)
    with ProcessPoolExecutor(a.workers) as ex, log.open("a", encoding="utf-8") as f:
        futs = {ex.submit(job, a.family, r): r["id"] for r in todo}
        for fut in as_completed(futs):
            try:
                f.write(json.dumps(fut.result(), ensure_ascii=False) + "\n")
                f.flush()
                print(futs[fut], "ok", flush=True)
            except Exception as e:                                  # one failed study must not lose the others
                print(futs[fut], "failed", f"{type(e).__name__}: {e}"[:300], flush=True)


if __name__ == "__main__":
    main()
