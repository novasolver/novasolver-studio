"""Gmsh worker. Always runs in its own process:  python -m novastudio.mesh_worker <job.json>

job.json: {"kind": "box"|"box2d"|"channel2d", "dims": [Lx, Ly, Lz] (m), "size": "coarse"|"normal"|"fine",
           "volume": bool, "order": 1|2, "out": "<dir>"}
Writes <out>/display.json (per-face triangles for the viewer) and, if volume, <out>/mesh.npz.
Faces are identified by bounding box position (x0 ... z1), never by Gmsh's internal numbering.
"""
from __future__ import annotations

import json
import math
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


def import_stl(gmsh, path: str, scale: float, remesh: bool = True) -> list[list[int]]:
    """Triangulated surface (e.g. exported from Blender) -> solid: split into faces by feature angle,
    rebuild a geometry that can be remeshed, and close it into one volume. scale converts file units to metres.
    remesh=False keeps the file's own triangles as the surface mesh (fallback when remeshing the surface fails).
    Returns the surfaces of each user-visible face."""
    gmsh.merge(path)
    if scale != 1.0:
        gmsh.model.mesh.affineTransform([scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0])
    gmsh.model.mesh.removeDuplicateNodes()
    xyz = np.asarray(gmsh.model.mesh.getNodes()[1]).reshape(-1, 3)
    remesh_flat_regions(gmsh, max_edge=0.01 * float(np.linalg.norm(np.ptp(xyz, axis=0))))
    gmsh.model.mesh.classifySurfaces(40 * math.pi / 180, True, remesh, math.pi)
    if remesh:
        gmsh.model.mesh.createGeometry()
    surfs = [t for _, t in gmsh.model.getEntities(2)]
    if not surfs:
        raise RuntimeError("NO_SOLID: the STL contains no surface")
    groups = stl_face_groups(gmsh, surfs)
    loop = gmsh.model.geo.addSurfaceLoop([s for g in groups for s in g])
    gmsh.model.geo.addVolume([loop])
    gmsh.model.geo.synchronize()
    return groups


def weld_vertices(xyz: np.ndarray, tris: np.ndarray, tol: float):
    """Exporters leave vertices a fraction of a micrometre apart (the STL of a gear had 2,560 edges under 1 um).
    The mesher then splits those needle triangles forever. Merge vertices closer than tol and drop the triangles
    that collapse."""
    from scipy.spatial import cKDTree
    pairs = cKDTree(xyz).query_pairs(tol, output_type="ndarray")
    parent = np.arange(len(xyz))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    root = np.array([find(i) for i in range(len(xyz))])
    tris = root[tris]
    tris = tris[(tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 2] != tris[:, 0])]
    _, first = np.unique(np.sort(tris, axis=1), axis=0, return_index=True)    # a collapse can leave twins
    tris = tris[np.sort(first)]
    used, tris = np.unique(tris, return_inverse=True)
    return xyz[used], tris.reshape(-1, 3)

