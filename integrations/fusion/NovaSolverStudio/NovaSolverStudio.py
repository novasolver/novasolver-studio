# SPDX-License-Identifier: GPL-3.0-or-later
"""Fusion add-in: send the active component to NovaSolver Studio as STEP, and bring the Genesis result of that case
back into the same component (a STEP body for extruded parts, otherwise a mesh body in its own coordinates).
Buttons: Utilities > Add-ins panel of the Design workspace. Studio's case id and the sent file's
hash are kept as attributes of the design, so the result is found again after a restart."""
import re
import tempfile
import traceback
from pathlib import Path

import adsk.core
import adsk.fusion

from . import nss_link as L

HERE = Path(__file__).resolve().parent
GROUP = "NovaSolverStudio"
PANEL_ID = "SolidScriptsAddinsPanel"            # Utilities > ADD-INS in the Design workspace
WORKSPACE_ID = "FusionSolidEnvironment"
_handlers = []

TEXT = {
    "send": {"en": "Send to NovaSolver Studio", "ja": "NovaSolver Studio に送る", "zh": "发送到 NovaSolver Studio"},
    "send_tip": {"en": "Open the active component in Studio as STEP, to analyse it or run Genesis",
                 "ja": "アクティブなコンポーネントを STEP のまま Studio で開き、解析や Genesis に使います",
                 "zh": "将活动组件以 STEP 在 Studio 中打开，用于分析或 Genesis"},
    "import": {"en": "Import Genesis result", "ja": "Genesis の結果を取り込む", "zh": "导入 Genesis 结果"},
    "import_tip": {"en": "Insert the shape Genesis made in Studio for this component (STEP for extruded parts, otherwise a mesh)",
                   "ja": "このコンポーネントについて Studio の Genesis が作った形を挿入します（押し出し形状は STEP、それ以外はメッシュ）",
                   "zh": "插入 Studio 的 Genesis 为该组件生成的形状（拉伸形状为 STEP，其余为网格）"},
    "no_design": {"en": "Open a design first.", "ja": "先にデザインを開いてください。", "zh": "请先打开设计。"},
    "empty": {"en": "The active component has no bodies.", "ja": "アクティブなコンポーネントにボディがありません。",
              "zh": "活动组件中没有实体。"},
    "opened": {"en": "Opened in Studio as {cid}.", "ja": "Studio で {cid} として開きました。", "zh": "已在 Studio 中打开为 {cid}。"},
    "opening": {"en": "Studio is opening the part in its window.", "ja": "Studio のウィンドウで部品を開いています。",
                "zh": "Studio 正在其窗口中打开零件。"},
    "not_running": {"en": "NovaSolver Studio is not running. Start it, then try again.",
                    "ja": "NovaSolver Studio が起動していません。起動してからもう一度実行してください。",
                    "zh": "NovaSolver Studio 未运行。请启动后重试。"},
    "no_case": {"en": "No Studio case was found for this design. Send the component first.",
                "ja": "このデザインに対応する Studio のケースが見つかりません。先にコンポーネントを送ってください。",
                "zh": "未找到与此设计对应的 Studio 案例。请先发送组件。"},
    "no_result": {"en": "Case {cid} has no Genesis result yet. Run Genesis in Studio, then import.",
                  "ja": "ケース {cid} にはまだ Genesis の結果がありません。Studio で Genesis を実行してから取り込んでください。",
                  "zh": "案例 {cid} 还没有 Genesis 结果。请先在 Studio 中运行 Genesis，再导入。"},
    "pick": {"en": "Studio cases with a Genesis result. Number to import:", "ja": "Genesis の結果があるケース。取り込む番号：",
             "zh": "有 Genesis 结果的案例。要导入的编号："},
    "inserted": {"en": "Inserted {label} ({kind}).", "ja": "{label} を挿入しました（{kind}）。", "zh": "已插入 {label}（{kind}）。"},
    "stale": {"en": "The case was changed after this Genesis run; the shape belongs to the earlier settings.",
              "ja": "この Genesis の実行後にケースが変更されています。形は変更前の設定のものです。",
              "zh": "此次 Genesis 运行后案例已被修改；该形状对应修改前的设置。"},
    "verify": {"en": "Check the shape with an analysis before you use it.", "ja": "使う前に解析で確かめてください。",
               "zh": "使用前请通过分析进行确认。"},
}


def app():
    return adsk.core.Application.get()


def lang():
    try:
        u = app().preferences.generalPreferences.userLanguage
        if u == adsk.core.UserLanguages.JapaneseLanguage:
            return "ja"
        if u in (getattr(adsk.core.UserLanguages, "ChineseSimplifiedLanguage", -1),
                 getattr(adsk.core.UserLanguages, "ChineseLanguage", -1)):
            return "zh"
    except Exception:
        pass
    return "en"


def tr(key, **kw):
    return TEXT[key][lang()].format(**kw)


def say(msg):
    app().userInterface.messageBox(msg, "NovaSolver Studio")


def design():
    return adsk.fusion.Design.cast(app().activeProduct)


def get_attr(d, name):
    a = d.attributes.itemByName(GROUP, name)
    return a.value if a else None


def set_attr(d, **kw):
    for k, v in kw.items():
        if v:
            d.attributes.add(GROUP, k, v)          # updates the value when it is already there


