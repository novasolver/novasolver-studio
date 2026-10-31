"""Validation suite: solves every built-in template that carries a reference solution and the standard benchmarks in
benchmarks.py, then writes validation/results/<version>.json. report.py turns it into the manual (docs/VALIDATION*.md).

    python validation/suite.py                     # everything (several hours: flow cases are slow)
    python validation/suite.py --quick             # templates + structural/thermal benchmarks, no mesh studies
    python validation/suite.py --only nafems-le1 cantilever
    python validation/suite.py --compare validation/results/0.6.3.json    # also flag values that moved

Runs in a private workspace, so it never touches the user's cases. Each case is independent: a failure is recorded
and the suite goes on.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ.setdefault("NOVASTUDIO_WORKSPACE", tempfile.mkdtemp(prefix="nsval_ws_"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))

from novastudio import __version__, commands as C, templates  # noqa: E402
import benchmarks as B  # noqa: E402

I18N = {l: json.loads((ROOT / "backend/novastudio/i18n" / f"{l}.json").read_text(encoding="utf-8")) for l in ("ja", "en", "zh")}
MOVED_PCT = 0.1          # a value that changed more than this since the compared release is flagged


def template_cases(study: bool):
    out = []
    for tid in templates.TEMPLATES:
        if tid.startswith("import-"):
            continue
        title = {l: I18N[l].get(f"template.{tid}.title", tid) for l in I18N}
        tests = {l: I18N[l].get(f"template.{tid}.description", "") for l in I18N}

        def run(tid=tid):
            cid = C.create_case(tid, {}, "en")["case"]["case_id"]
            r = None
            if study:
                try:
                    r = C.check_convergence(cid, wait_s=36000, lang="en")
                except Exception:                       # some kinds (modal, nonlinear, flow) have no mesh study
                    r = None
            if not r or not r.get("results"):
                # templates without a built-in preview solver (OpenFOAM only) run in final mode
                mode = "final" if any(i["code"] == "no_builtin" for i in C.validate_case(cid, "en")["items"]) else "preview"
                r = C.run_simulation(cid, mode, wait_s=36000, lang="en")
            res = r.get("results")
            if not res:
                raise RuntimeError(f"no results: {r.get('job')}")
            v = res.get("verification")
            cards = {c["key"]: c.get("value") for c in res["cards"]}
            info = {"gates": res["gates"], "elements": cards.get("elements") or cards.get("cells"),
                    "study": bool(res.get("convergence"))}
            if not v or v.get("reference") is None:
                return info, []
            return info, [{"quantity": v.get("label"), "computed": v.get("computed"), "reference": v.get("reference"),
                           "unit": v.get("unit"), "error_pct": v.get("error_pct"),
                           "error_abs": (v["computed"] - v["reference"]) if v.get("computed") is not None else None,
                           "tol_pct": v.get("tolerance_pct"), "tol_abs": None, "pass": bool(v.get("pass")),
                           "reference_label": v.get("reference_label")}]
        out.append({"id": f"template:{tid}", "physics": templates.TEMPLATES[tid].get("physics", ""), "title": title,
                    "source": I18N["en"].get(f"verify.{tid}", "built-in reference"), "tests": tests, "run": run,
                    "slow": templates.TEMPLATES[tid].get("physics") in ("cfd", "external", "conjugate")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--compare")
    ap.add_argument("--out")
    a = ap.parse_args()
    cases = template_cases(study=not a.quick) + B.CASES
    if a.quick:
        cases = [c for c in cases if not c["slow"]]
    if a.only:
        cases = [c for c in cases if c["id"] in a.only or c["id"].split(":")[-1] in a.only]
    out_path = Path(a.out) if a.out else HERE / "results" / f"{__version__}.json"
    out_path.parent.mkdir(exist_ok=True)
    doc = {"version": __version__, "date": datetime.date.today().isoformat(), "quick": a.quick,
           "machine": {"os": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count()},
           "cases": []}
    if out_path.exists() and a.only:                 # re-running some cases keeps the others
        doc["cases"] = [c for c in json.loads(out_path.read_text(encoding="utf-8"))["cases"]
                        if c["id"] not in {x["id"] for x in cases}]
    for c in cases:
        t0 = time.time()
        entry = {k: c[k] for k in ("id", "physics", "title", "source", "tests")}
        try:
            info, rows = c["run"]()
            entry.update(info=info, rows=rows, status="pass" if rows and all(r["pass"] for r in rows)
                         else "no-reference" if not rows else "fail")
        except Exception as e:
            entry.update(status="error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        entry["wall_s"] = round(time.time() - t0, 1)
        print(f"{entry['status']:12s} {c['id']:40s} {entry['wall_s']:8.1f}s", flush=True)
        doc["cases"].append(entry)
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if a.compare:
        prev = {c["id"]: c for c in json.loads(Path(a.compare).read_text(encoding="utf-8"))["cases"]}
        moved = []
        for c in doc["cases"]:
            for r in c.get("rows", []):
                old = next((x for x in prev.get(c["id"], {}).get("rows", []) if x["quantity"] == r["quantity"]), None)
                if old and old.get("computed") and r.get("computed") is not None:
                    d = (r["computed"] - old["computed"]) / abs(old["computed"]) * 100
                    if abs(d) > MOVED_PCT:
                        moved.append({"id": c["id"], "quantity": r["quantity"], "before": old["computed"],
                                      "after": r["computed"], "change_pct": d})
        doc["moved_since"] = {"version": json.loads(Path(a.compare).read_text(encoding="utf-8"))["version"], "items": moved}
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"{len(moved)} values moved more than {MOVED_PCT}% since {doc['moved_since']['version']}")
    n = {s: sum(c["status"] == s for c in doc["cases"]) for s in ("pass", "fail", "error", "no-reference")}
    print(n, "->", out_path)
    sys.exit(1 if n["fail"] or n["error"] else 0)


if __name__ == "__main__":
    main()