def remesh_flat_regions(gmsh, max_edge: float, interior: float | None = None) -> None:
    """CAD and Blender exporters triangulate flat faces into long slivers (a gear side becomes fans of near-collinear
    triangles from the bore to the teeth). Re-parametrising those for remeshing cuts them into hundreds of thin
    patches whose new meshes overlap. So every large flat region is re-triangulated here first, in a scratch model,
    as a plane surface whose outline keeps the original vertices: the shape and its seams stay exactly the same."""
    ent = gmsh.model.getEntities(2)
    ntags, coords, _ = gmsh.model.mesh.getNodes()
    xyz = np.asarray(coords).reshape(-1, 3)
    idx = {int(t): i for i, t in enumerate(ntags)}
    tris = np.concatenate([np.array([idx[int(n)] for n in nodes], dtype=np.int64).reshape(-1, 3)
                           for _, s in ent for et, nodes in zip(*gmsh.model.mesh.getElements(2, s)[::2]) if et == 2])
    xyz, tris = weld_vertices(xyz, tris, 1e-5 * float(np.linalg.norm(np.ptp(xyz, axis=0))))
    ntags = np.arange(1, len(xyz) + 1)
    nrm = np.cross(xyz[tris[:, 1]] - xyz[tris[:, 0]], xyz[tris[:, 2]] - xyz[tris[:, 0]])
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    unit = nrm / np.maximum(2 * area, 1e-300)[:, None]
    key = lambda p, q: (p, q) if p < q else (q, p)
    owner = {}
    for t, (a, b, c) in enumerate(tris):
        for p, q in ((a, b), (b, c), (c, a)):
            owner.setdefault(key(int(p), int(q)), []).append(t)
    parent = list(range(len(tris)))

    def find(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t
    # STL coordinates are float32, so the normals of slivers are noisy. Two neighbours are coplanar when the far
    # vertex of the worse-shaped one lies on the plane of the better-shaped one (float32 noise is ~1e-8 of the size,
    # the step between facets of a curved face is far larger than the 1e-6 tolerance).
    l2 = sum(np.sum((xyz[tris[:, i]] - xyz[tris[:, (i + 1) % 3]]) ** 2, axis=1) for i in range(3))
    quality = 4 * np.sqrt(3) * area / np.maximum(l2, 1e-300)
    tol = 1e-6 * float(np.linalg.norm(np.ptp(xyz, axis=0)))
    cos1 = math.cos(math.radians(1))
    for (p, q), ts in owner.items():
        if len(ts) != 2:
            continue
        a, b = sorted(ts, key=lambda t: -quality[t])        # a = better shaped
        far = [x for x in tris[b] if x != p and x != q][0]
        # a folded sliver (normal flipped: the exporter's triangulation overlaps itself) still belongs to the
        # flat face; the re-triangulation below removes the fold
        if abs(np.dot(xyz[far] - xyz[p], unit[a])) < tol and (abs(np.dot(unit[a], unit[b])) > cos1 and (np.dot(unit[a], unit[b]) > 0 or quality[b] < 0.05)):
            parent[find(a)] = find(b)
    regions = {}
    for t in range(len(tris)):
        regions.setdefault(find(t), []).append(t)
    new_xyz = [p for p in xyz]
    keep = np.ones(len(tris), bool)
    added = []
    big = [m for m in regions.values() if area[m].sum() > 50 * max_edge ** 2]
    for members in big:
        n = unit[max(members, key=lambda t: area[t])]
        folded = bool(np.any(unit[members] @ n < 0))
        if not folded and float(np.median(quality[members])) >= 0.2:
            continue                                     # already well shaped: leave the exporter's triangles alone
        mset = set(members)
        # outline = edges used once inside the region, oriented as in the region's triangles
        nxt = {}
        for t in members:
            a, b, c = (int(x) for x in tris[t])
            for p, q in ((a, b), (b, c), (c, a)):
                if sum(1 for o in owner[key(p, q)] if o in mset) == 1:
                    nxt[p] = q
        loops, seen = [], set()
        for s0 in nxt:
            if s0 in seen:
                continue
            loop, v = [], s0
            while v not in seen:
                seen.add(v); loop.append(v); v = nxt.get(v, s0)
            loops.append(loop)
        e1 = np.cross(n, [1, 0, 0] if abs(n[0]) < 0.9 else [0, 1, 0]); e1 /= np.linalg.norm(e1)
        e2 = np.cross(n, e1)
        o = xyz[loops[0][0]]
        uv = lambda i: (float(np.dot(xyz[i] - o, e1)), float(np.dot(xyz[i] - o, e2)))

        def signed_area(loop):
            p = np.array([uv(i) for i in loop])
            return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))
        loops.sort(key=lambda l: -abs(signed_area(l)))
        cur = gmsh.model.getCurrent()
        gmsh.model.add("_flat")
        try:
            ptag, curve_loops = {}, []
            for loop in loops:
                for i in loop:
                    ptag[i] = gmsh.model.geo.addPoint(*uv(i), 0)
                lines = [gmsh.model.geo.addLine(ptag[loop[k]], ptag[loop[(k + 1) % len(loop)]]) for k in range(len(loop))]
                curve_loops.append(gmsh.model.geo.addCurveLoop(lines))
            surf = gmsh.model.geo.addPlaneSurface(curve_loops)
            gmsh.model.geo.synchronize()
            for _, c in gmsh.model.getEntities(1):
                gmsh.model.mesh.setTransfiniteCurve(c, 2)      # keep the outline vertices exactly
            saved = {name: gmsh.option.getNumber(name) for name in ("Mesh.MeshSizeMax", "Mesh.MeshSizeMin",
                                                          "Mesh.MeshSizeExtendFromBoundary", "Mesh.MeshSizeFromPoints")}
            # interior at max_edge: do not let the fine outline spacing spread inwards
            gmsh.option.setNumber("Mesh.MeshSizeMax", interior or max_edge)
            gmsh.option.setNumber("Mesh.MeshSizeMin", 0)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            try:
                gmsh.model.mesh.generate(2)
            finally:
                for name, val in saved.items():
                    gmsh.option.setNumber(name, val)
            back = {}
            for i, pt in ptag.items():
                back[int(gmsh.model.mesh.getNodes(0, pt)[0][0])] = i
            tn, tc, _ = gmsh.model.mesh.getNodes(2, surf)
            for k, t_ in enumerate(tn):
                u_, v_ = tc[3 * k], tc[3 * k + 1]
                back[int(t_)] = len(new_xyz)
                new_xyz.append(o + u_ * e1 + v_ * e2)
            _, _, enodes = gmsh.model.mesh.getElements(2, surf)
            if not enodes:
                raise RuntimeError(f"flat face remesh failed: {len(members)} triangles, loops {[len(l) for l in loops]}, area {area[members].sum():.3g}")
            ft = np.array([back[int(x)] for x in enodes[0]], dtype=np.int64).reshape(-1, 3)
        finally:
            gmsh.model.remove()
            gmsh.model.setCurrent(cur)
        pts = np.array(new_xyz)
        fn = np.cross(pts[ft[:, 1]] - pts[ft[:, 0]], pts[ft[:, 2]] - pts[ft[:, 0]])
        flip = fn @ n < 0
        ft[flip] = ft[flip][:, ::-1]
        keep[members] = False
        added.append(ft)
    tris = np.concatenate([tris[keep]] + added)
    used, tris = np.unique(tris, return_inverse=True)          # drop vertices no triangle uses any more
    allp = np.array(new_xyz)[used]
    gmsh.model.removeEntities(ent)
    s = gmsh.model.addDiscreteEntity(2)
    gmsh.model.mesh.addNodes(2, s, list(range(1, len(allp) + 1)), allp.ravel().tolist())
    gmsh.model.mesh.addElementsByType(s, 2, [], (tris.ravel() + 1).tolist())

