# 0.7 review triage (since ebabd7f)

Independent Claude review (read-only, Codex unavailable until 2026-11-04). Every finding verified against the code.

| # | Finding | Outcome |
|---|---|---|
| H1 | Contact fields crash for mortar pairs: `field()` built the surface only from conformal `contact_*` arrays | **fixed**: `_mesh_for_run` saves `contact_master_/contact_slave_<pair>` for each contact_pairs entry; test `test_contact_fields_render_for_separate_surfaces` |
| H2 | `materials.solid.su/se` had no unit (MPa rejected, bare numbers read as Pa); editing any material value turned the preset to custom and dropped the fatigue data | **fixed**: default quantities in MPa; the original preset is kept as `base_preset` and used by `fatigue.material`; a new preset clears su/se/base_preset; test `test_strength_overrides_keep_the_metal` |
| M1 | Buckling P0 = resultant (0 for couples, pressure on closed shells); zero load gave lambda ~ 1e30 | **fixed**: P0 = sum of nodal force magnitudes (same value for column loads); no stress returns no load factor (err.buckling_none); test `test_zero_load_has_no_buckling` |
| M2 | Mortar quadrature memory: 144 points per slave element at once | **fixed**: slave elements processed in blocks of 500 (MORTAR_CHUNK), sparse sum per block |
| M3 | Fatigue silently missing for displacement/spring supports (incremental path) | **fixed**: `fatigue_scope` warning covers those roles |
| M4 | Manual "Mesh" column used the verified gate | **fixed**: suite records the GCI study's own pass flag (`gci_pass`), report uses it |
| L1 | Initial-gap seeding also changed conformal contact | **fixed**: mortar rows only |
| L2 | force_reference floor also loosened conformal cases | **fixed**: applied only when a mortar pair is present |
| L3 | Direct contact solve up to 120k could crash with MemoryError | **fixed**: MemoryError falls back to the iterative path |
| L4 | suite.py could run in the user's workspace | **fixed**: always a temporary workspace |
| L5 | Manual said contact/buckling/fatigue were not validated | **fixed**: wording now names the basic problems that check them; shells and explicit crash are out of scope |
| L6 | Fatigue card used the von Mises peak's support flag | **fixed**: `fatigue_on_support` from the location of the fatigue minimum |

DeepSeek first pass: see `2026-10-31_since-ebabd7f_to_HEAD.deepseek-reasoner.md` (triaged when it completes).

## DeepSeek first pass (deepseek-reasoner, 30 items; 4 of 8 requests cut off)

| # | Outcome |
|---|---|
| 1, 6 | **rejected (tool bug)**: the e-mail scrub in ds_review.py turned `+@mcp.tool` / `+@app.post` diff lines into an address. **fixed** the scrub (an address must start with a letter or digit) |
| 3 | **fixed**: detect_contacts coverage threshold relative to the smaller face |
| 17 | **fixed**: face owners per geometry kind (gap_blocks side faces belong to both blocks) |
| 18 | **fixed**: detect-contacts API applies only on `apply: true` |
| 25 | **fixed**: copper, like aluminium, has no endurance limit |
| 29 | **fixed**: the pair list skips a pair that is null while its removal is pending |
| 2, 4, 9, 10, 13, 14, 15, 16, 19, 22, 23, 24, 26, 27, 28, 30 | rejected: checked against the code; wrong file, wrong assumption, or already handled (e.g. DIVS is defined, the fatigue bar has roller supports so no singularity, the tied reference uses the magnitude, the keys exist in all three languages) |
| 5 | rejected: `gap_mm` in detect_contacts is a display value; interference is not a detection case |
| 7, 20, 21 | rejected: the path scrub works on real paths; tooling edge cases |
| 8 | noted: a rank-deficient contact block raises in the direct path as before 0.7 (same behaviour at <= 30k) |
| 11 | noted: R > 1 (compression-compression cycles) is out of scope; Goodman gives no credit to compressive means anyway |
| 12 | noted: the same isfinite pattern is used for every numeric path; a 400-digit integer from the API is not a realistic input |
