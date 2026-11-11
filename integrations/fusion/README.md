# NovaSolver Studio for Fusion

A Fusion add-in with two buttons under **Utilities > Add-ins** in the Design workspace. It talks only to NovaSolver
Studio on `127.0.0.1`; nothing leaves the computer.

- *Send to NovaSolver Studio*: the active component goes to Studio as STEP (with its units), so Studio keeps the real
  faces for choosing supports and loads. Studio starts if needed.
- *Import Genesis result*: after Genesis (topology optimisation) has run in Studio, the shape comes back into the same
  component: a STEP body with flat faces for an extruded part, otherwise a mesh body (in a base feature in parametric
  designs) in the component's own coordinates. The design keeps its Studio case as an attribute.

Fusion のアクティブなコンポーネントを STEP のまま NovaSolver Studio に送り、Genesis（トポロジー最適化）が作った形を同じコンポーネントに取り込むアドインです。

1. Install NovaSolver Studio (https://novasolver.jp/studio/).
2. In Studio open Help (?) > Connect other apps and click Install next to Fusion (Fusion must have run once on this
   computer). By hand: copy the `NovaSolverStudio` folder into Fusion's `API/AddIns` folder
   (Windows: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns`).
3. Restart Fusion (the add-in starts with Fusion), or start it in Utilities > Add-ins > Scripts and Add-ins.

Check the shape with an analysis in Studio before you use it.

GPL-3.0-or-later.
