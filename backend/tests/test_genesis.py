"""Genesis voxel topology optimisation: solver, exact gradients through every design map, results and geometry."""
import numpy as np
import pytest

from novastudio import genesis as gx
from novastudio import fem_tet10 as fe


def test_multigrid_matches_direct_solve():
    g = gx.cantilever(nx=16, ny=4, nz=8)
    g.configure(gx.Settings())
    rng = np.random.default_rng(0)
    E = rng.uniform(0.01, 1.0, g.shape)
    mg = gx.Multigrid(g.shape, g.h, 3, g.Ku, g.fixed, coarse_dofs=200)
    assert len(mg.levels) >= 2
    mg.set_moduli(E)
    u, it = mg.solve(g.loads[0], tol=1e-10, maxiter=500)
    lv = mg.levels[0]
    A = lv.assemble()
    free = np.nonzero(~lv.dead)[0]
    ud = np.zeros_like(u)
    ud[free] = fe.spd_factor(A[free][:, free]).solve(g.loads[0][free])
    assert np.abs(u - ud).max() <= 1e-7 * np.abs(ud).max()
    assert it < 100


def test_hex_patch_uniform_strain():
    """Unit matrices reproduce a uniform stress state: zero nodal residual inside a uniformly strained block."""
    Ke, Kt, B0, D = gx.hex_matrices(0.1, 0.3)
    assert np.allclose(Ke, Ke.T) and np.allclose(Kt, Kt.T)
    X = gx._CORNER * 0.1
    u = (X @ np.array([[1e-3, 0, 0], [0, 0, 0], [0, 0, 0]]).T).ravel()   # u_x = 1e-3 x
    assert np.allclose(B0 @ u, [1e-3, 0, 0, 0, 0, 0])
    assert np.abs(Ke @ np.tile([1.0, 0, 0], 8)).max() < 1e-12            # rigid translation: no force
    assert np.abs(Kt @ np.ones(8)).max() < 1e-12


def _fd_check(g, settings, rng, n=4, beta=4.0):
    g.configure(settings)
    g.beta = beta
    z = np.where(g.design, rng.uniform(0.3, 0.8, g.shape), 0.0)
    g.s.solver_tol = 1e-12
    c, dc, dv, rho, _ = g.evaluate(z)
    cells = np.argwhere(g.design)
    for idx in cells[rng.choice(len(cells), n, replace=False)]:
        idx = tuple(idx)
        h = 1e-5
        zp, zm = z.copy(), z.copy()
        zp[idx] += h; zm[idx] -= h
        g._u = [None] * len(g.loads)
        fd = (g.evaluate(zp)[0] - g.evaluate(zm)[0]) / (2 * h)
        assert dc[idx] == pytest.approx(fd, rel=2e-4, abs=1e-9 * abs(c))
        vfd = (g.volume_fraction(g.physical(zp)[0]) - g.volume_fraction(g.physical(zm)[0])) / (2 * h)
        assert dv[idx] == pytest.approx(vfd, rel=1e-5, abs=1e-12)


@pytest.mark.parametrize("opts", [
    {},
    {"symmetry": (1,)},
    {"extrusion": 1},
    {"overhang": (2, 1)},
    {"overhang": (0, -1), "symmetry": (1,)},
])
def test_gradients_match_finite_differences(opts):
    g = gx.cantilever(nx=12, ny=4, nz=6)
    _fd_check(g, gx.Settings(filter_radius=1.5, **opts), np.random.default_rng(3))


def test_thermal_gradient():
    g = gx.heat_plate(n=10, nz=2)
    _fd_check(g, gx.Settings(filter_radius=1.5), np.random.default_rng(4))


def test_two_load_cases_gradient():
    g0 = gx.cantilever(nx=12, ny=4, nz=6)
    f2 = np.zeros((g0.nn, 3))
    f2[np.nonzero(g0.loads[0].reshape(-1, 3)[:, 2])[0], 1] = 0.5
    g = gx.Genesis(g0.shape, g0.h, fixed=g0.fixed, loads=np.stack([g0.loads[0], f2.ravel()]), weights=[1.0, 2.0])
    _fd_check(g, gx.Settings(), np.random.default_rng(5))


