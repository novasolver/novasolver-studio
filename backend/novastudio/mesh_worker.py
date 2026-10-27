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


def import_stl(gmsh, path: str, scale: float, target: float | None = None, factor: float = 1.0,
               ref_faces: list[dict] | None = None) -> tuple[list[list[int]], dict | None]:
    """Triangulated surface (e.g. exported from Blender) -> solid, split into faces by feature angle and closed
    into one volume. scale converts file units to metres. The surface triangles are the surface mesh (gmsh is not
    asked to re-parametrise and remesh a faceted surface: that fails on chamfers and tiny faces).
    For a volume mesh, the surface is first remeshed with PyMeshLab into even triangles of about `target` metres
    (or the thinnest wall if thinner, sharp edges kept), times `factor` for the convergence level.
    With ref_faces (the case's display triangles and face keys) each remeshed triangle takes the key of the face it
    lies on. Returns the surfaces of each user-visible face, and {surface: key} when labelled from ref_faces."""
    if target:
        V, F = isotropic_surface(path, scale, target, factor)
        labels = label_by_reference(V, F, ref_faces) if ref_faces else None
        if labels is not None:
            # one surface per case face: the names survive the remesh without any centroid matching
            nodes = list(range(1, len(V) + 1))
            first = None
            for key in sorted(set(labels)):
                s = gmsh.model.addDiscreteEntity(2)
                if first is None:
                    gmsh.model.mesh.addNodes(2, s, nodes, V.ravel().tolist())
                    first = s
                idx = np.flatnonzero(labels == key)
                gmsh.model.mesh.addElementsByType(s, 2, (idx + 1).tolist(), (F[idx].ravel() + 1).tolist())
            gmsh.model.mesh.createTopology()            # boundary curves and points between the faces; may renumber
            key_of, by_key = {}, {}
            for _, s in gmsh.model.getEntities(2):
                _, etags, _ = gmsh.model.mesh.getElements(2, s)
                if not len(etags) or not len(etags[0]):
                    continue
                ks, counts = np.unique(labels[np.asarray(etags[0], np.int64) - 1], return_counts=True)
                key_of[s] = str(ks[np.argmax(counts)])
                by_key.setdefault(key_of[s], []).append(s)
            loop = gmsh.model.geo.addSurfaceLoop(list(key_of))
            gmsh.model.geo.addVolume([loop])
            gmsh.model.geo.synchronize()
            return list(by_key.values()), key_of
        s = gmsh.model.addDiscreteEntity(2)
        gmsh.model.mesh.addNodes(2, s, list(range(1, len(V) + 1)), V.ravel().tolist())
        gmsh.model.mesh.addElementsByType(s, 2, [], (F.ravel() + 1).tolist())
    else:
        gmsh.merge(path)
        if scale != 1.0:
            gmsh.model.mesh.affineTransform([scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0])
        gmsh.model.mesh.removeDuplicateNodes()
        xyz = np.asarray(gmsh.model.mesh.getNodes()[1]).reshape(-1, 3)
        remesh_flat_regions(gmsh, max_edge=0.01 * float(np.linalg.norm(np.ptp(xyz, axis=0))))
    gmsh.model.mesh.classifySurfaces(40 * math.pi / 180, True, False, math.pi)
    surfs = [t for _, t in gmsh.model.getEntities(2)]
    if not surfs:
        raise RuntimeError("NO_SOLID: the STL contains no surface")
    groups = stl_face_groups(gmsh, surfs)
    loop = gmsh.model.geo.addSurfaceLoop([s for g in groups for s in g])
    gmsh.model.geo.addVolume([loop])
    gmsh.model.geo.synchronize()
    return groups, None


