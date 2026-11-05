"""Turns the results of corpus.py into docs/PART_TEST.md: how often Studio gets a part it has never seen to a solved result,
with every kind of failure counted. Only totals are published, because the sample files have mixed or unknown licences.

    python validation/corpus_report.py results.jsonl docs/PART_TEST.md --version 0.7.6 --limit-s 480"""
from __future__ import annotations

import argparse
import json
import platform
from collections import Counter
from datetime import date
from pathlib import Path

KINDS = [
    ("solved", "Solved, and the reactions balance the 1,000 N load within 1 %"),
    ("unbalanced", "Solved, but the force balance is off by more than 1 %"),
    ("loose", "Refused with an explanation: a body has no support, or part of the model can move freely"),
    ("no_solid", "Refused with an explanation: the file contains no closed solid"),
    ("mesh", "Failed: no valid mesh"),
    ("solver", "Failed: the solver stopped"),
    ("time", "Failed: over the time limit"),
    ("other", "Failed: other"),
]


def kind(r: dict) -> str:
    text = f"{r.get('message') or ''} {r.get('error') or ''}"
    if r.get("ok"):
        return "solved" if (r.get("balance_err_pct") or 0) < 1 else "unbalanced"
    if "no support" in text or "free to move" in text:
        return "loose"
    if "no_solid" in text or "NO_SOLID" in text:
        return "no_solid"
    if "limit" in text or "Timeout" in text:
        return "time"
    if "Mesh generation failed" in text or "err.mesh" in text or "mesher" in text:
        return "mesh"
    if "solver" in text:
        return "solver"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("out")
    ap.add_argument("--version", required=True)
    ap.add_argument("--limit-s", type=int, required=True)
    a = ap.parse_args()
    rows = [json.loads(x) for x in open(a.results, encoding="utf-8") if x.strip()]
    if len({r["file"] for r in rows}) != len(rows):
        raise SystemExit("a file appears twice in the results")
    total = Counter(kind(r) for r in rows)
    by_source = {s: Counter(kind(r) for r in rows if r["file"].startswith(s + "/")) for s in sorted({r["file"].split("/")[0] for r in rows})}
    solved = [r for r in rows if kind(r) == "solved"]
    n = len(rows)
    pct = lambda c: f"{100 * c / n:.0f} %"                   # noqa: E731
    lines = [
        f"# Part test: {a.version}",
        "",
        f"Can Studio take a part it has never seen from import to a solved result? {n} STEP files that were not made for Studio "
        "went through `validation/corpus.py`: import, one end of the longest axis fixed, 1,000 N on the other end, automatic mesh at the coarse level, "
        f"solve, and a check that the reactions balance the load. Each file ran on its own, with a limit of {a.limit_s} s.",
        "",
        f"**{len(solved)} of {n} ({pct(len(solved))}) were solved.** Run on {date.today().isoformat()}, {platform.system()}, 8 CPU threads, 16 GB of memory.",
        "",
        "| Result | Parts | Share |",
        "|---|---:|---:|",
    ]
    lines += [f"| {label} | {total[k]} | {pct(total[k])} |" for k, label in KINDS if total[k]]
    lines += ["", "| Source | Parts | Solved |", "|---|---:|---:|"]
    names = {"solidcraft": "STEP test parts of the SolidCraft CAD project", "freecad": "An even sample of the FreeCAD parts library"}
    lines += [f"| {names.get(s, s)} | {sum(c.values())} | {c['solved']} |" for s, c in by_source.items()]
    lines += [
        "",
        "## How to read this",
        "",
        "- It tests robustness, not accuracy. The supports and the load are chosen by a script and mean nothing physically, "
        "so this says nothing about whether a stress value is right. Accuracy is in [VALIDATION.en.md](VALIDATION.en.md).",
        "- Many files are assemblies of loose parts, with screws, wires and enclosures. A refusal is often the right answer there, "
        "because a body that touches nothing cannot be solved under this script's supports.",
        "- Only totals are given. The FreeCAD library's licence is not stated for every file, so the files are not redistributed here.",
        "",
    ]
    Path(a.out).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(dict(total), "solved", len(solved), "of", n)


if __name__ == "__main__":
    main()
