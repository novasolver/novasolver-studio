"""Second opinion 2026-11-11 (Codex, since 1aef4d7): each test fails on the code before the fix."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from novastudio import commands as C, genesis as gx, genesis_case as GC, genesis_step as gs, store
from novastudio.store import StudioError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    return tmp_path


def test_contact_pairs_and_thermal_loads_are_refused(ws):
    """Contact pairs (hertz-cylinder) and a structural thermal load passed the check and were optimised without."""
    case = store.load(C.create_case("hertz-cylinder", {}, "en")["case"]["case_id"])
    with pytest.raises(StudioError) as e:
        GC.precheck(case, "ja")
    assert e.value.key == "err.genesis_scope"
    case = store.load(C.create_case("cantilever", {}, "en")["case"]["case_id"])
    GC.precheck(case)                                                   # the plain cantilever runs
    case["physics"]["thermal_load"] = {"mode": "uniform", "temperature": {"value": 300, "unit": "degC"}}
    with pytest.raises(StudioError) as e:
        GC.precheck(case, "en")
    assert e.value.key == "err.genesis_scope"


def _bar(nx=20, ny=4, h=0.01):
    """Thermal bar: sink on x = 0, heat flux into x = nx (face nodes only), no kept cells."""
    shape = (nx, ny, ny)
    nn = (nx + 1) * (ny + 1) ** 2
    J, K = np.meshgrid(np.arange(ny + 1), np.arange(ny + 1), indexing="ij")
    fixed = np.zeros(nn, bool)
    fixed[gx.node_index(shape, 0, J, K).ravel()] = True
    f = np.zeros(nn)
    hot = gx.node_index(shape, nx, J, K).ravel()
    f[hot] = 1.0 / len(hot)
    g = gx.Genesis(shape, h, physics="thermal", E=1.0, fixed=fixed, loads=f)
    g.carry_nodes = hot
    g.configure(gx.Settings(volume_fraction=0.3))
    return g


def test_heat_input_cut_off_is_reported():
    """A heated face cut off from the sink kept loads_carried=True (775 K in the void, 2.7 K reported)."""
    g = _bar()
    solid = np.ones(g.shape, bool)
    assert g.clean(solid)[1]["loads_carried"]
    solid[-3:] = False                                                  # the heated end is gone
    assert not g.clean(solid)[1]["loads_carried"]
    solid = np.ones(g.shape, bool); solid[8:10] = False                 # or separated from the sink
    out, p = g.clean(solid)
    assert not p["loads_carried"]


def test_empty_part_is_a_translated_error():
    """An empty final part crashed with 'zero-size array to reduction operation maximum'."""
    g = _bar()
    with pytest.raises(StudioError) as e:
        g._finish(np.zeros(g.shape), 1.0, [], "converged", 0.0)
    assert e.value.key == "err.genesis_empty"


def test_stl_keeps_the_analysed_volume_when_the_threshold_is_lowered():
    """A grey run cut below 0.5: the STL held 78 % of the analysed voxels (59 % on a one-cell slab)."""
    g = gx.cantilever(nx=48, ny=8, nz=12)
    r = g.optimize(gx.Settings(volume_fraction=0.3, iterations=30))
    assert r["threshold"] < 0.5
    chk = gx.surface_checks(*g.surface())
    assert chk["closed"] and chk["oriented"]
    assert chk["volume_m3"] == pytest.approx(g.solid_final.sum() * g.h ** 3, rel=0.15)


@pytest.mark.parametrize("ax", [0, 1, 2])
def test_step_with_a_hole_is_checked_by_reading_it_back(tmp_path, monkeypatch, ax):
    """The written STEP of a ring holds the ring's volume (read back in the same call; FreeCAD 1.1.4 also 240 mm3)."""
    shp = [10, 10, 10]; shp[ax] = 4
    S = np.ones(shp, bool); sl = [slice(2, 8)] * 3; sl[ax] = slice(None); S[tuple(sl)] = False
    g = NS(s=NS(extrusion=ax), active=np.ones_like(S), solid_final=S, origin=np.zeros(3), h=1e-3)
    monkeypatch.setattr(gs.gx, "surface_field", lambda g: g.solid_final.astype(float))
    info = gs.write_step(g, tmp_path / "ring.step")
    assert info["polygons"] == 1 and info["volume_m3"] == pytest.approx(240e-9, rel=1e-6)


def test_step_keeps_a_thin_bridge(tmp_path):
    """Second opinion 2026-11-12: two blocks joined by a one-cell bridge of density 0.4, cut at 0.35. The STL kept the
    bridge, the STEP section (old field, level 0.53) came out as two separate polygons."""
    shape = (30, 4, 14)
    rho = np.full(shape, 0.3)
    rho[1:9, :, 3:11] = rho[21:29, :, 3:11] = 1.0
    rho[9:21, :, 7] = 0.4
    g = NS(s=NS(extrusion=1), active=np.ones(shape, bool), solid=np.zeros(shape, bool), rho=rho, threshold=0.35,
           solid_final=rho >= 0.35, origin=np.zeros(3), h=1e-3)
    info = gs.write_step(g, tmp_path / "bridge.step")
    assert info["polygons"] == 1
    # the level stops at 0.6 (149 cells against 140 analysed): on this 140-cell section one boundary layer is 6 %;
    # keeping the member comes first, the share falls with the section's size
    assert info["volume_m3"] == pytest.approx(info["voxel_volume_m3"], rel=0.08)


