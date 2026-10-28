# SPEC — Studio 0.4.1: runs on macOS and Linux, installable from PyPI

Owner: Claude (spec, acceptance). Implementer: Codex. Branch `mac` (git worktree `..\studio_mac`).
Background and the dependency survey: `docs/MAC_PLAN.md` (read it first). This spec covers its steps 1 and 2. The
Windows app must keep working exactly as today.

## 0. Ground rules

- **Where to work.** Work only inside the worktree. Do not touch `release/`, `workspace/`, `marketing/`, `solvers/`,
  `.venv`.
- **Style.** Read the code before changing it and match it: short "why" comments, the same naming.
- **No behaviour change on Windows.** No new runtime dependency for the Windows build. `platformdirs` is acceptable
  only if you find it already installed; otherwise write the small helper yourself.
- **Tests.**
  - The full suite (`backend/tests`) must pass on Windows.
  - Tests that need Windows binaries must be marked or skipped cleanly on other OSes.
  - Run with the python at `E:\03_サイト構築\NovaSolver\studio\.venv\Scripts\python.exe`, with
    `PYTHONPATH=<worktree>\backend` and `LOCALAPPDATA=<worktree>\.tmp` (never commit `.tmp`).
- **Commits.** Small commits on `mac`, author `NovaSolver <info@novasolver.jp>`, trailer
  `Co-Authored-By: Codex <noreply@openai.com>`. Do not push. If git refuses (sandbox), leave the work uncommitted and
  say so.
- **No Mac here.** You cannot run macOS. Everything macOS-specific must be:
  1. written so that it can be tested on Windows by monkeypatching `sys.platform`, paths and `shutil.which`;
  2. exercised in CI (§4).

## 1. Per-OS locations (one helper, used everywhere)

Add `novastudio/platform.py` (or extend `config.py` if that reads better) with:

| function | Windows (unchanged) | macOS | Linux |
|---|---|---|---|
| `data_dir()`: runs, solver lock, downloaded solvers | `%LOCALAPPDATA%\NovaSolverStudio` | `~/Library/Application Support/NovaSolverStudio` | `$XDG_DATA_HOME/NovaSolverStudio`, else `~/.local/share/NovaSolverStudio` |
| `default_workspace()` (frozen app or installed package) | `~\Documents\NovaSolverStudio\workspace` (today) | `~/NovaSolverStudio/workspace`. Not `~/Documents`, which triggers a privacy prompt for unsigned apps. | `~/NovaSolverStudio/workspace` |

- Keep `NOVASTUDIO_WORKSPACE` overriding the workspace.
- Keep `LOCALAPPDATA` overriding the data dir on every OS: tests rely on it, so read it first if it is set.
- Replace every direct `LOCALAPPDATA` use: `config.py` (runs, OpenFOAM default location) and
  `run_worker._acquire_solver_slot`.
- A source checkout keeps today's `studio/workspace`.
- The `pip`/`uvx` install is a third mode besides "frozen" and "source checkout": it is not frozen and has no
  `studio/` folder around it. Detect it (for example the package is under `site-packages`) and use
  `default_workspace()` there.

## 2. Solvers on macOS / Linux

**CalculiX.**

- Today the lookup uses `ccx_static.exe` etc.
- On macOS and Linux, look for `ccx`, `ccx_2.22`, `ccx_2.21` on `PATH` (`shutil.which`). On macOS also look in
  `/opt/homebrew/bin` and `/usr/local/bin`.
- `NOVASTUDIO_CCX` still wins.
- `environment_check` messages per OS:
  - Windows: today's text
  - macOS: `brew install costerwi/calculix/calculix-ccx` (tap from MAC_PLAN)
  - Linux: `apt install calculix-ccx` / the distro package
- All three in ja/en/zh.

**OpenFOAM.**

