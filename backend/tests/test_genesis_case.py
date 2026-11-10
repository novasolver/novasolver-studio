"""Genesis on Studio cases: face conditions become grid conditions, the job runs like any other, and the analysis
results of the case are not replaced by a Genesis run."""
import time

import numpy as np
import pytest

from novastudio import commands as C, genesis_case as GC, store
from novastudio.store import StudioError


def wait_genesis(r):
    if r["done"]:
        return r["genesis"]
    t0 = time.monotonic()
    while True:
        j = C.job_status(r["job_id"], "en")
        assert j["state"] not in ("failed", "stopped"), j
        if j["state"] == "done":
            return j["genesis"]
        assert time.monotonic() - t0 < 1800
        time.sleep(2)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    return tmp_path


def test_cantilever_case(ws):
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    g = wait_genesis(C.run_genesis(cid, {"volume_fraction": 0.35, "cells": 12000, "iterations": 60}, wait_s=120, lang="en"))
    cards = {c["key"]: c for c in g["cards"]}
    assert cards["volume_fraction"]["value"] == pytest.approx(35, abs=2.5)
    assert g["surface"]["closed"] and g["surface"]["oriented"]
    assert 0.35 < g["kept"] < 1          # better than thinning the whole part uniformly, below the full part
    assert not any(w["key"] == "load_not_carried" for w in g["warnings"])
    s = C.genesis_surface(cid, g["run_id"], "en")
    assert len(s["positions"]) == 3 * (max(s["indices"]) + 1) and s["unit"] == "MPa"
    stl = C.genesis_stl(cid, g["run_id"])
    assert stl["path"].endswith("part.stl")
    # analysis results of the case are untouched: no results.json in a Genesis run
    with pytest.raises(StudioError):
        C.get_results(cid, lang="en")


def test_load_transfer_keeps_the_total(ws):
    """The nodal forces moved to the grid add up to the applied force of the case."""
    from novastudio import geometry
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    case = store.load(cid)
    geometry.generate_mesh(case)
    m = dict(np.load(geometry.mesh_dir(case) / "mesh.npz"))
    spec = GC.validate({"cells": 8000}, set(case["boundaries"]))
    g, setup = GC.build(case, m, spec)
    total = g.loads[0].reshape(-1, 3).sum(axis=0)
    assert np.allclose(total, setup["info"]["applied_n"], rtol=1e-9, atol=1e-9 * np.abs(total).max())
    assert g.fixed.reshape(-1, 3).any(axis=0).all()
    assert g.solid.any()                                    # loaded and fixed faces are kept


def _built(cid, spec):
    from novastudio import geometry
    case = store.load(cid)
    geometry.generate_mesh(case)
    m = dict(np.load(geometry.mesh_dir(case) / "mesh.npz"))
    return GC.build(case, m, GC.validate(spec, set(case["boundaries"])))


def test_extrusion_on_a_padded_case_grid(ws):
    """The grid pads the part, so 'prismatic' is over the part's span: the cantilever is a prism along its axis."""
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    # across the width (y): the end faces are prisms too, so the final part is exactly prismatic
    g, setup = _built(cid, {"cells": 8000, "extrusion": "y"})
    r = g.optimize(setup["settings"].__class__(**{**setup["settings"].__dict__, "iterations": 20}))
    sol = g.solid_final
    assert np.array_equal(sol, np.broadcast_to(sol.any(axis=1, keepdims=True), sol.shape) & g.active)
    assert "constraint_not_met" not in r["warnings"] and r["volume_fraction_binary"] > 0.1
    # along the length (x): the kept end faces cannot be prisms along x; the result says so
    g, setup = _built(cid, {"cells": 8000, "extrusion": "x"})
    r = g.optimize(setup["settings"].__class__(**{**setup["settings"].__dict__, "iterations": 20}))
    assert "constraint_not_met" in r["warnings"]


def test_condition_layer_does_not_move_plate_or_break_prism(ws):
    """At 12k cells the cantilever's end faces reach one cell layer beyond the body. That layer must neither become
    the AM build plate (the whole body was unsupported and the design vanished) nor make the y prism fail."""
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    g, setup = _built(cid, {"cells": 12000, "overhang": "+z"})
    g.configure(setup["settings"])
    x = np.where(g.active, 0.3, 0.0)
    assert g.am.forward(x)[g.active].mean() > 0.9 * 0.3          # a uniform start stays printable
    g, setup = _built(cid, {"cells": 12000, "extrusion": "y", "symmetry": ["y"]})
    assert setup["info"]["extrusion_trimmed"] < 0.05


