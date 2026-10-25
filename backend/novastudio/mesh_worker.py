"""Gmsh worker. Always runs in its own process:  python -m novastudio.mesh_worker <job.json>

job.json: {"kind": "box"|"box2d"|"channel2d", "dims": [Lx, Ly, Lz] (m), "size": "coarse"|"normal"|"fine",
           "volume": bool, "order": 1|2, "out": "<dir>"}
Writes <out>/display.json (per-face triangles for the viewer) and, if volume, <out>/mesh.npz.
Faces are identified by bounding box position (x0 ... z1), never by Gmsh's internal numbering.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

DIVS = {"coarse": 2, "normal": 3, "fine": 5}


def face_key(bb, dims, tol):
    xmin, ymin, zmin, xmax, ymax, zmax = bb
    for axis, (lo, hi) in enumerate(((xmin, xmax), (ymin, ymax), (zmin, zmax))):
        if abs(hi - lo) < tol:
            name = "xyz"[axis]
            return f"{name}0" if abs(lo) < tol else f"{name}1"
    return None


def build_external_domain(gmsh, job, bmin, bmax, keys) -> float:
    """Wind/water tunnel around the imported body: box minus body. Faces are grouped as inlet / outlet / sides / body.
    Mesh size is fine near the body and coarse far away (distance + threshold background field). Returns far size."""
    occ = gmsh.model.occ
    dm = job["domain"]
    axis = int(dm["axis"]); sign = 1 if dm["sign"] > 0 else -1
    L = float((bmax - bmin).max())
    lo = bmin - dm["side"] * L
    hi = bmax + dm["side"] * L
    if sign > 0:
        lo[axis] = bmin[axis] - dm["up"] * L; hi[axis] = bmax[axis] + dm["down"] * L
    else:
        hi[axis] = bmax[axis] + dm["up"] * L; lo[axis] = bmin[axis] - dm["down"] * L
    body = occ.getEntities(3)
    box = occ.addBox(*lo, *(hi - lo))
    occ.cut([(3, box)], body, removeObject=True, removeTool=True)
    occ.synchronize()
    tol = 1e-6 * float((hi - lo).max())
    groups = {"inlet": [], "outlet": [], "sides": [], "body": []}
    for _, tag in gmsh.model.getEntities(2):
        b = gmsh.model.getBoundingBox(2, tag)
        mn, mx = np.array(b[:3]), np.array(b[3:])
        name = "body"
        for ax in range(3):
            if mx[ax] - mn[ax] < tol * 10 and (abs(mn[ax] - lo[ax]) < tol * 10 or abs(mn[ax] - hi[ax]) < tol * 10):
                at_lo = abs(mn[ax] - lo[ax]) < tol * 10
                if ax == axis:
                    name = "inlet" if (at_lo and sign > 0) or (not at_lo and sign < 0) else "outlet"
                else:
                    name = "sides"
        groups[name].append(tag)
        keys[tag] = name
    for name, tags in groups.items():
        if tags:
            gmsh.model.addPhysicalGroup(2, tags, name=name)
    div = {"coarse": 16, "normal": 26, "fine": 40}[job.get("size", "normal")]
    h_body = L / div
    h_far = float((hi - lo).max()) / 18
    f1 = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(f1, "SurfacesList", groups["body"])
    gmsh.model.mesh.field.setNumber(f1, "Sampling", 60)
    f2 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(f2, "InField", f1)
    gmsh.model.mesh.field.setNumber(f2, "SizeMin", h_body)
    gmsh.model.mesh.field.setNumber(f2, "SizeMax", h_far)
    gmsh.model.mesh.field.setNumber(f2, "DistMin", 0.25 * L)
    gmsh.model.mesh.field.setNumber(f2, "DistMax", 3.0 * L)
    # wake: the region behind the body decides the pressure recovery (pressure drag); keep it reasonably fine
    wlo, whi = bmin - 0.6 * L, bmax + 0.6 * L
    if sign > 0:
        whi[axis] = bmax[axis] + 4.0 * L
    else:
        wlo[axis] = bmin[axis] - 4.0 * L
    fb = gmsh.model.mesh.field.add("Box")
    gmsh.model.mesh.field.setNumber(fb, "VIn", L / (div / 3.0))
    gmsh.model.mesh.field.setNumber(fb, "VOut", h_far)
    for k, v in zip(("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"), [*wlo, *whi]):
        gmsh.model.mesh.field.setNumber(fb, k, float(v))
    gmsh.model.mesh.field.setNumber(fb, "Thickness", L)
    fm = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(fm, "FieldsList", [f2, fb])
    gmsh.model.mesh.field.setAsBackgroundMesh(fm)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    return h_far, h_body


def main(job_path: str) -> None:
    import gmsh

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    gmsh.initialize(["", "-nopopup"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("studio")
        keys = {}
        face_info = []
        if job["kind"] == "import":
            gmsh.option.setString("Geometry.OCCTargetUnit", "M")     # CAD units -> metres
            gmsh.model.occ.importShapes(job["file"])
            n_before = len(gmsh.model.occ.getEntities(3))
            gmsh.model.occ.healShapes()
            if len(gmsh.model.occ.getEntities(3)) < n_before:
                # healing can destroy valid single-face solids (e.g. a sphere): fall back to the raw import
                gmsh.model.occ.remove(gmsh.model.occ.getEntities(), recursive=True)
                gmsh.model.occ.importShapes(job["file"])
            vols = gmsh.model.occ.getEntities(3)
            if not vols:
                raise RuntimeError("NO_SOLID: the file contains no closed solid body")
            if len(vols) > 1:
                gmsh.model.occ.fragment(vols[:1], vols[1:])          # conformal interfaces between bodies
            gmsh.model.occ.synchronize()
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            lx, ly, lz = xmax - xmin, ymax - ymin, zmax - zmin
            if job.get("domain"):
                h, job["_hmin"] = build_external_domain(gmsh, job, np.array([xmin, ymin, zmin]), np.array([xmax, ymax, zmax]), keys)
                bbox = [[xmin, ymin, zmin], [xmax, ymax, zmax]]
            for n, (dim, tag) in enumerate(sorted(gmsh.model.getEntities(2), key=lambda e: e[1]), start=1):
                if job.get("domain"):
                    break
                k = f"f{tag}"
                keys[tag] = k
                gmsh.model.addPhysicalGroup(2, [tag], tag=tag, name=k)
                up, _ = gmsh.model.getAdjacencies(2, tag)
                face_info.append({"key": k, "n": n, "area": gmsh.model.occ.getMass(2, tag),
                                  "centroid": list(gmsh.model.occ.getCenterOfMass(2, tag)),
                                  "type": gmsh.model.getType(2, tag),
                                  "bodies": [f"b{int(v)}" for v in up], "interface": len(up) > 1})
            diag = float(np.linalg.norm([lx, ly, lz]))
            if not job.get("domain"):
                h = diag / {"coarse": 10, "normal": 18, "fine": 30}[job.get("size", "normal")] if job.get("volume") else diag / 25
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)   # midside nodes on straight edges (solver matches them geometrically)
            bbox = [[xmin, ymin, zmin], [xmax, ymax, zmax]]
        else:
            lx, ly, lz = job["dims"]
            bbox = [[0, 0, 0], [lx, ly, lz]]
            tol = 1e-5 * max(lx, ly, lz)   # gmsh pads bounding boxes by ~1e-7 relative
            box = gmsh.model.occ.addBox(0, 0, 0, lx, ly, lz)
            hole_d = job.get("hole_d")
            if hole_d:                                           # plate with a central through-hole (stress concentration)
                cyl = gmsh.model.occ.addCylinder(lx / 2, ly / 2, -lz, 0, 0, 3 * lz, hole_d / 2)
                gmsh.model.occ.cut([(3, box)], [(3, cyl)])
            gmsh.model.occ.synchronize()
            for dim, tag in gmsh.model.getEntities(2):
                bb = gmsh.model.getBoundingBox(dim, tag)
                k = face_key(bb, (lx, ly, lz), tol) if gmsh.model.getType(2, tag) == "Plane" else "hole"
                if k is None:
                    raise RuntimeError(f"cannot identify face {tag} from bbox {bb}")
                keys[tag] = k
                gmsh.model.addPhysicalGroup(2, [tag], tag=tag, name=k)
            if job.get("volume") and hole_d:
                h = max(lz, ly / 8) / {"coarse": 0.8, "normal": 1.0, "fine": 1.4}[job.get("size", "normal")]
                hs = hole_d / {"coarse": 10, "normal": 16, "fine": 24}[job.get("size", "normal")]
                hole_tags = [tg for tg, kk in keys.items() if kk == "hole"]
                fd = gmsh.model.mesh.field.add("Distance")
                gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", hole_tags)
                ft = gmsh.model.mesh.field.add("Threshold")
                gmsh.model.mesh.field.setNumber(ft, "InField", fd)
                gmsh.model.mesh.field.setNumber(ft, "SizeMin", hs)
                gmsh.model.mesh.field.setNumber(ft, "SizeMax", h)
                gmsh.model.mesh.field.setNumber(ft, "DistMin", hole_d / 6)
                gmsh.model.mesh.field.setNumber(ft, "DistMax", hole_d * 1.0)
                gmsh.model.mesh.field.setAsBackgroundMesh(ft)
                job["_hmin"] = hs
            elif job.get("volume"):
                h = min(ly, lz) / DIVS[job.get("size", "normal")]
            else:
                h = min(lx, ly, lz) if job["kind"] == "box" else max(lx, ly) / 12
        if job.get("refine_faces") and job.get("h"):
            # fine only near the listed faces (e.g. a water channel inside a large plate), coarse elsewhere
            tags = [tg for tg, kk in keys.items() if kk in set(job["refine_faces"])]
            fd = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", tags)
            ft = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(ft, "InField", fd)
            gmsh.model.mesh.field.setNumber(ft, "SizeMin", job["h"])
            gmsh.model.mesh.field.setNumber(ft, "SizeMax", h)
            gmsh.model.mesh.field.setNumber(ft, "DistMin", job["h"] * 2)
            gmsh.model.mesh.field.setNumber(ft, "DistMax", job["h"] * 12)
            gmsh.model.mesh.field.setAsBackgroundMesh(ft)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            job["_hmin"] = job["h"]
        else:
            h = job.get("h", h)                 # caller may set the size directly (e.g. cells across a pipe inlet)
        if job["kind"] == "import" and not job.get("domain"):
            # one physical volume per body: gmshToFoam turns them into cellZones (b<tag>) for multi-region solvers
            for _, vt in gmsh.model.getEntities(3):
                gmsh.model.addPhysicalGroup(3, [vt], tag=100000 + vt, name=f"b{vt}")
            body_info = [{"key": f"b{vt}", "volume": gmsh.model.occ.getMass(3, vt),
                          "centroid": list(gmsh.model.occ.getCenterOfMass(3, vt))} for _, vt in gmsh.model.getEntities(3)]
        else:
            gmsh.model.addPhysicalGroup(3, [t for _, t in gmsh.model.getEntities(3)], tag=100000, name="solid")
            body_info = []
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", job["_hmin"] * 0.5 if job.get("_hmin") else h * (0.5 if job["kind"] != "import" else 0.1))
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        if job.get("volume"):
            gmsh.model.mesh.generate(3)
            if job.get("order", 2) == 2:
                gmsh.model.mesh.setOrder(2)
        else:
            gmsh.model.mesh.generate(2)
        if job.get("stl"):                      # body surface for snappyHexMesh (metres)
            gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 0)
            gmsh.write(job["stl"])
        if job.get("msh"):                      # ASCII MSH 2.2 for OpenFOAM gmshToFoam (patch names = face keys)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.option.setNumber("Mesh.Binary", 0)
            gmsh.write(str(out / "mesh.msh"))

        tags, coords, _ = gmsh.model.mesh.getNodes()
        coords = coords.reshape(-1, 3)
        index = {int(t): i for i, t in enumerate(tags)}

        display = {"dims": [lx, ly, lz], "bbox": bbox, "faces": [], "info": face_info, "bodies": body_info,
                   "volumes": len(gmsh.model.getEntities(3))}
        face_tri6 = {}
        for tag, k in keys.items():
            etypes, _, enodes = gmsh.model.mesh.getElements(2, tag)
            tris = []
            for et, nodes in zip(etypes, enodes):
                n = gmsh.model.mesh.getElementProperties(et)[3]
                conn = np.array([index[int(x)] for x in nodes], dtype=np.int64).reshape(-1, n)
                if n == 6:
                    face_tri6[k] = np.concatenate([face_tri6[k], conn]) if k in face_tri6 else conn
                    # split each 6-node triangle into 4 linear triangles for display
                    a, b, c, ab, bc, ca = conn.T
                    tris.append(np.stack([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1),
                                          np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)], 1).reshape(-1, 3))
                else:
                    face_tri6[k] = np.concatenate([face_tri6[k], conn]) if k in face_tri6 else conn
                    tris.append(conn[:, :3])
            tri = np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)
            used, inv = np.unique(tri, return_inverse=True)
            display["faces"].append({
                "id": int(tag), "key": k,
                "positions": coords[used].ravel().round(9).tolist(),
                "indices": inv.ravel().astype(int).tolist(),
            })
        (out / "display.json").write_text(json.dumps(display), encoding="utf-8")

        if job.get("volume"):
            tets, tet_body = [], []
            for _, vt in gmsh.model.getEntities(3):
                for et, nodes in zip(*gmsh.model.mesh.getElements(3, vt)[0:3:2]):
                    n = gmsh.model.mesh.getElementProperties(et)[3]
                    conn = np.array([index[int(x)] for x in nodes], dtype=np.int64).reshape(-1, n)
                    tets.append(conn)
                    tet_body.append(np.full(len(conn), vt, dtype=np.int64))
            tet = np.concatenate(tets)
            tet_body = np.concatenate(tet_body)
            np.savez_compressed(out / "mesh.npz", nodes=coords, tets=tet, tet_body=tet_body,
                                **{f"face_{k}": v for k, v in face_tri6.items()})
            q = gmsh.model.mesh.getElementQualities(gmsh.model.mesh.getElementsByType(11 if tet.shape[1] == 10 else 4)[0], "minSICN")
            stats = {"nodes": int(len(coords)), "elements": int(len(tet)), "element_type": f"tet{tet.shape[1]}",
                     "quality_min": float(np.min(q)), "quality_mean": float(np.mean(q)), "h": h}
            (out / "mesh_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    main(sys.argv[1])