- **Windows.** Keep the ESI Windows build with msmpi exactly as today.
- **macOS.** Detect `gerlero/openfoam-app`: `/Applications/OpenFOAM-v*.app` (newest `vNNNN`), or the `openfoam`
  command on `PATH`.
  - Run every OpenFOAM tool through the app's environment script: `<app>/Contents/Resources/etc/openfoam -c "<tool> <args>"`.
  - No msmpi.
- **Linux.** Detect `/usr/lib/openfoam/openfoam*/etc/bashrc` (ESI packages) or `$WM_PROJECT_DIR`.
  - Run tools with `bash -c 'source <bashrc> && <tool> <args>'`.
  - No msmpi.
- **One helper.** Introduce one helper, e.g. `config.foam_argv(foam, tool, args) -> list[str]`, and use it in place of
  every `str(Path(foam["bin"]) / f"{name}.exe")` in `flow3d.py` (4 places) and `external.py` (2 places). Quote
  arguments safely (`shlex.join` for the POSIX shells). Paths with spaces and non-ASCII must work.
- **`environment_check` messages per OS.**
  - macOS: `brew install gerlero/openfoam/openfoam` (Apple Silicon, macOS 14+)
  - Linux: openfoam.com packages
- **Keep the rest.** Keep the `available` logic and the messages agents see.

**Memory check (`fem_tet10.committable_bytes`).**

- macOS grows swap on demand, so free RAM plus swap under-estimates what can be allocated. On macOS return
  `virtual_memory().available + 0.5 * total` (a generous bound: the check is there to catch the impossible, not to refuse
  borderline runs), and keep the existing Linux branch.
- Document why in a comment.
- Unit-test both branches by monkeypatching `sys.platform` and psutil.

**Other.**

- `CREATE_NO_WINDOW` and process groups already branch on `os.name`: verify, do not rewrite.
- Matplotlib fonts in `results.py`: add the macOS CJK fonts `Hiragino Sans` / `Hiragino Kaku Gothic ProN` (ja) and
  `PingFang SC` (zh) to the preference lists. Add the Linux `Noto Sans CJK JP/SC` fonts.
- Search the backend for any remaining `.exe`, `\\`, `win32`, `LOCALAPPDATA`, `Documents`. Each one must be correct
  on all three OSes or guarded.

## 3. PyPI package

- **`pyproject.toml`** at the repository root.
  - Distribution name `novasolver-studio`; import package `novastudio`, from `backend/novastudio`. Version read from
    `novastudio/__init__.py`.
  - Licence GPL-3.0-or-later (match `LICENSE`). Python `>=3.10`.
  - Dependencies, with lower bounds at the versions in use: numpy, scipy, pyamg, gmsh, pymeshlab, fastapi,
    uvicorn[standard], mcp, matplotlib, psutil, pydantic, python-multipart, websockets, anyio, meshio, zstandard.
    Read the imports to confirm the list; do not add anything not imported.
  - Console scripts: `novasolver-studio = novastudio.__main__:main` and `novastudio = novastudio.__main__:main`.
    `novasolver-studio` with no argument starts the GUI server and opens the browser, like the Windows exe.
    `novasolver-studio mcp` is the stdio MCP server.
- **The built frontend goes inside the wheel**, as `novastudio/frontend_dist/`, together with the i18n files and the
  samples. The server must find it there when installed. Keep the source-checkout and frozen paths working.
- **Build script `tools/build_wheel.py`.** It runs `npm run build`, copies `frontend/dist` into the package data, and
  builds sdist + wheel with `python -m build` (add `build` only as a dev tool). Output to `dist-py/`, which is
  git-ignored.
- **Smoke test `tools/smoke_wheel.py`.**
  1. Create a fresh venv and install the wheel.
  2. Run `novasolver-studio mcp`, check `tools/list` returns 23 tools, create the cantilever template and solve it.
  3. Start the GUI server on a free port and fetch `/` and one asset.
  Run it on Windows here.
- **README** gains "Install with Python (macOS / Linux / Windows)":
  - `uvx novasolver-studio` / `pipx install novasolver-studio`
  - the MCP config snippet (`"command": "uvx", "args": ["novasolver-studio", "mcp"]`)
  - the CalculiX/OpenFOAM install lines per OS
