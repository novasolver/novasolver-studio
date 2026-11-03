"""Instant answers from solved points: right at the points, honest between them, silent outside them."""
import asyncio
import json
import math
from pathlib import Path

import numpy as np
import pytest

from novastudio import estimate as E
from novastudio import mcp_server
from novastudio.store import StudioError


def points(shape):
    return json.loads((E.DATA / f"{shape}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("shape", E.SHAPES)
def test_solved_point_returns_itself(shape):
    d = points(shape)
    names = [p[0] for p in d["params"]]
    r = d["points"][len(d["points"]) // 2]
    got = E.estimate(shape, dict(zip(names, r[1:1 + len(names)])))
    assert got["exact_point"] and got["nearest_point"]["id"] == r[0]
    for i, row in enumerate(got["results"]):
        assert row["dimensionless_value"] == r[1 + len(names) + 2 * i]
        assert row["interpolation_error_pct"] == 0


@pytest.mark.parametrize("shape", E.SHAPES)
def test_error_bar_holds_on_points_the_fit_never_saw(shape, tmp_path, monkeypatch):
    """Solved points held out of the data: at least nine in ten must land inside the stated error bar."""
    d = points(shape)
    names = [p[0] for p in d["params"]]
    held, kept = d["points"][::10], [r for i, r in enumerate(d["points"]) if i % 10]
    d = {k: v for k, v in d.items() if k != "gp"}                      # its settings are learned from the kept points alone
    (tmp_path / f"{shape}.json").write_text(json.dumps({**d, "points": kept}), encoding="utf-8")
    monkeypatch.setattr(E, "DATA", tmp_path)
    E._space.cache_clear()
    try:
        inside = total = 0
        for r in held:
            x = dict(zip(names, r[1:1 + len(names)]))
            for i, row in enumerate(E.estimate(shape, x)["results"]):
                true = r[1 + len(names) + 2 * i]
                inside += abs(row["dimensionless_value"] / true - 1) * 100 <= row["error_pct"]
                total += 1
        assert inside / total >= 0.9, (shape, inside, total)
    finally:
        E._space.cache_clear()


@pytest.mark.parametrize("shape", E.SHAPES)
def test_stored_settings_cover_every_quantity(shape):
    d = points(shape)
    assert len(d["gp"]) == len(E.SHAPES[shape]["out"])
    for h in d["gp"]:
        assert len(h["lengths"]) == len(d["params"]) and h["signal"] > 0 and h["noise"] > 0


def test_bar_widens_away_from_the_points():
    """A left-out constant says nothing about where the points are: the corner of the box is further from them."""
    centre = {"h_over_L": 0.7, "t_over_L": 0.095, "w_over_L": 0.5, "r_over_t": 0.9, "nu": 0.3}
    corner = {k: E.ranges("l_bracket")[k][0] for k in centre}
    interp = [E.estimate("l_bracket", x)["results"][1]["interpolation_error_pct"] for x in (centre, corner)]
    assert interp[1] > interp[0]


def test_thick_cylinder_matches_lame_between_the_points():
    x = {"b_over_a": 1.77, "nu": 0.31}
    r = E.estimate("thick_cylinder", x, {"p_MPa": 10, "a_mm": 50, "E_GPa": 206})["results"]
    k2 = 1.77 ** 2
    hoop = 10 * (1 + k2) / (k2 - 1)
    assert r[0]["value"] == pytest.approx(hoop, rel=r[0]["error_pct"] / 100)
    u = 10 * 50 / 206000 * 1.31 * ((1 - 0.62) + k2) / (k2 - 1)
    assert r[1]["value"] == pytest.approx(u, rel=r[1]["error_pct"] / 100)


def test_dimensional_value_follows_the_definition():
    r = E.estimate("stepped_shaft", {"D_over_d": 1.5, "r_over_h": 0.5}, {"d_mm": 20, "F_N": 10000})
    row = r["results"][0]
    assert r["ratios"]["nu"] == 0.3
    assert row["value"] == pytest.approx(row["dimensionless_value"] * 10000 / (math.pi * 100))


@pytest.mark.parametrize("shape,ratios,size,key", [
    ("spaceship", {}, None, "err.estimate_shape"),
    ("stepped_shaft", {"D_over_d": 1.5}, None, "err.estimate_ratios"),
    ("stepped_shaft", {"D_over_d": 1.5, "r_over_h": 0.5, "x": 1}, None, "err.estimate_ratios"),
    ("stepped_shaft", {"D_over_d": 3.0, "r_over_h": 0.5}, None, "err.estimate_range"),
    ("stepped_shaft", {"D_over_d": float("nan"), "r_over_h": 0.5}, None, "err.estimate_value"),
    ("stepped_shaft", {"D_over_d": 1.5, "r_over_h": 0.5}, {"d_mm": 20}, "err.estimate_size"),
    ("stepped_shaft", {"D_over_d": 1.5, "r_over_h": 0.5}, {"d_mm": 0, "F_N": 1}, "err.estimate_value"),
])
def test_refuses_what_the_data_does_not_cover(shape, ratios, size, key):
    with pytest.raises(StudioError) as e:
        E.estimate(shape, ratios, size)
    assert e.value.key == key


def test_mcp_tool_says_it_is_a_lookup():
    r = asyncio.run(mcp_server.instant_estimate("plate_hole", {"d_over_W": 0.3, "t_over_W": 0.1}, {"W_mm": 50, "F_N": 10000}, "en"))
    assert not r.is_error
    assert r.structured_content["results"][0]["unit"] == "MPa"
    assert "No solve was run" in r.content[0].text
    bad = asyncio.run(mcp_server.instant_estimate("plate_hole", {"d_over_W": 0.9, "t_over_W": 0.1}, None, "en"))
    assert bad.is_error and "0.6" in bad.content[0].text


def test_fast_enough_for_a_design_loop():
    import time
    E.estimate("l_bracket", {"h_over_L": 0.7, "t_over_L": 0.1, "w_over_L": 0.5, "r_over_t": 0.9})
    t0 = time.perf_counter()
    for f in np.linspace(0.05, 0.14, 100):
        E.estimate("l_bracket", {"h_over_L": 0.7, "t_over_L": float(f), "w_over_L": 0.5, "r_over_t": 0.9})
    assert (time.perf_counter() - t0) / 100 < 0.05

def test_stored_cylinder_answers_stay_within_their_band_of_lame():
    sp = E._space("thick_cylinder")
    for i, x in enumerate(dict(zip(sp["names"], row)) for row in sp["X"]):
        for q, exact in zip(sp["q"], (E._lame_hoop(x), E._lame_u(x))):
            assert abs(q["y"][i] / exact - 1) <= q["band"][i]


def test_titles_say_what_was_actually_solved():
    assert "spread evenly" in E.SHAPES["l_bracket"]["title"] and "tip" not in E.SHAPES["l_bracket"]["title"]
    assert "plane strain" in E.SHAPES["thick_cylinder"]["title"]
    doc = asyncio.run(mcp_server.mcp.list_tools())
    text = next(t.description for t in doc if t.name == "instant_estimate")
    assert "not a force at the tip" in text and "plane strain" in text


def test_the_desktop_build_bundles_the_data():
    path = Path(__file__).parents[2] / "build_release.ps1"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")               # Windows PowerShell misreads its Japanese text without a BOM
    build = path.read_text(encoding="utf-8")
    assert "novastudio\\estimate_data;novastudio\\estimate_data" in build
