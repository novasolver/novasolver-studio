"""0.7: linear (eigenvalue) buckling."""
import numpy as np
import pytest

from novastudio import box_mesh
from novastudio import fem_tet10 as fem

E, NU = 205e9, 0.3
L, H = 0.4, 0.01
I = H ** 4 / 12


@pytest.fixture(scope="module")
def column():
    return box_mesh.generate((L, H, H), (40, 2, 2))


def tip(mesh, force):
    """Uniform traction on x1 adding up to `force` along x."""
    tri = mesh["face_x1"]
    return [(tri, np.array([force / H ** 2, 0, 0]))]


def test_euler_fixed_free_and_degenerate_pair(column):
    r = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], tip(column, -1000.0), modes=4)
    ref = np.pi ** 2 * E * I / (4 * L ** 2)
    lam = np.array(r["load_factors"])
    assert r["converged"]
    assert lam[0] * r["applied_load"] == pytest.approx(ref, rel=0.02)
    assert lam[1] == pytest.approx(lam[0], rel=0.02)       # square section: the other bending axis
    assert r["mode_shapes"].shape[0] == len(lam)
    assert np.linalg.norm(r["mode_shapes"][0], axis=1).max() == pytest.approx(1.0)


def test_load_factor_scales_inversely_with_the_load(column):
    a = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], tip(column, -1000.0), modes=1)
    b = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], tip(column, -2000.0), modes=1)
    assert b["load_factors"][0] == pytest.approx(a["load_factors"][0] / 2, rel=1e-6)
    assert b["load_factors"][0] * b["applied_load"] == pytest.approx(a["load_factors"][0] * a["applied_load"], rel=1e-6)


def test_tension_gives_no_positive_load_factor(column):
    r = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], tip(column, 1000.0), modes=2)
    assert r["load_factors"] == []                         # run_buckling turns this into err.buckling_none
    assert not r["converged"]


def test_clamped_column_driven_by_displacement(column):
    x1 = column["face_x1"]
    pres = [(x1, 0, -1e-4), (x1, 1, 0.0), (x1, 2, 0.0)]
    r = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], [], prescribed=pres, modes=2)
    assert r["applied_load"] == pytest.approx(E * H ** 2 * 1e-4 / L, rel=0.01)   # EA delta / L
    # 4 pi^2 EI / L^2 less about 0.6 % from shear at this slenderness
    assert r["load_factors"][0] * r["applied_load"] == pytest.approx(4 * np.pi ** 2 * E * I / L ** 2, rel=0.02)


def test_geometric_stiffness_is_symmetric_and_matches_uniform_stress():
    mesh = box_mesh.generate((0.02, 0.01, 0.01), (2, 1, 1))
    nodes, tets = mesh["nodes"], fem.canonical_tets(mesh["nodes"], mesh["tets"])
    s = np.zeros((len(tets), 4, 6))
    s[:, :, 0] = -1e6                                      # uniform sigma_xx
    Kg = fem.geometric_stiffness(nodes, tets, s)
    assert abs(Kg - Kg.T).max() <= 1e-9 * abs(Kg).max()
    # for a uniform stress, u^T K_sigma u = sigma_xx int |du/dx|^2 dV: u = x^2 e_y gives (2x)^2 integrated
    x = nodes[:, 0]
    u = np.zeros_like(nodes)
    u[:, 1] = x ** 2
    Lx, A = 0.02, 1e-4
    assert u.ravel() @ (Kg @ u.ravel()) == pytest.approx(-1e6 * A * 4 * Lx ** 3 / 3, rel=1e-9)


def test_zero_load_has_no_buckling(column):
    """review M1: no load means no stress and no load factor (was lambda ~ 1e30 from round-off)."""
    r = fem.solve_buckling(column["nodes"], column["tets"], E, NU, [column["face_x0"]], tip(column, 0.0), modes=2)
    assert r["load_factors"] == []
