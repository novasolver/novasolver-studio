# SPEC: Studio 0.6.1, solved examples and case archives

Owner: Claude (spec and acceptance). Implementer: Codex. Branch `v0.6.1`, git worktree `..\studio_061`.

## Why

The operator asked to distribute the verification results as samples, and allowed external hosting such as GitHub.
Today a user, or an AI agent driving Studio over MCP, has to run a template before seeing any result. The
published verification table (studio page, 14 cases) is also only text.

Solved examples fix both:
- open one and the result appears at once;
- the verification card next to it shows the reference value and the error;
- anyone can rerun it and get the same number.

The files are GitHub release assets, so the NovaSolver VPS carries no load. It only links to GitHub.

## 0. Ground rules

The ground rules of `SPEC_0.4_faces_undo.md` §0 apply, with branch `v0.6.1`. In short:
- work in the worktree only, and match the existing code;
- i18n ja/en/zh with identical keys;
- use the studio-ui skill for visuals;
- add no new runtime dependencies;
- old cases keep opening;
- the full suite and the new tests pass, and `npm run build` passes;
- follow the commit and test-environment rules.

Files to read first:
- Backend:
  - `store.py`: `case_dir`, `load`, `save`, `new_id`, the `_ID` pattern, `list_all`
  - `jobs.py`: job.json, request.json, how the latest job is found
  - `results.py`: `load`, `payload`, stale detection
  - `commands.py`: `_latest_job`, `case_payload`, `list_samples`, `open_sample`, `import_geometry`, `export_results`
  - `exports.py`, `mcp_server.py`, `app.py`, `osdirs.py`, `config.py`, `templates.py`
- Frontend: `StartScreen.tsx`, `store.ts`, `ShareMenu.tsx`, `CommandPalette.tsx`

The main checkout already holds 0.6.1 fixes (commit d0fd3aa); the branch starts from it. Do not redo them.

## 1. Case archive (`.nscase`)

A zip with the extension `.nscase`. It is useful on its own, for sending a solved case to a colleague, and it is
the example format.

### 1.1 Export
- `export_case(case_id, include_results=True)` writes `<exports dir>/<slug>-<case_id>.nscase` and returns its path
  and size.
  - Use the existing exports location. If there is none, use `<workspace>/exports`.
  - It contains `case.json` and the current geometry and mesh folders (`geom/` or `mesh/`, whichever the case
    has).
  - With `include_results`, it also contains the latest **successful** run folder `run/<job_id>/`:
    `job.json`, `request.json`, `results.json`, `results.npz`, `mesh.npz` and `worker.log`.
  - Do not include other runs, `revisions/`, lock files or temp files.
- Add `nscase.json` at the root:
  - `format` = 1, `studio_version`, `template`, `physics`, `created_at`
  - `files`: a list of `{path, size, sha256}`
  - optionally `verification`: the payload's verification summary (reference label, reference value, result,
    error %, pass)
- **Privacy.** No absolute paths, user names or host names may leave the machine. Scrub `worker.log`, `job.json`,
  `request.json` and `case.json` provenance: replace the user's home directory, the workspace path and the
  data_dir with `<home>`, `<workspace>` and `<data>`.
  - A test must grep the whole archive for the test's home or workspace path and find nothing.
  - Imported CAD geometry keeps only its file name.
- The export must be deterministic: sorted entries, fixed zip timestamps, and a `created_at` taken from the job's
  finish time. The same case then gives the same sha256. The example index relies on this.

### 1.2 Import
- `import_case(path=None, data=None)` accepts a `.nscase` or `.zip`.
- Safety:
  - Reject an entry with an absolute path, a drive letter, `..`, a backslash trick or a symlink.
  - Reject paths outside the allowlist (`nscase.json`, `case.json`, `geom/**`, `mesh/**`, `run/<id>/<allowed
    files>`).
  - Reject more than 2,000 entries, more than 2 GB uncompressed, or any entry with a compression ratio above 200.
  - Check every sha256 against `nscase.json`.
  - Raise `StudioError('err.archive_invalid', 400, reason=...)` with localized reasons.
  - Extract into a temp folder inside the workspace, then rename it into place, so a failed import leaves nothing
    behind.
- The case gets a **new** case_id. Update the ids inside `case.json`, `job.json` and `request.json`, and keep the
  job_id.
  - Set `provenance.imported_from` to `{"case_id": old, "studio_version": ..., "example": name|None}`.
  - Load it through `store.load`, so old-format normalization runs.
- The imported result must open as the current, **non-stale** result (same mesh key and same revision semantics),
  with the same cards and the same verification as on the machine that solved it.
  - Editing the case makes the result stale, as it does for a local result.
  - "Run" works normally.
  - Test this with a round trip: export, import, then compare the `get_results` cards and `verify_case` output.
- An archive written by a newer `format` gives `err.archive_newer`.
- An archive from an older Studio whose results no longer load still imports the case. It drops the result and
  warns with `warn.archive_results_dropped`.

## 2. Examples (solved verification cases)

### 2.1 Build: `tools/build_examples.py`
- Runs in an isolated workspace and data dir, set through `NOVASTUDIO_WORKSPACE` and `LOCALAPPDATA` in a temp
  folder, never the user's.
