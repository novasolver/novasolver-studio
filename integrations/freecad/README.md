# NovaSolver Studio for FreeCAD

A FreeCAD macro that sends the selected part (or the active body) to NovaSolver Studio as STEP, so Studio keeps the
real faces (planes, cylinders, fillets) for choosing supports and loads. Studio starts if needed and opens the part
as a new case. The macro talks only to Studio on `127.0.0.1`.

FreeCAD で選んだ部品（またはアクティブなボディ）を STEP のまま NovaSolver Studio に送るマクロです。

1. Install NovaSolver Studio (https://novasolver.jp/studio/).
2. FreeCAD: Macro > Macros… shows the user macro folder. Copy `NovaSolverStudio.FCMacro` there.
3. Select the part and run the macro (or add it to a toolbar: Tools > Customize > Macros).

Analysis type: edit `PHYSICS = "structural"` at the top (`"thermal"` also works), or change it in Studio.

GPL-3.0-or-later.
