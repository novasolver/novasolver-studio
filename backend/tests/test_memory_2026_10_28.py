"""Large structural solves: constraints applied in place and 3x3 blocks for AMG (a 323k-element sphere octant ran out
of memory in the AMG set-up), plus the memory check before assembly."""
from __future__ import annotations

import numpy as np
import pytest

from novastudio import fem_tet10
from novastudio.store import StudioError


def block_mesh(n=6, L=(0.1, 0.02, 0.02)):
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.addBox(0, 0, 0, *L)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", L[1] / n)
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.setOrder(2)
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        nodes = xyz.reshape(-1, 3)
        idx = {t: i for i, t in enumerate(tags)}
        _, conn = gmsh.model.mesh.getElementsByType(11)
        tets = np.vectorize(idx.get)(conn.reshape(-1, 10))
        _, tconn = gmsh.model.mesh.getElementsByType(9)
        tri = np.vectorize(idx.get)(tconn.reshape(-1, 6))
    finally:
        gmsh.finalize()
    c = nodes[tri[:, :3]].mean(axis=1)
    return nodes, tets, tri[np.abs(c[:, 0]) < 1e-9], tri[np.abs(c[:, 0] - L[0]) < 1e-9], tri[np.abs(c[:, 1]) < 1e-9]


def test_block_amg_matches_direct(monkeypatch):
    nodes, tets, x0, x1, y0 = block_mesh()
    args = (nodes, tets, 200e9, 0.3, [x0], [(x1, np.array([0.0, 0.0, -1e6]))])
    kw = {"rollers": [(y0, 1)]}
    direct = fem_tet10.solve(*args, **kw)
    monkeypatch.setattr(fem_tet10, "DIRECT_LIMIT", 0)
    amg = fem_tet10.solve(*args, **kw)
    assert direct["nfree"] > 3000
    scale = np.abs(direct["u"]).max()
    assert np.abs(amg["u"] - direct["u"]).max() < 1e-5 * scale
    assert np.allclose(amg["reaction"], direct["reaction"], rtol=1e-5, atol=1e-6 * np.abs(direct["applied"]).max())
    assert amg["imbalance"] < 1e-5
    # constrained dofs stay exactly zero
    assert np.all(amg["u"][np.unique(x0)] == 0) and np.all(amg["u"][np.unique(y0), 1] == 0)


def test_memory_check_stops_with_a_message(monkeypatch):
    nodes, tets, x0, x1, _ = block_mesh(n=2)
    monkeypatch.setattr(fem_tet10, "committable_bytes", lambda: 10**8)
    with pytest.raises(StudioError) as e:
        fem_tet10.solve(nodes, tets, 200e9, 0.3, [x0], [(x1, np.array([0.0, 0.0, -1e6]))])
    assert e.value.key == "err.memory" and float(e.value.kw["need"]) > float(e.value.kw["have"])
    with pytest.raises(StudioError):
        fem_tet10.solve_scalar(nodes, tets, 1.0, [(x0, 0.0), (x1, 1.0)], [], [])


def test_memory_estimate_is_known():
    have = fem_tet10.committable_bytes()
    assert have is None or have > 0
    fem_tet10.check_memory(1000, "structural")     # a tiny model always fits


def test_memory_messages_in_three_languages():
    import json
    from pathlib import Path
    d = Path(fem_tet10.__file__).parent / "i18n"
    for lang in ("ja", "en", "zh"):
        t = json.loads((d / f"{lang}.json").read_text(encoding="utf-8"))
        assert {"{need}", "{have}", "{nodes}"} <= set(__import__("re").findall(r"\{\w+\}", t["err.memory"]))
        assert t["err.memory_short"]
