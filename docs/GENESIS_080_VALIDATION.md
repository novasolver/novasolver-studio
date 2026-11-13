# Genesis 0.8.0 validation status

Evidence reviewed: 2026-11-13. This is a limited qualification record for one specimen and selected UI checks.
**The release CI passed; the specimen is not strength-qualified.** The surface diagnostic records `qualified: false`; all six structural
solves record `ran: true`, `converged: true`, and `verified: false`.

## Raw and smoothed exports: six completed solves

The specimen is a 200 × 40 × 80 mm steel cantilever, optimised with a 35% target volume fraction. The actual raw
and smoothed STL exports were reimported and analysed using quadratic tetrahedral elements at three mesh settings.
The target volume fraction is an optimisation input, not a measurement of the final exported solid.

Support and load-region vertices were pinned during smoothing; comparison of the saved STL coordinates confirmed
that those vertices did not move. The reimported models used fixed supports at the retained support end and the
same total force of 1,000 N in the −z direction at the opposite end. Force was distributed by loaded-face area.
This preserves the resultant force; the surface areas, individual nodal loads and meshes are not identical.
The recorded support reactions balance the applied force in all six solves.

| Mesh setting | Export | Elements | Compliance (J) | Maximum displacement (mm) | Peak von Mises stress (MPa) |
| --- | --- | ---: | ---: | ---: | ---: |
| Coarse | Raw | 14,958 | 0.018728682 | 0.02149275 | 15.94416 |
| Coarse | Smoothed | 15,749 | 0.018656123 | 0.02136083 | 17.12151 |
| Normal | Raw | 31,181 | 0.018802258 | 0.02159661 | 17.38324 |
| Normal | Smoothed | 31,675 | 0.018715590 | 0.02143532 | 19.16447 |
| Fine | Raw | 61,676 | 0.018846117 | 0.02165680 | 19.88212 |
| Fine | Smoothed | 152,988 | 0.018802484 | 0.02154583 | 26.24857 |

Compliance is calculated as force dotted with displacement. Relative changes below use
`100 × (smoothed / raw − 1)`:

- Enclosed STL volume: **+0.087%** (recomputed from the saved exports; +0.087377% before rounding).
- Fine-mesh compliance: **−0.2315%**.
- Fine-mesh maximum displacement: **−0.5124%**.

These results show a small change in global response for this specimen. The fine meshes have different element
counts, so this is a comparison of the generated meshes, not an equal-resolution error estimate.
**Peak stress is not mesh-converged. These results are NOT proof of strength or safety.** Peaks occur at the
support in every solve and increase with refinement, particularly for the smoothed export. Solver convergence
does not establish mesh convergence or qualify arbitrary Genesis designs.

## Lamé reference probe and unresolved history

The recorded thick-cylinder pressure probe completed and showed excellent agreement with the analytical solution:

| Mid-wall stress | Computed (MPa) | Reference (MPa) | Relative error | Probe tolerance |
| --- | ---: | ---: | ---: | ---: |
| Hoop | 19.996122 | 19.993906 | 0.011081% | 1% |
| Axial | 9.756333 | 9.756098 | 0.002415% | 1% |

Both reference comparisons passed. However, the mesh-study Grid Convergence Index (GCI) was **3.145%**, with
`gci_pass: false` and `verified: false`. The diagnostic's probe-level `status: pass` does not mean the GCI gate
passed. The previously reported crash was not reproduced by this run; its cause remains unknown, and no crash
fix is established by this successful probe.

## UI and CI evidence boundaries

The recorded UI checks at widths of 1,440 and 1,280 pixels found no captured page errors or horizontal overflow.
Invalid minimum-member input was rejected, valid input was accepted, and both raw and smoothed STL download
endpoints returned content. These checks cover those controls and viewports only.

The final source is **`50fdf7554c69cca876d51b5cea2ffd2c2118df76`**. Its
[cross-platform CI](https://github.com/novasolver/novasolver-studio/actions/runs/43338311034)
passed on Windows, macOS and Linux. The associated accuracy artifact contains **37 passing reference cases**
for version 0.8.0 in **quick mode**; it is preserved in `validation/results/0.8.0.json`.
Quick-mode agreement does not establish every mesh-verification gate or arbitrary-design safety.
The Windows and Linux build workflows also passed, including their frozen-application smoke checks.
All 27 packaged examples solved and passed their recorded reference comparisons.

## STEP export unit regression: corrected and checked

After candidate `d2242b7`, the release maintainer reproduced a STEP export unit defect following an earlier SI-unit
import: exported geometry had a factor-of-1,000 linear-scale error even though Genesis's internal volume check
passed. An external SI readback regression failed before the correction. The maintainer reports applying an
explicit `Geometry.OCCTargetUnit = "MM"` setting in `genesis_step`. The completed combined post-fix run of
`test_genesis_review_1111.py`, `test_genesis.py`, and `test_step_names.py` recorded **53 passed in 433.38 seconds**,
as reported by the maintainer. This includes the external SI readback regression and STEP-name coverage.
A separate platform test run recorded **52 passed**. The final cross-platform CI and Windows/Linux rebuilds
subsequently passed on the source identified above. STEP unit correctness is covered by the external readback
regression, separately from the STL response comparison.

Evidence reviewed locally: `qualification.json`, `lame-before.json`, `ui-controls.json`, the downloaded accuracy
`ci.json`, the associated saved STL exports and pinning data, the diagnostic scripts and final CI records.
The PyPI 0.8.0 wheel was downloaded after publication: all 1,474 uncompressed files match the CI-tested wheel.
Personal paths and private
case/run identifiers are omitted.
No new solver or CI run was performed to prepare this summary.
