"""STEP solid of an extruded Genesis part: its section as straight-edged polygons, extruded through OpenCASCADE.

A part optimised with the extrusion constraint is a prism. Its section (the cell field averaged along the axis) is
contoured at the 0.5 level, each ring is simplified to straight edges (Douglas-Peucker, tolerance a fraction of a
cell), small islands and holes are dropped, and the polygons are extruded over the part's span. The result is a
B-rep solid with flat faces that CAD programs edit like any sketch-and-extrude part. Coordinates are written in
millimetres (the unit the STEP writer declares).

Runs gmsh, so it is called in a worker process (the Genesis job), never in the server process."""
from __future__ import annotations

import math

import numpy as np

from . import genesis as gx


def section(g):
    """(field 2D, axes (a, b, c), span lo/hi along a in cells) of a finished extruded design."""
    a = g.s.extrusion
    b, c = [i for i in range(3) if i != a]
    f = gx.surface_field(g)                                    # the STL's field: analysed cells >= 0.6, outside <= 0.4
    occ = g.active.any(axis=(b, c))
    lo, hi = int(np.argmax(occ)), int(len(occ) - np.argmax(occ[::-1]))
    sec = np.moveaxis(f, a, 0)[lo:hi].mean(axis=0)            # (n_b, n_c)
    return sec, (a, b, c), (lo, hi)


def _dp(P, tol):
    """Douglas-Peucker on an open polyline (iterative)."""
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        d = P[j] - P[i]
        n = math.hypot(*d)
        seg = P[i + 1:j] - P[i]
        dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / n if n > 0 else np.hypot(seg[:, 0], seg[:, 1])
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return P[keep]


def simplify_ring(R, tol):
    """Closed ring (no repeated end point) -> fewer vertices, split at the two farthest points so it stays closed."""
    if len(R) < 4:
        return R
    i = 0
    j = int(np.argmax(np.hypot(*(R - R[i]).T)))
    A = _dp(np.vstack([R[i:j + 1]]), tol)
    B = _dp(np.vstack([R[j:], R[:1]]), tol)
    return np.vstack([A[:-1], B[:-1]])


