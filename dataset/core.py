"""One solve of one family point through Studio's own commands (the same path an AI client takes over MCP).

A family module provides: dims, write_step, refine_face(faces), refine_length(p, scale), boundary_changes,
measure(C, cid, p, scale, refine_key) -> dimensional numbers, nondim(s, p, scale, force), references(p, s, nd),
NORMALISED, QUANTITIES, PARAMS, EXPECTED_DIRECTIONS, F, E, mirror_err(s)."""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))


def solve(fam, p: dict, level: float, scale: float = 1.0, force: float | None = None, mode: str = "preview") -> dict:
    """Coarse global mesh with the family's critical face refined to level * refine_length. The case is deleted."""
    from novastudio import commands as C, jobs
    force = fam.F if force is None else force
    with tempfile.TemporaryDirectory(prefix="nss_ds_") as tmp:
        step = Path(tmp) / "part.step"
        fam.write_step(p, step, scale)
        c = C.import_geometry("structural", step.name, None, str(step), "en", units="mm")["case"]
    cid = c["case_id"]
    try:
        faces = [C.face_descriptor(c, f, "en") for f in c["geometry"]["faces"] if not f.get("interface")]
        key = fam.refine_face(faces)
        ch = fam.boundary_changes(faces, p, scale, force)
        ch.update({"materials.solid.preset": "custom", "materials.solid.E": f"{fam.E / 1e9} GPa",
                   "materials.solid.nu": p["nu"], "mesh.size": "coarse", "run.mode": mode,
                   f"mesh.refine.{key}": f"{level * fam.refine_length(p, scale):.6g} mm"})
        if hasattr(fam, "extra_changes"):                           # e.g. elastic-plastic material, load steps
            ch.update(fam.extra_changes(p, scale, force))
        C.update_case(cid, c["revision"], ch, "en", source="ai")
        t0 = time.time()
        job = C.run_simulation(cid, mode, 1.0, "en", source="ai")["job"]["job_id"]
        j = jobs.wait(job, 3600)
        if j["state"] != "done":
            raise RuntimeError(f"solver {j['state']}: {C.job_status(job, 'en').get('message')}")
        res = C.get_results(cid, None, "en")
        cards = {x["key"]: x["value"] for x in res["cards"]}
        out = fam.measure(C, cid, p, scale, key)
        out.update({"max_vm_mpa": cards.get("max_vm"), "max_disp_mm": cards.get("max_disp"),
                    "reaction_n": cards.get("reaction"), "nodes": int(cards["nodes"]),
                    "elements": int(cards["elements"]), "converged": bool(res["gates"].get("converged")),
                    "engine": res.get("engine"), "wall_s": round(time.time() - t0, 1)})
        return out
    finally:
        try:
            C.delete_case(cid, cid, "en")
        except Exception:
            pass