def send():
    d = design()
    if d is None:
        return say(tr("no_design"))
    comp = d.activeComponent
    if comp.bRepBodies.count == 0 and comp.occurrences.count == 0:
        return say(tr("empty"))
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", comp.name).strip("_") or "part"
    folder = Path(tempfile.gettempdir()) / "novasolver_fusion"
    folder.mkdir(exist_ok=True)
    step = folder / f"{name}.step"
    em = d.exportManager
    em.execute(em.createSTEPExportOptions(str(step), comp))      # the STEP carries its units; Studio reads them
    cid = L.send(step, "structural", lang())
    set_attr(d, case=cid, sha256=L.sha256(step), file=step.name)
    app().log(f"NovaSolver Studio: {tr('opened', cid=cid) if cid else tr('opening')}")


def _choose(cases):
    lines = [f"{i + 1}. {c['title'].get(lang()) or c['title'].get('en') or c['case_id']} ({c['case_id']})"
             for i, c in enumerate(cases)]
    value, cancelled = app().userInterface.inputBox(tr("pick") + "\n" + "\n".join(lines), "NovaSolver Studio", "1")
    if cancelled or not value.strip().isdigit() or not 1 <= int(value) <= len(cases):
        return None
    return cases[int(value) - 1]


def _insert(d, comp, path, kind, label):
    if kind == "step":
        im = app().importManager
        im.importToTarget(im.createSTEPImportOptions(str(path)), comp)   # written in millimetres
        occ = comp.occurrences.item(comp.occurrences.count - 1)
        occ.component.name = label
        return
    units = adsk.fusion.MeshUnits.MeterMeshUnit                        # Studio's STL is in metres, part coordinates
    if d.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base = comp.features.baseFeatures.add()
        base.startEdit()
        bodies = comp.meshBodies.add(str(path), units, base)
        base.finishEdit()
        base.name = label
    else:
        bodies = comp.meshBodies.add(str(path), units)
    for i in range(bodies.count):
        bodies.item(i).name = label


def import_result():
    d = design()
    if d is None:
        return say(tr("no_design"))
    try:
        port = L.need_port()
    except L.StudioNotRunning:
        return say(tr("not_running"))
    found = L.find_cases(port, get_attr(d, "sha256"), get_attr(d, "file"), get_attr(d, "case"))
    hit = None
    for c in found:
        r = L.genesis(port, c["case_id"], lang())
        if r:
            hit = (c, r)
            break
    if hit is None and found:
        return say(tr("no_result", cid=found[0]["case_id"]))
    if hit is None:
        withres = [(c, r) for c in L.list_cases(port)[:40] if (r := L.genesis(port, c["case_id"], lang()))]
        if not withres:
            return say(tr("no_case"))
        c = _choose([c for c, _ in withres])
        if c is None:
            return
        hit = next(x for x in withres if x[0] is c)
    case, res = hit
    kind, url = L.pick_file(res)
    path = L.download(port, url, Path(tempfile.gettempdir()) / "novasolver_fusion" /
                      f"genesis_{case['case_id']}_{res['run_id']}{'.step' if kind == 'step' else '.stl'}")
    label = f"Genesis_{res['run_id']}"
    _insert(d, d.activeComponent, path, kind, label)
    set_attr(d, case=case["case_id"])
    lines = [tr("inserted", label=label, kind="STEP" if kind == "step" else "mesh")]
    lines += [f"{c['label']}: {c['value']} {c['unit']}" for c in res.get("cards", [])]
    lines += [w["message"] for w in res.get("warnings", [])]
    if res.get("stale"):
        lines.append(tr("stale"))
    lines.append(tr("verify"))
    say("\n".join(lines))


class _Run(adsk.core.CommandEventHandler):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def notify(self, args):
        try:
            self.fn()
        except Exception as e:
            app().log(traceback.format_exc())
            say(str(e))


class _Created(adsk.core.CommandCreatedEventHandler):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def notify(self, args):
        h = _Run(self.fn)
        args.command.execute.add(h)
        _handlers.append(h)


COMMANDS = (("NovaSolverStudio_send", "send", "send_tip", "send", send),
            ("NovaSolverStudio_import", "import", "import_tip", "genesis", import_result))


def run(context):
    try:
        ui = app().userInterface
        panel = ui.workspaces.itemById(WORKSPACE_ID).toolbarPanels.itemById(PANEL_ID)
        for cid, name, tip, icon, fn in COMMANDS:
            old = ui.commandDefinitions.itemById(cid)
            if old:
                old.deleteMe()
            cd = ui.commandDefinitions.addButtonDefinition(cid, tr(name), tr(tip), str(HERE / "resources" / icon))
            h = _Created(fn)
            cd.commandCreated.add(h)
            _handlers.append(h)
            if panel and not panel.controls.itemById(cid):
                panel.controls.addCommand(cd).isPromoted = True
    except Exception:
        app().userInterface.messageBox("NovaSolver Studio add-in failed to start:\n" + traceback.format_exc())


def stop(context):
    try:
        ui = app().userInterface
        panel = ui.workspaces.itemById(WORKSPACE_ID).toolbarPanels.itemById(PANEL_ID)
        for cid, *_ in COMMANDS:
            if panel and panel.controls.itemById(cid):
                panel.controls.itemById(cid).deleteMe()
            if ui.commandDefinitions.itemById(cid):
                ui.commandDefinitions.itemById(cid).deleteMe()
        _handlers.clear()
    except Exception:
        pass
