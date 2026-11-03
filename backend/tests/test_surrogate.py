"""A model of the person's own case: accurate between the points, honest about its bar, silent outside the ranges."""
import asyncio
import json
import math
import os

import numpy as np
import pytest

from novastudio import commands as C, jobs, mcp_server, store, surrogate as S
from novastudio.store import StudioError


@pytest.fixture(scope="module", autouse=True)
def private_workspace(tmp_path_factory):
    old = os.environ.get("NOVASTUDIO_WORKSPACE")
    os.environ["NOVASTUDIO_WORKSPACE"] = str(tmp_path_factory.mktemp("surrogate"))
    yield
    if old is None:
        os.environ.pop("NOVASTUDIO_WORKSPACE", None)
    else:
        os.environ["NOVASTUDIO_WORKSPACE"] = old


def smooth(U):
    return (2 + np.sin(2.5 * U[:, 0])) * np.exp(0.8 * U[:, 1]) * (1 + 0.3 * U[:, 2] ** 2)


def design(n, dim, seed=1):
    return np.random.default_rng(seed).random((n, dim))


def test_accurate_and_honest_on_points_it_never_saw():
    U, Q = design(60, 3), design(400, 3, 2)
    f = S.Fit(U, np.log(smooth(U)), S.NOISE_FLOOR)
    m, bar = f.predict(Q)
    e = np.abs(m - np.log(smooth(Q)))
    assert np.percentile(e, 95) < 0.01
    assert (e <= bar).mean() >= 0.9


def test_saved_numbers_give_the_same_answer():
    U, Q = design(40, 2), design(5, 2, 2)
    y = np.log(U[:, 0] + 1)
    a = S.Fit(U, y, S.NOISE_FLOOR)
    b = S.Fit(U, y, S.NOISE_FLOOR, json.loads(json.dumps(a.hyper())))
    assert a.predict(Q)[0] == pytest.approx(b.predict(Q)[0], rel=1e-10)
    assert a.predict(Q)[1] == pytest.approx(b.predict(Q)[1], rel=1e-10)


def test_bar_does_not_collapse_on_a_nearly_noiseless_answer():
    """With a nugget below the rounding of the data, sigma was numerics and the bar held 51 % of the left-out points."""
    U, Q = design(100, 3), design(300, 3, 2)
    fn = lambda X: np.exp(X[:, 0] + 0.5 * X[:, 1] + 0.2 * X[:, 2] ** 2)
    f = S.Fit(U, np.log(fn(U)), S.NOISE_FLOOR)
    m, bar = f.predict(Q)
    assert (np.abs(m - np.log(fn(Q))) <= bar).mean() >= 0.9
    assert bar.min() >= S.NOISE_FLOOR


def test_bar_widens_far_from_the_data():
    U = design(60, 2) * 0.5                        # nothing in the far corner
    f = S.Fit(U, np.log(smooth(np.c_[U, U[:, 0]])), S.NOISE_FLOOR)
    near, far = f.predict([[0.25, 0.25], [1.0, 1.0]])[1]
    assert far > 3 * near


@pytest.mark.parametrize("key,y,kind", [
    ("max_vm_pa", [1e6, 2e6], "log"), ("t_max_k", [300.0, 350.0], "linear"), ("umin_center", [-0.2, 0.1], "linear"),
    ("max_speed", [0.0, 1.0], "linear")])
def test_transform(key, y, kind):
    assert S.transform(key, y) == kind


def test_units_from_the_metric_name():
    assert [S._unit(k) for k in ("max_vm_pa", "max_disp_m", "t_max_k", "flow_rate_m3s", "j_max_a_m2", "cd")] == ["Pa", "m", "K", "m3/s", "A/m2", "-"]


def test_constant_output_does_not_break_the_fit():
    U = design(30, 2)
    r = S.fit_output("reaction_n", U, np.full(30, 1000.0), 5)
    assert r["holdout"]["inside"] == 5
    f = S.Fit(U, np.log(np.full(30, 1000.0)), r["floor"], r["hyper"])
    assert math.exp(f.predict([[0.3, 0.3]])[0][0]) == pytest.approx(1000.0)


