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
    good, n, left = fem.straighten_inverted(nodes, tets)
    assert n == 0 and left == 0 and np.allclose(good, nodes)
    folded = nodes.copy()
    folded[8] += [0, 0, -0.45]                           # bow edge (1,3)'s midside node out far enough to fold it
    out, n, left = fem.straighten_inverted(folded, tets)
    assert n == 1 and left == 0 and np.allclose(out, nodes)
    # folded only between the four Gauss points (det J > 0 there, < 0 at a mass-matrix point): still found
    hidden = nodes.copy()
    hidden[4] += 0.186 * np.array([0, 1, 1]) / np.sqrt(2)
    X = hidden[tets]
    assert all(np.linalg.det(np.einsum("ik,ekj->eij", fem.DSHAPE[g], X))[0] > 0 for g in range(4))
    out, n, left = fem.straighten_inverted(hidden, tets)
    assert n == 1 and left == 0 and np.allclose(out, nodes)


def test_straighten_inverted_follows_a_long_chain_and_stops_when_nothing_changes(monkeypatch):
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in fem.EDGES])
    nodes = np.vstack([corners, mids])
    tets = np.arange(20).reshape(2, 10)
    nodes = np.vstack([nodes, nodes + 5])
    # the fold moves back and forth between two elements for longer than the old limit of 5 rounds
    seq = iter([np.array([i % 2]) for i in range(8)] + [np.empty(0, int)])
    monkeypatch.setattr(fem, "folded_elements", lambda n, ct: next(seq))
    _, n, left = fem.straighten_inverted(nodes, tets)
    assert n == 2 and left == 0
    # corners inverted: straightening cannot help, so the same set returns and the rounds stop at once
    calls = []
    monkeypatch.setattr(fem, "folded_elements", lambda n, ct: calls.append(1) or np.array([0]))
    _, n, left = fem.straighten_inverted(nodes, tets)
    assert n == 1 and left == 1 and len(calls) == 3


def test_a_body_without_support_is_refused_instead_of_solved():
    from novastudio.run_worker import require_held_bodies
    from novastudio.store import StudioError
    one = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]]) * 0.01
    nodes = np.vstack([one, one + 0.1])
    tets = np.array([[0, 1, 2, 3], [4, 5, 6, 7]])
    require_held_bodies(nodes, tets, [np.array([[0, 1, 2]]), np.array([[4, 5, 6]])], [])
    require_held_bodies(nodes, tets, [np.array([[0, 1, 2]])], [(np.array([[4, 5, 6]]), 0)])
    with pytest.raises(StudioError) as e:
        require_held_bodies(nodes, tets, [np.array([[0, 1, 2]])], [])
    assert e.value.key == "err.floating_body" and e.value.kw["count"] == 1 and e.value.kw["total"] == 2


def test_canonical_tets_assigns_crowded_midside_nodes():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in fem.EDGES])
    # bow edge (0,1)'s midside node towards edge (0,2)'s midpoint: nearest-midpoint picks it twice
    mids[0] = mids[0] + 0.3 * (mids[1] - mids[0])
    nodes = np.vstack([corners, mids])
    tets = np.array([[0, 1, 2, 3, 5, 4, 6, 7, 8, 9]])    # midside columns shuffled
    out = fem.canonical_tets(nodes, tets)
    assert sorted(out[0, 4:]) == list(range(4, 10))

def test_mesh_retries_in_a_fresh_session_and_goes_finer_only_for_imports(tmp_path, monkeypatch):
    import json
    from novastudio import mesh_worker as W
    seen = []

    def fails_until(n):
        def job(j):
            seen.append((j["_surface_mesher"], j["_size_factor"]))
            if len(seen) <= n:
                raise W.MeshAttemptFailed("overlapping facets")
        return job
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"kind": "import"}), encoding="utf-8")
    monkeypatch.setattr(W, "mesh_job", fails_until(3))
    W.main(str(path))
    assert seen == [(6, 1.0), (5, 1.0), (1, 1.0), (6, 0.5)]
    seen.clear()
    path.write_text(json.dumps({"kind": "box"}), encoding="utf-8")
    monkeypatch.setattr(W, "mesh_job", fails_until(99))
    with pytest.raises(RuntimeError, match="overlapping facets"):
        W.main(str(path))
    assert all(f == 1.0 for _, f in seen) and len(seen) == 3


def test_midside_columns_follow_gmsh_order_when_geometry_cannot_tell():
    import gmsh
    gmsh.initialize(["", "-nopopup"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.addSphere(0, 0, 0, 1)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.6)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.model.mesh.generate(3)
        tag, xyz, _ = gmsh.model.mesh.getNodes()
        conn = gmsh.model.mesh.getElementsByType(11)[1]
    finally:
        gmsh.finalize()
    index = np.zeros(int(tag.max()) + 1, int)
    index[tag.astype(int)] = np.arange(len(tag))
    nodes, tets = xyz.reshape(-1, 3), index[conn.astype(int)].reshape(-1, 10)
    assert np.array_equal(fem._midsides_by_position(tets), fem.canonical_tets(nodes, tets))
    # a midside node bowed past half its edge: the geometric match gives up and the column order answers
    far = nodes.copy()
    far[tets[0, 4]] = far[tets[0, 0]] + 3.0 * (far[tets[0, 1]] - far[tets[0, 0]]) + 3.0 * (far[tets[0, 2]] - far[tets[0, 0]])
    assert np.array_equal(fem.canonical_tets(far, tets)[0], fem._midsides_by_position(tets)[0])


def test_a_singular_model_says_what_to_do():
    import scipy.sparse as sp
    from novastudio.store import StudioError
    with pytest.raises(StudioError) as e:
        fem.spd_factor(sp.csc_matrix(np.array([[1.0, 0.0], [0.0, 0.0]])))
    assert e.value.key == "err.singular"
