# SPEC — Studio 0.6: contact between parts, and nonlinear structural analysis

Owner: Claude (spec, acceptance). Implementer: Codex. Branch `v0.6` (git worktree `..\studio_06`).

**Why.** After 0.5 the two things a SolidWorks/Fusion/Discovery user still cannot do in Studio are:

- assemblies whose parts touch but are not glued: a shaft in a bore, a press fit, stacked plates, a bolted flange;
- anything past the linear range: large deflection of thin parts (springs, clips, 3D-printed snap fits) and
  yielding metal.

The operator asked for both, regardless of effort. Studio's rule stays: **every new analysis ships with a template
whose answer is known in closed form (or is an exact homogeneous solution), a mesh-study quantity, and honest
gates.** A nonlinear answer is only "verified" when the template matches its reference.

(CAD face names are done separately by Claude on main; do not work on them.)

## 0. Ground rules

Same as `SPEC_0.4_faces_undo.md` §0 (worktree only, match the code, i18n ja/en/zh with identical keys, studio-ui
skill for visuals, no new runtime dependencies, old cases keep opening, full suite plus the new tests pass,
`npm run build` passes, the commit and test-environment rules), with branch `v0.6`.

Files to read first: `fem_tet10.py` (`structural_system`, `solve`, `solve_modal`, `check_memory`, `_amg_cg`),
`run_worker.py` (`structural_loads`, `symmetry_rollers`, `run_structural_builtin`), `structural.py`
(`face_load`, `reference`, `comparison`), `templates.py` (`element_prop`, body groups), `mesh_worker.py`
(`fragment`, `face_info["bodies"]`, `face_info["interface"]`), `external.py` (CalculiX deck), `checks.py`,
`commands.py`, `mcp_server.py`, `exports.py`, `results.py`, and the frontend `StructuralSettings.tsx`,
`PropertiesPanel.tsx`, `ResultsTools.tsx`, `store.ts`.

## 1. Contact between bodies

Multi-body CAD imports are fragmented, so two touching bodies share a conformal interface face (`interface: true`,
`bodies: [bA, bB]`) and today share its nodes: they are glued. 0.6 makes the behaviour of every interface a choice.

### 1.1 Case data
- `contacts.<face>` for an interface face: `{"type": "bonded" | "frictionless" | "frictional" | "no-separation",
  "mu": 0.2, "offset": {"value": 0, "unit": "mm"}}`. Absent = `bonded` (old cases and behaviour unchanged).
- `offset` > 0 is an **interference** (the bodies overlap by that much along the normal; press fit, shrink fit);
  < 0 is an initial gap that must close before force is transmitted. Both only for the non-bonded types.
- Undo/history, `update_case` and the readiness check cover `contacts` like `boundaries`.

### 1.2 Mesh
- Bonded interfaces keep shared nodes. For every non-bonded interface, **duplicate its nodes** for the second body
  (the body with the larger tag), re-pointing that body's tets and face triangles, so that the mesh has coincident
  node pairs (slave node, master node). Keep a `contact_pairs` record per face: node pairs and the area-weighted
  normal (outward from body A) and the tributary area of each pair from the tri6 surface rule (corner and midside
  weights of the quadratic triangle, not 1/6 each: the corner weight of a tri6 is 0, use the consistent nodal
  areas ∫N_i dA, which for tri6 are 0 at corners and A/3 at midsides — handle this with a lumped scheme that gives
  every node positive area, e.g. the area of its dual region on the 4-way subdivided triangle, and test it).
- Do this as a post-step on the loaded mesh (in the run, not in gmsh), cached per mesh key and contact set, so that
  switching an interface between bonded and contact does not need a remesh.
- Separate bodies with a small gap (not fragmented together, no shared face) are out of scope for this release:
  the GUI says "touching faces only; parts must share a face after import".