@pytest.mark.parametrize("params,n,mesh,detail", [
    ([], None, 0, "parameters"),
    ([{"path": f"a{i}", "min": 0, "max": 1} for i in range(6)], None, 0, "parameters"),
    ([{"path": "boundaries.x1.force", "min": 5, "max": 1, "unit": "N"}], None, 0, "min < max"),
    ([{"path": "boundaries.x1.force", "min": 0, "max": float("nan"), "unit": "N"}], None, 0, "min < max"),
    ([{"path": "boundaries.x1.force", "min": 1, "max": 2, "unit": "N"}] * 2, None, 0, "once"),
    ([{"path": "boundaries.x1.force", "min": 1, "max": 2, "unit": "N"}], 5, 0, "n:"),
    ([{"path": "boundaries.x1.force", "min": 1, "max": 2, "unit": "N"}], None, 9, "mesh_checks"),
])
def test_refuses_a_bad_request(params, n, mesh, detail):
    cid = C.create_case("cantilever", None, lang="en")["case"]["case_id"]
    with pytest.raises(StudioError) as e:
        S.build(cid, params, None, n, mesh, None, "en")
    assert e.value.key == "err.surrogate_spec" and detail in e.value.kw["detail"]


def test_a_wrong_path_fails_at_once_and_leaves_no_case_behind():
    cid = C.create_case("cantilever", None, lang="en")["case"]["case_id"]
    before = set(p.name for p in store.cases_dir().iterdir())
    with pytest.raises(StudioError):
        S.build(cid, [{"path": "boundaries.nope.force", "min": 1, "max": 2, "unit": "N"}], None, 20, 0, None, "en")
    assert set(p.name for p in store.cases_dir().iterdir()) == before


def test_unknown_study():
    with pytest.raises(StudioError) as e:
        S.status("s_missing")
    assert e.value.key == "err.surrogate"
    with pytest.raises(StudioError):
        S.status("..\\x")


def wait_state(sid, states, seconds=900):
    import time
    end = time.time() + seconds
    while time.time() < end:
        s = S.status(sid)
        if s["state"] in states:
            return s
        time.sleep(1)
    raise AssertionError(S.status(sid))


@pytest.fixture(scope="module")
def built():
    """Three numbers of the textbook cantilever, solved for real. Stopped once on the way, so resume is exercised too."""
    cid = C.create_case("cantilever", None, lang="en")["case"]["case_id"]
    params = [{"path": "geometry.params.length", "min": 150, "max": 300, "unit": "mm"},
              {"path": "geometry.params.height", "min": 15, "max": 30, "unit": "mm"},
              {"path": "boundaries.x1.force", "min": 500, "max": 2000, "unit": "N"}]
    r = S.build(cid, params, None, 24, 1, None, "en")
    sid = r["study_id"]
    import time
    end = time.time() + 300
    while S.status(sid)["solved"] < 2 and time.time() < end:
        time.sleep(0.5)
    S.control(sid, "stop")
    stopped = wait_state(sid, ("stopped", "done", "failed"))
    assert stopped["state"] == "stopped", (stopped["message"], stopped["failures"], (S.study_dir(sid) / "worker.log").read_text(encoding="utf-8")[-800:])
    S.control(sid, "resume")
    done = wait_state(sid, ("done", "failed"))
    assert done["state"] == "done", (done["message"], done["failures"], (S.study_dir(sid) / "worker.log").read_text(encoding="utf-8")[-800:])
    return cid, sid, done, stopped


def test_build_finishes_and_keeps_the_points_across_a_stop(built):
    _, sid, done, stopped = built
    assert 2 <= stopped["solved"] < 24
    assert done["solved"] == 24 and done["failed"] == 0
    is_i = [json.loads(x)["i"] for x in (S.study_dir(sid) / "points.jsonl").read_text(encoding="utf-8").splitlines() if '"design"' in x]
    assert sorted(is_i) == list(range(24))                          # no point solved twice


def test_build_leaves_only_the_persons_case_behind(built):
    cid, sid, _, _ = built
    assert (store.cases_dir() / cid).is_dir()
    assert not any("surrogate" in json.dumps(store.load(p.name)["title"]) for p in store.cases_dir().iterdir() if (p / "case.json").is_file())


