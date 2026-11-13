# Contributing to NovaSolver Studio

Bug reports, test parts, benchmarks, translations and code are all welcome. Open an issue or a discussion first for
anything large, so that nobody builds the same thing twice.

Tried Studio? [Share a short experience](https://github.com/novasolver/novasolver-studio/issues/new?template=usage-feedback.yml)
or [report a problem](https://github.com/novasolver/novasolver-studio/issues/new?template=bug-report.yml).
English, 日本語 and 中文 are welcome. These are public issues; please omit personal information and confidential models/results.

## Get it running

```bash
git clone https://github.com/novasolver/novasolver-studio
cd novasolver-studio
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"     # Windows: .venv\Scripts\python.exe
cd frontend && npm ci && npm run build && cd ..
python -c "import shutil; shutil.copytree('integrations', 'backend/novastudio/integrations', dirs_exist_ok=True)"
.venv/bin/python -m pytest backend/tests -q
```

Start the app with `python -m novastudio serve --port 8765` from `backend/`. CalculiX and OpenFOAM are optional.

## Good places to start

- **A part that fails.** Attach a STEP or STL you may share, what you did, and what happened. Failed imports and failed
  meshes are the most useful reports we get.
- **A new benchmark.** Add a problem with a published answer to `validation/benchmarks.py`, with its source. A benchmark
  that Studio fails is as welcome as one it passes.
- **A second opinion.** Run a result in another solver and tell us if the numbers differ.
- **macOS and Linux.** The core runs there, but it gets far less use than on Windows. Reports help.
- **Translations.** The interface is in `backend/novastudio/i18n/` and `frontend/src/i18n/`. The key sets must stay identical.

## Rules for code

- The GUI, MCP and CLI all call `backend/novastudio/commands.py`. Do not add a second path around it.
- MCP tools never run a shell or arbitrary code. The model fills in the case schema, and the app writes the solver input.
- Gmsh and the solvers run as separate processes.
- A changed calculation needs a test against a known answer. Run `python validation/suite.py --quick`.
- `verified` means a mesh study or a reference comparison passed. It never means the design is safe, so do not word it that way.

More detail: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (Japanese) and [docs/DESIGN.md](docs/DESIGN.md).

## Licence

By contributing, you agree that your work is released under [GPL-3.0-or-later](LICENSE), the licence of this project.
Do not contribute code, text or data from commercial CAE products.
