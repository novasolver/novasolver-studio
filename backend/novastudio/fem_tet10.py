"""Built-in preview solver: linear elastic statics with 10-node (quadratic) tetrahedra.

Purpose: give a correct-order answer in seconds with no installation. The final run uses CalculiX.
Midside nodes are matched to edges geometrically, so the solver does not depend on a mesher's node ordering.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

EDGES = np.array([(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)])
DIRECT_LIMIT = 30000          # unknowns; above this the AMG-CG iterative solver is used
DIRECT_FALLBACK_LIMIT = 250000   # unknowns; direct solve when AMG-CG does not converge (about 2-4 GB at this size)
ASSEMBLY_CHUNK = 20000        # elements per block of element matrices (about 140 MB)


def committable_bytes() -> int | None:
    """Memory this process can still allocate: on Windows the commit limit (RAM + page file) decides when numpy raises
    MemoryError, not free RAM (a 3.8 GB solve finished with 2 GB of RAM free). None when unknown."""
    try:
        import ctypes
        import sys
        if sys.platform != "win32":
            import psutil
            return int(psutil.virtual_memory().available + psutil.swap_memory().free)

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("phys", ctypes.c_ulonglong),
                        ("avail_phys", ctypes.c_ulonglong), ("page", ctypes.c_ulonglong),
                        ("avail_page", ctypes.c_ulonglong), ("virt", ctypes.c_ulonglong),
                        ("avail_virt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        s = MS()
        s.len = ctypes.sizeof(MS)
        return int(s.avail_page) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else None
    except Exception:
        return None


# measured peak of the whole run worker (thick-sphere octant, 2026-10-28): 1.58 GB at 117k nodes, 3.84 GB at 454k
MEM_BASE = 600e6
MEM_PER_NODE = {"structural": 7.5e3, "scalar": 2.5e3}


def check_memory(n_nodes: int, kind: str) -> None:
    """Stop with a clear message before assembling a model that cannot fit, instead of a MemoryError deep in the AMG
    set-up after minutes of work."""
    # the calibration is the whole worker's peak, and the commit limit is what can still be added: subtract what this
    # process already holds (interpreter, libraries, mesh), or a small model would be refused for memory it never needs
    try:
        import psutil
        held = psutil.Process().memory_info().private
    except Exception:
        held = 0
    need = max(0.0, MEM_BASE + MEM_PER_NODE[kind] * n_nodes - held)
    have = committable_bytes()
    if have is not None and need > have:
        from .store import StudioError
        raise StudioError("err.memory", 500, need=f"{need / 1e9:.1f}", have=f"{have / 1e9:.1f}", nodes=n_nodes)


def _amg_cg(A, b, B=None, tol=1e-8):
    """Smoothed-aggregation AMG preconditioned CG. Strongly graded meshes (thin-wall and load refinement next to
    coarse regions) can make the default set-up stall, so a sturdier set-up with symmetric Gauss-Seidel smoothing
    is tried before giving up. tol 1e-8: on stiff, graded meshes CG reaches ~1e-9 and then drifts with round-off,
    so asking for 1e-10 made it run past the answer."""
    import pyamg
    setups = [
        dict(strength=("symmetric", {"theta": 0.0}), max_coarse=500),
        dict(strength=("symmetric", {"theta": 0.02}), max_coarse=1000,
             presmoother=("gauss_seidel", {"sweep": "symmetric", "iterations": 2}),
             postsmoother=("gauss_seidel", {"sweep": "symmetric", "iterations": 2}),
             smooth=("energy", {"krylov": "cg", "maxiter": 4})),
    ]
    last = None
    for kw in setups:
        ml = pyamg.smoothed_aggregation_solver(A, B=B, symmetry="symmetric", **kw)
        res = []
        x = ml.solve(b, tol=tol, accel="cg", maxiter=3000, residuals=res)
        last = res[-1] / max(res[0], 1e-300) if res else np.inf
        if np.all(np.isfinite(x)) and last <= 1e-6:
            return x
    raise RuntimeError(f"iterative solver did not converge (relative residual {last:.1e})")


GA, GB = 0.5854101966249685, 0.1381966011250105
GAUSS = np.array([[GB, GB, GB], [GA, GB, GB], [GB, GA, GB], [GB, GB, GA]])  # (xi, eta, zeta)
GW = np.full(4, 1.0 / 24.0)


def canonical_tets(nodes: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """Reorder columns 4..9 so that column 4+k is the midside node of EDGES[k]."""
    x = nodes[tets]                                   # (E,10,3)
    mid = 0.5 * (x[:, EDGES[:, 0]] + x[:, EDGES[:, 1]])  # (E,6,3)
    cand = x[:, 4:10]                                 # (E,6,3)
    d = np.linalg.norm(mid[:, :, None, :] - cand[:, None, :, :], axis=3)  # (E,6 edges,6 cand)
    pick = np.argmin(d, axis=2)
    if not np.all(np.sort(pick, axis=1) == np.arange(6)):
        raise ValueError("midside node matching failed (curved or non-conforming mesh)")
    out = tets.copy()
    out[:, 4:10] = np.take_along_axis(tets[:, 4:10], pick, axis=1)
    return out


def _dshape(g):
    """dN/d(xi,eta,zeta) at a point, shape (3,10)."""
    xi, eta, ze = g
    L = np.array([1 - xi - eta - ze, xi, eta, ze])
    dL = np.array([[-1, 1, 0, 0], [-1, 0, 1, 0], [-1, 0, 0, 1]], float)  # (3,4)
    dN = np.zeros((3, 10))
    for i in range(4):
        dN[:, i] = (4 * L[i] - 1) * dL[:, i]
    for k, (i, j) in enumerate(EDGES):
        dN[:, 4 + k] = 4 * (L[i] * dL[:, j] + L[j] * dL[:, i])
    return dN


DSHAPE = np.stack([_dshape(g) for g in GAUSS])  # (4,3,10)
LG = np.column_stack([1 - GAUSS.sum(axis=1), GAUSS])
SHAPE = np.column_stack([LG * (2 * LG - 1), 4 * LG[:, EDGES[:, 0]] * LG[:, EDGES[:, 1]]])


def gauss_to_nodes(tets, values, n, groups=None):
    """Linear extrapolation to corners, nodal average, then edge means (also for vector fields).
    groups: element index arrays of the materials. A field that jumps across an interface (E across two dielectrics)
    is then averaged within each material only, so the jump stays at the interface: only nodes on it take the mean of
    both sides, instead of the average leaking into the midside nodes next to it."""
    values = np.asarray(values)
    tail = values.shape[2:]
    corners = np.einsum("cg,egk->eck", np.linalg.inv(LG), values.reshape(len(tets), 4, -1))
    k = corners.shape[2]
    acc = np.zeros((n, k)); cnt = np.zeros(n)
    for idx in (groups if groups is not None and len(groups) > 1 else [np.arange(len(tets))]):
        ga = np.zeros((n, k)); gc = np.zeros(n)
        np.add.at(ga, tets[idx, :4].ravel(), corners[idx].reshape(-1, k))
        np.add.at(gc, tets[idx, :4].ravel(), 1)
        gv = np.divide(ga, gc[:, None], out=np.zeros_like(ga), where=gc[:, None] > 0)
        # midside nodes from this material's own corner values
        mids, a, b = tets[idx, 4:].ravel(), tets[idx][:, EDGES[:, 0]].ravel(), tets[idx][:, EDGES[:, 1]].ravel()
        gm = np.zeros(n, bool)
        gm[mids] = True
        gv[mids] = 0.5 * (gv[a] + gv[b])
        used = (gc > 0) | gm
        acc[used] += gv[used]
        cnt[used] += 1
    out = np.divide(acc, cnt[:, None], out=np.zeros_like(acc), where=cnt[:, None] > 0)
    return out.reshape((n,) + tail)


def elasticity_matrix(E: float, nu: float) -> np.ndarray:
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[3:, 3:] = np.eye(3) * mu
    return D


def _bmatrix(dNdx):
    """dNdx (E,3,10) -> B (E,6,30) with engineering shear strains (xy, yz, zx)."""
    E = dNdx.shape[0]
    B = np.zeros((E, 6, 30))
    dx, dy, dz = dNdx[:, 0], dNdx[:, 1], dNdx[:, 2]
    B[:, 0, 0::3] = dx
    B[:, 1, 1::3] = dy
    B[:, 2, 2::3] = dz
    B[:, 3, 0::3] = dy; B[:, 3, 1::3] = dx
    B[:, 4, 1::3] = dz; B[:, 4, 2::3] = dy
    B[:, 5, 0::3] = dz; B[:, 5, 2::3] = dx
    return B


def solve(nodes, tets, E, nu, fixed_faces: list[np.ndarray], tractions: list[tuple[np.ndarray, np.ndarray]],
          progress: Callable[[str, float], None] = lambda *_: None,
          rollers: list[tuple[np.ndarray, int]] = ()) -> dict:
    """fixed_faces: list of tri6 arrays whose nodes get u=0.
    tractions: list of (tri6 array, traction vector [Pa]) applied uniformly on that face.
    rollers: list of (tri6 array, component) whose nodes get u[component]=0 (symmetry planes normal to an axis).
    E, nu: one value, or one per element (assemblies of several materials).
    """
    tets = canonical_tets(nodes, tets)
    n = len(nodes)
    ndof = 3 * n
    check_memory(n, "structural")
    pairs, mat = np.unique(np.column_stack([np.broadcast_to(E, len(tets)), np.broadcast_to(nu, len(tets))]), axis=0,
                           return_inverse=True)
    Ds = np.array([elasticity_matrix(*p) for p in pairs])          # one D per material
    mat = mat.ravel()
    X = nodes[tets]                                   # (E,10,3)

    progress("job.assembling", 0.10)
    vol = np.zeros(len(tets))
    dofs = (3 * tets[:, :, None] + np.arange(3)).reshape(len(tets), 30)
    K = sp.csr_matrix((ndof, ndof))
    # in chunks: the element matrices of a 300k-element model take 2.3 GB at once
    for s in range(0, len(tets), ASSEMBLY_CHUNK):
        sl = slice(s, s + ASSEMBLY_CHUNK)
        Ke = np.zeros((len(dofs[sl]), 30, 30))
        for g in range(4):
            J = np.einsum("ik,ekj->eij", DSHAPE[g], X[sl])    # (E,3,3)
            detJ = np.linalg.det(J)
            if np.any(detJ <= 0):
                raise ValueError("inverted element (negative Jacobian)")
            dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(detJ), 3, 10)))
            B = _bmatrix(dNdx)
            Ke += GW[g] * detJ[:, None, None] * np.einsum("eki,ekl,elj->eij", B, Ds[mat[sl]], B)
            vol[sl] += GW[g] * detJ
        rows = np.repeat(dofs[sl], 30, axis=1).ravel()
        cols = np.tile(dofs[sl], (1, 30)).ravel()
        K = K + sp.csr_matrix((Ke.ravel(), (rows, cols)), shape=(ndof, ndof))
        del Ke

    f = np.zeros(ndof)
    for tri, t in tractions:
        P = nodes[tri[:, :3]]
        area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        # uniform traction on a 6-node triangle: corners 0, midsides area/3 each
        for k in range(3, 6):
            tt = t if np.ndim(t) == 2 else np.broadcast_to(t, (len(tri), 3))   # per-triangle or uniform traction
            np.add.at(f, (3 * tri[:, k])[:, None] + np.arange(3), (area / 3)[:, None] * tt)

    fixed_nodes = np.unique(np.concatenate([fa.ravel() for fa in fixed_faces])) if fixed_faces else np.array([], int)
    fixed = (3 * fixed_nodes[:, None] + np.arange(3)).ravel()
    if len(rollers):
        fixed = np.unique(np.concatenate([fixed] + [3 * np.unique(tri) + c for tri, c in rollers]))
    free = np.setdiff1d(np.arange(ndof), fixed)

    progress("job.solving", 0.45)
    u = np.zeros(ndof)
    Kfix = K[fixed]                                   # rows of the constrained dofs, for the reactions
    if len(free) <= DIRECT_LIMIT:
        u[free] = spla.spsolve(K[free][:, free].tocsc(), f[free])
    else:
        # large 3D problems: smoothed-aggregation AMG preconditioned CG with the rigid-body modes.
        # The constraints are applied in place (zero rows and columns, a scaled 1 on the diagonal) instead of copying
        # out K[free][:, free], and the matrix goes in as 3x3 blocks: AMG then measures strength per node, not per
        # dof. A 400k-element sphere needed 845 MB for the per-dof strength matrix alone and ran out of memory.
        isfix = np.zeros(ndof, bool)
        isfix[fixed] = True
        hit = np.repeat(isfix, np.diff(K.indptr))       # one bool per stored entry (an index array would be 8x larger)
        hit |= isfix[K.indices]
        K.data[hit] = 0.0
        del hit
        d = K.diagonal()
        d[fixed] = d[free].mean() if len(free) else 1.0
        K.setdiag(d)
        b = np.where(isfix, 0.0, f)
        A = K.tobsr(blocksize=(3, 3))
        del K
        xyz = nodes - nodes.mean(axis=0)                 # rotations about the centre: better-scaled near-null space
        x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        B = np.zeros((n, 3, 6))
        B[:, 0, 0] = B[:, 1, 1] = B[:, 2, 2] = 1.0
        B[:, 0, 3], B[:, 1, 3] = -y, x
        B[:, 1, 4], B[:, 2, 4] = -z, y
        B[:, 0, 5], B[:, 2, 5] = z, -x
        try:
            u[:] = _amg_cg(A, b, B.reshape(ndof, 6))
        except RuntimeError:
            # strongly graded meshes (fine around a load, coarse elsewhere) can stall AMG-CG; a direct solve is slower
            # and uses more memory but always answers, so fall back to it while the problem still fits
            if len(free) > DIRECT_FALLBACK_LIMIT:
                raise
            progress("job.solving", 0.6)
            u[:] = spla.spsolve(A.tocsc(), b)
        u[fixed] = 0.0

    progress("job.post", 0.85)
    reaction = np.zeros(ndof)
    reaction[fixed] = Kfix @ u - f[fixed]
    U = u.reshape(-1, 3)

    # stress at the 4 Gauss points, extrapolated linearly to the corner nodes (as CalculiX does), then
    # nodal averaging of the stress components; midside nodes take the mean of their edge ends
    sg = np.zeros((len(tets), 4, 6))
    for g in range(4):
        J = np.einsum("ik,ekj->eij", DSHAPE[g], X)
        dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(tets), 3, 10)))
        sg[:, g] = np.einsum("ekl,el->ek", Ds[mat], np.einsum("eij,ej->ei", _bmatrix(dNdx), u[dofs]))
    Lg = np.column_stack([1 - GAUSS.sum(axis=1), GAUSS])           # barycentric coords of Gauss points (4x4)
    sc = np.einsum("cg,egk->eck", np.linalg.inv(Lg), sg)            # (E, 4 corners, 6)
    acc = np.zeros((n, 6)); cnt = np.zeros(n)
    np.add.at(acc, tets[:, :4].ravel(), sc.reshape(-1, 6))
    np.add.at(cnt, tets[:, :4].ravel(), 1)
    sn = np.divide(acc, cnt[:, None], out=np.zeros((n, 6)), where=cnt[:, None] > 0)
    mids = tets[:, 4:].ravel()
    sn[mids] = 0.5 * (sn[tets[:, EDGES[:, 0]].ravel()] + sn[tets[:, EDGES[:, 1]].ravel()])
    vm = np.sqrt(0.5 * ((sn[:, 0] - sn[:, 1]) ** 2 + (sn[:, 1] - sn[:, 2]) ** 2 + (sn[:, 2] - sn[:, 0]) ** 2)
                 + 3 * (sn[:, 3] ** 2 + sn[:, 4] ** 2 + sn[:, 5] ** 2))
    se = sg.mean(axis=1)
    vm_e = np.sqrt(0.5 * ((se[:, 0] - se[:, 1]) ** 2 + (se[:, 1] - se[:, 2]) ** 2 + (se[:, 2] - se[:, 0]) ** 2)
                   + 3 * (se[:, 3] ** 2 + se[:, 4] ** 2 + se[:, 5] ** 2))
    applied = f.reshape(-1, 3).sum(axis=0)
    react = np.zeros(3)                                # over every constrained dof, symmetry planes included
    np.add.at(react, fixed % 3, reaction[fixed])
    # relative to the total load, not the net one: internal pressure on a closed vessel nets to ~0
    scale = max(np.linalg.norm(applied), np.linalg.norm(np.abs(f).reshape(-1, 3).sum(axis=0)), 1e-30)
    imbalance = float(np.linalg.norm(applied + react) / scale)
    return {"u": U, "vm": vm, "s": sn, "vm_elem_max": float(vm_e.max()), "applied": applied, "reaction": react,
            "imbalance": imbalance, "volume": float(vol.sum()), "ndof": ndof, "nfree": int(len(free))}


# ---------------------------------------------------------------- shared helpers for arbitrary shapes

def outward_normals(nodes: np.ndarray, tets: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Unit outward normal of each boundary triangle (orientation fixed by the adjacent tetrahedron)."""
    opp = {}
    corners = tets[:, :4]
    for a, b, c, d in ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)):
        for row in np.stack([corners[:, a], corners[:, b], corners[:, c], corners[:, d]], 1):
            opp[tuple(sorted(row[:3]))] = row[3]
    P = nodes[tri[:, :3]]
    n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    inner = np.array([nodes[opp[tuple(sorted(t[:3]))]] for t in tri])
    flip = np.einsum("ij,ij->i", n, inner - P[:, 0]) > 0
    n[flip] *= -1
    return n / np.linalg.norm(n, axis=1)[:, None]