- Includes every template that has a closed-form or reference check and runs on the built-in engines.
  - Today that is 23 templates: all templates except the `import-*` ones and those whose only engine is external.
  - The candidate list comes from `TEMPLATES`, not from a hard-coded list.
  - `--only a,b` and `--jobs N` options.
- For each template:
  1. create the case;
  2. run it in its default mode with the default mesh (the run the site's verification table quotes);
  3. wait for the run;
  4. require `verification.pass` (for collapse, the limit-load reference);
  5. export with results.
- A template that fails verification is **not** published. It is listed in the build report with the reason, and
  the script exits non-zero unless `--allow-missing` is given.
- Writes `release/examples/<version>/`:
  - `example-<template>.nscase`
  - `examples.json`, the index:
    - `format` 1, `studio_version`
    - `examples`: a list of `{name, template, physics, title{ja,en,zh}, description{ja,en,zh}, file, size,
      sha256, reference{label{ja,en,zh}, value, unit}, result{value, unit}, error_pct, mesh{nodes, elements},
      solve_s}`
  - `README.md` (EN + JA): a table of the same numbers, for the GitHub release page.
- Takes the titles and descriptions from the templates' existing localized strings. Write no new prose for them.

### 2.2 Hosting
- Attach the files as assets of the GitHub release `v<studio_version>` (repo `novasolver/novasolver-studio`).
  Claude uploads them; you only build them.
- The base URL is a constant in one place (`config.py`): `EXAMPLES_BASE =
  "https://github.com/novasolver/novasolver-studio/releases/download/v{version}/"`.
  - It can be overridden by the `NOVASTUDIO_EXAMPLES_URL` environment variable. Tests use a local `http.server`
    or a `file://` folder.

### 2.3 In the app
- `list_examples(lang)`:
  - fetches `examples.json`, with a 10 s timeout, a User-Agent `NovaSolverStudio/<version>`, and no cookies or
    personal data;
  - caches it in `<data>/examples/<version>/examples.json`;
  - falls back to the cache when offline.
  - With neither, it raises `err.examples_offline` with the release page URL and the manual route: download the
    `.nscase`, then use "Open file".
- `open_example(name, lang)`:
  - downloads the `.nscase` into the cache if missing;
  - verifies its sha256 against the index (on a mismatch, deletes the file and raises `err.example_corrupt`);
  - imports it with `example=name`;
  - returns the case payload.
  - Reports progress for downloads over 1 MB: the GUI shows a determinate bar, and MCP sends progress
    notifications if the existing tools do.
- Only the configured base URL is ever fetched. Names must match `^[a-z0-9-]+$` and exist in the index, so a tool
  argument cannot point the app at another host or path.
- MCP: add the tools `list_examples`, `open_example` and `export_case`, plus `import_case`, which takes a local path
  and is confined like `import_geometry`. Bump the tool count everywhere it is stated or tested, and update
  `make_mcpb.py` if it reads the list. The docstrings tell an agent that an example opens with its results already
  computed and verified, so it can inspect a result before running anything.
- GUI:
  - **Start screen:** a section "解析済みの例" / "Solved examples" / "已求解示例" below the templates.
    - Lazy: fetch the index only when the section scrolls into view, or when the user clicks "Show".
    - Rows: title, physics, reference vs result and error %, size, and an "Open" action. While downloading, the
      row shows progress.
    - Offline state: one line plus a link to the release page. Do not show an empty box.
  - **"Open file"** on the Start screen also accepts `.nscase`, with drag and drop if the current import supports
    it.
  - **Case menu or command palette:** "Export case (.nscase)", with and without results.
  - An opened example shows a quiet chip "Example · verified" next to the case title, until the case is edited.

## 3. Out of scope
- Uploading to GitHub (Claude does it) and any change to the novasolver.jp site (Claude does it).
- Examples for external-engine templates (OpenFOAM, CalculiX). Leave a TODO in the build script.

## 4. Tests (new; the existing suite must still pass)
1. Export, import and compare: cards, verification and the field values (`field` vm or T at 10 nodes) are
   identical. The result is not stale. One edit makes it stale.
2. Determinism: the same case exported twice gives the same sha256.
3. Privacy: grep the archive bytes, decompressed, for the home path, workspace path and user name and find
   nothing.
4. Malicious archives are rejected and leave nothing in `cases/`:
   - zip-slip (`../x`, `C:\x`, `/x`)
   - a symlink entry
   - an entry not on the allowlist
   - an entry with a bad sha256
   - an entry with a compression ratio of 1000
   - 2,001 entries
5. `list_examples` / `open_example` against a local server:
   - index fetch and cache
   - offline with cache, and offline without cache (error text in 3 languages)
   - a sha256 mismatch deletes the file
   - a bad name is rejected
6. `build_examples.py --only cantilever,plastic-bar` produces 2 archives and an index whose numbers equal
   `verify_case` output.
7. MCP: the new tools are listed, `open_example` → `get_results` works, and the tool count is updated.
8. Frontend: `npm run build`, plus a test in `frontend/tests/` for the examples section states: loading, list,
   offline, downloading, and opened.

## 5. Report

Write `reviews/v0.6.1_codex_report.md` with:
- what you changed, file by file;
- the test results;
- the size of each example archive and the total;
- the full build report from running `build_examples.py` on all eligible templates (the time and pass/fail of each);
- anything you could not do, and why.
