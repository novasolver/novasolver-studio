# SPDX-License-Identifier: GPL-3.0-or-later
"""NovaSolver Studio for Blender: send the active object to NovaSolver Studio (free, runs on this computer) and check
its strength or heat flow before printing or manufacturing it.

The object (with its modifiers, in world space, in metres) is written to a temporary STL and handed to the Studio
that runs on this computer over 127.0.0.1. Studio opens it as a new case with the chosen material; faces, loads and
the solve are set up in Studio's window (or by an AI assistant through Studio's MCP server)."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty

DOWNLOAD_PAGE = "https://novasolver.jp/studio/"
CASE_ID = re.compile(r"c_\d{8}_\d{6}_[0-9a-f]{4}")
MATERIALS = [("pla", "PLA", ""), ("petg", "PETG", ""), ("abs", "ABS", ""), ("tpu", "TPU", ""), ("steel", "Steel", ""),
             ("aluminium", "Aluminium", ""), ("titanium", "Titanium", ""), ("copper", "Copper", "")]
PHYSICS = [("structural", "Strength (stress, deflection)", ""), ("thermal", "Heat (temperature)", "")]


# ---------------------------------------------------------------- where Studio is

def data_dir() -> Path:
    """Same rule as novastudio/osdirs.py: Studio writes running.json here while it runs."""
    if os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path.home()
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "NovaSolverStudio"


def running_port() -> int | None:
    try:
        port = int(json.loads((data_dir() / "running.json").read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if 1024 <= port <= 65535 else None


def studio_program(prefs) -> list[str] | None:
    """Command that starts Studio: the path in the add-on preferences, the installer's location, or the
    pip/pipx command."""
    if prefs.program and Path(prefs.program).is_file():
        return [prefs.program]
    if os.environ.get("LOCALAPPDATA"):
        exe = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "NovaSolverStudio" / "NovaSolverStudio.exe"
        if exe.is_file():
            return [str(exe)]
    cmd = shutil.which("NovaSolverStudio.exe") or shutil.which("novasolver-studio")
    return [cmd] if cmd else None


# ---------------------------------------------------------------- STL of the active object

def stl_bytes(context, obj) -> tuple[bytes, int]:
    """Binary STL of the evaluated object (modifiers applied) in world space, in metres."""
    scale = context.scene.unit_settings.scale_length or 1.0
    deps = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = ev.to_mesh()
    try:
        mesh.calc_loop_triangles()
        mw = obj.matrix_world
        verts = [(mw @ v.co) * scale for v in mesh.vertices]
        out = bytearray(b"NovaSolver Studio from Blender".ljust(80, b" "))
        out += struct.pack("<I", len(mesh.loop_triangles))
        for tri in mesh.loop_triangles:
            a, b, c = (verts[i] for i in tri.vertices)
            n = (b - a).cross(c - a)
            n = n.normalized() if n.length > 0 else n
            out += struct.pack("<12fH", n.x, n.y, n.z, a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z, 0)
        return bytes(out), len(mesh.loop_triangles)
    finally:
        ev.to_mesh_clear()


# ---------------------------------------------------------------- talking to Studio (127.0.0.1 only)

def _request(port: int, method: str, path: str, data: bytes | None = None, timeout: float = 600) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json" if method == "PATCH" else
                                          "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send(port: int, name: str, stl: bytes, physics: str, material: str, lang: str) -> str:
    q = urllib.parse.urlencode({"physics": physics, "filename": f"{name}.stl", "units": "m", "lang": lang})
    pl = _request(port, "POST", f"/api/import?{q}", stl)
    case = pl["case"]
    if physics == "structural" and "solid" in case.get("materials", {}):
        body = json.dumps({"expected_revision": case["revision"],
                           "changes": {"materials.solid.preset": material}}).encode()
        _request(port, "PATCH", f"/api/cases/{case['case_id']}?lang={lang}", body, timeout=120)
    if not CASE_ID.fullmatch(case["case_id"]):
        raise ValueError("unexpected case id")
    return case["case_id"]


def ui_lang() -> str:
    loc = bpy.app.translations.locale or ""
    return "ja" if loc.startswith("ja") else "zh" if loc.startswith("zh") else "en"


# ---------------------------------------------------------------- operator

class NOVASOLVER_OT_send(bpy.types.Operator):
    """Open the active object in NovaSolver Studio as a new analysis case"""
    bl_idname = "novasolver.send"
    bl_label = "Analyze in NovaSolver Studio"
    bl_options = {"REGISTER"}

    _thread = None
    _result: dict = {}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        st = context.scene.novasolver
        obj = context.active_object
        stl, n = stl_bytes(context, obj)
        if n == 0:
            self.report({"ERROR"}, "The object has no faces")
            return {"CANCELLED"}
        if n > 400_000:
            self.report({"WARNING"}, f"{n} triangles: Studio remeshes this, which can take a while")
        # keep a copy next to the temporary files so the user can also open it by hand
        tmp = Path(tempfile.gettempdir()) / "novasolver_blender"
        tmp.mkdir(exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", obj.name).strip("_") or "part"
        (tmp / f"{name}.stl").write_bytes(stl)

        port = running_port()
        program = studio_program(prefs)
        if port is None and program is None:
            self.report({"ERROR"}, "NovaSolver Studio is not installed (or set its location in the add-on preferences)")
            webbrowser.open(DOWNLOAD_PAGE)
            return {"CANCELLED"}
        args = (port, program, name, stl, st.physics, st.material, ui_lang())
        result = NOVASOLVER_OT_send._result = {}
        NOVASOLVER_OT_send._thread = threading.Thread(target=_work, args=(*args, result), daemon=True)
        NOVASOLVER_OT_send._thread.start()
        st.status = "Sending to NovaSolver Studio..."
        bpy.app.timers.register(_poll, first_interval=0.5)
        return {"FINISHED"}


def _work(port, program, name, stl, physics, material, lang, result):
    try:
        if port is None:                                       # start Studio and wait for its server
            subprocess.Popen(program, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True)
            t0 = time.monotonic()
            while (port := running_port()) is None:
                if time.monotonic() - t0 > 180:
                    raise TimeoutError("NovaSolver Studio did not start within 3 minutes")
                time.sleep(1)
        result["case_id"] = send(port, name, stl, physics, material, lang)
        result["port"] = port
        result["program"] = program
    except Exception as e:                                     # shown in the panel; Blender keeps running
        result["error"] = f"{type(e).__name__}: {e}"


def _poll():
    t = NOVASOLVER_OT_send._thread
    if t is not None and t.is_alive():
        return 0.5
    r = NOVASOLVER_OT_send._result
    scene = bpy.context.scene
    if "error" in r:
        scene.novasolver.status = r["error"][:200]
        return None
    cid = r.get("case_id")
    if cid:
        scene.novasolver.status = f"Opened in NovaSolver Studio ({cid})"
        if r.get("program"):
            subprocess.Popen([*r["program"], "--case", cid], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
        else:
            webbrowser.open(f"http://127.0.0.1:{r['port']}/?case={cid}")
    return None


# ---------------------------------------------------------------- UI

class NovaSolverSettings(bpy.types.PropertyGroup):
    physics: EnumProperty(name="Analysis", items=PHYSICS, default="structural")
    material: EnumProperty(name="Material", items=MATERIALS, default="pla")
    status: StringProperty(name="Status", default="")


class NOVASOLVER_PT_panel(bpy.types.Panel):
    bl_label = "NovaSolver Studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NovaSolver"

    def draw(self, context):
        st = context.scene.novasolver
        col = self.layout.column()
        col.prop(st, "physics")
        if st.physics == "structural":
            col.prop(st, "material")
        col.label(text="Units: Scene > Units (Unit Scale 0.001 = millimetres)")
        col.operator(NOVASOLVER_OT_send.bl_idname, icon="MOD_PHYSICS")
        if st.status:
            col.label(text=st.status)
        col.operator("wm.url_open", text="Get NovaSolver Studio (free)", icon="URL").url = DOWNLOAD_PAGE


class NovaSolverPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    program: StringProperty(name="NovaSolver Studio program", subtype="FILE_PATH",
                            description="NovaSolverStudio.exe, or leave empty to find it automatically")

    def draw(self, context):
        self.layout.prop(self, "program")


TRANSLATIONS = {
    "ja_JP": {
        ("*", "Analysis"): "解析",
        ("*", "Strength (stress, deflection)"): "強度（応力・たわみ）",
        ("*", "Heat (temperature)"): "熱（温度）",
        ("*", "Material"): "材料",
        ("*", "Titanium"): "チタン",
        ("*", "Steel"): "鋼",
        ("*", "Aluminium"): "アルミニウム",
        ("*", "Copper"): "銅",
        ("Operator", "Analyze in NovaSolver Studio"): "NovaSolver Studio で解析",
        ("*", "Get NovaSolver Studio (free)"): "NovaSolver Studio を入手（無料）",
        ("*", "Units: Scene > Units (Unit Scale 0.001 = millimetres)"): "単位: シーン > 単位（単位スケール 0.001 = mm）",
    },
    "zh_HANS": {
        ("*", "Analysis"): "分析",
        ("*", "Strength (stress, deflection)"): "强度（应力、变形）",
        ("*", "Heat (temperature)"): "热（温度）",
        ("*", "Material"): "材料",
        ("*", "Titanium"): "钛",
        ("*", "Steel"): "钢",
        ("*", "Aluminium"): "铝",
        ("*", "Copper"): "铜",
        ("Operator", "Analyze in NovaSolver Studio"): "在 NovaSolver Studio 中分析",
        ("*", "Get NovaSolver Studio (free)"): "获取 NovaSolver Studio（免费）",
        ("*", "Units: Scene > Units (Unit Scale 0.001 = millimetres)"): "单位：场景 > 单位（单位缩放 0.001 = 毫米）",
    },
}

CLASSES = (NovaSolverSettings, NOVASOLVER_OT_send, NOVASOLVER_PT_panel, NovaSolverPreferences)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.novasolver = bpy.props.PointerProperty(type=NovaSolverSettings)
    bpy.app.translations.register(__package__, TRANSLATIONS)


def unregister():
    bpy.app.translations.unregister(__package__)
    del bpy.types.Scene.novasolver
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
