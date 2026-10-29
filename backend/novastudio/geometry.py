"""Geometry and meshing orchestration. Gmsh always runs in a separate worker process."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import units
from .config import STUDIO_ROOT, python_exe
from .store import StudioError, case_dir

BACKEND = STUDIO_ROOT / "backend"


def dims(case: dict) -> list[float]:
    p = case["geometry"].get("params", {})
    kind = case["geometry"]["kind"]
    if kind == "box":
        return [units.to_si(p["length"]), units.to_si(p["width"]), units.to_si(p["height"])]
    if kind == 'stacked':
        return [units.to_si(p['length']),units.to_si(p['width']),2*units.to_si(p['height'])]
    if kind == 'press_fit':
        return [units.to_si(p['outer_radius'])]*2+[units.to_si(p['height'])]
    if kind == "plate_hole":
        return [units.to_si(p["length"]), units.to_si(p["width"]), units.to_si(p["thickness"])]
    if kind == "tube":
        return [2 * units.to_si(p["b"]), 2 * units.to_si(p["b"]), units.to_si(p["length"])]
    if kind in ('shaft', 'quarter_disk'):
        r = units.to_si(p['radius'])
        return [r*(2 if kind == 'shaft' else 1)]*2 + [units.to_si(p['height'])]
    if kind == "box2d":
        s = units.to_si(p["size"])
        return [s, s, 0.12 * s]
    if kind == "import":
        (x0, y0, z0), (x1, y1, z1) = case["geometry"]["bbox"]
        return [x1 - x0, y1 - y0, z1 - z0]
    if kind == "channel2d":
        L, g = units.to_si(p["length"]), units.to_si(p["gap"])
        return [L, g, 0.5 * g]
    raise ValueError(kind)


MESHER_VERSION = 17        # bump whenever mesh_worker sizing rules change, so existing meshes are regenerated


def _canon(o):
    """200, 200.0 and 2e2 must hash the same: numbers become floats with 12 significant digits."""
    if isinstance(o, dict):
        return {k: _canon(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_canon(v) for v in o]
    if isinstance(o, (int, float)) and not isinstance(o, bool):
        return float(f"{float(o):.12g}")
    return o


def mesh_key(case: dict) -> str:
    """Hash of everything the mesh depends on; a mismatch means the mesh is stale."""
    extra = {}
    if case["template"] in ("import-flow", "import-conjugate"):   # mesh size follows the inlet/outlet faces
        from .flow3d import mesh_size
        extra = {"h": round(mesh_size(case), 9)}
    if case.get("flow"):                           # external-flow domain follows the flow direction
        extra = {"domain": external_domain(case)}
    if case.get("bodies"):
        extra["bodies"] = {b: i["role"] for b, i in case["bodies"].items()}
    if case["template"] == "import-structural":       # the loaded faces decide where the mesh is fine
        extra["refine"] = sorted(k for k, b in case.get("boundaries", {}).items() if b.get("role") in LOAD_ROLES)
    src = json.dumps(_canon({"g": case["geometry"], "m": case["mesh"], "x": extra, "v": MESHER_VERSION}), sort_keys=True)
    return hashlib.sha256(src.encode()).hexdigest()[:16]


def worker_job(case: dict, **kw) -> dict:
    job = {"kind": case["geometry"]["kind"], "dims": dims(case) if case["geometry"]["kind"] != "import" else [0, 0, 0]}
    if case["geometry"]["kind"] == "import":
        job["file"] = str(case_dir(case["case_id"]) / case["geometry"]["file"])
        if job["file"].lower().endswith(".stl"):
            from .commands import STL_UNITS
            job["stl_scale"] = STL_UNITS[case["geometry"].get("units", "mm")]
            if case["geometry"].get("faces"):       # lets a fallback surface keep the case's face names
                job["faces_ref"] = [{"key": f["key"], "centroid": f["centroid"], "area": f["area"]}
                                    for f in case["geometry"]["faces"]]
            # the import's own triangles with their face keys: the remeshed surface is labelled from them
            job["faces_display"] = str(case_dir(case["case_id"]) / "geom" / "display.json")
    if case["geometry"]["kind"] == "plate_hole":
        job["hole_d"] = units.to_si(case["geometry"]["params"]["hole"])
    if case["geometry"]["kind"] == "tube":
        job["a"] = units.to_si(case["geometry"]["params"]["a"])
        job["b"] = units.to_si(case["geometry"]["params"]["b"])
    if case['geometry']['kind'] in ('shaft', 'quarter_disk'):
        job['radius'] = units.to_si(case['geometry']['params']['radius'])
    if case['geometry']['kind'] == 'press_fit':
        job['radius'] = units.to_si(case['geometry']['params']['radius'])
    job.update(kw)
    return job


def _run_worker(job: dict, timeout: int = 300) -> None:
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    jf = out / "mesh_job.json"
    jf.write_text(json.dumps(job), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(BACKEND))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    from .config import worker_argv
    p = subprocess.run(worker_argv("novastudio.mesh_worker", str(jf)), cwd=str(BACKEND if BACKEND.is_dir() else STUDIO_ROOT), env=env,
                       capture_output=True, text=True, timeout=timeout, creationflags=flags)
    if p.returncode != 0:
        tail = [l for l in (p.stderr or p.stdout or "").strip().splitlines() if l.strip() and "***" not in l][-3:]
        if any("NO_SOLID" in l for l in tail):
            raise StudioError("err.no_solid", 400)
        raise StudioError("err.mesh", 500, detail=" | ".join(tail) or f"exit code {p.returncode}")


def display(case: dict) -> dict:
    """Per-face triangles for the viewer. Uses the volume mesh surface when it is current, else a light surface mesh."""
    d = case_dir(case["case_id"])
    key = mesh_key(case)
    meshdir = d / "mesh"
    if not case.get("flow") and (meshdir / "display.json").is_file() and (meshdir / "key.txt").is_file() \
            and (meshdir / "key.txt").read_text() == key:
        return json.loads((meshdir / "display.json").read_text(encoding="utf-8"))
    gdir = d / "geom"
    gkey = hashlib.sha256(json.dumps(_canon(case["geometry"]), sort_keys=True).encode()).hexdigest()[:16]
    if not ((gdir / "display.json").is_file() and (gdir / "key.txt").is_file() and (gdir / "key.txt").read_text() == gkey):
        _run_worker(worker_job(case, size="normal", volume=False, order=1, out=str(gdir)), timeout=180)
        (gdir / "key.txt").write_text(gkey)
    return json.loads((gdir / "display.json").read_text(encoding="utf-8"))


def mesh_state(case: dict) -> dict:
    """{'exists', 'stale', 'stats'} for the case's current volume mesh (structural) or grid (CFD)."""
    if case["mesh"]["method"] == "structured":
        from .cavity_fd import GRID
        n = GRID[case["mesh"]["size"]]
        return {"exists": True, "stale": False, "stats": {"nodes": n * n, "elements": (n - 1) ** 2, "element_type": "grid"}}
    meshdir = case_dir(case["case_id"]) / "mesh"
    if not (meshdir / "mesh_stats.json").is_file():
        return {"exists": False, "stale": False, "stats": None}
    stale = not (meshdir / "key.txt").is_file() or (meshdir / "key.txt").read_text() != mesh_key(case)
    return {"exists": True, "stale": stale, "stats": json.loads((meshdir / "mesh_stats.json").read_text())}


