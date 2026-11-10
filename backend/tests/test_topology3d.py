"""3D SIMP topology optimisation on the tet10 solver."""
import numpy as np
import pytest

from novastudio import fem_tet10 as fe
from novastudio import topology3d as t3


def small():
    return t3.cantilever_box(length=2.0, width=0.5, height=1.0, nx=8, ny=2, nz=4)


def test_box_mesh_volume_and_orientation():
    nodes, tets, _ = t3.box_mesh(2.0, 0.5, 1.0, 4, 2, 2)
    _, vol = t3.unit_stiffness(nodes, tets, 0.3)
    assert vol.min() > 0
    assert vol.sum() == pytest.approx(1.0, rel=1e-12)
    assert len(tets) == 6 * 4 * 2 * 2


def test_solid_design_matches_built_in_solver():
    """All densities 1: the optimiser's stiffness and solve must reproduce fem_tet10.solve."""
    p = small()
    u = p.solve(p.stiffness(np.ones(len(p.tets))))
    load_nodes = np.nonzero(p.force.reshape(-1, 3).any(axis=1))[0]
    # same problem through the public solver: clamp via a face list is not needed; compare energy with K u = f
    K, *_ = fe.structural_system(p.nodes, p.tets, 1.0, 0.3)
    r = K @ u - p.force
    assert np.abs(r[p.free]).max() < 1e-8 * np.abs(p.force).max()
    assert p.force.sum() == pytest.approx(-1.0) and len(load_nodes) == 5     # 3 corner + 2 midside nodes


@pytest.mark.parametrize("beta", [1.0, 8.0])
def test_sensitivity_matches_finite_difference(beta):
    p = small()
    p.beta = beta
    rng = np.random.default_rng(1)
    x = rng.uniform(0.3, 0.9, len(p.tets))
    c, dc, dv, rho, _ = p.evaluate(x)
    for e in rng.choice(len(x), 5, replace=False):
        h = 1e-6
        xp, xm = x.copy(), x.copy()
        xp[e] += h; xm[e] -= h
        fd = (p.evaluate(xp)[0] - p.evaluate(xm)[0]) / (2 * h)
        assert dc[e] == pytest.approx(fd, rel=1e-4, abs=1e-10 * abs(c))
        vfd = (p.volume_fraction(p.physical(xp)) - p.volume_fraction(p.physical(xm))) / (2 * h)
        assert dv[e] == pytest.approx(vfd, rel=1e-6, abs=1e-14)


def test_optimisation_meets_volume_and_lowers_compliance():
    p = small()
    r = t3.optimize(p, volume_fraction=0.4, iterations=25)
    assert r["volume_fraction"] == pytest.approx(0.4, abs=2e-3)
    h = [s["compliance"] for s in r["history"]]
    assert h[-1] < 0.7 * h[0]
    assert r["threshold"]["connected"]


def test_non_design_regions_stay_fixed():
    base = small()
    solid = base.centroids[:, 0] > 1.75
    p = t3.cantilever_box(length=2.0, width=0.5, height=1.0, nx=8, ny=2, nz=4, solid=solid)
    r = t3.optimize(p, volume_fraction=0.4, iterations=10)
    assert np.all(r["density"][solid] == 1.0)


def test_surface_is_watertight(tmp_path):
    p = small()
    r = t3.optimize(p, volume_fraction=0.4, iterations=15)
    tris = t3.boundary_surface(p, r["density"] >= 0.5)
    edges = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(edges, axis=0, return_counts=True)
    # closed: every edge shared by an even number of triangles (4 where two solid regions touch along an edge)
    assert np.all(cnt % 2 == 0)
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    fwd = {tuple(e) for e in directed.tolist()}
    assert all((b, a) in fwd for a, b in directed.tolist())        # consistently oriented
    V, F = t3.smooth(p.nodes, tris)
    t3.write_stl(tmp_path / "part.stl", V, F)
    assert (tmp_path / "part.stl").stat().st_size == 84 + 50 * len(F)
