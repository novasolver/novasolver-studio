"""Genesis: topology optimisation on a voxel grid (structural minimum compliance and steady heat conduction).

Discretisation: the design domain is covered by an axis-aligned grid of cubic 8-node hexahedra (edge h). Every element
has the same unit matrix, so nothing per element is stored except its density; the system is solved matrix-free by
conjugate gradients with a geometric multigrid V-cycle (rediscretised coarse grids, damped Jacobi smoothing, a direct
solve on the coarsest grid). This is the usual large-scale approach and handles a few hundred thousand elements on a
desktop. The final part is meant to be re-meshed and analysed with the normal Studio solvers (stress, CalculiX).

Design chain (every map is linear or smooth, and differentiated exactly):
  z  -- design variables, one per active element
  x  = S z          symmetry planes / extrusion direction (averaging, self-adjoint)
  xf = filter(x)    volume-weighted cone filter of radius r (convolution on the grid)
  xa = AM(xf)       optional overhang filter for additive manufacturing (Langelaar 2017, 45 degrees)
  rho = H(xa)       smoothed Heaviside projection (beta continuation)
  then solid / void non-design regions are imposed.
Objective: weighted sum of compliances f_i^T u_i over load cases (self-adjoint). Constraint: volume fraction.
Update: optimality criteria with bisection on the multiplier and a move limit.

After the loop the design is thresholded, floating pieces are removed (kept: the pieces that touch a support and, for
structures, carry the load), the 0/1 part is analysed again, its thinnest member is measured by a distance transform,
and a closed surface is extracted by marching tetrahedra.
"""
from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import scipy.sparse as sp
from scipy import ndimage

from . import fem_tet10 as fe

MAX_ELEMENTS = 2_000_000
# the coarsest multigrid grid is factorised directly at every design update. Smaller is cheaper to factorise but costs
# CG iterations: on the 40k-cell cantilever case 5k dofs took 4.1 s per design step against 3.6 s with 40k
COARSE_DOFS = 20000
# the density filter is a direct 3D convolution: cost ~ r^3 (one pass on 221k cells: 0.011 s at r = 1.5, 1.44 s at 10)
MAX_FILTER_CELLS = 8.0
# exact fallback when CG stalls: SuperLU on 100k unknowns took about 0.4 GB; beyond that, fail with a clear error
MAX_DIRECT_DOFS = 100000


