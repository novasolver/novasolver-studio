# SPEC — Studio 0.4: undo, and face conditions that a person and an AI share

Owner: Claude (spec, acceptance). Implementer: Codex. Branch `v0.4` (git worktree `..\studio_04`).

**Why.** Picking which face gets which condition is how a person states intent; it is the part of the UI that stays
when an AI does the rest. Today it works but is clumsy:

- there is no undo;
- faces are called "面13 · 平面";
- the only selection tools are click, Shift+click, "same shape" and search;
- hidden faces need camera work;
- an AI cannot see what the person selected, and cannot tell a hole from a seat because MCP gives only area and centroid.

The target workflow: **the person selects faces in the 3D view, says "fix these, put 500 N here", the AI applies it,
shows a labelled picture, and the person confirms. Any step, by either of them, can be undone.**

## 0. Ground rules

- Work only inside the worktree. Do not touch `release/`, `workspace/`, `marketing/`, `solvers/`, `.venv`.
- Read the existing code before changing it and reuse its patterns. The files involved:
  `store.py` (`apply_changes`, `save`, `case_lock`), `commands.py` (`update_case`, `case_payload`,
  `geometry_payload`, `render_view`), `api.py`, `mcp_server.py`, `checks.py`, `geometry.py` (`mesh_key`, `display`),
  `mesh_worker.py` (`face_info`, `display`), `results.py` (matplotlib rendering), `templates.py`;
  `frontend/src/state/store.ts`, `components/PropertiesPanel.tsx` (boundaries step), `components/ViewerPane.tsx`,
  `viewer/Viewer.ts` (picking), `components/CommandPalette.tsx`, `components/AiPanel.tsx`.
- Match the surrounding code: comment density, naming, short "why" comments, SI inside, units only at the edges.
- Every user-visible string goes through i18n with **identical key sets in ja/en/zh**, in both the backend and the
  frontend i18n files. Japanese and Chinese must read naturally.
- Follow `studio/.claude/skills/studio-ui/SKILL.md` for every visual change: tokens, type scale, no new colours in
  components, 32 px controls, quiet chrome.
- No new runtime dependencies.
- Old cases must keep opening. A case saved by 0.3.x has no new fields: treat them as absent, never crash.
- The full existing suite (`backend/tests`) must still pass, plus the new tests in §8. Then `npm run build` must
  pass with zero TypeScript errors.
- Run tests with:
  - python `E:\03_サイト構築\NovaSolver\studio\.venv\Scripts\python.exe`
  - `PYTHONPATH=<worktree>\backend`
  - `LOCALAPPDATA=<worktree>\.tmp`: create it and never commit it. The solver lock is machine-wide otherwise.
- Commit in small logical commits on `v0.4`:
  - author `NovaSolver <info@novasolver.jp>`, trailer `Co-Authored-By: Codex <noreply@openai.com>`
  - do not push
  - if git refuses to write (sandbox), leave the work uncommitted and say so in the report.

## 1. Undo / redo (backend: one history for the GUI and the AI)

**History.** Each `update_case` that changes something appends an entry to `workspace/<case>/history.json`:

- the entry holds `{rev_before, rev_after, ts, source, paths, before}`
- `before` is the full case JSON as it was
- keep the last 100 entries; write atomically, like `store.save`
- `source` is `"gui"` for the HTTP API and `"ai"` for MCP: add a `source` argument to `commands.update_case`, defaulting to `"gui"`, and pass `"ai"` from `mcp_server.py`.

**Coalescing.** A new edit merges into the previous entry when all of these hold:

- it has the same source and exactly the same `paths`
- it comes within 2 s of the previous entry
- the previous entry is the latest one

The merged entry keeps the earlier `before`. Autosave while typing "2000" must give one step, not four.

**Undo.** `commands.undo_case(case_id, expected_revision, redo=False, source=...)`:

- Restore the latest entry's `before` content as a **new** revision (revision = current + 1; never reuse numbers, so
  the revision check and the live update stay correct).