def test_cantilever_optimisation():
    g = gx.cantilever(nx=32, ny=4, nz=16)
    r = g.optimize(gx.Settings(volume_fraction=0.4, iterations=120))
    assert r["volume_fraction"] == pytest.approx(0.4, abs=3e-3)
    assert r["history"][-1]["objective"] < 0.25 * r["history"][0]["objective"]
    assert r["pieces"]["loads_carried"] and "load_not_carried" not in r["warnings"]
    assert r["objective_binary"] < 1.2 * r["objective"]
    assert r["grey_share"] < 0.1
    P, F = g.surface()
    chk = gx.surface_checks(P, F)
    assert chk["closed"] and chk["oriented"] and chk["volume_m3"] > 0
    voxel_volume = g.solid_final.sum() * g.h ** 3
    assert chk["volume_m3"] == pytest.approx(voxel_volume, rel=0.15)


def test_symmetry_is_exact():
    g = gx.cantilever(nx=16, ny=6, nz=8)
    g.optimize(gx.Settings(volume_fraction=0.35, iterations=40, symmetry=(1,)))
    assert np.allclose(g.rho, np.flip(g.rho, 1))


def test_extrusion_is_prismatic():
    g = gx.cantilever(nx=16, ny=6, nz=8)
    g.optimize(gx.Settings(volume_fraction=0.35, iterations=40, extrusion=1))
    assert np.allclose(g.rho, g.rho[:, :1, :])


def test_overhang_design_is_self_supporting():
    """Built along +z: every solid cell above the first layer rests on a solid cell among its 5 supports below."""
    g = gx.cantilever(nx=24, ny=4, nz=12)
    g.optimize(gx.Settings(volume_fraction=0.4, iterations=120, overhang=(2, 1)))
    s = g.rho >= 0.5
    p = np.pad(s, ((1, 1), (1, 1), (0, 0)))
    below = p[1:-1, 1:-1, :-1] | p[:-2, 1:-1, :-1] | p[2:, 1:-1, :-1] | p[1:-1, :-2, :-1] | p[1:-1, 2:, :-1]
    unsupported = s[:, :, 1:] & ~below
    assert unsupported.sum() <= 0.01 * s.sum()


def test_non_design_solid_kept():
    g = gx.cantilever(nx=16, ny=4, nz=8)
    keep = np.zeros(g.shape, bool); keep[-2:, :, 3:5] = True
    g2 = gx.Genesis(g.shape, g.h, fixed=g.fixed, loads=g.loads, solid=keep)
    g2.optimize(gx.Settings(volume_fraction=0.35, iterations=30))
    assert np.all(g2.rho[keep] == 1.0) and np.all(g2.solid_final[keep])


def test_heat_plate_tree():
    g = gx.heat_plate(n=32, nz=1)
    r = g.optimize(gx.Settings(volume_fraction=0.3, iterations=100))
    assert r["volume_fraction"] == pytest.approx(0.3, abs=3e-3)
    assert r["history"][-1]["objective"] < 0.2 * r["history"][0]["objective"]


def test_stl_roundtrip(tmp_path):
    g = gx.cantilever(nx=16, ny=4, nz=8)
    g.optimize(gx.Settings(volume_fraction=0.4, iterations=30))
    P, F = g.surface()
    gx.write_stl(tmp_path / "part.stl", P, F)
    assert (tmp_path / "part.stl").stat().st_size == 84 + 50 * len(F)


def test_input_validation():
    g = gx.cantilever(nx=8, ny=2, nz=4)
    with pytest.raises(ValueError):
        g.optimize(gx.Settings(volume_fraction=0.01))
    with pytest.raises(ValueError):
        gx.Genesis(g.shape, g.h, fixed=g.fixed, loads=np.zeros(g.ndof))
