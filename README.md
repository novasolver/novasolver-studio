# NovaSolver Studio

**Open-source engineering simulation you can trust — structural, thermal and flow — operable by you or by your AI assistant.**
**構造・熱・流れを解く、オープンソースの解析ソフト。画面からも、AI アシスタント（MCP）からも操作できます。**

> Early preview (v0.x). Every result comes with a clear status: **ran → converged → verified**.
> 開発中のプレビュー版です。結果には常に「実行できた → 収束した → 検証済み」の判定がつきます。

## What it does / できること

| Analysis | Geometry | Quick preview (built-in, seconds) | Final solve | Verification |
|---|---|---|---|---|
| Structural (linear static) | templates · import STEP / IGES / BREP | quadratic tetrahedral FEM | CalculiX | beam theory, Heywood Kt, mesh convergence (GCI) |
| Thermal (steady conduction) | templates · import | quadratic tetrahedral FEM | CalculiX | Fourier's law, fin theory, GCI |
| Internal flow | templates · import | 2D cavity (built-in) | OpenFOAM® | Ghia (cavity), Poiseuille, mass balance |
| Flow around a body | import | — | OpenFOAM® (snappyHexMesh + wall layers) | sphere drag vs Schiller–Naumann (+0.3%) |
| Water cooling (conjugate heat transfer) | import (2+ bodies) | — | OpenFOAM® (chtMultiRegionSimpleFoam) | heat balance (0.03%) |

- **Verified, not just "it ran"** — every template is checked against an analytic or literature reference; imported
  shapes are checked by an automatic mesh-convergence study (Roache GCI).
- **Warnings that matter** — e.g. stress above yield: the linear result does not hold, even if "verified".
- **Japanese / English / Chinese** UI, light & dark.
- **MCP server** with typed tools: create or import a case, set conditions, run, check convergence, verify, render.
  No shell or code-execution tool. Your AI's edits appear live in the GUI.

## Quick start (developers) / 開発者向けの起動手順

```bash
python -m venv .venv
.venv\Scripts\python -m pip install "mcp>=2.3,<3" fastapi "uvicorn[standard]" numpy scipy matplotlib gmsh meshio psutil pyamg pymeshlab zstandard pytest
cd frontend && npm install && npm run build && cd ..
cd backend
set PYTHONPATH=%CD%
..\.venv\Scripts\python -m novastudio serve        # open http://127.0.0.1:8765
```

Solvers are found automatically when installed (without them, the built-in preview solvers still work):

- **CalculiX**: put `ccx_static.exe` under `solvers/calculix/` or set `NOVASTUDIO_CCX`.
- **OpenFOAM** (ESI Windows MinGW build): install to `%LOCALAPPDATA%\NovaSolverStudio\solvers\openfoam` (an ASCII-only
  path) or set `NOVASTUDIO_OPENFOAM`. Put Microsoft MPI's `msmpi.dll` in `%LOCALAPPDATA%\NovaSolverStudio\solvers\msmpi`.

## Use it from an AI assistant (MCP) / AI アシスタントから使う

**Easiest (Claude Desktop and other MCPB-aware apps):** download `novasolver-studio-<version>-win64.mcpb` from
[Releases](https://github.com/novasolver/novasolver-studio/releases) and open it — the app installs it as an extension.
Also listed in the [MCP Registry](https://registry.modelcontextprotocol.io/) as `io.github.novasolver/novasolver-studio`.

**With the downloaded zip:** point any MCP client at the exe.

```json
{
  "mcpServers": {
    "novasolver-studio": {
      "command": "C:\\path\\to\\NovaSolverStudio\\NovaSolverStudio.exe",
      "args": ["mcp"]
    }
  }
}
```

**From source:**

```json
{
  "mcpServers": {
    "novasolver-studio": {
      "command": "<studio>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "novastudio", "mcp"],
      "env": { "PYTHONPATH": "<studio>\\backend" }
    }
  }
}
```

Then ask, for example: *"Import bracket.step, fix the bottom face, push 500 N on the top face, run it and tell me
whether the result is verified."*

## Electromagnetics (0.3) / 電磁気

The built-in tet10 solver now computes electrostatic potential, electric field and electrode charge, or DC current
with optional steady Joule heating. STEP assemblies can assign a dielectric or conductor to each body.
Three editable templates include analytic checks: **capacitor** against εA/d, **coax** against 2πεL/ln(b/a),
and **busbar** against L/(σA) and the temperature rise σΔV²/(8k) with both ends cooled.

内蔵 FEM で静電場・電流・ジュール発熱による温度を計算できます。平行平板コンデンサ・同軸ケーブル・銅母線の
3 テンプレートには解析解との比較があり、任意形状ではメッシュ収束を確認できます。

## Share face selection with an AI (0.4) / 選んだ面をAIと共有する

Select faces in the boundaries viewport, then ask “fix the faces I selected” or “put 500 N here”.
The assistant reads `get_gui_selection`, shows a numbered `render_view(quantity="faces", highlight=[...])`
to confirm the setup, and applies conditions through `update_case`. GUI and AI changes share one Undo/Redo
history. Ctrl+Z undoes the latest change by either of you; Ctrl+Shift+Z or Ctrl+Y redoes it.
Named face groups can be reused with `boundaries.@<group>.role` and other boundary fields.

画面で面を選んでから「選んだ面を固定して」のように頼めます。AIが選択内容を読み取り、面番号付きの画像で
確認してから条件を設定します。画面とAIの変更は共通の履歴に残り、どちらの変更も元に戻せます。
Hで選択した面を隠し、Alt+Hですべて表示。Ctrl+ドラッグで矩形選択、Xで透過表示を切り替えます。

在视图中选择面后，可以说“固定我选中的面”。AI会读取选择内容，用带面编号的图片确认设置，再应用边界条件。
界面与AI共用撤销和重做历史，双方的更改都可以撤销。面组可以保存并重复使用。

## Documentation

- Design: [`docs/DESIGN.md`](docs/DESIGN.md) · Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md) · Development notes: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- Tests: `python -m pytest backend/tests -q`

## License

GPL-3.0 — see [`LICENSE`](LICENSE). Programs called by Studio keep their own licenses — see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

This offering is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via
www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

Made by [NovaSolver](https://novasolver.jp) — interactive engineering simulators.