def surface_triangles(gmsh, tag: int):
    """Node tags (sorted), their coordinates and the triangles (as indices into them) of one surface's mesh."""
    ntags, coords, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)
    ntags = np.asarray(ntags, dtype=np.int64)
    xyz = np.asarray(coords).reshape(-1, 3)
    order = np.argsort(ntags)
    ntags, xyz = ntags[order], xyz[order]
    tris = []
    for et, nodes in zip(*gmsh.model.mesh.getElements(2, tag)[::2]):
        npe = gmsh.model.mesh.getElementProperties(et)[3]
        tris.append(np.asarray(nodes, dtype=np.int64).reshape(-1, npe)[:, :3])
    tri = np.searchsorted(ntags, np.concatenate(tris)) if tris else np.zeros((0, 3), np.int64)
    return ntags, xyz, tri


def thin_wall_sizes(gmsh, h: float, n_through: float, flip: set | None = None):
    """Local wall thickness from the (outward-oriented) surface triangles: for each sampled triangle, the nearest
    triangle on an opposite-facing wall straight behind it. Returns (points, sizes) where a thin wall needs a size
    below h so that n_through elements fit across it (a 1.2 mm fin, a 5 mm spanner handle), or None."""
    from scipy.spatial import cKDTree
    ntags, coords, _ = gmsh.model.mesh.getNodes()
    if len(ntags) == 0:
        return None
    xyz = np.asarray(coords).reshape(-1, 3)
    order = np.argsort(ntags)
    tags_sorted = np.asarray(ntags, dtype=np.int64)[order]
    tris = []
    for _, s in gmsh.model.getEntities(2):
        for et, nodes in zip(*gmsh.model.mesh.getElements(2, s)[::2]):
            npe = gmsh.model.mesh.getElementProperties(et)[3]
            tt = np.asarray(nodes, dtype=np.int64).reshape(-1, npe)[:, :3]
            tris.append(tt[:, ::-1] if flip and s in flip else tt)      # inward-meshed CAD faces turned outward
    if not tris:
        return None
    tri = order[np.searchsorted(tags_sorted, np.concatenate(tris))]
    a, b, c = xyz[tri[:, 0]], xyz[tri[:, 1]], xyz[tri[:, 2]]
    nv = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(nv, axis=1)
    ok = area > 0
    P, N = ((a + b + c) / 3)[ok], (nv[ok] / (2 * area[ok])[:, None])
    step = max(1, len(P) // 40000)
    S, SN = P[::step], N[::step]
    thick = np.full(len(S), np.inf)
    dirs = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], float)
    dirs = np.vstack([dirs, np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) / np.sqrt(3)])
    sbin = np.argmax(SN @ dirs.T, axis=1)
    for k, d in enumerate(dirs):
        mine = np.flatnonzero(sbin == k)
        cand = np.flatnonzero(N @ d < -0.5)                # walls facing the other way
        if len(mine) == 0 or len(cand) == 0:
            continue
        tree = cKDTree(P[cand])
        dist, j = tree.query(S[mine], k=min(8, len(cand)))
        dist, j = np.atleast_2d(dist.T).T, np.atleast_2d(j.T).T
        q = P[cand][j]                                      # (m, k, 3)
        v = q - S[mine][:, None, :]
        along = -np.einsum("mkd,md->mk", v, SN[mine])       # depth behind the wall
        lateral = np.linalg.norm(v + along[..., None] * SN[mine][:, None, :], axis=2)
        good = (along > 0) & (lateral < 0.6 * along + 1e-12)
        t = np.where(good, along, np.inf).min(axis=1)
        thick[mine] = np.minimum(thick[mine], t)
    size = np.clip(thick / n_through, h * 0.02, h)
    keep = size < 0.9 * h
    if keep.any():                             # edges and chamfers fake very thin "walls": floor at 0.4 x the 10th percentile
        size = np.maximum(size, 0.4 * np.percentile(size[keep], 10))
    if not keep.any():
        return None
    return S[keep], size[keep]


