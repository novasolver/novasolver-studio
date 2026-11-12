"""Reimport the actual Genesis exports and solve them with quadratic tetrahedra.

This is a release qualification of one specified specimen, not a safety certificate
for arbitrary optimised designs. Original cases/results are never changed.
Run with --out <private directory>; repeat resumes only this script's specimens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--levels", nargs="+", default=["coarse", "normal"])
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["NOVASTUDIO_WORKSPACE"] = str(out / "workspace")
    from novastudio import commands as C, store
    import numpy as np

    record = out / "qualification.json"
    d = json.loads(record.read_text(encoding="utf8")) if record.exists() else {
        "scope": "200 x 40 x 80 mm steel cantilever, 1000 N at the free end; 35% volume Genesis",
        "levels": {}, "qualified": False,
    }
    def save():
        record.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf8")
    def wait(r):
        if r.get("done"):
            return r
        jid = r.get("job_id") or r["job"]["job_id"]
        deadline = time.monotonic() + 7200
        while time.monotonic() < deadline:
            j = C.job_status(jid, "en")
            if j["state"] == "done":
                return j
            if j["state"] in ("failed", "stopped"):
                raise RuntimeError(j)
            time.sleep(2)
        raise TimeoutError(jid)

    if "source" not in d:
        c = C.create_case("cantilever", {}, "en")["case"]
        cid = c["case_id"]
        C.update_case(cid, c["revision"], {"geometry.params.width": "40 mm", "geometry.params.height": "80 mm"}, "en")
        d["source"] = cid
        save()
    cid = d["source"]
    if "genesis_run" not in d:
        print("Genesis optimisation", flush=True)
        r = wait(C.run_genesis(cid, {"volume_fraction": 0.35, "cells": 12000, "iterations": 100}, wait_s=1, lang="en"))
        g = r["genesis"]
        d["genesis_run"] = g["run_id"]
        d["genesis_summary"] = g
        save()
    for kind in ("raw", "smooth"):
        if kind in d:
            continue
        stl = Path(C.genesis_stl(cid, d["genesis_run"], smooth=kind == "smooth")["path"])
        print("Import", kind, flush=True)
        c = C.import_geometry("structural", stl.name, path=str(stl), units="m", lang="en")["case"]
        faces = c["geometry"]["faces"]
        lo = min(f["bbox"][0][0] for f in faces)
        hi = max(f["bbox"][1][0] for f in faces)
        tol = 1e-7
        ends = [[f for f in faces if abs(f["centroid"][0] - x) < tol and
                 abs(f["bbox"][1][0] - f["bbox"][0][0]) < tol] for x in (lo, hi)]
        assert all(ends), "Cannot identify the retained planar end faces; refuse approximate boundary transfer"
        area = sum(f["area"] for f in ends[1])
        ch = {"materials.solid.preset": "steel"}
        for f in ends[0]:
            ch[f"boundaries.{f['key']}.role"] = "fixed"
        for f in ends[1]:
            ch.update({f"boundaries.{f['key']}.role": "load",
                       f"boundaries.{f['key']}.force": f"{1000 * f['area'] / area:.16g} N",
                       f"boundaries.{f['key']}.direction": "-z"})
        C.update_case(c["case_id"], c["revision"], ch, "en")
        d[kind] = {"case_id": c["case_id"], "sha256": hashlib.sha256(stl.read_bytes()).hexdigest(),
                   "end_x_m": [lo, hi], "loaded_area_m2": area, "support_area_m2": sum(f["area"] for f in ends[0])}
        save()
    for level in args.levels:
        rows = d["levels"].setdefault(level, {})
        for kind in ("raw", "smooth"):
            if kind in rows:
                continue
            ic = d[kind]["case_id"]
            c = store.load(ic)
            C.update_case(ic, c["revision"], {"mesh.size": level}, "en")
            print("Solve", level, kind, flush=True)
            r = wait(C.run_simulation(ic, "preview", wait_s=1, lang="en"))
            result = r.get("results") or C.get_results(ic, lang="en")
            rows[kind] = {"gates": result.get("gates"), "cards": result.get("cards")}
            # Record exactly what is evaluated, including loads and residual checks from the solver output.
            jd = store.case_dir(ic) / "run"
            runs = [p for p in jd.glob("r_*") if (p / "results.json").exists()]
            latest = max(runs, key=lambda p: p.stat().st_mtime)
            rows[kind]["run_id"] = latest.name
            save()
    from novastudio import fem_tet10 as fe
    from novastudio.run_worker import structural_loads
    for rows in d["levels"].values():
        for kind, row in rows.items():
            jd = store.case_dir(d[kind]["case_id"]) / "run" / row["run_id"]
            req = json.loads((jd / "request.json").read_text(encoding="utf8"))
            actual = json.loads((jd / "results.json").read_text(encoding="utf8"))
            m = dict(np.load(jd / "mesh.npz"))
            z = np.load(jd / "results.npz")
            _, tractions = structural_loads(req["case"], m)
            forces = fe.surface_forces(m["nodes"], tractions)
            row["metrics"] = actual["metrics"]
            row["compliance_j"] = float(np.sum(forces * z["u"]))
            assert row["compliance_j"] > 0 and np.isfinite(row["compliance_j"])
            assert np.allclose(forces.sum(0), [0, 0, -1000], rtol=1e-8, atol=1e-6)
            assert actual["converged"], "Equilibrium failed"
    d["comparison"] = {level: {
        "compliance_change_pct": 100 * (rows["smooth"]["compliance_j"] / rows["raw"]["compliance_j"] - 1),
        "max_displacement_change_pct": 100 * (rows["smooth"]["metrics"]["max_disp_m"] / rows["raw"]["metrics"]["max_disp_m"] - 1),
    } for level, rows in d["levels"].items() if set(rows) == {"raw", "smooth"}}
    d["qualified"] = False  # mesh convergence and geometry changes require review, not just a successful exit
    save()
    print(record, flush=True)


if __name__ == "__main__":
    main()
