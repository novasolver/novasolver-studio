"""Genesis on a Studio case: the meshed part is the design envelope, its face conditions become grid conditions.

  envelope   cells whose centre lies inside the tet mesh
  supports   grid nodes within 0.75 cell of a fixed face (all components) / a symmetry or constraint face (one component);
             for heat, nodes on temperature faces (all at one temperature)
  loads      the consistent nodal forces of the case (same routine as the static solver) moved to the grid by trilinear
             weights, so every force component and the total are kept exactly; heat flux likewise
  keep       cells cut by a loaded or supported face (and any face the user lists) stay solid, so the interfaces
             the conditions act on survive; optionally a skin of n cells on the whole envelope
Output (job folder): genesis.json (settings, metrics, warnings, history), genesis.npz (grid densities, final part),
part.stl (closed surface). Nothing is written to results.json, so analysis results are never replaced by a Genesis run.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

from . import fem_tet10 as fe
from . import genesis as gx
from . import units
from .store import StudioError

AXES = {"x": 0, "y": 1, "z": 2}
STRUCTURAL_ROLES = {"fixed", "symmetry", "constraint", "load", "pressure", "moment", "bearing", "remote-force", "free"}
THERMAL_ROLES = {"temperature", "heat-flux", "insulated", "free"}
DEFAULTS = {"volume_fraction": 0.3, "cells": 120000, "min_member": None, "symmetry": [], "extrusion": None,
            "overhang": None, "keep_faces": [], "keep_bc_faces": True, "skin_cells": 0, "iterations": 150,
            "heat_source": None}
LIMITS = {"cells": (2000, 1500000), "iterations": (10, 400), "skin_cells": (0, 5)}


def _quantity(q, dim: str) -> float:
    """A {value, unit} (or '5 mm') of the given dimension, in SI; a bare number is refused (its unit is unknown)."""
    if isinstance(q, str):
        q = units.parse(q)
    if not isinstance(q, dict) or not isinstance(q.get("value"), (int, float)) or isinstance(q.get("value"), bool):
        raise ValueError("not a quantity")
    if units.dimension(q.get("unit", "-")) != dim:
        raise ValueError("wrong unit")
    return float(units.to_si(q))


def validate(spec: dict | None, faces: set[str]) -> dict:
    if spec is not None and not isinstance(spec, dict):
        raise StudioError("err.genesis_option", 400, option="settings (an object)")
    spec = dict(spec or {})
    unknown = set(spec) - set(DEFAULTS)
    if unknown:
        raise StudioError("err.genesis_option", 400, option=", ".join(sorted(unknown)))
    s = {**DEFAULTS, **spec}
    def bad(name):
        raise StudioError("err.genesis_option", 400, option=name)
    vf = s["volume_fraction"]
    if not isinstance(vf, (int, float)) or not 0.03 <= vf <= 0.9:
        bad("volume_fraction (0.03..0.9)")
    for k, (lo, hi) in LIMITS.items():
        if type(s[k]) is not int or not lo <= s[k] <= hi:
            bad(f"{k} ({lo}..{hi})")
    if s["min_member"] is not None:
        try:
            ok = _quantity(s["min_member"], "length") > 0
        except Exception:
            ok = False
        if not ok:
            bad("min_member ({value, unit: mm})")
    if not isinstance(s["symmetry"], list) or any(not isinstance(a, str) or a not in AXES for a in s["symmetry"]) \
            or len(set(s["symmetry"])) != len(s["symmetry"]):
        bad("symmetry (list of x/y/z)")
    if s["extrusion"] is not None and (not isinstance(s["extrusion"], str) or s["extrusion"] not in AXES):
        bad("extrusion (x/y/z)")
    if s["overhang"] is not None:
        o = s["overhang"]
        if not isinstance(o, str) or len(o) != 2 or o[0] not in "+-" or o[1] not in AXES:
            bad("overhang (+z, -x, ...: build direction)")
    if s["extrusion"] is not None and s["overhang"] is not None:
        bad("extrusion and overhang together")
    if not isinstance(s["keep_faces"], list) or any(not isinstance(f, str) or f not in faces for f in s["keep_faces"]):
        bad("keep_faces (face keys of this case)")
    if not isinstance(s["keep_bc_faces"], bool):
        bad("keep_bc_faces")
    if s["heat_source"] is not None:
        try:
            _quantity(s["heat_source"], "heat_source")
        except Exception:
            bad("heat_source ({value, unit: W/m3})")
    return s


# ------------------------------------------------------------------ geometry helpers
def tet_inverse(nodes, tets):
    X = nodes[tets[:, :4]]
    M = np.stack([X[:, 1] - X[:, 0], X[:, 2] - X[:, 0], X[:, 3] - X[:, 0]], axis=2)    # columns = edges
    return X[:, 0], np.linalg.inv(M)


def inside_mesh(points, nodes, tets, chunk=200000):
    """True where a point lies in some tet (barycentric test against the nearest tets by centroid)."""
    o, Minv = tet_inverse(nodes, tets)
    cen = nodes[tets[:, :4]].mean(axis=1)
    tree = cKDTree(cen)
    k = min(32, len(tets))
    out = np.zeros(len(points), bool)
    for s in range(0, len(points), chunk):
        P = points[s:s + chunk]
        d, idx = tree.query(P, k=k)
        if k == 1:
            d, idx = d[:, None], idx[:, None]
        lam = np.einsum("nkij,nkj->nki", Minv[idx], P[:, None, :] - o[idx])
        ok = (lam >= -1e-9).all(axis=2) & (lam.sum(axis=2) <= 1 + 1e-9)
        out[s:s + chunk] = ok.any(axis=1)
    # the nearest centroids can all belong to small tets next to a large one that holds the point (graded meshes):
    # a point inside tet T lies within T's centroid-to-corner radius, so test every such tet for the remaining points
    rad = np.linalg.norm(nodes[tets[:, :4]] - cen[:, None], axis=2).max(axis=1)
    if len(tets) > k:
        d0, _ = tree.query(points, k=1)
        todo = np.nonzero(~out & (d0 <= rad.max()))[0]
        for s in range(0, len(todo), 2000):
            ids = todo[s:s + 2000]
            for i, cand in zip(ids, tree.query_ball_point(points[ids], rad.max())):
                cand = np.asarray(cand, int)
                if not len(cand):
                    continue
                cand = cand[np.linalg.norm(cen[cand] - points[i], axis=1) <= rad[cand]]
                lam = np.einsum("kij,kj->ki", Minv[cand], points[i] - o[cand])
                if ((lam >= -1e-9).all(axis=1) & (lam.sum(axis=1) <= 1 + 1e-9)).any():
                    out[i] = True
    return out


def sample_faces(nodes, tri, spacing):
    """Points on the triangles (corners of tri6) no further than `spacing` apart, with the area each one stands for."""
    P = nodes[tri[:, :3]]
    edge = np.linalg.norm(P[:, [1, 2, 0]] - P, axis=2).max(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    # subdivision from the spacing (a fixed cap left a large mesh triangle as scattered point supports on a fine
    # grid); 1000 per edge bounds a degenerate input at 500k points per triangle
    n = np.clip(np.ceil(edge / spacing), 1, 1000).astype(int)
    pts, wts = [], []
    for m in np.unique(n):
        sel = n == m
        a, b = np.meshgrid(np.arange(m + 1), np.arange(m + 1), indexing="ij")
        keep = a + b <= m
        a, b = a[keep] / m, b[keep] / m
        c = 1 - a - b
        Q = (c[None, :, None] * P[sel, None, 0] + a[None, :, None] * P[sel, None, 1] + b[None, :, None] * P[sel, None, 2])
        pts.append(Q.reshape(-1, 3))
        wts.append(np.repeat(area[sel] / len(a), len(a)))
    return np.concatenate(pts), np.concatenate(wts)


def trilinear(grid, P):
    """Cell index and the 8 corner weights of points P in the grid."""
    rel = (P - grid["origin"]) / grid["h"]
    c = np.clip(np.floor(rel).astype(int), 0, np.array(grid["shape"]) - 1)
    f = np.clip(rel - c, 0, 1)
    w = np.stack([(f[:, 0] if cx else 1 - f[:, 0]) * (f[:, 1] if cy else 1 - f[:, 1]) * (f[:, 2] if cz else 1 - f[:, 2])
                  for cx, cy, cz in gx._CORNER], axis=1)
    nodes = np.stack([gx.node_index(grid["shape"], c[:, 0] + cx, c[:, 1] + cy, c[:, 2] + cz) for cx, cy, cz in gx._CORNER], axis=1)
    return c, nodes, w


# ------------------------------------------------------------------ setup
def precheck(case: dict, lang: str | None = None) -> str:
    """Case-level limits of Genesis, checked from the case alone (no mesh), so a request that cannot run is refused
    at once with its reason instead of failing inside the job. Returns the physics ('elastic' / 'thermal')."""
    from .templates import get as template
    kind = template(case["template"])["physics"]
    if kind not in ("structural", "thermal"):
        raise StudioError("err.genesis_scope", 400, what=kind)
    physics = "thermal" if kind == "thermal" else "elastic"
    roles = {f: b["role"] for f, b in case["boundaries"].items()}
    allowed = STRUCTURAL_ROLES if physics == "elastic" else THERMAL_ROLES
    bad = sorted({r for r in roles.values() if r not in allowed})
    if bad:
        if lang:                                         # role names as the user sees them in the boundary list
            from .i18n import t
            bad = [t(f"role.{r}", lang) for r in bad]
        raise StudioError("err.genesis_scope", 400, what=", ".join(bad))
    if case.get("contacts") and any(c.get("type", "bonded") != "bonded" for c in case["contacts"].values()):
        raise StudioError("err.genesis_scope", 400, what="contact")
    if physics == "thermal":
        temps = set()
        for b in case["boundaries"].values():
            if b["role"] == "temperature":
                try:
                    temps.add(round(float(units.to_si(b["temperature"])), 9))
                except Exception:
                    pass                                     # an unreadable value is reported by the case checks
        if len(temps) > 1:
            raise StudioError("err.genesis_temperatures", 400)
    return physics


def build(case: dict, m: dict, spec: dict, prog=lambda *a: None) -> tuple[gx.Genesis, dict]:
    from .templates import element_prop, element_k
    physics = precheck(case)
    nodes = m["nodes"]
    tets = fe.canonical_tets(nodes, m["tets"])
    if physics == "elastic":
        E, nu = element_prop(case, m, "E"), element_prop(case, m, "nu")
        if np.ndim(E) or np.ndim(nu):
            if np.ptp(E) > 0 or np.ptp(nu) > 0:
                raise StudioError("err.genesis_scope", 400, what="multi-material")
            E, nu = float(np.ravel(E)[0]), float(np.ravel(nu)[0])
    else:
        k = element_k(case, m)
        if np.ndim(k) and np.ptp(k) > 0:
            raise StudioError("err.genesis_scope", 400, what="multi-material")
        E, nu = float(np.ravel(k)[0]), 0.3

    # grid: cell size from the part volume and the requested number of cells inside it
    vol = float(np.abs(np.linalg.det(np.stack([nodes[tets[:, i]] - nodes[tets[:, 0]] for i in (1, 2, 3)], axis=2))).sum() / 6)
    h = (vol / spec["cells"]) ** (1 / 3)
    lo, hi = nodes.min(axis=0), nodes.max(axis=0)
    shape = np.array(gx.grid_shape(np.ceil((hi - lo) / h).astype(int) + 2, 3 if physics == "elastic" else 1))
    center = (lo + hi) / 2
    origin = center - shape * h / 2                        # grid centred on the part: symmetric parts stay symmetric
    grid = {"shape": tuple(int(s) for s in shape), "h": float(h), "origin": origin}
    if np.prod(shape) > gx.MAX_ELEMENTS:
        raise StudioError("err.genesis_option", 400, option=f"cells (grid {tuple(shape)} too large)")
    prog("genesis.voxelising", 0.04)
    I = np.indices(shape).reshape(3, -1).T
    centres = origin + (I + 0.5) * h
    active = inside_mesh(centres, nodes, tets).reshape(shape)
    body = active.copy()                     # cells whose centre is in the part (faces with conditions add a layer)
    if active.sum() < 500:
        raise StudioError("err.genesis_option", 400, option="cells (too few cells inside the part)")

    nn = int(np.prod(shape + 1))
    dpn = 3 if physics == "elastic" else 1
    fixed = np.zeros((nn, dpn), bool)
    keep = np.zeros(shape, bool)
    bc_cells = np.zeros(shape, bool)
    load = np.zeros((nn, dpn))
    info = {"faces": {}}
    node_xyz = None

    def face_cells(tri):
        P, w = sample_faces(nodes, tri, 0.5 * h)
        c, _, _ = trilinear(grid, P)
        mask = np.zeros(shape, bool)
        mask[c[:, 0], c[:, 1], c[:, 2]] = True
        return P, w, mask

    def near_nodes(P, cells):
        nonlocal node_xyz
        if node_xyz is None:
            J = np.indices(shape + 1).reshape(3, -1).T
            node_xyz = origin + J * h
        cand = np.unique(np.stack([gx.node_index(grid["shape"], *(np.argwhere(cells) + np.array(o)).T)
                                   for o in gx._CORNER]).ravel())
        d, _ = cKDTree(P).query(node_xyz[cand])
        return cand[d <= 0.75 * h]

    if physics == "elastic":
        from .run_worker import structural_loads, symmetry_rollers
        fixed_tris, tractions = structural_loads(case, m)
        rollers = symmetry_rollers(case, m)
        fmesh = fe.surface_forces(nodes, tractions) if tractions else np.zeros((len(nodes), 3))
        for face, b in case["boundaries"].items():
            tri = m.get(f"face_{face}")
            if tri is None or b["role"] == "free":
                continue
            P, w, cells = face_cells(tri)
            bc_cells |= cells
            active |= cells
            if b["role"] == "fixed":
                fixed[near_nodes(P, cells)] = True
            info["faces"][face] = b["role"]
        for tri, comp in rollers:
            P, w, cells = face_cells(tri) if tri.ndim == 2 and tri.shape[1] >= 3 else (nodes[np.ravel(tri)], None, None)
            if cells is None:                            # single-node constraint of a beam clamp
                _, nd, ww = trilinear(grid, P)
                fixed[nd[np.arange(len(nd)), np.argmax(ww, axis=1)], comp] = True
                continue
            fixed[near_nodes(P, cells), comp] = True
        used = np.nonzero(np.abs(fmesh).sum(axis=1) > 0)[0]
        if len(used):
            c, nd, ww = trilinear(grid, nodes[used])
            active[c[:, 0], c[:, 1], c[:, 2]] = True; bc_cells[c[:, 0], c[:, 1], c[:, 2]] = True
            for c in range(3):
                np.add.at(load[:, c], nd.ravel(), (ww * fmesh[used, c][:, None]).ravel())
        info["applied_n"] = fmesh.sum(axis=0).tolist()
        if spec["heat_source"] is not None:
            raise StudioError("err.genesis_option", 400, option="heat_source (heat cases only)")
        if case.get("physics", {}).get("gravity", {}).get("enabled") or case.get("physics", {}).get("rotation", {}).get("enabled"):
            info["ignored"] = ["body_loads"]
        if not all(fixed[:, c].any() for c in range(3)):
            raise StudioError("err.genesis_supports", 400)
    else:
        from .run_worker import thermal_groups
        fixed_t, fluxes, conv, _ = thermal_groups(case, m)
        if conv:
            raise StudioError("err.genesis_scope", 400, what="convection")
        temps = {round(T, 9) for _, T in fixed_t}
        if len(temps) != 1:
            raise StudioError("err.genesis_temperatures", 400)
        T0 = temps.pop()
        info["sink_k"] = T0
        for face, b in case["boundaries"].items():
            tri = m.get(f"face_{face}")
            if tri is None or b["role"] in ("free", "insulated"):
                continue
            P, w, cells = face_cells(tri)
            bc_cells |= cells; active |= cells
            if b["role"] == "temperature":
                fixed[near_nodes(P, cells), 0] = True
            elif b["role"] == "heat-flux":
                q = units.to_si(b["flux"])
                c, nd, ww = trilinear(grid, P)
                np.add.at(load[:, 0], nd.ravel(), (ww * (q * w)[:, None]).ravel())
            info["faces"][face] = b["role"]
        if spec["heat_source"] is not None:
            qv = units.to_si(spec["heat_source"])
            en = gx.Level(grid["shape"], h, 1, np.zeros((8, 8)), np.zeros(nn, bool)).enodes_all
            cells = np.nonzero(active.ravel())[0]
            np.add.at(load[:, 0], en[cells].ravel(), qv * h ** 3 / 8)
        if not np.any(load):
            raise StudioError("err.genesis_no_load", 400)
        info["heat_in_w"] = float(load.sum())
    if not np.any(load):
        raise StudioError("err.genesis_no_load", 400)

    if spec["keep_bc_faces"]:
        keep |= bc_cells
    for face in spec["keep_faces"]:
        tri = m.get(f"face_{face}")
        if tri is not None:
            keep |= face_cells(tri)[2]; active |= face_cells(tri)[2]
    if spec["skin_cells"]:
        inner = ndimage.binary_erosion(active, iterations=spec["skin_cells"])
        keep |= active & ~inner

    # symmetry: the grid is centred on the part, so a symmetric part gives a symmetric envelope up to round-off at
    # a few boundary cells; keep the common part and report how much was trimmed
    sym = [AXES[a] for a in spec["symmetry"]]
    for a in sym:
        merged = active & np.flip(active, a)
        info.setdefault("symmetry_trimmed", {})["xyz"[a]] = float((active & ~merged).sum() / active.sum())
        active = merged
        keep &= active
    if spec["extrusion"] is not None:
        a = AXES[spec["extrusion"]]
        # the grid pads the part: a prism is a full column over the part's extent along the axis, not the grid's.
        # The extent is that of the part body: the cells added for faces with conditions can reach one layer beyond
        # it (a face point in a cell whose centre is outside), which made every column look short (cantilever along
        # y at 12k cells: body 10 cells wide, end faces 12). Columns full over the body's extent become the prism
        # over the whole extent including that layer, so no support or load is cut off.
        def extent(mask):
            occ = mask.any(axis=tuple(i for i in range(3) if i != a))
            s = np.zeros(shape[a], bool)
            if occ.any():
                s[np.argmax(occ):len(occ) - np.argmax(occ[::-1])] = True
            return s
        core, span = extent(body & active), extent(active)
        if not core.any():
            raise StudioError("err.genesis_extrusion", 400, axis=spec["extrusion"])
        full = np.compress(core, active, axis=a).all(axis=a, keepdims=True)       # columns filled over the body
        prism = np.broadcast_to(full, shape) & span.reshape([-1 if i == a else 1 for i in range(3)])
        info["extrusion_trimmed"] = float((active & ~prism).sum() / active.sum())
        if prism.sum() < 0.5 * active.sum():
            raise StudioError("err.genesis_extrusion", 400, axis=spec["extrusion"])
        active = prism.copy()
        keep &= active
    if spec["overhang"]:
        info["build_direction"] = spec["overhang"]
    # loads and heat on grid nodes that no cell holds any more (trimmed by symmetry / extrusion) would be dropped
    # by the solver without a word: refuse instead
    live = np.zeros(nn, bool)
    en = gx.Level(grid["shape"], h, 1, np.zeros((8, 8)), np.zeros(nn, bool)).enodes_all
    live[np.unique(en[np.nonzero(active.ravel())[0]])] = True
    lost = float(np.abs(load[~live]).sum() / max(np.abs(load).sum(), 1e-300))
    if lost > 1e-6:
        raise StudioError("err.genesis_load_outside", 400, share=f"{100 * lost:.3g}")
    if not all(fixed[live][:, c].any() for c in range(dpn)):
        raise StudioError("err.genesis_supports", 400)

    g = gx.Genesis(grid["shape"], h, physics=physics, E=E, nu=nu, active=active, solid=keep,
                   fixed=fixed.ravel(), loads=load.ravel(), origin=origin, plate_from=body)
    # a requested thinnest member m: filter radius m cells. Measured on a 48x16x24 cantilever at 30 %: radius 3
    # left 17 % of the volume thinner than 3 cells, radius 1.5 left 46 %. The filter does not guarantee the size;
    # the result is measured and the warning reports members below 70 % of m. The eroded (robust) design helped
    # on that case (6 %) but made a 32x12x16 one worse (32 % against 23 %), so it is not used here
    r_cells, target, erode = 1.5, None, None
    if spec["min_member"] is not None:
        target = _quantity(spec["min_member"], "length") / h
        if target > gx.MAX_FILTER_CELLS:
            # the filter is a direct convolution: its cost grows with r^3 (r = 10 cells: 1.4 s a pass, ~35 passes a step)
            raise StudioError("err.genesis_min_member", 400, max_mm=f"{1e3 * gx.MAX_FILTER_CELLS * h:.3g}")
        r_cells = max(1.5, target)
    settings = gx.Settings(volume_fraction=float(spec["volume_fraction"]), filter_radius=float(r_cells),
                           eta_erode=erode, min_member_cells=target,
                           iterations=spec["iterations"], symmetry=tuple(sym),
                           extrusion=AXES[spec["extrusion"]] if spec["extrusion"] else None,
                           overhang=(AXES[spec["overhang"][1]], 1 if spec["overhang"][0] == "+" else -1) if spec["overhang"] else None)
    info.update(grid={"shape": list(grid["shape"]), "cell_m": h, "origin_m": origin.tolist()},
                cells_active=int(active.sum()), cells_kept=int(keep.sum()), part_volume_m3=vol)
    return g, {"settings": settings, "info": info, "physics": physics}


# ------------------------------------------------------------------ job
def run(req: dict, jd: Path, prog) -> dict:
    from .run_worker import _mesh_for_run
    case = req["case"]
    from .templates import face_keys
    spec = validate(req.get("genesis"), set(face_keys(case)))
    m = _mesh_for_run(case, jd, prog)
    prog("genesis.setup", 0.03)
    g, setup = build(case, m, spec, prog)
    t0 = time.time()
    stop = jd / "STOP"
    # mirror planes shared by the supports and loads are solved on the half model (same design, about half the time)
    r = gx.optimize_symmetric(g, setup["settings"], progress=lambda key, frac, args: prog(key, 0.05 + 0.85 * frac, args),
                              cancelled=stop.exists)
    if "body_loads" in setup["info"].get("ignored", []):
        r["warnings"].insert(0, "body_loads_ignored")        # gravity / rotation are not in the Genesis loads
    prog("genesis.surface", 0.93)
    P, F = g.surface()
    chk = gx.surface_checks(P, F)
    gx.write_stl(jd / "part.stl", P, F)
    step = None
    if g.s.extrusion is not None:
        # a prism: also a B-rep solid with flat faces (its section as polygons, extruded) for CAD
        prog("genesis.step", 0.95)
        from . import genesis_step
        try:
            step = genesis_step.write_step(g, jd / "part.step")
        except Exception as e:                      # the STL is the result; the STEP is a convenience
            step = {"error": f"{type(e).__name__}: {e}"[:300]}
    # per-vertex value for the viewer: density-weighted stress (structural) or temperature (thermal) of the nearest cell
    cell = np.clip(np.floor((P - g.origin) / g.h).astype(int), 0, np.array(g.shape) - 1)
    if g.physics == "elastic":
        vm = g.von_mises(g.u_final[0], g.solid_final)
        vm = ndimage.maximum_filter(vm, size=3)          # surface vertices sit on faces between solid and empty cells
        scal = vm[cell[:, 0], cell[:, 1], cell[:, 2]]
    else:
        Tn = g.u_final[0] + setup["info"]["sink_k"]
        idx = gx.node_index(g.shape, *np.clip(np.rint((P - g.origin) / g.h).astype(int), 0, np.array(g.shape)).T)
        scal = Tn[idx]
    np.savez_compressed(jd / "genesis.npz", rho=g.rho.astype(np.float32), solid=g.solid_final, active=g.active,
                        keep=g.solid, origin=g.origin, h=g.h, positions=P.astype(np.float32), indices=F.astype(np.int32),
                        scalars=scal.astype(np.float32))
    history = r.pop("history")
    out = {"kind": "genesis", "physics": g.physics, "spec": spec, "setup": setup["info"], "result": r,
           "surface": chk, "history": history, "solve_s": time.time() - t0, "step": step}
    if g.physics == "elastic":
        out["result"]["stress_estimate_note"] = "voxel"
    return out
