"""Learn NovaSolver Flash's Gaussian process settings offline and store them in each estimate_data/<shape>.json, because
learning takes seconds per quantity and an answer must not. Measurement of the choice: compare_surrogates.py, blind_check.py.

    python dataset/flash_hyper.py

Only the "gp" field changes; the solved points stay byte for byte. estimate.py and the site's explore.js read the same files."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from novastudio.estimate import DATA, SHAPES  # noqa: E402
from novastudio.surrogate import NOISE_FLOOR, Fit  # noqa: E402


def short(v) -> float:
    return float(f"{v:.5g}")


def learn(shape: str, d: dict) -> list[dict]:
    names = [p[0] for p in d["params"]]
    lo, hi = np.array([p[1] for p in d["params"]], float), np.array([p[2] for p in d["params"]], float)
    X = np.array([r[1:1 + len(names)] for r in d["points"]], float)
    out = []
    for i, (name, _sym, _unit, ref, _dim) in enumerate(SHAPES[shape]["out"]):
        y = np.array([r[1 + len(names) + 2 * i] for r in d["points"]], float)
        norm = np.array([ref(dict(zip(names, row))) for row in X]) if ref else 1.0
        h = Fit((X - lo) / (hi - lo), np.log(y / norm), NOISE_FLOOR).hyper()
        out.append({"lengths": [short(v) for v in h["lengths"]], "signal": short(h["signal"]), "noise": short(h["noise"])})
        print(shape, name, out[-1], flush=True)
    return out


def main():
    for shape in SHAPES:
        path = DATA / f"{shape}.json"
        text = path.read_bytes().decode("utf-8")
        d = json.loads(text)
        base = re.sub(r',\s*"gp":\s*\[.*\]\s*\}\s*$', "}", text, flags=re.S).rstrip()
        assert base.endswith("}") and json.loads(base)["points"] == d["points"]
        path.write_bytes((base[:-1] + ',"gp":' + json.dumps(learn(shape, d), separators=(",", ":")) + "}").encode("utf-8"))


if __name__ == "__main__":
    main()