def external_domain(case: dict) -> dict:
    """Tunnel around the body: 5 body lengths upstream, 10 downstream, 5 to each side."""
    d = case["flow"]["direction"]
    return {"axis": "xyz".index(d[1]), "sign": 1 if d[0] == "+" else -1, "up": 5.0, "down": 10.0, "side": 5.0}


def mesh_dir(case: dict) -> Path:
    """Where this case snapshot keeps its mesh. Convergence studies use a private folder per mesh level."""
    return Path(case["_mesh_dir"]) if case.get("_mesh_dir") else case_dir(case["case_id"]) / "mesh"


LOAD_ROLES = ("load", "pressure", 'moment', 'bearing', 'remote-force')
# elements across the thinnest wall of an imported solid: bending needs more than conduction; the three sizes keep a
# clear ratio (about 2, then 1.6) so the convergence study sees the trend; small ratios make the GCI inconclusive
THIN_THROUGH = {"import-structural": 2.0, "import-thermal": 1.2, "import-electrostatic": 1.2, "import-current": 1.2}
THIN_LEVEL = {"coarse": 0.5, "normal": 1.0, "fine": 1.6}
STL_SURF_DIV = 40                     # STL surface triangles at the normal level: min(diagonal / this, thinnest wall)
STL_SURF_FACTOR = {"coarse": 1.6, "normal": 1.0, "fine": 0.7}   # x that size per convergence level
REFINE_DIVS = {"coarse": 50, "normal": 100, "fine": 160}     # element size near loaded faces = diagonal / this
REFINE_LEVEL = {"coarse": 1.6, "normal": 1.0, "fine": 0.625}  # x the size set on a face (mesh.refine) per level


