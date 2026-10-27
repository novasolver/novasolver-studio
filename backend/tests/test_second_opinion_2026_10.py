"""Regression tests for the findings of the first second-opinion review (studio/reviews/2026-10-27_full.*).
Each test fails on the code before the fix. Run: python -m pytest backend/tests -q"""
from __future__ import annotations

import os
import tempfile
import threading

import numpy as np
import pytest

os.environ.setdefault("NOVASTUDIO_WORKSPACE", tempfile.mkdtemp(prefix="ns_test_"))

from novastudio import commands as C, flow3d, results, run_worker, store  # noqa: E402
from novastudio.probe import _Locator  # noqa: E402
from novastudio.store import StudioError  # noqa: E402


def _levels(values, h=(1.0, 0.5, 0.25)):
    return [{"h": hh, "value": v} for hh, v in zip(h, values)]


# 4 — a sequence that does not converge must not pass, and a final 0 must not hide a change
def test_gci_drifting_sequence_is_not_settled():
    g = run_worker.gci(_levels([100, 101, 102]))
    assert not g["asymptotic"] and g["monotone"]
    assert g["rel_change_pct"] > 0.5                      # run_study then refuses to pass it (settled = False, tol/10)


def test_gci_zero_final_value_keeps_the_change():
    g = run_worker.gci(_levels([1.0, 0.5, 0.0]))
    assert g["rel_change_pct"] == pytest.approx(100.0)
    assert g["gci_pct"] > 5.0


@pytest.mark.parametrize("values", [[100, 1, 0.5], [100, 1, 0]])
def test_gci_large_coarse_value_does_not_dilute(values):
    # second review 2026-10-28 #1: dividing by the coarse value made a 100 % change look like 0.04 %
    assert run_worker.gci(_levels(values))["gci_pct"] > 5.0


def test_gci_converging_sequence_still_passes():
    g = run_worker.gci(_levels([10.0, 10.4, 10.5]))
    assert g["asymptotic"] and g["gci_pct"] < 5.0


# 3 — two fixed temperatures: the study must track heat flow, never the imposed span
def test_thermal_study_quantity_is_heat_flow_with_two_fixed_faces():
    case = {"boundaries": {"a": {"role": "temperature"}, "b": {"role": "temperature"}}}
    with pytest.raises(ValueError):
        run_worker.primary_quantity(case, {"kind": "thermal", "metrics": {"t_max_k": 373.15, "t_min_k": 293.15}})
    name, val, _ = run_worker.primary_quantity(
        case, {"kind": "thermal", "metrics": {"t_max_k": 373.15, "t_min_k": 293.15, "q_in_w": 12.0}})
    assert (name, val) == ("q_in", 12.0)


# 14 — channel and conjugate studies have a quantity
def test_study_quantity_for_channel_and_conjugate():
    assert run_worker.primary_quantity({}, {"kind": "channel_of", "metrics": {"umax_outlet": 0.015}})[0] == "umax_outlet"
    q = run_worker.primary_quantity({}, {"kind": "conjugate", "metrics": {"t_solid_max_k": 330.0, "t_inlet_k": 300.0}})
    assert q[0] == "t_solid_rise" and q[1] == pytest.approx(30.0)


# 2 — physical ranges for materials in every template
@pytest.mark.parametrize("change", [{"materials.solid.E": "-1 GPa"}, {"materials.solid.nu": 0.75}])
def test_material_ranges_any_template(change):
    p = C.create_case("plate-hole")
    with pytest.raises(StudioError):
        C.update_case(p["case"]["case_id"], p["case"]["revision"], change)


# 1 — benchmark templates refuse role changes instead of ignoring them
def test_cavity_roles_are_fixed():
    p = C.create_case("cavity")
    with pytest.raises(StudioError) as e:
        C.update_case(p["case"]["case_id"], p["case"]["revision"], {"boundaries.x0.role": "moving-wall"})
    assert e.value.key == "err.fixed_roles"
    assert p["ui"]["fixed_roles"] is True


# 9 — a run id that leaves the case directory is refused
def test_run_id_traversal_refused():
    cid = C.create_case("cantilever")["case"]["case_id"]
    (store.case_dir(cid) / "run").mkdir(exist_ok=True)
    with pytest.raises(StudioError):
        results.latest_done_run(cid, "../../c_other/run/r_20260101_000000_abcd")


# 8 — two writers with the same expected revision: one wins, the other gets 409, no edit is lost silently
def test_concurrent_updates_one_conflicts():
    p = C.create_case("cantilever")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    out = []

    def edit(v):
        try:
            C.update_case(cid, rev, {"boundaries.x1.force": f"{v} N"})
            out.append("ok")
        except StudioError as e:
            out.append(e.status)

    ts = [threading.Thread(target=edit, args=(v,)) for v in (100, 200)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(map(str, out)) == ["409", "ok"]


# 10 — the local API only answers pages of this machine (Origin and Host checked; no Origin = curl / MCP bridge)
def test_api_refuses_other_sites():
    from fastapi.testclient import TestClient
    from novastudio.api import app
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/env").status_code == 200
    assert c.get("/api/env", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/env", headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert c.get("/api/env", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert c.post("/api/jobs/r_20260101_000000_abcd/stop", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert c.get("/api/env", headers={"Host": "evil.example:8765"}).status_code == 403     # DNS rebinding
    with pytest.raises(Exception):
        with c.websocket_connect("/ws", headers={"Origin": "https://untrusted.example"}):
            pass


# 5 — hydraulic diameter of a slot is 4A/P, not the circle of the same area
def test_hydraulic_diameter_of_a_slot():
    slot = {"area": 0.1 * 0.001, "perimeter": 2 * (0.1 + 0.001)}
    assert flow3d._hyd_diameter(slot) == pytest.approx(0.00198, rel=1e-3)
    circle = {"area": np.pi * 0.01 ** 2 / 4}               # old cases without a perimeter
    assert flow3d._hyd_diameter(circle) == pytest.approx(0.01)


# 16 — a curved tet10 reads a field that is linear in x exactly
def test_curved_tet10_probe_is_exact_for_a_linear_field():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    pairs = [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)]
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in pairs])
    mids[1] += [0.05, 0.05, 0.0]                           # bow the 1-2 edge outwards (a curved CAD face)
    nodes = np.vstack([corners, mids])
    tets = np.array([list(range(10))])
    loc = _Locator(nodes, tets)
    f = nodes[:, 0] + 2 * nodes[:, 1]                       # linear in physical x
    x = np.array([0.25, 0.225, 0.25])
    e, L = loc.locate(x)[:2]
    idx, w = loc.weights(e, loc.curved(e, x, L))
    assert float(f[idx] @ w) == pytest.approx(x[0] + 2 * x[1], abs=1e-9)
