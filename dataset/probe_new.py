"""Solve one point of a family at one mesh level and print what came back, before a family is built.

    python dataset/probe_new.py large_deflection t_over_L=0.02,w_over_t=2,nu=0.3 [standard]"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(HERE / "out" / "_probe_work"))
os.environ.setdefault("NOVASTUDIO_SOLVER_SLOTS", "4")
os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")


def main():
    import build
    import core
    fam = importlib.import_module(sys.argv[1])
    p = {a: float(b) for a, b in (kv.split("=") for kv in sys.argv[2].split(","))}
    level = sys.argv[3] if len(sys.argv) > 3 else "standard"
    t0 = time.time()
    s = core.solve(fam, p, getattr(fam, "LEVELS", build.LEVELS)[level])
    print(f"{sys.argv[1]} {level}: {time.time() - t0:.0f} s, nodes {s['nodes']}, converged {s['converged']}")
    nd = fam.nondim(s, p)
    print(" answers", {k: round(v, 5) for k, v in nd.items()})
    print(" references", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in fam.references(p, s, nd).items()})
    print(" raw", json.dumps({k: v for k, v in s.items() if k != "curve"})[:500])
    if s.get("curve"):
        print(" curve", len(s["curve"]), "last", s["curve"][-1])


if __name__ == "__main__":
    main()
