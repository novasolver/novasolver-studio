"""3D structural topology optimisation: minimum compliance under a volume limit, on the built-in tet10 solver.

Method (standard, written from the equations, not copied from research code):
  SIMP stiffness  E_e = E_min + rho_e**p (E - E_min), p = 3 by default
  density filter  rho_e = sum_j w_ej v_j x_j / sum_j w_ej v_j,  w_ej = max(0, r - |c_e - c_j|)   (v = element volume)
  sensitivity     dC/drho_e = -p rho_e**(p-1) (E - E_min) u_e^T K0_e u_e   (compliance is self-adjoint)
  update          optimality criteria with move limit and bisection on the volume multiplier
Non-design regions: elements forced solid (rho = 1) or void (rho = 0); they never change.

After the loop the design is thresholded at 0.5 and analysed again with only solid/void stiffness, so the reported
compliance belongs to a 0/1 part, not to the grey field. The solid set must connect the loaded nodes to the supports
(checked on the element graph); a disconnected result is reported, never silently exported.

This module only adds functions; it reads fem_tet10's element routines and does not change them.
"""
from __future__ import annotations

import math
import struct
import time
from typing import Callable

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from . import fem_tet10 as fe

MAX_ELEMENTS = 40000        # unit element matrices are kept: 40k x 30 x 30 x 8 B = 288 MB
MAX_FREE_DOFS = 150000      # direct factorisation each iteration (about 15-20 s at 100k unknowns)


# ---------------------------------------------------------------- design domain mesh
def box_mesh(length, width, height, nx, ny, nz):
    """Structured tet10 mesh of the box [0,L]x[0,W]x[0,H]: every hexahedral cell is split into 6 tetrahedra around
    its main diagonal (Kuhn split, conforming between neighbouring cells). Returns nodes (N,3), tets (E,10), cell (E,)
    the index of the hexahedral cell each tet came from."""
    xs, ys, zs = np.linspace(0, length, nx + 1), np.linspace(0, width, ny + 1), np.linspace(0, height, nz + 1)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    corners = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    idx = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k
    # the 8 hex vertices by bit pattern (dx, dy, dz); 6 tets along the 0 -> 7 diagonal
    paths = [(1, 2, 4), (1, 4, 2), (2, 1, 4), (2, 4, 1), (4, 1, 2), (4, 2, 1)]
    tets4, cell = [], []
    i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    i, j, k = i.ravel(), j.ravel(), k.ravel()
    vert = lambda b: idx(i + (b & 1), j + ((b >> 1) & 1), k + ((b >> 2) & 1))
    cid = np.arange(len(i))
    for a, b, c in paths:
        tets4.append(np.column_stack([vert(0), vert(a), vert(a | b), vert(7)]))
        cell.append(cid)
    tets4 = np.concatenate(tets4)
    cell = np.concatenate(cell)
    # half of the Kuhn tets come out left-handed: swap two corners so every signed volume is positive
    P = corners[tets4]
    neg = np.einsum("ij,ij->i", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0]) < 0
    tets4[neg] = tets4[neg][:, [0, 2, 1, 3]]
    # midside nodes, shared between tets through unique edges
    e = tets4[:, fe.EDGES]                                    # (E,6,2)
    e_sorted = np.sort(e.reshape(-1, 2), axis=1)
    uniq, inv = np.unique(e_sorted, axis=0, return_inverse=True)
    mids = corners[uniq].mean(axis=1)
    nodes = np.vstack([corners, mids])
    tets = np.hstack([tets4, len(corners) + inv.reshape(-1, 6)])
    tets = fe.canonical_tets(nodes, tets)
    return nodes, tets, cell


