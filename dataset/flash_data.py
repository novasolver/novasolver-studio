"""Write NovaSolver Flash's data file for a solved family: backend/novastudio/estimate_data/<family>.json, the same file
the site's explore.js reads. Rows are [id, ratios..., (answer, mesh band) per quantity, checks], checks a bit mask:
1 three-mesh study, 2 CalculiX, 4 similarity, 8 a picture exists. Then run flash_hyper.py to learn the "gp" settings.

    python dataset/flash_data.py square_hole_thermal strip_hole_current"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "backend" / "novastudio" / "estimate_data"
sys.path.insert(0, str(HERE))


def short(v: str) -> float:
    return float(f"{float(v):.6g}")


def build(family: str) -> dict:
    fam = __import__(family)
    rows = list(csv.DictReader((HERE / "out" / family / "points.csv").open(encoding="utf-8")))
    names = list(fam.PARAMS)
    pics = HERE / "out" / family / "pictures"
    points = []
    for r in rows:
        ck = (1 if r["has_gci"] == "True" else 0) | (2 if r["has_calculix"] == "True" else 0) | \
             (4 if r["has_similarity"] == "True" else 0) | (8 if (pics / f"{r['id']}.webp").is_file() else 0)
        q = []
        for name in fam.QUANTITIES:
            q += [short(r[name]), short(r[f"{name}_band"])]
        points.append([int(r["id"])] + [short(r[n]) for n in names] + q + [ck])
    return {"family": family, "params": [[n, *fam.PARAMS[n]] for n in names], "quantities": list(fam.QUANTITIES),
            "points": points}


def main():
    for family in sys.argv[1:]:
        d = build(family)
        (DATA / f"{family}.json").write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
        print(family, len(d["points"]), "points")


if __name__ == "__main__":
    main()
