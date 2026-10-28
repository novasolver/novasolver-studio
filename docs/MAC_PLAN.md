# macOS (and Linux) support — assessment and plan (2026-10-28)

**Conclusion.** It is feasible, and most of it is cheap. The expensive part is optional: a signed, notarized .app.

**Recommended order:**

1. Make the code platform-neutral.
2. Publish Studio on PyPI, so that `uvx novasolver-studio` works on macOS and Linux with no Gatekeeper problem.
3. Add a macOS .mcpb.
4. Only if demand shows up, ship a notarized .app/.dmg (Apple Developer Program, 99 USD/year).

**Why Mac at all.** Many Claude Desktop users are on macOS. The MCP side of Studio (an AI driving the solver) is its
distinctive feature, so a Mac user who installs MCP servers is a real target. CAE practitioners are mostly on Windows,
which stays the primary platform.

## 1. Dependencies on macOS (Apple Silicon)

| Part | macOS arm64 | Note |
|---|---|---|
| Python stack (numpy, scipy, pyamg, FastAPI, mcp, matplotlib, psutil) | wheels exist | — |
| gmsh 4.15.2 | `macosx_12_0_arm64` and `macosx_10_15_x86_64` wheels on PyPI | needs macOS 12 or later |
| pymeshlab 2025.7.post1 | `macosx_11_0_arm64` wheels for cp310–cp314 | — |
| Built-in FEM (structural / thermal / electric) | pure numpy / scipy / pyamg | works as is: the core of Studio needs nothing extra |
| CalculiX | community Homebrew tap `costerwi/calculix` (ccx 2.22, tested on M2) | no official binary; Studio must find `ccx` on PATH or Homebrew paths |
| OpenFOAM | `gerlero/openfoam-app` (ESI line v2606, native Apple Silicon, macOS 14+, Homebrew `brew install gerlero/openfoam/openfoam`) | Intel Macs are capped at v2506. The OpenFOAM Foundation's own route on macOS is a Linux VM (Multipass). |
| Frontend | browser UI | no change |

## 2. Windows-specific code to make neutral (inventory of `backend/novastudio`)

| Where | What | Change |
|---|---|---|
| `config.py` | `LOCALAPPDATA` for runs / solvers / lock; `Documents` workspace for the frozen app | per-OS data dir: Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support/NovaSolverStudio`, Linux `$XDG_DATA_HOME`. Workspace on macOS outside `~/Documents`, or the first access triggers a privacy prompt: `~/NovaSolverStudio/workspace`, or the Application Support folder plus an "open folder" button. |
| `run_worker._acquire_solver_slot` | lock under `LOCALAPPDATA` | same per-OS data dir |
| `config.py` CalculiX lookup | `ccx_static.exe`, … | also `ccx` / `ccx_2.22` on PATH and in `/opt/homebrew/bin` |
| `config.py` OpenFOAM lookup | `blockMesh.exe`; msmpi.dll required | macOS: detect `/Applications/OpenFOAM-v*.app`, or the `openfoam` command. Run tools through the app's environment script (`…/Contents/Resources/etc/openfoam -c "<cmd>"`) instead of calling the binaries directly. No msmpi. |
| `flow3d.py` (4×), `external.py` (2×) | `f"{name}.exe"` | one helper `foam_cmd(name, args)` that adds `.exe` on Windows or wraps with the environment script on macOS/Linux |
| `external.py`, `geometry.py` | `CREATE_NO_WINDOW` | already `getattr(..., 0)`: fine |
| `jobs.py` | process-group flags | already branches on `os.name`; POSIX uses `start_new_session`: fine |
| `fem_tet10.committable_bytes` | Windows commit limit | the non-Windows branch exists, but macOS swap grows on demand, so free RAM plus swap under-estimates. Use `virtual_memory().available` plus a margin, or refuse only above total RAM. |
| `commands.environment_check` | messages mention `ccx.exe` | per-OS wording |
| `build_release.ps1`, `prune_bundle.ps1`, `make_mcpb.py` | Windows build only | a separate macOS build job (below) |

Estimated effort for sections 2 and 3: about 2–4 working days, most of it in the OpenFOAM wrapper and in testing.

## 3. Distribution options

| Option | User experience | Cost / risk |
|---|---|---|
| **A. PyPI package** `novasolver-studio` (`uvx novasolver-studio` / `pipx install`) | one terminal command; MCP config `uvx novasolver-studio mcp`. The same package works on Linux. | No signing needed: no Gatekeeper prompt, because nothing is downloaded as an app. Needs the frontend `dist` inside the wheel and a `serve` entry point (both exist in source form). **Recommended first.** |
| B. macOS .mcpb for Claude Desktop | one-click install in Claude Desktop | Declare `compatibility.platforms` and `server.mcp_config.platform_overrides.darwin`. The binary inside must be arm64 and at least ad-hoc signed. Gatekeeper behaviour of an unsigned bundled binary is untested. |
| C. Notarized .app / .dmg | double-click like Windows | Apple Developer Program 99 USD/year, plus hardened runtime and entitlements for PyInstaller and gmsh/OCC dylibs. Without notarization, macOS 15 makes users go through System Settings → Privacy & Security → "Open Anyway": acceptable for a preview, poor for general users. |

**MCP Registry.** `server.json` can list a `pypi` package next to the current `mcpb` one, so registry clients on any
OS get an install path.

## 4. Testing without a Mac

There is no Mac in this setup. Use GitHub Actions instead:

- `macos-14` / `macos-15` are arm64 runners, free for public repositories. Add `ubuntu-latest` too.
- Run the backend test suite there. Skip OpenFOAM tests unless the runner installs the app. CalculiX installs from the tap.
- Add a smoke test of `uvx novasolver-studio mcp` with `tools/list` and one built-in solve.
- UI checks run in a browser, so the frontend needs no Mac-specific testing beyond fonts. CJK fonts: matplotlib
  rendering needs a Japanese/Chinese font on macOS (Hiragino or PingFang are present). Check that `results.py` font
  lookup finds them.

**Remaining risk.** Nobody has run it on a real Mac. Ask one or two Mac users (Discord) to try a preview before
announcing it.

## 5. Proposed steps

1. **0.4.x**: platform-neutral paths and solver lookup (§2), and CI on macOS and Linux with the built-in solvers.
2. PyPI release plus `server.json` pypi entry. Site: a "macOS / Linux (preview)" section with the `uvx` command and
   CalculiX/OpenFOAM install notes.
3. macOS .mcpb (arm64), built in CI.
4. Notarized .app only after real Mac usage appears. **Requires the operator to join the Apple Developer Program**
   under the business name (outside Claude's remit).

Sources:

- PyPI: https://pypi.org/simple/gmsh/
- PyPI: https://pypi.org/simple/pymeshlab/
- https://github.com/gerlero/openfoam-app
- https://calculix.discourse.group/t/homebrew-packages-for-ccx-and-cgx-for-macos/2729
- https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
- OpenFOAM.org macOS page: https://openfoam.org/download/12-macos/
