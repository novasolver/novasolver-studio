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

## Documentation

- Design: [`docs/DESIGN.md`](docs/DESIGN.md) · Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md) · Development notes: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
- Tests: `python -m pytest backend/tests -q`

## License

GPL-3.0 — see [`LICENSE`](LICENSE). Programs called by Studio keep their own licenses — see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

This offering is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software via
www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

Made by [NovaSolver](https://novasolver.jp) — interactive engineering simulators.
