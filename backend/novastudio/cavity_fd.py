"""Built-in preview solver: 2D lid-driven cavity, stream function - vorticity, finite differences.

Solved in non-dimensional form (side = 1, lid speed = 1, Re = U L / nu), then scaled back.
Thom's formula for wall vorticity, explicit vorticity transport, sparse LU for the Poisson equation.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

GRID = {"coarse": 41, "normal": 65, "fine": 129}

# Ghia, Ghia & Shin (1982), Table I, Re = 100: u on the vertical centreline x = 0.5
GHIA_RE100_Y = np.array([1.0, 0.9766, 0.9688, 0.9609, 0.9531, 0.8516, 0.7344, 0.6172, 0.5, 0.4531,
                         0.2813, 0.1719, 0.1016, 0.0703, 0.0625, 0.0547, 0.0])
GHIA_RE100_U = np.array([1.0, 0.84123, 0.78871, 0.73722, 0.68717, 0.23151, 0.00332, -0.13641, -0.20581,
                         -0.21090, -0.15662, -0.10150, -0.06434, -0.04775, -0.04192, -0.03717, 0.0])


def solve(re: float, size: str = "normal", tol: float = 1e-5, t_max: float = 80.0,
          progress: Callable[[str, float, dict], None] = lambda *_: None,
          should_stop: Callable[[], bool] = lambda: False) -> dict:
    n = GRID[size]
    h = 1.0 / (n - 1)
    m = n - 2
    lap = sp.diags([1, 1, -4, 1, 1], [-m, -1, 0, 1, m], shape=(m * m, m * m), format="lil", dtype=float)
    for i in range(1, m):                       # no wrap-around between rows
        lap[i * m, i * m - 1] = 0
        lap[i * m - 1, i * m] = 0
    lu = spla.splu((lap / h**2).tocsc())

    psi = np.zeros((n, n))   # index [j, i] = [y, x]
    w = np.zeros((n, n))
    dt = 0.9 * min(h * h * re / 4.0, h / 1.0)
    t, it, res = 0.0, 0, 1.0
    history = []
    while t < t_max:
        # Poisson: lap(psi) = -w on interior
        psi[1:-1, 1:-1] = lu.solve(-w[1:-1, 1:-1].ravel()).reshape(m, m)
        # wall vorticity (Thom)
        w[0, :] = -2 * psi[1, :] / h**2
        w[-1, :] = -2 * psi[-2, :] / h**2 - 2.0 / h
        w[:, 0] = -2 * psi[:, 1] / h**2
        w[:, -1] = -2 * psi[:, -2] / h**2
        u = (psi[2:, 1:-1] - psi[:-2, 1:-1]) / (2 * h)
        v = -(psi[1:-1, 2:] - psi[1:-1, :-2]) / (2 * h)
        wx = (w[1:-1, 2:] - w[1:-1, :-2]) / (2 * h)
        wy = (w[2:, 1:-1] - w[:-2, 1:-1]) / (2 * h)
        lw = (w[1:-1, 2:] + w[1:-1, :-2] + w[2:, 1:-1] + w[:-2, 1:-1] - 4 * w[1:-1, 1:-1]) / h**2
        dw = dt * (-u * wx - v * wy + lw / re)
        w[1:-1, 1:-1] += dw
        res = float(np.max(np.abs(dw)) / dt)
        t += dt
        it += 1
        if it % 200 == 0:
            history.append([it, res])
            progress("job.iterating", min(0.95, 0.05 + 0.9 * np.log10(1 / max(res, tol)) / np.log10(1 / tol)), {"res": res})
            if should_stop():
                break
        if res < tol:
            break

    x = np.linspace(0, 1, n)
    U = np.zeros((n, n)); V = np.zeros((n, n))
    U[1:-1, 1:-1] = (psi[2:, 1:-1] - psi[:-2, 1:-1]) / (2 * h)
    V[1:-1, 1:-1] = -(psi[1:-1, 2:] - psi[1:-1, :-2]) / (2 * h)
    U[-1, :] = 1.0
    # centreline u(y) at x = 0.5 (n is odd, so the centre column is a grid line)
    uc = U[:, n // 2]
    return {"n": n, "x": x, "psi": psi, "u": U, "v": V, "iterations": it, "residual": res,
            "converged": res < tol, "history": history, "centerline_y": x, "centerline_u": uc}


def ghia_error(result: dict) -> dict:
    u_at = np.interp(GHIA_RE100_Y, result["centerline_y"], result["centerline_u"])
    err = np.abs(u_at - GHIA_RE100_U)
    return {"mean_abs": float(err.mean()), "max_abs": float(err.max()),
            "u_min": float(result["centerline_u"].min()), "u_min_ref": float(GHIA_RE100_U.min()),
            "points": [[float(y), float(a), float(b)] for y, a, b in zip(GHIA_RE100_Y, u_at, GHIA_RE100_U)]}