def test_step_refuses_a_section_that_lost_a_member(tmp_path, monkeypatch):
    shape = (30, 4, 14)
    S = np.zeros(shape, bool)
    S[1:9, :, 3:11] = S[21:29, :, 3:11] = True
    S[9:21, :, 7] = True
    g = NS(s=NS(extrusion=1), active=np.ones(shape, bool), solid_final=S, origin=np.zeros(3), h=1e-3)
    cut = S.astype(float); cut[9:21, :, 7] = 0.0                   # a field that drops the bridge
    monkeypatch.setattr(gs.gx, "surface_field", lambda g: cut)
    with pytest.raises(ValueError, match="pieces"):
        gs.write_step(g, tmp_path / "lost.step")


def test_heat_check_survives_symmetry_and_refinement():
    """Second opinion 2026-11-12: the half model and the refinement problem dropped carry_nodes, so a heated end cut
    off from the sink passed as carried."""
    g = _bar()
    s = gx.Settings(volume_fraction=0.3, symmetry=("y",))
    gh = gx.mirror_half(g, 1, s)
    assert gh is not None and len(gh.carry_nodes) > 0
    solid = np.zeros(gh.shape, bool)
    solid[:, gh._mirror[1]:, :] = True                                 # the half's real cells (after the padding)
    assert gh.clean(solid)[1]["loads_carried"]
    solid[-3:] = False
    assert not gh.clean(solid)[1]["loads_carried"]
    # refinement on a grid twice as fine
    g.solid_final = np.ones(g.shape, bool)
    g.rho = np.ones(g.shape)
    f = _bar(40, 8, 0.005)
    gb, *_ = gx.refine_problem(g, f, gx.Settings(volume_fraction=0.3))
    assert np.array_equal(gb.carry_nodes, f.carry_nodes)
    solid = ~gb.void & gb.active
    solid[-6:] = False
    assert not gb.clean(solid)[1]["loads_carried"]


def test_cad_import_does_not_take_an_older_part_by_name(monkeypatch):
    """An edited Body.step sent again: the old Body.step case (other content, with a result) was picked by name."""
    sys.path.insert(0, str(ROOT / "integrations" / "freecad" / "NovaSolverStudio"))
    import nss_link as L
    cases = [{"case_id": "c_new", "source_sha256": "new", "source_file": "Body.step"},
             {"case_id": "c_old", "source_sha256": "old", "source_file": "Body.step"}]
    monkeypatch.setattr(L, "list_cases", lambda port: cases)
    assert [c["case_id"] for c in L.find_cases(1, digest="new", filename="Body.step")] == ["c_new"]
    assert [c["case_id"] for c in L.find_cases(1, filename="Body.step", case_id="c_new")] == ["c_new"]
    # nothing known but the name (an older FreeCAD without Meta, or Studio took the file through --import)
    assert [c["case_id"] for c in L.find_cases(1, digest="other", filename="Body.step")] == ["c_new", "c_old"]


def test_edit_survives_a_lost_revisions_folder(ws):
    """Found while checking the stale panel: temp cleanup removed the empty revisions/ folder and every edit was a 500."""
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    (store.case_dir(cid) / "revisions").rmdir()
    rev = store.load(cid)["revision"]
    out = C.update_case(cid, rev, {"boundaries.x1.force": {"value": 1200, "unit": "N"}}, "en")
    assert out["case"]["revision"] == rev + 1 and (store.case_dir(cid) / "revisions" / f"{rev}.json").is_file()


def test_genesis_result_carries_its_revision(ws):
    """The panel compares the run's revision with the open case: the fetched stale flag is older than an edit."""
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    jd = store.case_dir(cid) / "run" / "r_20261111_000000_abcd"
    jd.mkdir(parents=True)
    import json
    rev = store.load(cid)["revision"]
    jd.joinpath("genesis.json").write_text(json.dumps({
        "physics": "elastic", "revision": rev, "spec": {}, "setup": {"grid": {}, "cells_active": 1},
        "surface": {}, "history": [], "result": {"volume_fraction_binary": 0.3, "min_member_m": 1e-3,
                                                 "objective_binary": 1.0, "max_displacement_m": 1e-3,
                                                 "termination": "converged", "iterations": 1, "elapsed_s": 1.0,
                                                 "warnings": []}}), encoding="utf-8")
    g = C.genesis_result(cid, jd.name, "en")
    assert g["revision"] == rev and g["stale"] is False
    assert g["load_carried"] and [c["key"] for c in g["cards"]] == ["compliance", "volume_fraction", "min_member", "max_disp"]
    # the load not reaching the supports: no stiffness figures (the FreeCAD check showed 258,500 J and 296,300 mm)
    data = json.loads(jd.joinpath("genesis.json").read_text(encoding="utf-8"))
    data["result"]["warnings"] = ["load_not_carried"]
    jd.joinpath("genesis.json").write_text(json.dumps(data), encoding="utf-8")
    g = C.genesis_result(cid, jd.name, "en")
    assert not g["load_carried"] and [c["key"] for c in g["cards"]] == ["volume_fraction", "min_member"]
    assert [w["key"] for w in g["warnings"]] == ["load_not_carried"]