def entity_size_caps(gmsh) -> dict:
    """Largest sensible element size per discrete curve and surface of a remeshed STL: a short curve gets at least two
    segments, a narrow face (a 0.5 mm chamfer strip next to a fin) elements no wider than itself. Without this,
    remeshing tiny faces at the general size makes their new boundaries cross ("overlapping facets")."""
    caps, length = {}, {}
    for _, c in gmsh.model.getEntities(1):
        xyz = np.asarray(gmsh.model.mesh.getNodes(1, c, includeBoundary=True)[1]).reshape(-1, 3)
        if len(xyz) < 2:
            continue
        length[c] = float(np.linalg.norm(np.ptp(xyz, axis=0)))
        caps[(1, c)] = max(length[c] / 2, 1e-9)
    for _, s in gmsh.model.getEntities(2):
        area, _ = face_area_centroid(gmsh, s, True)
        per = sum(length.get(abs(c), 0.0) for _, c in gmsh.model.getBoundary([(2, s)], oriented=False))
        if area > 0 and per > 0:
            caps[(2, s)] = 2 * area / per
    return caps


def cad_inward_faces(gmsh) -> set:
    """Surface-mesh a CAD model and return the faces whose triangles point into the solid (gmsh meshes OCC faces
    along their own parametrisation, not necessarily outward): probe a point just off one triangle of each face."""
    gmsh.model.mesh.generate(2)
    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
    eps = 1e-4 * float(np.linalg.norm([xmax - xmin, ymax - ymin, zmax - zmin]))
    vols = [v for _, v in gmsh.model.getEntities(3)]
    inward = set()
    for _, s in gmsh.model.getEntities(2):
        ntags, xyz, tri = surface_triangles(gmsh, s)
        if len(tri) == 0:
            continue
        a, b, c = xyz[tri[0, 0]], xyz[tri[0, 1]], xyz[tri[0, 2]]
        n = np.cross(b - a, c - a)
        if not np.linalg.norm(n):
            continue
        p = (a + b + c) / 3 + eps * n / np.linalg.norm(n)
        if any(gmsh.model.isInside(3, v, list(p)) for v in vols):
            inward.add(s)
    return inward


