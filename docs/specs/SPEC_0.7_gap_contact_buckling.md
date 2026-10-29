# SPEC: Studio 0.7, contact between separate surfaces, and linear buckling

Owner: Claude (spec and acceptance). Implementer: Codex if available, otherwise Claude. Branch `v0.7`, worktree
`..\studio_07`.

## Why

After 0.6 these are the two most common analyses a Fusion, SolidWorks or Discovery user still cannot run:

- **Parts that are close but do not share a face.** Separately modelled parts in an assembly, a gap that closes
  under load, or a part pressed onto a support. In 0.6, contact works only where the CAD fragmenter made a
  conformal shared face.
- **Buckling of slender or thin parts:** columns, struts, thin walls and brackets. A linear static result says
  "stress fine" while the part would buckle at a fraction of the load.

The Studio rule holds: each analysis ships with templates whose answer is known in closed form or exactly, plus
honest gates.

## 0. Ground rules

The ground rules of `SPEC_0.4_faces_undo.md` §0 apply, with branch `v0.7`. Old cases keep their behaviour.

Read first:
- `contact.py`: `split_mesh`, `Constraints`. Note the B matrix rows: a basis times the slave minus master
  displacement.
- `fem_nonlinear.solve`: the contact Newton loop and `limit_control`.
- `fem_tet10.py`: `structural_system`, `solve_modal`, `modal_constraints`, `DSHAPE`, `GAUSS`, `canonical_tets`.
- `run_worker.py`: `run_structural_builtin`, `run_modal`.
- `results.py`: modal cards and `modes`.
- `external.py`: CalculiX deck.
- `templates.py`, `checks.py`, `mesh_worker.py`: how bodies and interfaces are found.
- Frontend: `StructuralSettings.tsx`, the modal mode selector and animation in `ResultsTools.tsx` /
  `ViewerPane.tsx`.

## 1. Contact between separate surfaces (small sliding)

### 1.1 Case data
- `contact_pairs.<name>` = `{"master": [face keys], "slave": [face keys], "type": "frictionless" | "frictional" |
  "no-separation" | "bonded", "mu": 0.2, "search": {"value": 1, "unit": "mm"}}`.
  - `search` is the largest initial gap that is still treated as a potential contact.
  - It covers interfaces between bodies that are **not** fragmented together (no shared face), and also faces of
    one body (self-contact is out of scope: refuse it with a clear error).
- **Auto-detect** on import and on request (`detect_contacts` command and MCP tool): candidate pairs are faces of
  different bodies whose gap is ≤ `search` and whose normals face each other (n_a·n_b < −0.9 where they are
  close).
  - Suggest them as `contact_pairs` with type `bonded`, which is the CAD default and keeps old expectations.
  - The user or the AI changes the type. The GUI lists suggested pairs in the Boundaries step with the same
    controls as the 0.6 interface contacts.
- `bonded` here means **tied**: the slave is constrained to the master surface with the same equations,
  multipliers always active. This lets non-matching meshes of separate parts be glued.

### 1.2 Discretisation
- **Segment-to-segment mortar** on the slave surface (tri6), with a dual or standard Lagrange multiplier space.
  Node-to-segment is not accepted: it fails the contact patch test on non-matching meshes, and 0.6's promise is
  that the answer does not depend on a penalty factor or on the mesh pairing.
- Projection: once per load step, at the start of the step (small sliding). Each slave quadrature point is
  projected along the slave normal onto the master tri6 surface, giving master shape-function weights and an
  initial gap g0 (positive = open).
- The existing `Constraints` takes a generalised B: row i = basis_i · (Σ_s M_is u_s − Σ_m D_im u_m), with
  mortar matrices D (slave) and M (master). Reuse its semismooth active set, Coulomb return mapping and
  complementarity check unchanged. Replace the per-node Python loop in `equations` with vectorised NumPy:
  this release must not be slower than 0.6 on the 0.6 templates (measure).
- Master/slave choice: the finer side is the slave by default (the side with the smaller mean element edge).
  The user may override.
- A pair whose slave points do not project onto the master within `search` stays open, and is reported as
  "no contact found" with the closest distance. That is not a crash and not a silent zero.

### 1.3 Templates (each with a reference)
1. **`gap-blocks`**: two blocks with an initial gap g, meshed separately with different element sizes (a
   non-matching interface).
   - The top face is pushed down by a prescribed displacement d > g; the lateral faces are free; frictionless.
   - Exact: uniform stress σ = E·(d − g)/(L1 + L2). Reaction = σ·A.
   - Reference: the reaction, tolerance 0.5 %. The contact pressure must also be uniform: max/min within 1 %
     (the mortar patch test).
2. **`hertz-cylinder`**: a long cylinder on a flat block, plane-strain-like slab with symmetry, frictionless.
   - Hertz max pressure p0 = sqrt(P·E*/(π·R)) per unit length.
   - Reference p0, tolerance 5 %, with a refinement zone at the contact (state the mesh in the template).
   - Mesh study quantity: p0.
