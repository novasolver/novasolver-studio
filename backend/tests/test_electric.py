"""Electromagnetics acceptance tests (SPEC_em_0.3 §8) and boundary/result regressions."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from novastudio import commands as C, jobs, results, store, templates, units
from novastudio.run_worker import EPS0
from novastudio.store import StudioError


@pytest.fixture(scope="module", autouse=True)
def private_workspace(tmp_path_factory):
    old = os.environ.get("NOVASTUDIO_WORKSPACE")
    os.environ["NOVASTUDIO_WORKSPACE"] = str(tmp_path_factory.mktemp("electric"))
    yield
    if old is None:
        os.environ.pop("NOVASTUDIO_WORKSPACE", None)
    else:
        os.environ["NOVASTUDIO_WORKSPACE"] = old


def solve(tid, changes=None):
    p = C.create_case(tid, changes)
    cid = p["case"]["case_id"]
    out = C.run_simulation(cid, wait_s=1)
    job = out.get("job_id") or out["job"]["job_id"]
    state = jobs.wait(job, 1800)
    assert state["state"] == "done", C.job_status(job)
    jd, r = results.load(cid)
    assert r["converged"], r
    return cid, jd, r


def number(name, computed, reference):
    err = (computed / reference - 1) * 100 if reference else abs(computed)
    print(f"MEASURE {name}: computed={computed:.12g}, reference={reference:.12g}, error_pct={err:.9g}", flush=True)


@pytest.fixture(scope="module")
def capacitor():
    return solve("capacitor")


def test_01_capacitor_charge_energy_and_probe(capacitor):
    cid, jd, r = capacitor
    m = r["metrics"]
    ref = EPS0 * 2.1 * 0.05 ** 2 / 0.002
    number("capacitor_C_F", m["capacitance_f"], ref)
    assert m["capacitance_f"] == pytest.approx(ref, rel=0.005)
    energy_c = 2 * m["energy_j"] / 100 ** 2
    number("capacitor_C_from_energy_F", energy_c, m["capacitance_f"])
    assert energy_c == pytest.approx(m["capacitance_f"], rel=0.001)
    p = C.probe_results(cid, points=[[25, 25, 1]], faces=["z0", "z1"])
    point = p["points"][0]
    assert point["inside"]
    number("capacitor_centre_E_V_m", point["values"]["emag"], 50000)
    number("capacitor_centre_V", point["values"]["v"], 50)
    assert point["values"]["emag"] == pytest.approx(50000, rel=0.005)
    assert point["values"]["v"] == pytest.approx(50, abs=0.05)
    assert point["values"]["ez"] == pytest.approx(-50000, rel=0.005)
    assert p["faces"][0]["charge_c"] < 0 < p["faces"][1]["charge_c"]
    assert C.verify_case(cid)["gates"]["verified"]
    for q in ("v", "emag"):
        assert np.isfinite(C.field(cid, q)["scalars"]).all()
    png, meta = C.render_view(cid)
    assert png.startswith(b"\x89PNG") and meta["quantity"] == "v"
    assert set(np.load(jd / "results.npz").files) == {"V", "E"}


def test_02_permittivity_scales_capacitance(capacitor):
    _, _, r = solve("capacitor", {"materials.solid.eps_r": 4})
    ref = capacitor[2]["metrics"]["capacitance_f"] * 4 / 2.1
    number("eps4_C_F", r["metrics"]["capacitance_f"], ref)
    assert r["metrics"]["capacitance_f"] == pytest.approx(ref, rel=0.001)


def test_03_coax_capacitance_and_peak_field():
    _, _, r = solve("coax")
    m = r["metrics"]
    ref = 2 * math.pi * EPS0 * 2.1 * 0.01 / math.log(3.5)
    eref = 1000 / (0.001 * math.log(3.5))
    number("coax_C_F", m["capacitance_f"], ref)
    number("coax_Emax_V_m", m["e_max_v_m"], eref)
    assert m["capacitance_f"] == pytest.approx(ref, rel=0.01)
    assert m["e_max_v_m"] == pytest.approx(eref, rel=0.03)


def two_box_step(path):
    import gmsh
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        for z in (0, 1):
            gmsh.model.occ.addBox(0, 0, z, 10, 10, 1)  # STEP carries mm
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def test_04_series_dielectrics(tmp_path):
    step = tmp_path / "dielectrics.step"
    two_box_step(step)
    p = C.import_geometry("electrostatic", step.name, path=str(step))
    c = p["case"]
    bodies = sorted(c["geometry"]["bodies"], key=lambda b: b["centroid"][2])
    faces = [f for f in c["geometry"]["faces"] if not f["interface"]]
    bottom, top = min(faces, key=lambda f: f["centroid"][2]), max(faces, key=lambda f: f["centroid"][2])
    ch = {f"body_materials.{b['key']}": mat for b, mat in zip(bodies, ("ptfe", "alumina"))}
    ch.update({f"boundaries.{bottom['key']}.role": "voltage", f"boundaries.{bottom['key']}.voltage": "0 V",
               f"boundaries.{top['key']}.role": "voltage", f"boundaries.{top['key']}.voltage": "100 V"})
    cid = c["case_id"]
    C.update_case(cid, c["revision"], ch)
    out = C.run_simulation(cid, wait_s=1)
    job = out.get("job_id") or out["job"]["job_id"]
    assert jobs.wait(job, 900)["state"] == "done", C.job_status(job)
    m = results.load(cid)[1]["metrics"]
    cref = EPS0 * 1e-4 / (0.001 / 2.1 + 0.001 / 9.8)
    vref = 100 * (1 / 2.1) / (1 / 2.1 + 1 / 9.8)
    v = C.probe_results(cid, points=[[5, 5, 1]])["points"][0]
    assert v["inside"]
    number("series_C_F", m["capacitance_f"], cref)
    number("series_interface_V", v["values"]["v"], vref)
    assert m["capacitance_f"] == pytest.approx(cref, rel=0.01)
    assert v["values"]["v"] == pytest.approx(vref, rel=0.01)
    # second opinion (EM) #2: the field keeps its jump at the interface (82 kV/m in PTFE, 18 kV/m in alumina); averaged
    # across it, the nodes 0.25 mm inside PTFE read 68 kV/m
    e = [pt["values"]["emag"] for pt in C.probe_results(cid, points=[[5, 5, 0.75], [5, 5, 1.25]])["points"]]
    assert e[0] == pytest.approx(vref / 0.001, rel=0.01)
    assert e[1] == pytest.approx((100 - vref) / 0.001, rel=0.01)
    assert m["imbalance"] < 1e-3


def test_05_busbar_coupled_power_and_temperature():
    cid, jd, r = solve("busbar")
    m = r["metrics"]
    rref = 0.2 / (5.96e7 * 0.02 * 0.005)
    tref = 5.96e7 * 0.02 ** 2 / (8 * 390)
    c = store.load(cid)
    vi = sum(units.to_si(c["boundaries"][f]["voltage"]) * i for f, i in m["face_current_a"].items())
    for name, value, ref in (("busbar_R_ohm", m["resistance_ohm"], rref), ("busbar_power_W", m["power_w"], vi),
                             ("busbar_qjoule_W", m["q_joule_w"], m["power_w"]),
                             ("busbar_rise_K", m["t_max_k"] - 293.15, tref)):
        number(name, value, ref)
    assert m["resistance_ohm"] == pytest.approx(rref, rel=0.005)
    assert m["power_w"] == pytest.approx(vi, rel=0.001)
    assert m["q_joule_w"] == pytest.approx(m["power_w"], rel=0.005)
    assert m["t_max_k"] - 293.15 == pytest.approx(tref, rel=0.01)
    print(f"MEASURE busbar balances: current={m['imbalance']:.9g}, heat={m['heat_imbalance']:.9g}")
    assert m["imbalance"] < 1e-3 and m["heat_imbalance"] < 1e-3
    assert {"V", "E", "J", "q", "T"} == set(np.load(jd / "results.npz").files)
    pl = C.get_results(cid)
    assert pl["quantities"][0]["id"] == "temp" and pl["cards"][0]["key"] == "t_rise"
    assert C.verify_case(cid)["gates"]["verified"]
    for q in ("temp", "v", "jmag", "q"):
        assert np.isfinite(C.field(cid, q)["scalars"]).all()
    assert C.render_view(cid)[1]["quantity"] == "temp"
    C.update_case(cid, c["revision"], {"physics.joule_heating": False})
    assert C.get_results(cid)["stale"]


def test_06_prescribed_total_current():
    cid, _, r = solve("busbar", {"boundaries.x0.role": "current", "boundaries.x0.current": "1 A", "physics.joule_heating": False})
    v = C.probe_results(cid, faces=["x0", "x1"])["faces"]
    ref = 0.2 / (5.96e7 * 0.02 * 0.005)
    number("current_1A_electrode_V", v[0]["mean"]["v"], ref)
    assert v[0]["mean"]["v"] == pytest.approx(ref, rel=0.005)
    assert v[0]["current_a"] == pytest.approx(1) and v[1]["current_a"] == pytest.approx(-1, rel=1e-3)
    assert "T" not in np.load(results.load(cid)[0] / "results.npz").files
    assert "temp" not in [q["id"] for q in C.get_results(cid)["quantities"]]


def test_07_validation_and_thermal_editing():
    p = C.create_case("capacitor")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    for ch in ({"materials.solid.eps_r": 0.5}, {"materials.solid.sigma": -1}, {"materials.solid.sigma": float("inf")},
               {"materials.solid.eps_r": float("nan")}, {"boundaries.z1.voltage": "1 A"}):
        with pytest.raises(StudioError):
            C.update_case(cid, rev, ch)
    C.update_case(cid, rev, {"boundaries.z0.role": "open", "boundaries.z1.role": "open"})
    v = C.validate_case(cid)
    assert not v["ready"] and any(i["code"] == "no_voltage" for i in v["items"])
    with pytest.raises(StudioError):
        C.run_simulation(cid)
    p = C.create_case("busbar")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    p = C.update_case(cid, rev, {"boundaries.y0.thermal.role": "convection", "boundaries.y0.thermal.h": "12 W/m2K",
                               "boundaries.y0.thermal.tinf": "25 degC"})
    assert p["case"]["boundaries"]["y0"]["thermal"]["h"]["value"] == 12
    with pytest.raises(StudioError):
        C.update_case(cid, p["case"]["revision"], {"boundaries.y0.thermal.role": "voltage"})
    p = C.update_case(cid, p["case"]["revision"], {"boundaries.x0.thermal.role": "insulated", "boundaries.x1.thermal.role": "insulated", "boundaries.y0.thermal.role": "insulated"})
    assert not p["ready"]
    p = C.update_case(cid, p["case"]["revision"], {"physics.joule_heating": False})
    assert p["ready"]


def test_08_capacitor_mesh_study(capacitor):
    cid = capacitor[0]
    out = C.check_convergence(cid, wait_s=1)
    job = out.get("job_id") or out["job"]["job_id"]
    assert jobs.wait(job, 1800)["state"] == "done", C.job_status(job)
    r = results.load(cid)[1]
    conv = r["convergence"]
    print(f"MEASURE capacitor study: GCI={conv['gci_pct']:.9g}%, elements={[l['elements'] for l in conv['levels']]}")
    assert conv["quantity"] == "capacitance" and conv["pass"] and conv["gci_pct"] <= 5
    assert all(l["converged"] for l in conv["levels"])


@pytest.mark.parametrize("physics", ["electrostatic", "current"])
def test_09_mcp_import_and_tool_count(tmp_path, physics):
    from novastudio import mcp_server as M
    step = tmp_path / "mcp.step"
    two_box_step(step)
    r = asyncio.run(M.import_geometry(str(step), physics, language="en"))
    assert not r.is_error
    d = r.structured_content
    c = store.load(d["case_id"])
    assert c["template"] == f"import-{physics}" and len(c["body_materials"]) == 2
    assert all(b["role"] == ("open" if physics == "electrostatic" else "insulated") for b in c["boundaries"].values())
    assert M.INSTRUCTIONS.count("Joule") >= 1
    assert Path(M.__file__).read_text(encoding="utf-8").count("@mcp.tool(") == 23
    for prop, val in (("eps_r", 0.5), ("sigma", -1), ("sigma", float("inf"))):
        body = next(iter(c["body_materials"]))
        with pytest.raises(StudioError):
            C.update_case(c["case_id"], c["revision"], {f"body_props.{body}.{prop}": val})


def test_10_i18n_keys():
    root = Path(__file__).resolve().parents[2]
    for folder in (root / "backend/novastudio/i18n", root / "frontend/src/i18n"):
        keys = [set(json.loads((folder / f"{lang}.json").read_text(encoding="utf-8"))) for lang in ("ja", "en", "zh")]
        assert keys[0] == keys[1] == keys[2], {str(folder): [sorted(k ^ keys[0]) for k in keys]}
        print(f"MEASURE i18n {folder.name} ({folder.parent.name}): {len(keys[0])} identical keys")


def test_surface_charge_balance_and_air_warning():
    cid, _, r = solve("capacitor", {"boundaries.z1.role": "surface-charge", "boundaries.z1.charge": "1e-4 C/m2",
                                   "materials.solid.preset": "air", "geometry.params.length": "5 mm", "geometry.params.width": "5 mm"})
    m = r["metrics"]
    assert m["imbalance"] < 1e-3 and "capacitance_f" not in m
    assert m["face_charge_c"]["z1"] == pytest.approx(1e-4 * 0.005 ** 2)
    assert m["face_charge_c"]["z0"] == pytest.approx(-m["face_charge_c"]["z1"], rel=1e-3)
    assert any(w["code"] == "air_breakdown" for w in C.get_results(cid)["warnings"])
    assert not C.verify_case(cid)["gates"]["verified"]


def test_multielectrode_reference_and_units():
    from novastudio.run_worker import primary_quantity, reference_electric
    case = templates.new_case("capacitor", "c_test")
    case["boundaries"]["y0"] = {"role": "voltage", "voltage": {"value": 25, "unit": "V"}}
    assert not reference_electric(case, {})["applicable"]
    # several electrodes: no capacitance, and the study tracks the energy (a response), not a charge
    m = {"face_charge_c": {"a": -2e-9, "b": 1e-9}, "energy_j": 3e-7}
    assert primary_quantity(case, {"kind": "electrostatic", "metrics": m}) == ("energy", 3e-7, "J")
    for value, si in (("2 mV", 0.002), ("3 kV", 3000), ("4 mA", 0.004), ("5 pF", 5e-12), ("6 mohm", 0.006)):
        assert units.to_si(value) == pytest.approx(si)


def solve_changed(tid, changes):
    p = C.create_case(tid)
    cid = p["case"]["case_id"]
    C.update_case(cid, p["case"]["revision"], changes)
    out = C.run_simulation(cid, wait_s=1)
    job = out.get("job_id") or out["job"]["job_id"]
    assert jobs.wait(job, 1800)["state"] == "done", C.job_status(job)
    return results.load(cid)[1]


# second opinion (EM) #1 and #5: a prescribed current is not a study quantity, and the current card is the current
# that goes through the part (+1 A), not the ground's reaction (-1 A)
def test_prescribed_current_card_and_study_quantity():
    from novastudio.run_worker import primary_quantity
    r = solve_changed("busbar", {"physics.joule_heating": False, "boundaries.x0.role": "current",
                                 "boundaries.x0.current": "1 A"})
    m = r["metrics"]
    assert m["current_a"] == pytest.approx(1.0, rel=1e-6)
    assert "resistance_ohm" not in m
    assert primary_quantity({}, r)[0] == "power"


# second opinion (EM) #4: an extra surface charge must not turn into a "capacitance"
def test_surface_charge_suppresses_capacitance():
    r = solve_changed("capacitor", {"boundaries.x0.role": "surface-charge", "boundaries.x0.charge": "0.001 C/m2"})
    assert "capacitance_f" not in r["metrics"]
    assert not r["reference"]["applicable"]


# second opinion (EM) #3: with convection only, the rise is measured from the ambient air
def test_convection_rise_from_ambient():
    ch = {}
    for f in ("x0", "x1", "y0", "y1", "z0", "z1"):
        ch.update({f"boundaries.{f}.thermal.role": "convection", f"boundaries.{f}.thermal.h": "10 W/m2K",
                   f"boundaries.{f}.thermal.tinf": "20 degC"})
    m = solve_changed("busbar", ch)["metrics"]
    assert m["t_rise_k"] == pytest.approx(m["t_max_k"] - 293.15, rel=1e-9)
    # nearly all of the Joule heat leaves through the surface: the part sits well above the air
    assert m["t_rise_k"] > 10 * (m["t_max_k"] - m["t_min_k"])
