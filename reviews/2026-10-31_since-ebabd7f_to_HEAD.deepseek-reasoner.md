# DeepSeek first pass: since-ebabd7f_to_HEAD (2026-10-31, deepseek-reasoner)

Unverified. Each finding must be checked against the code and recorded as fixed / rejected (reason).

Tokens: prompt 216173 (cache hit 61312), answer 765833. Problems: 4

- problem: backend/novastudio/exports.py, backend/novastudio/external.py, backend/novastudio/fatigue.py, backend/novastudio/fem_nonlinear.py, backend/novastudio/fem_tet10.py: answer cut off
- problem: backend/novastudio/api.py, backend/novastudio/box_mesh.py, backend/novastudio/checks.py, backend/novastudio/commands.py, backend/novastudio/contact.py: answer cut off
- problem: backend/novastudio/sections.py, backend/novastudio/store.py, backend/novastudio/structural.py: answer cut off
- problem: backend/novastudio/templates.py, backend/tests/test_electric.py, backend/tests/test_faces_undo.py, backend/tests/test_v05.py, backend/tests/test_v06.py, backend/tests/test_v07_buckling.py, backend/tests/test_v07_contact.py, backend/tests/test_v07_fatigue.py, frontend/src/App.tsx: answer cut off

| # | sev | conf | where | summary |
|---|---|---|---|---|
| 1 | high | high | backend/novastudio/mcp_server.py:328 | The `@mcp.tool(annotations=WRITE)` decorator for detect_contacts was replaced by `user@example.com(annotations=WRITE)`, an expression that raises NameError at module import and leaves the tool unregistered. |
| 2 | high | high | backend/novastudio/mesh.py:999 | Hardcoded volume tag 2 is invalid after occ.fragment, so gap_blocks meshing can crash or refine the wrong body. |
| 3 | high | high | contact.py:3 | Contact-pair filter uses len(A['c']) before slave/master assignment, so a small slave against a large master is discarded. |
| 4 | high | medium | backend/novastudio/mesh_worker.py:769 | gap_blocks computes h via DIVS[...] but never applies it; DIVS is likely undefined (other branches use inline dicts), so the job raises NameError, and even if defined no mesh size is set. |
| 5 | high | medium | contact.py:1 | np.abs() destroys the sign of the measured gap, so initial interference is stored as positive clearance. |
| 6 | high | low | backend/novastudio/api.py:274 | The decorator for the new detect_contacts route renders as user@example.com(...) instead of @app.post(...); the module will fail to import and the whole API goes down. |
| 7 | medium | high | tools/ds_review.py:37 | Home-path scrub regex is duplicated and matches only the literal text '/home/USER/', so real Linux/macOS home paths are never scrubbed. |
| 8 | medium | medium | backend/novastudio/fem_nonlinear.py:212 | Contact saddle systems up to 120k primal dofs now go straight to SuperLU (spsolve) with MatrixRankWarning escalated to an error and no GMRES/AMG fallback, so rank-deficient mortar blocks abort the solve and fill-in can OOM the worker. |
| 9 | medium | medium | backend/novastudio/geometry.py:73 | mesh_key() now calls hertz_line(case), so summarizing/validating/meshing a freshly created hertz case can raise if the force/material needed for the contact half-width is not yet set. |
| 10 | medium | medium | backend/novastudio/run_worker.py:692 | fatigue-bar mesh study tracks fatigue_sf_min, which is singular at the fixed support and never converges, so the GCI/convergence verdict is meaningless. |
| 11 | medium | medium | backend/novastudio/validation.py:123 | Fatigue load-ratio validation restricts R to [-1,1), rejecting valid compression-compression cycles with R>1. |
| 12 | medium | medium | backend/novastudio/validation.py:123 | math.isfinite(value) runs before the numeric bounds, so a huge JSON integer raises OverflowError and returns 500. |
| 13 | medium | medium | contact.py:24 | Bonded records are bilateral only if an extra 'tied' key exists; otherwise tangential slip is allowed. |
| 14 | medium | medium | contact.py:70 | Conformal force_pairs divides lambda by area while the new mortar path does not, producing inconsistent force units. |
| 15 | medium | low | backend/app/templates.py:646 | tied-parts displaces the top face +0.05 mm (up, away from the lower block) while gap-blocks uses -0.1 mm; the tied/bonded interface is pulled in tension, so the resulting contact force sign/magnitude likely won't match the fixed reference. |
| 16 | medium | low | backend/novastudio/store.py:168 | New error codes err.contact_pair_faces and err.contact_pair_same_face (plus new ENUM values 'buckling' and fatigue surfaces) have no ja/en/zh locale entries in this diff, so the UI shows raw keys. |
| 17 | medium | low | backend/novastudio/templates.py:120 | The shared `own` dict assigns `x1` only to b1; in `gap_blocks` the x1 side face spans both blocks, so BCs on x1 miss b2. |
| 18 | low | medium | backend/novastudio/api.py:276 | bool(b.get("apply")) coerces any non-empty string to True, so apply:"false"/"0" silently mutates the case by adding contact pairs. |
| 19 | low | medium | backend/novastudio/results.py:411 | fatigue_life viewer only floors life at 1 but never caps it at fatigue_infinite, unlike the card (min(life_min, fatigue_infinite)); the code comment says lives past the cap should read the same. |
| 20 | low | medium | tools/ds_review.py:147 | i18n mode crashes with FileNotFoundError if ja.json exists but en.json or zh.json is missing. |
| 21 | low | medium | tools/second_opinion.ps1:23 | With -DeepSeekFirst, invoking 'python' aborts the whole script on machines lacking a python on PATH, so Codex never writes the report. |
| 22 | low | low | backend/app/templates.py:705 | new_case now copies both 'contacts' (stacked-blocks, friction-block) and 'contact_pairs' (gap-blocks, tied-parts, hertz); if the solver/pipeline was migrated to read only 'contact_pairs', the two older templates silently lose their contact definition. |
| 23 | low | low | backend/app/templates.py:635 | gap-blocks/tied-parts set displacement boundary with 'ux':None,'uy':None; if the boundary schema/handler expects {value,unit} objects, this can throw or be treated as constrained rather than free. |
| 24 | low | low | backend/novastudio/fatigue.py:33 | Body lookup uses `if body`, so a falsy body key (integer index 0) silently uses the global solid preset/props instead of the body's, giving wrong Su/Se and safety factor and life. |
| 25 | low | low | backend/novastudio/fatigue.py:40 | endurance is only False for preset 'aluminium', so copper (C1100, also without a true endurance limit per the module's own note) gets life reported as infinite above its 1e8-cycle strength. |
| 26 | low | low | backend/novastudio/results.py:410 | fatigue_sf/fatigue_life arrays are not sanitised for NaN; NaN propagates into scalars/range and Starlette JSONResponse uses allow_nan=False, raising a 500. |
| 27 | low | low | backend/novastudio/run_worker.py:75 | mortar_pairs records (keys face/closest_m/no_contact) are appended into m['_contact_pairs'], which elsewhere holds split_mesh records with master/slave/normal arrays, risking a format mismatch. |
| 28 | low | low | backend/novastudio/sections.py:24 | Buckling sections read data['mode_shapes'] and treat the vectors as nodal displacements; if buckling results are stored under a different key/shape this raises KeyError -> HTTP 500. |
| 29 | low | low | frontend/src/components/StructuralSettings.tsx:153 | Removing a contact pair via change(...,null) leaves a null entry that the render dereferences (c.slave/c.master), crashing the Boundaries step. |
| 30 | low | low | frontend/src/components/StructuralSettings.tsx:149 | Pair label button calls selectFace(c.slave[0]) without guarding an empty slave face list. |

## 1. The `@mcp.tool(annotations=WRITE)` decorator for detect_contacts was replaced by `user@example.com(annotations=WRITE)`, an expression that raises NameError at module import and leaves the tool unregistered.
- where: backend/novastudio/mcp_server.py:328
- scenario: Backend startup / any MCP call -> `user` is undefined at import -> NameError crashes mcp_server module, so ALL tools (describe_case, run_simulation, ...) stop working; detect_contacts is never exposed as a tool.
- fix: Restore the line to `@mcp.tool(annotations=WRITE)` above `async def detect_contacts`.

## 2. Hardcoded volume tag 2 is invalid after occ.fragment, so gap_blocks meshing can crash or refine the wrong body.
- where: backend/novastudio/mesh.py:999
- scenario: Run a gap_blocks job: occ.fragment([(3,1)],[(3,2)]) deletes the original volumes and returns new tags; getBoundary([(3,2)]) then raises/returns empty, aborting meshing or leaving the interface unrefined.
- fix: Capture the outDimTags from occ.fragment and select the upper volume by centroid/bbox, not by original tag 2.

## 3. Contact-pair filter uses len(A['c']) before slave/master assignment, so a small slave against a large master is discarded.
- where: contact.py:3
- scenario: A is a 1000-node plate, B is a 20-node pad fully overlapping; hit.sum()=20 < 0.05*1000=50 -> continue, so no contact is generated.
- fix: Choose slave/master first and use len(slave) (or min(len(A),len(B))) for the coverage threshold.

## 4. gap_blocks computes h via DIVS[...] but never applies it; DIVS is likely undefined (other branches use inline dicts), so the job raises NameError, and even if defined no mesh size is set.
- where: backend/novastudio/mesh_worker.py:769
- scenario: gap_blocks job (size='fine'): if DIVS is not a module constant the worker crashes on this line; otherwise both blocks get gmsh default sizing, so the documented 'upper block finer / non-matching interface' is never produced and the contact test no longer exercises a non-matching mesh.
- fix: Define DIVS (or inline the dict) and add gmsh.option.setNumber('Mesh.MeshSizeMax', h) plus a finer size (e.g. MeshSizeMax on volume 2) for the upper block.

## 5. np.abs() destroys the sign of the measured gap, so initial interference is stored as positive clearance.
- where: contact.py:1
- scenario: A shrink-fit shaft overlaps the hole by 0.01 mm; signed gap is -0.01 mm but gap_m becomes +0.01 mm, so Constraints treats it as an open gap and applies no press-fit force.
- fix: Keep the signed dot product for g0; use abs only for search distance/coverage.

## 6. The decorator for the new detect_contacts route renders as user@example.com(...) instead of @app.post(...); the module will fail to import and the whole API goes down.
- where: backend/novastudio/api.py:274
- scenario: Backend start -> NameError/SyntaxError at import of nova studio.api -> every endpoint 500s (or if it's a diff anonymization artifact, ignore).
- fix: Restore @app.post("/api/cases/{case_id}/detect-contacts").

## 7. Home-path scrub regex is duplicated and matches only the literal text '/home/USER/', so real Linux/macOS home paths are never scrubbed.
- where: tools/ds_review.py:37
- scenario: Diff contains '/home/alice/repo/secret.py' from a traceback -> sent verbatim to api.deepseek.com, leaking the username/home dir contrary to the docstring.
- fix: Use r'/home/[^/\s"\']+/?' and add an equivalent macOS '/Users/<name>/' pattern.

## 8. Contact saddle systems up to 120k primal dofs now go straight to SuperLU (spsolve) with MatrixRankWarning escalated to an error and no GMRES/AMG fallback, so rank-deficient mortar blocks abort the solve and fill-in can OOM the worker.
- where: backend/novastudio/fem_nonlinear.py:212
- scenario: 100k-dof Hertz model with a mortar pair whose constraint rows are redundant -> spsolve raises MatrixRankWarning (simplefilter 'error') -> linear_solve raises instead of the old GMRES path -> Newton step crashes.
- fix: Wrap spsolve in try/except and fall back to the GMRES path on MatrixRankWarning/RuntimeError; size the limit by len(b) (primal+multipliers), not nprimal.

## 9. mesh_key() now calls hertz_line(case), so summarizing/validating/meshing a freshly created hertz case can raise if the force/material needed for the contact half-width is not yet set.
- where: backend/novastudio/geometry.py:73
- scenario: Create a hertz case, then call describe_case/validate_case before setting the force -> hertz_line computes 'a' from missing/invalid load -> exception aborts checks the user needs to fix the case.
- fix: Guard the call (try/except or skip the extra entry when load/materials are unset) so mesh_key never raises for incomplete cases.

## 10. fatigue-bar mesh study tracks fatigue_sf_min, which is singular at the fixed support and never converges, so the GCI/convergence verdict is meaningless.
- where: backend/novastudio/run_worker.py:692
- scenario: Run a mesh convergence study on a fatigue-bar case with a fully fixed face -> SF -> 0 as the mesh refines at the rigid support -> study reports monotonic non-convergence although the away-from-support SF converges.
- fix: Map 'fatigue-bar' to 'fatigue_sf_min_away' (fall back to max_disp only if absent).

## 11. Fatigue load-ratio validation restricts R to [-1,1), rejecting valid compression-compression cycles with R>1.
- where: backend/novastudio/validation.py:123
- scenario: User sets physics.fatigue.ratio=2 for a -100/-50 MPa cycle -> StudioError 400, analysis cannot run.
- fix: Allow R > 1 (or the full real range); only reject R=1 if static cycles are unsupported.

## 12. math.isfinite(value) runs before the numeric bounds, so a huge JSON integer raises OverflowError and returns 500.
- where: backend/novastudio/validation.py:123
- scenario: POST setting physics.fatigue.cycles=10**1000 -> math.isfinite raises OverflowError -> unhandled server error.
- fix: Catch OverflowError, or check 1<=value<=1e12 before calling math.isfinite, or convert to float in a try block.

## 13. Bonded records are bilateral only if an extra 'tied' key exists; otherwise tangential slip is allowed.
- where: contact.py:24
- scenario: A mortar record {'type':'bonded'} without 'tied' gets bilateral=True, tied=False and mu=0, so tangential residual is l/r and the bonded parts slide freely.
- fix: Derive tied as r.get('tied', r['type'] == 'bonded') so bonded implies no tangential slip.

## 14. Conformal force_pairs divides lambda by area while the new mortar path does not, producing inconsistent force units.
- where: contact.py:70
- scenario: A conformal contact with area 1e-4 m2 and lambda=100 N reports force_n ~1e6 (pressure) instead of 100 N; a mortar contact reports 100 N.
- fix: If lambda is force, use Rc.T without diag(1/area) for conformal force_pairs, matching mortar Rm.T.

## 15. tied-parts displaces the top face +0.05 mm (up, away from the lower block) while gap-blocks uses -0.1 mm; the tied/bonded interface is pulled in tension, so the resulting contact force sign/magnitude likely won't match the fixed reference.
- where: backend/app/templates.py:646
- scenario: Run 'tied-parts': top pulled +0.05 mm, bond carries tension; if reference contact_force assumes compression the 0.5% tolerance check fails or reports the wrong reaction.
- fix: Use a compressive displacement (e.g. -0.05 mm) or document/verify that a tensile bonded test matches the reference.

## 16. New error codes err.contact_pair_faces and err.contact_pair_same_face (plus new ENUM values 'buckling' and fatigue surfaces) have no ja/en/zh locale entries in this diff, so the UI shows raw keys.
- where: backend/novastudio/store.py:168
- scenario: User creates a contact pair referencing an unknown face -> raise StudioError('err.contact_pair_faces') -> frontend displays the literal key in all three languages.
- fix: Add err.contact_pair_faces, err.contact_pair_same_face and labels for the new enum values to all three locale catalogues.

## 17. The shared `own` dict assigns `x1` only to b1; in `gap_blocks` the x1 side face spans both blocks, so BCs on x1 miss b2.
- where: backend/novastudio/templates.py:120
- scenario: Create a gap_blocks case with a symmetry/convection BC on face 'x1' -> the upper block b2's x1 face is left unconstrained -> wrong/unbalanced results
- fix: Give gap_blocks and hertz separate body maps, and map 'x1' to ['b1','b2'] for gap_blocks (or drop it from the shared dict).

## 18. bool(b.get("apply")) coerces any non-empty string to True, so apply:"false"/"0" silently mutates the case by adding contact pairs.
- where: backend/novastudio/api.py:276
- scenario: POST detect-contacts with body {"apply":"false"} -> bool('false') is True -> bonded contact_pairs are written to the case.
- fix: Validate that apply is a real bool (e.g. `apply = b.get("apply")
if not isinstance(apply, bool): apply = False` or reject 400).

## 19. fatigue_life viewer only floors life at 1 but never caps it at fatigue_infinite, unlike the card (min(life_min, fatigue_infinite)); the code comment says lives past the cap should read the same.
- where: backend/novastudio/results.py:411
- scenario: Worker stores raw per-node life where infinite nodes carry values 1e8..1e20 -> log10 gives 8..20, so 'infinite' regions get different colours and the colour range is stretched, hiding low-life hotspots.
- fix: vals['fatigue_life'] = np.log10(np.clip(data['fatigue_life'][used], 1., m['fatigue_infinite']))

## 20. i18n mode crashes with FileNotFoundError if ja.json exists but en.json or zh.json is missing.
- where: tools/ds_review.py:147
- scenario: frontend/src/i18n/ja.json present, en.json accidentally deleted -> dict comprehension read_text raises, whole i18n review aborts with traceback.
- fix: Check all three files exist (or load each with exists() guard and use '(missing file)' for absent langs).

## 21. With -DeepSeekFirst, invoking 'python' aborts the whole script on machines lacking a python on PATH, so Codex never writes the report.
- where: tools/second_opinion.ps1:23
- scenario: Windows box where only 'py' exists -> -DeepSeekFirst -Since v0.3.0 throws CommandNotFoundException under $ErrorActionPreference='Stop' before the codex call.
- fix: Wrap the python call in try/catch (or check Get-Command python) and continue to Codex when it is unavailable.

## 22. new_case now copies both 'contacts' (stacked-blocks, friction-block) and 'contact_pairs' (gap-blocks, tied-parts, hertz); if the solver/pipeline was migrated to read only 'contact_pairs', the two older templates silently lose their contact definition.
- where: backend/app/templates.py:705
- scenario: Open/solve 'friction-block': its contact lives in 'contacts', solver reads 'contact_pairs' → no contact applied, wrong results.
- fix: Normalize all templates to a single contact representation, or confirm the solver consumes both keys.

## 23. gap-blocks/tied-parts set displacement boundary with 'ux':None,'uy':None; if the boundary schema/handler expects {value,unit} objects, this can throw or be treated as constrained rather than free.
- where: backend/app/templates.py:635
- scenario: Opening the boundary editor or validating the case dereferences ux.value on None → TypeError, or x/y get fixed unintentionally.
- fix: Omit unconstrained components or use an explicit free/omitted marker consistent with the schema.

## 24. Body lookup uses `if body`, so a falsy body key (integer index 0) silently uses the global solid preset/props instead of the body's, giving wrong Su/Se and safety factor and life.
- where: backend/novastudio/fatigue.py:33
- scenario: body_materials = {0:'aluminium', 1:'steel'}; material(case, 0) -> `if body` False -> returns the solid preset (e.g. steel) data for body 0.
- fix: Test `body is not None` in both the preset and body_props lookups (lines 33 and 35).

## 25. endurance is only False for preset 'aluminium', so copper (C1100, also without a true endurance limit per the module's own note) gets life reported as infinite above its 1e8-cycle strength.
- where: backend/novastudio/fatigue.py:40
- scenario: Copper part, sar just below ka*Se at 1e8 cycles, design life 1e9 -> life returned as INFINITE (1e10) although copper's S-N line keeps falling -> non-conservative pass.
- fix: Derive the endurance flag from the METALS data (endurance: False for aluminium and copper) instead of comparing the preset name.

## 26. fatigue_sf/fatigue_life arrays are not sanitised for NaN; NaN propagates into scalars/range and Starlette JSONResponse uses allow_nan=False, raising a 500.
- where: backend/novastudio/results.py:410
- scenario: Unloaded node yields fatigue_sf = 0/0 = NaN -> np.minimum(NaN,10)=NaN -> scalars/range contain NaN -> json.dumps(allow_nan=False) ValueError, whole viewer request fails.
- fix: Apply np.nan_to_num(..., nan=default, posinf=cap) to both arrays (or filter non-finite before emitting).

## 27. mortar_pairs records (keys face/closest_m/no_contact) are appended into m['_contact_pairs'], which elsewhere holds split_mesh records with master/slave/normal arrays, risking a format mismatch.
- where: backend/novastudio/run_worker.py:75
- scenario: A case with both non-bonded contacts and contact_pairs -> _contact_pairs contains mixed dict shapes -> the incremental contact solver reading r['master'] raises KeyError or models contact wrongly.
- fix: Keep the two pair lists separate or normalize mortar records to the split_mesh schema before appending.

## 28. Buckling sections read data['mode_shapes'] and treat the vectors as nodal displacements; if buckling results are stored under a different key/shape this raises KeyError -> HTTP 500.
- where: backend/novastudio/sections.py:24
- scenario: Section a buckling case whose results.npz lacks 'mode_shapes' (or stores it as (modes,nodes,3)) -> KeyError/IndexError -> 500.
- fix: Confirm buckling writes mode_shapes in the same (nodes,3) per-mode layout as modal, or guard the lookup.

## 29. Removing a contact pair via change(...,null) leaves a null entry that the render dereferences (c.slave/c.master), crashing the Boundaries step.
- where: frontend/src/components/StructuralSettings.tsx:153
- scenario: Click Remove on a detected pair -> contact_pairs.pair1 becomes null (if the store/backend keeps the key instead of deleting) -> Object.entries yields [pair1,null] -> c.slave[0] throws and BoundariesStep unmounts.
- fix: Filter null entries in the map or delete the key (dedicated delete API / omit from patch) instead of writing null.

## 30. Pair label button calls selectFace(c.slave[0]) without guarding an empty slave face list.
- where: frontend/src/components/StructuralSettings.tsx:149
- scenario: A pair whose slave list is empty (server-generated edge case) -> selectFace(undefined,'set') -> selection state contains undefined face key and no face highlights.
- fix: Guard: c.slave[0] && selectFace(c.slave[0],'set').
