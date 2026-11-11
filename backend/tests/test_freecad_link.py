"""The FreeCAD workbench's link to Studio (integrations/freecad/NovaSolverStudio/nss_link.py), against a real Studio
server on 127.0.0.1: send a STEP and find its case again by content hash, then fetch a Genesis result the way the
workbench does (STEP for an extruded part, the smoothed STL otherwise)."""
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from novastudio import commands as C

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "freecad" / "NovaSolverStudio"))
import nss_link as L  # noqa: E402


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVASTUDIO_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    monkeypatch.setattr(L, "studio_program", lambda: None)              # never start a real Studio
    opened = []
    monkeypatch.setattr(L.webbrowser, "open", opened.append)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    from novastudio.api import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    t0 = time.monotonic()
    while not server.started:
        assert time.monotonic() - t0 < 30
        time.sleep(0.05)
    d = tmp_path / "lad" / "NovaSolverStudio"
    d.mkdir(parents=True)
    (d / "running.json").write_text(json.dumps({"port": port}), encoding="utf-8")
    yield port, opened
    server.should_exit = True
    t.join(10)


def test_initgui_loads_the_way_freecad_runs_it(monkeypatch):
    """FreeCAD 1.1 runs InitGui.py with exec() inside a function (FreeCADGuiInit.RunInitGuiPy): top-level names of
    the file are not visible from the class methods. A helper defined at the top made the workbench vanish."""
    import types
    added = []

    class Workbench:
        def appendToolbar(self, *a): pass

        def appendMenu(self, *a): pass

    fake = types.SimpleNamespace(Workbench=Workbench, addWorkbench=added.append)
    monkeypatch.setitem(sys.modules, "FreeCADGui", fake)
    src = ROOT / "integrations" / "freecad" / "NovaSolverStudio" / "InitGui.py"

    def run_init_gui_py():                      # same call as FreeCAD's loader
        with open(src, "rt", encoding="utf-8") as f:
            exec(compile(f.read(), str(src), "exec"))
    run_init_gui_py()
    assert len(added) == 1 and Path(added[0].Icon).is_file()
    assert added[0].GetClassName() == "Gui::PythonWorkbench"


def test_send_and_find_again_by_hash(studio, tmp_path):
    port, opened = studio
    assert L.running_port() == port
    step = tmp_path / "Body.step"
    step.write_bytes((ROOT / "samples" / "l_bracket.step").read_bytes())
    cid = L.send(step, "structural", "en")
    assert L.CASE_ID.fullmatch(cid) and opened == [f"http://127.0.0.1:{port}/?case={cid}"]
    other = tmp_path / "Other.step"
    other.write_bytes((ROOT / "samples" / "sphere.step").read_bytes())
    L.send(other, "structural", "en")
    # the case id was lost (an older FreeCAD without Meta, or Studio took the file through --import): hash, then name
    assert [c["case_id"] for c in L.find_cases(port, digest=L.sha256(step))] == [cid]
    assert [c["case_id"] for c in L.find_cases(port, filename="Body.step")] == [cid]
    assert L.genesis(port, cid) is None                                 # no Genesis run yet


def test_import_the_genesis_result(studio, tmp_path):
    port, _ = studio
    cid = C.create_case("cantilever", {}, "en")["case"]["case_id"]
    C.run_genesis(cid, {"cells": 3000, "iterations": 10, "extrusion": "y"}, wait_s=600, lang="en")
    t0 = time.monotonic()
    while (res := L.genesis(port, cid)) is None:
        assert time.monotonic() - t0 < 900
        time.sleep(2)
    assert [c["case_id"] for c in L.find_cases(port, case_id=cid)] == [cid]
    kind, url = L.pick_file(res)
    assert kind == "step"                                                # extruded: the flat-faced solid
    path = L.download(port, url, tmp_path / "dl" / "g.step")
    assert path.read_bytes().startswith(b"ISO-10303-21")
    res["files"].pop("step")
    kind, url = L.pick_file(res)
    assert kind == "stl_smooth"
    stl = L.download(port, url, tmp_path / "dl" / "g.stl").read_bytes()
    n = struct.unpack("<I", stl[80:84])[0]
    assert n > 100 and len(stl) == 84 + 50 * n                           # binary STL
    import numpy as np
    rec = np.frombuffer(stl[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    assert 0.01 < np.abs(rec["v"]).max() < 2                             # metres: FreeCAD scales it by 1000
    with pytest.raises(ValueError):
        L.pick_file({"case_id": cid, "files": {"stl": "/api/cases/c_x/../../etc"}})