def test_answers_match_beam_theory_between_the_points(built):
    """Tip load on a slender beam: max stress and tip deflection have closed forms, in the units the build asked for."""
    _, sid, _, _ = built
    b = 20.0                                                        # template width, mm
    for L, h, F in ((200, 20, 1000), (260, 28, 700), (170, 17, 1800)):
        r = S.predict(sid, {"geometry.params.length": L, "geometry.params.height": h, "boundaries.x1.force": F})
        by = {q["key"]: q for q in r["results"]}
        d = F * L ** 3 / (3 * 200e3 * (b * h ** 3 / 12)) / 1000     # m (steel, 200 GPa)
        assert by["max_disp_m"]["value"] == pytest.approx(d, rel=0.03), (L, h, F)
        assert by["max_disp_m"]["unit"] == "m" and by["max_vm_pa"]["unit"] == "Pa"
        assert by["max_disp_m"]["error_pct"] > 0


def test_flags_too_few_points_and_reports_the_mesh_check(built):
    _, sid, done, _ = built
    assert "few_points" in done["model"]["warnings"]
    mesh = done["model"]["mesh"]
    assert done["mesh_checks_done"] == 1 and mesh["checks"] == 1 and mesh["gci_max_pct"] > 0
    assert "beam theory" not in mesh["quantity"]                    # the mesh study itself, not the template's reference
    for o in done["model"]["outputs"]:
        assert o["holdout"]["points"] == 4 and "bar_95" in o


@pytest.mark.parametrize("values,key", [
    ({"geometry.params.length": 200}, "err.surrogate_values"),
    ({"geometry.params.length": 999, "geometry.params.height": 20, "boundaries.x1.force": 1000}, "err.estimate_range"),
    ({"geometry.params.length": float("nan"), "geometry.params.height": 20, "boundaries.x1.force": 1000}, "err.estimate_value"),
])
def test_refuses_outside_what_it_solved(built, values, key):
    _, sid, _, _ = built
    with pytest.raises(StudioError) as e:
        S.predict(sid, values)
    assert e.value.key == key


def test_mcp_tools_say_what_the_bar_covers(built):
    _, sid, _, _ = built
    v = {"geometry.params.length": 200, "geometry.params.height": 20, "boundaries.x1.force": 1000}
    r = asyncio.run(mcp_server.surrogate_predict(sid, v, None, "en"))
    assert not r.is_error and "no solve was run" in r.content[0].text and "GCI" in r.content[0].text
    st = asyncio.run(mcp_server.surrogate_status(sid, "en"))
    assert "interpolation only" in st.content[0].text
    assert not asyncio.run(mcp_server.surrogate_status(None, "en")).is_error
    bad = asyncio.run(mcp_server.surrogate_predict(sid, {**v, "geometry.params.length": 9999}, None, "en"))
    assert bad.is_error and "300" in bad.content[0].text


def test_a_model_is_portable_numbers_only(built):
    _, sid, _, _ = built
    m = json.loads((S.study_dir(sid) / "model.json").read_text(encoding="utf-8"))
    assert len(m["U"]) == 24 and m["outputs"][0]["hyper"]["lengths"]


def test_answer_is_fast(built):
    import time
    _, sid, _, _ = built
    v = {"geometry.params.length": 200, "geometry.params.height": 20, "boundaries.x1.force": 1000}
    S.predict(sid, v)
    t0 = time.perf_counter()
    for _ in range(50):
        S.predict(sid, v)
    assert (time.perf_counter() - t0) / 50 < 0.05


def test_delete_needs_the_id_repeated(built):
    cid = C.create_case("cantilever", None, lang="en")["case"]["case_id"]
    r = S.build(cid, [{"path": "boundaries.x1.force", "min": 500, "max": 2000, "unit": "N"}], None, 20, 0, None, "en")
    sid = r["study_id"]
    with pytest.raises(StudioError):
        S.control(sid, "delete", "wrong", "en")
    S.control(sid, "delete", sid, "en")
    with pytest.raises(StudioError):
        S.status(sid)
    assert not any("surrogate" in json.dumps(store.load(p.name)["title"]) for p in store.cases_dir().iterdir() if (p / "case.json").is_file())