- Push the replaced state onto a redo list in the same file. A redo re-applies it.
- Any ordinary edit clears the redo list.
- Undo and redo are themselves not added to the undo list as new entries (they move between the two lists).
- Keep fields that are not user state from the current case: `revision`, `provenance` timestamps, anything
  `store.save` manages. Mesh staleness follows automatically from `geometry.mesh_key` (hash of the content).
  Results become stale because the revision changed. That is acceptable: say "results are from before the undo"
  through the existing stale banner.
- Return the same payload as `update_case`, plus `undone: {source, paths, summary}`. `summary` is a short localized
  text, for example 「面13ほか11面の役割（AI）」 / "role of face 13 and 11 more (AI)".
- Nothing to undo → `StudioError("err.nothing_to_undo", 409)` (and `err.nothing_to_redo`).
- `expected_revision` mismatch → the existing `err.revision`.

**HTTP.** Add `POST /api/cases/{id}/undo` and `/redo` with `{expected_revision}`. `GET /api/cases/{id}` gains
`history: {undo: [{rev, source, summary, ts}] (latest 10), redo_count}`.

**MCP.** Add a tool `undo_change(case_id, redo=False, language)`. Its description says it undoes the latest change
by anyone (person or AI) and tells what it undid. `describe_case` shows the last 5 history entries.

**Frontend.**

- **Buttons and keys.**
  - Undo / redo buttons in the top bar, next to the case name. Tooltip: "元に戻す：<summary>".
  - Ctrl+Z, Ctrl+Shift+Z and Ctrl+Y, but not while focus is in a text input, where the browser's own undo applies.
- **Before undoing.** Flush pending autosave first: the store already batches it. Undo must never be overtaken by a stale save.
- **After undoing.** Show a toast with an Undo-of-undo link ("やり直す").
  - If the undone change came from the AI, the toast says so: 「AIの変更を元に戻しました：…」.
- **Palette.** Add both commands to the command palette.

## 2. Face descriptors (backend, at import)

At import (`mesh_worker` where `face_info` is built), store for every face of an imported CAD/STL shape:

| field | content |
|---|---|
| `name` | the CAD face name when the file carries one; else absent. Use gmsh labels: `Geometry.OCCImportLabels` and `gmsh.model.getEntityName(2, tag)`. Strip the path prefix. Ignore empty or generic names (only digits, "Face", "NONE"). |
| `normal` | planar faces: unit outward normal (outward = away from the solid; reuse the orientation logic used for loads) |
| `axis`, `radius`, `axis_point` | cylinders: axis unit vector, radius [m], a point on the axis. Fit from the face's mesh nodes when gmsh does not give them. Cones/spheres/tori: `radius` only if cheap; otherwise leave absent. |
| `neighbors` | face keys sharing an edge with this face |
| `smooth_neighbors` | the subset of `neighbors` whose shared edge has a dihedral angle < 20° (tangent-continuous, e.g. a fillet and the faces it blends) |
| `bbox` | the face's own bounding box [m] |

- STL shapes have no CAD faces: compute `normal`, `neighbors` and `smooth_neighbors` from the face groups that
  `stl_face_groups` makes.
- Templates (box faces `x0..z1`, …) get `normal` and `neighbors` too; they are cheap from the template geometry.
- Store these in `case["geometry"]["faces"][i]`. They are geometry, not user state.
- Old cases without them: the features of §3 that need them hide their buttons. Re-importing the file fills them in.
  Do not bump `MESHER_VERSION` for this; the mesh does not change.

**Human-readable label.** `commands.face_label` keeps the face number and adds a short description:

- 「面13 · 平面 +Z · 1,200 mm²」
- 「面7 · 円筒 R5 軸Z」
- a CAD name first when present: 「ボルト座面（面7）」

Axis words: ±X/±Y/±Z when the normal or axis is within 2° of an axis, else no direction. Use the same labels in
the GUI list and in MCP.

## 3. Selecting faces (frontend, boundaries step)

Keep everything that exists: click, Shift/Ctrl+click, the list, search, role filter chips, "same shape".

**Selection actions.** When at least one face is selected, show them both in the selection card of the properties
panel and as a compact action row in the viewport HUD. The actions, each with a tooltip:

