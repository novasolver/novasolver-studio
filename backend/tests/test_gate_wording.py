"""The third gate is named by what it checked; nothing calls a user's model "verified"."""
import json
from pathlib import Path

from novastudio.mcp_server import _gates_line

I18N = Path(__file__).resolve().parents[1] / "novastudio" / "i18n"
UI = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"


def test_mcp_gate_line_names_the_check():
    assert _gates_line({"ran": True, "converged": True, "verified": True, "verified_by": "mesh"}) == \
        "ran=yes / converged=yes / mesh convergence (GCI) passed"
    assert _gates_line({"ran": True, "converged": True, "verified": False, "verified_by": None}).endswith(
        "mesh convergence not checked")
    assert _gates_line({"ran": True, "converged": True, "verified": False, "verified_by": "mesh"}).endswith(
        "mesh convergence not reached")
    assert _gates_line({"ran": True, "converged": True, "verified": True, "verified_by": "reference"}).endswith(
        "matches reference")


def test_gate_wording_has_no_verified_label():
    for root in (I18N, UI):
        for lang in ("ja", "en", "zh"):
            d = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
            assert d["gate.verified"] not in ("検証済み", "検証", "Verified", "已验证"), (root, lang)
    d = json.loads((I18N / "ja.json").read_text(encoding="utf-8"))
    assert d["gate.mesh_ok"].format(gci=1.94) == "メッシュ収束：確認済み（GCI 1.9%）"