def grid_shape(cells, dpn, coarse_dofs=COARSE_DOFS, max_cells=MAX_ELEMENTS):
    """Pad a box of `cells` (nx, ny, nz) so the multigrid can coarsen until the coarsest grid has at most
    `coarse_dofs`: every dimension a multiple of 2^L and at least 2^(L+1). Padding cells are void and cost
    nothing in the operator (only active cells are visited)."""
    cells = np.maximum(4, np.asarray(cells, int))
    best = None
    for L in range(2, 8):
        m = 2 ** L
        shape = np.maximum(((cells + m - 1) // m) * m, 2 * m)
        if np.prod(shape) > max_cells and best is not None:
            break
        best = shape
        if np.prod(shape // m + 1) * dpn <= coarse_dofs:
            break
    return tuple(int(s) for s in best)


class Cancelled(Exception):
    pass


# ======================================================================== element matrices
_GP = np.array([-1, 1]) / math.sqrt(3)
_CORNER = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])


def _dN(xi, eta, ze):
    s = 2 * _CORNER - 1
    return np.stack([s[:, 0] * (1 + s[:, 1] * eta) * (1 + s[:, 2] * ze),
                     s[:, 1] * (1 + s[:, 0] * xi) * (1 + s[:, 2] * ze),
                     s[:, 2] * (1 + s[:, 0] * xi) * (1 + s[:, 1] * eta)]) / 8          # (3,8) d/dxi


def hex_matrices(h, nu):
    """Unit (E = 1, k = 1) element matrices of a cube of edge h: elastic (24,24), conduction (8,8), and the
    strain-displacement matrix at the centre (6,24) for stress estimates."""
    D = fe.elasticity_matrix(1.0, nu) if nu is not None else None
    Ke = np.zeros((24, 24)); Kt = np.zeros((8, 8))
    detJ = (h / 2) ** 3
    for a in _GP:
        for b in _GP:
            for c in _GP:
                g = _dN(a, b, c) * (2 / h)                      # d/dx
                Kt += g.T @ g * detJ
                if D is not None:
                    B = np.zeros((6, 24))
                    B[0, 0::3], B[1, 1::3], B[2, 2::3] = g
                    B[3, 0::3], B[3, 1::3] = g[1], g[0]
                    B[4, 1::3], B[4, 2::3] = g[2], g[1]
                    B[5, 0::3], B[5, 2::3] = g[2], g[0]
                    Ke += B.T @ D @ B * detJ
    g = _dN(0, 0, 0) * (2 / h)
    B0 = np.zeros((6, 24))
    B0[0, 0::3], B0[1, 1::3], B0[2, 2::3] = g
    B0[3, 0::3], B0[3, 1::3] = g[1], g[0]
    B0[4, 1::3], B0[4, 2::3] = g[2], g[1]
    B0[5, 0::3], B0[5, 2::3] = g[2], g[0]
    return Ke, Kt, B0, D


# ======================================================================== grid operator
class Level:
    """Matrix-free operator  y = sum_e E_e K_unit u_e  on one grid, constrained dofs held at zero."""

    def __init__(self, shape, h, dpn, Kunit, fixed_dof_mask):
        self.shape, self.h, self.dpn, self.Ku = shape, h, dpn, Kunit
        nx, ny, nz = shape
        self.nn = (nx + 1) * (ny + 1) * (nz + 1)
        self.ndof = dpn * self.nn
        i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
        base = (i * (ny + 1) + j) * (nz + 1) + k
        off = np.array([(cx * (ny + 1) + cy) * (nz + 1) + cz for cx, cy, cz in _CORNER])
        enodes = base.ravel()[:, None] + off[None, :]                                  # (E,8), all box cells
        self.enodes_all = enodes
        self.fixed_mask = fixed_dof_mask
        self.Kel = None

    def _finish(self, act, diag_e):
        self.act = act
        en = self.enodes_all[act]
        self.edof = (self.dpn * en[:, :, None] + np.arange(self.dpn)).reshape(len(en), -1) if self.dpn > 1 else en
        diag = np.bincount(self.edof.ravel(), weights=diag_e.ravel(), minlength=self.ndof)
        self.dead = (diag <= 0) | self.fixed_mask
        self.inv_diag = np.where(self.dead, 0.0, 1.0 / np.where(diag > 0, diag, 1))
        self.lam = None

    def lambda_max(self, iters=10):
        """Largest eigenvalue of D^-1 A (power iteration, warm-started): damped Jacobi needs omega < 2 / lambda_max."""
        v = getattr(self, "_pv", None)
        if v is None or len(v) != self.ndof:
            v = np.random.default_rng(0).standard_normal(self.ndof)
        v = np.where(self.dead, 0.0, v)
        lam = 0.0
        for _ in range(iters):
            n = np.linalg.norm(v)
            if n == 0:
                return 1.0
            v /= n
            w = self.inv_diag * self.matvec(v)
            lam = float(np.linalg.norm(w))             # |D^-1 A v| for a unit v: tends to lambda_max
            v = w
        self._pv = v
        return max(lam, 1e-12)

    def set_moduli(self, Ebox):
        """Ebox: element moduli on the full box (nx,ny,nz); zero = element not present."""
        Ef = Ebox.ravel()
        act = np.nonzero(Ef > 0)[0]
        self.Ee, self.Kel = Ef[act], None
        self._finish(act, self.Ee[:, None] * np.diag(self.Ku)[None, :])

    def set_elements(self, act, Kel):
        """Coarse level: one element matrix per present cell (Galerkin products of the finer level)."""
        self.Ee, self.Kel = None, Kel
        self._finish(act, np.einsum("nii->ni", Kel))

    def matvec(self, u):
        ue = u[self.edof]
        ye = np.einsum("nij,nj->ni", self.Kel, ue) if self.Kel is not None else (ue @ self.Ku) * self.Ee[:, None]
        y = np.bincount(self.edof.ravel(), weights=ye.ravel(), minlength=self.ndof)
        y[self.dead] = 0.0
        return y

    def assemble(self):
        m = self.edof.shape[1]
        rows = np.repeat(self.edof, m, axis=1).ravel()
        cols = np.tile(self.edof, (1, m)).ravel()
        data = (self.Kel if self.Kel is not None else self.Ee[:, None, None] * self.Ku[None]).ravel()
        return sp.csr_matrix((data, (rows, cols)), shape=(self.ndof, self.ndof))


def _p1d(nc):
    """Linear interpolation from nc+1 coarse nodes to 2nc+1 fine nodes."""
    nf = 2 * nc
    rows, cols, vals = [], [], []
    for i in range(nf + 1):
        if i % 2 == 0:
            rows.append(i); cols.append(i // 2); vals.append(1.0)
        else:
            rows += [i, i]; cols += [i // 2, i // 2 + 1]; vals += [0.5, 0.5]
    return sp.csr_matrix((vals, (rows, cols)), shape=(nf + 1, nc + 1))


def _child_maps(dpn):
    """P_c (8 children): fine-element dofs of child c from the dofs of its coarse element (trilinear), node-major."""
    out = []
    for c in _CORNER:
        Pn = np.empty((8, 8))
        for a, ca in enumerate(_CORNER):
            x = (c + ca) / 2.0                                     # fine corner in coarse local coordinates
            for b, cb in enumerate(_CORNER):
                Pn[a, b] = np.prod(np.where(cb == 1, x, 1 - x))
        out.append(np.kron(Pn, np.eye(dpn)))
    return np.array(out)                                           # (8, m, m)


class Multigrid:
    """CG preconditioned by a geometric V-cycle. Coarse grids halve every direction while all dimensions stay even.
    Coarse operators are Galerkin products P^T A P, formed element by element (a coarse element matrix is the sum of
    P_c^T K_child P_c over its 8 children), so they stay exact for thin walls and 0/1 designs. The earlier
    rediscretisation with the mean modulus of the children needed ~100 CG iterations a solve on a thin-walled pipe
    elbow (12k cells) and the solve time grew tenfold as the design sharpened."""

    def __init__(self, shape, h, dpn, Kunit, fixed_mask, coarse_dofs=COARSE_DOFS, smooth=3, omega=0.6):
        self.levels, self.P = [], []
        self.smooth, self.omega = smooth, omega
        lv = Level(shape, h, dpn, Kunit, fixed_mask)
        self.levels.append(lv)
        s, hh, fm = shape, h, fixed_mask
        while all(d % 2 == 0 and d >= 4 for d in s) and lv.ndof > coarse_dofs:
            sc = tuple(d // 2 for d in s)
            P = sp.kron(_p1d(sc[0]), sp.kron(_p1d(sc[1]), _p1d(sc[2]))).tocsr()
            if dpn > 1:
                P = sp.kron(P, sp.identity(dpn)).tocsr()
            # a coarse dof is constrained when it interpolates to any constrained fine dof: supports on odd fine nodes
            # (any real part) must not vanish on the coarse grid, or the coarse operator is singular
            cfm = np.asarray(P.T @ fm.astype(float)).ravel() > 0
            hh = 2 * hh
            lv = Level(sc, hh, dpn, Kunit * (2 ** (len(self.levels))), cfm)
            self.levels.append(lv); self.P.append(P)
            s, fm = sc, cfm
        self.factor = None

    def set_moduli(self, Ebox):
        self.levels[0].set_moduli(Ebox)
        if len(self.levels) > 1:
            Pc = _child_maps(self.levels[0].dpn)
            Mc = np.einsum("cab,ad,cde->cbe", Pc, self.levels[0].Ku, Pc)   # P_c^T K_unit P_c
        for l in range(1, len(self.levels)):
            fine, lv = self.levels[l - 1], self.levels[l]
            nx, ny, nz = lv.shape
            fx, fy, fz = fine.shape
            I, J, K = (a.ravel() for a in np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"))
            child = np.stack([((2 * I + cx) * fy + 2 * J + cy) * fz + 2 * K + cz for cx, cy, cz in _CORNER], axis=1)
            pos = np.full(fx * fy * fz, -1)
            pos[fine.act] = np.arange(len(fine.act))
            cp = pos[child]                                           # (coarse cells, 8): index in fine.act or -1
            act = np.nonzero((cp >= 0).any(axis=1))[0]
            cp = cp[act]
            if fine.Kel is None:                                      # from scalar moduli: sum_c E_c M_c
                Ec = np.where(cp >= 0, fine.Ee[np.maximum(cp, 0)], 0.0)
                Kel = np.einsum("nc,cij->nij", Ec, Mc)
            else:
                m = fine.Kel.shape[1]
                Kel = np.zeros((len(act), m, m))
                for c in range(8):
                    has = cp[:, c] >= 0
                    if has.any():
                        Kel[has] += Pc[c].T @ fine.Kel[cp[has, c]] @ Pc[c]
            lv.set_elements(act, Kel)
        # damped Jacobi weight per level from its spectrum: a fixed 0.6 diverged on some modes (more sweeps took more
        # CG iterations: 180 -> 259 on the pipe elbow); 4 / (3 lambda_max) damps the upper half of the spectrum
        for lv in self.levels[:-1]:
            lv.omega = 4.0 / (3.0 * 1.05 * lv.lambda_max())
        last = self.levels[-1]
        A = last.assemble()
        free = np.nonzero(~last.dead)[0]
        self.cfree = free
        self.factor = fe.spd_factor(A[free][:, free]) if len(free) else None

    def vcycle(self, r, l=0):
        lv = self.levels[l]
        if l == len(self.levels) - 1:
            x = np.zeros_like(r)
            if self.factor is not None:
                x[self.cfree] = self.factor.solve(r[self.cfree])
            return x
        w = getattr(lv, "omega", self.omega)
        x = w * lv.inv_diag * r
        for _ in range(self.smooth - 1):
            x += w * lv.inv_diag * (r - lv.matvec(x))
        rc = self.P[l].T @ (r - lv.matvec(x))
        rc[self.levels[l + 1].dead] = 0.0
        x += self.P[l] @ self.vcycle(rc, l + 1)
        x[lv.dead] = 0.0
        for _ in range(self.smooth):
            x += w * lv.inv_diag * (r - lv.matvec(x))
        return x

    def solve(self, b, x0=None, tol=1e-6, maxiter=1000):
        # 200 was too few: a cantilever extruded along its width (40k cells, 46 % of the cells at the void stiffness
        # 1e-9) needed 318 iterations late in the run and the job failed at a residual of 1.5e-2. More smoothing, a
        # larger coarse grid or a 1e-6 void floor did not change that (269-306); the iteration did converge
        lv = self.levels[0]
        if len(self.levels) == 1:
            x = np.zeros_like(b)
            x[self.cfree] = self.factor.solve(b[self.cfree])
            return x, 0
        b = np.where(lv.dead, 0.0, b)
        x = np.zeros_like(b) if x0 is None else np.where(lv.dead, 0.0, x0)
        r = b - lv.matvec(x)
        nb = np.linalg.norm(b) or 1.0
        if np.linalg.norm(r) <= tol * nb:
            return x, 0
        z = self.vcycle(r); p = z.copy(); rz = r @ z
        for it in range(1, maxiter + 1):
            Ap = lv.matvec(p)
            alpha = rz / (p @ Ap)
            x += alpha * p; r -= alpha * Ap
            if np.linalg.norm(r) <= tol * nb:
                return x, it
            z = self.vcycle(r)
            rz_new = r @ z
            p = z + (rz_new / rz) * p; rz = rz_new
        # robustness: an exact solve when the preconditioned iteration stalls (memory permitting)
        free = np.nonzero(~lv.dead)[0]
        if len(free) <= MAX_DIRECT_DOFS:
            x = np.zeros_like(b)
            x[free] = fe.spd_factor(lv.assemble()[free][:, free]).solve(b[free])
            return x, maxiter
        raise RuntimeError(f"Genesis solver did not converge (relative residual {np.linalg.norm(r) / nb:.1e})")


# ======================================================================== design maps
def cone_kernel(radius_cells):
    R = int(math.ceil(radius_cells)) - (1 if float(radius_cells).is_integer() else 0)
    a = np.arange(-R, R + 1)
    X, Y, Z = np.meshgrid(a, a, a, indexing="ij")
    return np.maximum(0.0, radius_cells - np.sqrt(X ** 2 + Y ** 2 + Z ** 2))


class AMFilter:
    """Overhang filter (Langelaar, Struct. Multidisc. Optim. 2017, extended to 3D with the 5-element support region):
    an element can only be printed as dense as the maximum of the printed elements that support it in the layer below.
    Build direction: axis `axis`, +1 (layers grow towards larger index) or -1. Smooth max/min (P = 40, Q = P + log5/log
    x0) as in the paper; exact adjoint by backward recursion over layers."""

    def __init__(self, axis=2, direction=1, P=40.0, eps=1e-4, xi0=0.5):
        self.axis, self.dir, self.P, self.eps, self.xi0 = axis, direction, P, eps, xi0
        self.Q = P + math.log(5) / math.log(xi0)
        self.start = 0          # oriented layer index of the build plate: the lowest layer of the part

    def set_envelope(self, active):
        """The plate sits under the lowest layer that holds any part cell (padding below the part is not air
        the part must bridge)."""
        occ = self._orient(active).reshape(active.shape[self.axis], -1).any(axis=1)
        self.start = int(np.argmax(occ)) if occ.any() else 0

    def _orient(self, a):
        a = np.moveaxis(a, self.axis, 0)
        return a[::-1] if self.dir < 0 else a

    def _back(self, a):
        a = a[::-1] if self.dir < 0 else a
        return np.moveaxis(a, 0, self.axis)

    def _supports(self, prev):
        # 5 supports: below and the 4 face neighbours below (padded with 0 outside)
        p = np.pad(prev, 1)
        return np.stack([p[1:-1, 1:-1], p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])

    def forward(self, x):
        X = self._orient(x)
        n = X.shape[0]
        Y = np.empty_like(X)
        self.cache = []
        s0 = self.start
        Y[:s0 + 1] = X[:s0 + 1]                         # the plate supports the first layer of the part
        for i in range(s0 + 1, n):
            S = self._supports(Y[i - 1])                 # (5,a,b)
            Ssum = np.sum((S + self.eps) ** self.P, axis=0)
            smax = Ssum ** (1 / self.Q) - self.eps ** (self.P / self.Q)                 # smooth max (Langelaar Eq. 5)
            # smooth min(x, smax)
            d = X[i] - smax
            sq = np.sqrt(d * d + 1e-4)
            Y[i] = 0.5 * (X[i] + smax - sq + math.sqrt(1e-4))
            self.cache.append((S, Ssum, smax, d, sq))
        return self._back(Y)

    def adjoint(self, gy):
        """d(objective)/dx from d(objective)/dy (reverse of forward)."""
        G = self._orient(gy).copy()
        n = G.shape[0]
        gx = np.zeros_like(G)
        s0 = self.start
        for i in range(n - 1, s0, -1):
            S, Ssum, smax, d, sq = self.cache[i - s0 - 1]
            dy_dx = 0.5 * (1 - d / sq)
            dy_ds = 0.5 * (1 + d / sq)
            gx[i] += G[i] * dy_dx
            gs = G[i] * dy_ds                            # wrt smax (a,b)
            dsmax_dS = (1 / self.Q) * Ssum[None] ** (1 / self.Q - 1) * self.P * (S + self.eps) ** (self.P - 1)
            gS = gs[None] * dsmax_dS                     # (5,a,b) wrt supports in previous printed layer
            g = np.zeros((G.shape[1] + 2, G.shape[2] + 2))
            g[1:-1, 1:-1] += gS[0]; g[:-2, 1:-1] += gS[1]; g[2:, 1:-1] += gS[2]
            g[1:-1, :-2] += gS[3]; g[1:-1, 2:] += gS[4]
            G[i - 1] += g[1:-1, 1:-1]
        gx[:s0 + 1] += G[:s0 + 1]
        return self._back(gx)


@dataclass
class Settings:
    volume_fraction: float = 0.3
    filter_radius: float = 1.5          # in cells; also the target minimum member size (about 2 r cells)
    penal: float = 3.0
    iterations: int = 150
    move: float = 0.2
    tol: float = 0.01
    beta_max: float = 16.0
    beta_every: int = 25
    eta_erode: float | None = None     # eroded (robust) design for the analysis, e.g. 0.8 (experimental: mixed results)
    min_member_cells: float | None = None   # thinnest member asked for; warn when the result has thinner ones
    symmetry: tuple = ()               # axes (0,1,2) whose mid-plane is a mirror plane
    extrusion: int | None = None       # axis along which the part must be prismatic (milling / casting)
    overhang: tuple | None = None      # (axis, +1|-1) build direction for additive manufacturing
    timeout_s: float = 3600.0
    # CG tolerance inside the loop: 1e-4 gave the same design and compliance as 1e-6 on the cantilever case at 2/3 of
    # the time (OC needs the sign and size of the sensitivities, not 6 digits); the final 0/1 analysis uses 1e-8
    solver_tol: float = 1e-4


# ======================================================================== problem
class Genesis:
    """Voxel design domain.

    shape: (nx, ny, nz) cells; h: cell edge [m]; origin: (3,) coordinates of the grid corner.
    active: bool (nx,ny,nz) cells inside the design envelope (default: all).
    solid / void: bool masks of non-design cells (forced solid / forced empty).
    physics: "elastic" (E [Pa], nu) or "thermal" (E is the conductivity k [W/mK]).
    fixed: bool mask of constrained dofs (elastic: (nn,3); thermal: (nn,)), value 0.
    loads: (ncase, ndof) nodal force [N] or heat [W]; weights: (ncase,)."""

    def __init__(self, shape, h, *, physics="elastic", E=1.0, nu=0.3, active=None, solid=None, void=None,
                 fixed=None, loads=None, weights=None, origin=(0, 0, 0), e_min_ratio=None, plate_from=None):
        self.shape = tuple(int(s) for s in shape)
        # cells that place the AM build plate (default: the design envelope). A case passes its body cells: cells
        # added for faces with conditions can reach one layer below the body, and a plate there left the whole
        # body unsupported (cantilever +z at 12k cells: design wiped out from the first step)
        self.plate_from = None if plate_from is None else np.asarray(plate_from, bool)
        if np.prod(self.shape) > MAX_ELEMENTS:
            raise ValueError(f"design grid too large ({np.prod(self.shape)} cells > {MAX_ELEMENTS})")
        self.h, self.origin, self.physics = float(h), np.asarray(origin, float), physics
        self.E, self.nu = float(E), float(nu)
        self.dpn = 3 if physics == "elastic" else 1
        self.e_min = self.E * (e_min_ratio if e_min_ratio is not None else (1e-9 if physics == "elastic" else 1e-3))
        nx, ny, nz = self.shape
        self.nn = (nx + 1) * (ny + 1) * (nz + 1)
        self.ndof = self.dpn * self.nn
        full = np.ones(self.shape, bool)
        self.active = full if active is None else np.asarray(active, bool).copy()
        self.solid = np.zeros(self.shape, bool) if solid is None else (np.asarray(solid, bool) & self.active)
        self.void = np.zeros(self.shape, bool) if void is None else (np.asarray(void, bool) & self.active)
        if np.any(self.solid & self.void):
            raise ValueError("a cell is both solid and void")
        self.design = self.active & ~self.solid & ~self.void
        if not self.design.any():
            raise ValueError("no design cells")
        fixed = np.zeros(self.ndof, bool) if fixed is None else np.asarray(fixed, bool).ravel()
        if fixed.shape != (self.ndof,):
            raise ValueError("fixed: one flag per dof required")
        self.fixed = fixed
        L = np.atleast_2d(np.asarray(loads, float))
        if L.shape[1] != self.ndof or not np.isfinite(L).all() or not np.any(L):
            raise ValueError("loads: finite nonzero (ncase, ndof) array required")
        # load on a node that no active cell holds is dropped by the solver: refuse it rather than lose it silently
        live = np.zeros(self.nn, bool)
        nx, ny, nz = self.shape
        i, j, k = np.nonzero(self.active & ~self.void)
        for cx, cy, cz in _CORNER:
            live[node_index(self.shape, i + cx, j + cy, k + cz)] = True
        Ln = np.abs(L).reshape(len(L), self.nn, self.dpn).sum(axis=(0, 2))
        if Ln[~live].sum() > 1e-9 * Ln.sum():
            raise ValueError(f"loads: {100 * Ln[~live].sum() / Ln.sum():.3g} % of the load sits outside the part")
        self.loads = L
        self.weights = np.ones(len(L)) if weights is None else np.asarray(weights, float)
        Ke, Kt, self.B0, self.D = hex_matrices(self.h, self.nu if physics == "elastic" else None)
        self.Ku = Ke if physics == "elastic" else Kt
        self.mg = Multigrid(self.shape, self.h, self.dpn, self.Ku, self.fixed)
        self._u = [None] * len(L)
        self.stats = {"cg_iterations": 0, "solves": 0}
        self.beta, self.eta = 1.0, 0.5
        self.am = None

    # ---------------------------------------------------------------- design chain
    def configure(self, s: Settings):
        self.s = s
        self.kernel = cone_kernel(max(1.0, s.filter_radius))
        act = self.active.astype(float)
        self.wsum = ndimage.convolve(act, self.kernel, mode="constant")
        self.wsum[~self.active] = 1.0
        self.am = AMFilter(*s.overhang) if s.overhang else None
        if self.am:
            pf = self.active if self.plate_from is None else (self.plate_from & self.active)
            self.am.set_envelope(pf if pf.any() else self.active)
        for a in s.symmetry:
            if not np.array_equal(self.active, np.flip(self.active, a)):
                raise ValueError(f"symmetry about axis {a}: the design envelope is not symmetric")
        if s.extrusion is not None:
            a = s.extrusion
            # prismatic within the part's span along the axis (the grid around it may be padded)
            occ = self.active.any(axis=tuple(i for i in range(3) if i != a))
            span = np.zeros(self.shape[a], bool)
            span[np.argmax(occ):len(occ) - np.argmax(occ[::-1])] = True
            span = span.reshape([-1 if i == a else 1 for i in range(3)])
            if not np.array_equal(self.active, np.broadcast_to(self.active.any(axis=a, keepdims=True), self.shape) & span):
                raise ValueError("extrusion: the design envelope is not prismatic along that axis")
            self._ext_count = np.maximum(1, self.active.sum(axis=a, keepdims=True))

    def _sym(self, z):
        x = z
        for a in self.s.symmetry:
            x = 0.5 * (x + np.flip(x, a))
        if self.s.extrusion is not None:
            # mean over the part's cells of each column (padding cells do not dilute it); masked so the map stays
            # symmetric (its own adjoint): A = M P M with P the column average
            a = self.s.extrusion
            x = self.active * np.broadcast_to((x * self.active).sum(axis=a, keepdims=True) / self._ext_count, self.shape)
        return x

    _sym_T = _sym          # both maps are symmetric (self-adjoint) averaging operators

    def _filter(self, x):
        return ndimage.convolve(x * self.active, self.kernel, mode="constant") / self.wsum * self.active

    def _filter_T(self, g):
        return ndimage.convolve(g * self.active / self.wsum, self.kernel, mode="constant") * self.active

    def _project(self, t, eta=None):
        b, n = self.beta, (self.eta if eta is None else eta)
        den = math.tanh(b * n) + math.tanh(b * (1 - n))
        th = np.tanh(b * (t - n))
        return (math.tanh(b * n) + th) / den, b * (1 - th ** 2) / den

    def _pre(self, z):
        """Symmetry, filter, overhang: everything before the projection (the AM filter caches for its adjoint)."""
        x = self._sym(np.where(self.design, z, np.where(self.solid, 1.0, 0.0)))
        xf = self._filter(x)
        if self.s.extrusion is not None:          # the truncated kernel at the ends would break the prism again
            xf = self._sym(xf)
        return self.am.forward(xf) if self.am else xf

    def physical(self, z):
        return self._post(self._pre(z), self.eta)

    def _post(self, xa, eta):
        rho, drho = self._project(xa, eta)
        rho = np.where(self.solid, 1.0, np.where(self.design, rho, 0.0))
        drho = np.where(self.design, drho, 0.0)
        return rho, drho

    def chain_T(self, g_rho, drho):
        g = g_rho * drho
        if self.am:
            g = self.am.adjoint(g)
        if self.s.extrusion is not None:
            g = self._sym_T(g)
        g = self._filter_T(g)
        g = self._sym_T(g)
        return np.where(self.design, g, 0.0)

    # ---------------------------------------------------------------- analysis
    def moduli(self, rho):
        return np.where(self.active & ~self.void, self.e_min + rho ** self.s.penal * (self.E - self.e_min), 0.0)

    def analyse(self, Ebox, warm=True):
        self.mg.set_moduli(Ebox)
        us = []
        for i, f in enumerate(self.loads):
            u, it = self.mg.solve(f, x0=self._u[i] if warm else None, tol=self.s.solver_tol)
            self.stats["cg_iterations"] += it; self.stats["solves"] += 1
            if warm:
                self._u[i] = u
            us.append(u)
        return us

    def element_energy(self, u):
        lv = self.mg.levels[0]
        en = lv.enodes_all
        edof = (self.dpn * en[:, :, None] + np.arange(self.dpn)).reshape(len(en), -1) if self.dpn > 1 else en
        ue = u[edof]
        return np.einsum("ei,ij,ej->e", ue, self.Ku, ue).reshape(self.shape)

    def evaluate(self, z):
        """Compliance of the eroded design (projection threshold eta_erode > 0.5), volume of the blueprint (0.5).
        Optimising the eroded design is the compliance form of the robust formulation (Wang, Lazarov, Sigmund 2011;
        Lazarov et al. 2016): a member only counts once it survives erosion, so the blueprint cannot keep members
        thinner than about the filter diameter. Same cost as the plain projection: one analysis per step."""
        xa = self._pre(z)
        rho, drho_b = self._post(xa, self.eta)
        if self.s.eta_erode:
            rho_a, drho = self._post(xa, self.s.eta_erode)
        else:
            rho_a, drho = rho, drho_b
        us = self.analyse(self.moduli(rho_a))
        c, g = 0.0, np.zeros(self.shape)
        dEdrho = self.s.penal * rho_a ** (self.s.penal - 1) * (self.E - self.e_min)
        for w, f, u in zip(self.weights, self.loads, us):
            c += w * float(f @ u)
            g -= w * dEdrho * self.element_energy(u)
        nact = float(self.active.sum() - self.void.sum())
        dc = self.chain_T(g, drho)
        dv = self.chain_T(np.where(self.active & ~self.void, 1.0 / nact, 0.0), drho_b)
        if not np.isfinite(c) or c <= 0 or not np.isfinite(dc).all():
            raise ValueError("nonfinite or nonpositive response")
        return c, dc, dv, rho, us

    def volume_fraction(self, rho):
        m = self.active & ~self.void
        return float(rho[m].mean())

    # ---------------------------------------------------------------- optimisation
    def optimize(self, s: Settings | None = None, progress: Callable = lambda *_: None,
                 cancelled: Callable[[], bool] = lambda: False):
        s = s or Settings()
        if not 0.03 <= s.volume_fraction <= 0.9:
            raise ValueError("volume_fraction: 0.03..0.9")
        self.configure(s)
        m = self.active & ~self.void
        solid_share = float(self.solid[m].mean())
        if s.volume_fraction <= solid_share:
            raise ValueError("volume_fraction must exceed the share of solid non-design cells")
        z = np.where(self.design, (s.volume_fraction - solid_share) / float(self.design[m].mean()), 0.0)
        z = np.clip(z, 0, 1)
        history, t0, reason = [], time.monotonic(), "iteration_budget"
        self.beta, since = 1.0, 0
        for it in range(s.iterations):
            if cancelled():
                raise Cancelled()
            c, dc, dv, rho, _ = self.evaluate(z)
            history.append({"iteration": it, "objective": c, "volume_fraction": self.volume_fraction(rho),
                            "beta": self.beta, "elapsed_s": time.monotonic() - t0})
            progress("genesis.iterating", min(0.95, (it + 1) / s.iterations), {"iteration": it + 1, "objective": c})
            znew = self._oc(z, dc, dv, s.volume_fraction, s.move if self.beta < 8 else s.move / 2)
            change = float(np.max(np.abs(znew - z)[self.design]))
            z, since = znew, since + 1
            if time.monotonic() - t0 > s.timeout_s:
                reason = "time_budget"; break
            # settled: the design stops moving, or (at full projection, where single cells keep flipping) the
            # objective stops changing: < 0.1 % over the last 5 steps of this beta
            recent = [h["objective"] for h in history[-5:]]
            flat = since >= 5 and (max(recent) - min(recent)) <= 1e-3 * abs(recent[-1])
            settled = since >= 5 and (change < s.tol or flat)
            if self.beta >= s.beta_max:
                if settled:
                    reason = "converged"; break
            elif (settled or since >= s.beta_every) and it < s.iterations - 10:
                self.beta, since = min(s.beta_max, 2 * self.beta), 0
        c, _, _, rho, us = self.evaluate(z)
        self.z, self.rho = z, rho
        return self._finish(rho, c, history, reason, time.monotonic() - t0)

    def _oc(self, z, dc, dv, target, move):
        d = self.design
        zd = z[d]
        B = np.maximum(1e-30, -dc[d]) / np.maximum(1e-30, dv[d])
        lo, hi = 1e-30, 1e30
        new = z.copy()
        for _ in range(300):
            mid = math.sqrt(lo * hi)
            new[d] = np.clip(zd * np.sqrt(B / mid), np.maximum(0, zd - move), np.minimum(1, zd + move))
            if self.volume_fraction(self.physical(new)[0]) > target:
                lo = mid
            else:
                hi = mid
            if hi / lo < 1 + 1e-7:
                break
        return new

    # ---------------------------------------------------------------- result
    def clean(self, solid):
        """Keep only the pieces that touch a support (and, for structures, all of them together carry every load).
        Face connectivity: pieces that touch only along an edge are not structurally connected."""
        lab, n = ndimage.label(solid)
        if n == 0:
            return solid, {"pieces": 0, "kept": 0, "removed_share": 0.0, "loads_carried": False}
        node_of = lambda m: np.nonzero(m.reshape(-1, self.dpn).any(axis=1) if self.dpn > 1 else m)[0]
        fixed_nodes = node_of(self.fixed)
        loaded_nodes = node_of(np.any(self.loads != 0, axis=0))
        en = self.mg.levels[0].enodes_all
        lab_e = lab.ravel()
        def pieces_touching(nodes):
            hit = np.isin(en, nodes).any(axis=1) & (lab_e > 0)
            return set(np.unique(lab_e[hit]).tolist())
        sup = pieces_touching(fixed_nodes)
        keep = sup
        carried = True
        if self.physics == "elastic":
            ld = pieces_touching(loaded_nodes)
            keep = sup & ld if sup & ld else sup
            # every loaded node must sit on a kept piece
            on = np.zeros(self.nn, bool)
            on[np.unique(en[np.isin(lab_e, list(keep))])] = True
            carried = bool(np.all(on[loaded_nodes]))
        out = np.isin(lab, list(keep))
        # user-defined solid regions always stay; report when one is not attached to the kept structure
        detached = bool(np.any(self.solid & ~out))
        out |= self.solid
        removed = float(solid.sum() - out.sum()) / max(1, solid.sum())
        return out, {"pieces": int(n), "kept": len(keep), "removed_share": max(0.0, removed),
                     "loads_carried": carried, "non_design_detached": detached}

    def min_member(self, solid, cover=0.95):
        """Thinnest member, in cells: `cover` of the volume lies in members at least this thick (local thickness).
        Single voxels at stair steps are not members, a thin plate over a large area is. Resolution half a cell."""
        return min_member_cells(solid, cover)

    def binary_threshold(self, rho):
        """0.5, or lower when a still grey design would lose volume at 0.5: then the density whose threshold keeps
        the volume of the design (not below 0.2). A grey cantilever extruded along its width kept 20 % of 30 % at 0.5
        and its tip came apart (load not carried); a converged design is the same either way."""
        d = self.design & ~self.void
        if not d.any():
            return 0.5
        target = self.volume_fraction(rho)
        if self.volume_fraction(np.where(d, (rho >= 0.5).astype(float), rho)) >= 0.97 * target:
            return 0.5
        lo, hi = 0.2, 0.5
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if self.volume_fraction(np.where(d, (rho >= mid).astype(float), rho)) >= target:
                lo = mid
            else:
                hi = mid
        return lo

    def _finish(self, rho, c, history, reason, elapsed):
        self.threshold = self.binary_threshold(rho)
        base = self.active & ~self.void

        def cut(t):
            s, added = bridge_diagonals(((rho >= t) & base) | self.solid, rho, base)
            self.bridged = added
            return self.clean(s)
        solid, pieces = cut(self.threshold)
        # the joint of a member to a kept face can sit just under the threshold while the design carries the load
        # through it (cantilever extruded along z, 12k cells, 150 steps: 4 pieces, tip detached at 0.5). Then take
        # the highest lower threshold that connects every load and kept region, and report it
        t = self.threshold
        while (not pieces["loads_carried"] or pieces.get("non_design_detached")) and t > 0.2 + 1e-9:
            t = round(t - 0.05, 2)
            s2, p2 = cut(t)
            if p2["loads_carried"] and not p2.get("non_design_detached"):
                solid, pieces, self.threshold = s2, p2, t
                break
        else:
            if t != self.threshold:
                solid, pieces = cut(self.threshold)          # nothing better: the part at the first threshold
        Eb = np.where(self.active & ~self.void, np.where(solid, self.E, self.e_min), 0.0)
        loop_tol, self.s.solver_tol = self.s.solver_tol, min(self.s.solver_tol, 1e-8)
        us = self.analyse(Eb, warm=False)
        c_bin = float(sum(w * f @ u for w, f, u in zip(self.weights, self.loads, us)))
        # reference: the whole design space filled with material (the part as it was). The share of its stiffness
        # (or heat conductance) the optimised part keeps is the honest figure; the grey SIMP start is not a design
        Efull = np.where(self.active & ~self.void, self.E, 0.0)
        c_full = float(sum(w * f @ u for w, f, u in zip(self.weights, self.loads, self.analyse(Efull, warm=False))))
        grey = float(np.mean((rho[self.design] > 0.1) & (rho[self.design] < 0.9)))
        thin = self.min_member(solid)
        warn = []
        if not pieces["loads_carried"]:
            warn.append("load_not_carried")
        if self.threshold < 0.5:
            warn.append("threshold_lowered")
        if pieces.get("non_design_detached"):
            warn.append("non_design_region_detached")
        if pieces["removed_share"] > 0.02:
            warn.append("floating_material_removed")
        if grey > 0.1:
            warn.append("intermediate_densities")
        if self.s.min_member_cells and thin < 0.7 * self.s.min_member_cells:
            warn.append("thin_members_below_target")
        # kept (non-design) cells are imposed after the symmetry / extrusion / overhang maps: check the final part
        if not self.constraints_met(solid):
            warn.append("constraint_not_met")
        if reason != "converged":
            warn.append("not_converged_" + reason)
        res = {
            "method": "SIMP_voxel_H8_multigrid_OC", "physics": self.physics,
            "grid": list(self.shape), "cell_m": self.h, "cells_active": int((self.active & ~self.void).sum()),
            "settings": {**{k: (list(v) if isinstance(v, tuple) else v) for k, v in self.s.__dict__.items()}, "solver_tol": loop_tol},
            "objective": c, "objective_binary": c_bin, "objective_full": c_full,
            "stiffness_kept": c_full / c_bin if c_bin > 0 else None, "volume_fraction": self.volume_fraction(rho),
            "volume_fraction_binary": float(solid[self.active & ~self.void].mean()), "threshold": self.threshold,
            "cells_bridged": int(self.bridged),
            "grey_share": grey, "min_member_m": thin * self.h, "min_member_cells": thin,
            "pieces": pieces, "termination": reason, "iterations": len(history), "elapsed_s": elapsed,
            "solver": dict(self.stats), "history": history, "warnings": warn,
        }
        # maxima over the nodes of the part: empty cells (stiffness e_min) move and heat up without meaning
        on = np.zeros(self.nn, bool)
        i, j, k = np.nonzero(solid)
        for cx, cy, cz in _CORNER:
            on[node_index(self.shape, i + cx, j + cy, k + cz)] = True
        if self.physics == "elastic":
            res["max_displacement_m"] = float(max(np.linalg.norm(u.reshape(-1, 3), axis=1)[on].max() for u in us))
            res["von_mises_max_pa"] = float(self.von_mises(us[0], solid).max())
        else:
            res["max_temperature_rise_k"] = float(max(u[on].max() for u in us))
        self.solid_final, self.u_final = solid, us
        self.s.solver_tol = loop_tol
        return res

    def constraints_met(self, solid, unsupported_share=0.01):
        """The 0/1 part against the manufacturing settings: mirror symmetry, prism, self-supporting (overhang)."""
        for a in self.s.symmetry:
            if not np.array_equal(solid, np.flip(solid, a)):
                return False
        if self.s.extrusion is not None:
            a = self.s.extrusion
            if not np.array_equal(solid, np.broadcast_to(solid.any(axis=a, keepdims=True), self.shape) & self.active):
                return False
        if self.s.overhang:
            ax, d = self.s.overhang
            s = np.moveaxis(solid, ax, 0)[::-1 if d < 0 else 1]
            s0 = self.am.start                             # the same plate the filter used
            p = np.pad(s, ((0, 0), (1, 1), (1, 1)))
            below = (p[:-1, 1:-1, 1:-1] | p[:-1, :-2, 1:-1] | p[:-1, 2:, 1:-1] | p[:-1, 1:-1, :-2] | p[:-1, 1:-1, 2:])
            uns = s[s0 + 1:] & ~below[s0:]
            if uns.sum() > unsupported_share * max(1, s.sum()):
                return False
        return True

    def von_mises(self, u, solid):
        """Element-centre von Mises stress of the 0/1 part (a voxel estimate; staircase surfaces overstate peaks)."""
        en = self.mg.levels[0].enodes_all
        edof = (3 * en[:, :, None] + np.arange(3)).reshape(len(en), -1)
        sig = (u[edof] @ self.B0.T) @ self.D.T * self.E
        sx, sy, sz, txy, tyz, txz = sig.T
        vm = np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (txy ** 2 + tyz ** 2 + txz ** 2))
        return np.where(solid.ravel(), vm, 0.0).reshape(self.shape)

    # ---------------------------------------------------------------- geometry
    def node_coords(self):
        nx, ny, nz = self.shape
        i, j, k = np.meshgrid(np.arange(nx + 1), np.arange(ny + 1), np.arange(nz + 1), indexing="ij")
        return self.origin + self.h * np.column_stack([i.ravel(), j.ravel(), k.ravel()])

    def surface(self, field=None, level=0.5):
        """Closed triangle surface of the part. field: cell values (default the cleaned 0/1 part smoothed by the
        filter), sampled at the grid nodes; marching tetrahedra on the Kuhn split of every cell. Outside the grid the
        field is 0, so the surface is always closed."""
        if field is None:
            # projected densities restricted to the cleaned part: sharp (beta continuation) and without floating bits
            grow = ndimage.binary_dilation(self.solid_final, iterations=1)
            field = np.where(grow, self.rho, 0.0)
            field = np.where(self.solid_final & (field < 0.5), 0.5 + 1e-3, field)
            field = np.where(self.solid, 1.0, field)
        # sample points = cell centres (dual grid) with a ring of zeros: the 0.5 level then lies on the voxel faces
        return marching_tets(np.pad(field, 1), self.h, self.origin - 0.5 * self.h, level)


def marching_tets(V, h, origin, level):
    """Iso-surface of a nodal grid field by marching tetrahedra (6 Kuhn tets per cell, shared diagonals), so the
    surface is closed and consistently oriented with normals pointing to lower values."""
    nx, ny, nz = (d - 1 for d in V.shape)
    # a node exactly at the level makes zero-area triangles whose orientation is undefined (averages of 0/1 cells
    # hit 0.5 exactly): move such nodes slightly outside
    V = np.where(np.abs(V - level) < 1e-6, level - 1e-3, V)
    i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    i, j, k = i.ravel(), j.ravel(), k.ravel()
    cells = np.nonzero((np.minimum.reduce([V[i + a, j + b, k + c] for a in (0, 1) for b in (0, 1) for c in (0, 1)]) < level) &
                       (np.maximum.reduce([V[i + a, j + b, k + c] for a in (0, 1) for b in (0, 1) for c in (0, 1)]) >= level))[0]
    i, j, k = i[cells], j[cells], k[cells]
    vid = lambda b: ((i + (b & 1)) * (ny + 1) + (j + ((b >> 1) & 1))) * (nz + 1) + (k + ((b >> 2) & 1))
    paths = [(1, 2, 4), (1, 4, 2), (2, 1, 4), (2, 4, 1), (4, 1, 2), (4, 2, 1)]
    flat = V.ravel()
    tris = []
    for a, b, c in paths:
        tris.append(_tet_iso(np.column_stack([vid(0), vid(a), vid(a | b), vid(7)]), flat, level))
    E = np.concatenate([t for t in tris if len(t)]) if any(len(t) for t in tris) else np.zeros((0, 2, 2), int)
    if not len(E):
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    # E: (m,3,2) each triangle vertex is an edge (node a, node b); merge identical edges into one vertex
    key = np.sort(E.reshape(-1, 2), axis=1)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    va, vb = flat[uniq[:, 0]], flat[uniq[:, 1]]
    t = np.clip((level - va) / np.where(vb != va, vb - va, 1), 0, 1)
    coord = lambda n: np.column_stack([n // ((ny + 1) * (nz + 1)), (n // (nz + 1)) % (ny + 1), n % (nz + 1)]).astype(float)
    P = origin + h * (coord(uniq[:, 0]) * (1 - t)[:, None] + coord(uniq[:, 1]) * t[:, None])
    F = inv.reshape(-1, 3)
    # orient: the normal must point from the inside node to the outside node of the first edge
    e0 = E[:, 0]
    C0, C1 = coord(e0[:, 0]), coord(e0[:, 1])
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    flip = np.einsum("ij,ij->i", n, C1 - C0) < 0
    F[flip] = F[flip][:, [0, 2, 1]]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    return P, F


def _tet_iso(T, flat, level):
    """Iso-surface triangles inside tets T (m,4); every triangle vertex is an edge given as (inside node, outside node)."""
    inside = flat[T] >= level
    code = inside @ np.array([1, 2, 4, 8])
    out = []
    for cs in range(1, 15):
        m = code == cs
        if not m.any():
            continue
        ins = [q for q in range(4) if cs >> q & 1]
        outs = [q for q in range(4) if not cs >> q & 1]
        Tm = T[m]
        if len(ins) == 1:
            tris = [[(ins[0], o) for o in outs]]
        elif len(outs) == 1:
            tris = [[(i, outs[0]) for i in ins]]
        else:
            a, b = ins; c, d = outs
            q = [(a, c), (a, d), (b, d), (b, c)]          # a closed cycle around the quad
            tris = [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
        for tri in tris:
            out.append(np.stack([Tm[:, [p, r]] for p, r in tri], axis=1))
    return np.concatenate(out) if out else np.zeros((0, 3, 2), int)

def write_stl(path, P, F, name=b"NovaSolver Studio Genesis"):
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n /= np.maximum(1e-300, np.linalg.norm(n, axis=1))[:, None]
    rec = np.zeros(len(F), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, P[F]
    with open(path, "wb") as fh:
        fh.write(name.ljust(80, b" ")[:80]); fh.write(struct.pack("<I", len(F))); fh.write(rec.tobytes())


def surface_checks(P, F):
    """Closed, consistently oriented, outward (positive enclosed volume) and manifold edges."""
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, cnt = np.unique(key, axis=0, return_counts=True)
    _, dcnt = np.unique(e, axis=0, return_counts=True)
    vol = float(np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6)
    some = len(F) > 0                                   # no triangles is not a closed part (np.all of nothing is True)
    return {"triangles": int(len(F)), "closed": some and bool(np.all(cnt % 2 == 0)),
            "manifold_edges": some and bool(np.all(cnt == 2)), "oriented": some and bool(np.all(dcnt == 1)), "volume_m3": vol}


def bridge_diagonals(solid, rho, allowed, max_passes=20):
    """Join cells that touch only along an edge or at a corner by adding the bridging cell of higher density.
    A staircase diagonal one cell thick is connected in the grey design (the shared edge nodes carry force) but
    is a hinge in the 0/1 part: the face-connected cleanup removed it (cantilever extruded along its width: 11
    pieces, tip detached) and its STL would not be manifold. Returns the new solid and the number of cells added."""
    solid = solid.copy()
    n = solid.shape
    added = 0
    for _ in range(max_passes):
        changed = 0
        # edge contacts: P and P + da e_a + db e_b solid, both bridges P + da e_a, P + db e_b empty
        for a, b in ((0, 1), (0, 2), (1, 2)):
            for da, db in ((1, 1), (1, -1)):
                # views aligned on the base cell P = (i, j); shifts are relative to it on the cropped window
                ia = slice(max(0, -da), n[a] - max(0, da))
                ib = slice(max(0, -db), n[b] - max(0, db))
                def at(oa, ob, arr):
                    s = [slice(None)] * 3
                    s[a] = slice(ia.start + oa, ia.stop + oa)
                    s[b] = slice(ib.start + ob, ib.stop + ob)
                    return arr[tuple(s)]
                P, Q = at(0, 0, solid), at(da, db, solid)
                B1, B2 = at(da, 0, solid), at(0, db, solid)
                hit = P & Q & ~B1 & ~B2
                if not hit.any():
                    continue
                r1 = np.where(at(da, 0, allowed), at(da, 0, rho), -1.0)
                r2 = np.where(at(0, db, allowed), at(0, db, rho), -1.0)
                use1 = hit & (r1 >= r2) & (r1 >= 0)
                use2 = hit & ~use1 & (r2 >= 0)
                v1, v2 = at(da, 0, solid), at(0, db, solid)          # views into `solid`: assignment writes through
                v1[use1] = True
                v2[use2] = True
                changed += int(use1.sum() + use2.sum())
        # corner contacts: P and P + (dx, dy, dz) solid with no solid cell on any of the 6 paths between them;
        # add the face neighbour of higher density, the remaining edge contact is joined in the next pass
        for d in ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1)):
            win = tuple(slice(max(0, -di), ni - max(0, di)) for di, ni in zip(d, n))
            def at3(o, arr):
                return arr[tuple(slice(w.start + oi, w.stop + oi) for w, oi in zip(win, o))]
            P, Q = at3((0, 0, 0), solid), at3(d, solid)
            between = [(d[0], 0, 0), (0, d[1], 0), (0, 0, d[2]), (d[0], d[1], 0), (d[0], 0, d[2]), (0, d[1], d[2])]
            free = np.ones(P.shape, bool)
            for o in between:
                free &= ~at3(o, solid)
            hit = P & Q & free
            if not hit.any():
                continue
            cand = [(o, np.where(at3(o, allowed), at3(o, rho), -1.0)) for o in between[:3]]
            best = np.argmax(np.stack([c for _, c in cand]), axis=0)
            for k, (o, c) in enumerate(cand):
                sel = hit & (best == k) & (c >= 0)
                at3(o, solid)[sel] = True
                changed += int(sel.sum())
        added += changed
        if not changed:
            break
    return solid, added


def min_member_cells(solid, cover=0.95):
    """See Genesis.min_member. Local thickness (Hildebrand-Ruegsegger): a cell has thickness >= t when a ball
    inside the part with a centre at distance >= t from the void reaches it. On the grid refined twice a member m
    cells thick is 2m fine cells thick and its centre sits at distance m from the void, so the answer in cells is
    the largest t whose balls still reach `cover` of the volume. The sharp edges of square bars are reached only
    by smaller balls; `cover` leaves them out."""
    if not solid.any():
        return 0.0
    idx = np.nonzero(solid)
    box = tuple(slice(a.min(), a.max() + 1) for a in idx)
    fine = np.pad(solid[box], 1).repeat(2, 0).repeat(2, 1).repeat(2, 2)
    dt = ndimage.distance_transform_edt(fine)
    total = int(fine.sum())
    ts = np.unique(dt[fine])

    def covered(t):
        centres = dt >= t - 1e-9
        reach = ndimage.distance_transform_edt(~centres)
        # every cell closer to c than dt(c) is solid: the largest ball inside the part centred at c. One fine cell
        # (half a cell) of slack absorbs the staircase of a voxel surface; without it a round rod 7 cells across
        # measures 1 cell
        return int(np.count_nonzero(fine & (reach < t + 1.0))) >= cover * total

    lo, hi = 0, len(ts) - 1                     # ts[0] = 1 always covers everything
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if covered(ts[mid]):
            lo = mid
        else:
            hi = mid - 1
    return float(ts[lo])


# ======================================================================== reference problems
def node_index(shape, i, j, k):
    nx, ny, nz = shape
    return (np.asarray(i) * (ny + 1) + np.asarray(j)) * (nz + 1) + np.asarray(k)


def cantilever(nx=48, ny=8, nz=24, length=2.0, load=1.0, E=1.0, nu=0.3):
    """x = 0 face clamped; a downward line load across the width at mid-height of the free end."""
    h = length / nx
    shape = (nx, ny, nz)
    nn = (nx + 1) * (ny + 1) * (nz + 1)
    fixed = np.zeros((nn, 3), bool)
    J, K = np.meshgrid(np.arange(ny + 1), np.arange(nz + 1), indexing="ij")
    fixed[node_index(shape, 0, J, K).ravel()] = True
    f = np.zeros((nn, 3))
    nodes = node_index(shape, nx, np.arange(ny + 1), nz // 2)
    f[nodes, 2] = -load / len(nodes)
    return Genesis(shape, h, E=E, nu=nu, fixed=fixed, loads=f.ravel())


def heat_plate(n=64, nz=2, size=1.0, k=1.0, q=1.0, sink=0.1):
    """Volume-to-point problem: uniform heat generation q [W/m3], sink of width sink*size at the middle of x = 0."""
    h = size / n
    shape = (n, n, nz)
    nn = (n + 1) * (n + 1) * (nz + 1)
    fixed = np.zeros(nn, bool)
    J = np.arange(n + 1)
    J = J[np.abs(J * h - size / 2) <= sink * size / 2 + 1e-12]
    JJ, KK = np.meshgrid(J, np.arange(nz + 1), indexing="ij")
    fixed[node_index(shape, 0, JJ, KK).ravel()] = True
    # consistent nodal heat of a uniform source on trilinear hexes: q h^3 / 8 to each of the 8 nodes
    f = np.zeros(nn)
    lv = Level(shape, h, 1, np.zeros((8, 8)), fixed)
    np.add.at(f, lv.enodes_all.ravel(), q * h ** 3 / 8)
    return Genesis(shape, h, physics="thermal", E=k, fixed=fixed, loads=f)
