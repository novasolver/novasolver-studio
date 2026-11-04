"""CalculiX as an independent check of the collapse load, which its own curve cannot give (it stops at collapse with no
result to read): the same mesh must carry LOW x lam_limit and must fail at HIGH x lam_limit.

    python dataset/plastic_bracket.py 10,15,19

Each answer goes to out/l_bracket_plastic/ccx_bracket.jsonl."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "l_bracket_plastic"
LOW, HIGH = 0.95, 1.06


def one(idx: int, factor: float) -> None:
    """In a process of its own: LAM_MAX is read when the family is imported."""
    sys.path.insert(0, str(HERE))
    os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
    rows = [json.loads(x) for x in (OUT / "points.jsonl").read_text(encoding="utf-8").splitlines()]
    row = [r for r in rows if r["id"] == idx and r["status"] == "ok"][-1]
    import core
    import l_bracket_plastic as fam
    try:
        s = core.solve(fam, row["params"], fam.LEVELS["standard"], mode="final")
        ans = {"finished": True, "wall_s": s["wall_s"], "engine": s["engine"]}
    except Exception as e:
        text = str(e)
        ans = {"finished": False, "collapse": "increment size smaller" in text, "error": text[:200]}
    with (OUT / "ccx_bracket.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": idx, "factor": factor, "lam_builtin": row["standard"]["lam_reached"], **ans}) + "\n")
    print(idx, factor, ans, flush=True)


def main():
    if sys.argv[1] == "--one":
        return one(int(sys.argv[2]), float(sys.argv[3]))
    rows = [json.loads(x) for x in (OUT / "points.jsonl").read_text(encoding="utf-8").splitlines()]
    for idx in map(int, sys.argv[1].split(",")):
        lam = [r for r in rows if r["id"] == idx and r["status"] == "ok"][-1]["standard"]["lam_reached"]
        for factor in (LOW, HIGH):
            env = dict(os.environ, NSS_LAM_MAX=str(lam * factor), NOVASTUDIO_WORKSPACE=str(OUT / "_work"), NOVASTUDIO_SOLVER_SLOTS="4")
            subprocess.run([sys.executable, __file__, "--one", str(idx), str(factor)], env=env, check=True)


if __name__ == "__main__":
    main()
