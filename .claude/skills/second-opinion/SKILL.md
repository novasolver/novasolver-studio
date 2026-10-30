---
name: second-opinion
description: Cross-check NovaSolver Studio with Codex before a release or after a large change. Codex reviews read-only and writes findings; Claude verifies each one, fixes or rejects it with a reason, and records the outcome. Use before every `gh release create`, after refactors touching solvers/meshing/MCP, or when the user asks for a review.
---

# Second opinion (セカンドオピニオン)

Two different models read the same code. Claude wrote most of Studio, so Claude is the worst reviewer of its own
blind spots; Codex reads it cold. Codex only **reports**; it never edits. Claude decides.

## When

| Trigger | Scope |
|---|---|
| Before every release (`gh release create`) | diff since the previous release tag (`git diff vX.Y.Z..HEAD`) |
| After a large change (solver, meshing, MCP tools, case schema, share/export) | the files touched + their callers |
| First run / every ~5 releases | whole `backend/` and `frontend/src/` |

A release is not "ready" until the second-opinion report for it exists and every finding has an outcome.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File studio\tools\second_opinion.ps1 -Since v0.2.1          # diff review
powershell -ExecutionPolicy Bypass -File studio\tools\second_opinion.ps1 -Full                  # whole code base
```

The script runs `codex exec` with `--sandbox read-only` (newest `codex.exe` under
`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\`), model `gpt-6.1-sol`, effort `high`, and writes
`studio/reviews/<date>_<label>.codex.md`. It takes 10–40 minutes; run it in the background.

### Cheap first pass (DeepSeek)

`python studio/tools/ds_review.py diff <tag>` (also `files <paths>`, `i18n`) sends the scrubbed diff to DeepSeek and
writes `reviews/<date>_<label>.<model>.md/.json`. Key: `DEEPSEEK_API_KEY` or `E:\_SECRETS\deepseek.txt`, read in code
only. `-DeepSeekFirst` on `second_opinion.ps1` runs it before Codex and asks Codex to confirm/reject those findings
first. Use `DEEPSEEK_MODEL=deepseek-reasoner`: on the 0.6.3 updater diff (2026-10-31) `deepseek-chat` found 0 of the
9 real issues and repeated itself; the reasoner found about 3 of 9 plus one new real bug (shortcuts behind the Help
dialog), and about a third of its items were wrong (e.g. a TypeScript error the build disproves). It is a filter that
saves tokens, never a substitute for the independent review: every finding still gets an outcome here.

## What Codex is asked to look for (in this order)

1. **Wrong answers without a warning** — units, sign conventions, boundary conditions silently dropped, a gate
   (ran / converged / verified) that can pass when it should not, reference solutions that do not match the case.
2. Crashes and stuck jobs — solver lock, worker processes, timeouts, non-ASCII paths, large meshes, cancelled jobs.
3. Security — the local server only on 127.0.0.1, path traversal in imports/case ids, links (`?template=`) and MCP
   inputs that could write outside the workspace or run commands, untrusted STL/STEP.
4. MCP contract — tool schemas vs behaviour, error messages an agent can act on, long jobs.
5. UI — stale state after language/theme switches, captures leaving the viewer resized, i18n keys missing.
6. Packaging — files missing from the bundle, version strings, licence notices.

Each finding: file:line, what goes wrong (concrete input → wrong output), severity (high / medium / low), and a
suggested fix. No style comments.

## Triage (Claude, required)

For every finding, in `studio/reviews/<date>_<label>.triage.md`:

- **reproduce or read the code path** — do not accept or reject on the description alone;
- outcome: `fixed (commit)` / `rejected (why)` / `deferred (issue or ROADMAP line)`;
- a fix to physics or gates also needs a test in `backend/tests/` that would have caught it.

Run `pytest` (with `LOCALAPPDATA` pointed at a temp folder so the solver lock is not shared with running jobs) and
the studio-ui verification loop after fixes. Then release.

## Notes

- Codex has no network in its sandbox; it cannot run OpenFOAM or download anything. It may run `python -m pytest`
  read-only checks if the sandbox allows; findings that need a run are marked "needs run" for Claude.
- Keep reports in git (`studio/reviews/`). They are the history of what was checked.
