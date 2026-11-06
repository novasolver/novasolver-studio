"""Turns validation/results/mistakes-<version>.json into docs/SETUP_MISTAKES.md.

    python validation/mistakes_report.py validation/results/mistakes-0.7.6.json
"""
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    rows = [r for r in doc["rows"] if "error" not in r]
    hit = [r for r in rows if r["pointed_out"]]
    by = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["group"]][0] += r["pointed_out"]
        by[r["group"]][1] += 1
    L = [f"# Setup mistakes Studio points out — {doc['version']}", "",
         f"We took three correct setups, broke each one in a single way, and recorded what Studio said. "
         f"**{len(hit)} of {len(rows)} mistakes were pointed out; {len(rows) - len(hit)} were not.** "
         f"The list and the scoring were committed before the first run (`validation/mistakes.py`), "
         f"and every miss is in the table below.", "",
         "A mistake counts as pointed out when a message appears that the correct setup does not show in the same step: "
         "a value refused where it is typed in, a check before solving, a warning on the result, a failed gate, or a run "
         "that stops with an error. The comparison with a textbook answer is never counted, because your own part will "
         "not have one. Whether the message names the actual mistake is for you to judge: the table shows which message "
         "appeared.", "",
         "Some mistakes cannot be seen from the model alone: a load pointing the wrong way or the wrong material gives a "
         "perfectly valid answer to a different question. Those are misses here, and no checker can catch them without "
         "knowing what you meant.", "",
         "| Group | Pointed out |", "|---|---|"]
    for g, (a, n) in sorted(by.items()):
        L.append(f"| {g} | {a} of {n} |")
    general = {"peak_on_support", "stress_singular", "gate:mesh"}
    weak = [r["id"] for r in hit if all(c.split(":", 1)[1] in general for c in r["new"] if ":" in c)]
    if weak:
        L += ["", f"Our own reading: {', '.join(weak)} were pointed out only by a general warning about the peak "
              "stress (a singularity or a peak on a support). That warning does not say the support or the load is on the "
              "wrong face, so a user could easily miss the real cause. Counting those as misses gives "
              f"{len(hit) - len(weak)} of {len(rows)}."]
    L += ["", "## Correct setups", ""]
    for k, b in doc["bases"].items():
        msgs = b["checks"] + [f"run:{c}" for c in (b.get("run") or {}).get("codes", [])] + \
            [f"study:{c}" for c in (b.get("study") or {}).get("codes", [])]
        L.append(f"- **{k}**: {b['title']}. Messages on the correct setup: {', '.join(msgs) or 'none'}.")
    L += ["", "## Every mistake", "", "| | Mistake | Pointed out | New messages |", "|---|---|---|---|"]
    for r in doc["rows"]:
        if "error" in r:
            L.append(f"| {r['id']} | {r['mistake']} | not run | {r['error'][:80]} |")
            continue
        L.append(f"| {r['id']} | {r['mistake']} | {'yes' if r['pointed_out'] else '**no**'} | "
                 f"{', '.join(f'`{c}`' for c in r['new']) or '—'} |")
    shown = [r for r in rows if not r["pointed_out"] and r.get("setup")]
    if shown:
        L += ["", "## What the setup summary says for the misses", "",
              "`validate_case` also states the setup in words, so the person or the AI can compare it with what was meant. "
              "It is not a warning and is not counted above; here is the line about the changed item for each miss, so "
              "you can judge whether it would have made the mistake visible.", "",
              "| | Mistake | Setup summary |", "|---|---|---|"]
        for r in shown:
            line = next((s for s in r["setup"] if s.startswith("Material")), r["setup"][-1]) \
                if r["group"] == "materials" else r["setup"][0]
            L.append(f"| {r['id']} | {r['mistake']} | {line.replace('|', '/')} |")
    L += ["", "Prefixes: `input` refused where typed in; `error`/`warn`/`info` the check before solving; `run` the "
          "default solve; `study` the solve with the mesh study. `gate:` a gate that failed.", "",
          f"Re-run: `python validation/mistakes.py` (about an hour on a laptop). Raw results: "
          f"`validation/results/mistakes-{doc['version']}.json`.", ""]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "docs" / "SETUP_MISTAKES.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(out, f"{len(hit)}/{len(rows)}")


if __name__ == "__main__":
    main()
