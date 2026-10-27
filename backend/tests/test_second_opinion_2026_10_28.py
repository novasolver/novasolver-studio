"""Regression tests for the second-opinion review of the changes since v0.2.2 (studio/reviews/2026-10-28_since-v0.2.2.*).
Each test fails on the code before the fix. Run: python -m pytest backend/tests -q"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("NOVASTUDIO_WORKSPACE", tempfile.mkdtemp(prefix="ns_test_"))

from novastudio import commands as C, flow3d  # noqa: E402
from novastudio.probe import _Locator, _face_quadrature  # noqa: E402


# 2 — the worst energy residual of the last iteration, not the last region printed
def test_conjugate_residual_takes_every_region():
    log = ("Time = 499\nSolving for h, Initial residual = 0.5\n"
           "Time = 500\nSolving for fluid region water\nDILUPBiCG:  Solving for h, Initial residual = 0.2, Final\n"
           "Solving for solid region plate\nDICPCG:  Solving for h, Initial residual = 1e-06, Final\nEnd\n")
    assert flow3d.final_energy_residual(log) == pytest.approx(0.2)


# 4 — a point beyond an inward-bowed face is outside the curved element
def test_curved_tet10_membership():
    corners = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    pairs = [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)]
    mids = np.array([(corners[a] + corners[b]) / 2 for a, b in pairs])
    mids[1] = [0.45, 0.45, 0.0]                             # the 1-2 edge bowed inwards
    loc = _Locator(np.vstack([corners, mids]), np.array([list(range(10))]))
    hit = loc.locate(np.array([0.45, 0.45, 0.05]))
    assert hit is None or len(hit) == 3                    # (e, L, False): not inside
    assert len(loc.locate(np.array([0.2, 0.2, 0.2]))) == 2   # well inside: still found


# 5 — the area mean over a bowed tri6 is the true integral of the interpolant
def test_face_mean_on_curved_tri6():
    nodes = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, 0, 0], [0.6, 0.6, 0], [0, 0.5, 0]], float)
    tri = np.array([[0, 1, 2, 3, 4, 5]])
    N, idx, dA_v = _face_quadrature(nodes, tri)
    dA = np.linalg.norm(dA_v, axis=2)
    T = nodes[:, 0]                                         # T = x
    mean = float((np.einsum("qk,tk->tq", N, T[idx]) * dA).sum() / dA.sum())
    assert mean == pytest.approx(0.376842, abs=2e-6)
    # area of the bowed triangle: straight 0.5 plus the parabolic bulge 2/3 * base * height
    assert float(dA.sum()) == pytest.approx(0.5 + 2 / 3 * np.sqrt(2) * (0.6 * np.sqrt(2) - 0.5 * np.sqrt(2)), rel=1e-9)


# 7 — the MCP snippet of a source checkout carries the backend folder (and a workspace override)
def test_mcp_command_carries_source_path():
    m = C.environment_check()["mcp_command"]
    assert m["args"][-1] == "mcp"
    assert (Path(m["env"]["PYTHONPATH"]) / "novastudio" / "__init__.py").is_file()
    assert m["env"]["NOVASTUDIO_WORKSPACE"] == os.environ["NOVASTUDIO_WORKSPACE"] or \
        Path(m["env"]["NOVASTUDIO_WORKSPACE"]) == Path(os.environ["NOVASTUDIO_WORKSPACE"]).resolve()


# 8 — every study quantity has a label in every language
def test_study_quantity_labels():
    from novastudio.i18n import all3
    for q in ("max_disp", "q_in", "t_rise", "dp", "cd", "umin_center", "umax_outlet", "t_solid_rise"):
        for lang, text in all3(f"qty.study.{q}").items():
            assert text and not text.startswith("qty."), (q, lang)