def stl_face_groups(gmsh, surfs: list[int]) -> list[list[int]]:
    """classifySurfaces also cuts smooth regions into patches (a face with holes is not a disk). Join patches whose
    shared curve is flat (normals within 15 deg) so the user sees one face per CAD-like face."""
    normal = {}                                   # surface -> (sorted node tags, summed triangle normal per node)
    for s in surfs:
        ntags, xyz, tri = surface_triangles(gmsh, s)
        nv = np.cross(xyz[tri[:, 1]] - xyz[tri[:, 0]], xyz[tri[:, 2]] - xyz[tri[:, 0]])
        acc = np.zeros_like(xyz)
        for k in range(3):
            np.add.at(acc, tri[:, k], nv)
        normal[s] = (ntags, acc)

    def summed(s, nodes):
        ntags, acc = normal[s]
        i = np.clip(np.searchsorted(ntags, nodes), 0, len(ntags) - 1)
        return acc[i[ntags[i] == nodes]].sum(0)
    parent = {s: s for s in surfs}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s
    for _, c in gmsh.model.getEntities(1):
        up, _ = gmsh.model.getAdjacencies(1, c)
        up = [int(u) for u in up if int(u) in normal]
        if len(up) != 2:
            continue
        cn = np.asarray(gmsh.model.mesh.getNodes(1, c, includeBoundary=True)[0], dtype=np.int64)
        na, nb = summed(up[0], cn), summed(up[1], cn)
        la, lb = np.linalg.norm(na), np.linalg.norm(nb)
        if la and lb and np.dot(na, nb) / la / lb > np.cos(np.radians(15)):
            parent[find(up[0])] = find(up[1])
    groups = {}
    for s in surfs:
        groups.setdefault(find(s), []).append(s)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])

def face_area_centroid(gmsh, tag: int, discrete: bool):
    """Area [m2] and centroid of a face: exact from the CAD kernel, or from its triangles for STL input."""
    if not discrete:
        return gmsh.model.occ.getMass(2, tag), list(gmsh.model.occ.getCenterOfMass(2, tag))
    _, xyz, tri = surface_triangles(gmsh, tag)
    a, b, c = xyz[tri[:, 0]], xyz[tri[:, 1]], xyz[tri[:, 2]]
    ar = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    area = float(ar.sum())
    return area, ((ar[:, None] * (a + b + c) / 3).sum(0) / area).tolist() if area > 0 else [0.0, 0.0, 0.0]

def body_volume_centroid(gmsh, tag: int, discrete: bool):
    """Volume [m3] and centroid of a body; for STL input from its closed surface (divergence theorem)."""
    if not discrete:
        return gmsh.model.occ.getMass(3, tag), list(gmsh.model.occ.getCenterOfMass(3, tag))
    vol, acc = 0.0, np.zeros(3)
    for _, s in gmsh.model.getBoundary([(3, tag)], oriented=True):
        _, xyz, tri = surface_triangles(gmsh, abs(s))
        a, b, c = xyz[tri[:, 0]], xyz[tri[:, 1]], xyz[tri[:, 2]]
        v = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6 * (1 if s > 0 else -1)
        vol += float(v.sum())
        acc += (v[:, None] * (a + b + c) / 4).sum(0)
    return float(abs(vol)), (acc / vol).tolist() if vol else [0.0, 0.0, 0.0]

