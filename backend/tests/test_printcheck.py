"""3D-print strength check: for a PLA cantilever bent in the x-z plane, layers stacked along the beam (build
direction x) carry the full bending stress across the layer bond and are the worst orientation; y or z keep the
bending stress along the filament."""
import time

import pytest

from novastudio import commands as C, store
from novastudio.store import StudioError


def solve(cid):
    """Run and wait: the job may queue behind another solve on this computer (the solver lock is per user)."""
    r = C.run_simulation(cid, "preview", wait_s=60, lang="en")
    t0 = time.monotonic()
    while "results" not in r:
        assert time.monotonic() - t0 < 3600, "solve did not finish"
        time.sleep(5)
        r = C.job_status(r["job_id"], "en")
        assert r["state"] not in ("failed", "cancelled"), r
    return r["results"]


def solved_cantilever(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    C.update_case(cid, store.load(cid)["revision"], {"materials.solid.preset": preset}, "en")
    assert solve(cid)["gates"]["ran"]
    return cid


def test_orientation_and_safety_factors(tmp_path, monkeypatch):
    cid = solved_cantilever(tmp_path, monkeypatch, "pla")
    r = C.print_check(cid, lang="en")
    axes = {a["axis"]: a for a in r["axes"]}
    assert r["material"] == "pla" and r["strength_xy_mpa"] == 50 and r["strength_z_mpa"] == 25
    assert min(axes, key=lambda k: axes[k]["sf"]) == "x"           # layers across the bending stress
    assert r["best_axis"] in ("y", "z")
    # along x the layer tension is the bending stress itself, and it governs over the filament check
    assert axes["x"]["sf_layers"] == pytest.approx(25 / axes["x"]["layer_tension_mpa"])
    assert axes["x"]["sf"] < r["sf_filament"]
    assert r["best_sf"] == pytest.approx(min(axes[r["best_axis"]]["sf_layers"], r["sf_filament"]))
    # datasheet values replace the defaults
    r2 = C.print_check(cid, strength_xy_mpa=60, strength_z_mpa=40, lang="en")
    assert r2["strength_z_mpa"] == 40
    assert {a["axis"]: a for a in r2["axes"]}["x"]["sf_layers"] == pytest.approx(axes["x"]["sf_layers"] * 40 / 25)


def test_metals_and_bad_strengths_are_refused(tmp_path, monkeypatch):
    cid = solved_cantilever(tmp_path, monkeypatch, "steel")
    with pytest.raises(StudioError) as e:
        C.print_check(cid, lang="en")
    assert e.value.key == "err.print_check_scope"
    C.update_case(cid, store.load(cid)["revision"], {"materials.solid.preset": "petg"}, "en")
    solve(cid)
    with pytest.raises(StudioError) as e:
        C.print_check(cid, strength_z_mpa=-5, lang="en")
    assert e.value.key == "err.print_check_strength"
