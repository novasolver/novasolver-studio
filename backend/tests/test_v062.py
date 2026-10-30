"""0.6.2: curved pressure integration, folded curved elements, midside matching on small holes."""
import numpy as np
import pytest

from novastudio import fem_tet10 as fem
from novastudio.structural import pressure_load


def disk_tri6(R=0.025, n=12):
    """A flat disk of n tri6 fan elements whose rim midside nodes lie on the circle (as Gmsh puts them)."""
    nodes = [[0, 0, 0]]
    for k in range(n):
        a = 2 * np.pi * k / n
        nodes.append([R * np.cos(a), R * np.sin(a), 0])
    for k in range(n):                                   # rim midside on the arc
        a = 2 * np.pi * (k + .5) / n
        nodes.append([R * np.cos(a), R * np.sin(a), 0])
    for k in range(n):                                   # spoke midsides
        a = 2 * np.pi * k / n
        nodes.append([R / 2 * np.cos(a), R / 2 * np.sin(a), 0])
    tri = np.array([[0, 1 + k, 1 + (k + 1) % n, 1 + 2 * n + k, 1 + n + k, 1 + 2 * n + (k + 1) % n] for k in range(n)])
    return np.array(nodes, float), tri


def test_pressure_on_round_face_carries_the_full_force(monkeypatch):
    nodes, tri = disk_tri6()
    # outward normal +z for this face: a pressure pushes into it, along -z
    monkeypatch.setattr(fem, "outward_normals", lambda n, t, tr: np.tile([0, 0, 1.], (len(tr), 1)))
    f = pressure_load(nodes, None, tri, 60e6)
    total = f.reshape(-1, 3).sum(0)
    assert total[2] == pytest.approx(-60e6 * np.pi * 0.025 ** 2, rel=1e-3)   # the flat corner fan was 4.5 % short
    assert abs(total[0]) < 1e-6 * abs(total[2]) and abs(total[1]) < 1e-6 * abs(total[2])


def test_straighten_inverted_unfolds_only_the_folded_element():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in fem.EDGES])
    nodes = np.vstack([corners, mids])
    tets = np.arange(10)[None]
    good, n = fem.straighten_inverted(nodes, tets)
    assert n == 0 and np.allclose(good, nodes)
    folded = nodes.copy()
    folded[8] += [0, 0, -0.45]                           # bow edge (1,3)'s midside node out far enough to fold it
    out, n = fem.straighten_inverted(folded, tets)
    assert n == 1 and np.allclose(out, nodes)


def test_canonical_tets_assigns_crowded_midside_nodes():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in fem.EDGES])
    # bow edge (0,1)'s midside node towards edge (0,2)'s midpoint: nearest-midpoint picks it twice
    mids[0] = mids[0] + 0.3 * (mids[1] - mids[0])
    nodes = np.vstack([corners, mids])
    tets = np.array([[0, 1, 2, 3, 5, 4, 6, 7, 8, 9]])    # midside columns shuffled
    out = fem.canonical_tets(nodes, tets)
    assert sorted(out[0, 4:]) == list(range(4, 10))