### 1.3 Solver
- Node-to-node contact on the coincident pairs, normal gap g = (u_s − u_m)·n + g0 with g0 = −offset.
- **Normal:** augmented Lagrangian / semi-smooth Newton active set (no pure penalty: the answer must not depend on a
  penalty factor). Contact pressure p ≥ 0, g ≥ 0, p·g = 0, checked to tolerance at the end.
- **Frictional:** Coulomb, |t| ≤ μ p, stick/slip by return mapping in the same Newton loop.
  **No-separation:** normal bilateral, tangential free. **Frictionless:** tangential free.
- The tangent system reuses the assembled K. Augment it with the pair constraints by a sparse coupling matrix (or a
  penalty-regularised augmented Lagrangian with Uzawa updates that converges to the exact constraint). Use the direct
  solver up to `DIRECT_LIMIT` and AMG-CG beyond, as `solve` does.
- A model that is held only through frictionless contact is a mechanism: detect a singular / non-converging solve and
  report `err.contact_unstable` naming the body that is not held, instead of returning garbage.
- **Results:** contact pressure per face node (a nodal field `p_contact` on interface faces), gap and slip, the
  contact status (open / stick / slip) per pair, the transmitted force per interface, and in metrics the Newton
  iteration count, the final complementarity residual and the force balance.
- **Gates:** converged = Newton converged, complementarity residual < 1e-6 (relative to the max pressure × area),
  force imbalance < 5e-3 as in static.

## 2. Nonlinear structural analysis

### 2.1 Case data
- `physics.analysis = "nonlinear"` (alongside `static`, `modal`); contact alone does **not** require it (contact is
  solved by its own Newton loop in a static analysis).
- `physics.nonlinear = {"large_deformation": true, "steps": "auto" | n, "max_iterations": 25}`.
- Material model per material and per body (`body_props.<b>`):
  - `model: "linear"` (default)
  - `model: "elastoplastic"`: J2 (von Mises) plasticity with isotropic linear hardening, using `sy` (already in the
    presets) and `H` (tangent modulus after yield, Pa; default E/100; 0 allowed = perfectly plastic). Small-strain
    radial return when `large_deformation` is off; with it on, use a hyperelastic-based finite-strain J2
    (multiplicative, logarithmic strain) or, if that is too much, refuse the combination clearly — state which in the
    report.
  - `model: "neo-hookean"`: compressible neo-Hookean (μ, κ from E, ν) for rubber, TPU, silicone. Requires large
    deformation. Presets: `rubber` (E 5 MPa, ν 0.49), `tpu` (E 26 MPa, ν 0.45), `silicone` (E 1.5 MPa, ν 0.49).
    ν close to 0.5 locks tet10 elements: use a mixed / F-bar or selective treatment that keeps the uniaxial
    template within 2 %, and warn for ν > 0.495.

### 2.2 Solver
- Total Lagrangian, tet10, the same Gauss rule; Newton–Raphson with consistent tangent; load stepping with automatic
  cut-back (halve the increment on divergence, up to 8 times; then stop with `err.nonlinear_diverged` naming the load
  fraction reached, and keep the last converged step as results).
- Loads are dead loads (fixed direction and magnitude) except `pressure`, which follows the deformed face
  (follower load) when `large_deformation` is on; say so in the docs and the GUI help.
- Thermal strain, gravity, rotation, moment, bearing and remote-force loads combine as in static (dead loads).
- Convergence: relative residual < 1e-6 and relative displacement increment < 1e-8, per step.
- Progress reports per step ("step 3/10, iteration 4"), through the existing progress callback, so the GUI and MCP
  show it.
- Memory: extend `check_memory` (tangent matrices are rebuilt, not accumulated).
- Contact and nonlinear combine (one Newton loop).
- **Results:** displacement, Cauchy stress and von Mises in the deformed configuration, equivalent plastic strain
  (`peeq`) for elastoplastic, the load–displacement curve (load fraction vs max displacement and vs the displacement
  of a chosen face) per step, and the deformed shape at true scale ×1 by default (large deformation is the point).
  Results of every converged step are kept so the GUI can scrub through steps.

