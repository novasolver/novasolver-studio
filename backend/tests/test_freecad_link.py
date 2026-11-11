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


# ---------------------------------------------------------------- the Fusion add-in, with a stand-in Fusion API

def _fake_fusion(monkeypatch, tmp_path):
    import importlib
    import types
    from types import SimpleNamespace as NS
    log = {"messages": [], "exported": [], "imported": [], "meshes": [], "buttons": []}

    class Handler:
        def __init__(self):
            pass

    class Attrs:
        def __init__(self):
            self.d = {}

        def itemByName(self, g, n):
            return NS(value=self.d[(g, n)]) if (g, n) in self.d else None

        def add(self, g, n, v):
            self.d[(g, n)] = v

    class Coll:
        def __init__(self, items=()):
            self.items = list(items)

        @property
        def count(self):
            return len(self.items)

        def item(self, i):
            return self.items[i]

    comp = NS(name="Bracket 1", bRepBodies=Coll([object()]), occurrences=Coll())
    base = NS(startEdit=lambda: None, finishEdit=lambda: None, name="")
    comp.features = NS(baseFeatures=NS(add=lambda: base))

    def mesh_add(path, units, feature=None):
        log["meshes"].append((Path(path).read_bytes()[80:84], units, feature is base))
        return Coll([NS(name="")])
    comp.meshBodies = NS(add=mesh_add)

    def export(opts):
        Path(opts[0]).write_bytes((ROOT / "samples" / "l_bracket.step").read_bytes())
        log["exported"].append(opts)

    def import_to(opts, target):
        assert Path(opts).read_bytes().startswith(b"ISO-10303-21") and target is comp
        comp.occurrences.items.append(NS(component=NS(name="")))
        log["imported"].append(opts)
        return True
    design = NS(activeComponent=comp, attributes=Attrs(), designType="param",
                exportManager=NS(createSTEPExportOptions=lambda p, c: (p, c), execute=export))

    class Defs:
        def itemById(self, i):
            return None

        def addButtonDefinition(self, i, name, tip, res):
            log["buttons"].append((i, name, res))
            return NS(commandCreated=NS(add=lambda h: None))
    panel = NS(controls=NS(itemById=lambda i: None, addCommand=lambda cd: NS(isPromoted=False)))
    ui = NS(messageBox=lambda m, *a: log["messages"].append(m), inputBox=lambda *a: ("1", False),
            commandDefinitions=Defs(), workspaces=NS(itemById=lambda i: NS(toolbarPanels=NS(itemById=lambda j: panel))))
    app = NS(userInterface=ui, activeProduct=design, log=lambda m: None,
             importManager=NS(createSTEPImportOptions=lambda p: p, importToTarget=import_to),
             preferences=NS(generalPreferences=NS(userLanguage=3)))
    adsk = types.ModuleType("adsk")
    adsk.core = NS(Application=NS(get=lambda: app, log=lambda *a: None), CommandEventHandler=Handler, CommandCreatedEventHandler=Handler,
                   UserLanguages=NS(JapaneseLanguage=8, ChinesePRCLanguage=0))
    adsk.fusion = NS(Design=NS(cast=lambda p: p), MeshUnits=NS(MeterMeshUnit="metre"),
                     DesignTypes=NS(ParametricDesignType="param"))
    for name, mod in (("adsk", adsk), ("adsk.core", adsk.core), ("adsk.fusion", adsk.fusion)):
        monkeypatch.setitem(sys.modules, name, mod)
    pkg = types.ModuleType("nss_fusion_addin")
    pkg.__path__ = [str(ROOT / "integrations" / "fusion" / "NovaSolverStudio")]
    monkeypatch.setitem(sys.modules, "nss_fusion_addin", pkg)
    sys.modules.pop("nss_fusion_addin.NovaSolverStudio", None)
    sys.modules.pop("nss_fusion_addin.nss_link", None)
    addin = importlib.import_module("nss_fusion_addin.NovaSolverStudio")
    monkeypatch.setattr(addin.L, "studio_program", lambda: None)
    monkeypatch.setattr(addin.L.webbrowser, "open", lambda u: None)
    return addin, design, log


def test_fusion_addin_send_and_import(studio, tmp_path, monkeypatch):
    port, _ = studio
    addin, design, log = _fake_fusion(monkeypatch, tmp_path)
    addin.run(None)
    assert [b[0] for b in log["buttons"]] == ["NovaSolverStudio_send", "NovaSolverStudio_import"]
    assert all(Path(b[2], "32x32.png").is_file() for b in log["buttons"]) and not log["messages"]
    addin.send()
    cid = addin.get_attr(design, "case")
    assert L.CASE_ID.fullmatch(cid) and addin.get_attr(design, "file") == "Bracket_1.step"
    addin.import_result()
    assert f"{cid} has no Genesis result" in log["messages"][-1]
    for settings, kind in (({"cells": 3000, "iterations": 10, "extrusion": "y"}, "step"), ({"cells": 3000, "iterations": 10}, "mesh")):
        g = C.create_case("cantilever", {}, "en")["case"]["case_id"]
        C.run_genesis(g, settings, wait_s=600, lang="en")
        t0 = time.monotonic()
        while L.genesis(port, g) is None:
            assert time.monotonic() - t0 < 900
            time.sleep(2)
        design.attributes.add("NovaSolverStudio", "case", g)
        addin.import_result()
        assert "Inserted Genesis_r_" in log["messages"][-1] and "Check the shape" in log["messages"][-1]
    assert len(log["imported"]) == 1                                    # the extruded one as a STEP body
    assert len(log["meshes"]) == 1 and log["meshes"][0][1:] == ("metre", True)   # the other in a base feature
