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