def area(R):
    x, y = R[:, 0], R[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def self_intersects(rings):
    """True when any two non-adjacent edges of the rings cross (a simplified ring can fold over itself)."""
    E = []
    for r, R in enumerate(rings):
        n = len(R)
        E += [(r, k, R[k], R[(k + 1) % n], n) for k in range(n)]
    for x in range(len(E)):
        r1, k1, p1, p2, n1 = E[x]
        for y in range(x + 1, len(E)):
            r2, k2, q1, q2, _ = E[y]
            if r1 == r2 and (abs(k1 - k2) <= 1 or abs(k1 - k2) == n1 - 1):
                continue
            if max(p1[0], p2[0]) < min(q1[0], q2[0]) or max(q1[0], q2[0]) < min(p1[0], p2[0]) or \
               max(p1[1], p2[1]) < min(q1[1], q2[1]) or max(q1[1], q2[1]) < min(p1[1], p2[1]):
                continue
            d1, d2 = _cross(p1, p2, q1), _cross(p1, p2, q2)
            d3, d4 = _cross(q1, q2, p1), _cross(q1, q2, p2)
            if d1 * d2 < 0 and d3 * d4 < 0:
                return True
    return False


def _filled(sec, level):
    import contourpy
    cg = contourpy.contour_generator(z=np.pad(sec, 1), fill_type="OuterOffset")
    return cg.filled(level, 10.0)


def level_for_area(sec, target, lo=0.2, hi=0.8):
    """Contour level whose filled area (cells) is the target: the voxel part's section, so the solid keeps its volume
    (at 0.5 the contour through the cell centres cut 9 % off a coarse extruded cantilever)."""
    def net(level):
        P, O = _filled(sec, level)
        return sum(sum(area(p[o[k]:o[k + 1]][:-1]) for k in range(len(o) - 1)) for p, o in zip(P, O))
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if abs(net(mid)) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def polygons(sec, tol_cells=0.5, min_area_cells=2.0, level=0.5):
    """[(outer ring, [hole rings])] in cell units of the section grid (cell centres at i + 0.5)."""
    polys, offsets = _filled(sec, level)
    out = []
    for pts, off in zip(polys, offsets):
        # contourpy gives (column, row) = (c, b): swap to (b, c); padded index -> cell coordinates
        rings = [pts[off[k]:off[k + 1]][:-1, ::-1] - 0.5 for k in range(len(off) - 1)]
        for tol in (tol_cells, 0.5 * tol_cells, 0.25 * tol_cells, 0.0):
            rs = [simplify_ring(R, tol) if tol > 0 else R for R in rings]
            keep = [rs[0]] + [R for R in rs[1:] if abs(area(R)) >= min_area_cells and len(R) >= 3]
            if len(keep[0]) >= 3 and not self_intersects(keep):
                break
        if abs(area(keep[0])) < min_area_cells:
            continue
        outer = keep[0] if area(keep[0]) > 0 else keep[0][::-1]
        holes = [R if area(R) < 0 else R[::-1] for R in keep[1:]]
        out.append((outer, holes))
    return out


def write_step(g, path, tol_cells=0.5):
    """STEP of the extruded part. Returns {"volume_m3", "voxel_volume_m3", "faces", "polygons", "vertices"}."""
    import gmsh
    sec, (a, b, c), (lo, hi) = section(g)
    vsec = np.moveaxis(g.solid_final, a, 0)[lo:hi].mean(axis=0)
    voxel_area = float(vsec.sum())
    # between 0.4 and 0.6 the contour keeps every analysed cell and no outside one (surface_field), so matching the
    # area cannot cut a thin member off (with the old field a level of 0.53 removed a one-cell bridge)
    level = level_for_area(sec, voxel_area, lo=0.4, hi=0.6)
    polys = polygons(sec, tol_cells, level=level)
    if not polys:
        raise ValueError("empty section")
    from scipy import ndimage
    lab, n = ndimage.label(vsec > 0.5)                         # face-connected pieces of the analysed section
    size = np.bincount(lab.ravel())[1:]
    # polygons() drops pieces under about 2 cells; more polygons than pieces = a member cut through, fewer = one lost
    if not int(np.sum(size >= 3)) <= len(polys) <= n:
        raise ValueError(f"STEP section has {len(polys)} pieces, the analysed part {n}")
    mm = 1e3
    h = g.h
    gmsh.initialize(["", "-nopopup"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        # Coordinates below are millimetres. OCCT retains its internal length unit
        # after finalize(), so a previous SI import must not rescale this export.
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add("genesis")
        occ = gmsh.model.occ

        def at(u, v):
            p = np.zeros(3)
            p[a] = g.origin[a] + lo * h
            p[b] = g.origin[b] + u * h
            p[c] = g.origin[c] + v * h
            return occ.addPoint(*(p * mm))

        def loop(R):
            pts = [at(u, v) for u, v in R]
            lines = [occ.addLine(pts[k], pts[(k + 1) % len(pts)]) for k in range(len(pts))]
            return occ.addCurveLoop(lines)
        d = np.zeros(3)
        d[a] = (hi - lo) * h * mm
        vols, nv = [], 0
        for outer, holes in polys:
            s = occ.addPlaneSurface([loop(outer)] + [loop(H) for H in holes])
            nv += len(outer) + sum(len(H) for H in holes)
            vols += [t for dim, t in occ.extrude([(2, s)], *d) if dim == 3]
        if len(vols) > 1:
            occ.fuse([(3, vols[0])], [(3, t) for t in vols[1:]])
        occ.synchronize()
        nf = len(gmsh.model.getEntities(2))
        gmsh.write(str(path))
        # the written file read back: its solids must hold the polygons' volume. OCC's in-memory mass of the
        # extruded surfaces counted the holes as material, the file did not (ring 240 mm3 in gmsh and FreeCAD 1.1.4)
        gmsh.model.add("check")
        back = gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        v_file = sum(gmsh.model.occ.getMass(dim, t) for dim, t in back if dim == 3) / mm ** 3
    finally:
        gmsh.finalize()
    # the prism's volume from its polygons (exact)
    A = sum(area(o) + sum(area(H) for H in hs) for o, hs in polys)
    if abs(v_file - A * (hi - lo) * h ** 3) > 0.01 * A * (hi - lo) * h ** 3:
        raise ValueError(f"STEP solid volume {v_file:.6g} m3 differs from its section {A * (hi - lo) * h ** 3:.6g} m3")
    return {"volume_m3": A * (hi - lo) * h ** 3, "level": level, "voxel_volume_m3": float(g.solid_final.sum()) * h ** 3, "faces": nf,
            "polygons": len(polys), "vertices": nv}
