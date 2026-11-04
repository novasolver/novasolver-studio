"""Collect every analysed family into one small, publishable folder (Hugging Face dataset layout).

    python dataset/package.py [--out dataset/out/_release]

  _release/README.md              the map: every family, its parameters, answers, error bands and checks
  _release/index.json             the same, machine-readable
  _release/<family>/points.csv    one row per point (parameters, answers, error bands, checks)
  _release/<family>/checks_*.csv  mesh studies, similarity, CalculiX
  _release/<family>/summary.json  pass rates and bands
  _release/<family>/README.md     what was solved, how it was checked, how to read the columns
Only CSV / JSON / Markdown: no solver files, meshes or fields."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

pct = lambda x: "-" if x is None else f"{100 * x:.2g} %"
LICENSE = ("## License\n\nThis data is licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n"
           "Credit: NovaSolver, https://novasolver.jp/studio/verified/\n"
           "Provided as is, without warranty. Design decisions remain the user's responsibility.\n")


def family_readme(name: str, fam, s: dict) -> str:
    doc = inspect.getdoc(fam) or ""
    lines = [f"# {name}", "", doc, "", "## Parameters (nondimensional)", "", "| parameter | range |", "|---|---|"]
    lines += [f"| `{k}` | {lo} - {hi} |" for k, (lo, hi) in fam.PARAMS.items()]
    lines += ["", "## Answers and their error bands", "",
              "| answer | error band (median / 95 % / max) | similarity x2 / x4 | CalculiX (same mesh) |", "|---|---|---|---|"]
    for q in s["quantities"]:
        b, sim, ccx = s["error_band"].get(q) or {}, (s["similarity"].get(q) or {}), (s["calculix"].get(q) or {})
        lines.append(f"| `{q}` | {pct(b.get('median'))} / {pct(b.get('p95'))} / {pct(b.get('max'))} | "
                     f"max {pct(sim.get('max'))} | max {pct(ccx.get('max'))} |")
    lines += ["", "## Checks", "",
              f"- points: {s['points_ok']} solved, {s['points_failed']} failed",
              f"- three-mesh studies: {s['gci_studies']} (every {getattr(fam, 'GCI_EVERY', 10)}th point); the band of each point is 1.25 x the "
              "largest standard-mesh error among its 3 nearest studies",
              f"- symmetry check (max): {pct((s.get('mirror_err') or {}).get('max'))}",
              f"- neighbour check: flagged {sum(len(v) for v in s['neighbour_flags'].values())}, "
              f"re-solved on a finer mesh {s.get('rechecked', 0)}, unresolved "
              f"{sum(len(v) for v in s.get('neighbour_flags_unresolved', s['neighbour_flags']).values())}",
              "- direction checks: " + ", ".join(f"{k} {'ok' if v['ok'] else 'FAILED'} (rho {v['spearman']})"
                                                for k, v in s["directions"].items())]
    if s.get("references"):
        lines += ["", "## Against hand theory", "", "| ratio | median | 95 % | max |", "|---|---|---|---|"]
        lines += [f"| `{k}` | {v['median']:.4g} | {v['p95']:.4g} | {v['max']:.4g} |" for k, v in s["references"].items() if v]
    lines += ["", "## Columns of points.csv", "",
              "parameters, the answers, `<answer>_band` (relative), the hand-theory ratios, `mirror_err`, "
              "`equilibrium_err` (where a single reaction exists), `<answer>_loo_err` / `_neighbour_flag` (leave-one-out "
              "prediction from all other points), `<answer>_recheck_diff` / `_flag_resolved` (finer re-solve of a flagged "
              "point), `has_gci` / `has_similarity` / `has_calculix`, `nodes`, `solve_s`, `studio` (version).", "",
              "Solved with NovaSolver Studio through the same commands an AI client uses over MCP; the first section says "
              "which solver and mesh. The claim is verification (the equations are solved within the "
              "band), not validation against tests.", "", LICENSE]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out" / "_release"))
    a = ap.parse_args()
    rel = Path(a.out)
    rel.mkdir(parents=True, exist_ok=True)
    index = []
    for d in sorted((HERE / "out").iterdir()):
        # l_bracket_v2_inside and the like are earlier builds of a family, kept for comparison: not part of the release
        if not (d / "summary.json").exists() or d.name.startswith("_") or re.search(r"_v\d", d.name):
            continue
        s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        fam = importlib.import_module(s["family"])
        dst = rel / d.name
        dst.mkdir(exist_ok=True)
        for f in list(d.glob("*.csv")) + [d / "summary.json"]:
            shutil.copy2(f, dst / f.name)
        (dst / "README.md").write_text(family_readme(d.name, fam, s), encoding="utf-8")
        first = " ".join((inspect.getdoc(fam) or "").split("\n\n")[0].split())
        index.append({"family": d.name, "title": re.sub(r"^Family \w+: ", "", first.split(". ")[0].rstrip(".")),"points": s["points_ok"],
                      "params": s["params"], "answers": s["quantities"],
                      "error_band_p95": {q: (s["error_band"].get(q) or {}).get("p95") for q in s["quantities"]},
                      "size_kb": round(sum(f.stat().st_size for f in dst.iterdir()) / 1024, 1)})
    (rel / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["---", "license: cc-by-4.0", "---", "", "# Simulation data with error bars", "",
             "Parameter sweeps of standard engineering problems where every point carries its own verification: an error "
             "band from mesh studies, symmetry, similarity scaling, an independent solver (CalculiX) on a subset, hand "
             "theory where it exists, and a neighbour-consistency check over the whole space.", "",
             "| family | what | points | answers | error band (95 %) | size |", "|---|---|---|---|---|---|"]
    for i in index:
        lines.append(f"| [{i['family']}]({i['family']}/README.md) | {i['title']} | {i['points']} | "
                     + ", ".join(f"`{q}`" for q in i["answers"]) + " | "
                     + ", ".join(pct(v) for v in i["error_band_p95"].values()) + f" | {i['size_kb']} KB |")
    (rel / "README.md").write_text("\n".join(lines + ["", LICENSE]), encoding="utf-8")
    print(json.dumps(index, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