# ---------------------------------------------------------------- unit element matrices
def unit_stiffness(nodes, tets, nu):
    """Element stiffness with E = 1, shape (E,30,30), and element volumes."""
    D = fe.elasticity_matrix(1.0, nu)
    X = nodes[tets]
    Ke = np.zeros((len(tets), 30, 30))
    vol = np.zeros(len(tets))
    for g in range(4):
        J = np.einsum("ik,ekj->eij", fe.DSHAPE[g], X)
        detJ = np.linalg.det(J)
        if np.any(detJ <= 0):
            raise ValueError("inverted element (negative Jacobian)")
        dNdx = np.linalg.solve(J, np.broadcast_to(fe.DSHAPE[g], (len(detJ), 3, 10)))
        B = fe._bmatrix(dNdx)
        Ke += fe.GW[g] * detJ[:, None, None] * np.einsum("eki,kl,elj->eij", B, D, B)
        vol += fe.GW[g] * detJ
    return Ke, vol


def density_filter(centroids, vol, radius):
    """Sparse H (w_ej v_j) and its row sums for the volume-weighted cone filter."""
    tree = cKDTree(centroids)
    pairs = tree.sparse_distance_matrix(tree, radius, output_type="coo_matrix")
    w = radius - pairs.data
    rows, cols = pairs.row, pairs.col
    # sparse_distance_matrix leaves out the zero self distances
    rows = np.concatenate([rows, np.arange(len(vol))])
    cols = np.concatenate([cols, np.arange(len(vol))])
    w = np.concatenate([w, np.full(len(vol), radius)])
    keep = w > 0
    H = sp.csr_matrix((w[keep] * vol[cols[keep]], (rows[keep], cols[keep])), shape=(len(vol), len(vol)))
    return H, np.asarray(H.sum(axis=1)).ravel()