| action | rule |
|---|---|
| 同じ形の面 (exists) | keep |
| つながった面 | flood-fill over `smooth_neighbors` from the selection (a hole with its fillets, a rounded edge chain) |
| 同じ向きの面 | planar faces whose normal is within 2° of a selected planar face's normal |
| 同じ軸の円筒 | cylinders coaxial with a selected cylinder (axis within 2°, axis line within 1 % of the bbox diagonal); a second click on the same action keeps only the same radius (±1 %) |
| 反転 | select every face not selected (respecting the current list filter if one is active) |
| 隠す / すべて表示 | hide the selected faces (H), show all (Alt+H). Hidden faces are not drawn or pickable, so the faces behind them can be clicked. The list marks hidden faces. |

**Box selection.** Ctrl+drag in the viewport draws a rectangle. It selects the faces with a visible triangle centroid
inside it, front-most only. Use the existing picking or ID buffer if there is one; a CPU depth test against the
picked surface is fine for a few thousand triangles. Shift+Ctrl+drag adds to the selection.

**See-through.** A toggle in the viewport HUD (X key) draws unselected faces at about 25 % opacity, so the inner
faces of a pipe can be picked. Keep the draw-call budget: change the material's opacity, do not duplicate the mesh.

**Named groups.** "グループとして保存" in the selection card asks for a name; the default is the CAD name or 「グループ1」.

- Stored as `case["face_groups"] = {name: [face keys]}`. Edited through `update_case` paths `face_groups.<name>`,
  so they are revisioned and undoable.
- The boundaries panel lists the groups above the face list. Clicking a group selects its faces. Each group has a
  rename and a delete action.
- `update_case` accepts `boundaries.@<group>.<field>` and expands it to every face of the group, as if those paths
  had been sent. Unknown group → `err.unknown_group`. An empty group is allowed.
- `store.apply_changes` validates that group members are existing face keys.

**List rows.** Show the new label (§2): the CAD name when present, else the direction and size. Hovering a row
highlights the face in 3D (exists: keep).

## 4. The GUI selection is visible to the AI

The MCP server is a separate process from the GUI server. Share state through a file.

- The frontend sends its state, debounced to 300 ms, to `PUT /api/gui-state`: `{case_id, revision, step, selected, hidden}`.
- The API writes it atomically to `workspace/.gui_state.json` with `ts`.
- Do not send it when nothing changed.
- New MCP tool `get_gui_selection(language)` returns the case id, the step, the selected faces with their labels
  and descriptors (§2, in mm), the current role of each, and how many seconds ago the selection was made.
- No GUI state, or older than 30 min → say so plainly. "Nothing is selected" is a normal answer, not an error.
- The tool description tells the agent: when the person says "these faces", "the faces I selected" or 「選んだ面」,
  call this first.
- The AI panel's help text, and the "how to connect an AI" text, gain one line:
  「画面で面を選んでから『選んだ面を固定して』のように頼めます」(ja/en/zh).

## 5. A labelled picture for the AI to show and check

Extend `render_view` (commands and MCP) with `quantity="faces"`:

- Draw the surface, coloured by role. Use the same role colours as the viewer palette, both themes not needed: the light theme.
- Put the face number at each face's visible centroid. Skip faces whose centroid is hidden. Back-facing alone is not
  a good enough test for concave parts; use a depth test against the rendered surface.
- Draw a legend of roles.

Parameters:

- `view`: `iso` (default), `iso_back`, `top`, `bottom`, `front`, `back`, `left`, `right`
- `highlight`: face keys drawn in the accent colour, with the others grey. This is the picture an agent shows before
  applying conditions.

Read numbers from results, not pictures: keep that sentence in the tool description, and add that `faces` pictures
are for confirming the setup with the person.

MCP `import_geometry` and `describe_case` return the descriptors of §2 (mm, rounded like today) and `face_groups`.
Keep the existing fields and their names so that current agents keep working.

## 6. Readiness check

`checks.py`, thermal (and the thermal part of DC current with Joule heating off/on as appropriate):