def main(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    try:
        mesh_job(job)
    except Exception as e:                       # noqa: BLE001
        # remeshing a faceted STL surface can produce overlapping boundary facets (gmsh) on some shapes; the
        # file's own triangles are a valid closed surface, so fall back to filling the volume behind them
        stl = job["kind"] == "import" and job["file"].lower().endswith(".stl")
        if not stl or job.get("stl_keep_surface") or not job.get("volume"):
            raise
        print(f"surface remeshing failed ({e}); keeping the STL triangles", file=sys.stderr, flush=True)
        job["stl_keep_surface"] = True
        mesh_job(job)


def mesh_job(job: dict) -> None:
    import gmsh

    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    gmsh.initialize(["", "-nopopup"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("studio")
        keys = {}
        face_info = []
        if job["kind"] == "import":
            stl = job["file"].lower().endswith(".stl")
            if stl:
                groups = import_stl(gmsh, job["file"], float(job.get("stl_scale", 1e-3)), not job.get("stl_keep_surface"))
            else:
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
            if not stl:
                groups = [[tag] for _, tag in sorted(gmsh.model.getEntities(2), key=lambda e: e[1])]
            diag_ref = float(np.linalg.norm([lx, ly, lz]))
            for n, group in enumerate(groups, start=1):
                if job.get("domain"):
                    break
                tag = group[0]
                up, _ = gmsh.model.getAdjacencies(2, tag)
                parts = [face_area_centroid(gmsh, g, stl) for g in group]
                area = sum(a for a, _ in parts)
                cen = (sum(a * np.array(c) for a, c in parts) / area).tolist() if area else parts[0][1]
                k = f"f{tag}"
                if job.get("stl_keep_surface") and job.get("faces_ref"):
                    # the fallback splits the surface differently: keep the face names the case already uses
                    k = min(job["faces_ref"], key=lambda r: np.linalg.norm(np.subtract(r["centroid"], cen))
                            + abs(r["area"] - area) / max(r["area"], area, 1e-12) * diag_ref)["key"]
                for g in group:
                    keys[g] = k
                gmsh.model.addPhysicalGroup(2, group, tag=tag, name=k)
                face_info.append({"key": k, "n": n, "area": area, "centroid": cen,
                                  "type": "Discrete" if stl else gmsh.model.getType(2, tag),
                                  "bodies": [f"b{int(v)}" for v in up], "interface": len(up) > 1})
            diag = float(np.linalg.norm([lx, ly, lz]))
            if not job.get("domain"):
                h = diag / {"coarse": 10, "normal": 18, "fine": 30}[job.get("size", "normal")] if job.get("volume") \
                    else diag / (70 if stl else 25)   # STL: no curvature sizing, so the display mesh must be finer
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)   # midside nodes on straight edges (solver matches them geometrically)
            if stl:
                # sizing from the curvature of a discrete surface follows its facets, not the shape: very slow, no gain
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
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
            dmin, dmax = job.get("refine_dist") or (job["h"] * 2, job["h"] * 12)
            gmsh.model.mesh.field.setNumber(ft, "DistMin", dmin)
            gmsh.model.mesh.field.setNumber(ft, "DistMax", dmax)
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
            body_info = [{"key": f"b{vt}", **dict(zip(("volume", "centroid"), body_volume_centroid(gmsh, vt, stl)))}
                         for _, vt in gmsh.model.getEntities(3)]
        else:
            gmsh.model.addPhysicalGroup(3, [t for _, t in gmsh.model.getEntities(3)], tag=100000, name="solid")
            body_info = []
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", job["_hmin"] * 0.5 if job.get("_hmin") else h * (0.5 if job["kind"] != "import" else 0.1))
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)   # removes near-flat slivers that stall the iterative solver
        if job.get("volume") and job.get("thin_n") and job["kind"] == "import" and not job.get("domain"):
            # thin walls (fins, handles, ribs, plates) get enough elements across, whatever the overall size
            flip = None
            if not job["file"].lower().endswith(".stl"):
                flip = cad_inward_faces(gmsh)          # CAD: mesh the surfaces once to measure, then start over
            thin = thin_wall_sizes(gmsh, h, float(job["thin_n"]), flip)
            if flip is not None:
                gmsh.model.mesh.clear()
            tree = None
            if thin is not None:
                from scipy.spatial import cKDTree
                pts, sz = thin
                tree = cKDTree(pts)
                kk = min(8, len(pts))
                job["thin_min_mm"] = float(sz.min() * 1e3)
                gmsh.option.setNumber("Mesh.MeshSizeMin", min(gmsh.option.getNumber("Mesh.MeshSizeMin"), float(sz.min()) * 0.5))
            # a faceted STL surface remeshed much coarser than its features gives crossing patch boundaries
            # ("overlapping facets"): cap the surface size per level; the interior may still be coarse
            surf_cap = job.get("surf_cap") if job["file"].lower().endswith(".stl") and not job.get("stl_keep_surface") else None
            caps = entity_size_caps(gmsh) if surf_cap else {}

            def size_cb(dim, tag, x, y, z, lc):
                s = lc
                if tree is not None:
                    d, j = tree.query((x, y, z), k=kk)
                    s = min(s, float(np.min(sz[j] + 0.5 * d)))   # grows by half the distance away from the wall
                if surf_cap and dim <= 2:
                    s = min(s, surf_cap, caps.get((dim, tag), surf_cap))
                return float(s)
            if tree is not None or surf_cap:
                gmsh.model.mesh.setSizeCallback(size_cb)
        if job.get("volume"):
            gmsh.model.mesh.generate(3)
            if job.get("order", 2) == 2:
                gmsh.model.mesh.setOrder(2)
        elif not (job["kind"] == "import" and job["file"].lower().endswith(".stl")):
            gmsh.model.mesh.generate(2)       # an STL is shown with its own (classified) triangles: exact and instant
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
