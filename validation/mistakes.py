"""Setup-mistake study: how many common setup mistakes does Studio point out, on cases where nobody has a textbook answer?

Protocol (fixed before the first run; the list and the scoring were committed before any result was seen):

- Three correct setups: a steel cantilever box (fixed end, 1000 N on the free end), the bundled L-bracket STEP file
  (back face fixed to a wall, 200 N on the end of the other leg) and the thermal block (100 °C and 20 °C on opposite ends).
- Each mistake changes one thing in one correct setup. The list covers the usual groups of setup errors: units and
  magnitudes, supports, loads, materials, mesh and the type of analysis. Mistakes we expected Studio to miss are in the
  list on purpose.
- Each setup is checked (validate_case), then solved with the default preview solver, then solved again with the mesh
  study (check_convergence), the way a careful user would.
- A value refused where it is typed in (outside the allowed range) counts as pointed out.
- A mistake counts as pointed out when a message appears that does not appear on the correct setup in the same step:
  a check (error, warning or note), a warning on the result, a gate that fails, or a run that stops with an error.
  The comparison with a textbook answer is never counted, because the user's own part does not have one.
- Every row is published with the codes of the messages, including the misses. Whether a message names the actual
  mistake is a judgement and is left to the reader: the table shows which message appeared.

    python validation/mistakes.py                       # everything, writes validation/results/mistakes-<version>.json
    python validation/mistakes.py --only C1 L3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ["NOVASTUDIO_WORKSPACE"] = tempfile.mkdtemp(prefix="nsmis_ws_")
sys.path.insert(0, str(ROOT / "backend"))

from novastudio import __version__, commands as C, store  # noqa: E402
from novastudio.i18n import t  # noqa: E402


def q(v, u):
    return {"value": v, "unit": u}


def cantilever():
    return C.create_case("cantilever", {}, "en")["case"]["case_id"]


def bracket():
    p = ROOT / "backend/novastudio/samples/l_bracket.step"
    cid = C.import_geometry("structural", "l_bracket.step", path=str(p), lang="en")["case"]["case_id"]
    _change(cid, {"boundaries.f1.role": "fixed", "boundaries.f8.role": "load",
                  "boundaries.f8.force": q(200, "N"), "boundaries.f8.direction": "-z"})
    return cid


def block():
    return C.create_case("thermal-block", {}, "en")["case"]["case_id"]


BASES = {"C": ("Steel cantilever 200 x 20 x 20 mm, end fixed, 1000 N down on the free end", cantilever),
         "L": ("L-bracket (bundled STEP), back face fixed, 200 N down on the end of the other leg", bracket),
         "T": ("Steel block 100 x 50 x 20 mm, 100 °C and 20 °C on opposite ends", block)}

# id, group, what the user got wrong, changes to the correct setup
MISTAKES = [
    ("C1", "units", "Load typed 1000 times too large (1 000 000 N)", {"boundaries.x1.force": q(1e6, "N")}),
    ("C2", "units", "Load typed 1000 times too small (1 N)", {"boundaries.x1.force": q(1, "N")}),
    ("C3", "units", "Young's modulus in the wrong unit: 205 MPa for steel", {"materials.solid.E": q(205, "MPa")}),
    ("C4", "units", "Young's modulus 1000 times too large: 205 000 GPa", {"materials.solid.E": q(205000, "GPa")}),
    ("C5", "units", "Dimensions in metres instead of millimetres (200 m long)",
     {"geometry.params.length": q(200, "m"), "geometry.params.width": q(20, "m"), "geometry.params.height": q(20, "m")}),
    ("C6", "units", "Dimensions 1000 times too small (0.2 mm long)",
     {"geometry.params.length": q(0.2, "mm"), "geometry.params.width": q(0.02, "mm"), "geometry.params.height": q(0.02, "mm")}),
    ("C7", "supports", "No support at all", {"boundaries.x0.role": "free"}),
    ("C8", "loads", "No load", {"boundaries.x1.role": "free"}),
    ("C9", "loads", "Load pointing the wrong way (up instead of down)", {"boundaries.x1.direction": "+z"}),
    ("C10", "supports", "Support on the wrong face (a side face instead of the end)",
     {"boundaries.x0.role": "free", "boundaries.y0.role": "fixed"}),
    ("C11", "loads", "Load on the wrong face (the top face instead of the free end)",
     {"boundaries.x1.role": "free", "boundaries.z1.role": "load", "boundaries.z1.force": q(1000, "N"),
      "boundaries.z1.direction": "-z"}),
    ("C12", "supports", "Under-supported: only a symmetry plane at the end, so the beam can slide",
     {"boundaries.x0.role": "symmetry"}),
    ("C13", "materials", "Wrong material picked (aluminium instead of steel)", {"materials.solid.preset": "aluminium"}),
    ("C14", "materials", "Poisson's ratio 0.5 (incompressible) for steel", {"materials.solid.nu": q(0.5, "-")}),
    ("C15", "analysis", "Linear analysis far beyond yield (10 000 N)", {"boundaries.x1.force": q(10000, "N")}),
    ("C16", "analysis", "Linear analysis of a thin strip that bends a lot (2 mm thick, 20 N)",
     {"geometry.params.height": q(2, "mm"), "boundaries.x1.force": q(20, "N")}),
    ("C17", "mesh", "Coarse mesh", {"mesh.size": "coarse"}),
    ("C18", "analysis", "Vibration (modal) analysis with the load still set, expecting it to matter",
     {"physics.analysis": "modal"}),
    ("C19", "analysis", "Beam that is too short for beam theory (40 mm long, 20 mm high)",
     {"geometry.params.length": q(40, "mm")}),
    ("L1", "units", "Load typed 1000 times too large (200 000 N)", {"boundaries.f8.force": q(2e5, "N")}),
    ("L2", "units", "Young's modulus in the wrong unit: 205 MPa for steel", {"materials.solid.E": q(205, "MPa")}),
    ("L3", "supports", "No support at all", {"boundaries.f1.role": "free"}),
    ("L4", "supports", "Support on the wrong face (bottom of the leg instead of the wall face)",
     {"boundaries.f1.role": "free", "boundaries.f3.role": "fixed"}),
    ("L5", "loads", "Load on the wrong face (the bolt hole instead of the end)",
     {"boundaries.f8.role": "free", "boundaries.f9.role": "load", "boundaries.f9.force": q(200, "N"),
      "boundaries.f9.direction": "-z"}),
    ("L6", "loads", "Load pointing the wrong way", {"boundaries.f8.direction": "+z"}),
    ("L7", "materials", "Wrong material picked (PLA instead of steel)", {"materials.solid.preset": "pla"}),
    ("L8", "mesh", "Coarse mesh", {"mesh.size": "coarse"}),
    ("L9", "analysis", "Linear analysis far beyond yield (5000 N)", {"boundaries.f8.force": q(5000, "N")}),
    ("T1", "supports", "No temperature set anywhere (both ends insulated)",
     {"boundaries.x0.role": "insulated", "boundaries.x1.role": "insulated"}),
    ("T2", "loads", "The same temperature on both ends", {"boundaries.x1.temperature": q(100, "degC")}),
    ("T3", "units", "Temperature typed in kelvin instead of °C (100 K on the hot end)",
     {"boundaries.x0.temperature": q(100, "K")}),
    ("T4", "materials", "Conductivity 1000 times too large (50 000 W/mK)", {"materials.solid.k": q(50000, "W/mK")}),
    ("T5", "materials", "Wrong material picked (aluminium instead of steel)", {"materials.solid.preset": "aluminium"}),
    ("T6", "mesh", "Coarse mesh", {"mesh.size": "coarse"}),
]


def _change(cid, changes):
    return C.update_case(cid, store.load(cid)["revision"], changes, "en", source="mcp")


def _run(cid, study):
    """Messages from one solve: result warnings, failed gates, or the error that stopped the run."""
    try:
        r = C.check_convergence(cid, wait_s=36000, lang="en") if study else \
            C.run_simulation(cid, "preview", wait_s=36000, lang="en")
    except Exception as e:                       # refused before it started (a check error, a bad case)
        return {"stopped": f"{type(e).__name__}: {e}"[:300], "codes": ["stopped"]}
    res = r.get("results")
    if not res:
        job = r.get("job") or {}
        return {"stopped": str(job.get("error") or job.get("status") or r)[:300], "codes": ["stopped"]}
    g = res["gates"]
    codes = sorted({w["code"] for w in res["warnings"]})
    codes += [f"gate:{k}" for k in ("ran", "converged") if not g.get(k)]
    if study and g.get("verified_by") == "mesh" and not g.get("verified"):
        codes.append("gate:mesh")
    cards = {c["key"]: c.get("value") for c in res["cards"]}
    return {"codes": codes, "messages": {w["code"]: w["message"] for w in res["warnings"]}, "gates": g,
            "cards": {k: cards[k] for k in list(cards)[:6]}}


def study(cid):
    v = C.validate_case(cid, "en")
    out = {"checks": [f"{i['level']}:{i['code']}" for i in v["items"]],
           "check_messages": {i["code"]: i["message"] for i in v["items"]}, "setup": v.get("setup", [])}
    if not v["ready"]:
        return out                                # the user cannot solve it: the check error is the message
    out["run"] = _run(cid, False)
    case = store.load(cid)                       # the mesh study is for static stress and heat conduction
    out["study"] = _run(cid, True) if case["physics"].get("analysis", "static") in ("static", "linear-static") else None
    return out


def new_codes(row, base):
    """Messages on the mistaken setup that the correct setup did not show in the same step."""
    found = [c for c in row["checks"] if c not in base["checks"]]
    for step in ("run", "study"):
        mine, ref = row.get(step), base.get(step)
        if mine:
            found += [f"{step}:{c}" for c in mine["codes"] if not ref or c not in ref["codes"]]
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--label", default=__version__, help="version label for the output file (e.g. 0.7.7-dev)")
    a = ap.parse_args()
    out = HERE / "results" / f"mistakes-{a.label}.json"
    doc = {"version": a.label, "date": time.strftime("%Y-%m-%d"), "bases": {}, "rows": []}
    bases = {}
    for key, (title, make) in BASES.items():
        t0 = time.time()
        bases[key] = study(make())
        doc["bases"][key] = dict(bases[key], title=title, wall_s=round(time.time() - t0, 1))
        print(f"base {key}: {bases[key]['checks']} run={bases[key].get('run', {}).get('codes')} "
              f"study={(bases[key].get('study') or {}).get('codes')}", flush=True)
    for mid, group, what, changes in MISTAKES:
        if a.only and mid not in a.only:
            continue
        t0 = time.time()
        row = {"id": mid, "base": mid[0], "group": group, "mistake": what, "changes": changes}
        try:
            cid = BASES[mid[0]][1]()
            try:
                _change(cid, changes)
            except C.StudioError as e:           # the value is refused where it is typed in
                row.update(checks=[], refused=t(e.key, "en", **getattr(e, "kw", {})), new=[f"input:{getattr(e, 'key', 'refused')}"], pointed_out=True)
            else:
                row.update(study(cid))
                row["new"] = new_codes(row, bases[mid[0]])
                row["pointed_out"] = bool(row["new"])
        except Exception as e:
            row.update(error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
        row["wall_s"] = round(time.time() - t0, 1)
        print(f"{mid:4s} {'YES' if row.get('pointed_out') else 'no ' if 'error' not in row else 'ERR'} "
              f"{row.get('new', row.get('error'))}  {row['wall_s']}s", flush=True)
        doc["rows"].append(row)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    n = [r for r in doc["rows"] if "error" not in r]
    print(f"pointed out {sum(r['pointed_out'] for r in n)} of {len(n)} -> {out}")


if __name__ == "__main__":
    main()
