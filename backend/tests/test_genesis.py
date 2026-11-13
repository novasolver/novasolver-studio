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


def test_binary_threshold_keeps_the_volume_of_a_grey_design():
    g = gx.cantilever(nx=16, ny=2, nz=8)
    g.configure(gx.Settings(volume_fraction=0.4))
    rng = np.random.default_rng(0)
    crisp = np.where(rng.random(g.shape) < 0.4, 1.0, 0.0)
    assert g.binary_threshold(crisp) == 0.5                         # a 0/1 design: the usual 0.5
    grey = np.clip(rng.normal(0.4, 0.05, g.shape), 0, 1)            # all below 0.5: 0.5 would keep nothing
    t = g.binary_threshold(grey)
    assert 0.2 <= t < 0.5
    kept = float((grey[g.active] >= t).mean())
    assert kept >= g.volume_fraction(grey) - 0.02


def test_bridge_diagonals_joins_hinges():
    from scipy import ndimage
    # a staircase diagonal one cell thick in x-z, extruded along y: edge contacts only
    s = np.zeros((8, 3, 8), bool)
    for i in range(8):
        s[i, :, i] = True
    rho = np.broadcast_to(np.random.default_rng(0).uniform(0, 0.4, (8, 1, 8)), s.shape)   # a prism design
    out, added = gx.bridge_diagonals(s, rho, np.ones(s.shape, bool))
    assert ndimage.label(s)[1] == 8 and ndimage.label(out)[1] == 1
    assert added == 7 * 3 and (out | ~s).all()                     # one bridge per step and row, nothing removed
    assert np.array_equal(out, np.broadcast_to(out.any(axis=1, keepdims=True), out.shape))   # still a prism
    # corner contact: two cells touching at one vertex
    c = np.zeros((4, 4, 4), bool); c[1, 1, 1] = c[2, 2, 2] = True
    out, added = gx.bridge_diagonals(c, np.zeros(c.shape), np.ones(c.shape, bool))
    assert ndimage.label(out)[1] == 1 and added == 2
    # bridges only where allowed; a face-connected part is left alone
    blk = np.zeros((4, 4, 4), bool); blk[1:3, 1:3, 1:3] = True
    out, added = gx.bridge_diagonals(blk, np.zeros(blk.shape), np.ones(blk.shape, bool))
    assert added == 0 and np.array_equal(out, blk)


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


def test_two_step_cycle_is_damped():
    # a one-cell slab (a 2D cantilever) fell into a 3.7 / 6.5 style OC cycle: 150 steps without converging, the run
    # ended on the worse half and the 0/1 part kept 5.5 % of the full part's stiffness. With the cycle damped: ~47 %
    g = gx.cantilever(nx=48, ny=1, nz=12)
    r = g.optimize(gx.Settings(volume_fraction=0.3, iterations=150))
    assert r["termination"] == "converged"
    assert r["stiffness_kept"] > 0.4
    assert r["objective_binary"] < 1.2 * r["objective"]


def test_beta_step_that_wrecks_the_design_is_undone():
    # stand-in for thin members vanishing at a sharper projection: from beta 8 on the objective is 3x worse
    g = gx.cantilever(nx=16, ny=4, nz=8)
    real = g.evaluate

    def worse(z, *a, **k):
        c, dc, dv, rho, extra = real(z, *a, **k)
        return (3 * c, 3 * dc, dv, rho, extra) if g.beta >= 8 else (c, dc, dv, rho, extra)

    g.evaluate = worse
    r = g.optimize(gx.Settings(volume_fraction=0.4, iterations=120))
    assert r["beta_final"] == 4.0 and "projection_limited" in r["warnings"]
    assert r["history"][-1]["beta"] == 4.0 and max(h["beta"] for h in r["history"]) == 8.0
    # an ordinary run goes to full projection without the warning
    g2 = gx.cantilever(nx=16, ny=4, nz=8)
    r2 = g2.optimize(gx.Settings(volume_fraction=0.4, iterations=120))
    assert r2["beta_final"] == 16.0 and "projection_limited" not in r2["warnings"]


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


def test_smooth_surface_keeps_the_part():
    g = gx.cantilever(nx=24, ny=4, nz=12)
    g.optimize(gx.Settings(volume_fraction=0.4, iterations=40))
    P, F = g.surface()
    pinned = np.zeros(len(P), bool)
    pinned[P[:, 0] < g.origin[0] + 0.6 * g.h] = True            # the fixed end
    S = gx.smooth_surface(P, F, pinned)
    a, b = gx.surface_checks(P, F), gx.surface_checks(S, F)
    assert b["closed"] and b["oriented"] and b["manifold_edges"] == a["manifold_edges"]
    assert b["volume_m3"] == pytest.approx(a["volume_m3"], rel=0.03)
    assert np.array_equal(S[pinned], P[pinned])
    # the steps get smaller: the spread of the face normals of neighbouring triangles drops
    def roughness(X):
        n = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
        n /= np.linalg.norm(n, axis=1)[:, None]
        e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
        tri = np.tile(np.arange(len(F)), 3)
        o = np.lexsort((e[:, 1], e[:, 0]))
        e, tri = e[o], tri[o]
        same = np.all(e[1:] == e[:-1], axis=1)
        return float(np.mean(1 - np.einsum("ij,ij->i", n[tri[1:][same]], n[tri[:-1][same]])))
    assert roughness(S) < 0.7 * roughness(P)


