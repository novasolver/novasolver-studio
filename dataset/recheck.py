"""Re-solve the points the neighbour check flagged, on the finer mesh, and log them (rechecks.jsonl).

    python dataset/recheck.py --family l_bracket [--workers 3]

A flag says "this point is far from what its neighbours imply"; that is a reason to look, not a verdict (at the edge
of the space a smooth fit extrapolates). analyze.py then marks each flag resolved when the finer solve agrees with the
standard answer within the point's error band, and keeps it unresolved (to be investigated) otherwise."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def job(family: str, idx: int, p: dict, level: float) -> dict:
    os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
    import core
    fam = importlib.import_module(family)
    try:
        return {"id": idx, "level": level, "finer": core.solve(fam, p, level)}
    except Exception as e:
        return {"id": idx, "level": level, "error": f"{type(e).__name__}: {e}"[:300]}


def main():
    import build
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="l_bracket")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    fam = importlib.import_module(a.family)
    out = HERE / "out" / a.family
    os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(out / "_work"))
    os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", str(a.workers))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    log = out / "rechecks.jsonl"
    done = {json.loads(l)["id"] for l in log.read_text(encoding="utf-8").splitlines()} if log.exists() else set()
    ids = sorted({i for v in summary["neighbour_flags"].values() for i in v} - done)
    rows = {json.loads(l)["id"]: json.loads(l) for l in (out / "points.jsonl").read_text(encoding="utf-8").splitlines()}
    level = getattr(fam, "LEVELS", build.LEVELS)["finer"]
    print(f"{a.family}: re-solving {len(ids)} flagged points at level {level}", flush=True)
    with ProcessPoolExecutor(a.workers) as ex, log.open("a", encoding="utf-8") as f:
        for r in ex.map(job, [a.family] * len(ids), ids, [rows[i]["params"] for i in ids], [level] * len(ids)):
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(r["id"], "ok" if "finer" in r else r["error"], flush=True)


if __name__ == "__main__":
    main()
