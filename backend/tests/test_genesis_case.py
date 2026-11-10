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


def test_settings_are_checked(ws):
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    for bad in ({"volume_fraction": 2}, {"symmetry": ["w"]}, {"overhang": "z"}, {"keep_faces": ["nope"]},
                {"cells": 10}, {"unknown": 1}, {"extrusion": "x", "overhang": "+z"}):
        with pytest.raises(StudioError) as e:
            C.run_genesis(cid, bad, wait_s=0, lang="en")
        assert e.value.key == "err.genesis_option"