def label_by_reference(V: np.ndarray, F: np.ndarray, ref_faces: list[dict]) -> np.ndarray | None:
    """Face name of each triangle (V, F in metres): the name of the nearest point sampled densely over the case's
    original faces (display triangles with their keys). None if the reference does not cover this surface."""
    from scipy.spatial import cKDTree
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cen = (a + b + c) / 3
    h = float(np.median(np.linalg.norm(b - a, axis=1)))
    pts, lab = [], []
    for i, f in enumerate(ref_faces):
        P = np.asarray(f["positions"], float).reshape(-1, 3)
        T = np.asarray(f["indices"], np.int64).reshape(-1, 3)
        if len(T) == 0:
            continue
        A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
        n = np.maximum(1, np.ceil(area / (h / 4) ** 2)).astype(int)     # ~4 samples per edge length h
        r = np.random.default_rng(i).random((int(n.sum()), 2))
        flip = r.sum(1) > 1
        r[flip] = 1 - r[flip]
        idx = np.repeat(np.arange(len(T)), n)
        S = A[idx] + r[:, :1] * (B - A)[idx] + r[:, 1:] * (C - A)[idx]
        pts.append(np.vstack([S, A, B, C, (A + B + C) / 3]))
        lab.append(np.full(len(pts[-1]), i))
    if not pts:
        return None
    pts, lab = np.vstack(pts), np.concatenate(lab)
    d, j = cKDTree(pts).query(cen)
    if np.median(d) > h:                                  # reference in other units or another shape
        return None
    keys = np.array([f["key"] for f in ref_faces])
    return keys[lab[j]]


def isotropic_surface(path: str, scale: float, target: float, factor: float = 1.0):
    """Even, well-shaped surface triangles of about `target` metres from any closed STL (PyMeshLab isotropic explicit
    remeshing, feature edges over 30 degrees kept). The base size never exceeds the thinnest walls (10th percentile
    of the measured thickness) so fins and handles keep about one triangle across; factor scales it per level."""
    import pymeshlab as pml
    ms = pml.MeshSet()
    ms.load_new_mesh(path)
    ms.meshing_remove_duplicate_vertices()
    m = ms.current_mesh()
    V0, F0 = m.vertex_matrix() * scale, m.face_matrix()
    t = target
    thick = wall_thickness(V0, F0)
    if thick is not None:
        t = min(t, float(np.percentile(thick[1], 10)))
    t *= factor
    t = max(t, 1e-4 * float(np.linalg.norm(np.ptp(V0, axis=0))))
    # Remeshing can fold triangles where two walls nearly touch (organic, topology-optimised parts), and Gmsh then
    # refuses the surface. Repair such spots locally; if that fails, retry slightly finer, else keep the input.
    bodies = ms.get_topological_measures()["connected_components_number"]
    for attempt in range(4):
        trial = pml.MeshSet()
        trial.add_mesh(pml.Mesh(m.vertex_matrix(), m.face_matrix()))     # id 0: the input, to project repairs onto
        trial.add_mesh(pml.Mesh(m.vertex_matrix(), m.face_matrix()))
        try:
            trial.meshing_isotropic_explicit_remeshing(iterations=6, targetlen=pml.PureValue(t / scale),
                                                       featuredeg=30.0, checksurfdist=True,
                                                       maxsurfdist=pml.PureValue(t / scale / 20))
            ok = repair_self_intersections(trial, bodies, source=0, edge=t / scale / 2)
        except pml.PyMeshLabException as e:                # a filter refused the mesh: treat as a failed attempt
            print(f"remesh at {t * 1e3:.3g} mm failed: {e}", flush=True)
            ok = False
        if ok:
            out = trial.current_mesh()
            return out.vertex_matrix() * scale, out.face_matrix().astype(np.int64)
        print(f"remesh at {t * 1e3:.3g} mm self-intersects; retrying finer", flush=True)
        gap = wall_thickness(V0, F0[:, ::-1]) if attempt == 0 else None   # flipped: gaps between walls
        if gap is not None:
            # triangles wider than a narrow gap (e.g. a thin solid wall between two channels of a fluid domain)
            # poke through the opposite wall: go below the narrow gaps, once
            t = min(t * 0.8, float(np.percentile(gap[1], 2)))
        else:
            t *= 0.8
    print("remesh failed; using the input triangles", flush=True)
    return V0, F0.astype(np.int64)