### 2.3 Readiness checks (`checks.py`)
- Linear static result with max strain > 1 % or rotation > ~5° → info "consider large deformation"; peak von Mises
  above `sy` away from supports → the existing yield warning gains "run it as nonlinear (elastoplastic)".
- neo-Hookean without large deformation → error. Elastoplastic without `sy` → error.

## 3. Templates (each with a reference, a tolerance, and a study quantity)

| id | What | Reference | Tolerance |
|---|---|---|---|
| `press-fit` | Steel ring (bore 2b = 40 mm, outer 2c = 80 mm, length 20 mm) on a solid steel shaft (2b = 40 mm), radial interference δ = 0.02 mm (`offset`), frictionless; quarter model, symmetry planes | Lamé: contact pressure p = E δ / b · (c² − b²) / (2 c²) (same material, solid shaft; 78.75 MPa for E = 210 GPa, compute it from the preset E); ring bore hoop stress σθ = p (c² + b²)/(c² − b²) | 2 % |
| `stacked-blocks` | Two 20 mm cubes, frictionless contact, bottom fixed, 10 MPa pressure on top; then the same pulling (−10 MPa) | Compression: uniform σ = −10 MPa through both, contact force = p·A. Tension: the contact opens, top block reported as not held (`err.contact_unstable`) — the test, not a card | 0.5 % / error |
| `friction-block` | Block pressed on a fixed base with pressure p, shear traction τ on its side through a soft spring support so that the case is stable | τ < μp: all pairs stick, transmitted shear = τA. τ > μp: all slip, transmitted shear = μ p A | 1 % |
| `large-cantilever` | Steel strip 200 × 20 × 2 mm, one end fixed, tip force with PL²/EI = 1, large deformation on | Elastica (Bisshopp & Drucker): tip vertical deflection δ/L = 0.3017, horizontal 0.0566 (and the linear answer 1/3 shown for contrast) | 2 % |
| `plastic-bar` | Steel bar 100 × 10 × 10 mm, rollers on one end, imposed axial displacement to ε = 1 % then back to 0 (two load cases or a displacement-controlled step list), σy = 250 MPa, H = E/100 | Bilinear: σ at 1 % = σy + H(ε − σy/E); residual plastic strain after unloading = ε − σ/E | 1 % |
| `plastic-beam-collapse` | Steel cantilever 200 × 10 × 20 mm (h = 20), perfectly plastic (H = 0), tip load increased by load stepping | Collapse load P = Mp / L = σy b h² / (4L) (shear neglected); the solver reaches ≥ 95 % and diverges before 105 %; report the last converged load as the limit | 3 % |
| `rubber-tension` | neo-Hookean block 10 × 10 × 50 mm, ν = 0.45, stretched to λ = 2 by imposed displacement, lateral faces free | Exact homogeneous solution of compressible neo-Hookean uniaxial tension (solve the lateral stretch from zero lateral stress; write it in `structural.py`) | 2 % |

- Imposed displacement needs a new role: `displacement` on a face (vector in mm, any of x/y/z components set;
  unset components free). It is also generally useful (a clip pushed in by 2 mm). Add it to the GUI and MCP like the
  other roles. It is allowed in linear static too.
