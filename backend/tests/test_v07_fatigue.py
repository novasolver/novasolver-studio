"""0.7: stress-life fatigue post-processing."""
import numpy as np
import pytest

from novastudio import commands as C, fatigue


def case_of(ratio, surface="polished", preset="steel"):
    return {"physics": {"fatigue": {"enabled": True, "ratio": ratio, "surface": surface}},
            "materials": {"solid": {"preset": preset}}}


def uniaxial(s):
    return np.array([[s, 0, 0, 0, 0, 0]], float)


def test_goodman_and_fully_reversed():
    mat = fatigue.material(case_of(0))
    r = fatigue.evaluate(uniaxial(150e6), case_of(0), mat)
    assert r["sf"][0] == pytest.approx(1 / (75 / 200 + 75 / 400))          # Goodman, R = 0
    r = fatigue.evaluate(uniaxial(150e6), case_of(-1), mat)
    assert r["sf"][0] == pytest.approx(200 / 150)                            # fully reversed: Se / sigma_a
    assert r["life"][0] == fatigue.INFINITE                                  # below the endurance limit


def test_compressive_mean_gets_no_credit_and_surface_lowers_se():
    mat = fatigue.material(case_of(0))
    r = fatigue.evaluate(uniaxial(-150e6), case_of(0), mat)
    assert r["sf"][0] == pytest.approx(200 / 75)
    m = fatigue.evaluate(uniaxial(150e6), case_of(-1, "machined"), mat)
    ka = 4.51 * 400 ** -0.265
    assert m["ka"] == pytest.approx(ka) and m["sf"][0] == pytest.approx(ka * 200 / 150)


def test_finite_life_on_the_sn_line():
    mat = fatigue.material(case_of(-1))
    su, se = 400e6, 200e6
    b = np.log10(se / (0.9 * su)) / 3
    for n in (1e3, 1e4, 1e5):
        s = 0.9 * su * (n / 1e3) ** b                    # the amplitude whose life is n
        assert fatigue.evaluate(uniaxial(s), case_of(-1), mat)["life"][0] == pytest.approx(n, rel=1e-9)


def test_aluminium_has_no_endurance_limit():
    mat = fatigue.material(case_of(-1, preset="aluminium"))
    life = fatigue.evaluate(uniaxial(80e6), case_of(-1, preset="aluminium"), mat)["life"][0]
    assert 5e8 < life < fatigue.INFINITE                 # below Se(5e8) but still finite


def test_plastics_have_no_fatigue_data():
    assert fatigue.material(case_of(-1, preset="pla")) is None


def test_fatigue_bar_template(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path))
    cid = C.create_case("fatigue-bar", {}, "en")["case"]["case_id"]
    res = C.run_simulation(cid, "preview", wait_s=600, lang="en")["results"]
    assert res["gates"]["verified"] and abs(res["verification"]["error_pct"]) < 0.1
    assert any(w["code"] == "fatigue_infinite" for w in res["warnings"])
