"""One solve of one family point through Studio's own commands (the same path an AI client takes over MCP).

A family module provides: dims, write_step, refine_face(faces), refine_length(p, scale), boundary_changes,
measure(C, cid, p, scale, refine_key) -> dimensional numbers, nondim(s, p, scale, force), references(p, s, nd),
NORMALISED, QUANTITIES, PARAMS, EXPECTED_DIRECTIONS, F, E, mirror_err(s)."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Studio scales a face size by 1.6 / 1.0 / 0.625 for coarse / normal / fine meshes; these keep the face size the same
# whatever the global size (a family picks a finer global mesh with MESH_SIZE for a gentler size transition)
SIZE_COMP = {"coarse": 1.0, "normal": 1.6, "fine": 2.56}
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))


def metrics(cid: str) -> dict:
    """The run's unrounded numbers (the result cards hold 4 digits: too few for a small difference from a plain strip)."""
    from novastudio import results
    return results.load(cid, None)[1]["metrics"]


def solve(fam, p: dict, level: float, scale: float = 1.0, force: float | None = None, mode: str = "preview",
          picture: Path | None = None) -> dict:
    """Coarse global mesh with the family's critical face refined to level * refine_length. The case is deleted;
    with picture, a small stress picture of it is kept (picture.py)."""
    from novastudio import commands as C, jobs
    force = fam.F if force is None else force
    size = os.environ.get("NSS_MESH_SIZE") or getattr(fam, "MESH_SIZE", "coarse")
    physics = getattr(fam, "PHYSICS", "structural")
    if mode == "preview":
        mode = getattr(fam, "MODE", mode)                           # a flow family runs its real solver at every level
    if hasattr(fam, "make_case"):                                   # a built-in template with its own graded mesh
        c, ch = fam.make_case(C, p, level, scale, force)
        ch["run.mode"] = mode
        key = None
    else:
        with tempfile.TemporaryDirectory(prefix="nss_ds_") as tmp:
            step = Path(tmp) / "part.step"
            fam.write_step(p, step, scale)
            c = C.import_geometry(physics, step.name, None, str(step), "en", units="mm")["case"]
    cid = c["case_id"]
    try:
        if not hasattr(fam, "make_case"):
            faces = [C.face_descriptor(c, f, "en") for f in c["geometry"]["faces"] if not f.get("interface")]
            key = fam.refine_face(faces)
            ch = fam.boundary_changes(faces, p, scale, force)
            if isinstance(level, str):                              # a level named by Studio's own mesh size (flow meshes)
                ch.update({"mesh.size": level, "run.mode": mode})
            else:
                ch.update({"mesh.size": size, "run.mode": mode})
                for k in (key if isinstance(key, list) else [key]):  # a part may have several critical faces
                    ch[f"mesh.refine.{k}"] = f"{level * fam.refine_length(p, scale) * SIZE_COMP[size]:.6g} mm"
            if physics == "structural":
                ch.update({"materials.solid.preset": "custom", "materials.solid.E": f"{fam.E / 1e9} GPa",
                           "materials.solid.nu": p.get("nu", getattr(fam, "NU", 0.3))})
        if hasattr(fam, "extra_changes"):                           # e.g. elastic-plastic material, load steps
            ch.update(fam.extra_changes(p, scale, force))
        C.update_case(cid, c["revision"], ch, "en", source="ai")
        t0 = time.time()
        job = C.run_simulation(cid, mode, 1.0, "en", source="ai")["job"]["job_id"]
        j = jobs.wait(job, getattr(fam, "TIMEOUT_S", 3600))
        if j["state"] not in ("done", "failed", "error", "stopped"):
            jobs.stop(job)                                          # do not leave a solver running behind a timeout
        if j["state"] != "done":
            raise RuntimeError(f"solver {j['state']}: {C.job_status(job, 'en').get('message')}")
        res = C.get_results(cid, None, "en")
        cards = {x["key"]: x["value"] for x in res["cards"]}
        out = fam.measure(C, cid, p, scale, key)
        out.update({"max_vm_mpa": cards.get("max_vm"), "max_disp_mm": cards.get("max_disp"),
                    "reaction_n": cards.get("reaction"), "nodes": int(cards.get("nodes") or 0),
                    "elements": int(cards.get("elements") or 0), "converged": bool(res["gates"].get("converged")),
                    "engine": res.get("engine"), "wall_s": round(time.time() - t0, 1)})
        if picture:
            try:
                import picture as pic
                out["picture"] = pic.save(cid, picture, getattr(fam, "VIEW", pic.VIEW), getattr(fam, "PICTURE_CROP", None))
            except Exception as e:                                  # a missing picture never loses the numbers
                out["picture"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        return out
    finally:
        try:
            C.delete_case(cid, cid, "en")
        except Exception:
            pass