- All references must state their assumptions on the card ("Lamé thick cylinders, plane stress", "Euler elastica,
  inextensible", "bilinear hardening, uniaxial").

## 4. GUI

- **Contacts step.** In the boundaries step of a multi-body case, a "Contacts" section listing each interface face
  ("b1 ↔ b2 · face name", area) with its type, μ and offset. Selecting it highlights the interface in the viewer.
  Bulk-set selected interfaces. The face list shows a contact badge on interface faces.
- **Analysis selector**: Static / Modal / Nonlinear. Nonlinear shows: large deformation toggle, steps (auto/n),
  and per-material model with σy, H (or the neo-Hookean preset values).
- **Results:** a step slider (and play) for nonlinear runs; the load–displacement chart in the existing chart panel
  with CSV download; `p_contact`, contact status and `peeq` in the field picker; open contact gaps visible in the
  deformed view.
- Follow the studio-ui skill. Screens to check in the verification loop: contacts list on `press-fit`, results of
  `press-fit` (contact pressure), `large-cantilever` mid-step, `plastic-beam-collapse` load–displacement chart.

## 5. MCP, commands, export, report

- `update_case` documents `contacts.<face>.*`, `physics.analysis = "nonlinear"`, `physics.nonlinear.*`,
  `body_props.<b>.model/sy/H`, and the `displacement` role.
- `get_geometry` / `get_case` list interfaces with their contact settings; `render_view(quantity="faces")` shows
  interfaces in their own colour; `render_view` takes `step=` for nonlinear results and `quantity="p_contact"`,
  `"peeq"`.
- `get_results` gives the load–displacement table and, for contact, per-interface force and status counts.
- Keep the MCP tool count at 24 unless a new tool is clearly needed; if one is added, update the assertions and
  `make_mcpb.py` reads the list from the exe anyway.
- `export_results`: VTU with every step as a separate file plus a `.pvd` collection; CSV of the
  load–displacement curve; the report gains the contacts table, the material models and the curve picture.

## 6. CalculiX final run

- Contact: `*CONTACT PAIR` (node-to-surface or surface-to-surface, `TYPE=SURFACE TO SURFACE`), `*SURFACE INTERACTION`
  with `*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD` (or linear with a stiffness stated in the deck), `*FRICTION`;
  interference via the clearance/adjust options. Nonlinear: `*STEP, NLGEOM, INC=...`, `*PLASTIC` table from σy and H,
  `*HYPERELASTIC, NEO HOOKE`.
- If a combination is not supported by our deck writer, the final run refuses with a clear message (never runs a
  different model silently).
- Tests compare CalculiX with the built-in solver for `press-fit` and `large-cantilever` when CalculiX is present
  (skip otherwise), within 3 %.

## 7. Tests (`backend/tests/test_v06.py`; each must fail if the feature is broken)

1. Node duplication: a two-body import with a frictionless interface has the right number of extra nodes; the bonded
   case is unchanged (same node count and same answer as 0.5 to 1e-10). Tributary areas sum to the face area to 1e-10
   and are all positive.
2. `press-fit` p and σθ within 2 %; complementarity residual < 1e-6; the answer does not change by more than 0.1 %
   when the augmented-Lagrangian parameter is ×10 or ×0.1.
3. `stacked-blocks` compression within 0.5 %; tension raises `err.contact_unstable`.
4. `friction-block` stick and slip cases within 1 %.
5. `large-cantilever` within 2 %, and the linear result of the same case differs from the nonlinear one by > 5 %
   (proves large deformation is active). Newton converges quadratically near the solution (the residual ratio over
   the last two iterations shows it).
6. `plastic-bar` stress at 1 % and residual strain within 1 %; `plastic-beam-collapse` limit load within 3 %.
7. `rubber-tension` within 2 %.
8. Combined: `press-fit` with thermal load on the ring (shrink fit by heating, offset 0) gives the same pressure as
   the interference case with δ = α ΔT b, within 3 %.
9. Divergence: an over-loaded perfectly plastic case stops with `err.nonlinear_diverged`, keeps the last converged
   step, and its gates say not converged.
10. Old cases (0.5 fixtures) open and solve identically; `contacts` absent = bonded.
11. Every new template appears in `list_templates` in three languages and its verification card passes on the
    default preview mesh (mark the slow ones so the suite stays under twice its current time).
12. MCP: `update_case` with `contacts` and `physics.nonlinear` round-trips; undo restores the previous contacts.

## 8. Report back

`reviews/v0.6_codex_report.md`: what was done per section, test counts and time, what is not done, guesses, commits.
