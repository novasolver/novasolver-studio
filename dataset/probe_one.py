"""Solve one L-bracket point at several mesh settings and print time and the quantities the dataset keeps
(exploration: how coarse can the mesh be for a given error).  python probe_one.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("NOVASTUDIO_WORKSPACE", str(Path(tempfile.gettempdir()) / "nss_dataset_probe"))

import l_bracket as fam                                    # noqa: E402
from novastudio import commands as C, jobs                 # noqa: E402

p = {"h_over_L": 0.7, "t_over_L": 0.08, "w_over_L": 0.5, "r_over_t": 0.75, "nu": 0.3}
step = Path(tempfile.gettempdir()) / "nss_lb_probe.step"
fam.write_step(p, step)
d = fam.dims(p)
for size, refine in (("coarse", 0.5), ("coarse", 0.25), ("coarse", 0.125), ("coarse", 0.0625)):
    r = C.import_geometry("structural", step.name, None, str(step), "en", units="mm")
    c = r["case"]
    faces = [C.face_descriptor(c, f, "en") for f in c["geometry"]["faces"] if not f.get("interface")]
    fillet = [f["key"] for f in faces if f.get("type") == "Cylinder"]
    ch = fam.boundary_changes(faces, p)
    ch.update({"materials.solid.preset": "custom", "materials.solid.E": f"{fam.E / 1e9} GPa",
               "materials.solid.nu": p["nu"], "mesh.size": size})
    if refine:
        ch[f"mesh.refine.{fillet[0]}"] = f"{refine * d['R']:.4g} mm"
    C.update_case(c["case_id"], c["revision"], ch, "en", source="ai")
    t1 = time.time()
    out = C.run_simulation(c["case_id"], "preview", 1.0, "en", source="ai")
    j = jobs.wait(out["job"]["job_id"], 1800)
    t2 = time.time()
    res = C.get_results(c["case_id"], None, "en")
    cards = {x["key"]: x["value"] for x in res["cards"]}
    pr = C.probe_results(c["case_id"], [[d["L"], d["W"] / 2, d["t"]]], None, fillet, None, "en", 1, None)
    tip = pr["points"][0]["values"]["uz"]
    fil = pr["faces"][0]["max"]["vm"]
    print(f"{size:6s} refine {refine}: {round(t2 - t1, 1):6} s  nodes {cards['nodes']:8.0f}  max_vm {cards['max_vm']:7.2f}"
          f"  fillet_vm {fil:7.2f}  tip_uz {tip:.5f}  reaction {cards['reaction']}", flush=True)
    C.delete_case(c["case_id"], c["case_id"], "en")