- **The case.** No heat enters or leaves through a temperature difference: there is no heat-flux face, no volumetric
  source, and every fixed-temperature and convection reference is the same temperature.
- **Why warn.** Today it passes as "ready" and gives a uniform temperature.
- **The warning.** Make it a warning (orange) with the message 「熱の入力がないため、全体が周囲と同じ温度になります。発熱する面に熱流束を設定するか、温度の異なる面を指定してください。」 in ja/en/zh.

## 7. Small UI fixes found in the 0.3.1 walk-through

- **Value fields.** The "values" section listed every one of 12 selected faces separately with identical values. When
  several faces with the same role are selected, show one set of fields (the existing mixed-value handling already
  supports applying to all). The per-face list belongs only to the "all faces" overview, collapsed by default when it
  has more than 5 rows.
- **Long lists.** The face list must stay usable with 300 faces. Check scrolling, the search and filter chips, and
  that selection from 3D scrolls the row into view.

## 8. Tests (new file `backend/tests/test_faces_undo.py`; each must fail if the feature is broken)

1. **Undo and redo.** Edit role, then value, then geometry param.
   - Undo three times: the case equals the original. Its revision went up by 3, and the mesh is stale exactly when a
     geometry param changed.
   - Redo three times: equals the final state.
   - A new edit after an undo clears redo.
2. **Coalescing.** Five edits of the same path within 2 s give one undo step. Edits 3 s apart give two.
3. **Source.** An MCP edit's history entry has `source == "ai"`. `undo_change` through the MCP tool function
   restores it and reports the summary.
4. **Nothing to undo.** It raises `err.nothing_to_undo`, and a stale `expected_revision` raises `err.revision`.
5. **Descriptors** on a test-generated STEP: a box with a through hole, a fillet on one edge, and named faces if gmsh
   can write labels, else skip that assertion.
   - Planar normals are correct and outward.
   - The hole is a cylinder with the right radius (1 %) and axis.
   - The hole's `neighbors` are the two faces it passes through.
   - `smooth_neighbors` of the fillet are its two blended faces.
   - Labels contain the direction and size.
6. **STL descriptors.** The same box as STL: normals and neighbors present.
7. **Groups.**
   - Create a group. `boundaries.@group.role` sets every member, and a single undo reverts all of them.
   - An unknown group raises `err.unknown_group`.
   - Members must exist.
8. **GUI selection.** `PUT /api/gui-state`, then the MCP tool function returns those faces with labels and an age
   below 5 s. No file → the plain "no selection" answer.
9. **Labelled render.** `render_view(quantity="faces")` returns a PNG. On the box with a hole, the labelled set from
   `iso` and from `iso_back` together covers every face; neither view alone needs to. `highlight` makes the PNG
   differ from the plain one.
10. **Readiness.** Convection-only thermal gives the new warning. Adding a heat flux removes it.
11. **Old case.** A case JSON from 0.3.1 without the new fields: describe, render faces, undo and selection tools work
    or degrade without errors.
12. **MCP contract.**
    - The tool count goes from 21 to 23 (`undo_change`, `get_gui_selection`). Update the existing assertion that
      checks 21.
    - Every tool description stays under the existing length style.
    - `make_mcpb.py` picks the new tools up from the exe, with no change needed: confirm by reading it.

Frontend acceptance is done by Claude in a real browser (studio-ui loop). Make `npm run build` pass, and expose
`window.__nss` actions for undo/redo and the new selection tools so they can be driven from a script.

## 9. Docs

- **`docs/RELEASE_NOTES_v0.4.0_draft.md`.** Use measured numbers only; leave the numbers as TODO if not measured.
- **`README.md`.** Add a short section on how a person and an AI share face selection.
- **Server instructions.** Update the MCP server instructions string in `mcp_server.py` with the
  select → say → confirm → undo workflow.

## 10. Report back

Write `reviews/v0.4_codex_report.md` with:

- what was done per section
- the test results (counts), with the full-suite time
- anything not done and why
- every place where you had to guess what this spec meant
- the commit list, or "uncommitted" if git refused
