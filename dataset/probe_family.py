"""Solve one point of a family at several refinement levels and print the nondimensional answers and checks
(choosing the standard level before a build).  python probe_family.py plate_hole [levels...]"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(Path(tempfile.gettempdir()) / "nss_dataset_probe"))
os.environ.setdefault("NOVASTUDIO_MCP_NO_IMAGES", "1")
import core  # noqa: E402

fam = importlib.import_module(sys.argv[1])
levels = [float(x) for x in sys.argv[2:]] or [1 / 4, 1 / 8, 1 / 16, 1 / 32]
p = json.loads(os.environ.get("NSS_PROBE_P", "null")) or {k: round((lo + hi) / 2, 4) for k, (lo, hi) in fam.PARAMS.items()}
print("params", p, flush=True)
for lv in levels:
    s = core.solve(fam, p, lv)
    nd = fam.nondim(s, p)
    print(f"level {lv:.4g}: {s['wall_s']:6} s nodes {s['nodes']:7d}  "
          + "  ".join(f"{k} {v:.5g}" for k, v in {**nd, **fam.references(p, s, nd)}.items())
          + f"  reaction {s['reaction_n']}  mirror {fam.mirror_err(s):.2e}", flush=True)