def folded_faces(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Triangles folded back onto a neighbour (normals more than ~155 degrees apart across a shared edge). PyMeshLab's
    self-intersection test skips edge neighbours, but Gmsh sees such a fold as overlapping facets."""
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-300
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fid = np.tile(np.arange(len(F)), 3)
    key = np.sort(E, 1)
    o = np.lexsort((key[:, 1], key[:, 0]))
    k, f = key[o], fid[o]
    same = np.all(k[1:] == k[:-1], axis=1)
    a, b = f[:-1][same], f[1:][same]
    bad = np.einsum("ij,ij->i", n[a], n[b]) < -0.9
    return np.unique(np.concatenate([a[bad], b[bad]]))


def repair_self_intersections(ms, bodies: int, source: int, edge: float, rounds: int = 5) -> bool:
    """Cut out folded or self-intersecting triangles and close the holes with triangles of about `edge`, then put
    every vertex back on the input surface (mesh `source` of ms) so a fill across a sharp corner does not shave it
    off. The cut starts with just the bad triangles and widens by one ring each round they persist. True if the result
    is closed, manifold, free of both and still has `bodies` separate bodies."""
    import pymeshlab as pml
    for r in range(rounds):
        m = ms.current_mesh()
        V, F = m.vertex_matrix(), m.face_matrix()
        bad = np.zeros(len(F))
        bad[folded_faces(V, F)] = 1.0
        ms.add_mesh(pml.Mesh(V, F, f_scalar_array=bad))
        if bad.any():
            ms.compute_selection_by_condition_per_face(condselect="fq > 0.5")
        else:
            ms.compute_selection_by_self_intersections_per_face()
            if ms.current_mesh().selected_face_number() == 0:
                break
        for _ in range(r):
            ms.apply_selection_dilatation()
        ms.meshing_remove_selected_faces()
        ms.meshing_remove_unreferenced_vertices()
        ms.meshing_repair_non_manifold_edges(method=0)     # a cut can leave edges shared by 3+ triangles;
        ms.meshing_repair_non_manifold_vertices()          # hole filling refuses such a mesh
        ms.meshing_close_holes(maxholesize=10000, selfintersection=False, refinehole=True,
                               refineholeedgelen=pml.PureValue(edge))
        ms.transfer_attributes_per_vertex(sourcemesh=source, targetmesh=ms.current_mesh_id(), geomtransfer=True)
    m = ms.current_mesh()
    ms.compute_selection_by_self_intersections_per_face()
    g = ms.get_topological_measures()
    return (ms.current_mesh().selected_face_number() == 0 and not len(folded_faces(m.vertex_matrix(), m.face_matrix()))
            and g["boundary_edges"] == 0 and g["non_two_manifold_edges"] == 0
            and g["connected_components_number"] == bodies)


def wall_thickness(V: np.ndarray, F: np.ndarray):
    """Local wall thickness of a closed, outward-oriented triangle surface: for sampled triangles, the nearest
    triangle on an opposite-facing wall straight behind it. Returns (points, thickness) for the walls where one was
    found, or None."""
    from scipy.spatial import cKDTree
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    nv = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(nv, axis=1)
    ok = area > 0
    P, N = ((a + b + c) / 3)[ok], (nv[ok] / (2 * area[ok])[:, None])
    if len(P) == 0:
        return None
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
        dist, j = cKDTree(P[cand]).query(S[mine], k=min(8, len(cand)))
        j = j.reshape(len(mine), -1)
        v = P[cand][j] - S[mine][:, None, :]
        along = -np.einsum("mkd,md->mk", v, SN[mine])       # depth behind the wall
        lateral = np.linalg.norm(v + along[..., None] * SN[mine][:, None, :], axis=2)
        good = (along > 0) & (lateral < 0.6 * along + 1e-12)
        thick[mine] = np.minimum(thick[mine], np.where(good, along, np.inf).min(axis=1))
    found = np.isfinite(thick)
    if not found.any():
        return None
    t = thick[found]
    t = np.maximum(t, 0.4 * np.percentile(t, 10))           # edges and chamfers fake very thin "walls"
    return S[found], t


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
    if not tris:
        return ntags, xyz, np.zeros((0, 3), np.int64)
    tri_tags = np.concatenate(tris)
    missing = np.setdiff1d(tri_tags, ntags)
    if len(missing):                              # a triangle can use a node classified on another entity
        gtags, gcoords, _ = gmsh.model.mesh.getNodes()
        gtags = np.asarray(gtags, dtype=np.int64)
        gxyz = np.asarray(gcoords).reshape(-1, 3)
        g = np.argsort(gtags)
        extra = gxyz[g[np.searchsorted(gtags[g], missing)]]
        ntags = np.concatenate([ntags, missing])
        xyz = np.concatenate([xyz, extra])
        order = np.argsort(ntags)
        ntags, xyz = ntags[order], xyz[order]
    return ntags, xyz, np.searchsorted(ntags, tri_tags)


def thin_wall_sizes(gmsh, h: float, n_through: float, flip: set | None = None):
    """Element sizes for thin walls of the meshed surface: (points, sizes) where a wall needs a size below h so that
    n_through elements fit across it (a 1.2 mm fin, a 5 mm spanner handle), or None. flip: CAD faces meshed inward."""
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
    found = wall_thickness(xyz, order[np.searchsorted(tags_sorted, np.concatenate(tris))])
    if found is None:
        return None
    S, thick = found
    size = np.clip(thick / n_through, h * 0.02, h)
    keep = size < 0.9 * h
    if not keep.any():
        return None
    return S[keep], size[keep]

def cad_inward_faces(gmsh) -> set:
    """Surface-mesh a CAD model and return the faces whose triangles point into the solid (gmsh meshes OCC faces
    along their own parametrisation, not necessarily outward): probe a point just off one triangle of each face."""
    gmsh.model.mesh.generate(2)
    xmin, ymin, zmin, xmax, ymax, zmax = model_bounds(gmsh)
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

def face_perimeter(gmsh, group: list[int], discrete: bool) -> float:
    """Outer boundary length [m] of a face (a group of surfaces), for the hydraulic diameter 4A/P of inlets."""
    if not discrete:
        curves = gmsh.model.getBoundary([(2, g) for g in group], combined=True, oriented=False)
        return float(sum(gmsh.model.occ.getMass(1, abs(c)) for _, c in curves))
    xs, tris = [], []
    for g in group:
        _, xyz, tri = surface_triangles(gmsh, g)
        tris.append(tri + sum(len(x) for x in xs))
        xs.append(xyz)
    xyz, tri = np.vstack(xs), np.vstack(tris)
    # merge coincident vertices of neighbouring surfaces, then keep the edges used by one triangle only
    _, inv = np.unique(np.round(xyz / max(float(np.ptp(xyz)), 1e-30), 9), axis=0, return_inverse=True)
    t = inv.reshape(-1)[tri]
    e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    edges, cnt = np.unique(e, axis=0, return_counts=True)
    first = {int(v): int(i) for i, v in enumerate(inv.reshape(-1))}
    p = np.array([xyz[first[v]] for v in range(int(inv.max()) + 1)])
    b = edges[cnt == 1]
    return float(np.linalg.norm(p[b[:, 0]] - p[b[:, 1]], axis=1).sum())


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
    mesh_job(json.loads(Path(job_path).read_text(encoding="utf-8")))


def model_bounds(gmsh) -> tuple:
    """Tight bounding box of the solids. The whole-model OCC box can be wrong: the degenerate edge at the pole of a
    revolved surface may report its pre-scaling position, and B-spline boxes include the control polygon (an egg
    shell read as 28 m long, so no tetrahedron was made). Use the triangulation-based box over the volumes."""
    gmsh.option.setNumber("Geometry.OCCBoundsUseStl", 1)
    vols = gmsh.model.getEntities(3) or gmsh.model.getEntities(2)
    boxes = np.array([gmsh.model.getBoundingBox(d, t) for d, t in vols]) if vols else None
    if boxes is None or not len(boxes):
        return gmsh.model.getBoundingBox(-1, -1)
    return (*boxes[:, :3].min(0), *boxes[:, 3:].max(0))


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
                # volume meshes: even PyMeshLab triangles at this level's size; display: the file's own triangles
                ref = None
                if job.get("volume") and job.get("faces_display") and Path(job["faces_display"]).is_file():
                    ref = json.loads(Path(job["faces_display"]).read_text(encoding="utf-8")).get("faces")
                groups, labelled = import_stl(gmsh, job["file"], float(job.get("stl_scale", 1e-3)),
                                              target=job.get("surf_cap") if job.get("volume") else None,
                                              factor=float(job.get("surf_factor", 1.0)), ref_faces=ref)
            else:
                gmsh.option.setString("Geometry.OCCTargetUnit", "M")     # CAD units -> metres
                gmsh.model.occ.importShapes(job["file"])
                raw = gmsh.model.occ.getEntities(3)
                n_before = len(raw)
                mass_before = sum(gmsh.model.occ.getMass(3, t) for _, t in raw)
                gmsh.model.occ.healShapes()
                healed = gmsh.model.occ.getEntities(3)
                mass_after = sum(gmsh.model.occ.getMass(3, t) for _, t in healed)
                if len(healed) < n_before or abs(mass_after - mass_before) > 0.01 * max(mass_before, 1e-30):
                    # healing can destroy valid solids: a single-face sphere, or a hollow shell whose inner face it
                    # drops (the shell becomes a full body). Then fall back to the raw import
                    gmsh.model.occ.remove(gmsh.model.occ.getEntities(), recursive=True)
                    gmsh.model.occ.importShapes(job["file"])
                vols = gmsh.model.occ.getEntities(3)
                if not vols:
                    raise RuntimeError("NO_SOLID: the file contains no closed solid body")
                if len(vols) > 1:
                    gmsh.model.occ.fragment(vols[:1], vols[1:])          # conformal interfaces between bodies
                gmsh.model.occ.synchronize()
            xmin, ymin, zmin, xmax, ymax, zmax = model_bounds(gmsh)
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
                if stl and labelled:
                    k = labelled[tag]
                elif stl and job.get("volume") and job.get("faces_ref"):
                    # the remeshed surface is split into new entities: keep the face names the case already uses
                    k = min(job["faces_ref"], key=lambda r: np.linalg.norm(np.subtract(r["centroid"], cen))
                            + abs(r["area"] - area) / max(r["area"], area, 1e-12) * diag_ref)["key"]
                for g in group:
                    keys[g] = k
                gmsh.model.addPhysicalGroup(2, group, tag=tag, name=k)
                try:
                    perim = face_perimeter(gmsh, group, stl)
                except Exception:                       # the perimeter only refines inlet sizing; never fail on it
                    perim = None
                face_info.append({"key": k, "n": n, "area": area, "centroid": cen, "perimeter": perim,
                                  "type": "Discrete" if stl else gmsh.model.getType(2, tag),
                                  "bodies": [f"b{int(v)}" for v in up], "interface": len(up) > 1})
            diag = float(np.linalg.norm([lx, ly, lz]))
            if not job.get("domain"):
                h = diag / {"coarse": 10, "normal": 18, "fine": 30}[job.get("size", "normal")] if job.get("volume") \
                    else diag / (70 if stl else 25)   # STL: no curvature sizing, so the display mesh must be finer
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            # CAD: midside nodes on the true surface. Straight edges facet a round bar into a polygon (a 6-sided
            # 20 mm shaft has 17 % less area, so 17 % more stress). STL has no true surface: keep them straight.
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1 if stl else 0)
            if not stl:                       # a curved midside node on a coarse element next to a small fillet can
                gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)   # fold the element (quality < 0): untangle
            if stl:
                # sizing from the curvature of a discrete surface follows its facets, not the shape: very slow, no gain
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
            bbox = [[xmin, ymin, zmin], [xmax, ymax, zmax]]
        elif job["kind"] == "tube":
            a, b, lz = job["a"], job["b"], job["dims"][2]
            lx = ly = 2 * b
            bbox = [[-b, -b, 0], [b, b, lz]]
            occ = gmsh.model.occ
            outer = occ.addCylinder(0, 0, 0, 0, 0, lz, b)
            inner = occ.addCylinder(0, 0, 0, 0, 0, lz, a)
            occ.cut([(3, outer)], [(3, inner)])
            occ.synchronize()
            for _, tag in gmsh.model.getEntities(2):
                bb = gmsh.model.getBoundingBox(2, tag)
                if gmsh.model.getType(2, tag) == "Cylinder":
                    k = "inner" if abs(bb[3] - a) < abs(bb[3] - b) else "outer"
                else:
                    k = "z0" if abs(occ.getCenterOfMass(2, tag)[2]) < lz / 2 else "z1"
                keys[tag] = k
                gmsh.model.addPhysicalGroup(2, [tag], tag=tag, name=k)
            h = (b - a) / DIVS[job.get("size", "normal")]
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
            gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)
        else:
            lx, ly, lz = job["dims"]
            bbox = [[0, 0, 0], [lx, ly, lz]]
            # OCC pads bounding boxes by its absolute precision (~1e-7 m): a 1 mm box needs the 1 um floor
            tol = max(1e-5 * max(lx, ly, lz), 1e-6)
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
        spots = list(job.get("refine_spots") or [])        # faces the user asked to mesh finer (fillets, notches)
        if job.get("refine_faces") and job.get("h"):
            # fine only near the listed faces (e.g. a water channel inside a large plate), coarse elsewhere
            spots.insert(0, {"faces": job["refine_faces"], "h": job["h"], "dist": job.get("refine_dist")})
        else:
            h = job.get("h", h)                 # caller may set the size directly (e.g. cells across a pipe inlet)
        if spots:
            fields = []
            for sp in spots:
                tags = [tg for tg, kk in keys.items() if kk in set(sp["faces"])]
                if not tags:
                    continue
                fd = gmsh.model.mesh.field.add("Distance")
                gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", tags)
                # the distance is measured to sample points on the surface (20 per direction by default): around a
                # 0.5 mm fillet on a 20 mm shaft they sat 3 mm apart, wider than the whole refinement band
                ext = max(max(b[3] - b[0], b[4] - b[1], b[5] - b[2])
                          for b in (gmsh.model.getBoundingBox(2, tg) for tg in tags))
                gmsh.model.mesh.field.setNumber(fd, "Sampling", int(min(400, max(20, 2 * ext / sp["h"]))))
                ft = gmsh.model.mesh.field.add("Threshold")
                gmsh.model.mesh.field.setNumber(ft, "InField", fd)
                gmsh.model.mesh.field.setNumber(ft, "SizeMin", sp["h"])
                gmsh.model.mesh.field.setNumber(ft, "SizeMax", h)
                dmin, dmax = sp.get("dist") or (sp["h"] * 2, sp["h"] * 12)
                gmsh.model.mesh.field.setNumber(ft, "DistMin", dmin)
                gmsh.model.mesh.field.setNumber(ft, "DistMax", dmax)
                fields.append(ft)
            if len(fields) > 1:
                fm = gmsh.model.mesh.field.add("Min")
                gmsh.model.mesh.field.setNumbers(fm, "FieldsList", fields)
                fields = [fm]
            if fields:
                gmsh.model.mesh.field.setAsBackgroundMesh(fields[0])
                gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
                job["_hmin"] = min(sp["h"] for sp in spots)
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
            if tree is not None:
                def size_cb(dim, tag, x, y, z, lc):
                    d, j = tree.query((x, y, z), k=kk)
                    return float(min(lc, np.min(sz[j] + 0.5 * d)))   # grows by half the distance away from the wall
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