# ---------------------------------------------------------------- problem
class Problem:
    """nodes/tets: tet10 mesh of the design domain.
    fixed_dofs: constrained dof indices (3*node + component), u = 0.
    force: global load vector (3N,).
    solid / void: boolean element masks of the non-design regions."""
    DPN, MIN_FIXED = 3, 6

    def unit_matrices(self):
        return unit_stiffness(self.nodes, self.tets, self.nu)

    def __init__(self, nodes, tets, E, nu, fixed_dofs, force, *, solid=None, void=None, penal=3.0,
                 filter_radius=None, e_min_ratio=1e-9):
        if len(tets) > MAX_ELEMENTS:
            raise ValueError(f"too many elements for the optimiser ({len(tets)} > {MAX_ELEMENTS})")
        self.nodes, self.tets = np.asarray(nodes, float), fe.canonical_tets(np.asarray(nodes, float), np.asarray(tets))
        self.E, self.nu, self.penal, self.e_min = float(E), float(nu), float(penal), float(E) * e_min_ratio
        n = len(self.nodes)
        d = self.dpn = self.DPN
        self.ndof = d * n
        self.force = np.asarray(force, float).ravel()
        if self.force.shape != (self.ndof,) or not np.isfinite(self.force).all() or not self.force.any():
            raise ValueError(f"load: finite nonzero vector of length {d}N required")
        fixed = np.unique(np.asarray(fixed_dofs, int))
        if len(fixed) < self.MIN_FIXED:
            raise ValueError("supports do not prevent rigid-body motion" if d == 3 else "no fixed-temperature nodes")
        self.fixed = fixed
        self.free = np.setdiff1d(np.arange(self.ndof), fixed)
        if len(self.free) > MAX_FREE_DOFS:
            raise ValueError(f"too many unknowns for the optimiser ({len(self.free)} > {MAX_FREE_DOFS})")
        ne = len(self.tets)
        self.solid = np.zeros(ne, bool) if solid is None else np.asarray(solid, bool)
        self.void = np.zeros(ne, bool) if void is None else np.asarray(void, bool)
        if np.any(self.solid & self.void):
            raise ValueError("an element is both solid and void")
        self.design = ~(self.solid | self.void)
        if not self.design.any():
            raise ValueError("no design elements")
        self.Ke0, self.vol = self.unit_matrices()
        m = 10 * d
        self.dofs = (d * self.tets[:, :, None] + np.arange(d)).reshape(ne, m)
        self.rows = np.repeat(self.dofs, m, axis=1).ravel()
        self.cols = np.tile(self.dofs, (1, m)).ravel()
        self.centroids = self.nodes[self.tets[:, :4]].mean(axis=1)
        h = float(np.cbrt(self.vol.mean() * 6))           # about one hexahedral cell edge
        self.filter_radius = float(filter_radius) if filter_radius else 1.5 * h
        self.H, self.Hs = density_filter(self.centroids, self.vol, self.filter_radius)
        self.v_total = float(self.vol.sum())

    beta, eta = 1.0, 0.5         # Heaviside projection sharpness (raised by optimize) and threshold

    # physical densities from design variables; non-design regions are imposed after filtering and projection
    def _project(self, rt):
        b, n = self.beta, self.eta
        den = math.tanh(b * n) + math.tanh(b * (1 - n))
        rho = (math.tanh(b * n) + np.tanh(b * (rt - n))) / den
        drho = b * (1 - np.tanh(b * (rt - n)) ** 2) / den
        return rho, drho

    def physical(self, x, derivative=False):
        rho, drho = self._project((self.H @ x) / self.Hs)
        rho[self.solid], rho[self.void] = 1.0, 0.0
        drho[~self.design] = 0.0
        return (rho, drho) if derivative else rho

    def stiffness(self, rho_or_moduli, moduli=False):
        Ee = rho_or_moduli if moduli else self.e_min + rho_or_moduli ** self.penal * (self.E - self.e_min)
        data = (Ee[:, None, None] * self.Ke0).ravel()
        return sp.csr_matrix((data, (self.rows, self.cols)), shape=(self.ndof, self.ndof))

    _factor = None
    refactor_after = 25         # CG iterations; beyond this the old factor is a poor preconditioner
    solve_stats = None

    def solve(self, K, tol=1e-9):
        """Densities change little between iterations, so the last exact factorisation preconditions CG on the new
        matrix (a few iterations instead of a new factorisation); refactorise when CG slows down. The answer is
        always iterated to the relative residual tol, never taken from the stale factor alone."""
        import scipy.sparse.linalg as spla
        A = K[self.free][:, self.free].tocsr()
        b = self.force[self.free]
        if self.solve_stats is None:
            self.solve_stats = {"factorisations": 0, "cg_iterations": 0}
        x = None
        if self._factor is not None:
            count = [0]
            M = spla.LinearOperator(A.shape, matvec=self._factor.solve)
            x0 = self._last if getattr(self, "_last", None) is not None else None
            x, info = spla.cg(A, b, x0=x0, rtol=tol, maxiter=self.refactor_after, M=M,
                              callback=lambda _: count.__setitem__(0, count[0] + 1))
            self.solve_stats["cg_iterations"] += count[0]
            if info != 0 or np.linalg.norm(A @ x - b) > 10 * tol * np.linalg.norm(b):
                x = None
        if x is None:
            self._factor = fe.spd_factor(A)
            self.solve_stats["factorisations"] += 1
            x = self._factor.solve(b)
        self._last = x
        u = np.zeros(self.ndof)
        u[self.free] = x
        return u

    def evaluate(self, x):
        rho, drho = self.physical(x, derivative=True)
        u = self.solve(self.stiffness(rho))
        ue = u[self.dofs]
        energy = np.einsum("ei,eij,ej->e", ue, self.Ke0, ue)
        compliance = float(self.force @ u)
        dc_drho = -self.penal * rho ** (self.penal - 1) * (self.E - self.e_min) * energy
        dv_drho = self.vol / self.v_total
        # chain through the projection (drho = 0 on imposed elements) and the filter
        dc = self.H.T @ (dc_drho * drho / self.Hs)
        dv = self.H.T @ (dv_drho * drho / self.Hs)
        if not np.isfinite(u).all() or not np.isfinite(dc).all() or compliance <= 0:
            raise ValueError("nonfinite or nonpositive elastic response")
        return compliance, dc, dv, rho, u

    def volume_fraction(self, rho):
        return float(self.vol @ rho) / self.v_total