3. **`tied-parts`**: two separately meshed parts tied (bonded) across a non-matching interface, as a bar in
   tension. Exact uniform stress and tip displacement equal to one-piece bar theory. Tolerance 0.5 %.
- CalculiX: write `*CONTACT PAIR` / `*TIE` decks, so `final` mode can cross-check where ccx is installed.
  Compare in tests when ccx is on PATH.

### 1.4 Limits
- Small sliding only (projection fixed during a step). With large deformation, refuse as 0.6 does
  (`err.contact_large_deformation`).
- No self-contact, no edge-to-face or point contact. Document both.

## 2. Linear buckling (eigenvalue)

### 2.1 Case data and solver
- `physics.kind = "buckling"`, `physics.modes` (default 4). Loads and supports as in linear static.
- Solve the linear static problem for the applied load P0. Take the Gauss-point stress σ0.
- Assemble the geometric (initial-stress) stiffness: Kσ = Σ_e ∫ Gᵀ (σ0 ⊗ I3) G dV. G holds the shape-function
  gradients of tet10 at the existing 4 Gauss points, and σ0 is the 3×3 stress at that point.
- Eigenproblem (K + λ Kσ) φ = 0 on the free DOFs. Solve it as θ = 1/λ with `eigsh(-Kσ, M=K, which='LA')`,
  since K is positive definite after supports.
  - λ_i = 1/θ_i for θ_i > 0, sorted ascending.
  - A negative λ (the load would have to reverse) is listed separately and is not a "critical" load.
- Report:
  - load factors λ1…λn and critical loads λ_i·P0;
  - mode shapes, normalised to max |u| = 1;
  - a gate "converged": the eigen residual is below 1e-6 relative.
- Large models: reuse the modal path's AMG/LOBPCG pattern on (−Kσ, K). Use `check_memory` with a 'buckling'
  kind.
- Springs and symmetry rollers enter K as in modal. Thermal or prestress load cases are out of scope.

### 2.2 Templates
1. **`column-buckling`**: a fixed-free slender square column (L/h = 40), with an axial compressive tip load.
   - Euler P_cr = π²EI/(4L²).
   - Reference: λ1·P0, tolerance 2 %. Also check that the second mode (the other bending axis, a degenerate pair
     for a square section) is within 2 % of the first.
2. **`column-buckling-fixed`**: fixed at the bottom, guided at the top (lateral and rotation held through
   symmetry rollers or a constraint face, axial free), loaded axially.
   - P_cr = π²EI/L² (fixed-guided), tolerance 2 %.
3. **`plate-buckling`** (optional if time allows): a simply supported thin plate in uniaxial compression,
   k = 4. Tolerance 5 %.
- CalculiX `*BUCKLE` deck for `final`. Compare in tests when ccx is installed.

### 2.3 Results and UI
- Cards: critical load (the lead figure, compared with the reference), λ1 and the applied load. The mode table
  shows λ_i and P_cr,i.
- Reuse the modal mode selector and its animation in the viewer, labelled "buckling mode".
- Warnings:
  - λ1 < 1: the part buckles before the applied load. Say it plainly in the results strip.
  - Linear buckling overestimates real capacity for imperfection-sensitive shells. One line, shown for every
    buckling result.
- MCP: `physics.kind=buckling` through `update_case`. `get_results` returns the λ table, and `render_view` takes
  `mode=`.

## 3. Tests (new; the existing suite must pass)
1. Mortar patch test: the `gap-blocks` non-matching interface transmits uniform pressure to 1 %. The tied bar
   gives an exact displacement to 0.5 %.
2. Gap: before contact (d < g) the reaction is 0 and the status is open. After it, the reaction matches.
3. Hertz p0 within 5 %, and the contact half-width a = sqrt(4PR/(πE*)) within 10 %.
4. Auto-detect finds the gap-block pair and suggests nothing between far-apart bodies.
5. Contact performance: each 0.6 template runs no slower than in 0.6 (store the 0.6 times in the test as
   bounds, with a margin of 1.2×).
6. Buckling:
   - both Euler templates within 2 %;
   - λ scales as 1/P0 (doubling the load halves λ);
   - a tension-only load gives no positive λ and a clear message;
   - Kσ is symmetric;
   - for a uniform axial stress, Kσ matches a finite-difference check of the tangent of the nonlinear (TL)
     element at u = 0.
7. MCP round trip: create, run and read λ for column-buckling.
8. Frontend build, and the contact-pair list and buckling mode selector in JA/EN/ZH screenshots.

## 4. Report
Write `reviews/v0.7_report.md` with:
- the changes, file by file;
- the test results;
- the template results against their references;
- the timings, compared with 0.6;
- what was left out, and why.
