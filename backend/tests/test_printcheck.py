"""3D-print strength check: for a PLA cantilever bent in the x-z plane, layers stacked along the beam (build
direction x) carry the full bending stress across the layer bond and are the worst orientation; y or z keep the
bending stress along the filament."""
import math
import time

import pytest

from novastudio import commands as C, store
from novastudio.store import StudioError


def solve(cid):
    """Run and wait: the job may queue behind another solve on this computer (the solver lock is per user)."""
    r = C.run_simulation(cid, "preview", wait_s=60, lang="en")
    if "results" in r:
        return r["results"]
    t0 = time.monotonic()
    while True:
        j = C.job_status(r["job_id"], "en")
        assert j["state"] not in ("failed", "cancelled"), j
        if j["state"] == "done":
            return C.get_results(cid, lang="en")
        assert time.monotonic() - t0 < 3600, "solve did not finish"
        time.sleep(5)


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
    # along x the layer stress is the bending stress itself (plus the shear on that plane), and it governs
    x = axes["x"]
    assert x["sf_layers"] == pytest.approx(1 / math.hypot(x["layer_tension_mpa"] / 25, x["layer_shear_mpa"] / 25))
    assert x["layer_tension_mpa"] > 3 * x["layer_shear_mpa"]
    assert x["sf"] < r["sf_filament"]
    assert r["best_sf"] == pytest.approx(min(axes[r["best_axis"]]["sf_layers"], r["sf_filament"]))
    # stresses near the clamp are left out: the governing point is at least two elements from x = 0
    assert x["at_mm"][0] > 0 and r["vm_at_mm"][0] > 0
    # datasheet values replace the defaults
    r2 = C.print_check(cid, strength_xy_mpa=60, strength_z_mpa=40, lang="en")
    assert r2["strength_z_mpa"] == 40
    assert {a["axis"]: a for a in r2["axes"]}["x"]["sf_layers"] == pytest.approx(x["sf_layers"] * 40 / 25)


def test_metals_nonlinear_and_bad_strengths_are_refused(tmp_path, monkeypatch):
    cid = solved_cantilever(tmp_path, monkeypatch, "steel")
    with pytest.raises(StudioError) as e:
        C.print_check(cid, lang="en")
    assert e.value.key == "err.print_check_scope"
    C.update_case(cid, store.load(cid)["revision"], {"materials.solid.preset": "petg"}, "en")
    solve(cid)
    for bad in (-5, 0, float("inf"), float("nan")):
        with pytest.raises(StudioError) as e:
            C.print_check(cid, strength_z_mpa=bad, lang="en")
        assert e.value.key == "err.print_check_strength"
    C.update_case(cid, store.load(cid)["revision"], {"physics.analysis": "nonlinear"}, "en")
    with pytest.raises(StudioError) as e:
        C.print_check(cid, lang="en")
    assert e.value.key == "err.print_check_scope"