def unit_conduction(nodes, tets):
    """Element conduction matrix with k = 1, shape (E,10,10), and element volumes."""
    X = nodes[tets]
    Ke = np.zeros((len(tets), 10, 10))
    vol = np.zeros(len(tets))
    for g in range(4):
        J = np.einsum("ik,ekj->eij", fe.DSHAPE[g], X)
        detJ = np.linalg.det(J)
        if np.any(detJ <= 0):
            raise ValueError("inverted element (negative Jacobian)")
        dNdx = np.linalg.solve(J, np.broadcast_to(fe.DSHAPE[g], (len(detJ), 3, 10)))
        Ke += fe.GW[g] * detJ[:, None, None] * np.einsum("eki,ekj->eij", dNdx, dNdx)
        vol += fe.GW[g] * detJ
    return Ke, vol


def consistent_heat(nodes, tets, q):
    """Nodal loads of a uniform volumetric heat source q [W/m3] (tet10 shape functions at the 4-point rule; the
    corner loads of a quadratic tet are negative, so the total is exact while single nodes are not)."""
    X = nodes[tets]
    f = np.zeros(len(nodes))
    for g in range(4):
        detJ = np.linalg.det(np.einsum("ik,ekj->eij", fe.DSHAPE[g], X))
        np.add.at(f, tets.ravel(), (fe.GW[g] * detJ * q)[:, None].repeat(10, 1).ravel() * np.tile(fe.SHAPE[g], len(tets)))
    return f


class ThermalProblem(Problem):
    """Minimum thermal compliance (f^T T, i.e. the heat-weighted mean temperature) for steady conduction:
    k_e = k_min + rho^p (k - k_min). fixed_dofs: nodes held at the sink temperature (T = 0 relative);
    force: nodal heat input [W]. Same filter, projection and update as the elastic problem."""
    DPN, MIN_FIXED = 1, 1

    def __init__(self, nodes, tets, k, fixed_nodes, heat, **kw):
        kw.setdefault("e_min_ratio", 1e-3)    # the conductive "void" of the classical volume-to-point problem
        super().__init__(nodes, tets, k, 0.0, fixed_nodes, heat, **kw)

    def unit_matrices(self):
        return unit_conduction(self.nodes, self.tets)


def _oc_update(p, x, dc, dv, target, move):
    """Optimality criteria with bisection on the Lagrange multiplier; only design elements change."""
    d = p.design
    lo, hi = 1e-12, 1e12
    xd = x[d]
    ratio_base = np.maximum(1e-300, -dc[d]) / np.maximum(1e-300, dv[d])
    new = x.copy()
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        trial = np.clip(xd * np.sqrt(ratio_base / mid), np.maximum(0.0, xd - move), np.minimum(1.0, xd + move))
        new[d] = trial
        if p.volume_fraction(p.physical(new)) > target:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-9:
            break
    return new