def tri_areas(nodes, tri):
    P = nodes[tri[:, :3]]
    return 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)


# exact consistent "mass" matrix of a straight-sided 6-node triangle, times 180/A
TRI6_M = np.array([[6, -1, -1, 0, -4, 0], [-1, 6, -1, 0, 0, -4], [-1, -1, 6, -4, 0, 0],
                   [0, 0, -4, 32, 16, 16], [-4, 0, 0, 16, 32, 16], [0, -4, 0, 16, 16, 32]], float)


def solve_scalar(nodes, tets, k, fixed: list[tuple[np.ndarray, float]], fluxes: list[tuple[np.ndarray, float]],
                  convection: list[tuple[np.ndarray, float, float]],
                  progress: Callable[[str, float], None] = lambda *_: None, source=None) -> dict:
    """Scalar diffusion on tet10; surface flux and source (E,4) are positive into the body.
    Returns the scalar, Gauss gradients/weights and the reactions of the prescribed faces."""
    tets = canonical_tets(nodes, tets)
    n = len(nodes)
    check_memory(n, "scalar")
    progress("job.assembling", 0.10)
    K = sp.csr_matrix((n, n))
    f = np.zeros(n)
    weights = np.empty((len(tets), 4))
    source = np.zeros((len(tets), 4)) if source is None else np.broadcast_to(source, (len(tets), 4))
    coeff = np.broadcast_to(k, len(tets))
    # The finest thin-plate mesh has hundreds of thousands of tets; keep element matrices in bounded blocks.
    for start in range(0, len(tets), ASSEMBLY_CHUNK):
        sl = slice(start, start + ASSEMBLY_CHUNK)
        conn = tets[sl]
        X = nodes[conn]
        Ke = np.zeros((len(conn), 10, 10))
        fe = np.zeros((len(conn), 10))
        for g in range(4):
            J = np.einsum("ik,ekj->eij", DSHAPE[g], X)
            detJ = np.linalg.det(J)
            if np.any(detJ <= 0):
                raise ValueError("inverted element (negative Jacobian)")
            dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(conn), 3, 10)))
            weights[sl, g] = GW[g] * detJ
            Ke += (weights[sl, g] * coeff[sl])[:, None, None] * np.einsum("eki,ekj->eij", dNdx, dNdx)
            fe += (weights[sl, g] * source[sl, g])[:, None] * SHAPE[g]
        rows = np.repeat(conn, 10, axis=1).ravel()
        cols = np.tile(conn, (1, 10)).ravel()
        K = K + sp.csr_matrix((Ke.ravel(), (rows, cols)), shape=(n, n))
        np.add.at(f, conn.ravel(), fe.ravel())
    del Ke, fe, rows, cols, X

    def surface_load(tri, q):
        a = tri_areas(nodes, tri)
        for c in range(3, 6):
            np.add.at(f, tri[:, c], q * a / 3)

    for tri, q in fluxes:
        surface_load(tri, q)
    Hm = sp.csr_matrix((n, n))
    for tri, h, tinf in convection:
        a = tri_areas(nodes, tri)
        Me = (a / 180.0)[:, None, None] * TRI6_M[None, :, :] * h
        r = np.repeat(tri, 6, axis=1).ravel()
        c = np.tile(tri, (1, 6)).ravel()
        Hm = Hm + sp.csr_matrix((Me.ravel(), (r, c)), shape=(n, n))
        surface_load(tri, h * tinf)
    A = (K + Hm).tocsr()

    T = np.full(n, np.nan)
    for tri, temp in fixed:
        T[np.unique(tri)] = temp
    known = ~np.isnan(T)
    free = np.where(~known)[0]
    progress("job.solving", 0.45)
    Tk = np.nan_to_num(T)
    rhs = f[free] - A[free][:, known] @ Tk[known]
    Aff = A[free][:, free].tocsr()
    T[free] = spla.spsolve(Aff.tocsc(), rhs) if len(free) <= 3 * DIRECT_LIMIT else _amg_cg(Aff, rhs)

    progress("job.post", 0.85)
    resid = A @ T - f                         # heat that the fixed-temperature nodes must supply
    flows = {"fixed": [], "flux": [], "convection": []}
    owned = np.zeros(n, bool)
    for tri, temp in fixed:
        nds = np.setdiff1d(np.unique(tri), np.where(owned)[0])
        owned[nds] = True
        flows["fixed"].append(float(resid[nds].sum()))
    for tri, q in fluxes:
        flows["flux"].append(float(q * tri_areas(nodes, tri).sum()))
    for tri, h, tinf in convection:
        a = tri_areas(nodes, tri)
        Me = (a / 180.0)[:, None, None] * TRI6_M[None, :, :]
        # integral of h (Tinf - T) over the face
        intT = float(np.einsum("eij,ej->", Me, T[tri]))
        flows["convection"].append(float(h * (tinf * a.sum() - intT)))
    source_total = float(np.sum(weights * source))
    total_in = sum(v for vs in flows.values() for v in vs if v > 0) + max(source_total, 0)
    net = sum(v for vs in flows.values() for v in vs) + source_total
    grad = np.empty((len(tets), 4, 3))
    for start in range(0, len(tets), ASSEMBLY_CHUNK):
        sl = slice(start, start + ASSEMBLY_CHUNK)
        conn = tets[sl]
        X = nodes[conn]
        for g in range(4):
            J = np.einsum("ik,ekj->eij", DSHAPE[g], X)
            dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(conn), 3, 10)))
            grad[sl, g] = np.einsum("eij,ej->ei", dNdx, T[conn])
    return {"value": T, "gradient": grad, "weights": weights, "tets": tets, "source_total": source_total,
            "flows": flows, "imbalance": abs(net) / max(total_in, 1e-30), "total_in": total_in}


def solve_thermal(nodes, tets, k, fixed, fluxes, convection, progress=lambda *_: None, source=None):
    """Steady conduction; source is the volumetric heating at the four Gauss points of each element."""
    r = solve_scalar(nodes, tets, k, fixed, fluxes, convection, progress, source)
    return {**r, "T": r["value"]}