- **AI panel.** `environment_check`'s `mcp_command` must give the uvx/pipx form when running from an installed
  package.
- **Do not publish to PyPI.** The operator sets up the PyPI account and trusted publishing.
  - Add `.github/workflows/publish-pypi.yml`:
    - trigger: `workflow_dispatch` and tags `v*`
    - action: `pypa/gh-action-pypi-publish` with trusted publishing (`id-token: write`)
    - environment: `pypi`
    - it builds with the same steps as `tools/build_wheel.py`
  - Add a short `docs/PYPI_SETUP.md` listing what the operator must do on pypi.org: create the account under the
    business name, enable 2FA, add a pending trusted publisher for `novasolver/novasolver-studio`, workflow
    `publish-pypi.yml`, environment `pypi`.

## 4. CI on macOS and Linux

`.github/workflows/ci.yml`:

- **Trigger and matrix.** On push and pull request: `macos-14` (arm64), `ubuntu-latest` and `windows-latest`; Python 3.12.
- **Steps.**
  1. Install the package plus pytest from the repository: `pip install -e .`, or the same install
     `tools/build_wheel.py` produces.
  2. Run `pytest backend/tests` with OpenFOAM tests skipped when OpenFOAM is absent (they already skip).
  3. Install CalculiX where cheap:
     - Ubuntu: `apt-get install calculix-ccx`
     - macOS: `brew install costerwi/calculix/calculix-ccx`; allow this step to fail without failing the job, and
       report it
  4. Build the frontend (`npm ci && npm run build`) and run `tools/smoke_wheel.py` on all three.
- **Timeout.** Keep the job under the free-runner time; the full suite takes about 11 minutes on this PC.
- **Slow tests.** If a test is too slow for CI, mark it `slow` and run the slow set on Windows only. Say which.
- **Gmsh on headless Linux.** It needs `libglu1-mesa libgl1 libxrender1 libxcursor1 libxft2 libxinerama1` (see
  `Dockerfile`).

## 5. Site and server.json (prepare only)

- **`server.json`.** Add a second package entry `{"registryType": "pypi", "identifier": "novasolver-studio",
  "version": <same>, "transport": {"type": "stdio"}}` in a separate file `server.pypi.json`. Do not edit
  `server.json` yet: the registry validates that the PyPI package exists, so the switch happens after the first PyPI
  release.
- **README.** Add a line in the README "macOS / Linux (preview, community-tested)".

## 6. Tests (new file `backend/tests/test_platform.py`)

1. **`data_dir` / `default_workspace`.** Monkeypatch `sys.platform` (`win32`, `darwin`, `linux`), `Path.home`, and the
   environment. Expected paths per §1. `LOCALAPPDATA` and `NOVASTUDIO_WORKSPACE` override.
2. **CalculiX lookup.** Fake `shutil.which` and file existence. The macOS Homebrew paths are found, and
   `NOVASTUDIO_CCX` wins.
3. **OpenFOAM detection.**
   - A fake `/Applications/OpenFOAM-v2512.app` and a fake `OpenFOAM-v2606.app`: the newest wins.
   - `foam_argv` gives `[<app>/Contents/Resources/etc/openfoam, "-c", "blockMesh -case '<dir with space>'"]` on macOS
     and the bash form on Linux.
   - Windows is unchanged: the `.exe` path.
4. **Memory check.** Each OS branch returns a positive number, and macOS follows the formula.
5. **Package data.** `importlib.resources` finds `frontend_dist/index.html` when present. When absent (source
   checkout without a build), the server still starts with today's fallback.
6. **Grep test.** No `.exe"` literal and no `LOCALAPPDATA` outside the platform helper and the Windows-only branches.
   Allow-list file:line with a reason.

## 7. Report back

Write `reviews/mac_0.4.1_codex_report.md`:

- what was done per section
- test counts on Windows
- what could not be verified without a Mac
- every guess you made
- the commit list, or "uncommitted"
