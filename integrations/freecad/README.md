# NovaSolver Studio for FreeCAD

Two ways to use NovaSolver Studio from FreeCAD. Both talk only to Studio on `127.0.0.1`; nothing leaves the computer.

**Workbench `NovaSolverStudio/`** (FreeCAD 0.21 or later, Studio 0.7.7 or later)

- *Send to NovaSolver Studio*: the selected part (or the active body) goes to Studio as STEP, so Studio keeps the real
  faces (planes, cylinders, fillets) for choosing supports and loads. Studio starts if needed.
- *Import Genesis result*: after Genesis (topology optimisation) has run in Studio, the shape comes back into the same
  document: a STEP solid with flat faces for an extruded part, otherwise the smoothed mesh, in the part's own
  coordinates (millimetres). The document remembers its Studio case, also after a restart.

**Macro `NovaSolverStudio.FCMacro`**: the send step alone, for a toolbar button.

FreeCAD で選んだ部品を STEP のまま NovaSolver Studio に送り、Studio の Genesis（トポロジー最適化）が作った形を同じ文書に取り込めます。押し出し形状は平らな面の STEP ソリッド、それ以外は滑らかにしたメッシュで、元の部品と同じ座標（mm）に入ります。

1. Install NovaSolver Studio (https://novasolver.jp/studio/).
2. Easiest: in Studio open Help (?) > Connect other apps and click Install next to FreeCAD. It copies the workbench into
   FreeCAD's user `Mod` folder and the macro into the user macro folder; restart FreeCAD and pick *NovaSolver Studio* in
   the workbench list. By hand: copy the `NovaSolverStudio` folder into the `Mod` folder shown by
   `FreeCAD.getUserAppDataDir()` in FreeCAD's Python console.
3. Select the part, *Send to NovaSolver Studio*, set supports and loads and run Genesis in Studio, then
   *Import Genesis result*.

Check the shape with an analysis in Studio before you use it.

GPL-3.0-or-later.
