# NovaSolver Studio 0.4.0 — draft

The person selects faces in Studio and asks an AI to apply conditions. The assistant can read that selection,
show a numbered setup picture, and apply changes through the same command layer as the GUI.

- Shared Undo/Redo history for GUI and MCP edits, with revision checks, typing coalescence and AI attribution.
- Imported face descriptors: outward planar normals, cylinder axes/radii, bounds, edge neighbors and smooth neighbors.
  CAD face names are shown when the source file and importer retain them. Template faces carry descriptors too.
- Selection tools for smooth connections, matching normals, coaxial cylinders and radius, plus inversion,
  hidden faces, Ctrl+drag visible-face selection and see-through mode. Named groups are revisioned and undoable.
- `get_gui_selection` shares the GUI's current intent across the separate MCP process. `undo_change` undoes
  the latest edit by either participant. `render_view(quantity="faces")` supplies numbered views and highlights.
- Thermal readiness warns when every temperature reference is equal and no heat input is present.
- The boundary overview collapses long value lists; selected faces share one value editor.
- Japanese, English and Chinese strings are kept in matching key sets. Existing case files remain readable.

Validation: 84 backend tests passed and 4 skipped in 660.16 s. The face/undo store harness and TypeScript check pass.
The production build is blocked by an environment `spawn EPERM` error starting esbuild; details are in
`reviews/v0.4_codex_report.md`.
Interactive browser acceptance is assigned to Claude by the feature specification.

Performance on the target Intel HD 630: TODO (not measured). No performance improvement is claimed.
