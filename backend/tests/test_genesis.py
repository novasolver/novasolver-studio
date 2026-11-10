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
    {"eta_erode": 0.8},
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


@pytest.mark.parametrize("physics", ["elastic", "thermal"])
def test_coarse_operators_are_galerkin(physics):
    """Each coarse level equals P^T A P of the level above (element-wise Galerkin), also with void cells."""
    dpn =3 if physics == "elastic" else 1
    shape = (8, 8, 8)
    Ku = gx.Genesis((4, 4, 4), 1e-3, physics=physics, active=np.ones((4, 4, 4), bool),
                    fixed=np.r_[np.ones(25 * dpn, bool), np.zeros(100 * dpn, bool)],
                    loads=np.r_[np.zeros(124 * dpn), np.ones(dpn)]).Ku
    nn = 9 ** 3
    mg = gx.Multigrid(shape, 1e-3, dpn, Ku, np.zeros(nn * dpn, bool), coarse_dofs=10)
    assert len(mg.levels) >= 3
    rng = np.random.default_rng(1)
    E = rng.uniform(1e-3, 1, shape); E[rng.random(shape) < 0.3] = 0.0
    mg.set_moduli(E)
    for l in range(1, len(mg.levels)):
        Af, Ac, P = mg.levels[l - 1].assemble(), mg.levels[l].assemble(), mg.P[l - 1]
        ref = (P.T @ Af @ P).toarray()
        assert np.allclose(Ac.toarray(), ref, atol=1e-9 * np.abs(ref).max())


def test_empty_surface_is_not_closed():
    chk = gx.surface_checks(np.zeros((0, 3)), np.zeros((0, 3), int))
    assert not chk["closed"] and not chk["oriented"] and not chk["manifold_edges"]


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


def _lifted_cantilever(nx=12, ny=4, nz=8, gap=2):
    """Cantilever whose part starts `gap` layers above the bottom of the grid (as in a padded case grid)."""
    g0 = gx.cantilever(nx=nx, ny=ny, nz=nz)
    active = np.ones(g0.shape, bool); active[:, :, :gap] = False
    return gx.Genesis(g0.shape, g0.h, fixed=g0.fixed, loads=g0.loads, active=active)


def test_overhang_plate_under_a_lifted_part():
    """The build plate is the lowest layer of the part, not the bottom of the grid: a lifted part is still printable
    and the gradient is exact."""
    _fd_check(_lifted_cantilever(), gx.Settings(filter_radius=1.5, overhang=(2, 1)), np.random.default_rng(6))
    g = _lifted_cantilever(nx=24, ny=4, nz=14)
    r = g.optimize(gx.Settings(volume_fraction=0.4, iterations=80, overhang=(2, 1)))
    assert r["volume_fraction"] == pytest.approx(0.4, abs=5e-3)
    assert r["pieces"]["loads_carried"]


def test_grid_shape_gives_a_small_coarse_grid():
    for cells, dpn in (((92, 40, 30), 3), ((60, 60, 6), 1), ((7, 7, 7), 3), ((300, 20, 20), 3)):
        shape = gx.grid_shape(cells, dpn)
        assert all(s >= c for s, c in zip(shape, cells))
        g = gx.Multigrid(shape, 1.0, dpn, np.eye(8 * dpn), np.zeros(dpn * int(np.prod(np.add(shape, 1))), bool))
        assert g.levels[-1].ndof <= gx.COARSE_DOFS or np.prod(shape) > 0.5 * gx.MAX_ELEMENTS, (cells, shape)


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


def test_min_member_is_local_thickness():
    """Plates and bars read their thickness; stair voxels on a bar are not members; many thin fins are."""
    mm = gx.min_member_cells
    assert [mm(np.pad(np.ones((30, 30, m), bool), 3)) for m in range(1, 7)] == [1, 2, 3, 4, 5, 6]
    assert [mm(np.pad(np.ones((56, m, m), bool), 3)) for m in (2, 4, 6)] == [2, 4, 6]
    bar = np.zeros((60, 20, 20), bool); bar[2:58, 8:12, 8:12] = True; bar[10:50:6, 12, 8] = True
    assert mm(bar) == 4
    x, y, z = np.mgrid[0:60, 0:20, 0:20]
    assert 5 <= mm((np.hypot(y - 10, z - 10) <= 3.5) & (x > 2) & (x < 57)) <= 7      # round rod, 7 across
    plate = np.zeros((60, 60, 20), bool); plate[:, :, 2:8] = True; plate[:, 20:40:2, 8:18] = True
    assert mm(plate) == 1


def test_tension_bar_keeps_the_volume_share_of_stiffness():
    """Known optimum: an end face pulled uniformly, the other end held. The stiffest layout of a volume share v is a
    straight bar of v times the section, whose stiffness is v times the full block's (k = EA/L). With nu = 0 no
    layout of that volume can do better (stiffness_kept <= v); the load is spread over the whole end face, so the
    bar has to widen there and lands a few % below (measured 0.376 for v = 0.4)."""
    nx, ny, nz = 24, 8, 8
    g0 = gx.cantilever(nx=nx, ny=ny, nz=nz)
    f = np.zeros((g0.nn, 3))
    end = gx.node_index(g0.shape, *np.meshgrid(nx, np.arange(ny + 1), np.arange(nz + 1), indexing="ij")).ravel()
    f[end, 0] = 1.0 / len(end)
    g = gx.Genesis(g0.shape, g0.h, fixed=g0.fixed, loads=f.ravel(), nu=0.0)
    r = g.optimize(gx.Settings(volume_fraction=0.4, iterations=80))
    v = r["volume_fraction_binary"]
    assert 0.9 * v <= r["stiffness_kept"] <= v * (1 + 1e-6)
    assert r["pieces"]["loads_carried"]


def _thin_share(solid, t):
    """Share of the volume not reached by inscribed balls of local thickness t cells (see min_member_cells)."""
    from scipy import ndimage
    idx = np.nonzero(solid)
    box = tuple(slice(a.min(), a.max() + 1) for a in idx)
    fine = np.pad(solid[box], 1).repeat(2, 0).repeat(2, 1).repeat(2, 2)
    dt = ndimage.distance_transform_edt(fine)
    reach = ndimage.distance_transform_edt(~(dt >= t - 1e-9))
    return 1 - np.count_nonzero(fine & (reach < t + 1.0)) / fine.sum()


def test_input_validation():
    g = gx.cantilever(nx=8, ny=2, nz=4)
    with pytest.raises(ValueError):
        g.optimize(gx.Settings(volume_fraction=0.01))
    with pytest.raises(ValueError):
        gx.Genesis(g.shape, g.h, fixed=g.fixed, loads=np.zeros(g.ndof))