def test_extruded_part_exports_a_flat_faced_step(tmp_path):
    gmsh = pytest.importorskip("gmsh")
    from novastudio import genesis_step as gs
    g = gx.cantilever(24, 4, 12)
    g.optimize(gx.Settings(extrusion=1, iterations=40))
    info = gs.write_step(g, tmp_path / "part.step")
    # same material as the voxel part (the contour level is chosen for that; straight edges add a little)
    assert abs(info["volume_m3"] / info["voxel_volume_m3"] - 1) < 0.08
    gmsh.initialize(["", "-nopopup"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setString("Geometry.OCCTargetUnit", "M")
        gmsh.open(str(tmp_path / "part.step"))
        vols = gmsh.model.getEntities(3)
        assert len(vols) == 1
        assert abs(gmsh.model.occ.getMass(3, vols[0][1]) / info["volume_m3"] - 1) < 1e-6   # millimetres in the file
        x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
        top = g.origin + np.array(g.shape) * g.h
        assert np.allclose([y0, y1], [g.origin[1], top[1]], atol=1e-6)            # the full prism along y
        assert x0 > g.origin[0] - 0.5 * g.h and x1 < top[0] + 0.5 * g.h
        assert all(gmsh.model.getType(2, t) == "Plane" for _, t in gmsh.model.getEntities(2))
    finally:
        gmsh.finalize()

def test_mirror_filter_is_its_own_adjoint():
    g = gx.cantilever(12, 6, 6)
    g.configure(gx.Settings(filter_radius=2.5))
    g.mirror_axes = (1, 2)
    rng = np.random.default_rng(1)
    x, y = rng.standard_normal(g.shape), rng.standard_normal(g.shape)
    assert np.isclose(np.sum(g._conv(x) * y), np.sum(x * g._conv_T(y)), rtol=1e-12)


def test_half_model_gives_the_whole_design():
    s = gx.Settings(symmetry=(1,), iterations=30)
    g1, g2 = gx.cantilever(24, 4, 12), gx.cantilever(24, 4, 12)
    r1, r2 = g1.optimize(s), gx.optimize_symmetric(g2, s)
    assert r2["half_model"] == [1]
    assert np.array_equal(g1.solid_final, g2.solid_final)
    for k in ("objective", "objective_binary", "objective_full", "max_displacement_m", "volume_fraction_binary"):
        assert np.isclose(r1[k], r2[k], rtol=1e-5), k
    assert r2["grid"] == list(g1.shape) and r2["settings"]["symmetry"] == [1]


def test_half_model_needs_symmetric_loads():
    g = gx.cantilever(24, 4, 12)
    L = g.loads.copy().reshape(len(g.loads), -1, 3)
    L[:, np.nonzero(L[0, :, 2])[0][0], 1] = 1e-3          # a sideways push on one node
    g.loads = L.reshape(len(g.loads), -1)
    assert gx.mirror_half(g, 1, gx.Settings()) is None


def test_asymmetric_loads_fall_back_to_full_model_without_changing_forces():
    """The same resultant does not imply mirrored nodal loads; fallback must solve the actual full problem."""
    settings = gx.Settings(symmetry=(1,), iterations=8)
    full, fallback = gx.cantilever(12, 4, 6), gx.cantilever(12, 4, 6)
    original_total = full.loads.reshape(-1, 3).sum(axis=0)
    for problem in (full, fallback):
        forces = problem.loads.reshape(-1, 3)
        loaded = np.flatnonzero(forces[:, 2])
        forces[loaded[0], 2] += 0.01
        forces[loaded[-1], 2] -= 0.01
        assert np.allclose(forces.sum(axis=0), original_total, rtol=1e-12, atol=1e-12)
        assert not gx.mirror_symmetric(problem, 1)
    applied = fallback.loads.copy()
    reference = full.optimize(settings)
    result = gx.optimize_symmetric(fallback, settings)
    assert result.get("half_model") is None
    assert np.array_equal(fallback.loads, applied)
    assert np.array_equal(full.solid_final, fallback.solid_final)
    for key in ("objective", "objective_binary", "objective_full", "max_displacement_m", "volume_fraction_binary"):
        assert np.isclose(reference[key], result[key], rtol=1e-5), key
