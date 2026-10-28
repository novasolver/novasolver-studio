## NovaSolver Studio 0.4.0 (preview)

Saying which face gets which condition is how you tell a simulation what you mean. This release makes that step
fast, lets you take any step back, and lets an AI assistant see exactly the faces you picked.

### Undo and redo — for your edits and the AI's
- Ctrl+Z / Ctrl+Shift+Z (or the arrows in the top bar). One history for the GUI and the AI assistant: if the AI set
  the wrong faces, one undo takes it back ("Undid the AI's change: role of face 5 and 1 more").
- Typing a value is one step, not one per keystroke.

### Faces you can tell apart
- Faces are described by type, direction and size: "Face 9 · cylinder R5 axis Z", "Face 3 · plane −Z · 3,121 mm²".
- Face colours from the CAD file (STEP) are read; select every face of the same colour at once.

### Faster selection
- Select, then expand: same shape, connected (tangent) faces such as a hole with its fillets, faces facing the same
  way, coaxial cylinders (click again for the same radius only), invert.
- Ctrl+drag box selection of the visible faces.
- Hide faces (H, show all with Alt+H) or see through the part (X) to reach inner and rear faces.
- Save a selection as a named group ("bolt seats"); click the group to select it again. An AI can use the name too.
- Several selected faces share one set of value fields.

### Your selection, visible to the AI (MCP)
- New tool `get_gui_selection`: select faces in the 3D view, then say "fix these" or 「選んだ面を固定して」. The
  assistant reads exactly those faces, with their type, direction, radius, neighbours and current role.
- `render_view` with `quantity="faces"` draws the part with face numbers and one colour per condition, so the
  assistant can show you the setup and ask before running. `highlight` marks the faces it is about to change.
- New tool `undo_change`. Face descriptors (normal, axis, radius, neighbouring faces) in `import_geometry` and
  `describe_case`; `boundaries.@<group>.role` sets a whole named group. 23 tools in all.

### Fewer meaningless runs
- A heat case with convection but no heat input now warns that the whole part would just sit at the ambient
  temperature.

---

## NovaSolver Studio 0.4.0（プレビュー版）

「どの面に何をするか」は、解析で人の意図を伝えるいちばん大事な操作です。このリリースで、その操作が速くなり、どの一手も戻せるようになり、選んだ面を AI がそのまま読めるようになりました。

### 元に戻す・やり直す（人の操作も AI の変更も）
- Ctrl+Z / Ctrl+Shift+Z（上部の矢印ボタンでも可）。画面と AI で履歴は1本です。AI が違う面に条件を付けても、1回で戻せます（「AIの変更を元に戻しました：面 5ほか1面の役割」）。
- 数値の入力は、1文字ごとではなく1回の操作として記録します。

### 見分けられる面
- 面を種類・向き・大きさで表示します：「面 9 · 円筒面 R5 軸Z」「面 3 · 平面 -Z · 3,121 mm²」。
- CAD（STEP）で付けた面の色を読み込みます。同じ色の面をまとめて選べます。

### 速い選択
- 選んでから広げる：同じ形、つながった面（穴とそのフィレットなど）、同じ向きの面、同じ軸の円筒（もう一度押すと同じ半径だけ）、選択の反転。
- Ctrl+ドラッグで、見えている面を範囲選択。
- 面を隠す（H、すべて表示は Alt+H）・透かして見る（X）で、内側や裏側の面も選べます。
- 選択を名前付きグループとして保存（「ボルト座面」など）。クリックで選び直せ、AI もその名前で指定できます。
- 複数の面を選ぶと、値の入力欄は1つにまとまります。

### 選んだ面を AI が読める（MCP）
- 新ツール `get_gui_selection`：3D ビューで面を選んで「選んだ面を固定して」と頼むと、AI はその面を種類・向き・半径・隣の面・今の条件つきで受け取ります。
- `render_view` の `quantity="faces"`：面番号と条件ごとの色で形状を描き、AI が計算前に「この設定でよいか」を見せて確認できます。`highlight` でこれから変える面を示せます。
- 新ツール `undo_change`。`import_geometry` と `describe_case` に面の情報（向き・軸・半径・隣の面）を追加し、`boundaries.@<グループ名>.role` でグループ全体を設定できます。ツールは全部で 23 個です。

### 意味のない計算を減らす
- 対流だけで熱の入力がない熱解析は、「全体が周囲と同じ温度になります」と警告します。
