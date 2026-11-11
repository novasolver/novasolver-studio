# SPDX-License-Identifier: GPL-3.0-or-later
"""FreeCAD commands: send the selected part to NovaSolver Studio, and bring the Genesis result of that case back
into the document. Studio's case id and the sent file's hash are kept in the document's Meta, so the result is
found again after FreeCAD or Studio restart."""
import re
import tempfile
from pathlib import Path

import FreeCAD
import FreeCADGui

import nss_link as L

ICONS = Path(__file__).resolve().parent / "Resources" / "icons"
META_CASE, META_SHA, META_FILE = "NovaSolverStudio_case", "NovaSolverStudio_sha256", "NovaSolverStudio_file"

TEXT = {
    "send": {"en": "Send to NovaSolver Studio", "ja": "NovaSolver Studio に送る", "zh": "发送到 NovaSolver Studio"},
    "send_tip": {"en": "Open the selected part (or the active body) in Studio as STEP, to analyse it or run Genesis",
                 "ja": "選んだ部品（またはアクティブなボディ）を STEP のまま Studio で開き、解析や Genesis に使います",
                 "zh": "将所选零件（或活动实体）以 STEP 在 Studio 中打开，用于分析或 Genesis"},
    "import": {"en": "Import Genesis result", "ja": "Genesis の結果を取り込む", "zh": "导入 Genesis 结果"},
    "import_tip": {"en": "Insert the shape Genesis made in Studio for this part (STEP for extruded parts, otherwise a mesh)",
                   "ja": "この部品について Studio の Genesis が作った形を挿入します（押し出し形状は STEP、それ以外はメッシュ）",
                   "zh": "插入 Studio 的 Genesis 为该零件生成的形状（拉伸形状为 STEP，其余为网格）"},
    "select": {"en": "Select a part (or activate a body) first.", "ja": "先に部品を選ぶか、ボディをアクティブにしてください。",
               "zh": "请先选择零件（或激活实体）。"},
    "opened": {"en": "Opened in Studio as {cid}.", "ja": "Studio で {cid} として開きました。", "zh": "已在 Studio 中打开为 {cid}。"},
    "opening": {"en": "Studio is opening the part in its window.", "ja": "Studio のウィンドウで部品を開いています。",
                "zh": "Studio 正在其窗口中打开零件。"},
    "not_running": {"en": "NovaSolver Studio is not running. Start it, then try again.",
                    "ja": "NovaSolver Studio が起動していません。起動してからもう一度実行してください。",
                    "zh": "NovaSolver Studio 未运行。请启动后重试。"},
    "no_case": {"en": "No Studio case was found for this document. Send the part first, or pick a case.",
                "ja": "この文書に対応する Studio のケースが見つかりません。先に部品を送るか、ケースを選んでください。",
                "zh": "未找到与此文档对应的 Studio 案例。请先发送零件，或选择一个案例。"},
    "no_result": {"en": "Case {cid} has no Genesis result yet. Run Genesis in Studio (Form step), then import.",
                  "ja": "ケース {cid} にはまだ Genesis の結果がありません。Studio で Genesis を実行してから取り込んでください。",
                  "zh": "案例 {cid} 还没有 Genesis 结果。请先在 Studio 中运行 Genesis，再导入。"},
    "pick": {"en": "Studio cases with a Genesis result:", "ja": "Genesis の結果があるケース：", "zh": "有 Genesis 结果的案例："},
    "inserted": {"en": "Inserted {label} ({kind}).", "ja": "{label} を挿入しました（{kind}）。", "zh": "已插入 {label}（{kind}）。"},
    "stale": {"en": "The case was changed after this Genesis run; the shape belongs to the earlier settings.",
              "ja": "この Genesis の実行後にケースが変更されています。形は変更前の設定のものです。",
              "zh": "此次 Genesis 运行后案例已被修改；该形状对应修改前的设置。"},
    "verify": {"en": "Check the shape with an analysis before you use it.", "ja": "使う前に解析で確かめてください。",
               "zh": "使用前请通过分析进行确认。"},
}


def lang():
    try:
        code = FreeCADGui.getLocale()
    except Exception:
        code = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Language", "")
    code = (code or "").lower()
    return "ja" if code.startswith(("ja", "japan")) else "zh" if code.startswith(("zh", "chinese")) else "en"


def tr(key, **kw):
    return TEXT[key][lang()].format(**kw)


def report(msg, error=False):
    (FreeCAD.Console.PrintError if error else FreeCAD.Console.PrintMessage)(f"NovaSolver Studio: {msg}\n")
    try:
        from PySide import QtGui
        box = QtGui.QMessageBox.warning if error else QtGui.QMessageBox.information
        box(FreeCADGui.getMainWindow(), "NovaSolver Studio", msg)
    except Exception:
        pass


def _meta(doc):
    try:
        return dict(doc.Meta)
    except Exception:
        return {}


def _set_meta(doc, **kw):
    try:
        doc.Meta = {**_meta(doc), **{k: v for k, v in kw.items() if v}}
    except Exception:                       # an old FreeCAD without Meta: the hash and file name still find it
        pass


