"""The answer a user gets from NovaSolver Flash against new solves it never saw, per shape and quantity.

    python dataset/flash_blind_table.py [out.json]

Uses the points dataset/blind_check.py planned and solved. The thick cylinder is scored on Lame's exact answer: its data
are closer to it than a new solve on the standard mesh, so that solve is no reference."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))
from novastudio import estimate as E  # noqa: E402


def main():
    table = []
    for shape, spec in E.SHAPES.items():
        fam = importlib.import_module(shape)
        out = HERE / "out" / f"{shape}_blind"
        pred = json.loads((out / "predictions.json").read_text(encoding="utf-8"))
        got = {r["key"]: r for r in map(json.loads, (out / "solved.jsonl").read_text(encoding="utf-8").splitlines())}
        pts = [p for p in pred["points"] if p["kind"] in ("sobol", "hard") and got[p["key"]]["status"] == "ok"]
        for qi, row in enumerate(spec["out"]):
            if shape == "thick_cylinder":
                ref = np.array([(E._lame_hoop, E._lame_u)[qi](p["params"]) for p in pts])
            else:
                ref = np.array([got[p["key"]]["nd"][fam.QUANTITIES[qi]] for p in pts])
            ans = [E.estimate(shape, p["params"])["results"][qi] for p in pts]
            err = 100 * np.abs(np.array([a["dimensionless_value"] for a in ans]) / ref - 1)
            bar = np.array([a["error_pct"] for a in ans])
            table.append({"shape": shape, "quantity": row[0], "points": len(pts), "median_pct": float(np.median(err)), "max_pct": float(err.max()),
                          "inside": int((err <= bar).sum()), "mean_bar_pct": float(bar.mean())})
            print(shape, row[0], f"{len(pts)} points, median {np.median(err):.3f} %, max {err.max():.3f} %, inside {(err <= bar).sum()}, mean bar {bar.mean():.2f} %")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(table, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()