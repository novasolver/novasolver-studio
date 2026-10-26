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
    Kff = K[free][:, free].tocsr()
    if len(free) <= DIRECT_LIMIT:
        u[free] = spla.spsolve(Kff.tocsc(), f[free])
    else:
        # large 3D problems: smoothed-aggregation AMG preconditioned CG with the rigid-body modes (low memory)
        xyz = nodes[free // 3] - nodes.mean(axis=0)      # rotations about the centre: better-scaled near-null space
        comp = free % 3
        B = np.zeros((len(free), 6))
        B[np.arange(len(free)), comp] = 1.0
        x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        B[comp == 0, 3] = -y[comp == 0]; B[comp == 1, 3] = x[comp == 1]
        B[comp == 1, 4] = -z[comp == 1]; B[comp == 2, 4] = y[comp == 2]
        B[comp == 0, 5] = z[comp == 0]; B[comp == 2, 5] = -x[comp == 2]
        try:
            u[free] = _amg_cg(Kff, f[free], B)
        except RuntimeError:
            # strongly graded meshes (fine around a load, coarse elsewhere) can stall AMG-CG; a direct solve is slower
            # and uses more memory but always answers, so fall back to it while the problem still fits
            if len(free) > DIRECT_FALLBACK_LIMIT:
                raise
            progress("job.solving", 0.6)
            u[free] = spla.spsolve(Kff.tocsc(), f[free])

    progress("job.post", 0.85)
    reaction = K @ u - f
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


def solve_thermal(nodes, tets, k, fixed: list[tuple[np.ndarray, float]], fluxes: list[tuple[np.ndarray, float]],
                  convection: list[tuple[np.ndarray, float, float]],
                  progress: Callable[[str, float], None] = lambda *_: None) -> dict:
    """Steady conduction with quadratic tetrahedra.
    fixed: (tri6, T [K]); fluxes: (tri6, q [W/m2], positive = into the body); convection: (tri6, h [W/m2K], Tinf [K]).
    Returns nodal T and the heat flow through each boundary group (positive = into the body)."""
    tets = canonical_tets(nodes, tets)
    n = len(nodes)
    X = nodes[tets]
    progress("job.assembling", 0.10)
    Ke = np.zeros((len(tets), 10, 10))
    for g in range(4):
        J = np.einsum("ik,ekj->eij", DSHAPE[g], X)
        detJ = np.linalg.det(J)
        if np.any(detJ <= 0):
            raise ValueError("inverted element (negative Jacobian)")
        dNdx = np.linalg.solve(J, np.broadcast_to(DSHAPE[g], (len(tets), 3, 10)))
        Ke += GW[g] * detJ[:, None, None] * np.reshape(k, (-1, 1, 1)) * np.einsum("eki,ekj->eij", dNdx, dNdx)
    rows = np.repeat(tets, 10, axis=1).ravel()
    cols = np.tile(tets, (1, 10)).ravel()
    K = sp.csr_matrix((Ke.ravel(), (rows, cols)), shape=(n, n))
    f = np.zeros(n)

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
    total_in = sum(v for vs in flows.values() for v in vs if v > 0)
    net = sum(v for vs in flows.values() for v in vs)
    return {"T": T, "flows": flows, "imbalance": abs(net) / max(total_in, 1e-30), "total_in": total_in}