def test_precheck_refuses_before_the_job(ws):
    """Two sink temperatures (thermal block) are refused at once with the translated reason, not as a failed job."""
    cid = C.create_case("thermal-block", {}, "en")["case"]["case_id"]
    with pytest.raises(StudioError) as e:
        C.run_genesis(cid, {"cells": 4000}, wait_s=0, lang="en")
    assert e.value.key == "err.genesis_temperatures"


def test_trimming_never_drops_a_load(ws):
    """Engine: a load on a node no active cell holds is refused, not silently lost."""
    from novastudio import genesis as gx
    g0 = gx.cantilever(nx=8, ny=2, nz=4)
    active = np.ones(g0.shape, bool); active[-1] = False             # the loaded end column is gone
    with pytest.raises(ValueError, match="outside the part"):
        gx.Genesis(g0.shape, g0.h, fixed=g0.fixed, loads=g0.loads, active=active)


def test_supports_cover_large_triangles():
    """One mesh triangle 60 cells across: every grid node on it is supported (no patchy point supports)."""
    P, w = GC.sample_faces(np.array([[0, 0, 0], [60.0, 0, 0], [0, 60.0, 0]]), np.array([[0, 1, 2]]), 0.5)
    from scipy.spatial import cKDTree
    J = np.argwhere(np.ones((61, 61), bool)).astype(float)
    J = J[J.sum(axis=1) <= 60 - 1e-9]
    d, _ = cKDTree(P[:, :2]).query(J)
    assert d.max() <= 0.75 and w.sum() == pytest.approx(1800.0)


def test_inside_mesh_large_tet_next_to_small_ones():
    """A point in a large tet whose 40 nearest centroids belong to small tets beside it is still inside."""
    big = np.array([[0, 0, 0], [10.0, 0, 0], [0, 10.0, 0], [0, 0, 10.0]])
    nodes, tets = [big], [[0, 1, 2, 3]]
    rng = np.random.default_rng(0)
    for i in range(40):                                   # tiny tets just below the z = 0 face, near (1, 1, 0)
        c = np.array([1.0, 1.0, -0.05]) + rng.uniform(-0.03, 0.03, 3)
        nodes.append(c + 0.01 * np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, -1]]))
        tets.append(list(range(4 + 4 * i, 8 + 4 * i)))
    nodes = np.concatenate(nodes)
    inside = GC.inside_mesh(np.array([[1.0, 1.0, 0.02], [1.0, 1.0, -1.0], [6.0, 6.0, 6.0]]), nodes, np.array(tets))
    assert inside.tolist() == [True, False, False]


def test_genesis_run_does_not_hide_the_analysis(ws):
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    wait_genesis(C.run_genesis(cid, {"cells": 4000, "iterations": 12}, wait_s=120, lang="en"))
    pl = C.case_payload(cid, "en")
    assert pl["latest_run"] is None or pl["latest_run"].get("study") != "genesis"


def test_min_member_unit_and_cap(ws):
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    for bad in ({"min_member": 5}, {"min_member": {"value": 5, "unit": "kN"}}, {"heat_source": {"value": 1, "unit": "W"}}):
        with pytest.raises(StudioError) as e:
            C.run_genesis(cid, bad, wait_s=0, lang="en")
        assert e.value.key == "err.genesis_option"
    with pytest.raises(StudioError) as e:
        _built(cid, {"cells": 8000, "min_member": {"value": 1, "unit": "m"}})
    assert e.value.key == "err.genesis_min_member"
    with pytest.raises(StudioError) as e:
        _built(cid, {"cells": 8000, "heat_source": {"value": 1, "unit": "W/m3"}})
    assert e.value.key == "err.genesis_option"


def test_settings_are_checked(ws):
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    for bad in ({"volume_fraction": 2}, {"symmetry": ["w"]}, {"overhang": "z"}, {"keep_faces": ["nope"]},
                {"cells": 10}, {"unknown": 1}, {"extrusion": "x", "overhang": "+z"}):
        with pytest.raises(StudioError) as e:
            C.run_genesis(cid, bad, wait_s=0, lang="en")
        assert e.value.key == "err.genesis_option"