def structural_refinement(case: dict) -> dict:
    """Imported parts under load: stress peaks next to where the load goes in (a gear tooth root under its tip load,
    a bracket corner under its bolt). Mesh fine around the loaded faces, coarse far away; the three sizes keep a
    ratio of about 1.6 so the convergence study still sees a clean refinement sequence."""
    if case["template"] != "import-structural":
        return {}
    faces = sorted(k for k, b in case.get("boundaries", {}).items() if b.get("role") in LOAD_ROLES)
    if not faces:
        return {}
    diag = float(sum(d * d for d in dims(case)) ** 0.5)
    return {"refine_faces": faces, "h": diag / REFINE_DIVS[case["mesh"]["size"]],
            "refine_dist": [0.08 * diag, 0.3 * diag]}


def generate_mesh(case: dict) -> dict:
    if case["mesh"]["method"] == "structured":
        return mesh_state(case)["stats"]
    meshdir = mesh_dir(case)
    from .box_mesh import DIVISIONS,write
    if case['template'] in DIVISIONS:
        meshdir.mkdir(parents=True,exist_ok=True)
        stats = write(case,meshdir)
        (meshdir/'key.txt').write_text(mesh_key(case))
        return stats
    kw = {}
    if case["template"] == "import-flow":
        from .flow3d import mesh_size
        kw = {"msh": True, "h": mesh_size(case)}
    if case.get("flow"):
        kw = {"msh": True, "domain": external_domain(case)}
    if case.get("bodies"):
        from .flow3d import mesh_size
        fluid = {b for b, i in case["bodies"].items() if i["role"] == "fluid"}
        near = [f["key"] for f in case["geometry"]["faces"] if set(f.get("bodies", [])) & fluid]
        kw = {"msh": True, "h": mesh_size(case), "refine_faces": near}   # fine around the water, coarse elsewhere
    kw.update(structural_refinement(case))
    if case["mesh"].get("refine"):                  # element size the user set on chosen faces (a fillet, a notch)
        kw["refine_spots"] = [{"faces": [face], "h": units.to_si(q) * REFINE_LEVEL[case["mesh"]["size"]]}
                              for face, q in sorted(case["mesh"]["refine"].items())]
    if case["template"] in THIN_THROUGH:          # imported solids: enough elements across thin walls
        # never coarser than the wall itself: a surface element wider than a fin cannot be remeshed
        kw["thin_n"] = max(1.0, THIN_THROUGH[case["template"]] * THIN_LEVEL[case["mesh"]["size"]])
        if case["geometry"].get("file", "").lower().endswith(".stl"):
            diag = float(sum(d * d for d in dims(case)) ** 0.5)
            kw["surf_cap"] = diag / STL_SURF_DIV                      # base surface size (normal level)
            kw["surf_factor"] = STL_SURF_FACTOR[case["mesh"]["size"]]
    if case["template"] == "import-flow" and case["geometry"].get("file", "").lower().endswith(".stl"):
        # the STL's own triangles can be coarser than the channel (4 triangles on a 5 mm inlet): remesh the surface
        # at the flow cell size, which already follows the inlet's hydraulic diameter and the mesh level
        kw["surf_cap"], kw["surf_factor"] = kw["h"], 1.0
    _run_worker(worker_job(case, size=case["mesh"]["size"], volume=True, order=case["mesh"].get("order", 2),
                           out=str(meshdir), **kw), timeout=900)
    (meshdir / "key.txt").write_text(mesh_key(case))
    return json.loads((meshdir / "mesh_stats.json").read_text())
