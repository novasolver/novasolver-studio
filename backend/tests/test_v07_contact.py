"""0.7: contact between separate surfaces (contact_pairs, averaged-gap mortar)."""
import numpy as np
import pytest

from novastudio import commands as C, store
from novastudio.store import StudioError


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    return tmp_path


def run(cid):
    r = C.run_simulation(cid, "preview", wait_s=900, lang="en")
    assert r.get("results"), r.get("job")
    return r["results"]


def test_gap_blocks_patch_test_non_matching(ws):
    cid = C.create_case("gap-blocks", {}, "en")["case"]["case_id"]
    res = run(cid)
    assert res["gates"] == {"ran": True, "converged": True, "verified": True}
    v = res["verification"]
    assert abs(v["error_pct"]) < 0.5
    # the mortar patch test: a uniform stress crosses the non-matching interface unchanged
    from novastudio import results as R
    jd, raw = R.load(cid)
    data = np.load(jd / "results.npz")
    p = data["p_contact"][np.flatnonzero(data["p_contact"])]
    assert p.max() / p.min() < 1.01


def test_gap_stays_open_below_the_gap(ws):
    cid = C.create_case("gap-blocks", {"boundaries.top.uz": {"value": -0.03, "unit": "mm"}}, "en")["case"]["case_id"]
    res = run(cid)
    cards = {c["key"]: c["value"] for c in res["cards"]}
    assert cards.get("contact_force", 0) == pytest.approx(0, abs=1e-6)
    assert res["interfaces"]["interface"]["status_counts"]["open"] > 0
    assert res["interfaces"]["interface"]["status_counts"]["stick"] == 0


def test_tied_parts_match_one_bar(ws):
    cid = C.create_case("tied-parts", {}, "en")["case"]["case_id"]
    res = run(cid)
    assert res["gates"]["verified"]
    assert abs(res["verification"]["error_pct"]) < 0.5


def test_detect_contacts_finds_the_pair_and_nothing_far(ws):
    cid = C.create_case("gap-blocks", {}, "en")["case"]["case_id"]
    case = store.load(cid)
    C.update_case(cid, case["revision"], {"contact_pairs.interface": None}, "en")
    r = C.detect_contacts(cid, {"value": 1, "unit": "mm"}, apply=True, lang="en")
    assert [(p["master"], p["slave"]) for p in r["pairs"]] in ([(["lower_top"], ["upper_bottom"])], [(["upper_bottom"], ["lower_top"])])
    assert r["pairs"][0]["gap_mm"] == pytest.approx(0.05, rel=1e-3)
    assert store.load(cid)["contact_pairs"][r["pairs"][0]["name"]]["type"] == "bonded"
    far = C.create_case("gap-blocks", {"geometry.params.gap": {"value": 5, "unit": "mm"}}, "en")["case"]["case_id"]
    assert C.detect_contacts(far, {"value": 1, "unit": "mm"}, lang="en")["pairs"] == []


def test_contact_pair_validation(ws):
    cid = C.create_case("gap-blocks", {}, "en")["case"]["case_id"]
    rev = store.load(cid)["revision"]
    for bad in ({"master": ["lower_top"], "slave": ["lower_top"]},
                {"master": ["nope"], "slave": ["upper_bottom"]},
                {"master": ["lower_top"], "slave": ["upper_bottom"], "type": "glue"}):
        with pytest.raises(StudioError):
            C.update_case(cid, rev, {"contact_pairs.p": bad}, "en")
    C.update_case(cid, rev, {"physics.analysis": "modal"}, "en")
    assert any(i["code"] == "contact_pairs_analysis" for i in C.validate_case(cid, "en")["items"])


def test_contact_fields_render_for_separate_surfaces(ws):
    """review H1: the contact quantities of a mortar pair are drawn on its faces (was a 500)."""
    cid = C.create_case("gap-blocks", {}, "en")["case"]["case_id"]
    run(cid)
    f = C.get_field(cid, "p_contact", "en") if hasattr(C, "get_field") else None
    from novastudio import results as R
    out = R.field(store.load(cid), "p_contact", "en")
    assert out["quantity"] == "p_contact" and max(out["scalars"]) > 0