class SendToStudio:
    def GetResources(self):
        return {"Pixmap": str(ICONS / "nss_send.svg"), "MenuText": tr("send"), "ToolTip": tr("send_tip")}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        import Import
        doc = FreeCAD.ActiveDocument
        objs = [o for o in FreeCADGui.Selection.getSelection() if hasattr(o, "Shape") and not o.Shape.isNull()]
        if not objs and FreeCADGui.ActiveDocument:
            body = FreeCADGui.ActiveDocument.ActiveView.getActiveObject("pdbody")
            objs = [body] if body is not None else []
        if not objs:
            report(tr("select"), error=True)
            return
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", objs[0].Label).strip("_") or "part"
        folder = Path(tempfile.gettempdir()) / "novasolver_freecad"
        folder.mkdir(exist_ok=True)
        step = folder / f"{name}.step"
        Import.export(objs, str(step))                # FreeCAD works in millimetres; Studio is told units=mm
        try:
            cid = L.send(step, "structural", lang())
        except Exception as e:
            report(str(e), error=True)
            return
        _set_meta(doc, **{META_CASE: cid, META_SHA: L.sha256(step), META_FILE: step.name})
        if not cid:                                 # Studio was starting: the case id of an earlier send no longer fits
            try:
                m = _meta(doc)
                m.pop(META_CASE, None)
                doc.Meta = m
            except Exception:
                pass
        FreeCAD.Console.PrintMessage(f"NovaSolver Studio: {tr('opened', cid=cid) if cid else tr('opening')}\n")


def _choose(cases):
    from PySide import QtGui
    items = [f"{c['title'].get(lang()) or c['title'].get('en') or c['case_id']}  ({c['case_id']})" for c in cases]
    item, ok = QtGui.QInputDialog.getItem(FreeCADGui.getMainWindow(), "NovaSolver Studio", tr("pick"), items, 0, False)
    return cases[items.index(item)] if ok and item in items else None


def _insert(doc, path, kind, label):
    before = set(o.Name for o in doc.Objects)
    if kind == "step":
        import Import
        Import.insert(str(path), doc.Name)          # Studio writes it in millimetres
    else:
        import Mesh
        m = Mesh.Mesh(str(path))
        mat = FreeCAD.Matrix()
        mat.scale(1000.0, 1000.0, 1000.0)           # Studio's STL is in metres, in the part's own coordinates
        m.transform(mat)
        obj = doc.addObject("Mesh::Feature", "Genesis")
        obj.Mesh = m
    new = [o for o in doc.Objects if o.Name not in before]
    for o in new:
        o.Label = label
        vo = getattr(o, "ViewObject", None)
        if vo is not None and hasattr(vo, "ShapeColor"):
            vo.ShapeColor = (0.96, 0.62, 0.26)
    doc.recompute()
    return new


class ImportGenesis:
    def GetResources(self):
        return {"Pixmap": str(ICONS / "nss_genesis.svg"), "MenuText": tr("import"), "ToolTip": tr("import_tip")}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        try:
            port = L.need_port()
        except L.StudioNotRunning:
            report(tr("not_running"), error=True)
            return
        meta = _meta(doc)
        try:
            found = L.find_cases(port, meta.get(META_SHA), meta.get(META_FILE), meta.get(META_CASE))
            hit = next(((c, r) for c in found if (r := L.genesis(port, c["case_id"], lang()))), None)
            if hit is None and found:
                report(tr("no_result", cid=found[0]["case_id"]), error=True)
                return
            if hit is None:                             # nothing sent from this document: offer the cases with a result
                withres = [c for c in L.list_cases(port)[:40] if L.genesis(port, c["case_id"], lang())]
                if not withres:
                    report(tr("no_case"), error=True)
                    return
                c = _choose(withres)
                if c is None:
                    return
                hit = (c, L.genesis(port, c["case_id"], lang()))
            case, res = hit
            kind, url = L.pick_file(res)
            ext = ".step" if kind == "step" else ".stl"
            path = L.download(port, url, Path(tempfile.gettempdir()) / "novasolver_freecad" /
                              f"genesis_{case['case_id']}_{res['run_id']}{ext}")
        except Exception as e:
            report(str(e), error=True)
            return
        label = f"Genesis_{res['run_id']}"
        _insert(doc, path, kind, label)
        _set_meta(doc, **{META_CASE: case["case_id"]})
        lines = [tr("inserted", label=label, kind="STEP" if kind == "step" else "mesh")]
        lines += [f"{c['label']}: {c['value']} {c['unit']}" for c in res.get("cards", [])]
        lines += [w["message"] for w in res.get("warnings", [])]
        if res.get("stale"):
            lines.append(tr("stale"))
        lines.append(tr("verify"))
        report("\n".join(lines))


def register():
    FreeCADGui.addCommand("NSS_SendToStudio", SendToStudio())
    FreeCADGui.addCommand("NSS_ImportGenesis", ImportGenesis())
    return ["NSS_SendToStudio", "NSS_ImportGenesis"]