def connected(p, solid_mask):
    """True when the solid elements form one piece that touches both the loaded nodes and the supports."""
    if not solid_mask.any():
        return False
    corners = p.tets[solid_mask, :4]
    ne = len(corners)
    # element graph through shared corner nodes
    nodes_e = sp.csr_matrix((np.ones(corners.size), (np.repeat(np.arange(ne), 4), corners.ravel())),
                            shape=(ne, len(p.nodes)))
    adj = nodes_e @ nodes_e.T
    ncomp, label = connected_components(adj, directed=False)
    loaded_nodes = np.unique(np.nonzero(p.force.reshape(-1, p.dpn).any(axis=1))[0])
    fixed_nodes = np.unique(p.fixed // p.dpn)
    all_solid = p.tets[solid_mask]
    def comps_touching(nodeset):
        hit = np.isin(all_solid, nodeset).any(axis=1)
        return set(label[hit].tolist())
    a, b = comps_touching(loaded_nodes), comps_touching(fixed_nodes)
    return bool(a & b) and len(a) == 1


def optimize(p: Problem, volume_fraction=0.3, iterations=120, move=0.2, tol=0.01, timeout_s=600,
             beta_max=16.0, beta_every=20, progress: Callable[[str, float], None] = lambda *_: None):
    """beta continuation: the projection starts at beta = 1 and doubles every beta_every iterations, or earlier when
    the design has settled; the run ends when it has settled at beta_max."""
    if not 0.05 <= volume_fraction <= 0.9:
        raise ValueError("volume_fraction: 0.05..0.9")
    fixed_volume = float(p.vol[p.solid].sum()) / p.v_total
    if volume_fraction <= fixed_volume:
        raise ValueError("volume_fraction must exceed the solid non-design share")
    x = np.where(p.solid, 1.0, np.where(p.void, 0.0, 0.0))
    # start uniform at the density that meets the target
    free_share = float(p.vol[p.design].sum()) / p.v_total
    x[p.design] = (volume_fraction - fixed_volume) / free_share
    x = np.clip(x, 0, 1)
    history, started, reason = [], time.monotonic(), "iteration_budget"
    p.beta, since = 1.0, 0
    for it in range(iterations):
        c, dc, dv, rho, _ = p.evaluate(x)
        history.append({"iteration": it, "compliance": c, "volume_fraction": p.volume_fraction(rho), "beta": p.beta})
        progress("topology.iterating", (it + 1) / iterations)
        new = _oc_update(p, x, dc, dv, volume_fraction, move if p.beta < 8 else move / 2)
        change = float(np.max(np.abs(new - x)))
        x, since = new, since + 1
        if time.monotonic() - started > timeout_s:
            reason = "time_budget"; break
        settled = since >= 5 and change < tol
        if p.beta >= beta_max:
            if settled:
                reason = "density_change_tolerance"; break
        elif settled or since >= beta_every:
            p.beta, since = min(beta_max, 2 * p.beta), 0
    c, _, _, rho, u = p.evaluate(x)
    grey = float(np.mean((rho[p.design] > 0.1) & (rho[p.design] < 0.9)))
    solid = rho >= 0.5
    moduli = np.where(solid, p.E, p.e_min)
    u_bin = p.solve(p.stiffness(moduli, moduli=True))
    c_bin = float(p.force @ u_bin)
    conn = connected(p, solid)
    warnings = ["concept_geometry_needs_fresh_analysis_and_stress_check", "no_stress_buckling_or_manufacturing_constraint"]
    if not conn:
        warnings.insert(0, "thresholded_design_disconnected")
    if grey > 0.15:
        warnings.append("many_intermediate_densities")
    return {
        "method": "SIMP_tet10_density_filter_OC",
        "elements": int(len(p.tets)), "unknowns": int(len(p.free)),
        "penal": p.penal, "filter_radius": p.filter_radius,
        "compliance": c, "volume_fraction": p.volume_fraction(rho),
        "threshold": {"level": 0.5, "compliance": c_bin, "volume_fraction": float(p.vol[solid].sum()) / p.v_total,
                      "connected": conn, "max_field": float(np.linalg.norm(u_bin.reshape(-1, p.dpn), axis=1).max())},
        "grey_share": grey, "history": history, "termination": reason,
        "elapsed_s": time.monotonic() - started, "warnings": warnings,
        "density": rho,
    }


# ---------------------------------------------------------------- geometry out
def boundary_surface(p: Problem, solid_mask):
    """Outer triangles (corner nodes) of the solid tets, oriented outward. Watertight by construction."""
    t = p.tets[solid_mask, :4]
    faces = np.concatenate([t[:, [1, 2, 3]], t[:, [0, 3, 2]], t[:, [0, 1, 3]], t[:, [0, 2, 1]]])
    key = np.sort(faces, axis=1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    outer = faces[cnt[inv.ravel()] == 1]
    # orient with the opposite vertex: the normal must point away from the tet's own centroid
    opp = np.concatenate([t[:, 0], t[:, 1], t[:, 2], t[:, 3]])[cnt[inv.ravel()] == 1]
    P = p.nodes
    nrm = np.cross(P[outer[:, 1]] - P[outer[:, 0]], P[outer[:, 2]] - P[outer[:, 0]])
    flip = np.einsum("ij,ij->i", nrm, P[opp] - P[outer[:, 0]]) > 0
    outer[flip] = outer[flip][:, [0, 2, 1]]
    return outer


def smooth(points, tris, iterations=10, lam=0.5, mu=-0.53, pinned=None):
    """Taubin smoothing (shrink-free) of a triangle surface; returns new points for the used vertices."""
    used, local = np.unique(tris, return_inverse=True)
    local = local.reshape(-1, 3)
    V = points[used].copy()
    e = np.concatenate([local[:, [0, 1]], local[:, [1, 2]], local[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    A = sp.csr_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(V), len(V)))
    A.data[:] = 1.0
    deg = np.asarray(A.sum(axis=1)).ravel()
    keep = np.zeros(len(V), bool) if pinned is None else pinned[used]
    for _ in range(iterations):
        for f in (lam, mu):
            delta = (A @ V) / deg[:, None] - V
            delta[keep] = 0
            V = V + f * delta
    return V, local


def write_stl(path, V, F, name=b"novasolver topology"):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n /= np.maximum(1e-300, np.linalg.norm(n, axis=1))[:, None]
    rec = np.zeros(len(F), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, V[F]
    with open(path, "wb") as fh:
        fh.write(name.ljust(80, b" ")[:80])
        fh.write(struct.pack("<I", len(F)))
        fh.write(rec.tobytes())


# ---------------------------------------------------------------- reference problem
def cantilever_box(length=2.0, width=0.5, height=1.0, nx=24, ny=4, nz=12, E=1.0, nu=0.3, load=1.0, **kw):
    """3D cantilever: x = 0 face clamped, a downward line load across the width at the middle of the free end
    (x = L, z = H/2), shared equally by its nodes (nz must be even). The classical 2D answer is a truss of two chords
    and diagonal braces."""
    if nz % 2:
        raise ValueError("nz must be even")
    nodes, tets, _ = box_mesh(length, width, height, nx, ny, nz)
    tol = 1e-9 * length
    clamp = np.nonzero(nodes[:, 0] < tol)[0]
    fixed = (3 * clamp[:, None] + np.arange(3)).ravel()
    edge = np.nonzero((nodes[:, 0] > length - tol) & (np.abs(nodes[:, 2] - height / 2) < tol))[0]
    force = np.zeros(3 * len(nodes))
    force[3 * edge + 2] = -load / len(edge)
    return Problem(nodes, tets, E, nu, fixed, force, **kw)


def heat_plate(size=1.0, thickness=0.05, n=24, nz=1, k=1.0, q=1.0, sink=0.1, **kw):
    """Classical volume-to-point problem: a square plate with uniform heat generation q, insulated except a sink of
    width sink*size at the middle of the x = 0 edge held at T = 0. The known answer is a branching conductor tree."""
    nodes, tets, _ = box_mesh(size, size, thickness, n, n, nz)
    tol = 1e-9 * size
    s = np.nonzero((nodes[:, 0] < tol) & (np.abs(nodes[:, 1] - size / 2) <= sink * size / 2 + tol))[0]
    return ThermalProblem(nodes, tets, k, s, consistent_heat(nodes, fe.canonical_tets(nodes, tets), q), **kw)